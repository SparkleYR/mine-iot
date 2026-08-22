# Reliable IoT Data Sharing: ESP32 to Raspberry Pi 4B

This repository contains a robust, connection-drop-resilient data sharing system between an **ESP32 microcontroller** and a **Raspberry Pi 4B**.

## How It Works

To achieve high reliability over a wireless connection, the system uses **MQTT (Message Queuing Telemetry Transport)** over Wi-Fi:
1. **MQTT Broker**: Installed on the Raspberry Pi 4B to manage messages.
2. **ESP32 Firmware**: Periodically records sensor readings. If the Wi-Fi or MQTT broker is disconnected, readings are stored in a **RAM-based FIFO buffer** on the ESP32.
3. **Automatic Reconnection & Flush**: The ESP32 continuously attempts to reconnect in the background. Once the connection is re-established, the ESP32 flushes its local buffer in chronological order (FIFO), ensuring no data points are lost.
4. **Pi Receiver**: A Python client subscribes to the broker and writes all received sensor data to a local **SQLite database** (`sensor_data.db`) for long-term persistence.

```
+-------------------+             +-----------------------+             +------------------+
|   ESP32 Node      |             |   Raspberry Pi 4B     |             |  Data Storage    |
|                   |             |                       |             |                  |
|  [Sensor Loop]    |    Wi-Fi    |  [Mosquitto Broker]   |  sqlite3    |  [sensor_data]   |
|   Readings ->     | ==========> |   Listens on port     | ==========> |   SQLite DB      |
|  [RAM Buffer]     |             |   1883                |             |  (Persistent)    |
|  (if offline)     |             +-----------^-----------+             +------------------+
|                   |                         |
|  Auto-Reconnect   |                         | python3
|  & FIFO Flush     |                         |
|   when online     |             +-----------v-----------+
|                   |             |   [receiver.py]       |
+-------------------+             |   MQTT Subscriber     |
                                  +-----------------------+
```

---

## Step-by-step Setup Guide

### Phase 1: Setup Raspberry Pi 4B (Broker & Receiver)

#### 1. Install & Configure Mosquitto MQTT Broker
On your Raspberry Pi, run the following commands to install and start the Mosquitto broker:
```bash
# Update package list and install Mosquitto broker & clients
sudo apt update
sudo apt install -y mosquitto mosquitto-clients

# Enable Mosquitto to start automatically on system boot
sudo systemctl enable mosquitto

# Configure Mosquitto to allow remote connections (important for ESP32)
# Create a custom config file
sudo bash -c 'cat > /etc/mosquitto/conf.d/external.conf <<EOF
listener 1883
allow_anonymous true
EOF'

# Restart Mosquitto to apply the configuration
sudo systemctl restart mosquitto

# Verify that the service is running successfully
sudo systemctl status mosquitto
```

#### 2. Set Up the Python Receiver Script
Run these commands in the `pi_receiver/` folder on your Pi to install dependencies:
```bash
# Navigate to the receiver folder
cd pi_receiver

# Create a Python virtual environment (recommended)
python3 -m venv venv

# Activate the virtual environment
source venv/bin/activate

# Install requirements
pip install -r requirements.txt

# Run the receiver (it will start listening and create sensor_data.db)
python3 receiver.py
```

---

### Phase 2: Setup ESP32 Firmware

#### 1. Open the Code
Open the project file [esp32_firmware.ino](esp32_firmware/esp32_firmware.ino) in the Arduino IDE.

#### 2. Install Required Libraries
In the Arduino IDE:
1. Go to **Sketch** -> **Include Library** -> **Manage Libraries...**
2. Search for and install **PubSubClient** by Nick O'Leary.

#### 3. Configure Network Settings
At the top of `esp32_firmware.ino`, edit the configurations:
```cpp
const char* ssid          = "YOUR_WIFI_SSID";      // Your Wi-Fi name
const char* password      = "YOUR_WIFI_PASSWORD";  // Your Wi-Fi password
const char* mqtt_server   = "192.168.1.100";      // The local IP address of your Raspberry Pi 4B
```
> **Tip**: You can find your Pi's IP address by running `hostname -I` in the Raspberry Pi terminal.

#### 4. Upload Firmware
Connect your ESP32 to your computer via USB, select your board model under **Tools** -> **Board**, choose the correct port, and click **Upload**.

---

### Phase 3: Verification & Simulating Connection Drops

You can simulate connection drops and verify reliability without setting up physical ESP32 hardware using the included mock script.

#### 1. Launch the Receiver
In one terminal window on the Pi, run the receiver:
```bash
source pi_receiver/venv/bin/activate
python3 pi_receiver/receiver.py
```

#### 2. Run the Mock Publisher
In a second terminal window, run the mock publisher:
```bash
source pi_receiver/venv/bin/activate
python3 pi_receiver/mock_publisher.py
```
- **Scenario 1** will show real-time transmission. You will see outputs on both publisher and receiver terminals matching instantly.
- **Scenario 2** will simulate a connection drop. The publisher will buffer 3 messages, wait 5 seconds (simulating network outage), and then reconnect and flush them. You will see the receiver store all 3 messages with their original, correct sequence IDs and local relative timestamps.

#### 3. View Saved Data in SQLite
To inspect the saved data on the Pi:
```bash
sqlite3 pi_receiver/sensor_data.db "SELECT * FROM sensor_readings ORDER BY seq ASC;"
```

---

## Git Operations: Pushing to GitHub

Since this repository was initialized locally, you can push it to your own public GitHub repository with these steps:

1. **Create a Public GitHub Repository**:
   - Go to [GitHub](https://github.com) and log in.
   - Click the **New** repository button.
   - Name it (e.g. `mine-iot`), choose **Public**, and do **not** initialize it with a README, gitignore, or license (since we already have them).

2. **Run these commands in the project folder**:
   ```bash
   # Add your repository as the remote destination
   git remote add origin https://github.com/YOUR_GITHUB_USERNAME/YOUR_REPOSITORY_NAME.git
   
   # Push the branch to GitHub
   git push -u origin main
   ```
