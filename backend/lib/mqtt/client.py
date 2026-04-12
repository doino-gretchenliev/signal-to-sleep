"""
MQTT client for Signal-to-Sleep.

Subscribes to the Sensor Logger topic, ingests data into SQLite,
and provides a command publisher to control Sensor Logger remotely
via its Rule Engine.

Connection architecture:
- Sensor Logger -> WSS (WebSocket + TLS) on port 8884 -> Mosquitto
- Python server -> TCP + TLS on port 8883 -> Mosquitto
- Both authenticate with username/password
- All traffic encrypted with TLS 1.2+
"""

import os
import re
import ssl
import json
import time
import uuid
import logging
import threading
from datetime import datetime
from typing import Any, Callable
from pathlib import Path

import paho.mqtt.client as mqtt

from lib.db.database import SessionLocal, RecordingSession, SensorReading, SleepPeriod

logger: logging.Logger = logging.getLogger("signal-to-sleep.mqtt")

# ── Configuration ──────────────────────────────────────────

MQTT_BROKER: str = os.environ.get("MQTT_BROKER", "localhost")
MQTT_PORT: int = int(os.environ.get("MQTT_PORT", "8883"))
MQTT_TOPIC: str = os.environ.get("MQTT_TOPIC", "sensor-logger")
MQTT_COMMAND_TOPIC: str = os.environ.get("MQTT_COMMAND_TOPIC", "sensor-logger/command")
MQTT_USERNAME: str = os.environ.get("MQTT_USERNAME", "")
MQTT_PASSWORD: str = os.environ.get("MQTT_PASSWORD", "")
MQTT_USE_TLS: bool = os.environ.get("MQTT_USE_TLS", "true").lower() in ("true", "1", "yes")
MQTT_CA_CERT: str = os.environ.get("MQTT_CA_CERT", "/app/mosquitto/certs/ca.crt")
MQTT_QOS: int = 0


class SensorMQTTClient:
    """
    MQTT subscriber that ingests Sensor Logger data and stores it in SQLite.
    Also provides command publishing for controlling Sensor Logger.
    """

    def __init__(self) -> None:
        self.client: mqtt.Client = mqtt.Client(
            client_id="signal-to-sleep-server",
            protocol=mqtt.MQTTv311,
            transport="tcp",
        )

        # ── Authentication ─────────────────────────────────
        if MQTT_USERNAME:
            self.client.username_pw_set(MQTT_USERNAME, MQTT_PASSWORD)
            logger.info(f"MQTT auth configured for user '{MQTT_USERNAME}'")

        # ── TLS Encryption ─────────────────────────────────
        if MQTT_USE_TLS:
            ca_cert_path: str = MQTT_CA_CERT
            if Path(ca_cert_path).exists():
                self.client.tls_set(
                    ca_certs=ca_cert_path,
                    tls_version=ssl.PROTOCOL_TLSv1_2,
                )
                self.client.tls_insecure_set(True)  # Self-signed certs
                logger.info(f"TLS enabled with CA cert: {ca_cert_path}")
            else:
                logger.warning(
                    f"TLS requested but CA cert not found at {ca_cert_path}. "
                    f"Falling back to unencrypted connection."
                )

        self.connected: bool = False
        self.message_count: int = 0
        self.last_message_time: datetime | None = None
        self.active_sessions: dict[str, dict[str, Any]] = {}
        self._status_callbacks: list[Callable[[str, dict[str, Any]], None]] = []
        self._lock: threading.Lock = threading.Lock()

        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.on_message = self._on_message

    # ── Callbacks ──────────────────────────────────────────

    def add_status_callback(self, callback: Callable[[str, dict[str, Any]], None]) -> None:
        self._status_callbacks.append(callback)

    def _notify_status(self, event: str, data: dict[str, Any] | None = None) -> None:
        for cb in self._status_callbacks:
            try:
                cb(event, data or {})
            except Exception as e:
                logger.warning(f"Status callback error: {e}")

    def _on_connect(self, client: mqtt.Client, userdata: Any, flags: dict[str, int], rc: int) -> None:
        if rc == 0:
            logger.info(f"Connected to MQTT broker at {MQTT_BROKER}:{MQTT_PORT}")
            self.connected = True
            client.subscribe(f"{MQTT_TOPIC}/#", qos=MQTT_QOS)
            client.subscribe(MQTT_TOPIC, qos=MQTT_QOS)
            logger.info(f"Subscribed to: {MQTT_TOPIC} and {MQTT_TOPIC}/#")
            self._notify_status("connected")
        else:
            rc_messages: dict[int, str] = {
                1: "incorrect protocol version",
                2: "invalid client identifier",
                3: "server unavailable",
                4: "bad username or password",
                5: "not authorized",
            }
            reason: str = rc_messages.get(rc, f"unknown error code {rc}")
            logger.error(f"MQTT connection refused: {reason}")
            self.connected = False
            self._notify_status("error", {"code": rc, "reason": reason})

    def _on_disconnect(self, client: mqtt.Client, userdata: Any, rc: int) -> None:
        self.connected = False
        if rc != 0:
            logger.warning(f"Unexpected MQTT disconnect (rc={rc}). Will auto-reconnect.")
        self._notify_status("disconnected")

    # ── Message Ingestion ─────────────────────────────────

    def _on_message(self, client: mqtt.Client, userdata: Any, msg: mqtt.MQTTMessage) -> None:
        """Process incoming sensor data from Sensor Logger."""
        logger.debug(f"RAW msg on {msg.topic} len={len(msg.payload)} bytes")
        try:
            payload: dict[str, Any] = json.loads(msg.payload.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            logger.warning(f"Invalid message on {msg.topic}: {e}")
            return

        if "payload" not in payload or "sessionId" not in payload:
            logger.info(
                f"Ignoring non-sensor message on {msg.topic}: "
                f"keys={list(payload.keys())}"
            )
            return

        session_id: str = payload.get("sessionId", "unknown")
        device_id: str = payload.get("deviceId", "unknown")
        message_id: int = payload.get("messageId", 0)
        readings: list[dict[str, Any]] = payload.get("payload", [])

        if not readings:
            return

        # ── Compact sensor summary (debug level) ──
        from collections import Counter
        name_counts = Counter(item.get("name", "?") for item in readings)
        summary = ", ".join(f"{n}:{c}" for n, c in name_counts.most_common())
        logger.debug(f"[{session_id[:8]}] msg#{message_id} items={len(readings)} [{summary}]")

        db = SessionLocal()
        try:
            session: RecordingSession | None = db.query(RecordingSession).filter(
                RecordingSession.session_id == session_id
            ).first()

            if not session:
                session = RecordingSession(
                    session_id=session_id,
                    device_id=device_id,
                    started_at=datetime.utcnow(),
                    last_message_id=message_id,
                    total_messages=1,
                )
                db.add(session)
                logger.info(f"New session started: {session_id} from device {device_id}")
                self._notify_status("new_session", {
                    "session_id": session_id,
                    "device_id": device_id,
                })
            else:
                session.last_message_id = max(session.last_message_id, message_id)
                session.total_messages += 1

            annotations: list[tuple[int, str]] = []  # (time_ns, text)
            sensor_names_seen: set[str] = set()

            for item in readings:
                name: str = item.get("name", "unknown")
                raw_time = item.get("time", 0)
                # Sensor Logger sends timestamps in milliseconds over MQTT,
                # but we store everything in nanoseconds internally.
                # Heuristic: if the value looks like milliseconds (< 1e15),
                # convert to nanoseconds.  If already nanoseconds (>= 1e15),
                # keep as-is (e.g. demo seed data).
                if isinstance(raw_time, float):
                    raw_time = int(raw_time)
                time_ns: int = raw_time * 1_000_000 if raw_time < 1_000_000_000_000_000 else raw_time
                sensor_names_seen.add(name)
                # Sensor Logger nests values under a "values" key;
                # unwrap it so the detector can access fields directly.
                if "values" in item and isinstance(item["values"], dict):
                    values: dict[str, Any] = item["values"]
                else:
                    values: dict[str, Any] = {k: v for k, v in item.items() if k not in ("name", "time")}
                reading = SensorReading(
                    session_id=session_id,
                    sensor_name=name,
                    timestamp_ns=time_ns,
                    values_json=json.dumps(values),
                )
                db.add(reading)

                # Collect sleep annotations for processing after commit.
                name_lower = name.lower()
                if "annot" in name_lower or "label" in name_lower or "marker" in name_lower:
                    logger.info(f"[{session_id}] Annotation item: name={name!r} values={values!r}")
                    # Extract annotation text — try known keys, fall back to first string value
                    ann_text = ""
                    for key in ("text", "label", "annotation", "value", "message", "name"):
                        v = values.get(key)
                        if isinstance(v, str) and v.strip():
                            ann_text = v.strip()
                            break
                    if not ann_text and values:
                        # Fall back: use the first string value found
                        for v in values.values():
                            if isinstance(v, str) and v.strip():
                                ann_text = v.strip()
                                break
                    if ann_text:
                        annotations.append((time_ns, ann_text))

            logger.debug(f"[{session_id}] sensors in message: {sensor_names_seen}")

            db.commit()

            # Process sleep annotations outside the main ingestion loop
            for ann_time_ns, ann_text in annotations:
                try:
                    logger.info(f"[{session_id}] Processing annotation: {ann_text!r}")
                    self._handle_sleep_annotation(db, session_id, ann_time_ns, ann_text)
                except Exception as e:
                    logger.error(f"[{session_id}] Annotation handling failed: {e}", exc_info=True)

            with self._lock:
                self.message_count += 1
                self.last_message_time = datetime.utcnow()
                self.active_sessions[session_id] = {
                    "device_id": device_id,
                    "last_message_id": message_id,
                    "last_seen": datetime.utcnow().isoformat(),
                    "sensors": list(set(item.get("name", "") for item in readings)),
                }

        except Exception as e:
            logger.error(f"Database error processing message: {e}")
            db.rollback()
        finally:
            db.close()

    # ── Manual Sleep Annotations ─────────────────────────

    def _handle_sleep_annotation(
        self,
        db: Any,
        session_id: str,
        time_ns: int,
        text: str,
    ) -> None:
        """
        Handle 'Sleep Start' / 'Sleep Stop' annotations from Sensor Logger.

        Rules:
          Sleep Start:
            - If an open (non-final) sleep period already exists → do nothing
            - Otherwise → create a new manual sleep period (open-ended)
          Sleep Stop:
            - If an open (non-final) sleep period exists → finalize it
            - Otherwise → do nothing
        """
        normalised = re.sub(r"\s+", " ", text.strip().lower())

        if normalised in ("sleep start", "sleepstart", "sleep_start"):
            self._manual_sleep_start(db, session_id, time_ns)
        elif normalised in ("sleep stop", "sleepstop", "sleep_stop",
                            "sleep end", "sleepend", "sleep_end"):
            self._manual_sleep_stop(db, session_id, time_ns)

    def _manual_sleep_start(self, db: Any, session_id: str, time_ns: int) -> None:
        """Start a manual sleep period if none is currently open."""
        from lib.db.database import SleepPeriod

        open_period = (
            db.query(SleepPeriod)
            .filter(
                SleepPeriod.session_id == session_id,
                SleepPeriod.is_final == False,  # noqa: E712
            )
            .first()
        )

        if open_period:
            logger.info(
                f"[{session_id}] Sleep Start annotation ignored — "
                f"period {open_period.period_id} already open "
                f"(source={open_period.source})"
            )
            return

        now = datetime.utcnow()
        period = SleepPeriod(
            period_id=f"sp-{uuid.uuid4().hex[:10]}",
            session_id=session_id,
            start_ns=time_ns,
            end_ns=time_ns,  # will be updated on stop
            started_at=datetime.fromtimestamp(time_ns / 1_000_000_000),
            ended_at=datetime.fromtimestamp(time_ns / 1_000_000_000),
            sleep_type="night",  # will be reclassified on stop
            duration_min=0,
            confidence=1.0,  # manual = full confidence
            is_final=False,
            source="manual",
        )
        db.add(period)
        db.commit()

        logger.info(f"[{session_id}] Manual sleep START → {period.period_id}")
        self._notify_status("manual_sleep_start", {
            "session_id": session_id,
            "period_id": period.period_id,
        })

    def _manual_sleep_stop(self, db: Any, session_id: str, time_ns: int) -> None:
        """Finalize the open sleep period (manual or auto-detected)."""
        from lib.db.database import SleepPeriod

        open_period = (
            db.query(SleepPeriod)
            .filter(
                SleepPeriod.session_id == session_id,
                SleepPeriod.is_final == False,  # noqa: E712
            )
            .order_by(SleepPeriod.start_ns.desc())
            .first()
        )

        if not open_period:
            logger.info(f"[{session_id}] Sleep Stop annotation ignored — no open period")
            return

        open_period.end_ns = time_ns
        open_period.ended_at = datetime.fromtimestamp(time_ns / 1_000_000_000)
        dur_min = (time_ns - open_period.start_ns) / (60 * 1_000_000_000)
        open_period.duration_min = round(dur_min, 1)
        open_period.is_final = True

        # Reclassify night vs nap based on actual duration
        open_period.sleep_type = "night" if dur_min >= 180 else "nap"

        db.commit()

        logger.info(
            f"[{session_id}] Manual sleep STOP → {open_period.period_id} "
            f"({open_period.duration_min}min, {open_period.sleep_type})"
        )
        self._notify_status("manual_sleep_stop", {
            "session_id": session_id,
            "period_id": open_period.period_id,
            "duration_min": open_period.duration_min,
        })

    # ── Command Publishing ────────────────────────────────

    def send_command(self, command: str, payload: dict[str, Any] | None = None) -> bool:
        """Publish a command to the Sensor Logger command topic."""
        message: dict[str, Any] = {"command": command, "timestamp": time.time()}
        if payload:
            message.update(payload)

        result: mqtt.MQTTMessageInfo = self.client.publish(
            MQTT_COMMAND_TOPIC, json.dumps(message), qos=MQTT_QOS,
        )
        logger.info(f"Command sent to {MQTT_COMMAND_TOPIC}: {command}")
        return result.rc == mqtt.MQTT_ERR_SUCCESS

    def cmd_start_recording(self) -> bool:
        return self.send_command("start_recording")

    def cmd_stop_recording(self) -> bool:
        return self.send_command("stop_recording")

    def cmd_pause_recording(self) -> bool:
        return self.send_command("pause_recording")

    def cmd_resume_recording(self) -> bool:
        return self.send_command("resume_recording")

    def cmd_add_annotation(self, text: str) -> bool:
        return self.send_command("add_annotation", {"text": text})

    def cmd_add_tag(self, tag: str) -> bool:
        return self.send_command("add_tag", {"tag": tag})

    def cmd_adjust_sampling(self, sensor: str, rate_hz: float) -> bool:
        return self.send_command("adjust_sampling", {"sensor": sensor, "rate_hz": rate_hz})

    # ── Connection Management ─────────────────────────────

    def start(self) -> None:
        logger.info(f"Connecting to MQTT broker at {MQTT_BROKER}:{MQTT_PORT}...")
        try:
            self.client.connect(MQTT_BROKER, MQTT_PORT, keepalive=60)
            self.client.loop_start()
            logger.info("MQTT client loop started")
        except Exception as e:
            logger.error(f"Failed to connect to MQTT broker: {e}")
            raise

    def stop(self) -> None:
        self.client.loop_stop()
        self.client.disconnect()
        self.connected = False
        logger.info("MQTT client stopped")

    def get_status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "connected": self.connected,
                "broker": f"{MQTT_BROKER}:{MQTT_PORT}",
                "topic": MQTT_TOPIC,
                "command_topic": MQTT_COMMAND_TOPIC,
                "tls_enabled": MQTT_USE_TLS,
                "auth_enabled": bool(MQTT_USERNAME),
                "auth_user": MQTT_USERNAME if MQTT_USERNAME else None,
                "message_count": self.message_count,
                "last_message_time": self.last_message_time.isoformat() if self.last_message_time else None,
                "active_sessions": dict(self.active_sessions),
            }


# Singleton
mqtt_client: SensorMQTTClient = SensorMQTTClient()
