# Reliable IoT Data Sharing: ESP32 to Raspberry Pi 4B (Multi-Sensor & Multi-Node)

This repository contains a robust, connection-drop-resilient data sharing system between multiple **ESP32 microcontrollers** and a **Raspberry Pi 4B**.

This version supports:
* **SW-420** Vibration Sensor
* **Dual MPU6050** Gyroscope/Accelerometer (0x68 and 0x69)
* **HC-SR04** Ultrasonic Distance Sensor
* **Multi-Node tracking** (`device_id` column in SQLite)
* **Wi-Fi connection** via your Wi-Fi network `VIRUS` (SSID: `VIRUS`, Password: `abcdefgh`).

---

## Hardware Pin Connections

On your ESP32, wire the sensors as follows:

| Sensor / Module | Sensor Pin | ESP32 Pin | Description |
| :--- | :--- | :--- | :--- |
| **MPU6050 #1** | VCC | 3.3V | Power |
| | GND | GND | Ground |
| | SCL | GPIO 22 | I2C Clock (Default SCL) |
| | SDA | GPIO 21 | I2C Data (Default SDA) |
| **MPU6050 #2 / GY-87** | VCC | 3.3V | Power |
| | GND | GND | Ground |
| | SCL | GPIO 22 | Shared I2C Clock |
| | SDA | GPIO 21 | Shared I2C Data |
| **SW-420** | VCC | 3.3V | Power |
| | GND | GND | Ground |
| | DO | GPIO 13 | Digital Output (Vibration trigger) |
| **HC-SR04** | VCC | 5V / VIN | Power |
| | GND | GND | Ground |
| | TRIG | GPIO 25 | Trigger Pulse Input |
| | ECHO | GPIO 26 | Echo Signal Output |

---

## Setup Guide

### Phase 1: Setup Raspberry Pi 4B

#### 1. Connect the Pi to your Wi-Fi
Connect your Pi to your Wi-Fi network **`VIRUS`** (Password: `abcdefgh`).
Once connected, the Pi's IP address on the Wi-Fi network is **`10.48.78.8`**.

#### 2. Run the Receiver Script
On the Pi, navigate to the `pi_receiver/` folder and run:
```bash
source venv/bin/activate
python3 receiver.py
```
This automatically handles database migrations to the new multi-sensor layout.

---

### Phase 2: Setup ESP32 Firmware

#### 1. Open and Configure Firmware
Open the project file [esp32_firmware.ino](esp32_firmware/esp32_firmware.ino) in the Arduino IDE.

* For **ESP32 #1**, set:
  ```cpp
  const char* mqtt_client_id = "esp32_sensor_node_1";
  ```
* For **ESP32 #2**, set:
  ```cpp
  const char* mqtt_client_id = "esp32_sensor_node_2";
  ```

#### 2. Install Required Libraries in Arduino IDE
Go to **Sketch** -> **Include Library** -> **Manage Libraries...** and install:
1. **PubSubClient** by Nick O'Leary
2. **Adafruit MPU6050** by Adafruit
3. **Adafruit Unified Sensor** by Adafruit

#### 3. Flash your ESP32
Connect your board, select the correct Port/Board under **Tools**, and click **Upload**.

---

### Phase 3: Verification & Simulation

#### 1. Run the Mock Simulation on the Pi
```bash
source pi_receiver/venv/bin/activate
python3 pi_receiver/mock_publisher.py
```

#### 2. View Telemetry in SQLite
Query the database on your Pi to verify:
```bash
python3 -c "import sqlite3; conn = sqlite3.connect('pi_receiver/sensor_data.db'); c = conn.cursor(); c.execute('SELECT * FROM sensor_readings ORDER BY seq ASC'); [print(row) for row in c.fetchall()]; conn.close()"
```
Output columns correspond to: `[id, device_id, seq, device_ms, vibration, mpu1_ax, mpu1_ay, mpu1_az, mpu1_gx, mpu1_gy, mpu1_gz, mpu2_ax, mpu2_ay, mpu2_az, mpu2_gx, mpu2_gy, mpu2_gz, distance_cm, received_at]`.
