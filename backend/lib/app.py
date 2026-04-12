"""
FastAPI application: routes, lifecycle, and dashboard.

All API routes are defined here. The app is imported by server.py
which handles the uvicorn startup.
"""

import os
import json
import time
import uuid as _uuid
import logging
import asyncio
import threading
from datetime import datetime
from contextlib import asynccontextmanager
from collections.abc import AsyncGenerator
from typing import Any

from fastapi import FastAPI, Depends, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, StreamingResponse
from sqlalchemy.orm import Session as DBSession
from sqlalchemy import text

from lib.db.database import (
    init_db, get_db, engine, SessionLocal,
    RecordingSession, SensorReading, SleepPeriod, SleepAnalysis,
)
from lib.analysis.sleep_analyzer import run_analysis
from lib.analysis.sleep_detector import detect_sleep_periods, run_detection_for_all_sessions
from lib.mqtt.sensors import SENSOR_REGISTRY, SLEEP_SENSORS, WATCH_SENSORS
from lib.mqtt.client import (
    mqtt_client, MQTT_BROKER, MQTT_PORT, MQTT_TOPIC, MQTT_COMMAND_TOPIC,
)

logger: logging.Logger = logging.getLogger("signal-to-sleep")


# ──────────────────────────────────────────────
# WebSocket connection manager
# ──────────────────────────────────────────────

class WSManager:
    """Manages active WebSocket connections and broadcasts JSON events."""

    def __init__(self) -> None:
        self._connections: list[WebSocket] = []

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self._connections.append(ws)
        logger.info(f"WS client connected ({len(self._connections)} total)")

    def disconnect(self, ws: WebSocket) -> None:
        self._connections.remove(ws)
        logger.info(f"WS client disconnected ({len(self._connections)} total)")

    async def broadcast(self, event: dict[str, Any]) -> None:
        """Send a JSON event to all connected clients."""
        dead: list[WebSocket] = []
        payload = json.dumps(event)
        for ws in self._connections:
            try:
                await ws.send_text(payload)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self._connections.remove(ws)


ws_manager = WSManager()


def _get_active_sleep() -> dict[str, Any] | None:
    """Return info about the current open (non-final) sleep period, if any."""
    try:
        db = SessionLocal()
        period = (
            db.query(SleepPeriod)
            .filter(SleepPeriod.is_final == False)  # noqa: E712
            .order_by(SleepPeriod.start_ns.desc())
            .first()
        )
        if period:
            dur_min = (time.time() * 1e9 - period.start_ns) / (60 * 1e9)
            return {
                "period_id": period.period_id,
                "source": getattr(period, "source", "auto"),
                "started_at": period.started_at.isoformat() + "Z",
                "duration_min": round(dur_min, 1),
            }
        return None
    except Exception:
        return None
    finally:
        db.close()


def _build_health_event() -> dict[str, Any]:
    """Build a health_update payload from current system state."""
    try:
        db_ok = _check_db()["status"] == "up"
    except Exception:
        db_ok = False
    try:
        mqtt_info = mqtt_client.get_status()
    except Exception:
        mqtt_info = {}
    return {
        "type": "health_update",
        "db": db_ok,
        "mqtt": mqtt_info.get("connected", False),
        "mqtt_topic": mqtt_info.get("topic", MQTT_TOPIC),
        "message_count": mqtt_info.get("message_count", 0),
        "uptime_sec": round(time.time() - _start_time, 1),
        "version": "3.0.0",
        "active_sleep": _get_active_sleep(),
    }


_event_loop: asyncio.AbstractEventLoop | None = None


def _broadcast_sync(event: dict[str, Any]) -> None:
    """Fire-and-forget broadcast from sync code (detection loop, MQTT thread, etc.)."""
    loop = _event_loop
    if loop is None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return  # no event loop — skip

    if loop.is_running():
        # Called from a different thread (e.g. MQTT callback)
        asyncio.run_coroutine_threadsafe(ws_manager.broadcast(event), loop)
    else:
        loop.create_task(ws_manager.broadcast(event))


WEB_PORT: int = int(os.environ.get("WEB_PORT", "8080"))


def _get_host_ip() -> str:
    """Best-effort detection of the host machine's LAN IP for Sensor Logger config."""
    import socket
    try:
        # Connect to an external address to find our LAN-facing IP
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "localhost"

# Background detection interval (seconds). 0 = disabled.
# 5 min is fine — onset requires 15 consecutive calm minutes anyway.
DETECT_INTERVAL_SEC: int = int(os.environ.get("DETECT_INTERVAL_SEC", "300"))

# Auto-analysis: hour of day (24h format). Safety-net for any missed analyses.
AUTO_ANALYZE_HOUR: int = int(os.environ.get("AUTO_ANALYZE_HOUR", "0"))

_detection_task: asyncio.Task[None] | None = None
_analysis_scheduler_task: asyncio.Task[None] | None = None
_health_broadcast_task: asyncio.Task[None] | None = None

HEALTH_BROADCAST_SEC: int = 10  # push health to all WS clients every 10s


# ──────────────────────────────────────────────
# App Lifecycle
# ──────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Start MQTT on boot, stop on shutdown."""
    global _detection_task, _analysis_scheduler_task, _health_broadcast_task, _event_loop

    _event_loop = asyncio.get_running_loop()

    init_db()
    logger.info("Database initialized")

    def _on_mqtt_status(event: str, data: dict[str, Any]) -> None:
        """Forward manual sleep events to WebSocket clients."""
        if event in ("manual_sleep_start", "manual_sleep_stop"):
            _broadcast_sync({"type": "data_refresh", "source": event, **data})
            _broadcast_sync(_build_health_event())

    mqtt_client.add_status_callback(_on_mqtt_status)

    try:
        mqtt_client.start()
        logger.info(f"MQTT subscriber listening on {MQTT_BROKER}:{MQTT_PORT} topic={MQTT_TOPIC}")
    except Exception as e:
        logger.warning(f"MQTT connection failed: {e}. Server running without live data.")

    # Periodic sleep detection
    if DETECT_INTERVAL_SEC:
        _detection_task = asyncio.create_task(_detection_loop())
        logger.info(f"Sleep detection running every {DETECT_INTERVAL_SEC}s")

    # Daily auto-analysis
    if AUTO_ANALYZE_HOUR:
        _analysis_scheduler_task = asyncio.create_task(_auto_analysis_loop())
        logger.info(f"Auto-analysis scheduled daily at {AUTO_ANALYZE_HOUR:02d}:00")

    # Periodic health broadcast over WebSocket
    _health_broadcast_task = asyncio.create_task(_health_broadcast_loop())

    logger.info("Signal-to-Sleep ready")
    logger.info(f"  Dashboard:        http://0.0.0.0:{WEB_PORT}")
    logger.info(f"  MQTT Topic:       {MQTT_TOPIC}")
    # Print Sensor Logger connection info
    _host_ip = _get_host_ip()
    logger.info(f"  ── Sensor Logger MQTT Settings ──")
    logger.info(f"  Protocol:         wss (WebSocket + TLS)")
    logger.info(f"  Host:             {_host_ip}")
    logger.info(f"  Port:             8884")
    logger.info(f"  Topic:            {MQTT_TOPIC}")
    logger.info(f"  Username:         {os.environ.get('MQTT_USERNAME', '')}")
    logger.info(f"  Password:         {os.environ.get('MQTT_PASSWORD', '')}")
    logger.info(f"  URL:              wss://{_host_ip}:8884")
    logger.info(f"  TLS:              Accept self-signed certs")

    yield

    for task in (_detection_task, _analysis_scheduler_task, _health_broadcast_task):
        if task:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    mqtt_client.stop()
    logger.info("Shutdown complete")


# ──────────────────────────────────────────────
# Background loops
# ──────────────────────────────────────────────

async def _health_broadcast_loop() -> None:
    """Push health status to all WS clients periodically."""
    while True:
        await asyncio.sleep(HEALTH_BROADCAST_SEC)
        try:
            await ws_manager.broadcast(_build_health_event())
        except Exception as e:
            logger.debug(f"Health broadcast error: {e}")


async def _detection_loop() -> None:
    """Periodically scan for new sleep periods."""
    while True:
        await asyncio.sleep(DETECT_INTERVAL_SEC)
        try:
            from lib.db.database import SessionLocal
            db = SessionLocal()
            try:
                new = run_detection_for_all_sessions(db)
                if new:
                    logger.info(f"Detection loop: {len(new)} new sleep period(s)")
                    _broadcast_sync({
                        "type": "periods_detected",
                        "count": len(new),
                        "period_ids": [p.period_id for p in new],
                    })
                    # Auto-analyze new finalized periods
                    for period in new:
                        if period.is_final:
                            existing = db.query(SleepAnalysis).filter(
                                SleepAnalysis.period_id == period.period_id
                            ).first()
                            if not existing:
                                run_analysis(db, period.session_id, period=period)
                                logger.info(f"Auto-analyzed {period.period_id}")
                                _broadcast_sync({
                                    "type": "analysis_complete",
                                    "period_id": period.period_id,
                                })
            finally:
                db.close()
        except Exception as e:
            logger.error(f"Detection loop error: {e}")


async def _auto_analysis_loop() -> None:
    """Run analysis on all un-analyzed periods at AUTO_ANALYZE_HOUR every day."""
    import datetime
    while True:
        now = datetime.datetime.now()
        target = now.replace(hour=AUTO_ANALYZE_HOUR, minute=0, second=0, microsecond=0)
        if target <= now:
            target += datetime.timedelta(days=1)
        await asyncio.sleep((target - now).total_seconds())

        logger.info("Auto-analysis: running …")
        try:
            _analyze_all_pending()
        except Exception as e:
            logger.error(f"Auto-analysis failed: {e}")


def _analyze_all_pending() -> list[str]:
    """Analyze every finalized sleep period without an analysis."""
    from lib.db.database import SessionLocal
    db: DBSession = SessionLocal()
    analyzed: list[str] = []
    try:
        periods = db.query(SleepPeriod).filter(SleepPeriod.is_final == True).all()
        for p in periods:
            existing = db.query(SleepAnalysis).filter(
                SleepAnalysis.period_id == p.period_id
            ).first()
            if not existing:
                logger.info(f"Auto-analyzing period {p.period_id}")
                run_analysis(db, p.session_id, period=p)
                analyzed.append(p.period_id)
                _broadcast_sync({
                    "type": "analysis_complete",
                    "period_id": p.period_id,
                })
    finally:
        db.close()
    return analyzed


# ──────────────────────────────────────────────
# Health check helpers
# ──────────────────────────────────────────────

def _check_db() -> dict[str, Any]:
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return {"status": "up"}
    except Exception as e:
        return {"status": "down", "error": str(e)}


def _check_mqtt() -> dict[str, Any]:
    if mqtt_client.connected:
        return {"status": "up", "broker": f"{MQTT_BROKER}:{MQTT_PORT}"}
    return {"status": "down", "broker": f"{MQTT_BROKER}:{MQTT_PORT}"}


# ──────────────────────────────────────────────
# App Factory
# ──────────────────────────────────────────────

def create_app() -> FastAPI:
    app = FastAPI(title="Signal-to-Sleep", version="3.0.0", lifespan=lifespan)
    templates: Jinja2Templates = Jinja2Templates(directory="templates")

    # ── Health ─────────────────────────────────────────

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        db_status = _check_db()
        mqtt_status_info = _check_mqtt()
        healthy = db_status["status"] == "up"
        result: dict[str, Any] = {
            "status": "healthy" if healthy else "unhealthy",
            "version": "3.0.0",
            "uptime_sec": round(time.time() - _start_time, 1),
            "checks": {"database": db_status, "mqtt": mqtt_status_info},
            "config": {
                "auto_analyze": f"{AUTO_ANALYZE_HOUR:02d}:00 daily" if AUTO_ANALYZE_HOUR else None,
                "detect_interval_sec": DETECT_INTERVAL_SEC,
                "web_port": WEB_PORT,
            },
        }
        if not healthy:
            raise HTTPException(status_code=503, detail=result)
        return result

    # ── MQTT Status ────────────────────────────────────

    @app.get("/api/mqtt/status")
    def mqtt_status() -> dict[str, Any]:
        return mqtt_client.get_status()

    # ── Sleep Periods (primary data model) ─────────────

    @app.get("/api/sleep-periods")
    def list_sleep_periods(
        db: DBSession = Depends(get_db),
        start: str | None = None,
        end: str | None = None,
    ) -> list[dict[str, Any]]:
        """
        List detected sleep periods.
        Filter by ISO-8601 start/end (day-level granularity from the UI).
        """
        query = db.query(SleepPeriod)
        if start:
            try:
                start_dt = datetime.fromisoformat(start.replace("Z", "+00:00")).replace(tzinfo=None)
                query = query.filter(SleepPeriod.started_at >= start_dt)
            except ValueError:
                pass
        if end:
            try:
                end_dt = datetime.fromisoformat(end.replace("Z", "+00:00")).replace(tzinfo=None)
                query = query.filter(SleepPeriod.started_at <= end_dt)
            except ValueError:
                pass

        periods = query.order_by(SleepPeriod.started_at.desc()).all()
        result: list[dict[str, Any]] = []
        for p in periods:
            has_analysis = db.query(SleepAnalysis).filter(
                SleepAnalysis.period_id == p.period_id
            ).first() is not None
            result.append({
                "period_id": p.period_id,
                "session_id": p.session_id,
                "sleep_type": p.sleep_type,
                "started_at": p.started_at.isoformat() + "Z",
                "ended_at": p.ended_at.isoformat() + "Z" if p.ended_at else None,
                "duration_min": p.duration_min,
                "confidence": p.confidence,
                "is_final": p.is_final,
                "source": getattr(p, "source", "auto"),
                "has_analysis": has_analysis,
            })
        return result

    @app.get("/api/analysis/{period_id}")
    def get_analysis(period_id: str, db: DBSession = Depends(get_db)) -> dict[str, Any]:
        analysis: SleepAnalysis | None = db.query(SleepAnalysis).filter(
            SleepAnalysis.period_id == period_id
        ).first()
        if not analysis:
            raise HTTPException(404, "No analysis found for this period.")

        return {
            "period_id": period_id,
            "analyzed_at": analysis.analyzed_at.isoformat() + "Z",
            "total_duration_min": analysis.total_duration_min,
            "awake_min": analysis.awake_min,
            "light_sleep_min": analysis.light_sleep_min,
            "deep_sleep_min": analysis.deep_sleep_min,
            "rem_sleep_min": analysis.rem_sleep_min,
            "avg_heart_rate": analysis.avg_heart_rate,
            "min_heart_rate": analysis.min_heart_rate,
            "max_heart_rate": analysis.max_heart_rate,
            "avg_respiratory_rate": analysis.avg_respiratory_rate,
            "avg_hrv": analysis.avg_hrv,
            "sleep_efficiency": analysis.sleep_efficiency,
            "recovery_score": analysis.recovery_score,
            "sleep_quality_score": analysis.sleep_quality_score,
            "heart_rate_series": json.loads(analysis.heart_rate_series or "[]"),
            "movement_series": json.loads(analysis.movement_series or "[]"),
            "sleep_stage_series": json.loads(analysis.sleep_stage_series or "[]"),
            "respiratory_series": json.loads(analysis.respiratory_series or "[]"),
            "noise_series": json.loads(getattr(analysis, "noise_series", None) or "[]"),
            "data_coverage": getattr(analysis, "data_coverage", 1.0) or 1.0,
        }

    # ── Background analysis runner ─────────────────────
    _analyzing: set[str] = set()  # period_ids currently being analyzed

    def _run_analysis_background(period_id: str, session_id: str, source: str) -> None:
        """Run analysis in a background thread with its own DB session."""
        try:
            db = SessionLocal()
            try:
                period = db.query(SleepPeriod).filter(SleepPeriod.period_id == period_id).first()
                if not period:
                    logger.error(f"[BG Analysis] Period {period_id} not found")
                    return

                # Clear old analysis
                db.query(SleepAnalysis).filter(SleepAnalysis.period_id == period_id).delete()
                db.commit()

                logger.info(f"[BG Analysis] Starting analysis for {period_id}")
                analysis = run_analysis(db, session_id, period=period)
                logger.info(
                    f"[BG Analysis] Complete: {period_id} "
                    f"recovery={analysis.recovery_score} quality={analysis.sleep_quality_score}"
                )

                # Broadcast completion via WebSocket
                _broadcast_sync({
                    "type": "analysis_complete",
                    "period_id": period_id,
                    "recovery_score": analysis.recovery_score,
                    "sleep_quality_score": analysis.sleep_quality_score,
                    "sleep_efficiency": analysis.sleep_efficiency,
                    "total_duration_min": analysis.total_duration_min,
                })

            finally:
                db.close()
        except Exception as e:
            logger.error(f"[BG Analysis] Failed for {period_id}: {e}", exc_info=True)
        finally:
            _analyzing.discard(period_id)

    @app.post("/api/analyze/{period_id}", status_code=201)
    async def analyze_period(period_id: str, db: DBSession = Depends(get_db)) -> dict[str, Any]:
        """Kick off analysis in background. Returns immediately."""
        period = db.query(SleepPeriod).filter(SleepPeriod.period_id == period_id).first()
        if not period:
            raise HTTPException(404, f"Sleep period '{period_id}' not found")

        if period_id in _analyzing:
            return {"status": "already_running", "period_id": period_id}

        _analyzing.add(period_id)
        t = threading.Thread(
            target=_run_analysis_background,
            args=(period_id, period.session_id, getattr(period, "source", "auto")),
            daemon=True,
        )
        t.start()

        return {"status": "accepted", "period_id": period_id}

    @app.get("/api/analyze/{period_id}/stream")
    async def analyze_period_stream(period_id: str) -> dict[str, Any]:
        """Redirect SSE callers to the async POST endpoint."""
        # Legacy SSE endpoint — just trigger analysis via POST path
        from starlette.responses import RedirectResponse
        return RedirectResponse(url=f"/api/analyze/{period_id}", status_code=307)

    @app.post("/api/detect")
    def trigger_detection(db: DBSession = Depends(get_db)) -> dict[str, Any]:
        """Manually trigger sleep detection across all sessions."""
        new = run_detection_for_all_sessions(db)
        return {"status": "ok", "new_periods": len(new), "period_ids": [p.period_id for p in new]}

    @app.post("/api/analyze-all")
    def analyze_all() -> dict[str, Any]:
        analyzed = _analyze_all_pending()
        return {"status": "ok", "analyzed": analyzed, "count": len(analyzed)}

    @app.post("/api/notify-refresh")
    async def notify_refresh() -> dict[str, Any]:
        """Broadcast a refresh event so the dashboard reloads data."""
        await ws_manager.broadcast({"type": "data_refresh"})
        return {"status": "ok"}

    # ── Manual Sleep Control ─────────────────────────

    @app.post("/api/sleep/start")
    async def manual_sleep_start(db: DBSession = Depends(get_db)) -> dict[str, Any]:
        """Start a manual sleep session. Uses the most recent recording session."""

        # Find the most recent recording session
        session = (
            db.query(RecordingSession)
            .order_by(RecordingSession.started_at.desc())
            .first()
        )
        if not session:
            return {"status": "error", "message": "No recording session active"}

        # Check if there's already an open period
        open_period = (
            db.query(SleepPeriod)
            .filter(SleepPeriod.is_final == False)  # noqa: E712
            .first()
        )
        if open_period:
            return {
                "status": "ignored",
                "message": "Sleep session already in progress",
                "period_id": open_period.period_id,
            }

        now_ns = int(time.time() * 1e9)
        now_dt = datetime.utcnow()
        period = SleepPeriod(
            period_id=f"sp-{_uuid.uuid4().hex[:10]}",
            session_id=session.session_id,
            start_ns=now_ns,
            end_ns=now_ns,
            started_at=now_dt,
            ended_at=now_dt,
            sleep_type="night",
            duration_min=0,
            confidence=1.0,
            is_final=False,
            source="manual",
        )
        db.add(period)
        db.commit()

        logger.info(f"[API] Manual sleep START → {period.period_id}")
        await ws_manager.broadcast({
            "type": "data_refresh",
            "source": "manual_sleep_start",
            "period_id": period.period_id,
        })
        # Push health immediately so all clients see the active sleep
        await ws_manager.broadcast(_build_health_event())
        return {"status": "ok", "period_id": period.period_id}

    @app.post("/api/sleep/stop")
    async def manual_sleep_stop(db: DBSession = Depends(get_db)) -> dict[str, Any]:
        """Stop the current open sleep session."""
        open_period = (
            db.query(SleepPeriod)
            .filter(SleepPeriod.is_final == False)  # noqa: E712
            .order_by(SleepPeriod.start_ns.desc())
            .first()
        )
        if not open_period:
            return {"status": "ignored", "message": "No sleep session in progress"}

        now_ns = int(time.time() * 1e9)
        open_period.end_ns = now_ns
        open_period.ended_at = datetime.utcnow()
        dur_min = (now_ns - open_period.start_ns) / (60 * 1e9)
        open_period.duration_min = round(dur_min, 1)
        open_period.is_final = True
        open_period.sleep_type = "night" if dur_min >= 180 else "nap"
        db.commit()

        logger.info(
            f"[API] Manual sleep STOP → {open_period.period_id} "
            f"({open_period.duration_min}min, {open_period.sleep_type})"
        )
        await ws_manager.broadcast({
            "type": "data_refresh",
            "source": "manual_sleep_stop",
            "period_id": open_period.period_id,
            "duration_min": open_period.duration_min,
        })
        # Push health immediately so all clients clear the active sleep indicator
        await ws_manager.broadcast(_build_health_event())
        return {
            "status": "ok",
            "period_id": open_period.period_id,
            "duration_min": open_period.duration_min,
        }

    @app.post("/api/sleep-periods/manual")
    async def create_manual_period(
        body: dict[str, Any],
        db: DBSession = Depends(get_db),
    ) -> dict[str, Any]:
        """Create a manual sleep period with explicit start/end times."""
        start_iso = body.get("started_at")
        end_iso = body.get("ended_at")
        sleep_type = body.get("sleep_type", "nap")

        if not start_iso or not end_iso:
            raise HTTPException(400, "started_at and ended_at are required")

        start_dt = datetime.fromisoformat(start_iso.replace("Z", "+00:00")).replace(tzinfo=None)
        end_dt = datetime.fromisoformat(end_iso.replace("Z", "+00:00")).replace(tzinfo=None)

        if end_dt <= start_dt:
            raise HTTPException(400, "ended_at must be after started_at")

        start_ns = int(start_dt.timestamp() * 1e9)
        end_ns = int(end_dt.timestamp() * 1e9)
        dur_min = (end_ns - start_ns) / (60 * 1e9)

        # Find the most recent recording session to associate with
        session = (
            db.query(RecordingSession)
            .order_by(RecordingSession.started_at.desc())
            .first()
        )
        session_id = session.session_id if session else "manual"

        period = SleepPeriod(
            period_id=f"sp-{_uuid.uuid4().hex[:10]}",
            session_id=session_id,
            start_ns=start_ns,
            end_ns=end_ns,
            started_at=start_dt,
            ended_at=end_dt,
            sleep_type=sleep_type,
            duration_min=round(dur_min, 1),
            confidence=1.0,
            is_final=True,
            source="manual",
        )
        db.add(period)
        db.commit()

        logger.info(f"[API] Manual period created: {period.period_id} ({sleep_type}, {dur_min:.1f}min)")
        await ws_manager.broadcast({
            "type": "data_refresh",
            "source": "manual_period_created",
            "period_id": period.period_id,
        })
        return {"status": "ok", "period_id": period.period_id, "duration_min": round(dur_min, 1)}

    @app.put("/api/sleep-periods/{period_id}")
    async def update_period(
        period_id: str,
        body: dict[str, Any],
        db: DBSession = Depends(get_db),
    ) -> dict[str, Any]:
        """Update start/end times and sleep type of an existing period."""
        period = db.query(SleepPeriod).filter(SleepPeriod.period_id == period_id).first()
        if not period:
            raise HTTPException(404, f"Sleep period '{period_id}' not found")

        changed = False
        if "started_at" in body:
            dt = datetime.fromisoformat(body["started_at"].replace("Z", "+00:00")).replace(tzinfo=None)
            period.started_at = dt
            period.start_ns = int(dt.timestamp() * 1e9)
            changed = True
        if "ended_at" in body:
            dt = datetime.fromisoformat(body["ended_at"].replace("Z", "+00:00")).replace(tzinfo=None)
            period.ended_at = dt
            period.end_ns = int(dt.timestamp() * 1e9)
            changed = True
        if "sleep_type" in body:
            period.sleep_type = body["sleep_type"]
            changed = True

        if changed:
            dur_min = (period.end_ns - period.start_ns) / (60 * 1e9)
            period.duration_min = round(dur_min, 1)
            db.commit()
            logger.info(f"[API] Period updated: {period_id} → {period.sleep_type} {dur_min:.1f}min")
            await ws_manager.broadcast({
                "type": "data_refresh",
                "source": "period_updated",
                "period_id": period_id,
            })

        return {
            "status": "ok",
            "period_id": period_id,
            "started_at": period.started_at.isoformat() + "Z",
            "ended_at": period.ended_at.isoformat() + "Z",
            "sleep_type": period.sleep_type,
            "duration_min": period.duration_min,
        }

    @app.delete("/api/sleep-periods")
    async def delete_sleep_periods(
        period_ids: list[str],
        db: DBSession = Depends(get_db),
    ) -> dict[str, Any]:
        """Delete one or more sleep periods and their analyses."""
        deleted = []
        for pid in period_ids:
            period = db.query(SleepPeriod).filter(SleepPeriod.period_id == pid).first()
            if period:
                # Cascade deletes the analysis via relationship
                db.delete(period)
                deleted.append(pid)

        if deleted:
            db.commit()
            logger.info(f"[API] Deleted {len(deleted)} sleep period(s): {deleted}")
            await ws_manager.broadcast({
                "type": "data_refresh",
                "source": "periods_deleted",
                "deleted": deleted,
            })

        return {"status": "ok", "deleted": deleted, "count": len(deleted)}

    # ── Sensor reference ──────────────────────────────

    @app.get("/api/sensor-reference")
    def sensor_reference() -> dict[str, Any]:
        return {
            "total_sensors": len(SENSOR_REGISTRY),
            "sleep_relevant": SLEEP_SENSORS,
            "watch_sensors": WATCH_SENSORS,
            "sensors": {
                name: {
                    "source": info["source"],
                    "fields": info["fields"],
                    "units": info["units"],
                    "sleep_relevant": info["sleep_relevant"],
                    "description": info["description"],
                }
                for name, info in SENSOR_REGISTRY.items()
            },
        }

    # ── WebSocket: real-time push to dashboard ──────────

    @app.websocket("/ws")
    async def websocket_endpoint(ws: WebSocket) -> None:
        await ws_manager.connect(ws)
        # Send current health immediately on connect
        try:
            await ws.send_text(json.dumps(_build_health_event()))
        except Exception:
            pass
        try:
            while True:
                await ws.receive_text()
        except WebSocketDisconnect:
            ws_manager.disconnect(ws)

    # ── Dashboard (legacy fallback — nginx serves the Vue SPA) ──

    @app.get("/", response_class=HTMLResponse)
    async def dashboard(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(request=request, name="dashboard.html")

    return app


_start_time: float = time.time()
