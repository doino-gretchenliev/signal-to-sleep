#!/usr/bin/env python3
"""
Diagnose why a nap period was missed by automatic detection.
Replays the detector logic with verbose output.

Usage:  docker compose exec backend python -m scripts.debug_nap_detection
"""

import json
import numpy as np
from lib.db.database import SessionLocal, SensorReading, SleepPeriod

# ── The nap that was missed ──
NAP_START_NS = 1775984400000000000
NAP_END_NS   = 1775993400000000000

# ── Detection thresholds (from sleep_detector.py) ──
MOVEMENT_THRESHOLD = 0.025   # g
HR_DROP_BPM        = 12.0    # bpm below baseline
ONSET_WINDOW_MIN   = 15      # consecutive calm minutes
BIN_NS             = 60_000_000_000  # 1 minute

db = SessionLocal()

# Find the session
period = db.query(SleepPeriod).filter(
    SleepPeriod.start_ns == NAP_START_NS
).first()
if not period:
    print("Manual nap period not found, trying all periods...")
    for p in db.query(SleepPeriod).all():
        print(f"  {p.period_id}  start={p.start_ns}  end={p.end_ns}  source={getattr(p, 'source', '?')}")
    exit(1)

session_id = period.session_id
print(f"Nap: {period.period_id}  session={session_id}")
print(f"Duration: {(NAP_END_NS - NAP_START_NS) / 60e9:.0f} min")
print()

# ── Pull HR data in nap window ──
hr_readings = []
for ts, vj in (
    db.query(SensorReading.timestamp_ns, SensorReading.values_json)
    .filter(
        SensorReading.session_id == session_id,
        SensorReading.sensor_name.in_(["heartrate", "heart rate", "heartRate"]),
        SensorReading.timestamp_ns >= NAP_START_NS,
        SensorReading.timestamp_ns <= NAP_END_NS,
    )
    .order_by(SensorReading.timestamp_ns)
    .yield_per(2000)
):
    d = json.loads(vj)
    bpm = d.get("bpm") or d.get("heartRate")
    if bpm and 30 < bpm < 220:
        hr_readings.append((ts, float(bpm)))

print(f"HR readings in nap window: {len(hr_readings)}")
if hr_readings:
    bpms = [b for _, b in hr_readings]
    print(f"  min={min(bpms):.1f}  mean={np.mean(bpms):.1f}  max={max(bpms):.1f}")
    print(f"  p25={np.percentile(bpms, 25):.1f}  p50={np.percentile(bpms, 50):.1f}  p75={np.percentile(bpms, 75):.1f}")

# ── Pull ALL HR data for this session (baseline computation) ──
all_hr = []
for ts, vj in (
    db.query(SensorReading.timestamp_ns, SensorReading.values_json)
    .filter(
        SensorReading.session_id == session_id,
        SensorReading.sensor_name.in_(["heartrate", "heart rate", "heartRate"]),
    )
    .order_by(SensorReading.timestamp_ns)
    .yield_per(5000)
):
    d = json.loads(vj)
    bpm = d.get("bpm") or d.get("heartRate")
    if bpm and 30 < bpm < 220:
        all_hr.append(float(bpm))

baseline_hr = float(np.percentile(all_hr, 75)) if all_hr else 70.0
hr_threshold = baseline_hr - HR_DROP_BPM
print(f"\nBaseline HR (p75 of all session data): {baseline_hr:.1f} bpm")
print(f"Sleep threshold (baseline - {HR_DROP_BPM}): {hr_threshold:.1f} bpm")
if hr_readings:
    below = sum(1 for _, b in hr_readings if b < hr_threshold)
    print(f"HR readings below threshold during nap: {below}/{len(hr_readings)} ({100*below/len(hr_readings):.0f}%)")

# ── Pull motion data (sample — don't load all 1.7M) ──
print(f"\n── Motion analysis ──")
mot_count = (
    db.query(SensorReading.timestamp_ns)
    .filter(
        SensorReading.session_id == session_id,
        SensorReading.sensor_name.in_(["wrist motion", "wristMotion", "accelerometer"]),
        SensorReading.timestamp_ns >= NAP_START_NS,
        SensorReading.timestamp_ns <= NAP_END_NS,
    )
    .count()
)
print(f"Motion readings in nap window: {mot_count}")

# Compute per-minute movement stats by streaming
n_bins = int((NAP_END_NS - NAP_START_NS) / BIN_NS) + 1
bin_mags: dict[int, list[float]] = {}

sensor_name_used = None
for ts, sn, vj in (
    db.query(SensorReading.timestamp_ns, SensorReading.sensor_name, SensorReading.values_json)
    .filter(
        SensorReading.session_id == session_id,
        SensorReading.sensor_name.in_(["wrist motion", "wristMotion", "accelerometer"]),
        SensorReading.timestamp_ns >= NAP_START_NS,
        SensorReading.timestamp_ns <= NAP_END_NS,
    )
    .order_by(SensorReading.timestamp_ns)
    .yield_per(5000)
):
    if sensor_name_used is None:
        sensor_name_used = sn
    d = json.loads(vj)
    if sn == "accelerometer":
        x, y, z = d.get("x", 0) or 0, d.get("y", 0) or 0, d.get("z", 0) or 0
        net = abs(float(np.sqrt(x**2 + y**2 + z**2)) - 1.0)
    else:
        # Wrist motion — detector uses ONLY acceleration (no gravity)
        x = d.get("accelerationX", 0) or 0
        y = d.get("accelerationY", 0) or 0
        z = d.get("accelerationZ", 0) or 0
        net = float(np.sqrt(x**2 + y**2 + z**2))

    b = int((ts - NAP_START_NS) / BIN_NS)
    bin_mags.setdefault(b, []).append(net)

print(f"Sensor used: {sensor_name_used}")
print(f"Bins with data: {len(bin_mags)}/{n_bins}")

# Compute per-bin stats
bin_means = {}
for b, mags in sorted(bin_mags.items()):
    bin_means[b] = float(np.mean(mags))

if bin_means:
    all_means = list(bin_means.values())
    print(f"\nPer-minute movement magnitude (mean of bin means):")
    print(f"  min={min(all_means):.4f}g  mean={np.mean(all_means):.4f}g  max={max(all_means):.4f}g")
    print(f"  p25={np.percentile(all_means, 25):.4f}g  p50={np.percentile(all_means, 50):.4f}g  p75={np.percentile(all_means, 75):.4f}g")
    print(f"  Threshold: {MOVEMENT_THRESHOLD}g")
    below_thresh = sum(1 for m in all_means if m < MOVEMENT_THRESHOLD)
    print(f"  Bins below threshold: {below_thresh}/{len(all_means)} ({100*below_thresh/len(all_means):.0f}%)")

# ── Simulate detection: classify bins as calm ──
print(f"\n── Simulated detection ──")

# Bin HR during nap
bin_hr: dict[int, list[float]] = {}
for ts, bpm in hr_readings:
    b = int((ts - NAP_START_NS) / BIN_NS)
    bin_hr.setdefault(b, []).append(bpm)

calm_bins = []
for i in range(n_bins):
    avg_hr = float(np.mean(bin_hr[i])) if i in bin_hr else baseline_hr
    avg_mot = bin_means.get(i, 0.0)
    hr_ok = avg_hr < hr_threshold
    mot_ok = avg_mot < MOVEMENT_THRESHOLD
    calm = hr_ok and mot_ok
    calm_bins.append(calm)

calm_count = sum(calm_bins)
print(f"Calm bins: {calm_count}/{n_bins} ({100*calm_count/n_bins:.0f}%)")

# Find longest consecutive calm run
max_run = 0
cur_run = 0
for c in calm_bins:
    if c:
        cur_run += 1
        max_run = max(max_run, cur_run)
    else:
        cur_run = 0

print(f"Longest consecutive calm run: {max_run} min (need {ONSET_WINDOW_MIN})")

# Breakdown of WHY bins are not calm
hr_fail = 0
mot_fail = 0
both_fail = 0
for i in range(n_bins):
    avg_hr = float(np.mean(bin_hr[i])) if i in bin_hr else baseline_hr
    avg_mot = bin_means.get(i, 0.0)
    hr_ok = avg_hr < hr_threshold
    mot_ok = avg_mot < MOVEMENT_THRESHOLD
    if not hr_ok and not mot_ok:
        both_fail += 1
    elif not hr_ok:
        hr_fail += 1
    elif not mot_ok:
        mot_fail += 1

not_calm = n_bins - calm_count
print(f"\nWhy bins fail ({not_calm} non-calm bins):")
print(f"  HR too high only:       {hr_fail} ({100*hr_fail/max(not_calm,1):.0f}%)")
print(f"  Movement too high only: {mot_fail} ({100*mot_fail/max(not_calm,1):.0f}%)")
print(f"  Both:                   {both_fail} ({100*both_fail/max(not_calm,1):.0f}%)")

# Show first 30 bins in detail
print(f"\n── First 30 minutes detail ──")
print(f"{'Min':>4} {'AvgHR':>6} {'HR<Thr':>6} {'AvgMov':>8} {'Mov<Thr':>7} {'Calm':>5}")
for i in range(min(30, n_bins)):
    avg_hr = float(np.mean(bin_hr[i])) if i in bin_hr else baseline_hr
    avg_mot = bin_means.get(i, 0.0)
    hr_ok = avg_hr < hr_threshold
    mot_ok = avg_mot < MOVEMENT_THRESHOLD
    calm = hr_ok and mot_ok
    print(f"{i:4d} {avg_hr:6.1f} {'  YES' if hr_ok else '   NO':>6} {avg_mot:8.4f} {'  YES' if mot_ok else '   NO':>7} {'  YES' if calm else '   NO':>5}")

db.close()
