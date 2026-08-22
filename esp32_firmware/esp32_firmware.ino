#include <WiFi.h>
#include <PubSubClient.h>
#include <Wire.h>
#include <Adafruit_MPU6050.h>
#include <Adafruit_Sensor.h>
#include <vector>

// ==========================================
// CONFIGURATION
// ==========================================

// Wi-Fi
const char* ssid           = "VIRUS";
const char* password       = "abcdefgh";

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

// HC-SR04
const int HCSR04_TRIG_PIN = 25;
const int HCSR04_ECHO_PIN = 26;

// I2C
const int SDA_PIN = 21;
const int SCL_PIN = 22;

// ==========================================
// SENSOR I2C ADDRESSES
// ==========================================

// Standalone MPU6050
const uint8_t MPU1_ADDRESS = 0x68;

// MPU6050 inside GY-87
const uint8_t MPU2_ADDRESS = 0x69;

// ==========================================
// SAMPLING / RECONNECT INTERVALS
// ==========================================

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

  // MPU6050 #1
  float ax1;
  float ay1;
  float az1;
  float gx1;
  float gy1;
  float gz1;

  // MPU6050 #2 / GY-87
  float ax2;
  float ay2;
  float az2;
  float gx2;
  float gy2;
  float gz2;

  // HC-SR04
  float distance_cm;
};

// ==========================================
// BUFFER
// ==========================================

const size_t MAX_BUFFER_SIZE = 1000;
std::vector<DataPoint> dataBuffer;
uint32_t sequenceNumber = 0;

// ==========================================
// NETWORK CLIENTS
// ==========================================

WiFiClient espClient;
PubSubClient mqttClient(espClient);

// ==========================================
// MPU6050 OBJECTS
// ==========================================

Adafruit_MPU6050 mpu1;
Adafruit_MPU6050 mpu2;

// ==========================================
// STATE FLAGS
// ==========================================

bool mpu1_initialized = false;
bool mpu2_initialized = false;
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

void readSensors(
  int &vib,

  float &ax1,
  float &ay1,
  float &az1,
  float &gx1,
  float &gy1,
  float &gz1,

  float &ax2,
  float &ay2,
  float &az2,
  float &gx2,
  float &gy2,
  float &gz2,

  float &distance
);

float readDistance();
bool publishDataPoint(const DataPoint &dp);
void processQueue();

// ==========================================
// INTERRUPT
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
  Serial.println("------------------------------------------");
  Serial.println(" ESP32 Sensor Node Starting");
  Serial.println("------------------------------------------");

  // ----------------------------------------
  // 1. SW-420
  // ----------------------------------------

  pinMode(SW420_PIN, INPUT);

  attachInterrupt(
    digitalPinToInterrupt(SW420_PIN),
    handleVibrationInterrupt,
    RISING
  );

  Serial.printf(
    "[SW420] Interrupt attached to GPIO %d\n",
    SW420_PIN
  );

  // ----------------------------------------
  // 2. HC-SR04
  // ----------------------------------------

  pinMode(HCSR04_TRIG_PIN, OUTPUT);
  pinMode(HCSR04_ECHO_PIN, INPUT);
  digitalWrite(HCSR04_TRIG_PIN, LOW);

  Serial.printf(
    "[HCSR04] TRIG = GPIO %d, ECHO = GPIO %d\n",
    HCSR04_TRIG_PIN,
    HCSR04_ECHO_PIN
  );

  // ----------------------------------------
  // 3. I2C
  // ----------------------------------------

  Wire.begin(SDA_PIN, SCL_PIN);
  Wire.setClock(400000);

  Serial.printf(
    "[I2C] SDA = GPIO %d, SCL = GPIO %d\n",
    SDA_PIN,
    SCL_PIN
  );

  // ----------------------------------------
  // 4. MPU6050 #1
  // Address = 0x68
  // ----------------------------------------

  if (!mpu1.begin(MPU1_ADDRESS)) {
    Serial.println(
      "[ERROR] MPU6050 #1 at 0x68 not found!"
    );
    mpu1_initialized = false;
  } else {
    Serial.println(
      "[SUCCESS] MPU6050 #1 initialized at 0x68"
    );
    mpu1_initialized = true;
    mpu1.setAccelerometerRange(MPU6050_RANGE_8_G);
    mpu1.setGyroRange(MPU6050_RANGE_500_DEG);
    mpu1.setFilterBandwidth(MPU6050_BAND_21_HZ);
  }

  // ----------------------------------------
  // 5. MPU6050 #2 inside GY-87
  // Address = 0x69
  // ----------------------------------------

  if (!mpu2.begin(MPU2_ADDRESS)) {
    Serial.println(
      "[ERROR] GY-87 MPU6050 at 0x69 not found!"
    );
    mpu2_initialized = false;
  } else {
    Serial.println(
      "[SUCCESS] GY-87 MPU6050 initialized at 0x69"
    );
    mpu2_initialized = true;
    mpu2.setAccelerometerRange(MPU6050_RANGE_8_G);
    mpu2.setGyroRange(MPU6050_RANGE_500_DEG);
    mpu2.setFilterBandwidth(MPU6050_BAND_21_HZ);
  }

  // ----------------------------------------
  // 6. Wi-Fi
  // ----------------------------------------

  setupWiFi();

  // ----------------------------------------
  // 7. MQTT
  // ----------------------------------------

  mqttClient.setServer(
    mqtt_server,
    mqtt_port
  );

  Serial.println();
  Serial.println(
    "System initialized. Starting measurement loop."
  );
}

// ==========================================
// MAIN LOOP
// ==========================================

void loop() {
  unsigned long now = millis();

  // ----------------------------------------
  // 1. SENSOR SAMPLING
  // ----------------------------------------

  if (
    now - lastSensorReadTime >= SENSOR_INTERVAL ||
    lastSensorReadTime == 0
  ) {
    lastSensorReadTime = now;

    int vib = 0;

    // MPU #1
    float ax1 = 0.0;
    float ay1 = 0.0;
    float az1 = 0.0;
    float gx1 = 0.0;
    float gy1 = 0.0;
    float gz1 = 0.0;

    // MPU #2
    float ax2 = 0.0;
    float ay2 = 0.0;
    float az2 = 0.0;
    float gx2 = 0.0;
    float gy2 = 0.0;
    float gz2 = 0.0;

    // Distance
    float distance = -1.0;

    // Read everything
    readSensors(
      vib,
      ax1, ay1, az1, gx1, gy1, gz1,
      ax2, ay2, az2, gx2, gy2, gz2,
      distance
    );

    // Create data point
    sequenceNumber++;
    DataPoint dp = {
      sequenceNumber,
      now,
      vib,
      ax1, ay1, az1, gx1, gy1, gz1,
      ax2, ay2, az2, gx2, gy2, gz2,
      distance
    };

    // Buffer management
    if (dataBuffer.size() >= MAX_BUFFER_SIZE) {
      Serial.println(
        "[WARNING] Buffer full! Dropping oldest data point."
      );
      dataBuffer.erase(dataBuffer.begin());
    }
    dataBuffer.push_back(dp);

    // Serial output
    Serial.printf(
      "[SENSOR] #%lu | "
      "Vib=%d | "
      "MPU1 A=[%.2f, %.2f, %.2f] "
      "G=[%.2f, %.2f, %.2f] | "
      "MPU2 A=[%.2f, %.2f, %.2f] "
      "G=[%.2f, %.2f, %.2f] | "
      "Dist=%.2f cm | "
      "Buffer=%d/%d\n",
      (unsigned long)dp.seq,
      dp.vibration,
      dp.ax1, dp.ay1, dp.az1, dp.gx1, dp.gy1, dp.gz1,
      dp.ax2, dp.ay2, dp.az2, dp.gx2, dp.gy2, dp.gz2,
      dp.distance_cm,
      (int)dataBuffer.size(),
      (int)MAX_BUFFER_SIZE
    );
  }

  // ----------------------------------------
  // 2. NETWORK MANAGEMENT
  // ----------------------------------------

  if (WiFi.status() != WL_CONNECTED) {
    if (
      now - lastReconnectAttempt >=
      RECONNECT_INTERVAL
    ) {
      lastReconnectAttempt = now;
      setupWiFi();
    }
  } else if (!mqttClient.connected()) {
    if (
      now - lastReconnectAttempt >=
      RECONNECT_INTERVAL
    ) {
      lastReconnectAttempt = now;
      connectToMQTT();
    }
  }

  // ----------------------------------------
  // 3. MQTT QUEUE PROCESSING
  // ----------------------------------------

  if (
    WiFi.status() == WL_CONNECTED &&
    mqttClient.connected()
  ) {
    mqttClient.loop();
    processQueue();
  }
}

// ==========================================
// WIFI
// ==========================================

void setupWiFi() {
  Serial.printf(
    "[WIFI] Connecting to %s ...\n",
    ssid
  );

  WiFi.setHostname(
    "esp32-sensor-node-2"
  );

  WiFi.begin(
    ssid,
    password
  );

  int attempts = 0;
  while (
    WiFi.status() != WL_CONNECTED &&
    attempts < 10
  ) {
    delay(500);
    Serial.print(".");
    attempts++;
  }

  if (WiFi.status() == WL_CONNECTED) {
    Serial.println();
    Serial.print(
      "[WIFI] Connected! IP Address: "
    );
    Serial.println(
      WiFi.localIP()
    );
  } else {
    Serial.println();
    Serial.println(
      "[WIFI] Connection failed. "
      "Will retry in background."
    );
  }
}

// ==========================================
// MQTT
// ==========================================

void connectToMQTT() {
  Serial.print(
    "[MQTT] Connecting to broker... "
  );

  if (
    mqttClient.connect(
      mqtt_client_id
    )
  ) {
    Serial.println(
      "Connected!"
    );
  } else {
    Serial.printf(
      "Failed, rc=%d. "
      "Will retry in background.\n",
      mqttClient.state()
    );
  }
}

// ==========================================
// SENSOR READING
// ==========================================

void readSensors(
  int &vib,
  float &ax1, float &ay1, float &az1, float &gx1, float &gy1, float &gz1,
  float &ax2, float &ay2, float &az2, float &gx2, float &gy2, float &gz2,
  float &distance
) {
  // SW-420
  if (vibrationTriggered) {
    vib = 1;
    vibrationTriggered = false;
  } else {
    vib = 0;
  }

  // MPU6050 #1
  if (mpu1_initialized) {
    sensors_event_t a1;
    sensors_event_t g1;
    sensors_event_t temp1;

    if (mpu1.getEvent(&a1, &g1, &temp1)) {
      ax1 = a1.acceleration.x;
      ay1 = a1.acceleration.y;
      az1 = a1.acceleration.z;
      gx1 = g1.gyro.x;
      gy1 = g1.gyro.y;
      gz1 = g1.gyro.z;
    } else {
      Serial.println(
        "[ERROR] Failed to read MPU6050 #1."
      );
    }
  } else {
    if (mpu1.begin(MPU1_ADDRESS)) {
      Serial.println(
        "[SUCCESS] MPU6050 #1 reinitialized."
      );
      mpu1_initialized = true;
    }
  }

  // MPU6050 #2 / GY-87
  if (mpu2_initialized) {
    sensors_event_t a2;
    sensors_event_t g2;
    sensors_event_t temp2;

    if (mpu2.getEvent(&a2, &g2, &temp2)) {
      ax2 = a2.acceleration.x;
      ay2 = a2.acceleration.y;
      az2 = a2.acceleration.z;
      gx2 = g2.gyro.x;
      gy2 = g2.gyro.y;
      gz2 = g2.gyro.z;
    } else {
      Serial.println(
        "[ERROR] Failed to read GY-87 MPU6050."
      );
    }
  } else {
    if (mpu2.begin(MPU2_ADDRESS)) {
      Serial.println(
        "[SUCCESS] GY-87 MPU6050 reinitialized."
      );
      mpu2_initialized = true;
    }
  }

  // HC-SR04
  distance = readDistance();
}

// ==========================================
// HC-SR04 DISTANCE
// ==========================================

float readDistance() {
  digitalWrite(HCSR04_TRIG_PIN, LOW);
  delayMicroseconds(2);
  digitalWrite(HCSR04_TRIG_PIN, HIGH);
  delayMicroseconds(10);
  digitalWrite(HCSR04_TRIG_PIN, LOW);

  unsigned long duration = pulseIn(
    HCSR04_ECHO_PIN,
    HIGH,
    30000
  );

  if (duration == 0) {
    return -1.0;
  }

  float distance = (duration * 0.0343) / 2.0;
  return distance;
}

// ==========================================
// MQTT DATA PUBLISH
// ==========================================

bool publishDataPoint(const DataPoint &dp) {
  char payload[600];

  snprintf(
    payload,
    sizeof(payload),
    "{"
      "\"dev\":\"%s\","
      "\"seq\":%lu,"
      "\"ms\":%lu,"
      "\"vib\":%d,"
      "\"mpu1\":{"
        "\"ax\":%.3f,"
        "\"ay\":%.3f,"
        "\"az\":%.3f,"
        "\"gx\":%.3f,"
        "\"gy\":%.3f,"
        "\"gz\":%.3f"
      "},"
      "\"mpu2\":{"
        "\"ax\":%.3f,"
        "\"ay\":%.3f,"
        "\"az\":%.3f,"
        "\"gx\":%.3f,"
        "\"gy\":%.3f,"
        "\"gz\":%.3f"
      "},"
      "\"distance_cm\":%.2f"
    "}",
    mqtt_client_id,
    (unsigned long)dp.seq,
    (unsigned long)dp.timestamp_ms,
    dp.vibration,
    dp.ax1, dp.ay1, dp.az1, dp.gx1, dp.gy1, dp.gz1,
    dp.ax2, dp.ay2, dp.az2, dp.gx2, dp.gy2, dp.gz2,
    dp.distance_cm
  );

  return mqttClient.publish(mqtt_topic, payload);
}

// ==========================================
// QUEUE PROCESSING
// ==========================================

void processQueue() {
  while (!dataBuffer.empty()) {
    const DataPoint &dp = dataBuffer.front();

    Serial.printf(
      "[QUEUE] Attempting to publish #%lu ... ",
      (unsigned long)dp.seq
    );

    if (publishDataPoint(dp)) {
      Serial.println("Success!");
      dataBuffer.erase(dataBuffer.begin());
    } else {
      Serial.println(
        "Failed. Stopping queue processing."
      );
      break;
    }
    delay(10);
  }
}
