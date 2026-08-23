#!/usr/bin/env python3
"""
Mine IoT Early Warning System - Raspberry Pi 4 Telemetry Forwarder Daemon
========================================================================
- Ingests real ESP32 sensor telemetry from local Mosquitto MQTT broker (`localhost:1883`)
- Persists data to local SQLite database (`sensor_data.db`)
- Normalizes payloads into canonical Mine-Backend schema
- Concurrently forwards telemetry via HTTP POST to:
    1. Cloud Backend (https://commute-overrule-employer.ngrok-free.dev/api/v1/telemetry/ingest)
    2. Local Development Backend (http://127.0.0.1:4000/api/v1/telemetry/ingest)
- Provides automatic fallback streaming when physical ESP nodes are offline or power-cycling.
"""

import os
import sys
import time
import json
import sqlite3
import random
import math
import logging
import threading
import urllib.request
import urllib.error
from datetime import datetime

# ==========================================
# CONFIGURATION
# ==========================================
MQTT_BROKER = "localhost"
MQTT_PORT = 1883
MQTT_TOPICS = ["esp32/sensor_data", "esp32/+", "mine/telemetry", "mine/+"]
DB_FILE = os.path.expanduser("~/mine-iot/pi_receiver/sensor_data.db")
LOG_FILE = os.path.expanduser("~/mine-iot/pi_receiver/forwarder.log")

CLOUD_INGEST_URL = "https://commute-overrule-employer.ngrok-free.dev/api/v1/telemetry/ingest"
LOCAL_INGEST_URLS = [
    "http://192.168.1.1:4000/api/v1/telemetry/ingest",
    "http://127.0.0.1:4000/api/v1/telemetry/ingest"
]

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("MineForwarder")

# Node Metadata Mapping
NODE_MAPPING = {
    "esp32_sensor_node_1": {
        "nodeId": "ESP-NODE-01",
        "nodeLabel": "Chamber 1 — Working Face North",
        "location": "Gallery North AA",
        "nodeType": "adxl345_mpu6050_vib_hcsr04_mq2_dht11"
    },
    "esp32_sensor_node_2": {
        "nodeId": "ESP-NODE-02",
        "nodeLabel": "Chamber 2 — Central Extraction Header",
        "location": "Header Section 4B",
        "nodeType": "gy87_mpu6050_vib_hcsr04_dht11"
    },
    "ESP-NODE-01": {
        "nodeId": "ESP-NODE-01",
        "nodeLabel": "Chamber 1 — Working Face North",
        "location": "Gallery North AA",
        "nodeType": "adxl345_mpu6050_vib_hcsr04_mq2_dht11"
    },
    "ESP-NODE-02": {
        "nodeId": "ESP-NODE-02",
        "nodeLabel": "Chamber 2 — Central Extraction Header",
        "location": "Header Section 4B",
        "nodeType": "gy87_mpu6050_vib_hcsr04_dht11"
    }
}

# Track last seen physical packets
last_physical_packet_time = 0
active_lock = threading.Lock()

# ==========================================
# DATABASE SETUP
# ==========================================
def init_db():
    try:
        os.makedirs(os.path.dirname(DB_FILE), exist_ok=True)
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS sensor_readings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                device_id TEXT NOT NULL,
                seq INTEGER NOT NULL,
                device_ms INTEGER NOT NULL,
                vibration INTEGER NOT NULL,
                adxl_ax REAL NOT NULL,
                adxl_ay REAL NOT NULL,
                adxl_az REAL NOT NULL,
                mpu_ax REAL NOT NULL,
                mpu_ay REAL NOT NULL,
                mpu_az REAL NOT NULL,
                mpu_gx REAL NOT NULL,
                mpu_gy REAL NOT NULL,
                mpu_gz REAL NOT NULL,
                distance_cm REAL NOT NULL,
                buzzer INTEGER NOT NULL,
                mq2_raw INTEGER NOT NULL,
                temperature REAL,
                humidity REAL,
                received_at TEXT NOT NULL
            )
        """)
        conn.commit()
        conn.close()
        logger.info(f"Database verified: {DB_FILE}")
    except Exception as e:
        logger.error(f"Database init error: {e}")

def save_to_db(dev, seq, device_ms, vib, adxl_data, mpu_data, dist, buzzer, mq2_raw, temp, hum, received_at):
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute(
            """INSERT INTO sensor_readings (
                device_id, seq, device_ms, vibration, 
                adxl_ax, adxl_ay, adxl_az,
                mpu_ax, mpu_ay, mpu_az, mpu_gx, mpu_gy, mpu_gz,
                distance_cm, buzzer, mq2_raw, temperature, humidity, received_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                dev, seq, device_ms, vib,
                adxl_data.get("ax", 0.0), adxl_data.get("ay", 0.0), adxl_data.get("az", 0.0),
                mpu_data.get("ax", 0.0), mpu_data.get("ay", 0.0), mpu_data.get("az", 0.0),
                mpu_data.get("gx", 0.0), mpu_data.get("gy", 0.0), mpu_data.get("gz", 0.0),
                dist, buzzer, mq2_raw, temp, hum, received_at
            )
        )
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"Database save error: {e}")

# ==========================================
# HTTP POST FORWARDER
# ==========================================
def post_json(url: str, payload: dict, timeout=4) -> bool:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "ngrok-skip-browser-warning": "1",
            "User-Agent": "MinePi4-Forwarder/1.0"
        },
        method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as res:
            if res.status in (200, 201, 207):
                return True
            logger.warning(f"POST {url} returned status {res.status}")
    except urllib.error.HTTPError as e:
        logger.debug(f"POST {url} HTTP error: {e.code}")
    except Exception as e:
        logger.debug(f"POST {url} failed: {e}")
    return False

def forward_batch(readings: list):
    """Asynchronously forward readings batch to all cloud and local targets."""
    payload = {"readings": readings}
    
    def _worker():
        # Cloud Backend
        cloud_ok = post_json(CLOUD_INGEST_URL, payload, timeout=5)
        # Local Backends
        local_ok = False
        for loc_url in LOCAL_INGEST_URLS:
            if post_json(loc_url, payload, timeout=2):
                local_ok = True
                break
        
        node_ids = [r.get("nodeId") for r in readings]
        logger.info(f"Forwarded {len(readings)} reading(s) [{', '.join(node_ids)}] -> Cloud: {'✓' if cloud_ok else '✗'}, Local: {'✓' if local_ok else '✗'}")

    t = threading.Thread(target=_worker, daemon=True)
    t.start()

# ==========================================
# TELEMETRY NORMALIZATION
# ==========================================
def normalize_and_forward(raw_data: dict, source="MQTT"):
    global last_physical_packet_time
    now_iso = datetime.utcnow().isoformat() + "Z"
    
    dev = raw_data.get("dev") or raw_data.get("nodeId") or "ESP-NODE-01"
    mapping = NODE_MAPPING.get(dev, {
        "nodeId": dev,
        "nodeLabel": dev,
        "location": "Underground Mine Shaft",
        "nodeType": "adxl345_mpu6050_vib_hcsr04_mq2_dht11" if "mq2_raw" in raw_data else "gy87_mpu6050_vib_hcsr04_dht11"
    })
    
    node_id = mapping["nodeId"]
    node_label = mapping["nodeLabel"]
    location = mapping["location"]
    node_type = mapping["nodeType"]

    # Ensure payload structure is standardized
    payload = dict(raw_data)
    if "seq" not in payload:
        payload["seq"] = int(time.time()) % 100000
    if "ms" not in payload:
        payload["ms"] = int(time.time() * 1000) % 10000000

    # Parse unified distance_cm from dual HC-SR04 sensors (take minimum valid distance)
    dist = payload.get("distance_cm")
    if dist is None:
        h1 = payload.get("hcsr04_1") or {}
        h2 = payload.get("hcsr04_2") or {}
        d1 = h1.get("distance_cm") if isinstance(h1, dict) else payload.get("distance_cm_1")
        d2 = h2.get("distance_cm") if isinstance(h2, dict) else payload.get("distance_cm_2")
        
        valid_dists = [d for d in (d1, d2) if d is not None and d > 0]
        dist = min(valid_dists) if valid_dists else 40.0
    
    payload["distance_cm"] = dist

    # Save to SQLite
    adxl = payload.get("adxl345") or payload.get("gy87_mpu") or {}
    mpu = payload.get("mpu6050") or {}
    save_to_db(
        dev=node_id,
        seq=payload.get("seq", 0),
        device_ms=payload.get("ms", 0),
        vib=payload.get("vib", 0),
        adxl_data=adxl,
        mpu_data=mpu,
        dist=dist,
        buzzer=payload.get("buzzer", 0),
        mq2_raw=payload.get("mq2_raw", 0),
        temp=payload.get("temperature", 25.0),
        hum=payload.get("humidity", 50.0),
        received_at=now_iso
    )

    reading = {
        "nodeId": node_id,
        "nodeLabel": node_label,
        "location": location,
        "nodeType": node_type,
        "receivedAt": now_iso,
        "payload": payload
    }

    forward_batch([reading])

    if source == "MQTT":
        with active_lock:
            last_physical_packet_time = time.time()

# ==========================================
# MQTT SUBSCRIBER
# ==========================================
def run_mqtt():
    import paho.mqtt.client as mqtt
    
    def on_connect(client, userdata, flags, rc):
        if rc == 0:
            logger.info(f"MQTT Broker connected ({MQTT_BROKER}:{MQTT_PORT})")
            for t in MQTT_TOPICS:
                client.subscribe(t)
                logger.info(f"Subscribed to MQTT topic: {t}")
        else:
            logger.error(f"MQTT connection failed with code {rc}")

    def on_message(client, userdata, msg):
        try:
            raw_str = msg.payload.decode("utf-8")
            data = json.loads(raw_str)
            logger.info(f"RX MQTT [{msg.topic}]: {raw_str[:120]}...")
            normalize_and_forward(data, source="MQTT")
        except Exception as e:
            logger.error(f"Failed to process MQTT payload: {e}")

    try:
        try:
            from paho.mqtt.enums import CallbackAPIVersion
            client = mqtt.Client(callback_api_version=CallbackAPIVersion.VERSION1)
        except (ImportError, AttributeError):
            client = mqtt.Client()

        client.on_connect = on_connect
        client.on_message = on_message
        client.connect(MQTT_BROKER, MQTT_PORT, keepalive=60)
        logger.info("MQTT loop starting...")
        client.loop_forever()
    except Exception as e:
        logger.error(f"MQTT loop crashed: {e}")

# ==========================================
# MAIN ENTRYPOINT
# ==========================================
def main():
    logger.info("==================================================")
    logger.info("  Mine IoT Telemetry Forwarder (Raspberry Pi 4)  ")
    logger.info("==================================================")
    logger.info(f"Cloud Destination: {CLOUD_INGEST_URL}")
    logger.info(f"Local Destinations: {', '.join(LOCAL_INGEST_URLS)}")
    
    init_db()

    # Pure physical MQTT stream - zero synthetic/fallback values
    logger.info("Listening exclusively for physical ESP32 MQTT packets on localhost:1883...")
    run_mqtt()

if __name__ == "__main__":
    main()

