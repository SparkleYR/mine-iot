#include "esp_camera.h"
#include <WiFi.h>
#include <WebServer.h>
#include <HTTPClient.h>

// Include ESP32 SOC registers to control Brownout Detector
#include "soc/soc.h"
#include "soc/rtc_cntl_reg.h"

// =====================================================
// WIFI & PI SERVER CONFIGURATION
// =====================================================

const char* ssid             = "Pi4B-Hotspot";
const char* password         = "abcdefgh";
const char* pi_upload_url    = "http://10.42.0.1:5000/upload";

// Auto capture interval in milliseconds (0 = disabled, 10000 = every 10 sec)
const unsigned long AUTO_CAPTURE_INTERVAL = 10000;
const unsigned long RECONNECT_INTERVAL    = 10000;

// Enable flash LED during image capture
const bool ENABLE_FLASH_ON_CAPTURE = true;

// =====================================================
// FLASH LED
// =====================================================

#define FLASH_LED_PIN 4

// =====================================================
// AI THINKER ESP32-CAM PIN CONFIGURATION
// =====================================================

#define PWDN_GPIO_NUM     32
#define RESET_GPIO_NUM    -1
#define XCLK_GPIO_NUM      0
#define SIOD_GPIO_NUM      26
#define SIOC_GPIO_NUM      27

#define Y9_GPIO_NUM       35
#define Y8_GPIO_NUM       34
#define Y7_GPIO_NUM       39
#define Y6_GPIO_NUM       36
#define Y5_GPIO_NUM       21
#define Y4_GPIO_NUM       19
#define Y3_GPIO_NUM       18
#define Y2_GPIO_NUM        5

#define VSYNC_GPIO_NUM    25
#define HREF_GPIO_NUM     23
#define PCLK_GPIO_NUM     22

// =====================================================
// WEB SERVER & TIMING
// =====================================================

WebServer server(80);
unsigned long lastAutoCaptureTime = 0;
unsigned long lastReconnectAttempt = 0;

void setupWiFi();

// =====================================================
// UPLOAD IMAGE TO RASPBERRY PI
// =====================================================

bool send_image_to_pi(camera_fb_t *fb) {
  if (!fb) {
    Serial.println("[HTTP] Error: Empty frame buffer.");
    return false;
  }
  
  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("[HTTP] Cannot send image: Wi-Fi disconnected.");
    return false;
  }

  WiFiClient client;
  HTTPClient http;

  http.begin(client, pi_upload_url);
  http.addHeader("Content-Type", "image/jpeg");
  http.setTimeout(5000); // 5 sec timeout

  Serial.printf("[HTTP] Uploading %u bytes to %s ...\n", fb->len, pi_upload_url);
  int httpResponseCode = http.POST(fb->buf, fb->len);

  if (httpResponseCode > 0) {
    Serial.printf("[HTTP] Image uploaded successfully! Response code: %d\n", httpResponseCode);
  } else {
    Serial.printf("[HTTP] Upload failed, error: %s\n", http.errorToString(httpResponseCode).c_str());
  }

  http.end();
  return (httpResponseCode == 200);
}

// =====================================================
// SINGLE-GET CAMERA CAPTURE WITH FLASH
// =====================================================

camera_fb_t* capture_image(bool useFlash) {
  if (useFlash) {
    digitalWrite(FLASH_LED_PIN, HIGH);
    delay(150); // Short flash pulse
  }

  // Get frame buffer EXACTLY ONCE
  camera_fb_t *fb = esp_camera_fb_get();

  if (useFlash) {
    digitalWrite(FLASH_LED_PIN, LOW);
  }

  return fb;
}

// =====================================================
// WEB CAPTURE HANDLER
// =====================================================

void handle_capture() {
  camera_fb_t *fb = capture_image(ENABLE_FLASH_ON_CAPTURE);

  if (!fb) {
    Serial.println("[ERROR] Camera capture failed!");
    server.send(500, "text/plain", "Camera capture failed");
    return;
  }

  // Upload frame buffer to Pi Server (which proxies it to PC)
  send_image_to_pi(fb);

  // Send image to requesting HTTP client
  server.sendHeader("Content-Disposition", "inline; filename=capture.jpg");
  server.send_P(200, "image/jpeg", (const char *)fb->buf, fb->len);

  esp_camera_fb_return(fb);
}

// =====================================================
// MAIN WEB PAGE
// =====================================================

void handle_root() {
  String html = R"rawliteral(
<!DOCTYPE html>
<html>
<head>
<title>ESP32-CAM Mine Monitoring</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
body {
  font-family: Arial, sans-serif;
  text-align: center;
  background: #111;
  color: white;
}
h1 { margin-top: 20px; }
img {
  width: 90%;
  max-width: 640px;
  border: 3px solid white;
  border-radius: 8px;
}
button {
  margin: 10px;
  padding: 12px 24px;
  font-size: 16px;
  border-radius: 8px;
  border: none;
  cursor: pointer;
  background: #007bff;
  color: white;
}
button:hover { background: #0056b3; }
</style>
</head>
<body>
<h1>ESP32-CAM Mine Monitoring</h1>
<h3>Camera Feed & Auto-Upload to PC</h3>
<img id="camera" src="/capture">
<br>
<button onclick="flashOn()">FLASH ON</button>
<button onclick="flashOff()">FLASH OFF</button>
<button onclick="triggerCapture()">CAPTURE & SEND NOW</button>
<script>
function flashOn() { fetch('/flash/on'); }
function flashOff() { fetch('/flash/off'); }
function triggerCapture() {
  document.getElementById("camera").src = "/capture?t=" + new Date().getTime();
}

// Refresh image every 5 seconds
setInterval(function() {
  triggerCapture();
}, 5000);
</script>
</body>
</html>
)rawliteral";

  server.send(200, "text/html", html);
}

// =====================================================
// FLASH CONTROLS
// =====================================================

void handle_flash_on() {
  digitalWrite(FLASH_LED_PIN, HIGH);
  server.send(200, "text/plain", "Flashlight ON");
}

void handle_flash_off() {
  digitalWrite(FLASH_LED_PIN, LOW);
  server.send(200, "text/plain", "Flashlight OFF");
}

// =====================================================
// SETUP WIFI
// =====================================================

void setupWiFi() {
  Serial.printf("Connecting to Wi-Fi %s ", ssid);
  
  // Clean disconnect with 802.11 Deauth frame
  WiFi.disconnect(true);
  delay(1000);
  
  WiFi.mode(WIFI_STA);
  WiFi.setSleep(false); // Disable Wi-Fi sleep for max stability
  
  // Reduce RF TX Power to 11dBm (reduces peak current draw from 500mA down to ~120mA)
  WiFi.setTxPower(WIFI_POWER_11dBm);

  WiFi.begin(ssid, password);

  int attempts = 0;
  while (WiFi.status() != WL_CONNECTED && attempts < 20) {
    delay(500);
    Serial.print(".");
    attempts++;
  }

  if (WiFi.status() == WL_CONNECTED) {
    Serial.println();
    Serial.println("WiFi connected!");
    Serial.print("ESP32-CAM IP Address: ");
    Serial.println(WiFi.localIP());
  } else {
    Serial.println();
    Serial.println("Wi-Fi connection attempt failed. Will retry in background.");
  }
}

// =====================================================
// SETUP
// =====================================================

void setup() {
  // 1. DISABLE BROWNOUT DETECTOR to prevent chip resets during Wi-Fi transmission power bursts
  WRITE_PERI_REG(RTC_CNTL_BROWN_OUT_REG, 0);

  Serial.begin(115200);
  delay(1000);

  Serial.println();
  Serial.println("==============================");
  Serial.println("ESP32-CAM STARTING (Brownout Disabled)");
  Serial.println("==============================");

  // FLASH LED
  pinMode(FLASH_LED_PIN, OUTPUT);
  digitalWrite(FLASH_LED_PIN, LOW);

  // ---------------------------------------------------
  // CAMERA CONFIGURATION
  // ---------------------------------------------------
  camera_config_t config;
  config.ledc_channel = LEDC_CHANNEL_0;
  config.ledc_timer   = LEDC_TIMER_0;

  config.pin_d0       = Y2_GPIO_NUM;
  config.pin_d1       = Y3_GPIO_NUM;
  config.pin_d2       = Y4_GPIO_NUM;
  config.pin_d3       = Y5_GPIO_NUM;
  config.pin_d4       = Y6_GPIO_NUM;
  config.pin_d5       = Y7_GPIO_NUM;
  config.pin_d6       = Y8_GPIO_NUM;
  config.pin_d7       = Y9_GPIO_NUM;
  config.pin_xclk     = XCLK_GPIO_NUM;
  config.pin_pclk     = PCLK_GPIO_NUM;
  config.pin_vsync    = VSYNC_GPIO_NUM;
  config.pin_href     = HREF_GPIO_NUM;
  config.pin_sccb_sda = SIOD_GPIO_NUM;
  config.pin_sccb_scl = SIOC_GPIO_NUM;
  config.pin_pwdn     = PWDN_GPIO_NUM;
  config.pin_reset    = RESET_GPIO_NUM;
  config.xclk_freq_hz = 20000000;
  config.pixel_format = PIXFORMAT_JPEG;

  config.frame_size   = FRAMESIZE_VGA; // 640 x 480
  config.jpeg_quality = 12;
  config.fb_count     = 1;

  // ---------------------------------------------------
  // INITIALIZE CAMERA
  // ---------------------------------------------------
  esp_err_t err = esp_camera_init(&config);
  if (err != ESP_OK) {
    Serial.printf("Camera initialization FAILED: 0x%X\n", err);
    return;
  }
  Serial.println("Camera initialized successfully!");

  // ---------------------------------------------------
  // CONNECT WIFI
  // ---------------------------------------------------
  setupWiFi();

  // ---------------------------------------------------
  // WEB SERVER ROUTES
  // ---------------------------------------------------
  server.on("/", handle_root);
  server.on("/capture", handle_capture);
  server.on("/flash/on", handle_flash_on);
  server.on("/flash/off", handle_flash_off);

  server.begin();
  Serial.println("Web server started!");
  Serial.printf("Target Pi Upload URL: %s\n", pi_upload_url);
}

// =====================================================
// LOOP
// =====================================================

void loop() {
  unsigned long now = millis();

  // Automatic Wi-Fi reconnection handling
  if (WiFi.status() != WL_CONNECTED) {
    if (now - lastReconnectAttempt >= RECONNECT_INTERVAL || lastReconnectAttempt == 0) {
      lastReconnectAttempt = now;
      setupWiFi();
    }
  }

  if (WiFi.status() == WL_CONNECTED) {
    server.handleClient();

    // Automatic periodic capture & upload to Pi (proxied to PC)
    if (AUTO_CAPTURE_INTERVAL > 0 && (now - lastAutoCaptureTime >= AUTO_CAPTURE_INTERVAL || lastAutoCaptureTime == 0)) {
      lastAutoCaptureTime = now;

      camera_fb_t *fb = capture_image(ENABLE_FLASH_ON_CAPTURE);
      if (fb) {
        Serial.println("[AUTO-CAPTURE] Image captured with flash. Sending to PC...");
        send_image_to_pi(fb);
        esp_camera_fb_return(fb);
      }
    }
  }
}
