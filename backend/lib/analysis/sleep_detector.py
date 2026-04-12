"""
Automatic sleep period detection from continuous sensor streams.

Scans heart-rate and accelerometer/wrist-motion data to find windows where the
user was asleep.  Works on raw SensorReadings — no manual session boundaries
required.

Detection algorithm (simplified actigraphy):
  1.  Compute 1-minute HR and movement bins from the raw stream.
  2.  A 1-min bin is "still & low HR" when:
         - movement magnitude < MOVEMENT_THRESHOLD  AND
         - heart rate < baseline_hr − HR_DROP_BPM
  3.  Mark candidate sleep onset when we see ≥ ONSET_WINDOW consecutive
      still-and-low-HR minutes.
  4.  Mark candidate sleep offset when we see ≥ OFFSET_WINDOW consecutive
      NOT-still-and-low-HR minutes.
  5.  Discard any candidate shorter than MIN_NAP_MIN.
  6.  Label ≥ NIGHT_MIN_HOURS as "night", otherwise "nap".
  7.  Merge two adjacent periods separated by < MERGE_GAP_MIN.

Thresholds are deliberately conservative so we avoid false positives from
quiet sitting.  They will need per-user tuning once real data arrives.
"""

import json
import logging
import uuid
from datetime import datetime
from typing import Any

import numpy as np
from sqlalchemy import func
from sqlalchemy.orm import Session as DBSession

from lib.db.database import SensorReading, SleepPeriod

logger = logging.getLogger("signal-to-sleep.detector")

# ── Tuning knobs ──────────────────────────────────────────

MOVEMENT_THRESHOLD: float = 0.025          # g – net accel above which user is "moving"
MOVEMENT_HARD_LIMIT: float = 0.08          # g – above this, always awake (intentional motion)
HR_DROP_BPM: float = 12.0                 # bpm below baseline → strong sleep signal
HR_DROP_SOFT_BPM: float = 3.0             # bpm below baseline → mild sleep signal (nap range)
CALM_SCORE_THRESHOLD: float = 0.6         # combined score 0-1 to classify bin as calm
ONSET_WINDOW_MIN: int = 10                # consecutive calm minutes to declare onset
OFFSET_WINDOW_MIN: int = 20               # consecutive active minutes to declare offset
MIN_NAP_MIN: int = 20                     # shorter than this → discard
NIGHT_MIN_HOURS: float = 3.0              # threshold to call it a night vs a nap
MERGE_GAP_MIN: int = 60                   # merge two periods closer than this
BIN_DURATION_NS: int = 60 * 1_000_000_000 # 1-minute bins


# ── Helpers ───────────────────────────────────────────────

def _ns_to_min(ns: int) -> float:
    return ns / (60 * 1_000_000_000)


def _ns_to_dt(ns: int) -> datetime:
    return datetime.fromtimestamp(ns / 1_000_000_000)


def _compute_baseline_hr(hr_values: list[float]) -> float:
    """Daytime baseline HR ≈ 75th-percentile of all readings (biased toward wake)."""
    if not hr_values:
        return 70.0
    return float(np.percentile(hr_values, 75))


# ── Core detection ────────────────────────────────────────

def detect_sleep_periods(
    db: DBSession,
    session_id: str,
    *,
    since_ns: int | None = None,
) -> list[SleepPeriod]:
    """
    Scan sensor data for ``session_id`` and return newly detected SleepPeriods.
    Already-known periods (by overlapping time range) are skipped.

    Parameters
    ----------
    db : DBSession
    session_id : MQTT session that owns the sensor readings
    since_ns : only look at data after this timestamp (optimisation for incremental runs)
    """

    # ── 1. Pull HR + motion data ──────────────────────────
    hr_q = (
        db.query(SensorReading.timestamp_ns, SensorReading.values_json)
        .filter(SensorReading.session_id == session_id, SensorReading.sensor_name.in_(["heartrate", "heart rate", "heartRate", "heart_rate"]))
    )
    mot_q = (
        db.query(SensorReading.timestamp_ns, SensorReading.sensor_name, SensorReading.values_json)
        .filter(
            SensorReading.session_id == session_id,
            SensorReading.sensor_name.in_(["wrist motion", "accelerometer"]),
        )
    )
    if since_ns is not None:
        hr_q = hr_q.filter(SensorReading.timestamp_ns >= since_ns)
        mot_q = mot_q.filter(SensorReading.timestamp_ns >= since_ns)

    hr_q = hr_q.order_by(SensorReading.timestamp_ns)
    mot_q = mot_q.order_by(SensorReading.timestamp_ns)

    # Stream results to avoid materialising all ORM objects at once
    hr_points: list[tuple[int, float]] = []
    for ts, vj in hr_q.yield_per(5000):
        d = json.loads(vj)
        bpm = d.get("bpm") or d.get("heartRate")
        if bpm and 30 < bpm < 220:
            hr_points.append((ts, float(bpm)))

    if len(hr_points) < 10:
        logger.debug(f"[{session_id}] not enough HR data ({len(hr_points)} rows)")
        return []

    mot_points: list[tuple[int, float]] = []
    for ts, sensor_name, vj in mot_q.yield_per(5000):
        d = json.loads(vj)
        if sensor_name == "accelerometer":
            # Accelerometer includes gravity (~1g on Z), so subtract it
            x = d.get("x", 0) or 0
            y = d.get("y", 0) or 0
            z = d.get("z", 0) or 0
            mag = float(np.sqrt(x**2 + y**2 + z**2))
            net = abs(mag - 1.0)
        else:
            # Wrist motion: acceleration values are pure motion (no gravity)
            x = d.get("accelerationX", 0) or 0
            y = d.get("accelerationY", 0) or 0
            z = d.get("accelerationZ", 0) or 0
            net = float(np.sqrt(x**2 + y**2 + z**2))
        mot_points.append((ts, net))

    if not hr_points:
        return []

    # ── 2. Bin into 1-minute windows ──────────────────────
    t_min = hr_points[0][0]
    t_max = hr_points[-1][0]
    if mot_points:
        t_min = min(t_min, mot_points[0][0])
        t_max = max(t_max, mot_points[-1][0])

    n_bins = int((t_max - t_min) / BIN_DURATION_NS) + 1
    if n_bins < ONSET_WINDOW_MIN:
        return []

    bin_hr: dict[int, list[float]] = {}
    bin_mot: dict[int, list[float]] = {}

    for ts, bpm in hr_points:
        b = int((ts - t_min) / BIN_DURATION_NS)
        bin_hr.setdefault(b, []).append(bpm)

    for ts, net in mot_points:
        b = int((ts - t_min) / BIN_DURATION_NS)
        bin_mot.setdefault(b, []).append(net)

    # Baseline HR from all data
    baseline = _compute_baseline_hr([bpm for _, bpm in hr_points])
    hr_hard = baseline - HR_DROP_BPM       # strong sleep signal (nighttime)
    hr_soft = baseline - HR_DROP_SOFT_BPM  # mild sleep signal (nap range)
    logger.info(
        f"[{session_id}] baseline HR={baseline:.1f}, "
        f"soft_thr={hr_soft:.1f}, hard_thr={hr_hard:.1f}, bins={n_bins}"
    )

    # ── 3. Score each bin ─────────────────────────────────
    # Instead of binary calm/not-calm, compute a 0-1 sleep-likelihood
    # score combining movement stillness and HR drop. This catches naps
    # where HR only drops 5-8 bpm (not the 12+ of nighttime sleep).
    calm: list[bool] = []
    for i in range(n_bins):
        avg_hr = float(np.mean(bin_hr[i])) if i in bin_hr else baseline
        avg_mot = float(np.mean(bin_mot[i])) if i in bin_mot else 0.0

        # ── Movement score (0-1): lower movement → higher score
        if avg_mot >= MOVEMENT_HARD_LIMIT:
            mot_score = 0.0       # definitely moving
        elif avg_mot < MOVEMENT_THRESHOLD:
            mot_score = 1.0       # very still
        else:
            # Linear ramp between threshold and hard limit
            mot_score = 1.0 - (avg_mot - MOVEMENT_THRESHOLD) / (MOVEMENT_HARD_LIMIT - MOVEMENT_THRESHOLD)

        # ── HR score (0-1): lower HR relative to baseline → higher score
        if avg_hr <= hr_hard:
            hr_score = 1.0        # deep sleep territory
        elif avg_hr >= baseline:
            hr_score = 0.0        # at or above baseline
        elif avg_hr <= hr_soft:
            # Between soft and hard threshold — strong signal
            hr_score = 0.5 + 0.5 * (hr_soft - avg_hr) / max(hr_soft - hr_hard, 1.0)
        else:
            # Between baseline and soft threshold — weak but real signal
            hr_score = 0.5 * (baseline - avg_hr) / max(baseline - hr_soft, 1.0)

        # Combined: weighted — movement is the stronger signal for naps
        # since HR drop during naps is subtle
        score = mot_score * 0.55 + hr_score * 0.45
        calm.append(score >= CALM_SCORE_THRESHOLD)

    # ── 4. Find onset / offset transitions ────────────────
    candidates: list[tuple[int, int]] = []  # (onset_bin, offset_bin)
    in_sleep = False
    calm_run = 0
    active_run = 0
    onset_bin = 0

    for i, c in enumerate(calm):
        if not in_sleep:
            if c:
                calm_run += 1
                if calm_run >= ONSET_WINDOW_MIN:
                    in_sleep = True
                    onset_bin = i - calm_run + 1
                    active_run = 0
            else:
                calm_run = 0
        else:
            if not c:
                active_run += 1
                if active_run >= OFFSET_WINDOW_MIN:
                    offset_bin = i - active_run + 1
                    candidates.append((onset_bin, offset_bin))
                    in_sleep = False
                    calm_run = 0
                    active_run = 0
            else:
                active_run = 0

    # If still in sleep at end of data, the period is ongoing
    if in_sleep:
        candidates.append((onset_bin, n_bins - 1))

    if not candidates:
        return []

    # ── 5. Convert bins → nanosecond timestamps ───────────
    raw_periods: list[tuple[int, int, bool]] = []  # (start_ns, end_ns, is_final)
    for ob, eb in candidates:
        s_ns = t_min + ob * BIN_DURATION_NS
        e_ns = t_min + (eb + 1) * BIN_DURATION_NS
        is_final = eb < n_bins - 1  # final if ended before data runs out
        raw_periods.append((s_ns, e_ns, is_final))

    # ── 6. Merge close neighbours ─────────────────────────
    merged: list[tuple[int, int, bool]] = [raw_periods[0]]
    for s, e, final in raw_periods[1:]:
        prev_s, prev_e, prev_final = merged[-1]
        gap_min = _ns_to_min(s - prev_e)
        if gap_min < MERGE_GAP_MIN:
            merged[-1] = (prev_s, e, final)
        else:
            merged.append((s, e, final))

    # ── 7. Filter short, classify, deduplicate ────────────
    existing: list[SleepPeriod] = db.query(SleepPeriod).filter(
        SleepPeriod.session_id == session_id,
    ).all()
    existing_ranges: list[tuple[int, int, str]] = [
        (p.start_ns, p.end_ns, p.period_id) for p in existing
    ]

    new_periods: list[SleepPeriod] = []
    for s_ns, e_ns, is_final in merged:
        dur_min = _ns_to_min(e_ns - s_ns)
        if dur_min < MIN_NAP_MIN:
            continue

        # Check overlap with existing periods
        overlaps_id: str | None = None
        for ex_s, ex_e, ex_id in existing_ranges:
            overlap = min(e_ns, ex_e) - max(s_ns, ex_s)
            if overlap > 0:
                overlaps_id = ex_id
                break

        if overlaps_id:
            # Update existing period's end time if it grew —
            # but never touch manual periods (controlled by annotations)
            for ep in existing:
                if ep.period_id == overlaps_id:
                    if getattr(ep, "source", "auto") == "manual":
                        break  # manual periods are managed by annotations
                    if e_ns > ep.end_ns:
                        ep.end_ns = e_ns
                        ep.ended_at = _ns_to_dt(e_ns)
                        ep.duration_min = round(_ns_to_min(e_ns - ep.start_ns), 1)
                        ep.is_final = is_final
                    break
            continue

        sleep_type = "night" if dur_min >= NIGHT_MIN_HOURS * 60 else "nap"
        confidence = min(1.0, dur_min / 60)  # crude: longer = more confident

        period = SleepPeriod(
            period_id=f"sp-{uuid.uuid4().hex[:10]}",
            session_id=session_id,
            start_ns=s_ns,
            end_ns=e_ns,
            started_at=_ns_to_dt(s_ns),
            ended_at=_ns_to_dt(e_ns),
            sleep_type=sleep_type,
            duration_min=round(dur_min, 1),
            confidence=round(confidence, 3),
            is_final=is_final,
        )
        db.add(period)
        new_periods.append(period)

    if new_periods or any(p in db.dirty for p in existing):
        db.commit()
        logger.info(
            f"[{session_id}] detected {len(new_periods)} new sleep period(s), "
            f"updated {sum(1 for p in existing if p in db.dirty)} existing"
        )

    return new_periods


def run_detection_for_all_sessions(db: DBSession) -> list[SleepPeriod]:
    """Run detection across every recording session. Returns all new periods.

    Uses incremental scanning: only processes data after the latest known
    sleep period end time per session (minus a 30-min overlap buffer for
    merge logic).
    """
    from lib.db.database import RecordingSession
    from sqlalchemy import func

    sessions = db.query(RecordingSession).all()
    all_new: list[SleepPeriod] = []

    for s in sessions:
        try:
            # Find the latest period end for this session so we only scan new data
            latest_end = (
                db.query(func.max(SleepPeriod.end_ns))
                .filter(SleepPeriod.session_id == s.session_id)
                .scalar()
            )
            # Overlap buffer: go back 30 min to allow merging with recent periods
            since_ns = None
            if latest_end:
                since_ns = latest_end - (MERGE_GAP_MIN * 60 * 1_000_000_000)

            new = detect_sleep_periods(db, s.session_id, since_ns=since_ns)
            all_new.extend(new)
        except Exception as e:
            logger.error(f"Detection failed for {s.session_id}: {e}")
    return all_new
