
# Lumina — Interactive Robotic Lamp

## Overview

Lumina is an interactive robotic lamp that explores non-verbal communication between humans and machines. Unlike traditional "always-on" tracking systems, Lumina uses a strict Gestural Clutch Mechanism. It ignores casual movements (scratching, resting, holding objects) and only engages when the user explicitly "opens" the channel of communication using a specific hand pose.

This project demonstrates Computer Vision, Embedded Control, and Natural User Interface (NUI) design.

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
 - The Brain (Vision Processing): Laptop/PC running Python 3.11.
  - Why? Offloading vision allows for high-FPS, complex MediaPipe models that would lag on an MCU.
 - The Body (Actuation): ESP32 Microcontroller.
  - Role: Receives simplified coordinates (P90 T45) via Serial and drives the motors.
 - The Eye: USB Webcam (External or Integrated).
 - Actuators:
  - 2x Micro Servos (Pan & Tilt).
  - NeoPixel/LED Ring (Status Feedback).

### Wiring Pinout (ESP32)

| Component   | ESP32 Pin |
|-------------|-----------|
| Pan Servo   | GPIO 18   |
| Tilt Servo  | GPIO 19   |
| Status LED  | GPIO 2    |

## Software Stack

### Prerequisites
 - Python: 3.10 or 3.11 (Recommended for MediaPipe stability).
 - Arduino IDE: For flashing the ESP32 firmware.

### Installation
 - Clone the Repository
 ```bash
 git clone https://github.com/yourusername/lumina-hci.git
 cd lumina-hci
 ```

### Virtual Environment (recommended)
Create and activate a venv, then install dependencies. **Do not commit the `.venv` directory into source control.** Instead, track your dependencies using `requirements.txt` (or a lockfile) so environments are reproducible across machines:

```bash
python -m venv .venv
source .venv/bin/activate   # macOS / Linux
.venv\Scripts\activate     # Windows (PowerShell/CMD)

# Install pinned dependencies
pip install -r requirements.txt

# If you add/remove dependencies, update the tracked requirements file
pip freeze > requirements.txt
```

**Why:** Committing `.venv` bloats the repository and introduces platform-specific binaries; tracking `requirements.txt` keeps the repo small and reproducible.

 - Install Python Dependencies (alternative)
 ```bash
 pip install opencv-python mediapipe pyserial numpy
 ```

### Flash the Firmware

 - Open `lumina_firmware.ino` in Arduino IDE.
 - Select Board: DOIT ESP32 DEVKIT V1 (or your specific board).
 - Upload to the microcontroller.

## Usage Guide

### Connect Hardware
 - Plug the ESP32 into the USB port.

### Start the Brain
 ```bash
 python lumina_head_tracker.py
 ```

#### CLI Examples
 - Run with auto-detected serial port (prefers USB-serial adapters):
 ```bash
 python lumina_head_tracker.py --auto-detect
 ```
 - Override serial port and baud explicitly:
 ```bash
 python lumina_head_tracker.py -p /dev/tty.usbserial -b 115200
 ```
 - Force simulation mode (no Arduino attached):
 ```bash
 python lumina_head_tracker.py --no-arduino
 ```

 - The Interaction:
  - State 1: IDLE (Red Box)
    - The lamp is asleep. You can move freely; it will not follow.
  - State 2: ENGAGE (Green Box)
    - Raise your hand.
    - Open fingers WIDE (Stretch them vertically).
    - Visual Cue: The on-screen box will turn GREEN and the lamp will snap to look at you.
  - State 3: CONTROL
    - Move your hand slowly. The lamp head will mimic your movement.
  - State 4: DISENGAGE
    - Simply close your fist or drop your hand to stop tracking instantly.

## Algorithms Used
 - Google MediaPipe Hands: For skeletal landmark extraction (21 points).
 - Bounding Box Aspect Ratio Analysis: Ratio = BBox_Height / BBox_Width. Used to distinguish "Intent" (Open Hand) from "Noise" (Resting Hand).
 - Proportional Control Loop: Error-based servo correction for smooth following.

### Core Logic Snippet
```python
if aspect_ratio > 1.3 and finger_straightness > 0.85:
    status = "LOCKED"
    move_servos()
else:
    status = "IGNORED"
```

## Future Improvements
 - Gesture Recognition: Adding specific gestures (e.g., "Pinch" to dim light).
 - Face Priority: Fallback to Face Tracking when no hand is detected.
 - Wireless: Porting the Serial communication to WebSocket/UDP for a fully wireless lamp.

## Notes & Assistant
- I (your coding assistant) updated this README with setup and usage instructions. If you'd like, I can also:
  - Add a `requirements.txt` or `pyproject.toml`.
  - Add example Arduino firmware or wiring diagrams.
  - Create a small test harness script that simulates serial commands for development without hardware.

---
If you want any of the above extras added, tell me which and I'll implement them.
