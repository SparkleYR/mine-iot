#include <WiFi.h>
#include <PubSubClient.h>
#include <vector>

// ==========================================
// CONFIGURATION - Change these to match your setup
// ==========================================
const char* ssid          = "Pi4B-Hotspot";
const char* password      = "abcdefgh";
const char* mqtt_server   = "10.42.0.1"; // IP Address of your Raspberry Pi 4B Hotspot
const int mqtt_port       = 1883;            // Default Mosquitto MQTT port
const char* mqtt_topic    = "esp32/sensor_data";
const char* mqtt_client_id = "esp32_sensor_node";

// Sampling intervals (in milliseconds)
const unsigned long SENSOR_INTERVAL = 5000;    // Read sensor every 5 seconds
const unsigned long RECONNECT_INTERVAL = 10000; // Retry connection every 10 seconds

// ==========================================
// DATA STRUCTURES & BUFFERING
// ==========================================
struct DataPoint {
  uint32_t seq;
  uint32_t timestamp_ms;
  float temperature;
  float humidity;
};

// RAM-based circular buffer
const size_t MAX_BUFFER_SIZE = 1000; // Limit buffer to avoid Out-Of-Memory (OOM)
std::vector<DataPoint> dataBuffer;
uint32_t sequenceNumber = 0;

// Network Clients
WiFiClient espClient;
PubSubClient mqttClient(espClient);

// Timing variables
unsigned long lastSensorReadTime = 0;
unsigned long lastReconnectAttempt = 0;

// ==========================================
// FUNCTION DECLARATIONS
// ==========================================
void setupWiFi();
void connectToMQTT();
void readSensor(float &temp, float &hum);
bool publishDataPoint(const DataPoint &dp);
void processQueue();

// ==========================================
// SETUP & LOOP
// ==========================================
void setup() {
  Serial.begin(115200);
  delay(1000);
  Serial.println("\n--- ESP32 Reliable Data Client Starting ---");

  setupWiFi();
  mqttClient.setServer(mqtt_server, mqtt_port);
  
  Serial.println("System initialized. Starting measurement loop.");
}

void loop() {
  unsigned long now = millis();

  // 1. Read sensor and queue data at fixed intervals
  if (now - lastSensorReadTime >= SENSOR_INTERVAL || lastSensorReadTime == 0) {
    lastSensorReadTime = now;
    
    float temp = 0.0;
    float hum = 0.0;
    readSensor(temp, hum);
    
    sequenceNumber++;
    DataPoint dp = { sequenceNumber, now, temp, hum };

    // Prevent buffer overflow (FIFO style)
    if (dataBuffer.size() >= MAX_BUFFER_SIZE) {
      Serial.println("[WARNING] Buffer full! Dropping oldest data point.");
      dataBuffer.erase(dataBuffer.begin());
    }
    
    dataBuffer.push_back(dp);
    Serial.printf("[SENSOR] Read #%u: Temp=%.2fC, Hum=%.2f%%. Buffer size: %d/%d\n", 
                  dp.seq, dp.temperature, dp.humidity, dataBuffer.size(), MAX_BUFFER_SIZE);
  }

  // 2. Manage Wi-Fi and MQTT connection non-blockingly
  if (WiFi.status() != WL_CONNECTED) {
    // If Wi-Fi is lost, trigger reconnect logic
    if (now - lastReconnectAttempt >= RECONNECT_INTERVAL) {
      lastReconnectAttempt = now;
      setupWiFi();
    }
  } else if (!mqttClient.connected()) {
    // If Wi-Fi is OK but MQTT is down, reconnect to broker
    if (now - lastReconnectAttempt >= RECONNECT_INTERVAL) {
      lastReconnectAttempt = now;
      connectToMQTT();
    }
  }

  // 3. Process the queue if we are online
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
  
  // Set host name for easy identification
  WiFi.setHostname("esp32-sensor-node");
  WiFi.begin(ssid, password);
  
  // Non-blocking connection check for setup, but we don't stall the main loop during execution
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
  // Attempt to connect
  if (mqttClient.connect(mqtt_client_id)) {
    Serial.println("Connected!");
  } else {
    Serial.printf("Failed, rc=%d. Will retry in background.\n", mqttClient.state());
  }
}

// ==========================================
// CORE DATA PROCESSING & SENDING
// ==========================================
void readSensor(float &temp, float &hum) {
  // Mock sensor implementation (replace with actual DHT22/BME280 etc. code)
  // Generating smooth sinewave sensor values for testing
  double angle = (millis() / 50000.0);
  temp = 22.0 + 5.0 * sin(angle);         // Simulates 17C - 27C
  hum  = 50.0 + 15.0 * cos(angle * 0.5);  // Simulates 35% - 65%
}

bool publishDataPoint(const DataPoint &dp) {
  // Construct a minimal JSON payload
  char payload[128];
  snprintf(payload, sizeof(payload), 
           "{\"seq\":%u,\"ms\":%u,\"temp\":%.2f,\"hum\":%.2f}", 
           dp.seq, dp.timestamp_ms, dp.temperature, dp.humidity);

  // Publish to broker
  return mqttClient.publish(mqtt_topic, payload);
}

void processQueue() {
  // Flush queue in FIFO order
  while (!dataBuffer.empty()) {
    // Peek at oldest data point
    const DataPoint &dp = dataBuffer.front();
    
    Serial.printf("[QUEUE] Attempting to publish #%u (buffered)... ", dp.seq);
    
    if (publishDataPoint(dp)) {
      Serial.println("Success!");
      // Remove from buffer on successful transmission
      dataBuffer.erase(dataBuffer.begin());
    } else {
      Serial.println("Failed. Stopping queue processing.");
      break; // Stop processing queue if publish fails, retry next loop
    }
    
    // Tiny delay to avoid flooding the broker / network stack
    delay(10);
  }
}
