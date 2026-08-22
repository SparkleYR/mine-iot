#!/usr/bin/env python3
import os
import sys
import json
import sqlite3
import datetime
import paho.mqtt.client as mqtt

# ==========================================
# CONFIGURATION
# ==========================================
MQTT_BROKER = "localhost"
MQTT_PORT = 1883
MQTT_TOPIC = "esp32/sensor_data"
DB_FILE = "sensor_data.db"

# ==========================================
# DATABASE SETUP
# ==========================================
def init_db():
    """Initializes the SQLite database and handles schema migrations automatically."""
    print(f"Initializing database: {DB_FILE}")
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    # Check if table exists and inspect columns
    cursor.execute("PRAGMA table_info(sensor_readings)")
    columns = [col[1] for col in cursor.fetchall()]
    
    # Migrate if table has old schema (lacks device_id column)
    if columns and "device_id" not in columns:
        print("[MIGRATION] Schema mismatch detected (lacks device_id). Dropping old table.")
        cursor.execute("DROP TABLE sensor_readings")
        conn.commit()
        columns = []
        
    if not columns:
        print("Creating new sensor_readings table with multi-node support.")
        cursor.execute("""
            CREATE TABLE sensor_readings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                device_id TEXT NOT NULL,
                seq INTEGER NOT NULL,
                device_ms INTEGER NOT NULL,
                vibration INTEGER NOT NULL,
                accel_x REAL NOT NULL,
                accel_y REAL NOT NULL,
                accel_z REAL NOT NULL,
                gyro_x REAL NOT NULL,
                gyro_y REAL NOT NULL,
                gyro_z REAL NOT NULL,
                received_at TEXT NOT NULL
            )
        """)
        conn.commit()
    else:
        print("Database schema is up to date.")
    conn.close()

def save_reading(device_id, seq, device_ms, vibration, ax, ay, az, gx, gy, gz):
    """Inserts a sensor reading into the SQLite database."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    received_at = datetime.datetime.utcnow().isoformat()
    try:
        cursor.execute(
            """INSERT INTO sensor_readings (
                device_id, seq, device_ms, vibration, accel_x, accel_y, accel_z, gyro_x, gyro_y, gyro_z, received_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (device_id, seq, device_ms, vibration, ax, ay, az, gx, gy, gz, received_at)
        )
        conn.commit()
        print(f"[{received_at}] Saved [{device_id}] #{seq}: Vib={vibration}, Accel=[{ax:.2f},{ay:.2f},{az:.2f}], Gyro=[{gx:.2f},{gy:.2f},{gz:.2f}]")
    except sqlite3.Error as e:
        print(f"Database error: {e}", file=sys.stderr)
    finally:
        conn.close()

# ==========================================
# MQTT CLIENT CALLBACKS
# ==========================================
def on_connect(client, userdata, flags, rc):
    """Callback when client connects to the broker."""
    if rc == 0:
        print(f"Connected successfully to MQTT Broker ({MQTT_BROKER}:{MQTT_PORT})")
        client.subscribe(MQTT_TOPIC)
        print(f"Subscribed to topic: {MQTT_TOPIC}")
    else:
        print(f"Connection failed with code {rc}", file=sys.stderr)

def on_message(client, userdata, msg):
    """Callback when a message is received on a subscribed topic."""
    try:
        # Parse the JSON payload
        payload = json.loads(msg.payload.decode('utf-8'))
        
        # Extract fields
        dev = payload.get("dev", "unknown_device")
        seq = payload.get("seq")
        device_ms = payload.get("ms")
        vib = payload.get("vib")
        ax = payload.get("ax")
        ay = payload.get("ay")
        az = payload.get("az")
        gx = payload.get("gx")
        gy = payload.get("gy")
        gz = payload.get("gz")
        
        if None in (seq, device_ms, vib, ax, ay, az, gx, gy, gz):
            print(f"Warning: Received incomplete payload: {payload}", file=sys.stderr)
            return
            
        # Save to database
        save_reading(dev, seq, device_ms, vib, ax, ay, az, gx, gy, gz)
        
    except json.JSONDecodeError:
        print(f"Error: Failed to decode JSON payload: {msg.payload}", file=sys.stderr)
    except Exception as e:
        print(f"Error processing message: {e}", file=sys.stderr)

# ==========================================
# MAIN EXECUTION
# ==========================================
def main():
    print("--- Starting Pi MQTT Receiver (Vibration & Motion) ---")
    init_db()

    # Create MQTT client instance with compatibility for Paho 2.x
    try:
        from paho.mqtt.enums import CallbackAPIVersion
        client = mqtt.Client(callback_api_version=CallbackAPIVersion.VERSION1)
    except ImportError:
        client = mqtt.Client()

    client.on_connect = on_connect
    client.on_message = on_message

    try:
        print(f"Connecting to broker at {MQTT_BROKER}...")
        client.connect(MQTT_BROKER, MQTT_PORT, keepalive=60)
    except Exception as e:
        print(f"Failed to connect to broker: {e}", file=sys.stderr)
        sys.exit(1)

    print("Starting listener loop. Press Ctrl+C to exit.")
    try:
        client.loop_forever()
    except KeyboardInterrupt:
        print("\nStopping receiver... Goodbye!")
        client.disconnect()

if __name__ == "__main__":
    main()
