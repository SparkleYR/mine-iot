# Reliable IoT Data Sharing: ESP32 & ESP32-CAM to Raspberry Pi 4B

This repository contains a robust, multi-node IoT data & image streaming system between **ESP32 microcontrollers**, **ESP32-CAM module**, and a **Raspberry Pi 4B**.

This repository includes:
* **ESP32 Telemetry Node**: ADXL345, MPU6050, SW-420, HC-SR04, Buzzer, MQ-2, and DHT11 sensors over MQTT.
* **ESP32-CAM Node**: Automatic periodic capture & on-demand image uploads over HTTP POST.
* **Pi Telemetry Receiver**: SQLite storage with 19 schema columns (`receiver.py`).
* **Pi Image Upload Server**: Python HTTP image server (`image_server.py`) saving timestamped JPEGs to `pi_receiver/captured_images/`.
* **Wi-Fi Connection**: All nodes connect to the Pi's broadcast network (`Pi4B-Hotspot` SSID, Password: `abcdefgh`, Gateway IP: `10.42.0.1`).

---

## 📷 ESP32-CAM Setup & Operation

### 1. Features
* Connects to **`Pi4B-Hotspot`** (Password: `abcdefgh`).
* Runs a local Web Server on Port `80` with a live camera preview (`/capture`), Flash control (`/flash/on`, `/flash/off`), and a manual **CAPTURE & SEND NOW** button.
* Automatically uploads captured JPEG frames directly to the Raspberry Pi image server at `http://10.42.0.1:5000/upload`.
* The Pi saves each uploaded image in `pi_receiver/captured_images/` with a precise timestamp filename (e.g. `img_20260822_232256_984300.jpg`).

### 2. Flash the ESP32-CAM
1. Open the project file [esp32_cam_firmware.ino](esp32_cam_firmware/esp32_cam_firmware.ino) in Arduino IDE.
2. Select Board: **AI Thinker ESP32-CAM**.
3. Under **Tools**, set:
   * PSRAM: **Enabled** (if available)
   * Partition Scheme: **Huge APP (3MB No OTA/1MB SPIFFS)**
4. Connect GPIO 0 to GND while flashing, then disconnect GPIO 0 and press Reset.

---

## Hardware Pin Connections

### 1. ESP32 Sensor Node
| Sensor / Module | Sensor Pin | ESP32 Pin | Description |
| :--- | :--- | :--- | :--- |
| **ADXL345** | VCC / GND / SCL / SDA | 3.3V / GND / GPIO 22 / GPIO 21 | Accelerometer (0x53) |
| **MPU6050** | VCC / GND / SCL / SDA / AD0 | 3.3V / GND / GPIO 22 / GPIO 21 / 3.3V | Gyro/Accel (0x69) |
| **SW-420** | VCC / GND / DO | 3.3V / GND / GPIO 13 | Vibration Trigger Interrupt |
| **HC-SR04** | VCC / GND / TRIG / ECHO | 5V / GND / GPIO 25 / GPIO 26 | Ultrasonic Distance Sensor |
| **Buzzer** | positive (+) / GND | GPIO 27 / GND | Distance Alert (Active < 50cm) |
| **MQ-2** | VCC / GND / AO | 5V / GND / GPIO 34 | Gas/Smoke Sensor |
| **DHT11** | VCC / GND / DATA | 3.3V / GND / GPIO 33 | Temperature & Humidity |

### 2. AI Thinker ESP32-CAM Pinout
Standard AI Thinker GPIO mapping is pre-configured in [esp32_cam_firmware.ino](esp32_cam_firmware/esp32_cam_firmware.ino):
* Flash LED: **GPIO 4**
* Y2–Y9: **GPIO 5, 18, 19, 21, 36, 39, 34, 35**
* XCLK / PCLK / VSYNC / HREF: **GPIO 0, 22, 25, 23**
* SIOD (SDA) / SIOC (SCL): **GPIO 26, 27**

---

## Setup Guide

### Phase 1: Raspberry Pi Servers

1. **Activate Wi-Fi Hotspot on Pi**:
   ```bash
   sudo nmcli connection modify Hotspot 802-11-wireless.band bg 802-11-wireless.channel 6 connection.autoconnect yes
   sudo nmcli connection up Hotspot
   ```
2. **Start Telemetry & Image Receiver Daemons**:
   ```bash
   cd ~/mine-iot/pi_receiver
   source venv/bin/activate
   nohup python -u receiver.py > receiver.log 2>&1 &
   nohup python -u image_server.py > image_server.log 2>&1 &
   ```

---

### Phase 2: Viewing Captured Images on Pi / PC

Images captured by the ESP32-CAM are automatically saved to:
* **Raspberry Pi**: `/home/sih/mine-iot/pi_receiver/captured_images/`
* **Filename Format**: `img_YYYYMMDD_HHMMSS_microseconds.jpg`

To view the saved images on the Pi:
```bash
ls -la ~/mine-iot/pi_receiver/captured_images/
```
