#!/usr/bin/env python3
"""
Diagnostic script to debug sleep detection failures.

Runs inside the docker container with:
  docker compose exec backend python scripts/debug_detection.py

Performs step-by-step analysis of the detection algorithm:
  1. Counts HR readings and date range
  2. Counts readings per day to verify all 7 days loaded
  3. Runs detection with verbose output showing:
     - Baseline HR, threshold
     - Total bins, calm bins count
     - Each onset/offset transition
     - Candidate periods before/after filtering
"""

import os
import sys
import json
import logging
from datetime import datetime, timedelta
from typing import Optional

import numpy as np
from sqlalchemy import func

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lib.db.database import init_db, SessionLocal, SensorReading, SleepPeriod, RecordingSession

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(message)s'
)
logger = logging.getLogger("debug-detection")

# ── Detection parameters (copied from sleep_detector.py) ──
MOVEMENT_THRESHOLD: float = 0.025
HR_DROP_BPM: float = 12.0
ONSET_WINDOW_MIN: int = 15
OFFSET_WINDOW_MIN: int = 8
MIN_NAP_MIN: int = 20
NIGHT_MIN_HOURS: float = 3.0
MERGE_GAP_MIN: int = 30
BIN_DURATION_NS: int = 60 * 1_000_000_000


def _ns_to_min(ns: int) -> float:
    return ns / (60 * 1_000_000_000)


def _ns_to_dt(ns: int) -> datetime:
    return datetime.fromtimestamp(ns / 1_000_000_000)


def _compute_baseline_hr(hr_values: list[float]) -> float:
    """Daytime baseline HR ≈ 75th-percentile of all readings (biased toward wake)."""
    if not hr_values:
        return 70.0
    return float(np.percentile(hr_values, 75))


def analyze_data(session_id: str, db) -> None:
    """Run diagnostic analysis on detection algorithm."""
    print(f"\n{'='*80}")
    print(f"SLEEP DETECTION DEBUG ANALYSIS")
    print(f"{'='*80}\n")

    # ── Step 1: Query data and check coverage ──────────────────
    print("Step 1: Checking data coverage")
    print("-" * 80)

    hr_q = (
        db.query(SensorReading.timestamp_ns, SensorReading.values_json)
        .filter(SensorReading.session_id == session_id, SensorReading.sensor_name.in_(["heartrate", "heart rate", "heartRate", "heart_rate"]))
        .order_by(SensorReading.timestamp_ns)
    )

    mot_q = (
        db.query(SensorReading.timestamp_ns, SensorReading.sensor_name, SensorReading.values_json)
        .filter(
            SensorReading.session_id == session_id,
            SensorReading.sensor_name.in_(["wrist motion", "accelerometer"]),
        )
        .order_by(SensorReading.timestamp_ns)
    )

    hr_points: list[tuple[int, float]] = []
    for ts, vj in hr_q.yield_per(5000):
        d = json.loads(vj)
        bpm = d.get("bpm") or d.get("heartRate")
        if bpm and 30 < bpm < 220:
            hr_points.append((ts, float(bpm)))

    mot_points: list[tuple[int, float]] = []
    for ts, sensor_name, vj in mot_q.yield_per(5000):
        d = json.loads(vj)
        if sensor_name == "accelerometer":
            x = d.get("x", 0) or 0
            y = d.get("y", 0) or 0
            z = d.get("z", 0) or 0
            mag = float(np.sqrt(x**2 + y**2 + z**2))
            net = abs(mag - 1.0)
        else:
            x = d.get("accelerationX", 0) or 0
            y = d.get("accelerationY", 0) or 0
            z = d.get("accelerationZ", 0) or 0
            net = float(np.sqrt(x**2 + y**2 + z**2))
        mot_points.append((ts, net))

    if not hr_points:
        print("ERROR: No HR data found!")
        return

    t_min = hr_points[0][0]
    t_max = hr_points[-1][0]
    if mot_points:
        t_min = min(t_min, mot_points[0][0])
        t_max = max(t_max, mot_points[-1][0])

    dt_min = _ns_to_dt(t_min)
    dt_max = _ns_to_dt(t_max)

    print(f"Total HR readings: {len(hr_points):,}")
    print(f"Total motion readings: {len(mot_points):,}")
    print(f"Time range: {dt_min.strftime('%Y-%m-%d %H:%M:%S')} → {dt_max.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Total duration: {_ns_to_min(t_max - t_min) / 60:.1f} hours\n")

    # ── Step 2: Readings per day ───────────────────────────────
    print("Step 2: Readings per day")
    print("-" * 80)

    readings_by_day: dict[str, int] = {}
    for ts, _ in hr_points:
        dt = _ns_to_dt(ts)
        day_str = dt.strftime("%Y-%m-%d")
        readings_by_day[day_str] = readings_by_day.get(day_str, 0) + 1

    for day in sorted(readings_by_day.keys()):
        count = readings_by_day[day]
        print(f"  {day}: {count:5d} HR readings")

    print()

    # ── Step 3: Bin the data ───────────────────────────────────
    print("Step 3: Binning into 1-minute windows")
    print("-" * 80)

    n_bins = int((t_max - t_min) / BIN_DURATION_NS) + 1
    print(f"Total bins: {n_bins}")
    print(f"Required for onset: {ONSET_WINDOW_MIN} consecutive calm bins\n")

    bin_hr: dict[int, list[float]] = {}
    bin_mot: dict[int, list[float]] = {}

    for ts, bpm in hr_points:
        b = int((ts - t_min) / BIN_DURATION_NS)
        bin_hr.setdefault(b, []).append(bpm)

    for ts, net in mot_points:
        b = int((ts - t_min) / BIN_DURATION_NS)
        bin_mot.setdefault(b, []).append(net)

    # ── Step 4: Compute baseline and threshold ─────────────────
    print("Step 4: Baseline HR and threshold")
    print("-" * 80)

    baseline = _compute_baseline_hr([bpm for _, bpm in hr_points])
    hr_threshold = baseline - HR_DROP_BPM

    print(f"All HR values (n={len(hr_points)}): min={min(bpm for _, bpm in hr_points):.1f}, "
          f"max={max(bpm for _, bpm in hr_points):.1f}, "
          f"mean={np.mean([bpm for _, bpm in hr_points]):.1f}")
    print(f"Baseline HR (75th percentile): {baseline:.1f} bpm")
    print(f"HR threshold (baseline - {HR_DROP_BPM}): {hr_threshold:.1f} bpm")
    print(f"Movement threshold: {MOVEMENT_THRESHOLD} g\n")

    # ── Step 5: Classify each bin ──────────────────────────────
    print("Step 5: Classifying bins as calm or active")
    print("-" * 80)

    calm: list[bool] = []
    for i in range(n_bins):
        avg_hr = float(np.mean(bin_hr[i])) if i in bin_hr else baseline
        avg_mot = float(np.mean(bin_mot[i])) if i in bin_mot else 0.0
        is_calm = avg_hr < hr_threshold and avg_mot < MOVEMENT_THRESHOLD
        calm.append(is_calm)

    calm_count = sum(1 for c in calm if c)
    active_count = sum(1 for c in calm if not c)

    print(f"Calm bins: {calm_count:,} ({calm_count/n_bins*100:.1f}%)")
    print(f"Active bins: {active_count:,} ({active_count/n_bins*100:.1f}%)\n")

    # ── Step 6: Find onset/offset transitions ───────────────────
    print("Step 6: Finding sleep onset/offset transitions")
    print("-" * 80)

    candidates: list[tuple[int, int]] = []
    in_sleep = False
    calm_run = 0
    active_run = 0
    onset_bin = 0

    transitions: list[dict] = []

    for i, c in enumerate(calm):
        if not in_sleep:
            if c:
                calm_run += 1
                if calm_run >= ONSET_WINDOW_MIN:
                    in_sleep = True
                    onset_bin = i - calm_run + 1
                    onset_ts = t_min + onset_bin * BIN_DURATION_NS
                    onset_dt = _ns_to_dt(onset_ts)
                    transitions.append({
                        'type': 'ONSET',
                        'bin': onset_bin,
                        'dt': onset_dt,
                        'calm_run': calm_run
                    })
                    print(f"  Onset at bin {onset_bin:5d}: {onset_dt.strftime('%Y-%m-%d %H:%M:%S')} "
                          f"(after {calm_run} calm bins)")
                    active_run = 0
            else:
                calm_run = 0
        else:
            if not c:
                active_run += 1
                if active_run >= OFFSET_WINDOW_MIN:
                    offset_bin = i - active_run + 1
                    offset_ts = t_min + offset_bin * BIN_DURATION_NS
                    offset_dt = _ns_to_dt(offset_ts)
                    candidates.append((onset_bin, offset_bin))
                    transitions.append({
                        'type': 'OFFSET',
                        'bin': offset_bin,
                        'dt': offset_dt,
                        'active_run': active_run
                    })
                    print(f"  Offset at bin {offset_bin:5d}: {offset_dt.strftime('%Y-%m-%d %H:%M:%S')} "
                          f"(after {active_run} active bins)")
                    in_sleep = False
                    calm_run = 0
                    active_run = 0
            else:
                active_run = 0

    if in_sleep:
        offset_bin = n_bins - 1
        offset_ts = t_min + (offset_bin + 1) * BIN_DURATION_NS
        offset_dt = _ns_to_dt(offset_ts)
        candidates.append((onset_bin, offset_bin))
        transitions.append({
            'type': 'ONGOING',
            'bin': offset_bin,
            'dt': offset_dt
        })
        print(f"  Still asleep at end of data: offset would be bin {offset_bin:5d}")

    print()

    # ── Step 7: Show candidates before filtering ────────────────
    print("Step 7: Candidate periods (before filtering)")
    print("-" * 80)

    if not candidates:
        print("  No candidates found!")
        print()
        return

    for i, (ob, eb) in enumerate(candidates):
        s_ns = t_min + ob * BIN_DURATION_NS
        e_ns = t_min + (eb + 1) * BIN_DURATION_NS
        s_dt = _ns_to_dt(s_ns)
        e_dt = _ns_to_dt(e_ns)
        dur_min = _ns_to_min(e_ns - s_ns)
        print(f"  Candidate {i+1}: {s_dt.strftime('%Y-%m-%d %H:%M:%S')} → {e_dt.strftime('%H:%M:%S')} ({dur_min:.1f} min)")

    print()

    # ── Step 8: Convert to ns timestamps ───────────────────────
    print("Step 8: Converting to nanosecond timestamps")
    print("-" * 80)

    raw_periods: list[tuple[int, int, bool]] = []
    for ob, eb in candidates:
        s_ns = t_min + ob * BIN_DURATION_NS
        e_ns = t_min + (eb + 1) * BIN_DURATION_NS
        is_final = eb < n_bins - 1
        raw_periods.append((s_ns, e_ns, is_final))
        dur_min = _ns_to_min(e_ns - s_ns)
        print(f"  Period: {_ns_to_dt(s_ns).strftime('%Y-%m-%d %H:%M:%S')} → {_ns_to_dt(e_ns).strftime('%H:%M:%S')} "
              f"({dur_min:.1f} min, final={is_final})")

    print()

    # ── Step 9: Merge close neighbors ──────────────────────────
    print("Step 9: Merging periods closer than MERGE_GAP_MIN")
    print("-" * 80)
    print(f"Merge gap threshold: {MERGE_GAP_MIN} minutes\n")

    merged: list[tuple[int, int, bool]] = [raw_periods[0]]
    print(f"  Initial: period 1 (before merge)")

    for i, (s, e, final) in enumerate(raw_periods[1:], start=2):
        prev_s, prev_e, prev_final = merged[-1]
        gap_min = _ns_to_min(s - prev_e)
        if gap_min < MERGE_GAP_MIN:
            old_dur = _ns_to_min(prev_e - prev_s)
            new_dur = _ns_to_min(e - prev_s)
            merged[-1] = (prev_s, e, final)
            print(f"  Period {i}: MERGED (gap={gap_min:.1f} min < {MERGE_GAP_MIN}) — "
                  f"extended from {old_dur:.1f} to {new_dur:.1f} min")
        else:
            merged.append((s, e, final))
            print(f"  Period {i}: kept separate (gap={gap_min:.1f} min >= {MERGE_GAP_MIN})")

    print()

    # ── Step 10: Apply minimum duration filter ─────────────────
    print("Step 10: Filtering by minimum duration")
    print("-" * 80)
    print(f"Min nap duration: {MIN_NAP_MIN} minutes\n")

    filtered: list[tuple[int, int, bool]] = []
    for i, (s_ns, e_ns, is_final) in enumerate(merged):
        dur_min = _ns_to_min(e_ns - s_ns)
        s_dt = _ns_to_dt(s_ns)
        e_dt = _ns_to_dt(e_ns)
        if dur_min < MIN_NAP_MIN:
            print(f"  Period {i+1}: DISCARDED ({dur_min:.1f} min < {MIN_NAP_MIN})")
        else:
            filtered.append((s_ns, e_ns, is_final))
            sleep_type = "night" if dur_min >= NIGHT_MIN_HOURS * 60 else "nap"
            print(f"  Period {i+1}: KEPT ({dur_min:.1f} min, type={sleep_type})")

    print()

    # ── Step 11: Show final result ─────────────────────────────
    print("Step 11: FINAL RESULT")
    print("-" * 80)
    print(f"Final periods to be stored: {len(filtered)}\n")

    for i, (s_ns, e_ns, is_final) in enumerate(filtered, start=1):
        dur_min = _ns_to_min(e_ns - s_ns)
        s_dt = _ns_to_dt(s_ns)
        e_dt = _ns_to_dt(e_ns)
        sleep_type = "night" if dur_min >= NIGHT_MIN_HOURS * 60 else "nap"
        confidence = min(1.0, dur_min / 60)
        print(f"  {i}. {s_dt.strftime('%Y-%m-%d %H:%M:%S')} → {e_dt.strftime('%H:%M:%S')}")
        print(f"     Type: {sleep_type:5s} | Duration: {dur_min:6.1f} min | Confidence: {confidence:.3f}")

    # Compare with actual DB records
    print()
    print("Step 12: Comparing with existing database records")
    print("-" * 80)

    existing = db.query(SleepPeriod).filter(SleepPeriod.session_id == session_id).all()
    print(f"Already in database: {len(existing)} period(s)\n")

    for p in existing:
        print(f"  {p.period_id}")
        print(f"    {p.started_at.strftime('%Y-%m-%d %H:%M:%S')} → {p.ended_at.strftime('%H:%M:%S')}")
        print(f"    Type: {p.sleep_type:5s} | Duration: {p.duration_min:6.1f} min | Final: {p.is_final}")

    print()
    print("=" * 80)
    print()


def main() -> None:
    init_db()
    db = SessionLocal()

    try:
        # Get the most recent recording session
        session = db.query(RecordingSession).order_by(RecordingSession.started_at.desc()).first()

        if not session:
            print("ERROR: No recording session found in database!")
            return

        print(f"Using session: {session.session_id}")
        analyze_data(session.session_id, db)

    finally:
        db.close()


if __name__ == "__main__":
    main()
