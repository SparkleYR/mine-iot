#include "esp_camera.h"
#include <WiFi.h>
#include <WebServer.h>
#include <HTTPClient.h>

// =====================================================
// WIFI & PI SERVER CONFIGURATION
// =====================================================

const char* ssid             = "Pi4B-Hotspot";
const char* password         = "abcdefgh";
const char* pi_upload_url    = "http://10.42.0.1:5000/upload";

// Auto capture interval in milliseconds (0 = disabled, 10000 = every 10 sec)
const unsigned long AUTO_CAPTURE_INTERVAL = 10000;

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

// =====================================================
// UPLOAD IMAGE TO RASPBERRY PI
// =====================================================

bool send_image_to_pi(camera_fb_t *fb) {
  if (!fb || WiFi.status() != WL_CONNECTED) {
    Serial.println("[HTTP] Cannot send image: No Wi-Fi or empty frame buffer.");
    return false;
  }

  HTTPClient http;
  http.begin(pi_upload_url);
  http.addHeader("Content-Type", "image/jpeg");
  http.setTimeout(5000); // 5 sec timeout

  Serial.printf("[HTTP] Uploading %u bytes to %s ...\n", fb->len, pi_upload_url);
  int httpResponseCode = http.POST(fb->buf, fb->len);

  if (httpResponseCode > 0) {
    Serial.printf("[HTTP] Image uploaded successfully! Response code: %d\n", httpResponseCode);
  } else {
    Serial.printf("[HTTP] Upload failed error: %s\n", http.errorToString(httpResponseCode).c_str());
  }

  http.end();
  return (httpResponseCode == 200);
}

// =====================================================
// CAPTURE IMAGE WITH FLASH
// =====================================================

camera_fb_t* capture_with_flash() {
  // 1. Turn Flash LED ON
  digitalWrite(FLASH_LED_PIN, HIGH);

  // 2. Delay 300ms to allow sensor AGC/AEC auto-exposure to adjust to flash
  delay(300);

  // 3. Flush old pre-flash frame buffer if present (due to fb_count = 2)
  camera_fb_t *fb_stale = esp_camera_fb_get();
  if (fb_stale) {
    esp_camera_fb_return(fb_stale);
  }

  // 4. Capture fresh frame illuminated by flash
  camera_fb_t *fb = esp_camera_fb_get();

  // 5. Turn Flash LED OFF
  digitalWrite(FLASH_LED_PIN, LOW);

  return fb;
}

// =====================================================
// WEB CAPTURE HANDLER
// =====================================================

void handle_capture() {
  camera_fb_t *fb = capture_with_flash();

  if (!fb) {
    server.send(500, "text/plain", "Camera capture failed");
    return;
  }

  // Upload frame buffer to Pi Server in background
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
<h3>Camera Feed & Auto-Upload to Pi</h3>
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
// SETUP
// =====================================================

void setup() {
  Serial.begin(115200);
  delay(1000);

  Serial.println();
  Serial.println("==============================");
  Serial.println("ESP32-CAM STARTING");
  Serial.println("==============================");

  // ---------------------------------------------------
  // FLASH LED
  // ---------------------------------------------------
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
  config.fb_count     = 2;

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
  WiFi.disconnect(true);
  delay(100);
  WiFi.mode(WIFI_STA);
  delay(100);

  WiFi.begin(ssid, password);
  Serial.printf("Connecting to Wi-Fi %s ", ssid);

  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }

  Serial.println();
  Serial.println("WiFi connected!");
  Serial.print("ESP32-CAM IP Address: ");
  Serial.println(WiFi.localIP());

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
  server.handleClient();

  // Automatic periodic capture & upload to Pi
  unsigned long now = millis();
  if (AUTO_CAPTURE_INTERVAL > 0 && (now - lastAutoCaptureTime >= AUTO_CAPTURE_INTERVAL)) {
    lastAutoCaptureTime = now;

    Serial.println("[AUTO-CAPTURE] Turning on Flash & Capturing Image...");
    camera_fb_t *fb = capture_with_flash();
    if (fb) {
      send_image_to_pi(fb);
      esp_camera_fb_return(fb);
    }
  }
}
