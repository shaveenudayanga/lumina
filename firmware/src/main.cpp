/**
 * Lumina Pro Firmware - "The Split Nervous System"
 * ESP32 DevKit V1 (Device A - Body)
 * 
 * Architecture:
 *   - Device A (Body): This ESP32 - Motors, Lamp, Audio, Touch, OLED
 *   - Device B (Eyes): ESP32-CAM - Passive IP Camera
 *   - Device C (Brain): Laptop (Python) - AI Processing
 * 
 * Hardware Pinout:
 *   - Pan Servo:    GPIO 18
 *   - Tilt Servo:   GPIO 19
 *   - OLED SDA:     GPIO 21
 *   - OLED SCL:     GPIO 22
 *   - WS2812 LED:   GPIO 5 (via HW-222 Signal Booster)
 *   - Touch Sensor: GPIO 4 (TTP223)
 *   - I2S LRC:      GPIO 25
 *   - I2S BCLK:     GPIO 26
 *   - I2S DIN:      GPIO 27
 *   - Mic ADC:      GPIO 34 (MAX4466)
 * 
 * Features:
 *   - WiFiManager for captive portal setup
 *   - ArduinoOTA for wireless updates
 *   - Touch toggle for chat mode
 *   - UDP communication with Brain (laptop)
 */

#include <Arduino.h>
#include <WiFi.h>
#include <WiFiManager.h>
#include <ArduinoOTA.h>
#include <WiFiUdp.h>
#include <Wire.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>
#include <ESP32Servo.h>
#include <FastLED.h>

// ============== PIN DEFINITIONS ==============
#define PIN_SERVO_PAN    18
#define PIN_SERVO_TILT   19
#define PIN_OLED_SDA     21
#define PIN_OLED_SCL     22
#define PIN_LED_DATA     5    // Via HW-222 booster
#define PIN_TOUCH        4    // TTP223 touch sensor
#define PIN_I2S_LRC      25
#define PIN_I2S_BCLK     26
#define PIN_I2S_DIN      27
#define PIN_MIC_ADC      34   // MAX4466 analog out

// ============== HARDWARE CONSTANTS ==============
#define SCREEN_WIDTH     128
#define SCREEN_HEIGHT    64
#define OLED_RESET       -1
#define OLED_ADDR        0x3C

#define NUM_LEDS         8    // LED stick count
#define LED_BRIGHTNESS   80

#define SERVO_MIN_US     500
#define SERVO_MAX_US     2400

// ============== NETWORK SETTINGS ==============
#define UDP_PORT         5005
#define HOSTNAME         "lumina"

// ============== TIMING CONSTANTS ==============
#define BLINK_INTERVAL       4000
#define TALK_ANIM_INTERVAL   150
#define LED_UPDATE_INTERVAL  20
#define TOUCH_DEBOUNCE       300
#define UDP_CHECK_INTERVAL   5
#define STATUS_SEND_INTERVAL 500

// ============== GLOBAL OBJECTS ==============
Adafruit_SSD1306 display(SCREEN_WIDTH, SCREEN_HEIGHT, &Wire, OLED_RESET);
Servo panServo;
Servo tiltServo;
CRGB leds[NUM_LEDS];
WiFiUDP udp;
WiFiManager wifiManager;

// ============== STATE VARIABLES ==============
enum FaceState { FACE_SLEEP, FACE_HAPPY, FACE_TALKING, FACE_LISTENING, FACE_SAD, FACE_LOVE };
FaceState currentFace = FACE_SLEEP;

bool chatMode = false;      // Toggle via touch sensor
bool isTalking = false;
bool isLocked = false;

int targetPan = 90;
int targetTilt = 90;
int currentPan = 90;
int currentTilt = 90;

// LED color state
CRGB currentColor = CRGB::Blue;
uint8_t currentBrightness = LED_BRIGHTNESS;

// ============== TIMING VARIABLES ==============
unsigned long lastBlinkTime = 0;
unsigned long lastTalkAnimTime = 0;
unsigned long lastLedUpdateTime = 0;
unsigned long lastTouchTime = 0;
unsigned long lastStatusSendTime = 0;
unsigned long lastUdpCheckTime = 0;

bool eyesOpen = true;
int mouthState = 0;
uint8_t breathPhase = 0;
bool lastTouchState = false;

// ============== UDP BUFFER ==============
char udpBuffer[256];
IPAddress brainIP;
bool brainConnected = false;

// ============== FUNCTION PROTOTYPES ==============
void setupWiFi();
void setupOTA();
void parseCommand(String cmd);
void updateServos();
void updateFace();
void updateLeds();
void handleTouch();
void handleUDP();
void sendStatus(const char* status);
void drawFace();
void drawEyes(bool open);
void drawMouth(int state);
void showIP();
void drawListeningIcon();
void drawHeartEye(int cx, int cy);

// ============== SETUP ==============
void setup() {
    Serial.begin(115200);
    Serial.println("\n\n=============================");
    Serial.println("  Lumina Pro - Body Unit");
    Serial.println("=============================");

    // Initialize Touch Sensor
    pinMode(PIN_TOUCH, INPUT);
    Serial.println("✓ Touch sensor ready");

    // Initialize I2C for OLED
    Wire.begin(PIN_OLED_SDA, PIN_OLED_SCL);
    
    // Initialize OLED
    if (!display.begin(SSD1306_SWITCHCAPVCC, OLED_ADDR)) {
        Serial.println("✗ OLED failed!");
        while (true) { delay(100); }
    }
    display.clearDisplay();
    display.setTextColor(SSD1306_WHITE);
    display.setTextSize(1);
    display.setCursor(0, 0);
    display.println("Lumina Booting...");
    display.display();
    Serial.println("✓ OLED ready");

    // Initialize Servos
    ESP32PWM::allocateTimer(0);
    ESP32PWM::allocateTimer(1);
    panServo.setPeriodHertz(50);
    tiltServo.setPeriodHertz(50);
    panServo.attach(PIN_SERVO_PAN, SERVO_MIN_US, SERVO_MAX_US);
    tiltServo.attach(PIN_SERVO_TILT, SERVO_MIN_US, SERVO_MAX_US);
    panServo.write(90);
    tiltServo.write(90);
    Serial.println("✓ Servos ready");

    // Initialize FastLED (GPIO 5 via HW-222 booster)
    FastLED.addLeds<WS2812, PIN_LED_DATA, GRB>(leds, NUM_LEDS);
    FastLED.setBrightness(LED_BRIGHTNESS);
    fill_solid(leds, NUM_LEDS, CRGB::Yellow);  // Boot color
    FastLED.show();
    Serial.println("✓ LEDs ready");

    // Initialize ADC for Mic
    analogReadResolution(12);
    pinMode(PIN_MIC_ADC, INPUT);
    Serial.println("✓ Mic ready");

    // Setup WiFi with captive portal
    setupWiFi();
    
    // Setup OTA
    setupOTA();
    
    // Start UDP listener
    udp.begin(UDP_PORT);
    Serial.printf("✓ UDP listening on port %d\n", UDP_PORT);

    // Show IP address on OLED
    showIP();
    delay(3000);
    
    // Initial state
    currentFace = FACE_SLEEP;
    currentColor = CRGB::Blue;
    drawFace();
    
    Serial.println("\n✓ Lumina Ready!");
    Serial.println("Touch sensor to toggle chat mode");
}

// ============== WIFI SETUP ==============
void setupWiFi() {
    display.clearDisplay();
    display.setCursor(0, 0);
    display.println("Connecting WiFi...");
    display.display();

    // Set hostname
    WiFi.setHostname(HOSTNAME);
    
    // Configure WiFiManager
    wifiManager.setConfigPortalTimeout(180);  // 3 minute timeout
    wifiManager.setAPCallback([](WiFiManager* wm) {
        display.clearDisplay();
        display.setCursor(0, 0);
        display.println("WiFi Setup Mode");
        display.println();
        display.println("Connect to:");
        display.println("  Lumina-Setup");
        display.println();
        display.println("Open browser:");
        display.println("  192.168.4.1");
        display.display();
        
        // Pulse LEDs orange during setup
        fill_solid(leds, NUM_LEDS, CRGB::Orange);
        FastLED.show();
    });
    
    // Try to connect, or start config portal
    if (!wifiManager.autoConnect("Lumina-Setup")) {
        Serial.println("Failed to connect, restarting...");
        display.clearDisplay();
        display.setCursor(0, 0);
        display.println("WiFi Failed!");
        display.println("Restarting...");
        display.display();
        delay(2000);
        ESP.restart();
    }
    
    Serial.println("✓ WiFi connected!");
    Serial.print("  IP: ");
    Serial.println(WiFi.localIP());
    
    // Success - green flash
    fill_solid(leds, NUM_LEDS, CRGB::Green);
    FastLED.show();
    delay(500);
}

// ============== OTA SETUP ==============
void setupOTA() {
    ArduinoOTA.setHostname(HOSTNAME);
    
    ArduinoOTA.onStart([]() {
        String type = (ArduinoOTA.getCommand() == U_FLASH) ? "firmware" : "filesystem";
        Serial.println("OTA Start: " + type);
        
        display.clearDisplay();
        display.setCursor(0, 20);
        display.setTextSize(1);
        display.println("OTA Update...");
        display.display();
        
        fill_solid(leds, NUM_LEDS, CRGB::Purple);
        FastLED.show();
    });
    
    ArduinoOTA.onProgress([](unsigned int progress, unsigned int total) {
        int percent = (progress * 100) / total;
        Serial.printf("OTA Progress: %u%%\r", percent);
        
        display.clearDisplay();
        display.setCursor(0, 10);
        display.println("OTA Update");
        display.drawRect(10, 30, 108, 15, SSD1306_WHITE);
        display.fillRect(12, 32, (percent * 104) / 100, 11, SSD1306_WHITE);
        display.setCursor(50, 50);
        display.printf("%d%%", percent);
        display.display();
    });
    
    ArduinoOTA.onEnd([]() {
        Serial.println("\nOTA Complete!");
        display.clearDisplay();
        display.setCursor(20, 25);
        display.println("Update Done!");
        display.display();
        fill_solid(leds, NUM_LEDS, CRGB::Green);
        FastLED.show();
    });
    
    ArduinoOTA.onError([](ota_error_t error) {
        Serial.printf("OTA Error[%u]: ", error);
        fill_solid(leds, NUM_LEDS, CRGB::Red);
        FastLED.show();
    });
    
    ArduinoOTA.begin();
    Serial.println("✓ OTA ready");
}

// ============== MAIN LOOP ==============
void loop() {
    unsigned long currentMillis = millis();
    
    // Handle OTA updates
    ArduinoOTA.handle();
    
    // Handle Touch Sensor
    handleTouch();
    
    // Handle UDP Commands
    if (currentMillis - lastUdpCheckTime >= UDP_CHECK_INTERVAL) {
        lastUdpCheckTime = currentMillis;
        handleUDP();
    }
    
    // Also check Serial for debugging
    while (Serial.available() > 0) {
        static String serialBuffer = "";
        char c = Serial.read();
        if (c == '\n') {
            serialBuffer.trim();
            if (serialBuffer.length() > 0) {
                parseCommand(serialBuffer);
            }
            serialBuffer = "";
        } else {
            serialBuffer += c;
        }
    }
    
    // Servo Smoothing
    updateServos();
    
    // Face Animation
    if (isTalking) {
        if (currentMillis - lastTalkAnimTime >= TALK_ANIM_INTERVAL) {
            lastTalkAnimTime = currentMillis;
            mouthState = random(0, 3);
            int wiggle = random(-3, 4);
            tiltServo.write(constrain(currentTilt + wiggle, 45, 135));
            drawFace();
        }
    } else {
        if (currentMillis - lastBlinkTime >= BLINK_INTERVAL) {
            lastBlinkTime = currentMillis;
            eyesOpen = false;
            drawFace();
        }
        if (!eyesOpen && currentMillis - lastBlinkTime >= 200) {
            eyesOpen = true;
            drawFace();
        }
    }
    
    // LED Breathing Animation
    if (currentMillis - lastLedUpdateTime >= LED_UPDATE_INTERVAL) {
        lastLedUpdateTime = currentMillis;
        updateLeds();
    }
    
    // Periodic status send to brain
    if (brainConnected && currentMillis - lastStatusSendTime >= STATUS_SEND_INTERVAL) {
        lastStatusSendTime = currentMillis;
        // Send heartbeat with current state
        if (chatMode) {
            sendStatus("HEARTBEAT:LISTENING");
        } else {
            sendStatus("HEARTBEAT:MUTE");
        }
    }
}

// ============== TOUCH HANDLER ==============
void handleTouch() {
    bool touchState = digitalRead(PIN_TOUCH) == HIGH;
    unsigned long now = millis();
    
    // Debounced toggle on rising edge
    if (touchState && !lastTouchState && (now - lastTouchTime > TOUCH_DEBOUNCE)) {
        lastTouchTime = now;
        
        // Toggle chat mode
        chatMode = !chatMode;
        
        Serial.printf("Touch! Chat mode: %s\n", chatMode ? "ON" : "OFF");
        
        if (chatMode) {
            // Start listening mode
            currentColor = CRGB::Green;
            currentFace = FACE_LISTENING;
            sendStatus("STATUS:LISTENING");
            
            // Visual feedback
            fill_solid(leds, NUM_LEDS, CRGB::Green);
            FastLED.show();
            drawFace();
        } else {
            // Stop listening mode
            currentColor = CRGB::Red;
            currentFace = FACE_SLEEP;
            sendStatus("STATUS:MUTE");
            
            // Visual feedback
            fill_solid(leds, NUM_LEDS, CRGB::Red);
            FastLED.show();
            delay(200);
            currentColor = CRGB::Blue;
            drawFace();
        }
    }
    
    lastTouchState = touchState;
}

// ============== UDP HANDLER ==============
void handleUDP() {
    int packetSize = udp.parsePacket();
    if (packetSize) {
        int len = udp.read(udpBuffer, sizeof(udpBuffer) - 1);
        if (len > 0) {
            udpBuffer[len] = '\0';
            
            // Remember brain's IP for responses
            brainIP = udp.remoteIP();
            brainConnected = true;
            
            String cmd = String(udpBuffer);
            cmd.trim();
            
            Serial.printf("UDP from %s: %s\n", brainIP.toString().c_str(), cmd.c_str());
            parseCommand(cmd);
        }
    }
}

// ============== SEND STATUS TO BRAIN ==============
void sendStatus(const char* status) {
    if (brainConnected) {
        udp.beginPacket(brainIP, UDP_PORT);
        udp.print(status);
        udp.endPacket();
        Serial.printf("-> Brain: %s\n", status);
    }
}

// ============== COMMAND PARSER ==============
void parseCommand(String cmd) {
    Serial.print("CMD: ");
    Serial.println(cmd);

    // Discovery/Handshake
    if (cmd == "DISCOVER") {
        sendStatus("LUMINA_BODY");
        return;
    }
    
    if (cmd == "PING") {
        sendStatus("PONG");
        return;
    }

    // Pan/Tilt command: P90T45
    if (cmd.startsWith("P") && cmd.indexOf("T") > 0) {
        int tIndex = cmd.indexOf("T");
        targetPan = cmd.substring(1, tIndex).toInt();
        targetTilt = cmd.substring(tIndex + 1).toInt();
        targetPan = constrain(targetPan, 0, 180);
        targetTilt = constrain(targetTilt, 45, 135);
        isLocked = true;
        return;
    }

    // Face commands
    if (cmd == "F_TALK_START") {
        isTalking = true;
        currentFace = FACE_TALKING;
        drawFace();
        return;
    }
    
    if (cmd == "F_TALK_STOP") {
        isTalking = false;
        mouthState = 0;
        currentFace = FACE_HAPPY;
        drawFace();
        return;
    }
    
    if (cmd == "F_HAPPY") {
        currentFace = FACE_HAPPY;
        isLocked = true;
        drawFace();
        return;
    }
    
    if (cmd == "F_SLEEP") {
        currentFace = FACE_SLEEP;
        isLocked = false;
        isTalking = false;
        chatMode = false;
        currentColor = CRGB::Blue;
        drawFace();
        return;
    }
    
    if (cmd == "F_LISTENING") {
        currentFace = FACE_LISTENING;
        currentColor = CRGB::Green;
        drawFace();
        return;
    }
    
    if (cmd == "F_SAD") {
        currentFace = FACE_SAD;
        drawFace();
        return;
    }
    
    if (cmd == "F_LOVE") {
        currentFace = FACE_LOVE;
        currentColor = CRGB::DeepPink;
        drawFace();
        return;
    }

    // LED brightness: L[0-255] or B[0-100]
    if (cmd.startsWith("L")) {
        int brightness = cmd.substring(1).toInt();
        currentBrightness = constrain(brightness, 0, 255);
        FastLED.setBrightness(currentBrightness);
        FastLED.show();
        return;
    }
    
    if (cmd.startsWith("B")) {
        int percent = cmd.substring(1).toInt();
        currentBrightness = map(constrain(percent, 0, 100), 0, 100, 0, 255);
        FastLED.setBrightness(currentBrightness);
        FastLED.show();
        return;
    }
    
    // LED color: C[r],[g],[b] or COLOR:[name]
    if (cmd.startsWith("C") && cmd.indexOf(",") > 0) {
        int c1 = cmd.indexOf(",");
        int c2 = cmd.lastIndexOf(",");
        int r = cmd.substring(1, c1).toInt();
        int g = cmd.substring(c1 + 1, c2).toInt();
        int b = cmd.substring(c2 + 1).toInt();
        currentColor = CRGB(r, g, b);
        return;
    }
    
    if (cmd.startsWith("COLOR:")) {
        String colorName = cmd.substring(6);
        colorName.toLowerCase();
        
        if (colorName == "red") currentColor = CRGB::Red;
        else if (colorName == "green") currentColor = CRGB::Green;
        else if (colorName == "blue") currentColor = CRGB::Blue;
        else if (colorName == "yellow") currentColor = CRGB::Yellow;
        else if (colorName == "orange") currentColor = CRGB::Orange;
        else if (colorName == "purple") currentColor = CRGB::Purple;
        else if (colorName == "pink") currentColor = CRGB::DeepPink;
        else if (colorName == "cyan") currentColor = CRGB::Cyan;
        else if (colorName == "white") currentColor = CRGB::White;
        else if (colorName == "warm") currentColor = CRGB(255, 200, 100);
        else if (colorName == "cool") currentColor = CRGB(200, 220, 255);
        
        fill_solid(leds, NUM_LEDS, currentColor);
        FastLED.show();
        return;
    }
    
    // Enable/disable chat mode remotely
    if (cmd == "CHAT_START") {
        chatMode = true;
        currentColor = CRGB::Green;
        currentFace = FACE_LISTENING;
        drawFace();
        sendStatus("STATUS:LISTENING");
        return;
    }
    
    if (cmd == "CHAT_STOP") {
        chatMode = false;
        isTalking = false;
        currentColor = CRGB::Blue;
        currentFace = FACE_SLEEP;
        drawFace();
        sendStatus("STATUS:MUTE");
        return;
    }
}

// ============== SERVO UPDATE ==============
void updateServos() {
    if (currentPan != targetPan) {
        if (currentPan < targetPan) currentPan = min(currentPan + 2, targetPan);
        else currentPan = max(currentPan - 2, targetPan);
        panServo.write(currentPan);
    }
    
    if (currentTilt != targetTilt) {
        if (currentTilt < targetTilt) currentTilt = min(currentTilt + 2, targetTilt);
        else currentTilt = max(currentTilt - 2, targetTilt);
        tiltServo.write(currentTilt);
    }
}

// ============== LED UPDATE ==============
void updateLeds() {
    breathPhase += 2;
    uint8_t brightness = (sin8(breathPhase) / 3) + 80;  // 80-165 range
    
    CRGB color = currentColor;
    color.nscale8(brightness);
    fill_solid(leds, NUM_LEDS, color);
    FastLED.show();
}

// ============== SHOW IP ADDRESS ==============
void showIP() {
    display.clearDisplay();
    display.setTextSize(1);
    display.setCursor(0, 0);
    display.println("Lumina Connected!");
    display.println();
    display.print("IP: ");
    display.println(WiFi.localIP());
    display.println();
    display.print("Host: ");
    display.println(HOSTNAME);
    display.println();
    display.printf("UDP Port: %d", UDP_PORT);
    display.display();
}

// ============== FACE DRAWING ==============
void drawFace() {
    display.clearDisplay();
    
    switch (currentFace) {
        case FACE_SLEEP:
            // Sleepy eyes (horizontal lines)
            display.fillRect(20, 28, 30, 4, SSD1306_WHITE);
            display.fillRect(78, 28, 30, 4, SSD1306_WHITE);
            // ZZZ
            display.setTextSize(1);
            display.setCursor(100, 10);
            display.print("z");
            display.setCursor(105, 5);
            display.print("Z");
            break;
            
        case FACE_HAPPY:
            drawEyes(eyesOpen);
            drawMouth(0);  // Smile
            break;
            
        case FACE_TALKING:
            drawEyes(true);
            drawMouth(mouthState);
            break;
            
        case FACE_LISTENING:
            drawListeningIcon();
            break;
            
        case FACE_SAD:
            // Sad droopy eyes
            display.drawLine(20, 20, 50, 30, SSD1306_WHITE);
            display.drawLine(78, 30, 108, 20, SSD1306_WHITE);
            display.fillCircle(35, 32, 8, SSD1306_WHITE);
            display.fillCircle(93, 32, 8, SSD1306_WHITE);
            // Frown
            for (int i = -15; i <= 15; i++) {
                int y = 52 - (i * i) / 30;
                display.drawPixel(64 + i, y, SSD1306_WHITE);
            }
            break;
            
        case FACE_LOVE:
            // Heart eyes
            drawHeartEye(35, 25);
            drawHeartEye(93, 25);
            // Blush smile
            for (int i = -15; i <= 15; i++) {
                int y = 50 + (i * i) / 30;
                display.drawPixel(64 + i, y, SSD1306_WHITE);
                display.drawPixel(64 + i, y + 1, SSD1306_WHITE);
            }
            break;
    }
    
    display.display();
}

void drawHeartEye(int cx, int cy) {
    // Simple heart shape
    display.fillCircle(cx - 4, cy - 2, 5, SSD1306_WHITE);
    display.fillCircle(cx + 4, cy - 2, 5, SSD1306_WHITE);
    display.fillTriangle(cx - 9, cy, cx + 9, cy, cx, cy + 10, SSD1306_WHITE);
}

void drawListeningIcon() {
    // Microphone icon in center
    int cx = 64, cy = 28;
    
    // Mic body
    display.fillRoundRect(cx - 8, cy - 15, 16, 25, 8, SSD1306_WHITE);
    
    // Mic stand arc
    display.drawCircle(cx, cy + 5, 15, SSD1306_WHITE);
    display.fillRect(cx - 16, cy - 10, 32, 20, SSD1306_BLACK);  // Clear top half
    
    // Stand
    display.drawLine(cx, cy + 20, cx, cy + 28, SSD1306_WHITE);
    display.drawLine(cx - 10, cy + 28, cx + 10, cy + 28, SSD1306_WHITE);
    
    // Sound waves
    display.drawCircle(cx, cy, 25, SSD1306_WHITE);
    display.fillRect(cx - 30, cy - 30, 60, 35, SSD1306_BLACK);  // Clear waves above
    
    // "Listening..." text
    display.setTextSize(1);
    display.setCursor(30, 54);
    display.print("Listening...");
}

void drawEyes(bool open) {
    int eyeY = 20;
    int leftEyeX = 32;
    int rightEyeX = 96;
    int eyeRadius = 12;
    
    if (open) {
        display.fillCircle(leftEyeX, eyeY, eyeRadius, SSD1306_WHITE);
        display.fillCircle(rightEyeX, eyeY, eyeRadius, SSD1306_WHITE);
        display.fillCircle(leftEyeX + 2, eyeY + 2, 4, SSD1306_BLACK);
        display.fillCircle(rightEyeX + 2, eyeY + 2, 4, SSD1306_BLACK);
    } else {
        display.fillRect(leftEyeX - eyeRadius, eyeY - 2, eyeRadius * 2, 4, SSD1306_WHITE);
        display.fillRect(rightEyeX - eyeRadius, eyeY - 2, eyeRadius * 2, 4, SSD1306_WHITE);
    }
}

void drawMouth(int state) {
    int mouthY = 48;
    int mouthX = 64;
    
    switch (state) {
        case 0:  // Smile
            for (int i = -15; i <= 15; i++) {
                int y = mouthY + (i * i) / 30;
                display.drawPixel(mouthX + i, y, SSD1306_WHITE);
                display.drawPixel(mouthX + i, y + 1, SSD1306_WHITE);
            }
            break;
            
        case 1:  // Open O
            display.fillCircle(mouthX, mouthY, 8, SSD1306_WHITE);
            display.fillCircle(mouthX, mouthY, 4, SSD1306_BLACK);
            break;
            
        case 2:  // Wide open
            display.fillRoundRect(mouthX - 12, mouthY - 6, 24, 12, 4, SSD1306_WHITE);
            display.fillRoundRect(mouthX - 8, mouthY - 3, 16, 6, 2, SSD1306_BLACK);
            break;
    }
}
