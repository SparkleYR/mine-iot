#!/usr/bin/env python3
import time
import json
import random
import paho.mqtt.client as mqtt

# ==========================================
# CONFIGURATION
# ==========================================
MQTT_BROKER = "localhost"
MQTT_PORT = 1883
MQTT_TOPIC = "esp32/sensor_data"

def main():
    print("--- Starting Mock ESP32 Publisher (Full Sensors) ---")
    
    # Create MQTT client instance with compatibility for Paho 2.x
    try:
        from paho.mqtt.enums import CallbackAPIVersion
        client = mqtt.Client(callback_api_version=CallbackAPIVersion.VERSION1)
    except ImportError:
        client = mqtt.Client()

    try:
        client.connect(MQTT_BROKER, MQTT_PORT, keepalive=60)
        client.loop_start()
        print(f"Connected to broker at {MQTT_BROKER}")
    except Exception as e:
        print(f"Connection failed: {e}. Make sure mosquitto broker is running.")
        return

    seq = 0
    start_time = int(time.time() * 1000)

    try:
        # Scenario 1: Online publishing
        print("\n--- Scenario 1: Normal Online Publishing (5 messages) ---")
        for _ in range(5):
            seq += 1
            device_ms = int(time.time() * 1000) - start_time
            vib = random.choice([0, 0, 0, 1])
            dist = round(10.0 + random.uniform(0, 150), 2)
            buzzer = 1 if dist < 50.0 else 0
            mq2 = random.randint(200, 1500)
            
            # DHT11 sometimes None
            temp = round(20.0 + random.uniform(0, 15), 2) if random.random() > 0.1 else None
            hum = round(40.0 + random.uniform(0, 40), 2) if temp is not None else None
            
            # ADXL345
            adxl_ax = round(random.uniform(-0.5, 0.5), 3)
            adxl_ay = round(random.uniform(-0.5, 0.5), 3)
            adxl_az = round(9.8 + random.uniform(-0.2, 0.2), 3)
            
            # MPU6050
            mpu_ax = round(random.uniform(-0.5, 0.5), 3)
            mpu_ay = round(random.uniform(-0.5, 0.5), 3)
            mpu_az = round(9.8 + random.uniform(-0.2, 0.2), 3)
            mpu_gx = round(random.uniform(-0.1, 0.1), 3)
            mpu_gy = round(random.uniform(-0.1, 0.1), 3)
            mpu_gz = round(random.uniform(-0.1, 0.1), 3)
            
            payload = {
                "dev": "mock_esp32_1",
                "seq": seq,
                "ms": device_ms,
                "vib": vib,
                "adxl345": {
                    "ax": adxl_ax, "ay": adxl_ay, "az": adxl_az
                },
                "mpu6050": {
                    "ax": mpu_ax, "ay": mpu_ay, "az": mpu_az,
                    "gx": mpu_gx, "gy": mpu_gy, "gz": mpu_gz
                },
                "distance_cm": dist,
                "buzzer": buzzer,
                "mq2_raw": mq2,
                "temperature": temp,
                "humidity": hum
            }
            client.publish(MQTT_TOPIC, json.dumps(payload))
            print(f"Published: {payload}")
            time.sleep(2)

        # Scenario 2: Simulate buffering during a connection drop
        print("\n--- Scenario 2: Simulating Connection Drop / Local Buffering ---")
        print("We will generate 3 messages locally, but delay publishing to simulate a drop...")
        buffered_payloads = []
        for _ in range(3):
            seq += 1
            device_ms = int(time.time() * 1000) - start_time
            vib = random.choice([0, 1])
            dist = round(10.0 + random.uniform(0, 150), 2)
            buzzer = 1 if dist < 50.0 else 0
            mq2 = random.randint(200, 1500)
            
            temp = round(20.0 + random.uniform(0, 15), 2)
            hum = round(40.0 + random.uniform(0, 40), 2)
            
            # ADXL345
            adxl_ax = round(random.uniform(-1.5, 1.5), 3)
            adxl_ay = round(random.uniform(-1.5, 1.5), 3)
            adxl_az = round(9.8 + random.uniform(-1.0, 1.0), 3)
            
            # MPU6050
            mpu_ax = round(random.uniform(-1.5, 1.5), 3)
            mpu_ay = round(random.uniform(-1.5, 1.5), 3)
            mpu_az = round(9.8 + random.uniform(-1.0, 1.0), 3)
            mpu_gx = round(random.uniform(-0.5, 0.5), 3)
            mpu_gy = round(random.uniform(-0.5, 0.5), 3)
            mpu_gz = round(random.uniform(-0.5, 0.5), 3)
            
            buffered_payloads.append({
                "dev": "mock_esp32_1",
                "seq": seq,
                "ms": device_ms,
                "vib": vib,
                "adxl345": {
                    "ax": adxl_ax, "ay": adxl_ay, "az": adxl_az
                },
                "mpu6050": {
                    "ax": mpu_ax, "ay": mpu_ay, "az": mpu_az,
                    "gx": mpu_gx, "gy": mpu_gy, "gz": mpu_gz
                },
                "distance_cm": dist,
                "buzzer": buzzer,
                "mq2_raw": mq2,
                "temperature": temp,
                "humidity": hum
            })
            time.sleep(1)

        print(f"ESP32 Offline. Generated {len(buffered_payloads)} readings in RAM.")
        print("Simulating reconnecting in 5 seconds...")
        time.sleep(5)

        print("\nESP32 Reconnected! Flushing buffer in FIFO order...")
        for payload in buffered_payloads:
            client.publish(MQTT_TOPIC, json.dumps(payload))
            print(f"Flushed buffered: {payload}")
            time.sleep(0.5)

        print("\nSimulation completed successfully.")
        
    except KeyboardInterrupt:
        print("\nStopping publisher...")
    finally:
        client.loop_stop()
        client.disconnect()

if __name__ == "__main__":
    main()
