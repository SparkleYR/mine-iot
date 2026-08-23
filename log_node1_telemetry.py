#!/usr/bin/env python3
import sqlite3
import time
import os
import json
from datetime import datetime

DB_PATH = os.path.expanduser("~/mine-iot/pc_telemetry.db")
LOG_FILE_TXT = "/home/sparkle/Documents/MINE SIH/mine-iot/node1_15min_telemetry.log"
LOG_FILE_JSONL = "/home/sparkle/.gemini/antigravity/brain/07d9b2d9-d7df-4768-a555-bce8b7b5c57d/node1_15min_telemetry.jsonl"

DURATION_SECONDS = 900  # 15 minutes
POLL_INTERVAL = 2       # Check database every 2 seconds

def main():
    print("==================================================")
    print(" Starting 15-Minute Telemetry Logger for Node 1   ")
    print(" Target Node: ESP-NODE-01 / esp32_sensor_node_1   ")
    print(f" Duration: {DURATION_SECONDS} seconds ({DURATION_SECONDS // 60} mins)")
    print("==================================================")

    # Initialize log files
    with open(LOG_FILE_TXT, "w") as f:
        f.write(f"=== Node 1 (ESP-NODE-01) Telemetry Log ===\n")
        f.write(f"Started at: {datetime.now().isoformat()}\n\n")

    os.makedirs(os.path.dirname(LOG_FILE_JSONL), exist_ok=True)
    with open(LOG_FILE_JSONL, "w") as f:
        pass

    start_time = time.time()
    last_processed_id = 0

    # Get baseline max ID from database so we only log new incoming records
    if os.path.exists(DB_PATH):
        try:
            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()
            c.execute("SELECT MAX(id) FROM sensor_readings WHERE device_id IN ('ESP-NODE-01', 'esp32_sensor_node_1')")
            row = c.fetchone()
            if row and row[0] is not None:
                last_processed_id = row[0]
            conn.close()
        except Exception as e:
            print(f"[WARN] Error reading initial DB state: {e}")

    print(f"[INIT] Baseline record ID: {last_processed_id}")
    packet_count = 0
    last_report_time = time.time()

    while True:
        elapsed = time.time() - start_time
        if elapsed >= DURATION_SECONDS:
            break

        if os.path.exists(DB_PATH):
            try:
                conn = sqlite3.connect(DB_PATH)
                c = conn.cursor()
                c.execute(
                    "SELECT id, device_id, seq, device_ms, vibration, adxl_ax, adxl_ay, adxl_az, "
                    "mpu_ax, mpu_ay, mpu_az, mpu_gx, mpu_gy, mpu_gz, distance_cm, buzzer, mq2_raw, "
                    "temperature, humidity, received_at FROM sensor_readings "
                    "WHERE id > ? AND device_id IN ('ESP-NODE-01', 'esp32_sensor_node_1') "
                    "ORDER BY id ASC",
                    (last_processed_id,)
                )
                rows = c.fetchall()
                conn.close()

                for r in rows:
                    rec_id, dev_id, seq, dev_ms, vib, a_ax, a_ay, a_az, m_ax, m_ay, m_az, m_gx, m_gy, m_gz, dist, buzz, mq2, temp, hum, rec_at = r
                    last_processed_id = rec_id
                    packet_count += 1

                    data_dict = {
                        "db_id": rec_id,
                        "device_id": dev_id,
                        "seq": seq,
                        "device_ms": dev_ms,
                        "vibration": vib,
                        "adxl345": {"ax": a_ax, "ay": a_ay, "az": a_az},
                        "mpu6050": {"ax": m_ax, "ay": m_ay, "az": m_az, "gx": m_gx, "gy": m_gy, "gz": m_gz},
                        "distance_cm": dist,
                        "buzzer": buzz,
                        "mq2_raw": mq2,
                        "temperature": temp,
                        "humidity": hum,
                        "received_at": rec_at
                    }

                    formatted_line = (
                        f"[{rec_at}] #Seq:{seq} | Vib:{vib} | Dist:{dist:.2f}cm | MQ2:{mq2} | "
                        f"Temp:{temp}°C | Hum:{hum}% | ADXL:[{a_ax:.2f}, {a_ay:.2f}, {a_az:.2f}] | "
                        f"MPU_A:[{m_ax:.2f}, {m_ay:.2f}, {m_az:.2f}]\n"
                    )

                    with open(LOG_FILE_TXT, "a") as f:
                        f.write(formatted_line)

                    with open(LOG_FILE_JSONL, "a") as f:
                        f.write(json.dumps(data_dict) + "\n")

                    print(f"[NODE 1 PACKET #{packet_count}] Seq {seq} received at {rec_at} | Dist: {dist:.1f}cm | MQ2: {mq2}")

            except Exception as e:
                print(f"[WARN] DB Polling exception: {e}")

        # Periodic status report every 30 seconds
        if time.time() - last_report_time >= 30:
            last_report_time = time.time()
            rem = int(DURATION_SECONDS - elapsed)
            print(f"[STATUS] {int(elapsed)}s elapsed / {rem}s remaining | Captured {packet_count} packets from Node 1")

        time.sleep(POLL_INTERVAL)

    print("==================================================")
    print(f" COMPLETED 15-MINUTE LOGGING FOR NODE 1")
    print(f" Total Node 1 Packets Captured: {packet_count}")
    print(f" Text Log: {LOG_FILE_TXT}")
    print(f" JSONL Log: {LOG_FILE_JSONL}")
    print("==================================================")

if __name__ == "__main__":
    main()
