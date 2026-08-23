#!/usr/bin/env python3
import json
import sqlite3
import time
import os
from datetime import datetime, timezone

DB_PATH = "/home/sparkle/mine-iot/pc_telemetry.db"
OUTPUT_JSONL = "/home/sparkle/.gemini/antigravity/brain/07d9b2d9-d7df-4768-a555-bce8b7b5c57d/node1_15min_telemetry.jsonl"
OUTPUT_LOG = "/home/sparkle/Documents/MINE SIH/mine-iot/node1_15min_live.log"

duration_seconds = 15 * 60
start_time = time.time()
last_seen_id = 0

print(f"[Logger] Starting 15-minute telemetry capture for Node 1 (ESP-NODE-01)...")

with open(OUTPUT_JSONL, "a") as f_jsonl, open(OUTPUT_LOG, "a") as f_log:
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
                WHERE id > ? AND device_id IN ('ESP-NODE-01', 'esp32_sensor_node_1')
                  AND adxl_ax IS NOT NULL
                ORDER BY id ASC
            """, (last_seen_id,))
            rows = c.fetchall()
            conn.close()

            for r in rows:
                rec_id, dev, seq, ms, vib, ax1, ay1, az1, ax2, ay2, az2, gx2, gy2, gz2, dist, buzzer, mq2, temp, hum, ts = r
                last_seen_id = rec_id

                rec_obj = {
                    "id": rec_id,
                    "device_id": dev,
                    "seq": seq,
                    "ms": ms,
                    "vibration": vib,
                    "adxl345": {"ax": ax1, "ay": ay1, "az": az1},
                    "mpu6050": {"ax": ax2, "ay": ay2, "az": az2, "gx": gx2, "gy": gy2, "gz": gz2},
                    "distance_cm": dist,
                    "buzzer": buzzer,
                    "mq2_raw": mq2,
                    "temperature": temp,
                    "humidity": hum,
                    "timestamp": ts
                }

                f_jsonl.write(json.dumps(rec_obj) + "\n")
                f_jsonl.flush()

                log_entry = f"[{ts}] Seq #{seq} | ADXL({ax1},{ay1},{az1}) | MPU({ax2},{ay2},{az2}) | Dist:{dist}cm | MQ2:{mq2} | Temp:{temp}°C\n"
                f_log.write(log_entry)
                f_log.flush()

                print(f"[Captured] {ts} - Seq #{seq} - Distance: {dist}cm, Temp: {temp}°C")

        except Exception as e:
            print(f"[Logger Error] {e}")

        time.sleep(3)

print(f"[Logger] Completed 15-minute telemetry capture.")
