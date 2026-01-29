# Lumina

An interactive robotic desk lamp that tracks your hand, shows expressions, and has real conversations.

## What it does

Lumina is a desk lamp with a personality. When idle, it displays a sleepy face with "SAY HI LUMINA" scrolling across the screen. Wave at it with an open palm and it wakes up and follows your hand. Say "Hey Lumina" and you can have a natural back-and-forth conversation - it uses Google's Gemini Live API for real-time voice chat.

The lamp shows different facial expressions on its OLED display, has a second display showing the current time, and an LED ring that changes color based on mood.

## Hardware

- **ESP32 DevKit V1** - Controls motors, displays, LEDs, audio
- **ESP32-CAM** - Streams video (optional - can use laptop webcam)
- **2x SSD1306 OLED** - One for expressions (0x3D), one for clock (0x3C)
- **2x SG90 Servos** - Pan and tilt
- **WS2812 LED Ring** - 12 LEDs for mood lighting
- **MAX98357A + Speaker** - Audio output via I2S
- **Laptop/Mac** - Runs Python for vision and AI

### Wiring

| Part | Pin |
|------|-----|
| Pan Servo | GPIO 18 |
| Tilt Servo | GPIO 19 |
| OLED SDA | GPIO 21 |
| OLED SCL | GPIO 22 |
| LED Ring | GPIO 5 |
| I2S LRC | GPIO 25 |
| I2S BCLK | GPIO 26 |
| I2S DIN | GPIO 27 |

## Quick Start

**1. Install dependencies**

```bash
git clone https://github.com/yourusername/lumina.git
cd lumina
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

**2. Flash ESP32 (first time via USB)**

```bash
cd firmware
pio run -t upload
```

Connect to "Lumina-Setup" WiFi, go to 192.168.4.1, enter your network credentials.

**3. Set up Gemini API key**

```bash
cp .env.example .env
# Edit .env: GEMINI_API_KEY="your-key"
```

**4. Update IPs in config**

Edit `lumina_unified.py` and set your device IPs:
```python
BODY_IP = "192.168.x.x"   # Your ESP32's IP
CAM_IP = "192.168.x.x"    # ESP32-CAM IP (or None for laptop webcam)
```

**5. Run**

```bash
python lumina_unified.py
```

## OTA Updates

Once WiFi is configured, upload wirelessly:

```bash
cd firmware
pio run -t upload --upload-port <ESP32_IP>
```

## Features

- **Hand tracking** - Open palm gesture to wake, tracks your hand movement
- **Voice chat** - Say "Hey Lumina" for natural conversation via Gemini Live API
- **Expressions** - Happy, sleep, listening, talking animations on OLED
- **Clock display** - Second OLED shows current time (NTP synced, UTC+5:30)
- **LED control** - Ask Lumina to change brightness or color
- **WiFiManager** - No hardcoded credentials, configure via captive portal
- **OTA updates** - Flash firmware over WiFi

## Controls

- `q` - Quit
- `v` - Force voice mode

## Architecture

```
┌─────────────────┐     ┌──────────────┐     ┌─────────────┐
│  Python (Mac)   │────►│  ESP32 Body  │     │  ESP32-CAM  │
│  - MediaPipe    │ UDP │  - Servos    │     │  - Stream   │
│  - Gemini Live  │     │  - OLEDs     │     └──────┬──────┘
│  - Audio I/O    │     │  - LEDs      │            │
└─────────────────┘     └──────────────┘      HTTP  │
        ▲                                           │
        └───────────────────────────────────────────┘
```

## Project Structure

```
lumina/
├── lumina_unified.py     # Main Python app
├── requirements.txt
├── .env.example
├── firmware/             # ESP32 body (PlatformIO)
│   └── src/main.cpp
└── firmware-cam/         # ESP32-CAM (PlatformIO)
    └── src/main.cpp
```

## License

MIT - See [LICENSE](LICENSE)
