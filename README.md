# Lumina

An interactive robotic desk lamp that tracks your hand, shows expressions, and has real conversations.

## What it does

Lumina is a desk lamp with a personality. When idle, it displays a sleepy face with "SAY HI LUMINA" scrolling across the screen. Wave at it with an open palm and it wakes up and follows your hand. Say "Hey Lumina" and you can have a natural back-and-forth conversation - it uses Google's Gemini 2.5 Flash Native Audio API for real-time voice chat with Aoede voice.

The lamp shows different facial expressions on its OLED display, has a second display showing the current time, and a WS2812 LED strip (8 LEDs) that changes color based on mood or voice commands.

## Hardware

- **ESP32 DevKit V1** - Controls motors, displays, LEDs
- **ESP32-CAM** - Streams video (optional - can use laptop webcam)
- **2x SSD1306 OLED** - One for expressions (0x3D), one for clock (0x3C)
- **2x Servos** - Pan (0-180°) and tilt (30-150°, inverted)
- **WS2812 LED Strip** - 8 LEDs for mood lighting
- **Laptop/Mac** - Runs Python for vision, audio I/O, and AI

### Wiring

| Part | Pin |
|------|-----|
| Pan Servo | GPIO 18 |
| Tilt Servo | GPIO 19 |
| OLED SDA | GPIO 21 |
| OLED SCL | GPIO 22 |
| LED Ring | GPIO 5 |
| I2S Strip | GPIO 5
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
pio run -t uploadfirmware (first time via USB)**

```bash
cd firmware
pio run -t upload
```

Connect to "Lumina-Setup" WiFi, go to 192.168.4.1, enter your network credentials. After initial setup, use WiFi OTA updates (see below)
cp .env.example .env
# Edit .env: GEMINI_API_KEY="your-key"
```
Get your API key from [Google AI Studio](https://aistudio.google.com/apikey).

```bash
cp .env.example .env
# Edit .env: GEMINI_API_KEY="your-key-here"
```

**4. Update configuration**

Edit `lumina_unified.py` to set your ESP32's IP address:
```python
class Config:
    BODY_IP = "192.168.228.68"  # Your ESP32's IP (find via router)
    BODY_PORT = 5005
    CAM_URL = None  # Use local webcam (or set ESP32-CAM stream URL)
    LIVE_MODEL = "gemini-2.5-flash-native-audio-preview-12-2025"
    VOICE = "Aoede"
```bash
python lumina_unified.py
```WiFi OTA Updates

After initial USB flash and WiFi setup, update firmware wirelessly:

```bash
cd firmware
pio run -t upload --upload-port 192.168.228.68
```

Replace with your ESP32's IP address. OTA upload takes ~40 seconds.firmware
pio run -t upload --upload-port <ESP32_IP>
```center-following proportional control
- **Voice chat** - Say "Hey Lumina" for natural conversation via Gemini 2.5 Flash Native Audio
- **Expressions** - Happy, sad, love, sleep, listening, talking animations on OLED
- **Clock display** - Second OLED shows current time (NTP synced, UTC+5:30)
- **LED control** - White default (80%), ask Lumina to change brightness or color
- **UDP commands** - Send commands directly: `SERVO_PAN:90`, `COLOR:blue`, `B50`, `F_HAPPY`
- **WiFiManager** - No hardcoded credentials, configure via captive portal
- **WiFi OTA** - Flash firmware over network without USB cable talking animations on OLED
- *Keyboard Controls

- `q` - Quit application
- `v` - Force voice mode
- `ESC` - Exit fullscreen/quith firmware over WiFi

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
        └────────────────────────────────── (1769 lines)
├── requirements.txt      # Python dependencies
├── .env.example          # Environment template
├── test_esp32.py         # Hardware diagnostic script
├── firmware/             # ESP32 body (PlatformIO)
│   ├── platformio.ini
│   └── src/main.cpp      # Firmware (1732 lines)
└── firmware-cam/         # ESP32-CAM (PlatformIO)
    ├── platformio.ini
    └── src/main.cpp
```

## UDP Command Reference

Send commands to ESP32 at `192.168.228.68:5005`:

### Servo Commands
- `SERVO_ENABLE` - Attach servos
- `SERVO_DISABLE` - Detach servos
- `SERVO_PAN:angle` - Pan 0-180°
- `SERVO_TILT:angle` - Tilt 30-150° (inverted)

### LED Commands
- `B{0-100}` - Brightness: `B80`
- `C{r},{g},{b}` - RGB: `C255,0,0`
- `COLOR:{name}` - Named colors: `COLOR:blue`, `COLOR:white`, `COLOR:off`

### Face Commands
- `F_HAPPY`, `F_SAD`, `F_LOVE`, `F_SLEEP`, `F_LISTENING`, `F_TALKING`

### Test ESP32
```bash
python test_esp32.py
```

## Troubleshooting

**ESP32 not responding to commands?**
- Verify IP with router/serial monitor
- Test UDP: `nc -zuv 192.168.228.68 5005`
- Run diagnostics: `python test_esp32.py`

**LEDs not changing color?**
- Ensure firmware uploaded after Dec 2025 (includes FastLED.show() fix)
- Test: `echo -n 'C255,0,0' | nc -u -w1 192.168.228.68 5005`

**Voice chat not working?**
- Check Gemini API key in `.env`
- Verify model: `gemini-2.5-flash-native-audio-preview-12-2025`
- Test mic/speaker permissions in macOS System Settings

**Tilt servo backwards?**
- Firmware includes inverted tilt (180 - angle)
- Re-upload if needed: `cd firmware && pio run -t upload --upload-port 192.168.228.68─ lumina_unified.py     # Main Python app
├── requirements.txt
├── .env.example
├── firmware/             # ESP32 body (PlatformIO)
│   └── src/main.cpp
└── firmware-cam/         # ESP32-CAM (PlatformIO)
    └── src/main.cpp
```

## License

MIT - See [LICENSE](LICENSE)
