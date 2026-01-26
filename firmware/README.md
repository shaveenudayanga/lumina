# Lumina Pro Firmware - "The Split Nervous System"

ESP32 DevKit V1 firmware for the Lumina interactive robotic lamp.

## Architecture Overview

```
┌───────────────────────────────────────────────────────────────┐
│                    "The Split Nervous System"                 │
├───────────────────────────────────────────────────────────────┤
│                                                               │
│  Device A (Body)          Device B (Eyes)    Device C (Brain) │
│  ESP32 DevKit V1          ESP32-CAM           Laptop (Python) │
│  ┌──────────────┐         ┌──────────┐        ┌────────────┐  │
│  │ Motors       │         │ Camera   │        │ Vision AI  │  │
│  │ LED Lamp     │◄──UDP───│ Streamer │──HTTP─►│ Voice AI   │  │
│  │ OLED Display │         └──────────┘        │ Gemini API │  │
│  │ Touch Sensor │◄────────UDP Commands───────►│            │  │
│  │ Audio I/O    │                             └────────────┘  │
│  └──────────────┘                                             │
└───────────────────────────────────────────────────────────────┘
```

## Hardware Requirements (Device A - Body)

- **ESP32 DevKit V1**
- **SSD1306 OLED Display** (128x64, I2C) - Shows faces/status
- **2x SG90 Servo Motors** (Pan/Tilt)
- **WS2812 LED Stick** - Main lamp via HW-222 signal booster
- **TTP223 Touch Sensor** - Toggle chat mode
- **MAX4466 Microphone** - Audio input (analog)
- **MAX98357A I2S Amplifier** - Audio output

## Pinout

| Component        | ESP32 Pin | Notes                    |
|------------------|-----------|--------------------------|
| **Pan Servo**    | GPIO 18   |                          |
| **Tilt Servo**   | GPIO 19   |                          |
| **OLED SDA**     | GPIO 21   | I2C Data                 |
| **OLED SCL**     | GPIO 22   | I2C Clock                |
| **WS2812 LED**   | GPIO 5    | Via HW-222 level shifter |
| **Touch Sensor** | GPIO 4    | TTP223                   |
| **I2S LRC**      | GPIO 25   | MAX98357A                |
| **I2S BCLK**     | GPIO 26   | MAX98357A                |
| **I2S DIN**      | GPIO 27   | MAX98357A                |
| **Mic ADC**      | GPIO 34   | MAX4466 analog out       |

## LED Wiring (3-Wire Config with HW-222)

```
            ┌─────────────────────────────────────┐
            │         HW-222 Signal Booster       │
            │  ┌───────────────────────────────┐  │
5V ─────────┼──┤ VCC                       VCC ├──┼──── WS2812 5V
            │  │                               │  │
GPIO 5 ─────┼──┤ IN (3.3V)         OUT (5V)    ├──┼──── WS2812 DIN
            │  │                               │  │
GND ────────┼──┤ GND                       GND ├──┼──── WS2812 GND
            │  └───────────────────────────────┘  │
            └─────────────────────────────────────┘
```

## Features

### WiFiManager (No Hardcoded Credentials)
- On first boot, creates "Lumina-Setup" access point
- Connect to it and open 192.168.4.1 to configure WiFi
- Credentials are saved to flash

### ArduinoOTA (Wireless Updates)
- After WiFi connection, upload wirelessly:
  ```bash
  pio run -t upload --upload-port lumina.local
  ```

### Touch Sensor Toggle
- **Touch** → Toggle chat mode ON/OFF
- **Chat ON** → LEDs Green, sends `STATUS:LISTENING` to laptop
- **Chat OFF** → LEDs Red briefly, sends `STATUS:MUTE` to laptop

### UDP Communication (Port 5005)
- Brain discovers body via broadcast `DISCOVER`
- Body responds with `LUMINA_BODY`
- Commands: `P90T45`, `F_HAPPY`, `COLOR:blue`, `B50`, etc.

## Setup

### 1. Install PlatformIO

Install the [PlatformIO extension](https://platformio.org/install/ide?install=vscode) for VS Code.

### 2. Build the Project

```bash
cd firmware
pio run
```

### 3. Upload to ESP32 (USB - First Time)

```bash
pio run -t upload
```

### 4. Configure WiFi

1. Connect to "Lumina-Setup" WiFi network
2. Open http://192.168.4.1 in browser
3. Select your WiFi network and enter password
4. ESP32 will restart and connect

### 5. Upload via OTA (After WiFi Setup)

```bash
pio run -t upload --upload-port lumina.local
```

### 6. Monitor Serial Output

```bash
pio device monitor
```

## Serial/UDP Commands

| Command         | Description                      |
|-----------------|----------------------------------|
| `P90T45`        | Move pan to 90°, tilt to 45°     |
| `F_HAPPY`       | Display happy face               |
| `F_SLEEP`       | Display sleep face               |
| `F_LISTENING`   | Display listening icon           |
| `F_TALK_START`  | Start talking animation          |
| `F_TALK_STOP`   | Stop talking animation           |
| `B50`           | Set brightness to 50%            |
| `L128`          | Set brightness (0-255)           |
| `COLOR:blue`    | Set LED color by name            |
| `C255,0,0`      | Set LED color RGB                |
| `CHAT_START`    | Enable chat mode remotely        |
| `CHAT_STOP`     | Disable chat mode remotely       |
| `PING`          | Response: `PONG`                 |
| `DISCOVER`      | Response: `LUMINA_BODY`          |

## Status Messages (Body → Brain)

| Status               | Meaning                     |
|----------------------|-----------------------------|
| `STATUS:LISTENING`   | Touch activated, ready      |
| `STATUS:MUTE`        | Touch deactivated           |
| `HEARTBEAT:LISTENING`| Periodic status (chat on)   |
| `HEARTBEAT:MUTE`     | Periodic status (chat off)  |
| `LUMINA_BODY`        | Discovery response          |
| `PONG`               | Ping response               |

## Troubleshooting

### WiFi Not Connecting
- Hold reset button for 5+ seconds to clear saved WiFi
- Or erase flash: `pio run -t erase`

### OTA Upload Fails
- Ensure laptop is on same network as ESP32
- Try using IP address instead: `--upload-port 192.168.x.x`

### LEDs Not Working
- Check HW-222 connections (5V, GND, signal direction)
- Verify GPIO 5 is correct

### Touch Not Responding
- TTP223 needs stable 3.3V power
- Check GPIO 4 connection
