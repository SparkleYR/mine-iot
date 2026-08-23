#!/usr/bin/env python3
"""
Node 1 ML Training Dataset Collector (15 Minutes)
==================================================
Collects 15 minutes (180 samples @ 5s) of ALL sensor features from ESP-NODE-01:
- Accelerometer 1 (ADXL345: ax, ay, az)
- Accelerometer 2 (MPU6050: ax, ay, az, gx, gy, gz)
- Dual HC-SR04 Ultrasound Distance (cm)
- SW-420 Vibration (binary & event count)
- MQ-2 Methane/Smoke Raw ADC
- DHT11 Temperature (°C) & Humidity (%)
- Timestamp & Sequence ID

Exports to JSONL and CSV formats for ML model training.
Updates all 15-minute dataset files.
"""

import json
import sqlite3
import os
import csv
from datetime import datetime, timezone

DB_PATH = "/home/sparkle/mine-iot/pc_telemetry.db"
BRAIN_DIR = "/home/sparkle/.gemini/antigravity/brain/07d9b2d9-d7df-4768-a555-bce8b7b5c57d"

ML_JSONL_PATH = os.path.join(BRAIN_DIR, "node1_15min_ml_training_dataset.jsonl")
ML_CSV_PATH = "/home/sparkle/Documents/MINE SIH/mine-iot/node1_15min_ml_training_dataset.csv"
DATASET_15MIN_PATH = os.path.join(BRAIN_DIR, "node1_15min_telemetry.jsonl")

def fetch_clean_node1_readings(limit=180):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        SELECT id, device_id, seq, device_ms, vibration,
               adxl_ax, adxl_ay, adxl_az,
               mpu_ax, mpu_ay, mpu_az, mpu_gx, mpu_gy, mpu_gz,
               distance_cm, buzzer, mq2_raw, temperature, humidity, received_at
        FROM sensor_readings
        WHERE device_id IN ('ESP-NODE-01', 'esp32_sensor_node_1')
          AND adxl_ax IS NOT NULL
          AND mpu_ax IS NOT NULL
        ORDER BY id DESC LIMIT ?
    """, (limit,))
    rows = c.fetchall()
    conn.close()
    rows.reverse()
    return rows

def export_datasets():
    rows_15min = fetch_clean_node1_readings(180)

    jsonl_lines = []
    csv_rows = []
    
    csv_header = [
        "timestamp", "seq", "device_ms", "vibration",
        "adxl_ax", "adxl_ay", "adxl_az",
        "mpu_ax", "mpu_ay", "mpu_az", "mpu_gx", "mpu_gy", "mpu_gz",
        "distance_cm", "mq2_raw", "temperature", "humidity", "buzzer"
    ]

    for r in rows_15min:
        rec_id, dev, seq, ms, vib, ax1, ay1, az1, ax2, ay2, az2, gx2, gy2, gz2, dist, buzzer, mq2, temp, hum, ts = r
        obj = {
            "timestamp": ts,
            "device_id": dev,
            "seq": seq,
            "device_ms": ms,
            "vibration": vib,
            "adxl345": {"ax": ax1, "ay": ay1, "az": az1},
            "mpu6050": {"ax": ax2, "ay": ay2, "az": az2, "gx": gx2, "gy": gy2, "gz": gz2},
            "distance_cm": dist,
            "mq2_raw": mq2,
            "temperature": temp,
            "humidity": hum,
            "buzzer": buzzer
        }
        jsonl_lines.append(json.dumps(obj))
        csv_rows.append([ts, seq, ms, vib, ax1, ay1, az1, ax2, ay2, az2, gx2, gy2, gz2, dist, mq2, temp, hum, buzzer])

    os.makedirs(BRAIN_DIR, exist_ok=True)

    with open(ML_JSONL_PATH, "w") as f:
        f.write("\n".join(jsonl_lines) + "\n")

    with open(ML_CSV_PATH, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(csv_header)
        writer.writerows(csv_rows)

    with open(DATASET_15MIN_PATH, "w") as f:
        f.write("\n".join(jsonl_lines) + "\n")

    print(f"15-Minute ML Dataset successfully generated!")
    print(f"  - 15-Min Training Dataset (JSONL): {ML_JSONL_PATH} ({len(rows_15min)} records)")
    print(f"  - 15-Min Training Dataset (CSV)  : {ML_CSV_PATH} ({len(rows_15min)} records)")
    print(f"  - Updated Telemetry File (JSONL)  : {DATASET_15MIN_PATH} ({len(rows_15min)} records)")

if __name__ == "__main__":
    export_datasets()
