# Reliable IoT Data Sharing: ESP32 to Raspberry Pi 4B (All Sensors & Multi-Node)

This repository contains a robust, connection-drop-resilient data sharing system between multiple **ESP32 microcontrollers** and a **Raspberry Pi 4B**.

This version supports:
* **ADXL345** Accelerometer (0x53)
* **MPU6050** Gyroscope/Accelerometer (0x69)
* **SW-420** Vibration Sensor
* **HC-SR04** Ultrasonic Distance Sensor
* **Buzzer** (Active when distance < 50.0 cm)
* **MQ-2** Gas/Smoke Sensor (Analog)
* **DHT11** Temperature & Humidity Sensor
* **Multi-Node tracking** (`device_id` column in SQLite)
* **Wi-Fi connection** via the Pi's broadcast network (`Pi4B-Hotspot` SSID, Password: `abcdefgh`, Broker: `10.42.0.1`).

---

## Hardware Pin Connections

On your ESP32, wire the sensors as follows:

| Sensor / Module | Sensor Pin | ESP32 Pin | Description |
| :--- | :--- | :--- | :--- |
| **ADXL345** | VCC | 3.3V | Power |
| | GND | GND | Ground |
| | SCL | GPIO 22 | I2C Clock (Shared SCL) |
| | SDA | GPIO 21 | I2C Data (Shared SDA) |
| **MPU6050** | VCC | 3.3V | Power |
| | GND | GND | Ground |
| | SCL | GPIO 22 | I2C Clock (Shared SCL) |
| | SDA | GPIO 21 | I2C Data (Shared SDA) |
| | AD0 | 3.3V | Address pin pulled HIGH to set to 0x69 |
| **SW-420** | VCC | 3.3V | Power |
| | GND | GND | Ground |
| | DO | GPIO 13 | Digital Output (Vibration trigger) |
| **HC-SR04** | VCC | 5V / VIN | Power |
| | GND | GND | Ground |
| | TRIG | GPIO 25 | Trigger Pulse Input |
| | ECHO | GPIO 26 | Echo Signal Output |
| **Buzzer** | positive (+) | GPIO 27 | Active Output Trigger |
| **MQ-2** | VCC | 5V / VIN | Power |
| | GND | GND | Ground |
| | AO | GPIO 34 | Analog Output (ADC1_CH6) |
| **DHT11** | VCC | 3.3V / 5V | Power |
| | GND | GND | Ground |
| | DATA | GPIO 33 | One-Wire Data Pin |

---

## Setup Guide

### Phase 1: Setup Raspberry Pi 4B

#### 1. Configure the Wi-Fi Hotspot on the Pi
Open a terminal on your Pi and run:
```bash
# Create and start the Wi-Fi Hotspot using NetworkManager
sudo nmcli device wifi hotspot ifname wlan0 ssid Pi4B-Hotspot password "abcdefgh"
```
The Pi's IP address on this hotspot interface will be `10.42.0.1`.

#### 2. Run the Receiver Script
On the Pi, navigate to the `pi_receiver/` folder and run:
```bash
source venv/bin/activate
python3 receiver.py
```
This automatically handles database migrations to the new layout.

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
3. **Adafruit ADXL345** by Adafruit
4. **Adafruit Unified Sensor** by Adafruit
5. **DHT sensor library** by Adafruit

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
Output columns correspond to: `[id, device_id, seq, device_ms, vibration, adxl_ax/y/z, mpu_ax/y/z, mpu_gx/y/z, distance_cm, buzzer, mq2_raw, temperature, humidity, received_at]`.
