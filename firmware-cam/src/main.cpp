/**
 * Lumina ESP32-CAM Firmware - Device B (Eyes)
 * 
 * Simple IP Camera Streamer
 * - WiFiManager for easy setup
 * - MJPEG stream on /stream
 * - ArduinoOTA for wireless updates
 * 
 * Camera Model: AI-Thinker ESP32-CAM
 */

#include <Arduino.h>
#include <WiFi.h>
#include <WiFiManager.h>
#include <WiFiMulti.h>
#include <ArduinoOTA.h>
#include "esp_camera.h"
#include "esp_http_server.h"

// ============== CAMERA PINS (AI-Thinker ESP32-CAM) ==============
#define PWDN_GPIO_NUM     32
#define RESET_GPIO_NUM    -1
#define XCLK_GPIO_NUM      0
#define SIOD_GPIO_NUM     26
#define SIOC_GPIO_NUM     27

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

// ============== SETTINGS ==============
#define HOSTNAME "lumina-cam"
#define LED_BUILTIN 33  // Flash LED on ESP32-CAM

// ============== GLOBALS ==============
WiFiManager wifiManager;
WiFiMulti wifiMulti;
httpd_handle_t stream_httpd = NULL;
httpd_handle_t camera_httpd = NULL;

// ============== MULTI-NETWORK CONFIG ==============
// Add your WiFi networks here (SSID, password)
// The device will connect to whichever is available
const char* networks[][2] = {
  {"Galaxy S20 FE C565", "poiuytre"},  // Mobile hotspot
  // {"YourHomeWiFi", "homepassword"},
  // {"YourOfficeWiFi", "officepassword"},
};
const int numNetworks = sizeof(networks) / sizeof(networks[0]);

// ============== CAMERA INIT ==============
bool initCamera() {
    camera_config_t config;
    config.ledc_channel = LEDC_CHANNEL_0;
    config.ledc_timer = LEDC_TIMER_0;
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
    config.xclk_freq_hz = 20000000;
    config.pixel_format = PIXFORMAT_JPEG;
    
    // Optimized for LOW LATENCY hand tracking
    if (psramFound()) {
        config.frame_size = FRAMESIZE_QVGA;  // 320x240 - FASTER!
        config.jpeg_quality = 20;  // Higher = faster encoding, lower quality
        config.fb_count = 2;  // Double buffer for smooth streaming
        config.grab_mode = CAMERA_GRAB_LATEST;  // Always get latest frame
    } else {
        config.frame_size = FRAMESIZE_QVGA;
        config.jpeg_quality = 25;
        config.fb_count = 1;
    }
    
    // Initialize camera
    esp_err_t err = esp_camera_init(&config);
    if (err != ESP_OK) {
        Serial.printf("Camera init failed: 0x%x\n", err);
        return false;
    }
    
    // Sensor settings for better image
    sensor_t * s = esp_camera_sensor_get();
    if (s != NULL) {
        s->set_brightness(s, 0);     // -2 to 2
        s->set_contrast(s, 0);       // -2 to 2
        s->set_saturation(s, 0);     // -2 to 2
        s->set_special_effect(s, 0); // 0 = No Effect
        s->set_whitebal(s, 1);       // 0 = disable, 1 = enable
        s->set_awb_gain(s, 1);       // 0 = disable, 1 = enable
        s->set_wb_mode(s, 0);        // 0 to 4
        s->set_exposure_ctrl(s, 1);  // 0 = disable, 1 = enable
        s->set_aec2(s, 0);           // 0 = disable, 1 = enable
        s->set_ae_level(s, 0);       // -2 to 2
        s->set_aec_value(s, 300);    // 0 to 1200
        s->set_gain_ctrl(s, 1);      // 0 = disable, 1 = enable
        s->set_agc_gain(s, 0);       // 0 to 30
        s->set_gainceiling(s, (gainceiling_t)0);  // 0 to 6
        s->set_bpc(s, 0);            // 0 = disable, 1 = enable
        s->set_wpc(s, 1);            // 0 = disable, 1 = enable
        s->set_raw_gma(s, 1);        // 0 = disable, 1 = enable
        s->set_lenc(s, 1);           // 0 = disable, 1 = enable
        s->set_hmirror(s, 0);        // 0 = disable, 1 = enable
        s->set_vflip(s, 1);          // 0 = disable, 1 = enable (FLIPPED UPSIDE DOWN)
        s->set_dcw(s, 1);            // 0 = disable, 1 = enable
        s->set_colorbar(s, 0);       // 0 = disable, 1 = enable
    }
    
    Serial.println("✓ Camera initialized");
    return true;
}

// ============== HTTP HANDLERS ==============
static esp_err_t index_handler(httpd_req_t *req) {
    const char* html = R"rawliteral(
<!DOCTYPE html>
<html>
<head>
    <title>Lumina Cam</title>
    <style>
        body { font-family: Arial; text-align: center; padding: 20px; background: #1a1a1a; color: #fff; }
        h1 { color: #4CAF50; }
        img { max-width: 100%; border: 2px solid #4CAF50; border-radius: 8px; }
        .info { background: #333; padding: 10px; border-radius: 5px; margin: 10px auto; max-width: 600px; }
    </style>
</head>
<body>
    <h1>📹 Lumina Camera - Device B (Eyes)</h1>
    <div class="info">
        <p><strong>Stream URL:</strong> http://%s/stream</p>
        <p><strong>Status:</strong> Active</p>
    </div>
    <img src="/stream" />
</body>
</html>
)rawliteral";
    
    char response[2048];
    snprintf(response, sizeof(response), html, WiFi.localIP().toString().c_str());
    
    httpd_resp_set_type(req, "text/html");
    return httpd_resp_send(req, response, strlen(response));
}

static esp_err_t stream_handler(httpd_req_t *req) {
    camera_fb_t * fb = NULL;
    esp_err_t res = ESP_OK;
    size_t _jpg_buf_len = 0;
    uint8_t * _jpg_buf = NULL;
    char * part_buf[64];

    res = httpd_resp_set_type(req, "multipart/x-mixed-replace; boundary=frame");
    if (res != ESP_OK) {
        return res;
    }

    while (true) {
        fb = esp_camera_fb_get();
        if (!fb) {
            Serial.println("Camera capture failed");
            res = ESP_FAIL;
        } else {
            if (fb->format != PIXFORMAT_JPEG) {
                bool jpeg_converted = frame2jpg(fb, 80, &_jpg_buf, &_jpg_buf_len);
                esp_camera_fb_return(fb);
                fb = NULL;
                if (!jpeg_converted) {
                    Serial.println("JPEG compression failed");
                    res = ESP_FAIL;
                }
            } else {
                _jpg_buf_len = fb->len;
                _jpg_buf = fb->buf;
            }
        }
        if (res == ESP_OK) {
            size_t hlen = snprintf((char *)part_buf, 64, "Content-Type: image/jpeg\r\nContent-Length: %u\r\n\r\n", _jpg_buf_len);
            res = httpd_resp_send_chunk(req, (const char *)part_buf, hlen);
        }
        if (res == ESP_OK) {
            res = httpd_resp_send_chunk(req, (const char *)_jpg_buf, _jpg_buf_len);
        }
        if (res == ESP_OK) {
            res = httpd_resp_send_chunk(req, "\r\n--frame\r\n", 13);
        }
        if (fb) {
            esp_camera_fb_return(fb);
            fb = NULL;
            _jpg_buf = NULL;
        } else if (_jpg_buf) {
            free(_jpg_buf);
            _jpg_buf = NULL;
        }
        if (res != ESP_OK) {
            break;
        }
    }
    return res;
}

// ============== START WEB SERVER ==============
void startCameraServer() {
    httpd_config_t config = HTTPD_DEFAULT_CONFIG();
    config.server_port = 80;

    httpd_uri_t index_uri = {
        .uri       = "/",
        .method    = HTTP_GET,
        .handler   = index_handler,
        .user_ctx  = NULL
    };

    httpd_uri_t stream_uri = {
        .uri       = "/stream",
        .method    = HTTP_GET,
        .handler   = stream_handler,
        .user_ctx  = NULL
    };

    Serial.printf("Starting web server on port %d\n", config.server_port);
    if (httpd_start(&camera_httpd, &config) == ESP_OK) {
        httpd_register_uri_handler(camera_httpd, &index_uri);
        httpd_register_uri_handler(camera_httpd, &stream_uri);
        Serial.println("✓ Camera server started");
    }
}

// ============== WIFI SETUP ==============
void setupWiFi() {
    Serial.println("Setting up WiFi...");
    
    WiFi.setHostname(HOSTNAME);
    
    // Try known networks first (if any configured)
    if (numNetworks > 0) {
        Serial.printf("Trying %d known networks...\n", numNetworks);
        for (int i = 0; i < numNetworks; i++) {
            wifiMulti.addAP(networks[i][0], networks[i][1]);
            Serial.printf("  - %s\n", networks[i][0]);
        }
        
        if (wifiMulti.run(10000) == WL_CONNECTED) {
            Serial.println("✓ Connected to known network!");
            Serial.print("  SSID: ");
            Serial.println(WiFi.SSID());
            Serial.print("  IP: ");
            Serial.println(WiFi.localIP());
            Serial.print("  MAC: ");
            Serial.println(WiFi.macAddress());
            return;
        }
        Serial.println("No known networks found, starting setup portal...");
    }
    
    // Fall back to WiFiManager setup portal
    wifiManager.setConfigPortalTimeout(180);
    wifiManager.setAPCallback([](WiFiManager* wm) {
        Serial.println("\n*** WiFi Setup Mode ***");
        Serial.println("Connect to: Lumina-Cam-Setup");
        Serial.println("Open: 192.168.4.1");
        
        // Blink LED during setup
        pinMode(LED_BUILTIN, OUTPUT);
        for (int i = 0; i < 5; i++) {
            digitalWrite(LED_BUILTIN, HIGH);
            delay(200);
            digitalWrite(LED_BUILTIN, LOW);
            delay(200);
        }
    });
    
    if (!wifiManager.autoConnect("Lumina-Cam-Setup")) {
        Serial.println("Failed to connect, restarting...");
        delay(2000);
        ESP.restart();
    }
    
    Serial.println("✓ WiFi connected!");
    Serial.print("  IP: ");
    Serial.println(WiFi.localIP());
    Serial.print("  Hostname: ");
    Serial.println(HOSTNAME);
}

// ============== OTA SETUP ==============
void setupOTA() {
    ArduinoOTA.setHostname(HOSTNAME);
    
    ArduinoOTA.onStart([]() {
        Serial.println("OTA Update Start");
        pinMode(LED_BUILTIN, OUTPUT);
        digitalWrite(LED_BUILTIN, HIGH);
    });
    
    ArduinoOTA.onEnd([]() {
        Serial.println("\nOTA Update Complete!");
        digitalWrite(LED_BUILTIN, LOW);
    });
    
    ArduinoOTA.onProgress([](unsigned int progress, unsigned int total) {
        Serial.printf("Progress: %u%%\r", (progress / (total / 100)));
    });
    
    ArduinoOTA.onError([](ota_error_t error) {
        Serial.printf("OTA Error[%u]: ", error);
        digitalWrite(LED_BUILTIN, LOW);
    });
    
    ArduinoOTA.begin();
    Serial.println("✓ OTA ready");
}

// ============== SETUP ==============
void setup() {
    Serial.begin(115200);
    Serial.println("\n\n================================");
    Serial.println("  Lumina Camera - Device B");
    Serial.println("================================");
    
    // Flash LED
    pinMode(LED_BUILTIN, OUTPUT);
    digitalWrite(LED_BUILTIN, HIGH);
    delay(500);
    digitalWrite(LED_BUILTIN, LOW);
    
    // Initialize camera
    if (!initCamera()) {
        Serial.println("Camera init failed!");
        while (true) {
            digitalWrite(LED_BUILTIN, HIGH);
            delay(200);
            digitalWrite(LED_BUILTIN, LOW);
            delay(200);
        }
    }
    
    // Setup WiFi
    setupWiFi();
    
    // Setup OTA
    setupOTA();
    
    // Start camera server
    startCameraServer();
    
    Serial.println("\n✓ Lumina Camera Ready!");
    Serial.printf("   Stream: http://%s/stream\n", WiFi.localIP().toString().c_str());
    Serial.printf("   Web UI: http://%s/\n", WiFi.localIP().toString().c_str());
}

// ============== LOOP ==============
void loop() {
    ArduinoOTA.handle();
    delay(10);
}
