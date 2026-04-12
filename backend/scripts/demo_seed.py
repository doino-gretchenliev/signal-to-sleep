"""
Seed realistic continuous sensor data by publishing through MQTT.

Generates a configurable number of days of data with natural circadian rhythm:
daytime activity → evening wind-down → night sleep → morning wake-up.
Also includes occasional afternoon naps.

Data flows through the full pipeline:
  MQTT publish → Mosquitto → Backend subscriber → SQLite

After seeding, runs sleep detection + analysis so the dashboard is ready.

Modes:
  --seed-only     Seed historical data, detect sleep, run analysis, exit.
  --stream-only   Stream live continuous data in real-time (background).
  (neither)       Seed first, then stream.

Usage:
    python scripts/demo_seed.py --seed-only
    python scripts/demo_seed.py --stream-only
"""

import os
import sys
import ssl
import json
import math
import random
import time
import signal
import argparse
from datetime import datetime, timedelta
from pathlib import Path

import paho.mqtt.client as mqtt

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ── Config ────────────────────────────────────────────────

DEVICE_ID: str = "AppleWatchUltra-DEMO"
SAMPLE_RATE_SEC: int = 5
HISTORY_DAYS: int = 7
SESSION_ID: str = "continuous-demo"

# MQTT config (same env vars as the backend)
MQTT_BROKER: str = os.environ.get("MQTT_BROKER", "mosquitto")
MQTT_PORT: int = int(os.environ.get("MQTT_PORT", "8883"))
MQTT_TOPIC: str = os.environ.get("MQTT_TOPIC", "sensor-logger")
MQTT_USERNAME: str = os.environ.get("MQTT_USERNAME", "")
MQTT_PASSWORD: str = os.environ.get("MQTT_PASSWORD", "")
MQTT_USE_TLS: bool = os.environ.get("MQTT_USE_TLS", "true").lower() in ("true", "1", "yes")
MQTT_CA_CERT: str = os.environ.get("MQTT_CA_CERT", "/app/mosquitto/certs/ca.crt")

# Batching: group N samples into one MQTT message to speed up seeding.
# Keep batches small enough that the backend can ingest each before the next
# arrives — SQLite commits are the bottleneck (~5-10ms each).
PUBLISH_BATCH: int = 20  # samples per MQTT message for historical seed
PUBLISH_QOS: int = 1     # QoS 1 = at-least-once delivery (prevents drops)
PUBLISH_PAUSE: float = 0.005  # seconds between publishes (paces the backend)

_running: bool = True


def _signal_handler(sig: int, frame: object) -> None:
    global _running
    _running = False
    print("\n  Stopping …")


signal.signal(signal.SIGINT, _signal_handler)
signal.signal(signal.SIGTERM, _signal_handler)


# ── MQTT publisher ───────────────────────────────────────

def create_mqtt_client() -> mqtt.Client:
    """Create and connect an MQTT client for publishing seed data."""
    client = mqtt.Client(
        client_id="signal-to-sleep-seeder",
        protocol=mqtt.MQTTv311,
        transport="tcp",
    )

    if MQTT_USERNAME:
        client.username_pw_set(MQTT_USERNAME, MQTT_PASSWORD)

    if MQTT_USE_TLS:
        ca_cert_path = MQTT_CA_CERT
        if Path(ca_cert_path).exists():
            client.tls_set(
                ca_certs=ca_cert_path,
                tls_version=ssl.PROTOCOL_TLSv1_2,
            )
            client.tls_insecure_set(True)  # self-signed certs
        else:
            print(f"  WARNING: CA cert not found at {ca_cert_path}, connecting without TLS")

    print(f"  Connecting to MQTT broker at {MQTT_BROKER}:{MQTT_PORT} …")
    client.connect(MQTT_BROKER, MQTT_PORT, keepalive=60)
    client.loop_start()
    # Give it a moment to connect
    time.sleep(1)
    if not client.is_connected():
        time.sleep(2)
    if not client.is_connected():
        print("  WARNING: MQTT not connected yet, proceeding anyway …")
    else:
        print(f"  Connected to MQTT broker")
    return client


def publish_readings(client: mqtt.Client, session_id: str, device_id: str,
                     message_id: int, readings: list[dict]) -> None:
    """Publish a batch of sensor readings in Sensor Logger MQTT format."""
    message = {
        "sessionId": session_id,
        "deviceId": device_id,
        "messageId": message_id,
        "payload": readings,
    }
    info = client.publish(MQTT_TOPIC, json.dumps(message), qos=PUBLISH_QOS)
    # QoS 1: wait for broker ACK to ensure delivery (timeout 5s)
    if PUBLISH_QOS >= 1:
        info.wait_for_publish(timeout=5)


# ── Circadian rhythm model ────────────────────────────────

def get_activity_state(dt: datetime) -> str:
    """
    Return the expected physiological state for a given wall-clock time.
    States: "active", "sedentary", "wind_down", "sleep", "nap", "waking"
    """
    h = dt.hour + dt.minute / 60.0

    # Sleep: ~11pm to ~7am (varies ±30min)
    if 23.0 <= h or h < 6.5:
        return "sleep"
    if 6.5 <= h < 7.5:
        return "waking"
    # Afternoon nap window (20% chance, 1:30-3:00pm)
    if 13.5 <= h < 15.0:
        if dt.timetuple().tm_yday % 5 == 0:
            return "nap"
    if 21.0 <= h < 23.0:
        return "wind_down"
    if 8.0 <= h < 12.0 or 14.0 <= h < 18.0:
        return "active"
    return "sedentary"


def jitter(val: float, pct: float = 0.05) -> float:
    return val + val * random.uniform(-pct, pct)


# ── Generate one sample ──────────────────────────────────

def generate_sample(t_ns: int, dt: datetime) -> list[dict]:
    """Generate sensor reading dicts for a single time point based on circadian state."""
    state = get_activity_state(dt)
    readings: list[dict] = []

    # ── Heart rate (varies by state + sleep architecture) ──
    hr_profiles = {
        "waking":    (58, 72),
        "wind_down": (60, 70),
        "sedentary": (62, 78),
        "active":    (72, 110),
    }

    if state == "sleep":
        h = dt.hour + dt.minute / 60.0
        sleep_onset_h = 23.0
        hrs_in = (h - sleep_onset_h) % 24
        mins_in = hrs_in * 60
        night_frac = hrs_in / 7.5

        doy = dt.timetuple().tm_yday
        night_rng = random.Random(doy * 137)
        cycle_len = 80 + night_rng.random() * 25
        personal_rhr = 48 + (doy % 7) * 0.8
        onset_latency = 5 + night_rng.random() * 20

        cycle_pos = (mins_in % cycle_len) / cycle_len
        cycle_num = int(mins_in / cycle_len)

        if mins_in < onset_latency:
            hr = random.uniform(personal_rhr + 8, personal_rhr + 18)
            hr -= (mins_in / onset_latency) * 8
        elif abs(cycle_pos - 0.0) < 0.03 and cycle_num > 0 and night_rng.random() < 0.6:
            hr = random.uniform(personal_rhr + 12, personal_rhr + 25)
        elif random.random() < 0.005:
            hr = random.uniform(personal_rhr + 8, personal_rhr + 20)
        elif cycle_pos < 0.40:
            deep_intensity = max(0.15, 1 - cycle_num * 0.3)
            deep_drop = deep_intensity * 8
            base = personal_rhr - deep_drop
            hr = random.uniform(base, base + 5)
            hr += 1.0 * math.sin(2 * math.pi * mins_in / 0.3)
        elif cycle_pos < 0.52:
            hr = random.uniform(personal_rhr - 2, personal_rhr + 6)
            hr += random.uniform(-1.5, 1.5)
        else:
            rem_boost = min(cycle_num * 2.5, 10)
            base = personal_rhr + 2 + rem_boost
            hr = random.uniform(base, base + 8)
            hr += random.uniform(-4, 4)
            hr += 2.5 * math.sin(2 * math.pi * mins_in / 0.15)

        drift = 3 * math.sin(2 * math.pi * night_frac * 0.7)
        rsa = 1.5 * math.sin(2 * math.pi * mins_in / 0.25)
        hr += drift + rsa
        hr = max(38, min(hr, 95))

    elif state == "nap":
        nap_min = (dt.hour - 13) * 60 + dt.minute - 30
        nap_frac = max(0, min(1, nap_min / 90))

        if nap_frac < 0.08:
            hr = random.uniform(58, 66)
        elif 0.2 < nap_frac < 0.45:
            hr = random.uniform(46, 54)
            hr += 1.0 * math.sin(2 * math.pi * nap_min / 0.3)
        elif nap_frac > 0.6:
            hr = random.uniform(52, 62)
            hr += random.uniform(-2, 2)
        else:
            hr = random.uniform(50, 58)
        if 0.45 < nap_frac < 0.5 and random.random() < 0.3:
            hr = random.uniform(62, 72)
        rsa = 1.2 * math.sin(2 * math.pi * nap_min / 0.25)
        hr += rsa

    else:
        lo, hi = hr_profiles[state]
        hr = random.uniform(lo, hi)

    readings.append({
        "name": "heart rate",
        "time": t_ns,
        "values": {"bpm": round(hr, 1)},
    })

    # ── Wrist motion ──────────────────────────────────
    mov_profiles = {
        "waking":    (0.03, 0.15),
        "wind_down": (0.01, 0.06),
        "sedentary": (0.02, 0.08),
        "active":    (0.08, 0.5),
    }

    if state == "sleep":
        h = dt.hour + dt.minute / 60.0
        hrs_in = (h - 23.0) % 24
        mins_in = hrs_in * 60
        doy = dt.timetuple().tm_yday
        night_rng = random.Random(doy * 137)
        cycle_len = 80 + night_rng.random() * 25
        cycle_pos = (mins_in % cycle_len) / cycle_len
        cycle_num = int(mins_in / cycle_len)
        onset_latency = 5 + night_rng.random() * 20

        if mins_in < onset_latency:
            mag = random.uniform(0.02, 0.12)
        elif abs(cycle_pos - 0.0) < 0.03 and cycle_num > 0 and night_rng.random() < 0.6:
            mag = random.uniform(0.08, 0.35)
        elif random.random() < 0.005:
            mag = random.uniform(0.06, 0.2)
        elif cycle_pos < 0.40:
            mag = random.uniform(0.0003, 0.004)
        elif cycle_pos < 0.52:
            mag = random.uniform(0.004, 0.018)
        else:
            mag = random.uniform(0.001, 0.008)
            if random.random() < 0.08:
                mag = random.uniform(0.015, 0.04)
    elif state == "nap":
        nap_min = (dt.hour - 13) * 60 + dt.minute - 30
        nap_frac = max(0, min(1, nap_min / 90))
        if nap_frac < 0.08:
            mag = random.uniform(0.02, 0.08)
        elif 0.2 < nap_frac < 0.45:
            mag = random.uniform(0.0005, 0.005)
        elif 0.45 < nap_frac < 0.5:
            mag = random.uniform(0.03, 0.12)
        else:
            mag = random.uniform(0.001, 0.015)
    else:
        lo, hi = mov_profiles[state]
        mag = random.uniform(lo, hi)

    if state in ("sleep", "nap") and random.random() < 0.003:
        mag = random.uniform(0.1, 0.4)

    a1 = random.uniform(0, 2 * math.pi)
    a2 = random.uniform(0, math.pi)
    ax = mag * math.sin(a2) * math.cos(a1)
    ay = mag * math.sin(a2) * math.sin(a1)
    az = mag * math.cos(a2)
    rot = mag * 0.5

    readings.append({
        "name": "wrist motion",
        "time": t_ns,
        "values": {
            "accelerationX": round(ax, 5), "accelerationY": round(ay, 5), "accelerationZ": round(az, 5),
            "gravityX": round(random.uniform(-0.01, 0.01), 5),
            "gravityY": round(random.uniform(-0.01, 0.01), 5),
            "gravityZ": round(jitter(1.0, 0.005), 5),
            "rotationRateX": round(rot * math.cos(a1), 5),
            "rotationRateY": round(rot * math.sin(a1), 5),
            "rotationRateZ": round(rot * 0.1, 5),
            "quaternionW": round(jitter(1.0, 0.002), 6),
            "quaternionX": round(random.uniform(-0.01, 0.01), 6),
            "quaternionY": round(random.uniform(-0.01, 0.01), 6),
            "quaternionZ": round(random.uniform(-0.01, 0.01), 6),
        },
    })

    # ── Accelerometer ─────────────────────────────────
    readings.append({
        "name": "accelerometer",
        "time": t_ns,
        "values": {"x": round(ax * 0.3, 5), "y": round(ay * 0.3, 5), "z": round(jitter(1.0, 0.002), 5)},
    })

    # ── Microphone ────────────────────────────────────
    noise_profiles = {
        "sleep": -48, "nap": -45, "waking": -30,
        "wind_down": -35, "sedentary": -32, "active": -25,
    }
    readings.append({
        "name": "microphone",
        "time": t_ns,
        "values": {"dBFS": round(jitter(noise_profiles[state], 0.1), 1)},
    })

    return readings


# ── Seed historical data ─────────────────────────────────

def seed_history(client: mqtt.Client) -> str:
    """Seed HISTORY_DAYS of continuous 24/7 data via MQTT. Returns the session_id."""
    now = datetime.now()
    start = now - timedelta(days=HISTORY_DAYS)
    total_seconds = int(HISTORY_DAYS * 86400)
    total_samples = total_seconds // SAMPLE_RATE_SEC

    print(f"  Seeding {HISTORY_DAYS} days of continuous data ({total_samples:,} samples) via MQTT …")
    print(f"  Range: {start.strftime('%b %d %H:%M')} → {now.strftime('%b %d %H:%M')}")
    print(f"  Batch size: {PUBLISH_BATCH} samples per MQTT message")
    print()

    start_ns = int(start.timestamp() * 1e9)
    last_pct_printed = -1
    message_id = 0
    batch_readings: list[dict] = []

    for i in range(total_samples):
        t_ns = start_ns + int(i * SAMPLE_RATE_SEC * 1e9)
        dt = start + timedelta(seconds=i * SAMPLE_RATE_SEC)
        readings = generate_sample(t_ns, dt)
        batch_readings.extend(readings)

        if (i + 1) % PUBLISH_BATCH == 0 or i == total_samples - 1:
            message_id += 1
            publish_readings(client, SESSION_ID, DEVICE_ID, message_id, batch_readings)
            batch_readings = []

            # Pace the backend: pause after every publish so SQLite can commit
            time.sleep(PUBLISH_PAUSE)

            pct = int(((i + 1) / total_samples) * 100)
            tens = pct // 10 * 10
            if tens > 0 and tens != last_pct_printed:
                last_pct_printed = tens
                state = get_activity_state(dt)
                print(f"    [{tens:3d}%]  {dt.strftime('%b %d %H:%M')}  state={state}  ({message_id} msgs)")

    # Wait for backend to finish ingesting the last messages
    print("    Waiting for backend to finish ingestion …")
    time.sleep(5)

    print(f"    [100%]  done — {message_id} MQTT messages published")
    print()
    return SESSION_ID


# ── Post-seed detection & analysis ───────────────────────

def run_detection_and_analysis(session_id: str) -> None:
    """Run sleep detection then analyse each detected period (via direct DB)."""
    from lib.db.database import init_db, SessionLocal, SleepPeriod, SleepAnalysis
    from lib.analysis.sleep_detector import detect_sleep_periods
    from lib.analysis.sleep_analyzer import run_analysis

    init_db()
    db = SessionLocal()

    print("  Running sleep detection …")
    periods = detect_sleep_periods(db, session_id)
    all_periods = db.query(SleepPeriod).filter(SleepPeriod.session_id == session_id).all()

    print(f"  Found {len(all_periods)} sleep period(s)  ({len(periods)} new)")
    print()

    for p in all_periods:
        existing = db.query(SleepAnalysis).filter(SleepAnalysis.period_id == p.period_id).first()
        if existing:
            continue
        try:
            analysis = run_analysis(db, session_id, period=p)
            print(f"    {p.period_id}  {p.sleep_type:5s}  "
                  f"{p.started_at.strftime('%b %d %H:%M')}–{p.ended_at.strftime('%H:%M')}  "
                  f"{p.duration_min:.0f}min  "
                  f"recovery={analysis.recovery_score:.0f} quality={analysis.sleep_quality_score:.0f}")
        except Exception as e:
            print(f"    {p.period_id}: analysis failed — {e}")
    print()
    db.close()

    # Notify the dashboard to refresh via the backend's WebSocket broadcast
    try:
        import urllib.request
        urllib.request.urlopen(
            urllib.request.Request("http://127.0.0.1:8080/api/notify-refresh", method="POST"),
            timeout=3,
        )
        print("  Dashboard notified to refresh.")
    except Exception:
        pass  # backend may not be reachable from inside container via localhost


# ── Live stream ──────────────────────────────────────────

def run_stream(client: mqtt.Client) -> None:
    """Stream continuous data in real-time via MQTT."""
    print("  Streaming live data via MQTT (Ctrl+C / SIGTERM to stop) …")
    print()

    message_id = 0
    while _running:
        now = datetime.now()
        t_ns = int(time.time() * 1e9)
        readings = generate_sample(t_ns, now)
        message_id += 1
        publish_readings(client, SESSION_ID, DEVICE_ID, message_id, readings)

        if message_id % 120 == 0:
            state = get_activity_state(now)
            print(f"    [{message_id:6d}]  {now.strftime('%H:%M:%S')}  state={state}")

        time.sleep(SAMPLE_RATE_SEC)

    print(f"\n  Stopped. {message_id} live messages published.")


# ── Main ─────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Signal-to-Sleep demo seeder")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--seed-only", action="store_true")
    group.add_argument("--stream-only", action="store_true")
    args = parser.parse_args()

    mode = "stream only" if args.stream_only else ("seed only" if args.seed_only else "seed + stream")
    print(f"Signal-to-Sleep  ·  Demo Seeder  [{mode}]")
    print(f"  Publishing via MQTT → {MQTT_BROKER}:{MQTT_PORT}/{MQTT_TOPIC}")
    print()

    # Connect to MQTT broker
    client = create_mqtt_client()

    try:
        if not args.stream_only:
            seed_history(client)
            # Detection & analysis still use direct DB (post-ingest)
            run_detection_and_analysis(SESSION_ID)

        if args.seed_only:
            print("  Done.")
            return

        run_stream(client)
    finally:
        client.loop_stop()
        client.disconnect()


if __name__ == "__main__":
    main()
