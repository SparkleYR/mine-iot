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
MQTT_BROKER = "localhost"  # Set to "localhost" if running on the Pi directly
MQTT_PORT = 1883
MQTT_TOPIC = "esp32/sensor_data"
DB_FILE = "sensor_data.db"

# ==========================================
# DATABASE SETUP
# ==========================================
def init_db():
    """Initializes the SQLite database and creates the readings table if it doesn't exist."""
    print(f"Initializing database: {DB_FILE}")
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS sensor_readings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            seq INTEGER NOT NULL,
            device_ms INTEGER NOT NULL,
            temperature REAL NOT NULL,
            humidity REAL NOT NULL,
            received_at TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()

def save_reading(seq, device_ms, temperature, humidity):
    """Inserts a sensor reading into the SQLite database."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    received_at = datetime.datetime.utcnow().isoformat()
    try:
        cursor.execute(
            "INSERT INTO sensor_readings (seq, device_ms, temperature, humidity, received_at) VALUES (?, ?, ?, ?, ?)",
            (seq, device_ms, temperature, humidity, received_at)
        )
        conn.commit()
        print(f"[{received_at}] Saved reading: Seq={seq}, Temp={temperature}°C, Hum={humidity}%, DeviceMs={device_ms}")
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
        # Subscribe to the topic
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
        seq = payload.get("seq")
        device_ms = payload.get("ms")
        temp = payload.get("temp")
        hum = payload.get("hum")
        
        if None in (seq, device_ms, temp, hum):
            print(f"Warning: Received incomplete payload: {payload}", file=sys.stderr)
            return
            
        # Save to database
        save_reading(seq, device_ms, temp, hum)
        
    except json.JSONDecodeError:
        print(f"Error: Failed to decode JSON payload: {msg.payload}", file=sys.stderr)
    except Exception as e:
        print(f"Error processing message: {e}", file=sys.stderr)

# ==========================================
# MAIN EXECUTION
# ==========================================
def main():
    print("--- starting Pi MQTT Receiver ---")
    init_db()

    # Create MQTT client instance with compatibility for Paho 2.x
    try:
        from paho.mqtt.enums import CallbackAPIVersion
        client = mqtt.Client(callback_api_version=CallbackAPIVersion.VERSION1)
    except ImportError:
        client = mqtt.Client()

    # Assign callbacks
    client.on_connect = on_connect
    client.on_message = on_message

    # Attempt connection
    try:
        print(f"Connecting to broker at {MQTT_BROKER}...")
        client.connect(MQTT_BROKER, MQTT_PORT, keepalive=60)
    except Exception as e:
        print(f"Failed to connect to broker: {e}", file=sys.stderr)
        print("Please ensure Mosquitto broker is running. Exiting.", file=sys.stderr)
        sys.exit(1)

    # Start network loop (handles auto-reconnect automatically)
    print("Starting listener loop. Press Ctrl+C to exit.")
    try:
        client.loop_forever()
    except KeyboardInterrupt:
        print("\nStopping receiver... Goodbye!")
        client.disconnect()

if __name__ == "__main__":
    main()
