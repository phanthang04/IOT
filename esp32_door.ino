/*
=====================================================
 SMART DOOR LOCK FULL VERSION
 ESP32-CAM + PIR + FACE + PALM + SERVO
=====================================================
Luồng hoạt động:
  PIR → server event "motion" → browser phát NhinCam.mp3
  Face OK → server event "face_ok" → browser phát DoTay.mp3
  Face FAIL → server event "face_fail" → browser phát NguoiLa.mp3
  Palm OK → server event "palm_ok" → browser phát XinChao.mp3 + mở cửa
  Palm FAIL → server event "palm_fail" → browser phát KhongXacThuc.mp3

MJPEG Stream: http://<ESP32_IP>:81/stream
=====================================================
*/

#include "esp_camera.h"
#include "esp_http_server.h"
#include <ArduinoJson.h>
#include <ESP32Servo.h>
#include <HTTPClient.h>
#include <WiFi.h>

//================ WIFI ==================
const char *ssid = "TQT";
const char *password = "11111111";

const char *SERVER = "http://10.68.234.62:5000";

#define SERVO_PIN 14
#define PIR_PIN 15

Servo doorServo;
WiFiClient httpClient;

//============= CAMERA CONFIG ============
#define PWDN_GPIO_NUM 32
#define RESET_GPIO_NUM -1
#define XCLK_GPIO_NUM 0
#define SIOD_GPIO_NUM 26
#define SIOC_GPIO_NUM 27
#define Y9_GPIO_NUM 35
#define Y8_GPIO_NUM 34
#define Y7_GPIO_NUM 39
#define Y6_GPIO_NUM 36
#define Y5_GPIO_NUM 21
#define Y4_GPIO_NUM 19
#define Y3_GPIO_NUM 18
#define Y2_GPIO_NUM 5
#define VSYNC_GPIO_NUM 25
#define HREF_GPIO_NUM 23
#define PCLK_GPIO_NUM 22

volatile bool isCameraSleeping = false;
volatile unsigned long lastActiveTime = 0;
const unsigned long cameraSleepDelay = 15000; // 15 giây không hoạt động sẽ ngủ

void setupCamera() {
  // Bật nguồn camera thủ công để đảm bảo cảm biến không bị treo
  pinMode(PWDN_GPIO_NUM, OUTPUT);
  digitalWrite(PWDN_GPIO_NUM, LOW);
  delay(100);

  camera_config_t config;
  config.ledc_channel =
      LEDC_CHANNEL_7; // Tránh xung đột với Servo (thường dùng Channel 0)
  config.ledc_timer = LEDC_TIMER_3;
  config.pin_d0 = Y2_GPIO_NUM;
  config.pin_d1 = Y3_GPIO_NUM;
  config.pin_d2 = Y4_GPIO_NUM;
  config.pin_d3 = Y5_GPIO_NUM;
  config.pin_d4 = Y6_GPIO_NUM;
  config.pin_d5 = Y7_GPIO_NUM;
  config.pin_d6 = Y8_GPIO_NUM;
  config.pin_d7 = Y9_GPIO_NUM;
  config.pin_xclk = XCLK_GPIO_NUM;
  config.pin_pclk = PCLK_GPIO_NUM;
  config.pin_vsync = VSYNC_GPIO_NUM;
  config.pin_href = HREF_GPIO_NUM;
  config.pin_sscb_sda = SIOD_GPIO_NUM;
  config.pin_sscb_scl = SIOC_GPIO_NUM;
  config.pin_pwdn = PWDN_GPIO_NUM;
  config.pin_reset = RESET_GPIO_NUM;
  config.xclk_freq_hz =
      10000000; // Giảm xung nhịp xuống 10MHz để chống treo camera
  config.pixel_format = PIXFORMAT_JPEG;
  config.frame_size =
      FRAMESIZE_VGA; // Giảm xuống VGA (640x480) để đảm bảo không bị thiếu RAM
  config.jpeg_quality =
      12; // Tăng số này lên (10-12) để giảm kích thước ảnh, chống tràn bộ nhớ
  config.fb_count = 1; // Chỉ dùng 1 frame buffer để tiết kiệm RAM

  if (esp_camera_init(&config) != ESP_OK) {
    Serial.println("Camera FAILED");
  } else {
    Serial.println("Camera OK");
  }
}

void wakeCamera() {
  if (isCameraSleeping) {
    Serial.println(">>> WAKING UP CAMERA <<<");
    pinMode(PWDN_GPIO_NUM, OUTPUT);
    digitalWrite(PWDN_GPIO_NUM, LOW); // Cấp nguồn cho camera
    delay(500);                       // Đợi nguồn điện ổn định
    setupCamera();                    // Khởi tạo driver camera
    isCameraSleeping = false;
    delay(500); // Đợi cảm biến camera thích nghi với ánh sáng (AGC/AEC)
  }
}

void sleepCamera() {
  if (!isCameraSleeping) {
    Serial.println(">>> PUTTING CAMERA TO SLEEP <<<");
    esp_camera_deinit(); // Giải phóng tài nguyên camera
    pinMode(PWDN_GPIO_NUM, OUTPUT);
    digitalWrite(PWDN_GPIO_NUM, HIGH); // Tắt nguồn camera (PWDN Active High)
    isCameraSleeping = true;
  }
}

//======= MJPEG STREAMING SERVER (port 81) ========

#define PART_BOUNDARY "123456789000000000000987654321"
static const char *STREAM_CONTENT_TYPE =
    "multipart/x-mixed-replace;boundary=" PART_BOUNDARY;
static const char *STREAM_BOUNDARY = "\r\n--" PART_BOUNDARY "\r\n";
static const char *STREAM_PART =
    "Content-Type: image/jpeg\r\nContent-Length: %u\r\n\r\n";

httpd_handle_t stream_httpd = NULL;

static esp_err_t stream_handler(httpd_req_t *req) {
  wakeCamera();
  lastActiveTime = millis();

  camera_fb_t *fb = NULL;
  esp_err_t res = ESP_OK;
  char part_buf[64];

  httpd_resp_set_type(req, STREAM_CONTENT_TYPE);
  httpd_resp_set_hdr(req, "Access-Control-Allow-Origin", "*");
  httpd_resp_set_hdr(req, "Cache-Control", "no-cache");

  while (true) {
    lastActiveTime =
        millis(); // Cập nhật liên tục khi đang stream để không bị ngủ
    fb = esp_camera_fb_get();
    if (!fb) {
      res = ESP_FAIL;
      break;
    }
    res = httpd_resp_send_chunk(req, STREAM_BOUNDARY, strlen(STREAM_BOUNDARY));
    if (res == ESP_OK) {
      size_t hlen = snprintf(part_buf, sizeof(part_buf), STREAM_PART, fb->len);
      res = httpd_resp_send_chunk(req, part_buf, hlen);
    }
    if (res == ESP_OK) {
      res = httpd_resp_send_chunk(req, (const char *)fb->buf, fb->len);
    }
    esp_camera_fb_return(fb);
    if (res != ESP_OK)
      break;
  }
  return res;
}

volatile bool isAutoDetect = true; // Cờ bật tắt tự động nhận diện
volatile unsigned long doorOpenTime = 0;
volatile bool isDoorOpen = false;

static esp_err_t open_handler(httpd_req_t *req) {
  httpd_resp_set_hdr(req, "Access-Control-Allow-Origin", "*");
  const char *resp = "OK";
  httpd_resp_send(req, resp, strlen(resp));

  Serial.println(">>> Nhan lenh /open tu Server - MO NGAY LAP TUC <<<");
  // Force re-attach to ensure camera didn't steal the PWM channel
  doorServo.detach();
  doorServo.attach(SERVO_PIN, 500, 2400);
  doorServo.write(120); // Mở góc rộng hơn để dễ thấy
  doorOpenTime = millis();
  isDoorOpen = true;

  return ESP_OK;
}

static esp_err_t close_handler(httpd_req_t *req) {
  httpd_resp_set_hdr(req, "Access-Control-Allow-Origin", "*");
  const char *resp = "OK";
  httpd_resp_send(req, resp, strlen(resp));

  Serial.println(">>> Nhan lenh /close tu Server - DONG NGAY LAP TUC <<<");
  doorServo.detach();
  doorServo.attach(SERVO_PIN, 500, 2400);
  doorServo.write(0);
  isDoorOpen = false;

  return ESP_OK;
}

static esp_err_t autoon_handler(httpd_req_t *req) {
  httpd_resp_set_hdr(req, "Access-Control-Allow-Origin", "*");
  isAutoDetect = true;
  httpd_resp_send(req, "OK", 2);
  Serial.println("Auto Detect: ON");
  return ESP_OK;
}

static esp_err_t autooff_handler(httpd_req_t *req) {
  httpd_resp_set_hdr(req, "Access-Control-Allow-Origin", "*");
  isAutoDetect = false;
  sleepCamera(); // Cho camera ngủ ngay lập tức
  httpd_resp_send(req, "OK", 2);
  Serial.println("Auto Detect: OFF - Sleeping Camera");
  return ESP_OK;
}

static esp_err_t capture_handler(httpd_req_t *req) {
  wakeCamera();
  lastActiveTime = millis();

  camera_fb_t *fb = esp_camera_fb_get();
  if (!fb) {
    httpd_resp_send_500(req);
    return ESP_FAIL;
  }
  httpd_resp_set_type(req, "image/jpeg");
  httpd_resp_set_hdr(req, "Access-Control-Allow-Origin", "*");
  esp_err_t res = httpd_resp_send(req, (const char *)fb->buf, fb->len);
  esp_camera_fb_return(fb);
  return res;
}

static esp_err_t wake_handler(httpd_req_t *req) {
  httpd_resp_set_hdr(req, "Access-Control-Allow-Origin", "*");
  wakeCamera();
  lastActiveTime = millis();
  const char *resp = "WOKEN";
  httpd_resp_send(req, resp, strlen(resp));
  Serial.println(">>> Nhan lenh /wake tu Server <<<");
  return ESP_OK;
}

static esp_err_t status_handler(httpd_req_t *req) {
  httpd_resp_set_hdr(req, "Access-Control-Allow-Origin", "*");
  char resp[128];
  snprintf(resp, sizeof(resp), "{\"sleeping\":%s,\"auto_detect\":%s}",
           isCameraSleeping ? "true" : "false",
           isAutoDetect ? "true" : "false");
  httpd_resp_set_type(req, "application/json");
  httpd_resp_send(req, resp, strlen(resp));
  return ESP_OK;
}

httpd_handle_t cmd_httpd = NULL;

void startStreamServer() {
  // 1. Server cho Stream (Port 81)
  httpd_config_t config_stream = HTTPD_DEFAULT_CONFIG();
  config_stream.server_port = 81;
  config_stream.max_uri_handlers = 2;
  // Cho phép stream chạy trên một thread độc lập

  httpd_uri_t stream_uri = {.uri = "/stream",
                            .method = HTTP_GET,
                            .handler = stream_handler,
                            .user_ctx = NULL};

  if (httpd_start(&stream_httpd, &config_stream) == ESP_OK) {
    httpd_register_uri_handler(stream_httpd, &stream_uri);
    Serial.println("Stream: http://" + WiFi.localIP().toString() +
                   ":81/stream");
  }
  httpd_config_t config_cmd = HTTPD_DEFAULT_CONFIG();
  config_cmd.server_port = 82;
  config_cmd.ctrl_port = 32769; 
  config_cmd.max_uri_handlers = 10; 
  httpd_uri_t open_uri = {.uri = "/open",
                          .method = HTTP_GET,
                          .handler = open_handler,
                          .user_ctx = NULL};
  httpd_uri_t close_uri = {.uri = "/close",
                           .method = HTTP_GET,
                           .handler = close_handler,
                           .user_ctx = NULL};
  httpd_uri_t capture_uri = {.uri = "/capture",
                             .method = HTTP_GET,
                             .handler = capture_handler,
                             .user_ctx = NULL};
  httpd_uri_t autoon_uri = {.uri = "/auto_on",
                            .method = HTTP_GET,
                            .handler = autoon_handler,
                            .user_ctx = NULL};
  httpd_uri_t autooff_uri = {.uri = "/auto_off",
                             .method = HTTP_GET,
                             .handler = autooff_handler,
                             .user_ctx = NULL};
  httpd_uri_t wake_uri = {.uri = "/wake",
                          .method = HTTP_GET,
                          .handler = wake_handler,
                          .user_ctx = NULL};
  httpd_uri_t status_uri = {.uri = "/status",
                            .method = HTTP_GET,
                            .handler = status_handler,
                            .user_ctx = NULL};

  if (httpd_start(&cmd_httpd, &config_cmd) == ESP_OK) {
    httpd_register_uri_handler(cmd_httpd, &open_uri);
    httpd_register_uri_handler(cmd_httpd, &close_uri);
    httpd_register_uri_handler(cmd_httpd, &capture_uri);
    httpd_register_uri_handler(cmd_httpd, &autoon_uri);
    httpd_register_uri_handler(cmd_httpd, &autooff_uri);
    httpd_register_uri_handler(cmd_httpd, &wake_uri);
    httpd_register_uri_handler(cmd_httpd, &status_uri);
    Serial.println("Command: http://" + WiFi.localIP().toString() + ":82");
  }
}

void connectWifi() {
  WiFi.begin(ssid, password);
  WiFi.setSleep(
      false);
  Serial.print("Connecting WiFi");
  int tries = 0;
  while (WiFi.status() != WL_CONNECTED && tries < 30) {
    delay(500);
    Serial.print(".");
    tries++;
  }
  if (WiFi.status() == WL_CONNECTED) {
    Serial.println("\nWiFi OK: " + WiFi.localIP().toString());
  } else {
    Serial.println("\nWiFi FAILED");
    ESP.restart();
  }
}

void registerStreamUrl() {
  HTTPClient http;
  String myIP = WiFi.localIP().toString();
  String body = "{\"stream_url\":\"http://" + myIP + ":81/stream\",\"ip\":\"" +
                myIP + "\"}";
  http.begin(httpClient, String(SERVER) + "/api/esp32/register");
  http.addHeader("Content-Type", "application/json");
  int httpCode = http.POST(body);
  Serial.println("Register to server: " + String(httpCode));
  http.end();
}


void openDoor() {
  Serial.println("OPEN");
  doorServo.write(90);
  doorOpenTime = millis();
  isDoorOpen = true;
}



void setup() {
  Serial.begin(115200);

  pinMode(PIR_PIN, INPUT_PULLDOWN);

  setupCamera();
  isCameraSleeping = false;

  doorServo.setPeriodHertz(50);
  doorServo.attach(SERVO_PIN, 500, 2400);
  doorServo.write(0);
  delay(500);

  connectWifi();
  startStreamServer();
  delay(300);
  registerStreamUrl();

  lastActiveTime = millis();

  Serial.println("=== SMART DOOR ===");
  Serial.println("IP: " + WiFi.localIP().toString());
}


unsigned long lastMotionTime = 0;
const unsigned long motionCooldown = 10000; // 10 giây

void loop() {
  if (WiFi.status() != WL_CONNECTED) {
    connectWifi();
    registerStreamUrl();
    lastActiveTime = millis(); 
    return;
  }

  // Tự động đóng cửa sau 3 giây
  if (isDoorOpen && (millis() - doorOpenTime >= 3000)) {
    Serial.println("CLOSE (auto)");
    doorServo.detach();
    doorServo.attach(SERVO_PIN, 500, 2400);
    doorServo.write(0);
    isDoorOpen = false;
  }

  if (isAutoDetect && digitalRead(PIR_PIN) == HIGH) {
    if (millis() - lastMotionTime >= motionCooldown || lastMotionTime == 0) {
      lastMotionTime = millis();
      lastActiveTime = millis(); // Giữ camera thức
      Serial.println("=== Motion Detected ===");

      // Đánh thức camera ngay lập tức
      wakeCamera();

      // Gửi báo cáo chuyển động lên Server
      HTTPClient http;
      http.begin(httpClient, String(SERVER) + "/api/trigger_motion");
      http.setTimeout(3000);
      int httpCode = http.GET();
      http.end();

      Serial.println("Sent motion trigger to Server, Code: " +
                     String(httpCode));
    }
  }

  delay(100);
}
