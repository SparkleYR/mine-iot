# Reliable IoT Data Sharing: ESP32 to Raspberry Pi 4B (Vibration & Motion)

This repository contains a robust, connection-drop-resilient data sharing system between an **ESP32 microcontroller** and a **Raspberry Pi 4B**, collecting data from a **SW-420 vibration sensor** and an **MPU6050 gyroscope/accelerometer**.

## How It Works

To achieve high reliability over a wireless connection, the system uses **MQTT** over Wi-Fi:
1. **MQTT Broker**: Installed on the Raspberry Pi 4B.
2. **Wi-Fi AP (Hotspot)**: The Pi acts as the Wi-Fi Access Point (`Pi4B-Hotspot`), allowing direct connection.
3. **ESP32 Firmware**: Periodically records sensor readings. If Wi-Fi or the broker is disconnected, readings are stored in a **RAM-based FIFO buffer** on the ESP32.
4. **SW-420 Interrupt Latch**: An interrupt is attached to the SW-420 output pin (GPIO 13), latching any vibration trigger occurring within the sampling interval.
5. **Automatic Reconnection & Flush**: The ESP32 attempts reconnection in the background. When reconnected, it flushes the buffered data in chronological order.
6. **Pi Receiver**: A Python client subscribes and writes data to a local **SQLite database** (`sensor_data.db`).

```
+--------------------+             +-----------------------+             +------------------+
|    ESP32 Node      |             |   Raspberry Pi 4B     |             |  Data Storage    |
|                    |             |                       |             |                  |
|  [MPU6050 & SW420] |    Wi-Fi    |  [Mosquitto Broker]   |  sqlite3    |  [sensor_data]   |
|   Readings ->      | ==========> |   Listens on port     | ==========> |   SQLite DB      |
|  [RAM Buffer]      |             |   1883                |             |  (Persistent)    |
|  (if offline)      |             +-----------^-----------+             +------------------+
|                    |                         |
|  Auto-Reconnect    |                         | python3
|  & FIFO Flush      |                         |
|   when online      |             +-----------v-----------+
|                    |             |   [receiver.py]       |
+--------------------+             |   MQTT Subscriber     |
                                   +-----------------------+
```

---

## Hardware Pin Connections

| Sensor / Module | Sensor Pin | ESP32 Pin | Description |
| :--- | :--- | :--- | :--- |
| **MPU6050** | VCC | 3.3V | Power |
| | GND | GND | Ground |
| | SCL | GPIO 22 | I2C Clock (Default SCL) |
| | SDA | GPIO 21 | I2C Data (Default SDA) |
| **SW-420** | VCC | 3.3V / 5V | Power |
| | GND | GND | Ground |
| | DO | GPIO 13 | Digital Output (Vibration trigger) |

---

## Step-by-step Setup Guide

### Phase 1: Setup Raspberry Pi 4B (Broker, Hotspot & Receiver)

#### 1. Configure the Wi-Fi Hotspot on the Pi
Open a terminal on your Pi and run:
```bash
# Create and start the Wi-Fi Hotspot using NetworkManager
sudo nmcli device wifi hotspot ifname wlan0 ssid Pi4B-Hotspot password "abcdefgh"
```
The Pi's IP address on this hotspot interface will be `10.42.0.1`.

#### 2. Install & Configure Mosquitto MQTT Broker
```bash
# Install Mosquitto
sudo apt update
sudo apt install -y mosquitto mosquitto-clients
sudo systemctl enable mosquitto

# Allow remote connections
sudo bash -c 'cat > /etc/mosquitto/conf.d/external.conf <<EOF
listener 1883
allow_anonymous true
EOF'

# Restart service
sudo systemctl restart mosquitto
```

#### 3. Set Up the Python Receiver Script
```bash
cd pi_receiver

# Create & activate virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Run the receiver (creates database automatically)
python3 receiver.py
```

---

### Phase 2: Setup ESP32 Firmware

#### 1. Open the Code
Open the project file [esp32_firmware.ino](esp32_firmware/esp32_firmware.ino) in the Arduino IDE.

#### 2. Install Required Libraries
In the Arduino IDE (**Sketch** -> **Include Library** -> **Manage Libraries...**), search for and install:
1. **PubSubClient** by Nick O'Leary
2. **Adafruit MPU6050** by Adafruit
3. **Adafruit Unified Sensor** by Adafruit

#### 3. Upload Firmware
Connect your ESP32, select your board model and port under **Tools**, and click **Upload**.

---

### Phase 3: Verification & Simulation

#### 1. Run the Mock Simulation
Verify database schemas and connectivity on the Pi:
```bash
source pi_receiver/venv/bin/activate
python3 pi_receiver/mock_publisher.py
```
This simulates real-time data streaming, an offline period, and a queue flush.

#### 2. View Telemetry in SQLite
Run the following script to query the database and verify:
```bash
python3 -c "import sqlite3; conn = sqlite3.connect('pi_receiver/sensor_data.db'); c = conn.cursor(); c.execute('SELECT * FROM sensor_readings ORDER BY seq ASC'); [print(row) for row in c.fetchall()]; conn.close()"
```
Output columns correspond to: `[id, device_id, seq, device_ms, vibration, accel_x, accel_y, accel_z, gyro_x, gyro_y, gyro_z, received_at]`.
