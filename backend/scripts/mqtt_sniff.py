#!/usr/bin/env python3
"""
MQTT message sniffer for Signal-to-Sleep.

Subscribes to all topics on the MQTT broker and prints every message
with timestamp, topic, and pretty-printed JSON payload.

Use this to inspect the exact format Sensor Logger sends so you can
paste the output for analysis.

Usage (inside Docker):
    docker compose exec backend python scripts/mqtt_sniff.py

Usage (local, with venv):
    MQTT_BROKER=localhost python scripts/mqtt_sniff.py

Options:
    --raw       Print raw payload without JSON formatting
    --topic T   Subscribe to specific topic (default: # = everything)
    --count N   Stop after N messages (default: unlimited)
"""

import os
import sys
import json
import signal
import argparse
from datetime import datetime

import paho.mqtt.client as mqtt

# ── Config (same env vars as backend) ─────────────────────

MQTT_BROKER = os.environ.get("MQTT_BROKER", "mosquitto")
MQTT_PORT = int(os.environ.get("MQTT_PORT", "1884"))
MQTT_USERNAME = os.environ.get("MQTT_USERNAME", "")
MQTT_PASSWORD = os.environ.get("MQTT_PASSWORD", "")

_running = True
_count = 0
_max_count = 0


def _signal_handler(sig, frame):
    global _running
    _running = False
    print("\nStopping …")


signal.signal(signal.SIGINT, _signal_handler)
signal.signal(signal.SIGTERM, _signal_handler)


def on_connect(client, userdata, flags, rc):
    if rc == 0:
        topic = userdata.get("topic", "#")
        client.subscribe(topic, qos=0)
        print(f"Connected — subscribed to: {topic}")
        print(f"Waiting for messages … (Ctrl+C to stop)\n")
        print("=" * 80)
    else:
        reasons = {
            1: "incorrect protocol version",
            2: "invalid client identifier",
            3: "server unavailable",
            4: "bad username or password",
            5: "not authorized",
        }
        print(f"Connection refused: {reasons.get(rc, f'unknown error {rc}')}")
        sys.exit(1)


def on_message(client, userdata, msg):
    global _count
    _count += 1
    raw_mode = userdata.get("raw", False)

    ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    size = len(msg.payload)

    print(f"\n[{ts}]  topic={msg.topic}  size={size}B  msg#{_count}")
    print("-" * 80)

    try:
        payload = msg.payload.decode("utf-8")
        if raw_mode:
            print(payload)
        else:
            data = json.loads(payload)
            # Print top-level keys summary
            if isinstance(data, dict):
                keys = list(data.keys())
                print(f"Keys: {keys}")
                for k, v in data.items():
                    if k == "payload" and isinstance(v, list):
                        print(f"  {k}: [{len(v)} items]")
                        # Print first 3 items in detail
                        for i, item in enumerate(v[:3]):
                            print(f"    [{i}] {json.dumps(item, indent=6)}")
                        if len(v) > 3:
                            print(f"    … and {len(v) - 3} more items")
                    elif isinstance(v, (dict, list)):
                        print(f"  {k}: {json.dumps(v, indent=4)[:200]}")
                    else:
                        print(f"  {k}: {v}")
            else:
                print(json.dumps(data, indent=2)[:2000])
    except (json.JSONDecodeError, UnicodeDecodeError):
        print(f"[binary/non-JSON] {msg.payload[:200]}")

    print("=" * 80)

    if _max_count and _count >= _max_count:
        print(f"\nReached {_max_count} messages — stopping.")
        client.disconnect()


def main():
    global _max_count

    parser = argparse.ArgumentParser(description="MQTT message sniffer")
    parser.add_argument("--raw", action="store_true", help="Print raw payload")
    parser.add_argument("--topic", default="#", help="Topic to subscribe (default: # = all)")
    parser.add_argument("--count", type=int, default=0, help="Stop after N messages")
    args = parser.parse_args()
    _max_count = args.count

    print(f"Signal-to-Sleep — MQTT Sniffer")
    print(f"  Broker:   {MQTT_BROKER}:{MQTT_PORT}")
    print(f"  Username: {MQTT_USERNAME}")
    print(f"  Topic:    {args.topic}")
    if args.count:
        print(f"  Max msgs: {args.count}")
    print()

    client = mqtt.Client(
        client_id="signal-to-sleep-sniffer",
        protocol=mqtt.MQTTv311,
        transport="websockets",
        userdata={"topic": args.topic, "raw": args.raw},
    )

    if MQTT_USERNAME:
        client.username_pw_set(MQTT_USERNAME, MQTT_PASSWORD)

    client.on_connect = on_connect
    client.on_message = on_message

    print(f"Connecting to {MQTT_BROKER}:{MQTT_PORT} …")
    try:
        client.connect(MQTT_BROKER, MQTT_PORT, keepalive=60)
    except Exception as e:
        print(f"Failed to connect: {e}")
        sys.exit(1)

    client.loop_start()

    # Wait for connection to establish
    import time
    for _ in range(50):
        if client.is_connected():
            break
        time.sleep(0.1)

    if not client.is_connected():
        print("Failed to connect within 5 seconds.")
        client.loop_stop()
        sys.exit(1)

    try:
        while _running:
            time.sleep(0.1)
    except KeyboardInterrupt:
        pass

    client.loop_stop()
    client.disconnect()
    print(f"\nTotal messages received: {_count}")


if __name__ == "__main__":
    main()
