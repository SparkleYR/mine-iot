#!/usr/bin/env python3
"""
Mine IoT Early Warning System - Node 2 10-Minute Live Telemetry Receiver & Collector
===================================================================================
Captures 10 minutes (600 seconds) of live telemetry from ESP-NODE-02.
Computes 0-calibrated 3D total tilt and differential Euler angles.
Flushes each record in real-time to JSONL and LOG output files.
"""

import json
import sqlite3
import time
import os
import math
from datetime import datetime, timezone

DB_PATH = "/home/sparkle/mine-iot/pc_telemetry.db"
BRAIN_DIR = "/home/sparkle/.gemini/antigravity/brain/07d9b2d9-d7df-4768-a555-bce8b7b5c57d"
OUTPUT_JSONL = os.path.join(BRAIN_DIR, "node2_10min_telemetry.jsonl")
OUTPUT_ML_JSONL = os.path.join(BRAIN_DIR, "node2_10min_ml_training_dataset.jsonl")
OUTPUT_LOG = "/home/sparkle/Documents/MINE SIH/mine-iot/node2_10min_live.log"

# Node 2 Ground Baseline Vector
IMU_BASELINE = {"ax": 2.83, "ay": -0.201, "az": -7.293}

def wrap180(deg):
    w = deg % 360
    if w > 180: w -= 360
    if w < -180: w += 360
    return w

def compute_tilt_angles(ax, ay, az, base):
    if ax is None or ay is None or az is None:
        return 0.0, 0.0, 0.0
    
    raw_roll = math.atan2(ay, az) * 180 / math.pi
    raw_pitch = math.atan2(-ax, math.sqrt(ay*ay + az*az)) * 180 / math.pi

    base_roll = math.atan2(base['ay'], base['az']) * 180 / math.pi
    base_pitch = math.atan2(-base['ax'], math.sqrt(base['ay']*base['ay'] + base['az']*base['az'])) * 180 / math.pi

    roll_deg = wrap180(raw_roll - base_roll)
    pitch_deg = wrap180(raw_pitch - base_pitch)

    dot = ax*base['ax'] + ay*base['ay'] + az*base['az']
    mag = math.sqrt(ax*ax + ay*ay + az*az)
    base_mag = math.sqrt(base['ax']*base['ax'] + base['ay']*base['ay'] + base['az']*base['az'])
    
    cos_theta = max(-1.0, min(1.0, dot / (mag * base_mag))) if mag > 0 and base_mag > 0 else 1.0
    total_tilt = math.acos(cos_theta) * 180 / math.pi
    if math.isnan(total_tilt): total_tilt = 0.0

    return round(roll_deg, 2), round(pitch_deg, 2), round(total_tilt, 2)

duration_seconds = 10 * 60
start_time = time.time()
last_seen_id = 0

print(f"[Node 2 Collector] Starting 10-minute live telemetry capture for ESP-NODE-02...")
os.makedirs(BRAIN_DIR, exist_ok=True)

with open(OUTPUT_JSONL, "a") as f_jsonl, open(OUTPUT_ML_JSONL, "a") as f_ml, open(OUTPUT_LOG, "a") as f_log:
    while time.time() - start_time < duration_seconds:
        try:
            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()
            c.execute("""
                SELECT id, device_id, seq, device_ms, vibration,
                       adxl_ax, adxl_ay, adxl_az,
                       mpu_ax, mpu_ay, mpu_az, mpu_gx, mpu_gy, mpu_gz,
                       distance_cm, buzzer, mq2_raw, temperature, humidity, received_at
                FROM sensor_readings
                WHERE id > ? AND device_id IN ('ESP-NODE-02', 'esp32_sensor_node_2')
                  AND mpu_ax IS NOT NULL
                ORDER BY id ASC
            """, (last_seen_id,))
            rows = c.fetchall()
            conn.close()

            for r in rows:
                rec_id, dev, seq, ms, vib, ax1, ay1, az1, ax2, ay2, az2, gx2, gy2, gz2, dist, buzzer, mq2, temp, hum, ts = r
                last_seen_id = rec_id
                r2, p2, t2 = compute_tilt_angles(ax2, ay2, az2, IMU_BASELINE)

                rec_obj = {
                    "id": rec_id,
                    "device_id": dev,
                    "seq": seq,
                    "ms": ms,
                    "vibration": vib,
                    "imu2": {
                        "accelX": ax2, "accelY": ay2, "accelZ": az2,
                        "gyroX": gx2, "gyroY": gy2, "gyroZ": gz2,
                        "rollDeg": r2, "pitchDeg": p2, "totalTiltDeg": t2
                    },
                    "distance_cm": dist,
                    "mq2_raw": mq2,
                    "temperature": temp,
                    "humidity": hum,
                    "buzzer": buzzer,
                    "timestamp": ts
                }

                line = json.dumps(rec_obj) + "\n"
                f_jsonl.write(line)
                f_jsonl.flush()

                f_ml.write(line)
                f_ml.flush()

                log_entry = f"[{ts}] Seq #{seq} | MPU({ax2},{ay2},{az2}) Tilt:{t2}° | Dist:{dist}cm | Temp:{temp}°C\n"
                f_log.write(log_entry)
                f_log.flush()

                print(f"[Node 2 Captured] {ts} - Seq #{seq} - Tilt: {t2}°, Dist: {dist}cm, Temp: {temp}°C")

        except Exception as e:
            print(f"[Node 2 Collector Error] {e}")

        time.sleep(3)

print(f"[Node 2 Collector] Completed 10-minute telemetry capture.")
