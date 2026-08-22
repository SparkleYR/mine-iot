#include <WiFi.h>
#include <PubSubClient.h>
#include <Wire.h>
#include <Adafruit_MPU6050.h>
#include <Adafruit_Sensor.h>
#include <vector>

// ==========================================
// CONFIGURATION
// ==========================================
const char* ssid          = "Pi4B-Hotspot";
const char* password      = "abcdefgh";
const char* mqtt_server   = "10.42.0.1";     // IP Address of Raspberry Pi 4B Hotspot
const int mqtt_port       = 1883;            // Default Mosquitto MQTT port
const char* mqtt_topic    = "esp32/sensor_data";
const char* mqtt_client_id = "esp32_sensor_node";

// Pins
const int SW420_PIN = 13; // SW-420 digital out pin

// Sampling intervals (in milliseconds)
const unsigned long SENSOR_INTERVAL = 5000;    // Read sensor every 5 seconds
const unsigned long RECONNECT_INTERVAL = 10000; // Retry connection every 10 seconds

// ==========================================
// DATA STRUCTURES & BUFFERING
// ==========================================
struct DataPoint {
  uint32_t seq;
  uint32_t timestamp_ms;
  int vibration;
  float ax, ay, az;
  float gx, gy, gz;
};

// RAM-based circular buffer
const size_t MAX_BUFFER_SIZE = 1000; // Limit buffer to avoid Out-Of-Memory (OOM)
std::vector<DataPoint> dataBuffer;
uint32_t sequenceNumber = 0;

// Network Clients
WiFiClient espClient;
PubSubClient mqttClient(espClient);
Adafruit_MPU6050 mpu;

// State flags
bool mpu_initialized = false;
volatile bool vibrationTriggered = false; // Latch for vibration interrupt

// Timing variables
unsigned long lastSensorReadTime = 0;
unsigned long lastReconnectAttempt = 0;

// ==========================================
// INTERRUPT SERVICE ROUTINES
// ==========================================
void IRAM_ATTR handleVibrationInterrupt() {
  vibrationTriggered = true;
}

// ==========================================
// FUNCTION DECLARATIONS
// ==========================================
void setupWiFi();
void connectToMQTT();
void readSensors(int &vib, float &ax, float &ay, float &az, float &gx, float &gy, float &gz);
bool publishDataPoint(const DataPoint &dp);
void processQueue();

// ==========================================
// SETUP & LOOP
// ==========================================
void setup() {
  Serial.begin(115200);
  delay(1000);
  Serial.println("\n--- ESP32 Reliable Data Client (MPU6050 & SW-420) Starting ---");

  // 1. Initialize SW-420 Sensor with Interrupt
  pinMode(SW420_PIN, INPUT);
  attachInterrupt(digitalPinToInterrupt(SW420_PIN), handleVibrationInterrupt, RISING);
  Serial.printf("SW-420 Interrupt attached to GPIO %d\n", SW420_PIN);

  // 2. Initialize MPU6050 I2C Sensor
  Wire.begin(21, 22); // Default SDA/SCL pins
  if (!mpu.begin()) {
    Serial.println("[ERROR] Failed to find MPU6050 chip! Check connection/wiring. Will report 0.0.");
  } else {
    Serial.println("[SUCCESS] MPU6050 initialized.");
    mpu_initialized = true;
    
    // Set sensor ranges & bandwidth
    mpu.setAccelerometerRange(MPU6050_RANGE_8_G);
    mpu.setGyroRange(MPU6050_RANGE_500_DEG);
    mpu.setFilterBandwidth(MPU6050_BAND_21_HZ);
  }

  // 3. Connect to networks
  setupWiFi();
  mqttClient.setServer(mqtt_server, mqtt_port);
  
  Serial.println("System initialized. Starting measurement loop.");
}

void loop() {
  unsigned long now = millis();

  // 1. Read sensor and queue data at fixed intervals
  if (now - lastSensorReadTime >= SENSOR_INTERVAL || lastSensorReadTime == 0) {
    lastSensorReadTime = now;
    
    int vib = 0;
    float ax = 0.0, ay = 0.0, az = 0.0;
    float gx = 0.0, gy = 0.0, gz = 0.0;
    
    readSensors(vib, ax, ay, az, gx, gy, gz);
    
    sequenceNumber++;
    DataPoint dp = { sequenceNumber, now, vib, ax, ay, az, gx, gy, gz };

    // Prevent buffer overflow (FIFO style)
    if (dataBuffer.size() >= MAX_BUFFER_SIZE) {
      Serial.println("[WARNING] Buffer full! Dropping oldest data point.");
      dataBuffer.erase(dataBuffer.begin());
    }
    
    dataBuffer.push_back(dp);
    Serial.printf("[SENSOR] Read #%u: Vib=%d, Accel=[%.2f,%.2f,%.2f], Gyro=[%.2f,%.2f,%.2f]. Buffer size: %d/%d\n", 
                  dp.seq, dp.vibration, dp.ax, dp.ay, dp.az, dp.gx, dp.gy, dp.gz, dataBuffer.size(), MAX_BUFFER_SIZE);
  }

  // 2. Manage Wi-Fi and MQTT connection non-blockingly
  if (WiFi.status() != WL_CONNECTED) {
    if (now - lastReconnectAttempt >= RECONNECT_INTERVAL) {
      lastReconnectAttempt = now;
      setupWiFi();
    }
  } else if (!mqttClient.connected()) {
    if (now - lastReconnectAttempt >= RECONNECT_INTERVAL) {
      lastReconnectAttempt = now;
      connectToMQTT();
    }
  }

  // 3. Process the queue if online
  if (WiFi.status() == WL_CONNECTED && mqttClient.connected()) {
    mqttClient.loop();
    processQueue();
  }
}

// ==========================================
// NETWORK & MQTT FUNCTIONS
// ==========================================
void setupWiFi() {
  Serial.printf("[WIFI] Connecting to %s ...\n", ssid);
  WiFi.setHostname("esp32-sensor-node");
  WiFi.begin(ssid, password);
  
  int attempts = 0;
  while (WiFi.status() != WL_CONNECTED && attempts < 10) {
    delay(500);
    Serial.print(".");
    attempts++;
  }
  
  if (WiFi.status() == WL_CONNECTED) {
    Serial.println("\n[WIFI] Connected! IP Address: " + WiFi.localIP().toString());
  } else {
    Serial.println("\n[WIFI] Connection failed. Will retry in background.");
  }
}

void connectToMQTT() {
  Serial.print("[MQTT] Connecting to broker... ");
  if (mqttClient.connect(mqtt_client_id)) {
    Serial.println("Connected!");
  } else {
    Serial.printf("Failed, rc=%d. Will retry in background.\n", mqttClient.state());
  }
}

// ==========================================
// CORE DATA PROCESSING & SENDING
// ==========================================
void readSensors(int &vib, float &ax, float &ay, float &az, float &gx, float &gy, float &gz) {
  // Read SW-420 vibration sensor state (check latch)
  if (vibrationTriggered) {
    vib = 1;
    vibrationTriggered = false; // Reset latch
  } else {
    vib = 0;
  }

  // Read MPU6050
  if (mpu_initialized) {
    sensors_event_t a, g, temp;
    if (mpu.getEvent(&a, &g, &temp)) {
      ax = a.acceleration.x;
      ay = a.acceleration.y;
      az = a.acceleration.z;
      gx = g.gyro.x;
      gy = g.gyro.y;
      gz = g.gyro.z;
    } else {
      Serial.println("[ERROR] Failed to get MPU6050 event reading.");
    }
  } else {
    // If not initialized, try to reinitialize
    if (mpu.begin()) {
      Serial.println("[SUCCESS] MPU6050 re-initialized successfully.");
      mpu_initialized = true;
    }
  }
}

bool publishDataPoint(const DataPoint &dp) {
  // Construct JSON payload
  char payload[256];
  snprintf(payload, sizeof(payload), 
           "{\"seq\":%u,\"ms\":%u,\"vib\":%d,\"ax\":%.3f,\"ay\":%.3f,\"az\":%.3f,\"gx\":%.3f,\"gy\":%.3f,\"gz\":%.3f}", 
           dp.seq, dp.timestamp_ms, dp.vibration, dp.ax, dp.ay, dp.az, dp.gx, dp.gy, dp.gz);

  return mqttClient.publish(mqtt_topic, payload);
}

void processQueue() {
  while (!dataBuffer.empty()) {
    const DataPoint &dp = dataBuffer.front();
    
    Serial.printf("[QUEUE] Attempting to publish #%u (buffered)... ", dp.seq);
    
    if (publishDataPoint(dp)) {
      Serial.println("Success!");
      dataBuffer.erase(dataBuffer.begin());
    } else {
      Serial.println("Failed. Stopping queue processing.");
      break; 
    }
    
    delay(10);
  }
}
