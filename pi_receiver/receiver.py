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
    
    # Migrate if table has old schema (lacks mq2_raw column)
    if columns and "mq2_raw" not in columns:
        print("[MIGRATION] Schema mismatch detected (lacks mq2_raw). Dropping old table.")
        cursor.execute("DROP TABLE sensor_readings")
        conn.commit()
        columns = []
        
    if not columns:
        print("Creating new sensor_readings table with ADXL345, MPU6050, SW-420, HC-SR04, MQ-2, and DHT11 support.")
        cursor.execute("""
            CREATE TABLE sensor_readings (
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
    else:
        print("Database schema is up to date.")
    conn.close()

def save_reading(device_id, seq, device_ms, vibration, adxl_data, mpu_data, distance_cm, buzzer, mq2_raw, temperature, humidity):
    """Inserts a sensor reading into the SQLite database."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    received_at = datetime.datetime.utcnow().isoformat()
    try:
        cursor.execute(
            """INSERT INTO sensor_readings (
                device_id, seq, device_ms, vibration, 
                adxl_ax, adxl_ay, adxl_az,
                mpu_ax, mpu_ay, mpu_az, mpu_gx, mpu_gy, mpu_gz,
                distance_cm, buzzer, mq2_raw, temperature, humidity, received_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                device_id, seq, device_ms, vibration,
                adxl_data.get("ax", 0.0), adxl_data.get("ay", 0.0), adxl_data.get("az", 0.0),
                mpu_data.get("ax", 0.0), mpu_data.get("ay", 0.0), mpu_data.get("az", 0.0),
                mpu_data.get("gx", 0.0), mpu_data.get("gy", 0.0), mpu_data.get("gz", 0.0),
                distance_cm, buzzer, mq2_raw, temperature, humidity, received_at
            )
        )
        conn.commit()
        
        temp_str = f"{temperature:.1f}°C" if temperature is not None else "None"
        hum_str = f"{humidity:.1f}%" if humidity is not None else "None"
        print(f"[{received_at}] Saved [{device_id}] #{seq}: Vib={vibration}, ADXL_A=[{adxl_data.get('ax'):.2f},{adxl_data.get('ay'):.2f},{adxl_data.get('az'):.2f}], MPU_A=[{mpu_data.get('ax'):.2f},{mpu_data.get('ay'):.2f},{mpu_data.get('az'):.2f}], Dist={distance_cm:.2f}cm, Buzzer={buzzer}, MQ2={mq2_raw}, Temp={temp_str}, Hum={hum_str}")
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
        adxl_data = payload.get("adxl345", {})
        mpu_data = payload.get("mpu6050", {})
        distance_cm = payload.get("distance_cm")
        if distance_cm is None:
            d1 = payload.get("hcsr04_1", {}).get("distance_cm")
            d2 = payload.get("hcsr04_2", {}).get("distance_cm")
            distance_cm = d1 if d1 is not None else d2

        buzzer = payload.get("buzzer", 0)
        mq2_raw = payload.get("mq2_raw", 0)
        temperature = payload.get("temperature")
        humidity = payload.get("humidity")
        
        if None in (seq, device_ms, vib):
            print(f"Warning: Received incomplete payload: {payload}", file=sys.stderr)
            return

        if distance_cm is None:
            distance_cm = -1.0
            
        # Save to database
        save_reading(dev, seq, device_ms, vib, adxl_data, mpu_data, distance_cm, buzzer, mq2_raw, temperature, humidity)
        
    except json.JSONDecodeError:
        print(f"Error: Failed to decode JSON payload: {msg.payload}", file=sys.stderr)
    except Exception as e:
        print(f"Error processing message: {e}", file=sys.stderr)

# ==========================================
# MAIN EXECUTION
# ==========================================
def main():
    print("--- Starting Pi MQTT Receiver (Full Sensor Integration) ---")
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
