#!/usr/bin/env python3
import time
import json
import sys
import paho.mqtt.client as mqtt

# ==========================================
# CONFIGURATION
# ==========================================
MQTT_BROKER = "localhost"
MQTT_PORT = 1883
MQTT_TOPIC = "esp32/sensor_data"
RECORD_DURATION = 900  # 15 minutes in seconds
OUTPUT_FILE = "telemetry_15min_dump.jsonl"

# State variables
start_time = None
record_count = 0

def on_connect(client, userdata, flags, rc):
    if rc == 0:
        print(f"Connected successfully to local MQTT Broker.")
        client.subscribe(MQTT_TOPIC)
        print(f"Waiting for first telemetry message on topic '{MQTT_TOPIC}'...")
    else:
        print(f"Connection failed with code {rc}", file=sys.stderr)
        sys.exit(1)

def on_message(client, userdata, msg):
    global start_time, record_count
    
    current_time = time.time()
    
    # Check if this is the first message to start the timer
    if start_time is None:
        start_time = current_time
        print(f"\n[START] First telemetry packet received! Starting {RECORD_DURATION/60:.1f} minutes recording.")
        print(f"Saving data to: {OUTPUT_FILE}")
        print("Recording...")

    elapsed_time = current_time - start_time
    
    if elapsed_time < RECORD_DURATION:
        try:
            payload_str = msg.payload.decode('utf-8')
            # Parse to ensure it is valid JSON
            payload = json.loads(payload_str)
            
            # Format entry with a receipt timestamp
            entry = {
                "received_at_epoch": current_time,
                "data": payload
            }
            
            # Write to JSONL file
            with open(OUTPUT_FILE, "a") as f:
                f.write(json.dumps(entry) + "\n")
                
            record_count += 1
            sys.stdout.write(f"\rCaptured packet #{record_count} (elapsed: {elapsed_time:.1f}s / {RECORD_DURATION}s)...")
            sys.stdout.flush()
            
        except Exception as e:
            print(f"\nError processing message: {e}", file=sys.stderr)
    else:
        # Duration exceeded, exit
        print(f"\n\n[COMPLETE] {RECORD_DURATION/60:.1f} minutes elapsed.")
        print(f"Successfully recorded {record_count} telemetry packets to '{OUTPUT_FILE}'.")
        client.disconnect()
        sys.exit(0)

def main():
    print("==================================================")
    print(" 15-Minute Telemetry Recorder")
    print("==================================================")
    
    # Create MQTT client instance with compatibility for Paho 2.x
    try:
        from paho.mqtt.enums import CallbackAPIVersion
        client = mqtt.Client(callback_api_version=CallbackAPIVersion.VERSION1)
    except ImportError:
        client = mqtt.Client()

    client.on_connect = on_connect
    client.on_message = on_message

    try:
        client.connect(MQTT_BROKER, MQTT_PORT, keepalive=60)
    except Exception as e:
        print(f"Failed to connect to broker: {e}", file=sys.stderr)
        sys.exit(1)

    try:
        client.loop_forever()
    except KeyboardInterrupt:
        print("\n\nRecording interrupted by user. Exiting.")
        sys.exit(0)

if __name__ == "__main__":
    main()
