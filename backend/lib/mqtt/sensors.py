"""
Complete Sensor Logger sensor reference.

Documents every sensor the app can push over HTTP, the exact field names,
data types, units, and which device they come from.

Based on: https://github.com/tszheichoi/awesome-sensor-logger/blob/main/UNITS.md
          https://github.com/tszheichoi/awesome-sensor-logger/blob/main/PUSHING.md
"""

from typing import Any, TypedDict


class SensorInfo(TypedDict):
    """Schema for a single sensor entry in the registry."""
    source: str
    fields: dict[str, str]
    units: str
    sleep_relevant: bool
    description: str


# All known sensor definitions from Sensor Logger.
# Each entry: { "source", "fields", "units", "sleep_relevant" }
SENSOR_REGISTRY: dict[str, SensorInfo] = {
    # ── iPhone Motion Sensors ──────────────────────────────────────────
    "accelerometer": {
        "source": "iphone",
        "fields": {"x": "float", "y": "float", "z": "float"},
        "units": "m/s²",
        "sleep_relevant": True,
        "description": "Device acceleration including gravity",
    },
    "accelerometeruncalibrated": {
        "source": "iphone",
        "fields": {"x": "float", "y": "float", "z": "float"},
        "units": "m/s² (raw)",
        "sleep_relevant": False,
        "description": "Raw accelerometer without calibration corrections",
    },
    "gravity": {
        "source": "iphone",
        "fields": {"x": "float", "y": "float", "z": "float"},
        "units": "m/s²",
        "sleep_relevant": False,
        "description": "Gravity vector in device frame",
    },
    "gyroscope": {
        "source": "iphone",
        "fields": {"x": "float", "y": "float", "z": "float"},
        "units": "rad/s",
        "sleep_relevant": True,
        "description": "Device rotation rate",
    },
    "gyroscopeuncalibrated": {
        "source": "iphone",
        "fields": {"x": "float", "y": "float", "z": "float"},
        "units": "rad/s (raw)",
        "sleep_relevant": False,
        "description": "Raw gyroscope without bias correction",
    },
    "magnetometer": {
        "source": "iphone",
        "fields": {"x": "float", "y": "float", "z": "float"},
        "units": "μT (microtesla)",
        "sleep_relevant": False,
        "description": "Magnetic field strength",
    },
    "magnetometeruncalibrated": {
        "source": "iphone",
        "fields": {"x": "float", "y": "float", "z": "float"},
        "units": "μT (raw)",
        "sleep_relevant": False,
        "description": "Raw magnetometer without calibration",
    },
    "orientation": {
        "source": "iphone",
        "fields": {
            "pitch": "float", "roll": "float", "yaw": "float",
            "qx": "float", "qy": "float", "qz": "float", "qw": "float",
        },
        "units": "radians / quaternion",
        "sleep_relevant": False,
        "description": "Device orientation as Euler angles and quaternion",
    },

    # ── Apple Watch Sensors ────────────────────────────────────────────
    "heartrate": {
        "source": "watch",
        "fields": {"bpm": "int"},
        "units": "beats per minute",
        "sleep_relevant": True,
        "description": "Heart rate from Apple Watch optical sensor",
    },
    "heart rate": {
        "source": "watch",
        "fields": {"bpm": "int"},
        "units": "beats per minute",
        "sleep_relevant": True,
        "description": "Heart rate from Apple Watch (Sensor Logger name)",
    },
    "wrist motion": {
        "source": "watch",
        "fields": {
            "accelerationX": "float", "accelerationY": "float", "accelerationZ": "float",
            "gravityX": "float", "gravityY": "float", "gravityZ": "float",
            "rotationRateX": "float", "rotationRateY": "float", "rotationRateZ": "float",
            "quaternionW": "float", "quaternionX": "float", "quaternionY": "float", "quaternionZ": "float",
        },
        "units": "m/s² (accel), rad/s (rotation), unitless (quaternion)",
        "sleep_relevant": True,
        "description": "9-axis motion from Apple Watch (acceleration + gravity + rotation + orientation)",
    },
    "pedometer": {
        "source": "watch",
        "fields": {"steps": "int"},
        "units": "step count",
        "sleep_relevant": True,
        "description": "Step counter from Apple Watch",
    },
    "activity": {
        "source": "watch",
        "fields": {"activity": "string", "confidence": "string"},
        "units": "categorical",
        "sleep_relevant": True,
        "description": "Detected activity type (stationary, walking, running, etc.)",
    },

    # ── Environmental Sensors ──────────────────────────────────────────
    "barometer": {
        "source": "iphone/watch",
        "fields": {"pressure": "float", "relativeAltitude": "float"},
        "units": "mBar / meters",
        "sleep_relevant": False,
        "description": "Atmospheric pressure and relative altitude change",
    },
    "brightness": {
        "source": "iphone",
        "fields": {"brightness": "float"},
        "units": "0.0 - 1.0",
        "sleep_relevant": True,
        "description": "Screen brightness level (proxy for ambient light)",
    },
    "microphone": {
        "source": "iphone",
        "fields": {"dBFS": "float"},
        "units": "decibels (full scale)",
        "sleep_relevant": True,
        "description": "Ambient noise level (useful for snoring/environment detection)",
    },

    # ── Location ───────────────────────────────────────────────────────
    "location": {
        "source": "iphone/watch",
        "fields": {
            "latitude": "float", "longitude": "float", "altitude": "float",
            "speed": "float", "bearing": "float",
            "horizontalAccuracy": "float", "verticalAccuracy": "float",
            "speedAccuracy": "float", "bearingAccuracy": "float",
            "altitudeAboveMeanSeaLevel": "float",
        },
        "units": "degrees / meters / m/s",
        "sleep_relevant": False,
        "description": "GPS location (dual-frequency on Apple Watch Ultra)",
    },

    # ── Device State ───────────────────────────────────────────────────
    "battery": {
        "source": "iphone",
        "fields": {
            "batteryLevel": "float",
            "batteryState": "string",  # unknown, unplugged, charging, full
            "lowPowerMode": "bool",
        },
        "units": "0.0 - 1.0 / state string",
        "sleep_relevant": False,
        "description": "Battery level and charging state",
    },

    # ── Connectivity ───────────────────────────────────────────────────
    "network": {
        "source": "iphone",
        "fields": {
            "type": "string", "isConnected": "bool", "isInternetReachable": "bool",
            "isWifiEnabled": "bool", "isConnectionExpensive": "bool",
            "ssid": "string", "bssid": "string", "strength": "float",
            "ipAddress": "string", "frequency": "float",
            "cellularGeneration": "string", "carrier": "string",
        },
        "units": "mixed",
        "sleep_relevant": False,
        "description": "Network connectivity information",
    },
    "bluetooth": {
        "source": "iphone",
        "fields": {"id": "string", "rssi": "int", "txPowerLevel": "int", "manufacturerData": "string"},
        "units": "dBm (rssi)",
        "sleep_relevant": False,
        "description": "Nearby Bluetooth device signal strength",
    },
    "bluetoothmetadata": {
        "source": "iphone",
        "fields": {"id": "string", "name": "string", "isConnectable": "bool", "localName": "string", "serviceUUIDs": "string"},
        "units": "metadata",
        "sleep_relevant": False,
        "description": "Bluetooth device metadata",
    },

    # ── AirPods / Headphones ───────────────────────────────────────────
    "headphone": {
        "source": "airpods",
        "fields": {
            "devicelocation": "string",
            "pitch": "float", "roll": "float", "yaw": "float",
            "quaternionW": "float", "quaternionX": "float", "quaternionY": "float", "quaternionZ": "float",
            "rotationRateX": "float", "rotationRateY": "float", "rotationRateZ": "float",
            "gravityX": "float", "gravityY": "float", "gravityZ": "float",
            "accelerationX": "float", "accelerationY": "float", "accelerationZ": "float",
        },
        "units": "radians / m/s² / rad/s",
        "sleep_relevant": False,
        "description": "AirPods head tracking motion data",
    },

    # ── User Input ─────────────────────────────────────────────────────
    "annotation": {
        "source": "user",
        "fields": {"text": "string", "millisecond_press_duration": "int"},
        "units": "text / ms",
        "sleep_relevant": True,
        "description": "Manual text annotations (e.g., 'going to sleep', 'woke up')",
    },
}

# Sensors critical for sleep analysis
SLEEP_SENSORS: list[str] = [name for name, info in SENSOR_REGISTRY.items() if info["sleep_relevant"]]

# Sensors from Apple Watch
WATCH_SENSORS: list[str] = [name for name, info in SENSOR_REGISTRY.items() if "watch" in info["source"]]


def get_sensor_info(sensor_name: str) -> SensorInfo | None:
    """Look up sensor info by name (case-insensitive)."""
    # Try exact match first
    if sensor_name in SENSOR_REGISTRY:
        return SENSOR_REGISTRY[sensor_name]
    # Try case-insensitive
    lower: str = sensor_name.lower()
    for name, info in SENSOR_REGISTRY.items():
        if name.lower() == lower:
            return info
    return None
