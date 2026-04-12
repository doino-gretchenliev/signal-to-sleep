"""MQTT layer: broker client, command publisher, and sensor registry."""

from lib.mqtt.client import SensorMQTTClient, mqtt_client
from lib.mqtt.sensors import SENSOR_REGISTRY, SLEEP_SENSORS, WATCH_SENSORS, get_sensor_info

__all__ = [
    "SensorMQTTClient", "mqtt_client",
    "SENSOR_REGISTRY", "SLEEP_SENSORS", "WATCH_SENSORS", "get_sensor_info",
]
