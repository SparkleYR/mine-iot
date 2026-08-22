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
    
    # Migrate if table has old schema (lacks distance_cm column)
    if columns and "distance_cm" not in columns:
        print("[MIGRATION] Schema mismatch detected (lacks distance_cm). Dropping old table.")
        cursor.execute("DROP TABLE sensor_readings")
        conn.commit()
        columns = []
        
    if not columns:
        print("Creating new sensor_readings table with dual MPU6050 and HC-SR04 support.")
        cursor.execute("""
            CREATE TABLE sensor_readings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                device_id TEXT NOT NULL,
                seq INTEGER NOT NULL,
                device_ms INTEGER NOT NULL,
                vibration INTEGER NOT NULL,
                mpu1_ax REAL NOT NULL,
                mpu1_ay REAL NOT NULL,
                mpu1_az REAL NOT NULL,
                mpu1_gx REAL NOT NULL,
                mpu1_gy REAL NOT NULL,
                mpu1_gz REAL NOT NULL,
                mpu2_ax REAL NOT NULL,
                mpu2_ay REAL NOT NULL,
                mpu2_az REAL NOT NULL,
                mpu2_gx REAL NOT NULL,
                mpu2_gy REAL NOT NULL,
                mpu2_gz REAL NOT NULL,
                distance_cm REAL NOT NULL,
                received_at TEXT NOT NULL
            )
        """)
        conn.commit()
    else:
        print("Database schema is up to date.")
    conn.close()

def save_reading(device_id, seq, device_ms, vibration, mpu1_data, mpu2_data, distance_cm):
    """Inserts a sensor reading into the SQLite database."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    received_at = datetime.datetime.utcnow().isoformat()
    try:
        cursor.execute(
            """INSERT INTO sensor_readings (
                device_id, seq, device_ms, vibration, 
                mpu1_ax, mpu1_ay, mpu1_az, mpu1_gx, mpu1_gy, mpu1_gz,
                mpu2_ax, mpu2_ay, mpu2_az, mpu2_gx, mpu2_gy, mpu2_gz,
                distance_cm, received_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                device_id, seq, device_ms, vibration,
                mpu1_data.get("ax", 0.0), mpu1_data.get("ay", 0.0), mpu1_data.get("az", 0.0),
                mpu1_data.get("gx", 0.0), mpu1_data.get("gy", 0.0), mpu1_data.get("gz", 0.0),
                mpu2_data.get("ax", 0.0), mpu2_data.get("ay", 0.0), mpu2_data.get("az", 0.0),
                mpu2_data.get("gx", 0.0), mpu2_data.get("gy", 0.0), mpu2_data.get("gz", 0.0),
                distance_cm, received_at
            )
        )
        conn.commit()
        print(f"[{received_at}] Saved [{device_id}] #{seq}: Vib={vibration}, MPU1_A=[{mpu1_data.get('ax'):.2f},{mpu1_data.get('ay'):.2f},{mpu1_data.get('az'):.2f}], MPU2_A=[{mpu2_data.get('ax'):.2f},{mpu2_data.get('ay'):.2f},{mpu2_data.get('az'):.2f}], Dist={distance_cm:.2f} cm")
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
        mpu1_data = payload.get("mpu1", {})
        mpu2_data = payload.get("mpu2", {})
        distance_cm = payload.get("distance_cm")
        
        if None in (seq, device_ms, vib, distance_cm):
            print(f"Warning: Received incomplete payload: {payload}", file=sys.stderr)
            return
            
        # Save to database
        save_reading(dev, seq, device_ms, vib, mpu1_data, mpu2_data, distance_cm)
        
    except json.JSONDecodeError:
        print(f"Error: Failed to decode JSON payload: {msg.payload}", file=sys.stderr)
    except Exception as e:
        print(f"Error processing message: {e}", file=sys.stderr)

# ==========================================
# MAIN EXECUTION
# ==========================================
def main():
    print("--- Starting Pi MQTT Receiver (Vibration, Motion & Distance) ---")
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
