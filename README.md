
# Lumina Pro — Interactive Robotic Lamp

## Overview

Lumina Pro is an interactive robotic lamp that explores non-verbal communication between humans and machines. Unlike traditional "always-on" tracking systems, Lumina uses a strict **Gestural Clutch Mechanism**. It ignores casual movements (scratching, resting, holding objects) and only engages when the user explicitly "opens" the channel of communication using a specific hand pose.

This project demonstrates **Computer Vision**, **Embedded Control**, **Voice AI**, and **Natural User Interface (NUI)** design.

## Project Structure

```
lumina/
├── lumina_head_tracker.py   # Standalone vision tracking (no voice)
├── lumina_master.py         # Full system: Vision + Voice AI + Robot Control
├── requirements.txt         # Python dependencies
├── firmware/                # ESP32 PlatformIO project
│   ├── platformio.ini
│   ├── src/main.cpp
│   └── README.md
└── tests/                   # Unit tests
    └── test_detect_serial.py
```

## Key Features

### The "Gestural Clutch" (Input Sanitization)
The system does not track just any hand. It uses a multi-stage validation pipeline to reject false positives:
 - Aspect Ratio Gating: Calculates the bounding box of the hand. Only hands with a Height/Width > 1.3 (Tall Rectangle) are accepted. "Claw" or "Fist" shapes (Square aspect ratio) are physically rejected.
 - "Nuclear" Straightness Check: Uses a "weakest link" algorithm. If even one finger is curled (e.g., a relaxed hand), the entire lock is rejected.
 - Geometric Validation: Rejects back-of-hand (nails visible) and inverted hand poses to prevent erratic behavior.

### Smooth "Telekinetic" Tracking
Once locked, the lamp follows the user's hand in real-time using:
 - Incremental Tracking: Uses relative error correction rather than absolute mapping, preventing "jumpy" movement.
 - Deadzone Logic: A 40px center radius where movement is suppressed to prevent motor jitter (noise filtering).
 - Soft-Start Physics: Gain variables control the acceleration/deceleration for organic, lifelike motion.

🛠 Hardware Architecture

| Component | Description |
|-----------|-------------|
| **Brain** | Laptop/PC running Python 3.11 (offloads vision for high-FPS MediaPipe) |
| **Body**  | ESP32 DevKit V1 (receives serial commands, drives actuators) |
| **Eye**   | USB Webcam (external or integrated) |
| **Face**  | SSD1306 OLED Display (128x64) with animated expressions |
| **Neck**  | 2x SG90 Micro Servos (Pan & Tilt) |
| **Glow**  | WS2812 LED Ring (12 LEDs, breathing animation) |
| **Voice** | I2S Microphone + Speaker (optional, for Voice AI) |

### Wiring Pinout (ESP32 DevKit V1)

| Component    | ESP32 Pin |
|--------------|-----------|
| Pan Servo    | GPIO 18   |
| Tilt Servo   | GPIO 19   |
| OLED SDA     | GPIO 21   |
| OLED SCL     | GPIO 22   |
| WS2812 LED   | GPIO 5    |
| I2S LRC      | GPIO 25   |
| I2S BCLK     | GPIO 26   |
| I2S DIN      | GPIO 27   |
| Mic ADC      | GPIO 34   |

## Software Stack

### Prerequisites

- **Python**: 3.10 or 3.11 (recommended for MediaPipe stability)
- **PlatformIO**: For building and flashing ESP32 firmware

### Installation

1. **Clone the Repository**
   ```bash
   git clone https://github.com/yourusername/lumina.git
   cd lumina
   ```

2. **Set up Python Environment**
   ```bash
   python -m venv .venv
   source .venv/bin/activate   # macOS / Linux
   # .venv\Scripts\activate    # Windows

   pip install -r requirements.txt
   ```

3. **Flash the ESP32 Firmware**
   ```bash
   cd firmware
   pio run -t upload
   ```

   > See [firmware/README.md](firmware/README.md) for more details.

### Optional: Voice AI Setup

To enable voice interaction with Gemini AI you can either set an environment variable or create a local `.env` file in the project root.

Option A — set it for the current shell session:

```bash
export GEMINI_API_KEY="your-api-key-here"
```

Option B — create a `.env` file (recommended for local dev):

1. Copy the example file:

```bash
cp .env.example .env
```

2. Edit `.env` and set your key:

```bash
GEMINI_API_KEY="your-api-key-here"
```

The project already calls `load_dotenv()` so `.env` will be loaded automatically. Your `.env` file is ignored by Git (see `.gitignore`) so it is safe to keep your secret locally.

Voice AI requires these optional dependencies (already in requirements.txt):
- `google-generativeai` - Gemini API
- `SpeechRecognition` - Voice input
- `gTTS` + `pygame` - Voice output

## Usage Guide

### Quick Start

1. **Connect Hardware**: Plug the ESP32 into USB
2. **Start Lumina**:
   ```bash
   # Basic tracking only
   python lumina_head_tracker.py --auto-detect

   # Full system with Voice AI
   python lumina_master.py
   ```

### CLI Options (lumina_head_tracker.py)

| Option | Description |
|--------|-------------|
| `--auto-detect` | Auto-detect serial port (prefers USB-serial adapters) |
| `--pick` | Interactively select from multiple detected ports |
| `-p PORT` | Specify serial port manually |
| `-b BAUD` | Specify baud rate (default: 115200) |
| `--no-arduino` | Simulation mode (no hardware required) |

### Controls (lumina_master.py)

| Key | Action |
|-----|--------|
| `v` | Activate voice chat |
| `q` | Quit |

### Interaction States

| State | Visual Cue | Description |
|-------|------------|-------------|
| **IDLE** | Red box | Lamp is sleeping, ignores all movement |
| **TRACKING** | Green box | Hand detected, lamp follows your movement |
| **LISTENING** | Orange bar | Waiting for voice input |
| **RESPONDING** | Blue bar | AI is speaking |

### Hand Gesture Requirements

- **Palm facing camera** (not back of hand)
- **Fingers spread wide** (aspect ratio > 1.3)
- **All fingers straight** (no curled fingers)
- **Hand upright** (wrist below fingers)

## Serial Protocol

Commands sent from Python to ESP32 over serial (115200 baud):

| Command | Description |
|---------|-------------|
| `P<pan>T<tilt>` | Move servos (e.g., `P90T45`) |
| `F_HAPPY` | Happy face expression |
| `F_SLEEP` | Sleep mode expression |
| `F_TALK_START` | Start talking animation |
| `F_TALK_STOP` | Stop talking animation |
| `L<brightness>` | Set LED brightness (0-255) |

## Algorithms

- **Google MediaPipe Hands**: Skeletal landmark extraction (21 points)
- **Bounding Box Aspect Ratio**: `Height / Width > 1.3` distinguishes "Intent" from "Noise"
- **Finger Straightness**: "Weakest link" algorithm rejects curled fingers
- **Proportional Control Loop**: Error-based servo correction for smooth following

## Running Tests

```bash
pytest tests/ -v
```

## Future Improvements

- [ ] Gesture Recognition (pinch to dim, wave to greet)
- [ ] Face Tracking fallback when no hand detected
- [ ] Wireless mode (WebSocket/UDP instead of Serial)
- [ ] Custom wake words
- [ ] Emotion detection from voice tone

## License

See [LICENSE](LICENSE) for details.
