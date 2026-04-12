"""
Signal-to-Sleep — Entry Point

Apple Watch sleep data analysis server.
Ingests sensor data from Sensor Logger via MQTT, analyzes sleep stages,
and serves a web dashboard.

Usage:
    python server.py
    # or
    uvicorn server:app --host 0.0.0.0 --port 8080
"""

import os
import logging

from fastapi import FastAPI
from lib.app import create_app

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)

# Silence noisy uvicorn access logs (health-check spam etc.)
logging.getLogger("uvicorn.access").setLevel(logging.WARNING)

app: FastAPI = create_app()

if __name__ == "__main__":
    import uvicorn

    port: int = int(os.environ.get("WEB_PORT", "8080"))
    uvicorn.run("server:app", host="0.0.0.0", port=port, reload=True)
