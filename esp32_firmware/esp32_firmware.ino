#include <WiFi.h>
#include <PubSubClient.h>
#include <Wire.h>
#include <Adafruit_MPU6050.h>
#include <Adafruit_Sensor.h>
#include <Adafruit_ADXL345_U.h>
#include <DHT.h>
#include <vector>

// ==========================================
// CONFIGURATION
// ==========================================

// Wi-Fi
const char* ssid     = "Pi4B-Hotspot";
const char* password = "abcdefgh";

// MQTT
const char* mqtt_server    = "10.42.0.1";
const int   mqtt_port      = 1883;
const char* mqtt_topic     = "esp32/sensor_data";
const char* mqtt_client_id = "esp32_sensor_node_2";

// ==========================================
// PIN CONFIGURATION
// ==========================================

// SW-420 vibration sensor
const int SW420_PIN = 13;

// I2C
const int SDA_PIN = 21;
const int SCL_PIN = 22;

// HC-SR04
const int HCSR04_TRIG_PIN = 25;
const int HCSR04_ECHO_PIN = 26;

// Buzzer
const int BUZZER_PIN = 27;

// MQ-2 analog output
const int MQ2_PIN = 34;

// DHT11
const int DHT_PIN = 33;

// DHT sensor type
#define DHTTYPE DHT11

// ==========================================
// I2C ADDRESSES
// ==========================================

// ADXL345
const uint8_t ADXL345_ADDRESS = 0x53;

// MPU6050
const uint8_t MPU6050_ADDRESS = 0x69;

// ==========================================
// SENSOR SETTINGS
// ==========================================

const float BUZZER_DISTANCE_THRESHOLD = 50.0;
const unsigned long SENSOR_INTERVAL = 5000;
const unsigned long RECONNECT_INTERVAL = 10000;

// ==========================================
// DATA STRUCTURE
// ==========================================

struct DataPoint {
  uint32_t seq;
  uint32_t timestamp_ms;

  // SW-420
  int vibration;

  // ADXL345
  float adxl_ax;
  float adxl_ay;
  float adxl_az;

  // MPU6050
  float mpu_ax;
  float mpu_ay;
  float mpu_az;
  float mpu_gx;
  float mpu_gy;
  float mpu_gz;

  // HC-SR04
  float distance_cm;

  // Buzzer
  int buzzer;

  // MQ-2
  int mq2_raw;

  // DHT11
  float temperature;
  float humidity;
};

// ==========================================
// BUFFER
// ==========================================

const size_t MAX_BUFFER_SIZE = 1000;
std::vector<DataPoint> dataBuffer;
uint32_t sequenceNumber = 0;

// ==========================================
// NETWORK
// ==========================================

WiFiClient espClient;
PubSubClient mqttClient(espClient);

// ==========================================
// SENSOR OBJECTS
// ==========================================

Adafruit_MPU6050 mpu;
Adafruit_ADXL345_Unified adxl = Adafruit_ADXL345_Unified(12345);
DHT dht(DHT_PIN, DHTTYPE);

// ==========================================
// SENSOR STATE
// ==========================================

bool mpu_initialized = false;
bool adxl_initialized = false;
volatile bool vibrationTriggered = false;

// ==========================================
// TIMING
// ==========================================

unsigned long lastSensorReadTime = 0;
unsigned long lastReconnectAttempt = 0;

// ==========================================
// FUNCTION DECLARATIONS
// ==========================================

void setupWiFi();
void connectToMQTT();
float readDistance();
void readSensors(
  int &vib,
  float &adxl_ax, float &adxl_ay, float &adxl_az,
  float &mpu_ax, float &mpu_ay, float &mpu_az,
  float &mpu_gx, float &mpu_gy, float &mpu_gz,
  float &distance,
  int &mq2_raw,
  float &temperature,
  float &humidity
);
bool publishDataPoint(const DataPoint &dp);
void processQueue();

// ==========================================
// SW-420 INTERRUPT
// ==========================================

void IRAM_ATTR handleVibrationInterrupt() {
  vibrationTriggered = true;
}

// ==========================================
// SETUP
// ==========================================

void setup() {
  Serial.begin(115200);
  delay(1000);

  Serial.println();
  Serial.println("==================================================");
  Serial.println(" ESP32 SENSOR NODE");
  Serial.println(" ADXL345 + MPU6050 + SW-420 + HC-SR04");
  Serial.println(" MQ-2 + DHT11");
  Serial.println("==================================================");

  // SW-420
  pinMode(SW420_PIN, INPUT);
  attachInterrupt(
    digitalPinToInterrupt(SW420_PIN),
    handleVibrationInterrupt,
    RISING
  );
  Serial.printf("[SW420] Interrupt attached to GPIO %d\n", SW420_PIN);

  // HC-SR04
  pinMode(HCSR04_TRIG_PIN, OUTPUT);
  pinMode(HCSR04_ECHO_PIN, INPUT);
  digitalWrite(HCSR04_TRIG_PIN, LOW);
  Serial.printf("[HCSR04] TRIG = GPIO %d | ECHO = GPIO %d\n", HCSR04_TRIG_PIN, HCSR04_ECHO_PIN);

  // Buzzer
  pinMode(BUZZER_PIN, OUTPUT);
  digitalWrite(BUZZER_PIN, LOW);
  Serial.printf("[BUZZER] Output on GPIO %d\n", BUZZER_PIN);

  // MQ-2
  pinMode(MQ2_PIN, INPUT);
  analogSetPinAttenuation(MQ2_PIN, ADC_11db);
  Serial.printf("[MQ2] Analog output on GPIO %d\n", MQ2_PIN);

  // DHT11
  dht.begin();
  Serial.printf("[DHT11] Data on GPIO %d\n", DHT_PIN);

  // I2C
  Wire.begin(SDA_PIN, SCL_PIN);
  Wire.setClock(400000);
  Serial.printf("[I2C] SDA = GPIO %d | SCL = GPIO %d\n", SDA_PIN, SCL_PIN);

  // ADXL345
  Serial.println("[I2C] Initializing ADXL345 at 0x53...");
  if (adxl.begin(ADXL345_ADDRESS)) {
    Serial.println("[SUCCESS] ADXL345 initialized at 0x53");
    adxl_initialized = true;
    adxl.setRange(ADXL345_RANGE_16_G);
    adxl.setDataRate(ADXL345_DATARATE_100_HZ);
    Serial.println("[ADXL345] Range = +/-16g");
  } else {
    Serial.println("[ERROR] ADXL345 not found!");
    adxl_initialized = false;
  }

  // MPU6050
  Serial.println("[I2C] Initializing MPU6050 at 0x69...");
  if (mpu.begin(MPU6050_ADDRESS)) {
    Serial.println("[SUCCESS] MPU6050 initialized at 0x69");
    mpu_initialized = true;
    mpu.setAccelerometerRange(MPU6050_RANGE_8_G);
    mpu.setGyroRange(MPU6050_RANGE_500_DEG);
    mpu.setFilterBandwidth(MPU6050_BAND_21_HZ);
  } else {
    Serial.println("[ERROR] MPU6050 at 0x69 not found!");
    mpu_initialized = false;
  }

  // Wi-Fi & MQTT
  setupWiFi();
  mqttClient.setServer(mqtt_server, mqtt_port);
  mqttClient.setBufferSize(1024);

  Serial.println();
  Serial.println("System initialized. Starting measurement loop...");
}

// ==========================================
// MAIN LOOP
// ==========================================

void loop() {
  unsigned long now = millis();

  // SENSOR SAMPLING
  if (
    now - lastSensorReadTime >= SENSOR_INTERVAL ||
    lastSensorReadTime == 0
  ) {
    lastSensorReadTime = now;

    int vib = 0;
    float adxl_ax = 0.0, adxl_ay = 0.0, adxl_az = 0.0;
    float mpu_ax = 0.0, mpu_ay = 0.0, mpu_az = 0.0;
    float mpu_gx = 0.0, mpu_gy = 0.0, mpu_gz = 0.0;
    float distance = -1.0;
    int mq2_raw = 0;
    float temperature = NAN;
    float humidity = NAN;

    readSensors(
      vib,
      adxl_ax, adxl_ay, adxl_az,
      mpu_ax, mpu_ay, mpu_az,
      mpu_gx, mpu_gy, mpu_gz,
      distance,
      mq2_raw,
      temperature,
      humidity
    );

    // Buzzer logic
    bool buzzerActive = (distance > 0 && distance < BUZZER_DISTANCE_THRESHOLD);
    digitalWrite(BUZZER_PIN, buzzerActive ? HIGH : LOW);

    // Create data point
    sequenceNumber++;
    DataPoint dp = {
      sequenceNumber,
      now,
      vib,
      adxl_ax, adxl_ay, adxl_az,
      mpu_ax, mpu_ay, mpu_az,
      mpu_gx, mpu_gy, mpu_gz,
      distance,
      buzzerActive ? 1 : 0,
      mq2_raw,
      temperature,
      humidity
    };

    // Buffer management
    if (dataBuffer.size() >= MAX_BUFFER_SIZE) {
      Serial.println("[WARNING] Buffer full! Dropping oldest data point.");
      dataBuffer.erase(dataBuffer.begin());
    }
    dataBuffer.push_back(dp);

    // Serial output
    Serial.printf(
      "[SENSOR] #%lu | Vib=%d | ADXL345 A=[%.2f, %.2f, %.2f] | MPU6050 A=[%.2f, %.2f, %.2f] G=[%.2f, %.2f, %.2f] | Dist=%.2f cm | Buzzer=%d | MQ2=%d | Temp=%.2f C | Humidity=%.2f %% | Buffer=%d/%d\n",
      (unsigned long)dp.seq,
      dp.vibration,
      dp.adxl_ax, dp.adxl_ay, dp.adxl_az,
      dp.mpu_ax, dp.mpu_ay, dp.mpu_az,
      dp.mpu_gx, dp.mpu_gy, dp.mpu_gz,
      dp.distance_cm,
      dp.buzzer,
      dp.mq2_raw,
      dp.temperature,
      dp.humidity,
      (int)dataBuffer.size(),
      (int)MAX_BUFFER_SIZE
    );
  }

  // NETWORK MANAGEMENT
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

  // MQTT QUEUE PROCESSING
  if (WiFi.status() == WL_CONNECTED && mqttClient.connected()) {
    mqttClient.loop();
    processQueue();
  }
}

// ==========================================
// WIFI
// ==========================================

void setupWiFi() {
  Serial.printf("[WIFI] Connecting to %s ...\n", ssid);
  
  // Clean up any existing connection state and force STA mode
  WiFi.disconnect(true);
  delay(200);
  WiFi.mode(WIFI_STA);
  delay(200);

  WiFi.setHostname("esp32-sensor-node-2");
  WiFi.begin(ssid, password);

  int attempts = 0;
  while (WiFi.status() != WL_CONNECTED && attempts < 20) {
    delay(500);
    Serial.print(".");
    attempts++;
  }

  if (WiFi.status() == WL_CONNECTED) {
    Serial.println();
    Serial.print("[WIFI] Connected! IP Address: ");
    Serial.println(WiFi.localIP());
  } else {
    Serial.println();
    Serial.println("[WIFI] Connection failed. Will retry in background.");
  }
}

// ==========================================
// MQTT
// ==========================================

void connectToMQTT() {
  Serial.print("[MQTT] Connecting to broker... ");
  if (mqttClient.connect(mqtt_client_id)) {
    Serial.println("Connected!");
  } else {
    Serial.printf("Failed, rc=%d. Will retry in background.\n", mqttClient.state());
  }
}

// ==========================================
// SENSOR READING
// ==========================================

void readSensors(
  int &vib,
  float &adxl_ax, float &adxl_ay, float &adxl_az,
  float &mpu_ax, float &mpu_ay, float &mpu_az,
  float &mpu_gx, float &mpu_gy, float &mpu_gz,
  float &distance,
  int &mq2_raw,
  float &temperature,
  float &humidity
) {
  // SW-420
  if (vibrationTriggered) {
    vib = 1;
    vibrationTriggered = false;
  } else {
    vib = 0;
  }

  // ADXL345
  if (adxl_initialized) {
    sensors_event_t event;
    adxl.getEvent(&event);
    adxl_ax = event.acceleration.x;
    adxl_ay = event.acceleration.y;
    adxl_az = event.acceleration.z;
  } else {
    Serial.println("[ERROR] ADXL345 is not initialized.");
  }

  // MPU6050
  if (mpu_initialized) {
    sensors_event_t a, g, temp;
    if (mpu.getEvent(&a, &g, &temp)) {
      mpu_ax = a.acceleration.x;
      mpu_ay = a.acceleration.y;
      mpu_az = a.acceleration.z;
      mpu_gx = g.gyro.x;
      mpu_gy = g.gyro.y;
      mpu_gz = g.gyro.z;
    } else {
      Serial.println("[ERROR] Failed to read MPU6050.");
    }
  } else {
    Serial.println("[ERROR] MPU6050 is not initialized.");
  }

  // HC-SR04
  distance = readDistance();

  // MQ-2
  mq2_raw = analogRead(MQ2_PIN);

  // DHT11
  float newHumidity = dht.readHumidity();
  float newTemperature = dht.readTemperature();

  if (isnan(newHumidity) || isnan(newTemperature)) {
    Serial.println("[ERROR] Failed to read DHT11.");
  } else {
    humidity = newHumidity;
    temperature = newTemperature;
  }
}

// ==========================================
// HC-SR04
// ==========================================

float readDistance() {
  digitalWrite(HCSR04_TRIG_PIN, LOW);
  delayMicroseconds(2);
  digitalWrite(HCSR04_TRIG_PIN, HIGH);
  delayMicroseconds(10);
  digitalWrite(HCSR04_TRIG_PIN, LOW);

  unsigned long duration = pulseInLong(
    HCSR04_ECHO_PIN,
    HIGH,
    30000
  );

  if (duration == 0) {
    Serial.println("[HCSR04] No echo received!");
    return -1.0;
  }

  float distance = (duration * 0.0343) / 2.0;
  return distance;
}

// ==========================================
// MQTT DATA PUBLISH
// ==========================================

bool publishDataPoint(const DataPoint &dp) {
  char payload[800];
  bool validDHT = !isnan(dp.temperature) && !isnan(dp.humidity);

  if (validDHT) {
    snprintf(
      payload,
      sizeof(payload),
      "{"
        "\"dev\":\"%s\","
        "\"seq\":%lu,"
        "\"ms\":%lu,"
        "\"vib\":%d,"
        "\"adxl345\":{"
          "\"ax\":%.3f,"
          "\"ay\":%.3f,"
          "\"az\":%.3f"
        "},"
        "\"mpu6050\":{"
          "\"ax\":%.3f,"
          "\"ay\":%.3f,"
          "\"az\":%.3f,"
          "\"gx\":%.3f,"
          "\"gy\":%.3f,"
          "\"gz\":%.3f"
        "},"
        "\"distance_cm\":%.2f,"
        "\"buzzer\":%d,"
        "\"mq2_raw\":%d,"
        "\"temperature\":%.2f,"
        "\"humidity\":%.2f"
      "}",
      mqtt_client_id,
      (unsigned long)dp.seq,
      (unsigned long)dp.timestamp_ms,
      dp.vibration,
      dp.adxl_ax, dp.adxl_ay, dp.adxl_az,
      dp.mpu_ax, dp.mpu_ay, dp.mpu_az,
      dp.mpu_gx, dp.mpu_gy, dp.mpu_gz,
      dp.distance_cm,
      dp.buzzer,
      dp.mq2_raw,
      dp.temperature,
      dp.humidity
    );
  } else {
    snprintf(
      payload,
      sizeof(payload),
      "{"
        "\"dev\":\"%s\","
        "\"seq\":%lu,"
        "\"ms\":%lu,"
        "\"vib\":%d,"
        "\"adxl345\":{"
          "\"ax\":%.3f,"
          "\"ay\":%.3f,"
          "\"az\":%.3f"
        "},"
        "\"mpu6050\":{"
          "\"ax\":%.3f,"
          "\"ay\":%.3f,"
          "\"az\":%.3f,"
          "\"gx\":%.3f,"
          "\"gy\":%.3f,"
          "\"gz\":%.3f"
        "},"
        "\"distance_cm\":%.2f,"
        "\"buzzer\":%d,"
        "\"mq2_raw\":%d,"
        "\"temperature\":null,"
        "\"humidity\":null"
      "}",
      mqtt_client_id,
      (unsigned long)dp.seq,
      (unsigned long)dp.timestamp_ms,
      dp.vibration,
      dp.adxl_ax, dp.adxl_ay, dp.adxl_az,
      dp.mpu_ax, dp.mpu_ay, dp.mpu_az,
      dp.mpu_gx, dp.mpu_gy, dp.mpu_gz,
      dp.distance_cm,
      dp.buzzer,
      dp.mq2_raw
    );
  }

  return mqttClient.publish(mqtt_topic, payload);
}

// ==========================================
// QUEUE PROCESSING
// ==========================================

void processQueue() {
  while (!dataBuffer.empty()) {
    const DataPoint &dp = dataBuffer.front();

    Serial.printf("[QUEUE] Attempting to publish #%lu ... ", (unsigned long)dp.seq);
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
