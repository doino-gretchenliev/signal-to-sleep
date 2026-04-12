"""
Generate realistic test data simulating a night of sleep recorded on Apple Watch Ultra.

Publishes data via MQTT (mimicking Sensor Logger) to the Mosquitto broker.

Simulates ~8 hours of sleep with:
- Heart rate patterns matching sleep stages (from Watch)
- Wrist motion with 9-axis data (from Watch)
- Accelerometer (from iPhone on nightstand)
- Microphone levels for ambient noise (from iPhone)
- Pedometer step counts during awake periods (from Watch)
- Barometer pressure readings (from Watch)

Connects via TCP+TLS to port 8883 with username/password auth.
(Sensor Logger connects via WSS to port 8884.)

Usage:
  python generate_test_data.py [host] [port] [topic] [username] [password] [--no-tls]
"""

import os
import ssl
import time
import json
import random
import math
import uuid
import sys
from pathlib import Path

import paho.mqtt.client as mqtt

# Configuration from args or environment
BROKER_HOST = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("MQTT_BROKER", "localhost")
BROKER_PORT = int(sys.argv[2]) if len(sys.argv) > 2 else int(os.environ.get("MQTT_PORT", "8883"))
TOPIC = sys.argv[3] if len(sys.argv) > 3 else os.environ.get("MQTT_TOPIC", "sensor-logger")
USERNAME = sys.argv[4] if len(sys.argv) > 4 else os.environ.get("MQTT_USERNAME", "")
PASSWORD = sys.argv[5] if len(sys.argv) > 5 else os.environ.get("MQTT_PASSWORD", "")
USE_TLS = "--no-tls" not in sys.argv
CA_CERT = os.environ.get("MQTT_CA_CERT", "mosquitto/certs/ca.crt")

SESSION_ID = f"test-{uuid.uuid4().hex[:8]}"
DEVICE_ID = "AppleWatchUltra-SIM"
SLEEP_DURATION_HOURS = 8
SAMPLE_RATE_SEC = 5
START_TIME_NS = int(time.time() * 1e9) - int(SLEEP_DURATION_HOURS * 3600 * 1e9)

print(f"Signal-to-Sleep MQTT Test Data Generator")
print(f"  Broker:   {BROKER_HOST}:{BROKER_PORT}")
print(f"  Topic:    {TOPIC}")
print(f"  TLS:      {'Enabled' if USE_TLS else 'Disabled'}")
print(f"  Auth:     {'Yes (' + USERNAME + ')' if USERNAME else 'No'}")
print(f"  Session:  {SESSION_ID}")
print(f"  Duration: {SLEEP_DURATION_HOURS}h of simulated sleep")
print()


def sleep_stage_at(minutes_elapsed: float) -> str:
    """Simulate realistic 90-min sleep stage cycling."""
    cycle_pos = (minutes_elapsed % 90) / 90
    cycle_num = int(minutes_elapsed / 90)

    if minutes_elapsed < 10:
        return "light"
    if cycle_pos < 0.15:
        return "light"
    elif cycle_pos < 0.35:
        return "deep" if cycle_num < 3 else "light"
    elif cycle_pos < 0.55:
        return "deep" if cycle_num < 2 else "light"
    elif cycle_pos < 0.75:
        return "light"
    else:
        return "rem" if cycle_num >= 1 else "light"


def noise(val, pct=0.05):
    return val + val * random.uniform(-pct, pct)


# Connect to broker with TLS + auth
client = mqtt.Client(client_id="test-data-gen", transport="tcp")

if USERNAME:
    client.username_pw_set(USERNAME, PASSWORD)

if USE_TLS:
    ca_path = Path(CA_CERT)
    if ca_path.exists():
        client.tls_set(ca_certs=str(ca_path), tls_version=ssl.PROTOCOL_TLSv1_2)
        client.tls_insecure_set(True)  # Accept self-signed certs
        print(f"TLS enabled with CA cert: {ca_path}")
    else:
        print(f"WARNING: CA cert not found at {ca_path}, connecting without TLS")

try:
    client.connect(BROKER_HOST, BROKER_PORT, keepalive=60)
    client.loop_start()
    print(f"Connected to MQTT broker")
except Exception as e:
    print(f"Failed to connect: {e}")
    print(f"Make sure Mosquitto is running on port {BROKER_PORT}")
    if USE_TLS:
        print(f"  For unencrypted testing: add --no-tls flag")
    sys.exit(1)

total_samples = int(SLEEP_DURATION_HOURS * 3600 / SAMPLE_RATE_SEC)
batch_size = 20
message_id = 0
payload_batch = []

for i in range(total_samples):
    t_ns = START_TIME_NS + int(i * SAMPLE_RATE_SEC * 1e9)
    minutes = i * SAMPLE_RATE_SEC / 60
    stage = sleep_stage_at(minutes)

    # Occasional awakenings
    if random.random() < 0.015:
        stage = "awake"

    # Heart rate based on sleep stage
    hr_base = {"awake": 72, "light": 58, "deep": 50, "rem": 64}[stage]
    hr = noise(hr_base, 0.08)
    hr += 2 * math.sin(2 * math.pi * minutes / 0.25)

    # Movement magnitude based on stage
    if stage == "awake":
        accel_mag = random.uniform(0.05, 0.3)
    elif stage == "light":
        accel_mag = random.uniform(0.005, 0.03)
    elif stage == "rem":
        accel_mag = random.uniform(0.002, 0.015)
    else:
        accel_mag = random.uniform(0.001, 0.008)

    angle1 = random.uniform(0, 2 * math.pi)
    angle2 = random.uniform(0, math.pi)
    ax = accel_mag * math.sin(angle2) * math.cos(angle1)
    ay = accel_mag * math.sin(angle2) * math.sin(angle1)
    az = accel_mag * math.cos(angle2)

    # ── Watch sensors ──

    # Heart rate (Watch)
    payload_batch.append({"name": "heartrate", "time": t_ns, "bpm": round(hr, 1)})

    # Wrist motion (Watch) — 9-axis
    rot_rate = accel_mag * 0.5
    payload_batch.append({
        "name": "wrist motion", "time": t_ns,
        "accelerationX": round(ax, 5), "accelerationY": round(ay, 5), "accelerationZ": round(az, 5),
        "gravityX": round(random.uniform(-0.01, 0.01), 5),
        "gravityY": round(random.uniform(-0.01, 0.01), 5),
        "gravityZ": round(noise(1.0, 0.005), 5),
        "rotationRateX": round(rot_rate * math.cos(angle1), 5),
        "rotationRateY": round(rot_rate * math.sin(angle1), 5),
        "rotationRateZ": round(rot_rate * 0.1, 5),
        "quaternionW": round(noise(1.0, 0.002), 6),
        "quaternionX": round(random.uniform(-0.01, 0.01), 6),
        "quaternionY": round(random.uniform(-0.01, 0.01), 6),
        "quaternionZ": round(random.uniform(-0.01, 0.01), 6),
    })

    # Pedometer (Watch) — steps during awake periods
    if stage == "awake" and random.random() < 0.1:
        payload_batch.append({"name": "pedometer", "time": t_ns, "steps": random.randint(1, 5)})

    # ── iPhone sensors ──

    # Accelerometer (iPhone on nightstand — very little movement)
    payload_batch.append({
        "name": "accelerometer", "time": t_ns,
        "x": round(ax * 0.05, 5), "y": round(ay * 0.05, 5), "z": round(noise(1.0, 0.002), 5),
    })

    # Microphone (iPhone)
    noise_base = {"awake": -30, "light": -45, "deep": -50, "rem": -42}[stage]
    payload_batch.append({"name": "microphone", "time": t_ns, "dBFS": round(noise(noise_base, 0.1), 1)})

    # Barometer (every ~60 seconds)
    if i % 12 == 0:
        payload_batch.append({
            "name": "barometer", "time": t_ns,
            "pressure": round(1013.25 + random.uniform(-0.5, 0.5), 2),
            "relativeAltitude": 0.0,
        })

    # Send batch via MQTT
    if len(payload_batch) >= batch_size * 5:
        message = {
            "messageId": message_id,
            "sessionId": SESSION_ID,
            "deviceId": DEVICE_ID,
            "payload": payload_batch,
        }
        result = client.publish(TOPIC, json.dumps(message), qos=0)

        if message_id % 50 == 0:
            pct = int((i / total_samples) * 100)
            print(f"  [{pct:3d}%] Published message {message_id} ({minutes:.0f} min)")

        message_id += 1
        payload_batch = []
        time.sleep(0.01)  # Small delay to avoid overwhelming broker

# Send remaining
if payload_batch:
    message = {"messageId": message_id, "sessionId": SESSION_ID, "deviceId": DEVICE_ID, "payload": payload_batch}
    client.publish(TOPIC, json.dumps(message), qos=0)
    message_id += 1

# Wait for messages to be delivered
time.sleep(1)
client.loop_stop()
client.disconnect()

print(f"\nDone! Published {message_id} messages to topic '{TOPIC}'")
print(f"Session ID: {SESSION_ID}")
print(f"\nOpen the dashboard to analyze this session.")
