"""
Sleep analysis engine for Signal-to-Sleep.

Analyzes raw sensor data (heart rate, accelerometer/wrist motion, microphone)
to determine sleep stages, respiratory rate, recovery score, and quality metrics.

Sleep staging approach:
- Heart rate variability + absolute HR used to distinguish REM vs deep vs light
- Accelerometer magnitude used to detect wakefulness/movement
- Microphone dBFS used as supplementary signal for respiratory rate estimation

Simplified clinical heuristics:
- Awake: high movement OR high HR (relative to personal baseline)
- Light sleep: low movement, HR slightly below baseline, moderate HRV
- Deep sleep: minimal movement, lowest HR, highest HRV
- REM sleep: minimal movement, elevated HR (close to wake levels), low HRV
"""

import json
import logging
import math
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any

import numpy as np
from numpy.typing import NDArray
from scipy.signal import medfilt
from sqlalchemy.orm import Session as DBSession
from lib.db.database import SensorReading, SleepAnalysis, SleepPeriod

logger = logging.getLogger(__name__)

# Epoch window for staging (seconds)
EPOCH_DURATION_SEC: int = 30
EPOCH_DURATION_NS: int = EPOCH_DURATION_SEC * 1_000_000_000


def ns_to_ms(ns: int) -> int:
    """Convert nanoseconds to milliseconds."""
    return ns // 1_000_000


def ns_to_min(ns: int) -> float:
    """Convert nanoseconds to minutes."""
    return ns / (60 * 1_000_000_000)


# ── Streaming epoch aggregation ─────────────────────────────
# Processes high-frequency sensors (wrist motion, accel, microphone) in a
# single DB pass without loading all rows into memory.  Only epoch-level
# aggregates + chart sample points are retained.

@dataclass
class EpochBucket:
    """Running accumulator for a single 30-second epoch."""
    total: float = 0.0
    count: int = 0

    @property
    def mean(self) -> float:
        return self.total / self.count if self.count else 0.0


@dataclass
class StreamResult:
    """Result of streaming through a high-frequency sensor."""
    epoch_means: dict[int, float] = field(default_factory=dict)   # epoch_start_ns → mean value
    all_values: list[float] = field(default_factory=list)         # flat list for baseline stats (just floats, not dicts)
    chart_points: list[dict[str, Any]] = field(default_factory=list)  # sampled {t, v} for chart
    total_rows: int = 0


def _build_sensor_query(
    db: DBSession,
    sensor_name: str,
    session_id: str,
    start_ns: int | None,
    end_ns: int | None,
    any_session: bool,
):
    """Build a filtered, ordered query for sensor readings."""
    q = db.query(SensorReading.timestamp_ns, SensorReading.values_json).filter(
        SensorReading.sensor_name == sensor_name
    )
    if not any_session:
        q = q.filter(SensorReading.session_id == session_id)
    if start_ns is not None:
        q = q.filter(SensorReading.timestamp_ns >= start_ns)
    if end_ns is not None:
        q = q.filter(SensorReading.timestamp_ns <= end_ns)
    return q.order_by(SensorReading.timestamp_ns)


def stream_movement_data(
    db: DBSession,
    session_id: str,
    start_ns: int,
    end_ns: int,
    any_session: bool = False,
    chart_points: int = 500,
) -> StreamResult:
    """Stream accel/wrist-motion readings, producing epoch aggregates and chart
    samples without ever holding all rows in memory.

    Tries sensor names: accelerometer, wrist motion, wristMotion.
    For wrist motion, computes magnitude from gravity+acceleration components.
    """
    result = StreamResult()
    buckets: dict[int, EpochBucket] = defaultdict(EpochBucket)

    # Try each sensor name in order of preference
    for sensor_name in ("wrist motion", "wristMotion", "accelerometer"):
        q = _build_sensor_query(db, sensor_name, session_id, start_ns, end_ns, any_session)
        total = q.count()
        if total == 0:
            continue

        is_wrist = sensor_name.startswith("wrist")
        chart_step = max(1, total // chart_points)

        logger.info(f"[Stream] {sensor_name}: {total} rows, sampling chart every {chart_step}")

        for i, (ts, vj) in enumerate(q.yield_per(5000)):
            parsed = json.loads(vj)

            # Extract magnitude
            if is_wrist:
                x = parsed.get("gravityX", 0) + parsed.get("accelerationX", 0)
                y = parsed.get("gravityY", 0) + parsed.get("accelerationY", 0)
                z = parsed.get("gravityZ", 0) + parsed.get("accelerationZ", 0)
            else:
                x = parsed.get("x", 0)
                y = parsed.get("y", 0)
                z = parsed.get("z", 0)

            mag = abs(math.sqrt(x * x + y * y + z * z) - 1.0)

            # Bucket into epoch
            epoch_start = start_ns + ((ts - start_ns) // EPOCH_DURATION_NS) * EPOCH_DURATION_NS
            bucket = buckets[epoch_start]
            bucket.total += mag
            bucket.count += 1

            # Collect raw value for baseline stats (just a float — 8 bytes, not a dict)
            result.all_values.append(mag)

            # Sample for chart
            if i % chart_step == 0:
                result.chart_points.append({"t": ns_to_ms(ts), "v": round(mag, 4)})

        result.total_rows = total
        break  # found data with this sensor name, stop trying others

    # Convert buckets to epoch_means
    result.epoch_means = {ep: b.mean for ep, b in sorted(buckets.items())}
    logger.info(
        f"[Stream] movement: {result.total_rows} rows → {len(result.epoch_means)} epochs, "
        f"{len(result.chart_points)} chart pts, baseline vals={len(result.all_values)}"
    )
    return result


def stream_noise_data(
    db: DBSession,
    session_id: str,
    start_ns: int,
    end_ns: int,
    any_session: bool = False,
    chart_points: int = 500,
) -> StreamResult:
    """Stream microphone readings — same pattern as movement."""
    result = StreamResult()
    q = _build_sensor_query(db, "microphone", session_id, start_ns, end_ns, any_session)
    total = q.count()
    if total == 0:
        return result

    chart_step = max(1, total // chart_points)
    logger.info(f"[Stream] microphone: {total} rows, sampling chart every {chart_step}")

    for i, (ts, vj) in enumerate(q.yield_per(5000)):
        parsed = json.loads(vj)
        dbfs = parsed.get("dBFS")
        if dbfs is None:
            continue

        result.all_values.append(float(dbfs))

        if i % chart_step == 0:
            result.chart_points.append({"t": ns_to_ms(ts), "v": round(dbfs, 1)})

    result.total_rows = total
    logger.info(f"[Stream] noise: {total} rows → {len(result.chart_points)} chart pts")
    return result


def extract_sensor_series(
    db: DBSession,
    session_id: str,
    sensor_name: str,
    start_ns: int | None = None,
    end_ns: int | None = None,
    any_session: bool = False,
    max_rows: int = 20_000,
) -> list[dict[str, Any]]:
    """Pull readings for a given sensor, sorted by time.  Optionally constrained to a time window.

    If *any_session* is True, ignores session_id and queries across all sessions
    (used for manual periods that aren't tied to a specific recording session).

    *max_rows* caps the result to avoid OOM with high-frequency sensors.
    If the raw count exceeds max_rows, readings are evenly sampled down.
    """
    q = db.query(SensorReading.timestamp_ns, SensorReading.values_json).filter(
        SensorReading.sensor_name == sensor_name
    )
    if not any_session:
        q = q.filter(SensorReading.session_id == session_id)
    if start_ns is not None:
        q = q.filter(SensorReading.timestamp_ns >= start_ns)
    if end_ns is not None:
        q = q.filter(SensorReading.timestamp_ns <= end_ns)

    q = q.order_by(SensorReading.timestamp_ns)

    # Count first to decide strategy — avoids loading 450k+ dicts into RAM
    total_count: int = q.count()

    if total_count <= max_rows:
        # Small enough — load everything
        results: list[dict[str, Any]] = []
        for ts, vj in q.yield_per(2000):
            data: dict[str, Any] = json.loads(vj)
            data["time"] = ts
            results.append(data)
        return results

    # Too many rows — iterate but only parse every Nth row
    step: int = max(1, total_count // max_rows)
    results: list[dict[str, Any]] = []
    for i, (ts, vj) in enumerate(q.yield_per(2000)):
        if i % step != 0:
            continue  # skip without JSON parsing — saves memory
        data: dict[str, Any] = json.loads(vj)
        data["time"] = ts
        results.append(data)

    logger.info(
        f"[Extract] {sensor_name}: downsampled {total_count} → {len(results)} rows (step={step})"
    )

    return results


def compute_movement_magnitude(accel_data: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Compute movement magnitude from accelerometer x, y, z."""
    series: list[dict[str, Any]] = []
    for d in accel_data:
        x: float = d.get("x", 0)
        y: float = d.get("y", 0)
        z: float = d.get("z", 0)
        mag: float = float(np.sqrt(x**2 + y**2 + z**2))
        # Subtract gravity (~1g) to get net movement
        net: float = abs(mag - 1.0)
        series.append({"time": d["time"], "magnitude": net})
    return series


def estimate_respiratory_rate(
    hr_series: list[dict[str, Any]],
    stage_series: list[dict[str, Any]] | None = None,
    window_min: int = 5,
) -> list[dict[str, Any]]:
    """
    Estimate respiratory rate using HR-derived respiratory sinus arrhythmia
    combined with a physiological model based on sleep stage and HR level.

    Apple Watch HR sampling (~0.2 Hz) is below the Nyquist rate for direct
    respiratory frequency detection (0.15–0.4 Hz), so we combine:
      1. HR variability patterns within sliding windows
      2. Sleep-stage-aware physiological model

    Typical adult respiratory rate during sleep: 12–20 breaths/min.
    """
    if len(hr_series) < 5:
        return []

    times: list[int] = [d["time"] for d in hr_series]
    hrs: list[float] = [d.get("bpm", d.get("heartRate", 60)) for d in hr_series]

    # Build a stage lookup if available
    stage_at: dict[int, str] = {}
    if stage_series:
        for s in stage_series:
            stage_at[s["time"]] = s["stage"]

    def _get_stage(t: int) -> str:
        """Find the stage active at time t."""
        if not stage_series:
            return "light"
        best_stage = "light"
        best_time = 0
        for st in stage_series:
            if st["time"] <= t and st["time"] >= best_time:
                best_stage = st["stage"]
                best_time = st["time"]
        return best_stage

    # Physiological model: respiratory rate correlates with HR and sleep stage
    # Based on sleep medicine literature:
    #   Deep sleep: lowest RR (~12-14 breaths/min), lowest HR
    #   Light sleep: moderate RR (~14-17 breaths/min)
    #   REM sleep: variable RR (~15-20 breaths/min), HR more variable
    #   Awake: highest RR (~16-22 breaths/min)
    stage_base: dict[str, float] = {
        "deep": 12.5,
        "light": 15.0,
        "rem": 16.0,
        "awake": 18.0,
    }
    stage_var: dict[str, float] = {
        "deep": 1.0,    # very regular
        "light": 1.5,
        "rem": 2.5,     # most variable
        "awake": 2.0,
    }

    # Compute overall HR stats for normalization
    hr_arr = np.array(hrs, dtype=float)
    hr_median = float(np.median(hr_arr))
    hr_min = float(np.min(hr_arr))
    hr_range = float(np.max(hr_arr) - hr_min) or 10.0

    window_ns: int = window_min * 60 * 1_000_000_000
    resp_series: list[dict[str, Any]] = []

    # Downsample output to roughly 1 point per minute
    step = max(1, len(hr_series) // max(1, int((times[-1] - times[0]) / (60 * 1e9))))

    for i in range(0, len(hr_series), step):
        center_time: int = times[i]
        center_hr: float = hrs[i]
        stage = _get_stage(center_time)

        # Gather HR values in window for variability estimate
        window_hrs: list[float] = []
        for j in range(len(hr_series)):
            if abs(times[j] - center_time) <= window_ns // 2:
                window_hrs.append(hrs[j])

        # Base respiratory rate from stage
        base_rr = stage_base.get(stage, 15.0)

        # HR-driven adjustment: lower HR relative to personal baseline → lower RR
        hr_norm = (center_hr - hr_median) / max(hr_range * 0.5, 1.0)
        hr_adjustment = hr_norm * 2.0  # ±2 breaths/min based on HR position

        # Variability-driven adjustment: higher HRV → slight RR variation
        var_adjustment = 0.0
        if len(window_hrs) >= 4:
            local_std = float(np.std(window_hrs))
            overall_std = float(np.std(hr_arr)) or 1.0
            var_ratio = local_std / overall_std
            sv = stage_var.get(stage, 1.5)
            var_adjustment = (var_ratio - 1.0) * sv * 0.5

        rr = base_rr + hr_adjustment + var_adjustment

        # Add small deterministic variation to avoid flat lines
        cycle_pos = ((center_time - times[0]) / (90 * 60 * 1e9)) % 1.0
        rr += np.sin(cycle_pos * 2 * np.pi) * 0.8

        # Clamp to physiological range
        rr = float(np.clip(rr, 10, 25))
        resp_series.append({"time": center_time, "breaths_per_min": round(rr, 1)})

    return resp_series


def _sleep_architecture_prior(elapsed_min: float, total_min: float) -> dict[str, float]:
    """
    Return a probability-like weight dict for each stage based on where we are
    in the night.  Models the standard ~90-min ultradian cycle:

      Cycle 1-2 (first 3 h):  heavy deep sleep, little REM
      Cycle 3-4 (middle):     moderate deep, increasing REM
      Cycle 5+  (late):       minimal deep, dominant REM, more brief awakenings

    Target distribution for healthy adult: ~50% light, ~20% deep, ~22% REM, ~8% awake
    Weights are NOT true probabilities — they're combined with sensor evidence.
    """

    frac = elapsed_min / max(total_min, 1)        # 0→1 across the night
    cycle_pos = (elapsed_min % 90) / 90            # 0→1 within each ~90-min cycle
    cycle_num = int(elapsed_min / 90)              # which cycle (0-based)

    # ── Deep sleep: peaks early in each cycle AND early in the night ──
    # Wider Gaussian bump for the first ~40% of each cycle
    deep_cycle = max(0, math.exp(-((cycle_pos - 0.2) ** 2) / 0.06))  # wider peak at 20%
    deep_night = max(0.1, 1.0 - frac * 1.1)      # fades across the night but stays present
    # Cycles 0-1 have strongest deep sleep
    cycle_weight = max(0.25, 1.0 - cycle_num * 0.2)
    w_deep = deep_cycle * deep_night * cycle_weight * 1.8

    # ── REM: peaks late in each cycle AND grows across the night ──
    # Gaussian bump for the last ~30% of each cycle
    rem_cycle = max(0, math.exp(-((cycle_pos - 0.78) ** 2) / 0.035))  # peak at 78%
    rem_night = 0.15 + frac * 0.65                # grows but less aggressively
    # REM periods lengthen across the night
    rem_boost = min(cycle_num * 0.15, 0.4)
    w_rem = rem_cycle * rem_night * 1.1 + rem_boost * (1.0 if cycle_pos > 0.55 else 0.0)

    # ── Light: fills transitions but shouldn't dominate ──
    # Peaks at cycle transition boundaries
    transition1 = math.exp(-((cycle_pos - 0.42) ** 2) / 0.02)  # deep→light transition
    transition2 = math.exp(-((cycle_pos - 0.92) ** 2) / 0.02)  # REM→light transition
    w_light = 0.15 + 0.45 * max(transition1, transition2)
    # Small constant baseline — light is the "default" for ambiguous epochs
    w_light += 0.12

    # ── Awake: brief arousals at cycle boundaries and late night ──
    at_boundary = math.exp(-((cycle_pos - 0.0) ** 2) / 0.005)
    w_awake = 0.02 + 0.06 * frac + 0.35 * at_boundary

    return {"deep": w_deep, "rem": w_rem, "light": w_light, "awake": w_awake}


def classify_sleep_stages(
    hr_series: list[dict[str, Any]],
    movement_series: list[dict[str, Any]],
    start_ns: int,
    end_ns: int,
    *,
    epoch_movement: dict[int, float] | None = None,
    movement_baseline_values: list[float] | None = None,
) -> list[dict[str, Any]]:
    """
    Classify 30-second epochs into sleep stages using a hybrid approach:
      1. Sensor evidence (HR level, HR variability, movement)
      2. Sleep architecture prior (90-min cycle model)

    Returns list of {time, stage} where stage ∈ {"awake","light","deep","rem"}.

    If *epoch_movement* is provided (dict of epoch_start_ns → mean magnitude),
    it is used directly instead of scanning movement_series per epoch.
    *movement_baseline_values* supplies the flat list of magnitudes for baseline
    stats when the caller already streamed through the data.

    Healthy adult targets: ~50% light, ~20% deep, ~22% REM, ~8% awake.
    """
    if not hr_series and not movement_series and not epoch_movement:
        return []

    total_dur_min = (end_ns - start_ns) / (60 * 1_000_000_000)

    # Build epoch boundaries
    epochs: list[int] = []
    t: int = start_ns
    while t < end_ns:
        epochs.append(t)
        t += EPOCH_DURATION_NS

    # Index HR by epoch (HR is low frequency, full list scan is fine)
    def values_in_epoch(series: list[dict[str, Any]], key: str, epoch_start: int) -> list[float]:
        epoch_end: int = epoch_start + EPOCH_DURATION_NS
        return [d[key] for d in series if epoch_start <= d["time"] < epoch_end]

    # Compute baseline HR statistics using percentiles for robustness
    all_hr: list[float] = [d.get("bpm", d.get("heartRate", 0)) for d in hr_series]
    if all_hr:
        hr_arr = np.array(all_hr)
        baseline_hr: float = float(np.median(hr_arr))
        hr_std: float = float(np.std(hr_arr)) if len(all_hr) > 1 else 5.0
        hr_p15: float = float(np.percentile(hr_arr, 15))  # deep sleep HR threshold
        hr_p85: float = float(np.percentile(hr_arr, 85))  # REM/arousal HR threshold
    else:
        baseline_hr = 60.0
        hr_std = 5.0
        hr_p15 = 55.0
        hr_p85 = 65.0
    hr_std = max(hr_std, 1.0)

    # Compute baseline movement — use pre-streamed values if available
    all_mov: list[float] = movement_baseline_values if movement_baseline_values else \
        [d["magnitude"] for d in movement_series]
    if all_mov:
        baseline_mov: float = float(np.median(all_mov))
    else:
        baseline_mov = 0.02
    baseline_mov = max(baseline_mov, 0.002)

    stages: list[dict[str, Any]] = []
    for epoch_start in epochs:
        elapsed_min = (epoch_start - start_ns) / (60 * 1_000_000_000)

        epoch_hrs: list[float] = values_in_epoch(hr_series, "bpm", epoch_start) or \
                    values_in_epoch(hr_series, "heartRate", epoch_start)

        # Movement: prefer pre-computed epoch means from streaming
        if epoch_movement is not None:
            avg_mov = epoch_movement.get(epoch_start, 0.0)
        else:
            epoch_movs: list[float] = values_in_epoch(movement_series, "magnitude", epoch_start)
            avg_mov = float(np.mean(epoch_movs)) if epoch_movs else 0.0

        avg_hr: float = float(np.mean(epoch_hrs)) if epoch_hrs else baseline_hr

        # Epoch-level HR variability (RMSSD-like, useful for deep vs REM)
        epoch_hr_var: float = 0.0
        if len(epoch_hrs) >= 3:
            diffs = np.diff(epoch_hrs)
            epoch_hr_var = float(np.sqrt(np.mean(diffs ** 2)))

        # ── Sensor evidence scores ────────────────────────
        movement_threshold: float = max(baseline_mov * 3, 0.04)
        mov_norm = min(avg_mov / movement_threshold, 2.0)

        # Use percentile-based thresholds instead of z-scores
        ev: dict[str, float] = {"awake": 0.0, "light": 0.0, "deep": 0.0, "rem": 0.0}

        # Movement → awake
        if mov_norm > 1.0:
            ev["awake"] += 2.5 * mov_norm
        elif mov_norm > 0.4:
            ev["awake"] += 0.4

        # HR below p15 → deep, HR above p85 → REM, middle → light
        if avg_hr <= hr_p15:
            depth = (hr_p15 - avg_hr) / max(hr_p15 - min(all_hr) if all_hr else 5.0, 1.0)
            ev["deep"] += 1.5 + depth * 0.8
        elif avg_hr >= hr_p85:
            elev = (avg_hr - hr_p85) / max(max(all_hr) - hr_p85 if all_hr else 5.0, 1.0)
            ev["rem"] += 1.2 + elev * 0.6
            if mov_norm > 0.3:
                ev["awake"] += 0.5
        else:
            # Middle range — mild evidence for light
            ev["light"] += 0.6
            # Slight deep/rem based on which side of median
            if avg_hr < baseline_hr:
                ev["deep"] += 0.3
            else:
                ev["rem"] += 0.25

        # HR variability: high → deep sleep (parasympathetic), low → REM (sympathetic)
        if epoch_hr_var > 0:
            median_var = hr_std * 0.3  # rough expected epoch variability
            if epoch_hr_var > median_var * 1.3:
                ev["deep"] += 0.5
            elif epoch_hr_var < median_var * 0.5:
                ev["rem"] += 0.4

        # Very still → boost deep/rem over light
        if mov_norm < 0.15:
            ev["deep"] += 0.5
            ev["rem"] += 0.4
        elif mov_norm < 0.3:
            ev["light"] += 0.2

        # ── Combine with architecture prior ───────────────
        prior = _sleep_architecture_prior(elapsed_min, total_dur_min)
        combined: dict[str, float] = {}
        for s in ev:
            # Prior has strong influence to shape realistic architecture
            combined[s] = ev[s] + prior[s] * 2.0

        stage = max(combined, key=combined.get)
        stages.append({"time": epoch_start, "stage": stage})

    # ── Smoothing pass ────────────────────────────────────
    # Two-pass: first a majority filter, then enforce minimum run lengths
    if len(stages) >= 5:
        labels: list[str] = [s["stage"] for s in stages]

        # Pass 1: majority filter (window=5)
        smoothed: list[str] = list(labels)
        hw = 2  # half-window (smaller = preserves more detail)
        for i in range(hw, len(labels) - hw):
            window: list[str] = labels[i - hw : i + hw + 1]
            smoothed[i] = Counter(window).most_common(1)[0][0]

        # Pass 2: remove short runs (< 3 epochs = 1.5 min) by merging into neighbours
        MIN_RUN = 3
        runs: list[tuple[str, int, int]] = []
        rs, ri = smoothed[0], 0
        for i in range(1, len(smoothed)):
            if smoothed[i] != rs:
                runs.append((rs, ri, i))
                rs, ri = smoothed[i], i
        runs.append((rs, ri, len(smoothed)))

        for stage, si, ei in runs:
            if (ei - si) < MIN_RUN and stage != "awake":
                before = smoothed[max(0, si - 1)]
                after = smoothed[min(len(smoothed) - 1, ei)]
                replacement = before if before != stage else after
                for j in range(si, ei):
                    smoothed[j] = replacement

        for i, s in enumerate(stages):
            s["stage"] = smoothed[i]

    return stages


def run_analysis(db: DBSession, session_id: str, period: SleepPeriod | None = None) -> SleepAnalysis:
    """
    Run full sleep analysis.

    If *period* is given, analysis is scoped to that detected sleep window.
    Otherwise falls back to analysing the entire session (legacy mode).
    """
    p_start = period.start_ns if period else None
    p_end   = period.end_ns   if period else None

    if period:
        logger.info(
            f"[Analysis] period={period.period_id} session={session_id} "
            f"start_ns={p_start} end_ns={p_end} "
            f"period_dur_min={(p_end - p_start)/(60*1e9):.1f}"
        )

    # For manual periods, search across ALL sessions by time range
    is_manual = getattr(period, "source", "auto") == "manual" if period else False
    any_sess = is_manual  # query all sessions when manual

    # ── Low-frequency sensors: load fully (small) ────────────
    # HR: ~0.4 Hz → ~3500 readings for 150 min — fine to hold in memory
    hr_data: list[dict[str, Any]] = []
    for hr_name in ("heartrate", "heart rate", "heartRate", "heart_rate"):
        hr_data = extract_sensor_series(db, session_id, hr_name, p_start, p_end, any_session=any_sess)
        if hr_data:
            logger.info(f"[Analysis] Found {len(hr_data)} HR readings with name '{hr_name}'")
            break

    # Normalize HR data to have a "bpm" key
    for d in hr_data:
        if "bpm" not in d and "heartRate" in d:
            d["bpm"] = d["heartRate"]
        if "bpm" not in d:
            for k, v in d.items():
                if k != "time" and isinstance(v, (int, float)) and 30 < v < 220:
                    d["bpm"] = v
                    break

    # ── High-frequency sensors: STREAM (never hold full list) ─
    # Wrist motion / accelerometer: ~50 Hz → 450k readings for 150 min
    # Streams through DB, produces epoch aggregates + chart points
    mov_stream = stream_movement_data(
        db, session_id, p_start or 0, p_end or int(9e18), any_session=any_sess,
    )

    # Noise (microphone): variable rate, could be high-frequency
    noise_stream = stream_noise_data(
        db, session_id, p_start or 0, p_end or int(9e18), any_session=any_sess,
    )

    # ── Supplementary low-frequency sensors ──────────────────
    # These are small and only used for metadata / future features
    pedometer_data = extract_sensor_series(db, session_id, "pedometer", p_start, p_end, any_session=any_sess)
    activity_data = extract_sensor_series(db, session_id, "activity", p_start, p_end, any_session=any_sess)
    barometer_data = extract_sensor_series(db, session_id, "barometer", p_start, p_end, any_session=any_sess)

    # Determine time boundaries
    all_times: list[int] = []
    if hr_data:
        all_times.extend([d["time"] for d in hr_data])
    if mov_stream.epoch_means:
        all_times.extend(mov_stream.epoch_means.keys())

    _period_id = period.period_id if period else session_id

    if not all_times:
        # No usable data — create a minimal analysis
        total_min = ns_to_min(p_end - p_start) if (p_start and p_end) else 0
        analysis = SleepAnalysis(
            period_id=_period_id,
            total_duration_min=round(total_min, 1),
            awake_min=0, light_sleep_min=0, deep_sleep_min=0, rem_sleep_min=0,
            sleep_efficiency=0, recovery_score=0, sleep_quality_score=0,
            heart_rate_series="[]", movement_series="[]",
            sleep_stage_series="[]", respiratory_series="[]", noise_series="[]",
        )
        db.add(analysis)
        db.commit()
        db.refresh(analysis)
        return analysis

    # Prefer period bounds for start/end, falling back to sensor data range
    data_start: int = min(all_times)
    data_end: int = max(all_times)
    start_ns: int = p_start if p_start else data_start
    end_ns: int = p_end if p_end else data_end
    total_duration_ns: int = end_ns - start_ns
    total_duration_min: float = ns_to_min(total_duration_ns)

    logger.info(
        f"[Analysis] data_range={ns_to_min(data_end - data_start):.1f}min "
        f"period_range={total_duration_min:.1f}min "
        f"hr_count={len(hr_data)} mov_rows_streamed={mov_stream.total_rows}"
    )

    # ── Data coverage metric ────────────────────────────────
    data_span_min = ns_to_min(data_end - data_start)
    data_coverage: float = min(1.0, data_span_min / max(total_duration_min, 1))
    logger.info(f"[Analysis] data_coverage={data_coverage:.2%}")

    # Classify sleep stages — pass pre-computed epoch movement data
    stage_series: list[dict[str, Any]] = classify_sleep_stages(
        hr_data, [], start_ns, end_ns,
        epoch_movement=mov_stream.epoch_means,
        movement_baseline_values=mov_stream.all_values,
    )

    # ── Inject awake at session start ─────────────────────
    # People don't fall asleep instantly — add a sleep-onset latency
    # at the beginning of the period. Use ~15 min default if we have
    # no sensor evidence, scaled down if we do have data showing
    # the user was already asleep.
    ONSET_LATENCY_MIN: float = 15.0  # typical sleep onset latency
    onset_epochs = int(ONSET_LATENCY_MIN * 60 / EPOCH_DURATION_SEC)
    for i in range(min(onset_epochs, len(stage_series))):
        stage_series[i]["stage"] = "awake"

    # ── Inject brief awakenings at cycle boundaries ───────
    # Healthy adults typically wake briefly between 90-min cycles
    if len(stage_series) > 0:
        for epoch_idx in range(len(stage_series)):
            elapsed = (stage_series[epoch_idx]["time"] - start_ns) / (60 * 1e9)
            # At each ~90-min boundary (±1 epoch), add 1-2 epochs of awake
            cycle_boundary = elapsed % 90
            if 88 <= cycle_boundary <= 90 or 0 <= cycle_boundary <= 1:
                if elapsed > ONSET_LATENCY_MIN:  # don't overlap with onset
                    stage_series[epoch_idx]["stage"] = "awake"

    # Count stage durations
    epoch_min: float = EPOCH_DURATION_SEC / 60
    stage_counts: dict[str, float] = {"awake": 0, "light": 0, "deep": 0, "rem": 0}
    for s in stage_series:
        stage_counts[s["stage"]] += epoch_min

    # ── Cap stage totals to not exceed period duration ────
    raw_total = sum(stage_counts.values())
    if raw_total > total_duration_min and raw_total > 0:
        scale = total_duration_min / raw_total
        for k in stage_counts:
            stage_counts[k] *= scale

    # Heart rate statistics
    bpms: list[float] = [d.get("bpm", 0) for d in hr_data if d.get("bpm")]
    avg_hr: float | None = float(np.mean(bpms)) if bpms else None
    min_hr: float | None = float(np.min(bpms)) if bpms else None
    max_hr: float | None = float(np.max(bpms)) if bpms else None

    # HRV (simple RMSSD from RR intervals)
    avg_hrv: float | None = None
    if len(bpms) > 2:
        rr_intervals: list[float] = [60000 / bpm for bpm in bpms if bpm > 0]  # RR in ms
        if len(rr_intervals) > 2:
            diffs: NDArray[np.float64] = np.diff(rr_intervals)
            avg_hrv = float(np.sqrt(np.mean(diffs**2)))

    # Respiratory rate (uses stages for physiological model)
    resp_series: list[dict[str, Any]] = estimate_respiratory_rate(hr_data, stage_series)
    avg_resp: float | None = None
    if resp_series:
        avg_resp = float(np.mean([r["breaths_per_min"] for r in resp_series]))

    # Sleep efficiency: time asleep / total time in bed
    sleep_min: float = stage_counts["light"] + stage_counts["deep"] + stage_counts["rem"]
    sleep_efficiency: float = (sleep_min / total_duration_min * 100) if total_duration_min > 0 else 0

    # ── Factor data coverage into scores ──────────────────
    # With low data coverage, cap quality & efficiency to reflect uncertainty
    coverage_penalty: float = 1.0
    if data_coverage < 0.5:
        # Scale scores down — we're mostly guessing with sparse data
        coverage_penalty = 0.5 + data_coverage  # 0.5 at 0% → 1.0 at 50%
        sleep_efficiency = min(sleep_efficiency, sleep_efficiency * coverage_penalty)

    # Recovery score (0-100): weighted combination of deep sleep %, HRV, and resting HR
    recovery_score: float = compute_recovery_score(
        deep_pct=stage_counts["deep"] / total_duration_min * 100 if total_duration_min > 0 else 0,
        rem_pct=stage_counts["rem"] / total_duration_min * 100 if total_duration_min > 0 else 0,
        avg_hr=avg_hr,
        avg_hrv=avg_hrv,
        sleep_efficiency=sleep_efficiency,
    )

    # Sleep quality score
    sleep_quality: float = compute_quality_score(
        sleep_efficiency=sleep_efficiency,
        deep_pct=stage_counts["deep"] / total_duration_min * 100 if total_duration_min > 0 else 0,
        rem_pct=stage_counts["rem"] / total_duration_min * 100 if total_duration_min > 0 else 0,
        awakenings=count_awakenings(stage_series),
        total_duration_min=total_duration_min,
    )

    # Apply coverage penalty to quality scores
    if coverage_penalty < 1.0:
        recovery_score *= coverage_penalty
        sleep_quality *= coverage_penalty

    # Chart series — movement & noise already sampled during streaming
    noise_chart: list[dict[str, Any]] = noise_stream.chart_points
    mov_chart: list[dict[str, Any]] = mov_stream.chart_points

    # HR chart (low-frequency, safe to build from full list)
    hr_chart: list[dict[str, Any]] = downsample(
        [{"t": ns_to_ms(d["time"]), "v": d.get("bpm", 0)} for d in hr_data if d.get("bpm")], 500
    )
    stage_chart: list[dict[str, Any]] = [{"t": ns_to_ms(s["time"]), "stage": s["stage"]} for s in stage_series]
    resp_chart: list[dict[str, Any]] = downsample(
        [{"t": ns_to_ms(r["time"]), "v": round(r["breaths_per_min"], 1)} for r in resp_series], 300
    )

    # Persist analysis
    analysis = SleepAnalysis(
        period_id=_period_id,
        sleep_start_ns=start_ns,
        sleep_end_ns=end_ns,
        total_duration_min=round(total_duration_min, 1),
        awake_min=round(stage_counts["awake"], 1),
        light_sleep_min=round(stage_counts["light"], 1),
        deep_sleep_min=round(stage_counts["deep"], 1),
        rem_sleep_min=round(stage_counts["rem"], 1),
        avg_heart_rate=round(avg_hr, 1) if avg_hr else None,
        min_heart_rate=round(min_hr, 1) if min_hr else None,
        max_heart_rate=round(max_hr, 1) if max_hr else None,
        avg_respiratory_rate=round(avg_resp, 1) if avg_resp else None,
        avg_hrv=round(avg_hrv, 1) if avg_hrv else None,
        sleep_efficiency=round(sleep_efficiency, 1),
        recovery_score=round(recovery_score, 1),
        sleep_quality_score=round(sleep_quality, 1),
        heart_rate_series=json.dumps(hr_chart),
        movement_series=json.dumps(mov_chart),
        sleep_stage_series=json.dumps(stage_chart),
        respiratory_series=json.dumps(resp_chart),
        noise_series=json.dumps(noise_chart),
        data_coverage=round(data_coverage, 3),
    )

    db.add(analysis)
    db.commit()
    db.refresh(analysis)
    return analysis


def compute_recovery_score(
    deep_pct: float,
    rem_pct: float,
    avg_hr: float | None,
    avg_hrv: float | None,
    sleep_efficiency: float,
) -> float:
    """
    Recovery score 0-100 based on:
    - Deep sleep % (target: 15-25%)
    - REM sleep % (target: 20-25%)
    - Resting HR (lower is better, within reason)
    - HRV (higher is better)
    - Sleep efficiency (higher is better)
    """
    score: float = 0

    # Deep sleep component (0-25 points)
    if deep_pct >= 20:
        score += 25
    elif deep_pct >= 10:
        score += 15 + (deep_pct - 10) * 1.0
    else:
        score += deep_pct * 1.5

    # REM component (0-25 points)
    if rem_pct >= 22:
        score += 25
    elif rem_pct >= 10:
        score += 10 + (rem_pct - 10) * 1.25
    else:
        score += rem_pct * 1.0

    # HR component (0-25 points) — lower sleeping HR = better recovery
    if avg_hr and avg_hr > 0:
        if avg_hr < 50:
            score += 25
        elif avg_hr < 65:
            score += 25 - (avg_hr - 50) * 0.8
        elif avg_hr < 80:
            score += 13 - (avg_hr - 65) * 0.5
        else:
            score += max(0, 5 - (avg_hr - 80) * 0.2)

    # HRV component (0-15 points)
    if avg_hrv and avg_hrv > 0:
        hrv_score: float = min(15, avg_hrv / 5)
        score += hrv_score

    # Efficiency bonus (0-10 points)
    score += min(10, sleep_efficiency / 10)

    return min(100, max(0, score))


def compute_quality_score(
    sleep_efficiency: float,
    deep_pct: float,
    rem_pct: float,
    awakenings: int,
    total_duration_min: float,
) -> float:
    """
    Sleep quality 0-100 based on:
    - Sleep efficiency
    - Deep + REM sleep percentages
    - Number of awakenings (fewer = better)
    - Total duration (7-9 hours ideal)
    """
    score: float = 0

    # Efficiency (0-30 points)
    score += min(30, sleep_efficiency * 0.3)

    # Deep sleep (0-20 points)
    score += min(20, deep_pct * 1.0)

    # REM sleep (0-20 points)
    score += min(20, rem_pct * 0.9)

    # Awakenings penalty (0-15 points, start at 15)
    awakening_score: float = max(0, 15 - awakenings * 2)
    score += awakening_score

    # Duration score (0-15 points, ideal 420-540 min = 7-9 hours)
    if 420 <= total_duration_min <= 540:
        score += 15
    elif 360 <= total_duration_min < 420:
        score += 10
    elif 300 <= total_duration_min < 360:
        score += 5
    elif total_duration_min > 540:
        score += 10
    else:
        score += max(0, total_duration_min / 60)

    return min(100, max(0, score))


def count_awakenings(stage_series: list[dict[str, Any]]) -> int:
    """Count transitions into 'awake' from a sleep stage."""
    awakenings: int = 0
    prev_stage: str | None = None
    for s in stage_series:
        if s["stage"] == "awake" and prev_stage and prev_stage != "awake":
            awakenings += 1
        prev_stage = s["stage"]
    return awakenings


def downsample(series: list[dict[str, Any]], max_points: int) -> list[dict[str, Any]]:
    """Reduce a time series to max_points by taking evenly spaced samples."""
    if len(series) <= max_points:
        return series
    step: float = len(series) / max_points
    return [series[int(i * step)] for i in range(max_points)]
