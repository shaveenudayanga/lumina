# Lumina Camera Firmware

ESP32-CAM firmware that streams video to the Python app.

## Hardware

- AI-Thinker ESP32-CAM module
- OV2640 camera (built-in)

## First time upload

The ESP32-CAM needs a USB-serial adapter for the first upload.

**1. Wire it up**

| ESP32-CAM | USB Adapter |
|-----------|-------------|
| GND | GND |
| 5V | 5V |
| U0T | RX |
| U0R | TX |
| IO0 | GND (only during upload!) |

**2. Upload**

```bash
cd firmware-cam
pio run -t upload --upload-port /dev/tty.usbserial-xxxx
```

**3. Disconnect IO0 from GND and press RESET**

**4. Configure WiFi**

Connect to "Lumina-Cam-Setup" hotspot, go to 192.168.4.1, enter your WiFi credentials.

## Test it

Open a browser to the camera's IP:
- Web UI: `http://<IP>/`
- Stream: `http://<IP>/stream`

## OTA updates

After WiFi is working:

```bash
pio run -t upload --upload-port lumina-cam.local
```

## Use with Lumina

Set the IP in `lumina_unified.py`:

```python
CAM_IP = "192.168.x.x"  # your camera's IP
```
