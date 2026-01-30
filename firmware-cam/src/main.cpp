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
#include <ESPmDNS.h>
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

// Stream client tracking - ESP32-CAM can only serve ONE client at a time
volatile bool stream_client_connected = false;
volatile unsigned long last_frame_time = 0;
const unsigned long STREAM_TIMEOUT_MS = 10000;  // Auto-disconnect after 10s of no frames

// WiFi reconnect tracking
volatile int wifi_fail_count = 0;
const int WIFI_MAX_FAILS = 6; // Reboot after this many failed reconnect attempts

// MJPEG boundary - standard format for reliable parsing
#define PART_BOUNDARY "123456789000000000000987654321"
static const char* _STREAM_CONTENT_TYPE = "multipart/x-mixed-replace;boundary=" PART_BOUNDARY;
static const char* _STREAM_BOUNDARY = "\r\n--" PART_BOUNDARY "\r\n";
static const char* _STREAM_PART = "Content-Type: image/jpeg\r\nContent-Length: %u\r\n\r\n";

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
        config.jpeg_quality = 12;  // Lower = better compression = faster transfer (10-15 ideal)
        config.fb_count = 2;  // Double buffer for smooth streaming
        config.grab_mode = CAMERA_GRAB_LATEST;  // Always get latest frame (skips stale frames)
    } else {
        config.frame_size = FRAMESIZE_QQVGA;  // Even smaller without PSRAM
        config.jpeg_quality = 15;
        config.fb_count = 1;
    }
    
    // Initialize camera
    esp_err_t err = esp_camera_init(&config);
    if (err != ESP_OK) {
        Serial.printf("Camera init failed: 0x%x\n", err);
        return false;
    }
    
    // Sensor settings - OPTIMIZED FOR BRIGHTER IMAGE
    sensor_t * s = esp_camera_sensor_get();
    if (s != NULL) {
        s->set_brightness(s, 2);     // -2 to 2 (MAX brightness)
        s->set_contrast(s, 1);       // -2 to 2 (slightly higher contrast)
        s->set_saturation(s, 1);     // -2 to 2 (slightly more color)
        s->set_special_effect(s, 0); // 0 = No Effect
        s->set_whitebal(s, 1);       // 0 = disable, 1 = enable
        s->set_awb_gain(s, 1);       // 0 = disable, 1 = enable
        s->set_wb_mode(s, 0);        // 0 = Auto WB
        s->set_exposure_ctrl(s, 1);  // 0 = disable, 1 = enable auto exposure
        s->set_aec2(s, 1);           // Enable AEC DSP (better auto exposure)
        s->set_ae_level(s, 2);       // -2 to 2 (MAX auto exposure level)
        s->set_aec_value(s, 600);    // 0 to 1200 (higher = brighter)
        s->set_gain_ctrl(s, 1);      // 0 = disable, 1 = enable auto gain
        s->set_agc_gain(s, 15);      // 0 to 30 (higher gain = brighter but more noise)
        s->set_gainceiling(s, (gainceiling_t)6);  // 0 to 6 (MAX gain ceiling)
        s->set_bpc(s, 1);            // Bad pixel correction
        s->set_wpc(s, 1);            // White pixel correction
        s->set_raw_gma(s, 1);        // Gamma correction
        s->set_lenc(s, 1);           // Lens correction
        s->set_hmirror(s, 0);        // 0 = disable, 1 = enable
        s->set_vflip(s, 1);          // 0 = disable, 1 = enable (FLIPPED UPSIDE DOWN)
        s->set_dcw(s, 1);            // Downsize enable
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
    // Single-client enforcement: reject if another client is streaming
    if (stream_client_connected) {
        Serial.println("⚠️ Stream rejected: another client is already connected");
        httpd_resp_set_status(req, "503 Service Unavailable");
        httpd_resp_set_type(req, "text/plain");
        return httpd_resp_send(req, "Stream busy - only one client supported", HTTPD_RESP_USE_STRLEN);
    }
    
    stream_client_connected = true;
    last_frame_time = millis();
    Serial.println("📹 Stream client connected");
    
    camera_fb_t * fb = NULL;
    esp_err_t res = ESP_OK;
    size_t _jpg_buf_len = 0;
    uint8_t * _jpg_buf = NULL;
    char part_buf[64];
    unsigned long frame_count = 0;
    int64_t last_frame_us = esp_timer_get_time();

    // Set headers for MJPEG stream - use proper boundary format
    res = httpd_resp_set_type(req, _STREAM_CONTENT_TYPE);
    if (res != ESP_OK) {
        stream_client_connected = false;
        return res;
    }
    httpd_resp_set_hdr(req, "Access-Control-Allow-Origin", "*");
    httpd_resp_set_hdr(req, "Cache-Control", "no-cache, no-store, must-revalidate");

    while (stream_client_connected) {
        // Get latest frame (CAMERA_GRAB_LATEST skips old frames)
        fb = esp_camera_fb_get();
        if (!fb) {
            Serial.println("Camera capture failed");
            vTaskDelay(10 / portTICK_PERIOD_MS);
            continue;  // Try again instead of breaking
        }
        
        _jpg_buf_len = fb->len;
        _jpg_buf = fb->buf;
        
        // Send boundary
        res = httpd_resp_send_chunk(req, _STREAM_BOUNDARY, strlen(_STREAM_BOUNDARY));
        
        // Send part header with content length
        if (res == ESP_OK) {
            size_t hlen = snprintf(part_buf, sizeof(part_buf), _STREAM_PART, _jpg_buf_len);
            res = httpd_resp_send_chunk(req, part_buf, hlen);
        }
        
        // Send JPEG data
        if (res == ESP_OK) {
            res = httpd_resp_send_chunk(req, (const char *)_jpg_buf, _jpg_buf_len);
        }
        
        // Return frame buffer immediately
        esp_camera_fb_return(fb);
        fb = NULL;
        
        // Check for send errors (client disconnected)
        if (res != ESP_OK) {
            Serial.println("Client disconnected");
            break;
        }
        
        // Update stats
        frame_count++;
        
        // Yield to WiFi stack - CRITICAL for stable streaming
        vTaskDelay(1);
        
        // FPS calculation every 100 frames
        if (frame_count % 100 == 0) {
            int64_t now_us = esp_timer_get_time();
            float fps = 100.0f * 1000000.0f / (now_us - last_frame_us);
            last_frame_us = now_us;
            Serial.printf("📊 Stream: %.1f FPS, %u KB avg\n", fps, _jpg_buf_len / 1024);
        }
    }
    
    // Cleanup on exit
    stream_client_connected = false;
    Serial.printf("📹 Stream ended: %lu frames\n", frame_count);
    return res;
}

// Status endpoint - check if stream is available
static esp_err_t status_handler(httpd_req_t *req) {
    char json[256];
    snprintf(json, sizeof(json), 
        "{\"streaming\":%s,\"uptime\":%lu,\"heap\":%u,\"psram\":%u}",
        stream_client_connected ? "true" : "false",
        millis() / 1000,
        ESP.getFreeHeap(),
        ESP.getFreePsram());
    
    httpd_resp_set_type(req, "application/json");
    httpd_resp_set_hdr(req, "Access-Control-Allow-Origin", "*");
    return httpd_resp_send(req, json, strlen(json));
}

// Force disconnect current stream client
static esp_err_t disconnect_handler(httpd_req_t *req) {
    if (stream_client_connected) {
        stream_client_connected = false;  // Signal stream loop to exit
        httpd_resp_sendstr(req, "Stream client disconnected");
    } else {
        httpd_resp_sendstr(req, "No client connected");
    }
    return ESP_OK;
}

// Reboot handler - top-level (so it compiles correctly)
static esp_err_t reboot_handler(httpd_req_t *req) {
    httpd_resp_sendstr(req, "Rebooting");
    // give client time to receive
    delay(100);
    esp_restart();
    return ESP_OK;
}

// ============== START WEB SERVER ==============
void startCameraServer() {
    httpd_config_t config = HTTPD_DEFAULT_CONFIG();
    config.server_port = 80;
    config.stack_size = 8192;  // Larger stack for stream handling
    config.max_uri_handlers = 8;

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
    
    httpd_uri_t status_uri = {
        .uri       = "/status",
        .method    = HTTP_GET,
        .handler   = status_handler,
        .user_ctx  = NULL
    };
    
    httpd_uri_t disconnect_uri = {
        .uri       = "/disconnect",
        .method    = HTTP_GET,
        .handler   = disconnect_handler,
        .user_ctx  = NULL
    };

    // Reboot endpoint
    httpd_uri_t reboot_uri = {
        .uri       = "/reboot",
        .method    = HTTP_GET,
        .handler   = reboot_handler,
        .user_ctx  = NULL
    };

    Serial.printf("Starting web server on port %d\n", config.server_port);
    if (httpd_start(&camera_httpd, &config) == ESP_OK) {
        httpd_register_uri_handler(camera_httpd, &index_uri);
        httpd_register_uri_handler(camera_httpd, &stream_uri);
        httpd_register_uri_handler(camera_httpd, &status_uri);
        httpd_register_uri_handler(camera_httpd, &disconnect_uri);
        httpd_register_uri_handler(camera_httpd, &reboot_uri);
        Serial.println("✓ Camera server started");
        Serial.println("   /stream    - MJPEG video stream");
        Serial.println("   /status    - JSON status (check if busy)");
        Serial.println("   /disconnect - Force disconnect current client");
        Serial.println("   /reboot    - Reboot device");
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

    // Announce mDNS name for easier discovery on LAN
    if (MDNS.begin(HOSTNAME)) {
        Serial.println("✓ mDNS responder started");
        MDNS.addService("http", "tcp", 80);
    } else {
        Serial.println("⚠️ mDNS failed to start");
    }
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

    // Ensure WiFi stays connected; try reconnecting if lost
    if (WiFi.status() != WL_CONNECTED) {
        wifi_fail_count++;
        Serial.printf("⚠️ WiFi disconnected (%d/%d), attempting reconnect...\n", wifi_fail_count, WIFI_MAX_FAILS);
        if (wifiMulti.run(5000) == WL_CONNECTED) {
            Serial.println("✓ WiFi reconnected");
            wifi_fail_count = 0;
        } else {
            Serial.println("   reconnect attempt failed");
            if (wifi_fail_count >= WIFI_MAX_FAILS) {
                Serial.println("⚠️ WiFi failed repeatedly, restarting device...");
                delay(2000);
                ESP.restart();
            }
        }
    } else {
        wifi_fail_count = 0; // reset counter when connected
    }

    delay(10);
}
