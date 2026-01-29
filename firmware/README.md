# Lumina Body Firmware

ESP32 firmware that controls the lamp's motors, display, and LEDs.

## What's in here

This is the code running on the ESP32 DevKit that makes the lamp move and show expressions. It talks to the Python app over WiFi (UDP).

## Wiring

| Component | ESP32 Pin |
|-----------|-----------|
| Pan Servo | GPIO 18 |
| Tilt Servo | GPIO 19 |
| OLED SDA | GPIO 21 |
| OLED SCL | GPIO 22 |
| LED Ring | GPIO 5 |
| Touch | GPIO 4 |
| I2S LRC | GPIO 25 |
| I2S BCLK | GPIO 26 |
| I2S DIN | GPIO 27 |

## First time setup

**1. Build and upload via USB**

```bash
pio run -t upload
```

**2. Configure WiFi**

After upload, the ESP32 creates a hotspot called "Lumina-Setup". Connect to it with your phone or laptop, go to 192.168.4.1, and enter your WiFi credentials.

**3. Upload over the air (after WiFi works)**

```bash
pio run -t upload --upload-port <ESP32_IP>
# or
pio run -t upload --upload-port lumina.local
```

## Commands

The Python app sends these over UDP port 5005:

| Command | What it does |
|---------|--------------|
| `P90T45` | Move pan to 90°, tilt to 45° |
| `F_HAPPY` | Show happy face |
| `F_SLEEP` | Show sleep face |
| `F_TALK_START` | Start talking animation |
| `F_TALK_STOP` | Stop talking |
| `B50` | Set LED brightness to 50% |
| `COLOR:blue` | Set LED color |

## Troubleshooting

**WiFi won't connect?**
- Erase flash and reconfigure: `pio run -t erase`

**OTA upload fails?**
- Make sure your laptop is on the same network
- Try using the IP address directly instead of `lumina.local`

**LEDs not working?**
- Check that you're using a level shifter (HW-222) between 3.3V GPIO and 5V LED strip
