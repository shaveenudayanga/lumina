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
#include <driver/i2s.h>

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
#define PIN_AMP_EN       14   // Amplifier enable / mute control (connect to SHDN/OE)
#define PIN_TONE         13   // Tone output pin (use through amplifier input or coupling capacitor)
#define TONE_LEDC_CHANNEL 0   // LEDC channel for tone generation


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
#define UDP_AUDIO_OUT_PORT 5006  // ESP32 sends mic audio to laptop
#define UDP_AUDIO_IN_PORT  5007  // ESP32 receives speaker audio from laptop
#define HOSTNAME         "lumina"

// ============== TIMING CONSTANTS ==============
#define BLINK_INTERVAL       4000
#define TALK_ANIM_INTERVAL   150
#define LED_UPDATE_INTERVAL  20
#define TOUCH_DEBOUNCE       300
#define UDP_CHECK_INTERVAL   5
#define STATUS_SEND_INTERVAL 500

// ============== AUDIO SETTINGS ==============
#define I2S_SAMPLE_RATE      16000  // 16kHz for voice
#define I2S_BUFFER_SIZE      512    // Samples per buffer
#define I2S_MIC_PORT         I2S_NUM_0
#define I2S_SPEAKER_PORT     I2S_NUM_1

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
CRGB currentColor = CRGB::White;
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

// ============== AUDIO STREAMING ==============
WiFiUDP audioOutUdp;  // Send mic audio to laptop
WiFiUDP audioInUdp;   // Receive speaker audio from laptop
bool audioStreamingActive = false;
TaskHandle_t micTaskHandle = NULL;
TaskHandle_t speakerTaskHandle = NULL;
int16_t micBuffer[I2S_BUFFER_SIZE];
int16_t speakerBuffer[I2S_BUFFER_SIZE];

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
void playTone(int freq, int duration_ms);
void setupI2S();
void startAudioStreaming();
void stopAudioStreaming();
void micStreamTask(void* param);
void speakerPlaybackTask(void* param);
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
    fill_solid(leds, NUM_LEDS, CRGB::White);  // Boot color
    FastLED.show();
    Serial.println("✓ LEDs ready");

    // Initialize ADC for Mic
    analogReadResolution(12);
    pinMode(PIN_MIC_ADC, INPUT);
    Serial.println("✓ Mic ready");

    // Initialize amplifier mute control (keep muted by default)
    pinMode(PIN_AMP_EN, OUTPUT);
    digitalWrite(PIN_AMP_EN, LOW);
    Serial.println("✓ Amp muted (PIN_AMP_EN)");

    // Initialize tone output (LEDC PWM) - pin should be routed to amp input via coupling
    pinMode(PIN_TONE, OUTPUT);
    ledcSetup(TONE_LEDC_CHANNEL, 2000, 8); // initial 2kHz, 8-bit
    ledcAttachPin(PIN_TONE, TONE_LEDC_CHANNEL);
    ledcWriteTone(TONE_LEDC_CHANNEL, 0); // silence
    Serial.println("✓ Tone output initialized (PIN_TONE)");

    // NOTE: I2S audio will be initialized when AUDIO_START command is received
    // This prevents noise during boot and when audio is not in use

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
    currentColor = CRGB::White;
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

            // Enable amplifier for listening/speaking
            digitalWrite(PIN_AMP_EN, HIGH);
            Serial.println("✓ Amp enabled");
            
            // Visual feedback
            fill_solid(leds, NUM_LEDS, CRGB::Green);
            FastLED.show();
            drawFace();
        } else {
            // Stop listening mode
            currentColor = CRGB::Red;
            currentFace = FACE_SLEEP;
            sendStatus("STATUS:MUTE");

            // Mute amplifier when chat stops
            digitalWrite(PIN_AMP_EN, LOW);
            Serial.println("✓ Amp muted");
            
            // Visual feedback
            fill_solid(leds, NUM_LEDS, CRGB::Red);
            FastLED.show();
            delay(200);
            currentColor = CRGB::White;
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
        // Ensure amplifier is enabled when speaking
        digitalWrite(PIN_AMP_EN, HIGH);
        Serial.println("✓ Amp enabled (F_TALK_START)");
        drawFace();
        return;
    }
    
    if (cmd == "F_TALK_STOP") {
        isTalking = false;
        mouthState = 0;
        currentFace = FACE_HAPPY;
        // Mute amp if chat mode is not active
        if (!chatMode) {
            digitalWrite(PIN_AMP_EN, LOW);
            Serial.println("✓ Amp muted (F_TALK_STOP)");
        }
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
        currentColor = CRGB::White;
        // Mute amplifier when going to sleep
        digitalWrite(PIN_AMP_EN, LOW);
        Serial.println("✓ Amp muted (F_SLEEP)");
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
        Serial.printf("LED: COLOR R=%d G=%d B=%d\n", currentColor.r, currentColor.g, currentColor.b);
        Serial.printf("LED: BRIGHTNESS=%d\n", currentBrightness);
        return;
    }
    
    // Enable/disable chat mode remotely
    if (cmd == "CHAT_START") {
        chatMode = true;
        currentColor = CRGB::Green;
        currentFace = FACE_LISTENING;
        // Enable amp for remote chat start
        digitalWrite(PIN_AMP_EN, HIGH);
        Serial.println("✓ Amp enabled (CHAT_START)");
        drawFace();
        sendStatus("STATUS:LISTENING");
        return;
    }
    
    if (cmd == "CHAT_STOP") {
        chatMode = false;
        isTalking = false;
        currentColor = CRGB::White;
        currentFace = FACE_SLEEP;
        // Mute amp for remote chat stop
        digitalWrite(PIN_AMP_EN, LOW);
        Serial.println("✓ Amp muted (CHAT_STOP)");
        drawFace();
        sendStatus("STATUS:MUTE");
        return;
    }

    // Tone command: TONE or TONE:<freq>,<duration_ms>
    if (cmd.startsWith("TONE")) {
        int freq = 1500; // default 1.5 kHz
        int dur = 300;   // default 300 ms
        if (cmd.indexOf(":") >= 0) {
            String params = cmd.substring(cmd.indexOf(":") + 1);
            int comma = params.indexOf(",");
            if (comma > 0) {
                freq = params.substring(0, comma).toInt();
                dur = params.substring(comma + 1).toInt();
            } else {
                freq = params.toInt();
            }
        }
        playTone(freq, dur);
        return;
    }

    // Quick hardware-driven sound test (toggle PIN_TONE manually)
    // Usage: SOUND_TEST[:freq,ms]  freq used only to compute toggle timing (approx)
    if (cmd.startsWith("SOUND_TEST")) {
        int freq = 1000; int dur = 300;
        if (cmd.indexOf(":") >= 0) {
            String params = cmd.substring(cmd.indexOf(":") + 1);
            int comma = params.indexOf(",");
            if (comma > 0) {
                freq = params.substring(0, comma).toInt();
                dur = params.substring(comma + 1).toInt();
            } else {
                freq = params.toInt();
            }
        }
        Serial.printf("SOUND_TEST: freq=%d dur=%d\n", freq, dur);
        // enable amp
        digitalWrite(PIN_AMP_EN, HIGH);
        int half_us = max(200, 500000 / max(1, freq) ); // approximate
        unsigned long end = millis() + dur;
        while (millis() < end) {
            digitalWrite(PIN_TONE, HIGH);
            delayMicroseconds(half_us);
            digitalWrite(PIN_TONE, LOW);
            delayMicroseconds(half_us);
        }
        digitalWrite(PIN_TONE, LOW);
        // restore amp
        digitalWrite(PIN_AMP_EN, LOW);
        Serial.println("SOUND_TEST: done");
        return;
    }

    // Diagnostics commands
    if (cmd == "MIC_TEST") {
        // Read analog mic multiple times and print average
        long sum = 0;
        const int samples = 32;
        for (int i = 0; i < samples; i++) {
            sum += analogRead(PIN_MIC_ADC);
            delay(5);
        }
        int avg = sum / samples;
        Serial.printf("MIC_ADC: %d (avg of %d samples)\n", avg, samples);
        return;
    }

    if (cmd == "AMP_STATUS") {
        int state = digitalRead(PIN_AMP_EN);
        if (state) {
            Serial.println("AMP:ENABLED");
        } else {
            Serial.println("AMP:MUTED");
        }
        return;
    }
    
    // Audio streaming control
    if (cmd == "AUDIO_START") {
        startAudioStreaming();
        sendStatus("AUDIO:STREAMING");
        return;
    }
    
    if (cmd == "AUDIO_STOP") {
        stopAudioStreaming();
        sendStatus("AUDIO:STOPPED");
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
    // Log current face for diagnostics
    const char* faceNames[] = {"SLEEP","HAPPY","TALKING","LISTENING","SAD","LOVE"};
    int faceIndex = (int)currentFace - (int)FACE_SLEEP; // enum order matches array
    if (faceIndex >= 0 && faceIndex < 6) {
        Serial.printf("FACE: %s\n", faceNames[faceIndex]);
    } else {
        Serial.println("FACE: UNKNOWN");
    }
    
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

// Play a simple tone using LEDC PWM. Connect PIN_TONE to amp input (via coupling cap) or speaker driver.
void playTone(int freq, int duration_ms) {
    if (freq <= 0 || duration_ms <= 0) return;

    // Ensure amp is enabled while tone plays
    bool wasChat = chatMode;
    digitalWrite(PIN_AMP_EN, HIGH);
    Serial.printf("TONE: start freq=%d dur=%dms\n", freq, duration_ms);

    // Use ledcWriteTone (ESP32 helper) and set moderate duty to ensure audible level
    ledcWriteTone(TONE_LEDC_CHANNEL, freq);
    ledcWrite(TONE_LEDC_CHANNEL, 128); // 50% duty (8-bit)
    Serial.printf("TONE: PWM duty set=128\n");
    delay(duration_ms);
    // Stop tone
    ledcWriteTone(TONE_LEDC_CHANNEL, 0);
    ledcWrite(TONE_LEDC_CHANNEL, 0);

    // Restore amp state
    if (!wasChat) {
        digitalWrite(PIN_AMP_EN, LOW);
    }
    Serial.println("TONE: stop");
}

// ============== I2S AUDIO SETUP ==============
void setupI2S() {
    // Configure I2S for microphone input (INMP441 or similar)
    i2s_config_t i2s_mic_config = {
        .mode = (i2s_mode_t)(I2S_MODE_MASTER | I2S_MODE_RX),
        .sample_rate = I2S_SAMPLE_RATE,
        .bits_per_sample = I2S_BITS_PER_SAMPLE_16BIT,
        .channel_format = I2S_CHANNEL_FMT_ONLY_LEFT,
        .communication_format = I2S_COMM_FORMAT_STAND_I2S,
        .intr_alloc_flags = ESP_INTR_FLAG_LEVEL1,
        .dma_buf_count = 4,
        .dma_buf_len = I2S_BUFFER_SIZE,
        .use_apll = false,
        .tx_desc_auto_clear = false,
        .fixed_mclk = 0
    };
    
    i2s_pin_config_t pin_mic_config = {
        .bck_io_num = PIN_I2S_BCLK,
        .ws_io_num = PIN_I2S_LRC,
        .data_out_num = I2S_PIN_NO_CHANGE,
        .data_in_num = PIN_I2S_DIN
    };
    
    if (i2s_driver_install(I2S_MIC_PORT, &i2s_mic_config, 0, NULL) != ESP_OK) {
        Serial.println("✗ I2S mic driver install failed!");
        return;
    }
    
    if (i2s_set_pin(I2S_MIC_PORT, &pin_mic_config) != ESP_OK) {
        Serial.println("✗ I2S mic pin config failed!");
        return;
    }
    
    // Clear I2S buffers to prevent initial noise
    i2s_zero_dma_buffer(I2S_MIC_PORT);
    
    Serial.println("✓ I2S microphone ready");
    
    // Configure I2S for speaker output (MAX98357A or similar I2S DAC/amp)
    i2s_config_t i2s_speaker_config = {
        .mode = (i2s_mode_t)(I2S_MODE_MASTER | I2S_MODE_TX),
        .sample_rate = I2S_SAMPLE_RATE,
        .bits_per_sample = I2S_BITS_PER_SAMPLE_16BIT,
        .channel_format = I2S_CHANNEL_FMT_ONLY_LEFT,
        .communication_format = I2S_COMM_FORMAT_STAND_I2S,
        .intr_alloc_flags = ESP_INTR_FLAG_LEVEL1,
        .dma_buf_count = 4,
        .dma_buf_len = I2S_BUFFER_SIZE,
        .use_apll = false,
        .tx_desc_auto_clear = true,
        .fixed_mclk = 0
    };
    
    // Note: For I2S speaker, you may need different pins (e.g., GPIO32/33/15 for second I2S)
    // or use the same I2S port in TX mode (not simultaneous RX/TX)
    // For now, we'll use I2S_NUM_1 with separate pins (adjust as needed for your hardware)
    i2s_pin_config_t pin_speaker_config = {
        .bck_io_num = 32,     // BCLK for speaker (adjust to your wiring)
        .ws_io_num = 33,      // LRC for speaker (adjust to your wiring)  
        .data_out_num = 15,   // DOUT for speaker - CHANGED from 25 to avoid conflict
        .data_in_num = I2S_PIN_NO_CHANGE
    };
    
    if (i2s_driver_install(I2S_SPEAKER_PORT, &i2s_speaker_config, 0, NULL) != ESP_OK) {
        Serial.println("✗ I2S speaker driver install failed!");
        return;
    }
    
    if (i2s_set_pin(I2S_SPEAKER_PORT, &pin_speaker_config) != ESP_OK) {
        Serial.println("✗ I2S speaker pin config failed!");
        return;
    }
    
    // Clear I2S buffers to prevent initial noise
    i2s_zero_dma_buffer(I2S_SPEAKER_PORT);
    
    Serial.println("✓ I2S speaker ready");
}

// ============== AUDIO STREAMING CONTROL ==============
void startAudioStreaming() {
    if (audioStreamingActive) {
        Serial.println("Audio streaming already active");
        return;
    }
    
    if (!brainConnected) {
        Serial.println("Cannot start audio: Brain not connected");
        return;
    }
    
    // Initialize I2S now (not on boot) to prevent noise
    Serial.println("Initializing I2S for audio streaming...");
    setupI2S();
    
    audioStreamingActive = true;
    
    // Create microphone streaming task
    xTaskCreatePinnedToCore(
        micStreamTask,
        "MicStream",
        4096,
        NULL,
        1,
        &micTaskHandle,
        0
    );
    
    // Create speaker playback task
    xTaskCreatePinnedToCore(
        speakerPlaybackTask,
        "SpeakerPlay",
        4096,
        NULL,
        1,
        &speakerTaskHandle,
        0
    );
    
    Serial.println("✓ Audio streaming started");
}

void stopAudioStreaming() {
    if (!audioStreamingActive) return;
    
    audioStreamingActive = false;
    
    // Delete tasks
    if (micTaskHandle != NULL) {
        vTaskDelete(micTaskHandle);
        micTaskHandle = NULL;
    }
    
    if (speakerTaskHandle != NULL) {
        vTaskDelete(speakerTaskHandle);
        speakerTaskHandle = NULL;
    }
    
    // Deinitialize I2S to stop any noise
    Serial.println("Deinitializing I2S drivers...");
    i2s_driver_uninstall(I2S_MIC_PORT);
    i2s_driver_uninstall(I2S_SPEAKER_PORT);
    
    // Ensure amp is muted
    digitalWrite(PIN_AMP_EN, LOW);
    
    Serial.println("✓ Audio streaming stopped");
}

// ============== AUDIO STREAMING TASKS ==============
void micStreamTask(void* param) {
    size_t bytes_read = 0;
    
    Serial.println("Mic streaming task started");
    
    while (audioStreamingActive) {
        // Read from I2S microphone
        i2s_read(I2S_MIC_PORT, micBuffer, I2S_BUFFER_SIZE * sizeof(int16_t), &bytes_read, portMAX_DELAY);
        
        if (bytes_read > 0 && brainConnected) {
            // Send audio data to laptop via UDP
            audioOutUdp.beginPacket(brainIP, UDP_AUDIO_OUT_PORT);
            audioOutUdp.write((uint8_t*)micBuffer, bytes_read);
            audioOutUdp.endPacket();
        }
        
        // Small yield to prevent watchdog timeout
        vTaskDelay(1);
    }
    
    Serial.println("Mic streaming task ended");
    vTaskDelete(NULL);
}

void speakerPlaybackTask(void* param) {
    size_t bytes_written = 0;
    
    Serial.println("Speaker playback task started");
    
    // Initialize speaker buffer with silence
    memset(speakerBuffer, 0, sizeof(speakerBuffer));
    
    // Keep amp MUTED initially - will enable when we receive first real audio packet
    digitalWrite(PIN_AMP_EN, LOW);
    
    // Start listening for audio packets from laptop
    audioInUdp.begin(UDP_AUDIO_IN_PORT);
    
    bool firstPacketReceived = false;
    
    while (audioStreamingActive) {
        int packetSize = audioInUdp.parsePacket();
        
        if (packetSize > 0) {
            // Read UDP packet into speaker buffer
            int bytesRead = audioInUdp.read((uint8_t*)speakerBuffer, min(packetSize, (int)(I2S_BUFFER_SIZE * sizeof(int16_t))));
            
            if (bytesRead > 0) {
                // Enable amp on first real audio packet
                if (!firstPacketReceived) {
                    digitalWrite(PIN_AMP_EN, HIGH);
                    firstPacketReceived = true;
                    Serial.println("✓ First audio received, amp enabled");
                }
                
                // Write to I2S speaker
                i2s_write(I2S_SPEAKER_PORT, speakerBuffer, bytesRead, &bytes_written, portMAX_DELAY);
            }
        }
        
        // Small yield
        vTaskDelay(1);
    }
    
    // Mute amplifier when done (unless in chat mode)
    if (!chatMode) {
        digitalWrite(PIN_AMP_EN, LOW);
    }
    
    Serial.println("Speaker playback task ended");
    vTaskDelete(NULL);
}
