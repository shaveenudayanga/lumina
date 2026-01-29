#!/usr/bin/env python3
"""
Quick ESP32 test script - sends commands to verify hardware is responding
"""
import socket
import time

ESP32_IP = "192.168.228.68"
ESP32_PORT = 5005

def send_udp(cmd):
    """Send UDP command to ESP32"""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.sendto(cmd.encode(), (ESP32_IP, ESP32_PORT))
    sock.close()
    print(f"✓ Sent: {cmd}")
    time.sleep(0.5)

print(f"Testing ESP32 at {ESP32_IP}:{ESP32_PORT}")
print("=" * 50)

# Test 1: Enable servos
print("\n1. Enabling servos...")
send_udp("SERVO_ENABLE")

# Test 2: Move to center
print("\n2. Moving to center (90°)...")
send_udp("SERVO_PAN:90")
send_udp("SERVO_TILT:90")

# Test 3: LED brightness test
print("\n3. Testing LED brightness...")
for level in [0, 50, 100, 50, 0]:
    send_udp(f"B{level}")
    print(f"   Brightness: {level}%")
    time.sleep(0.5)

# Test 4: Color test
print("\n4. Testing LED colors...")
for color in ["red", "green", "blue", "white", "off"]:
    send_udp(f"COLOR:{color}")
    print(f"   Color: {color}")
    time.sleep(0.5)

# Test 5: Face test
print("\n5. Testing OLED faces...")
for face in ["HAPPY", "SAD", "LOVE", "SLEEP"]:
    send_udp(f"F_{face}")
    print(f"   Face: {face}")
    time.sleep(1)

# Test 6: Servo movement
print("\n6. Testing servo movement...")
positions = [
    (90, 90, "center"),
    (120, 90, "pan right"),
    (60, 90, "pan left"),
    (90, 120, "tilt down"),
    (90, 60, "tilt up"),
    (90, 90, "center again"),
]
for pan, tilt, desc in positions:
    send_udp(f"SERVO_PAN:{pan}")
    send_udp(f"SERVO_TILT:{tilt}")
    print(f"   {desc}: pan={pan}°, tilt={tilt}°")
    time.sleep(1)

print("\n" + "=" * 50)
print("Test complete! Watch your ESP32 for responses.")
print("If nothing happened:")
print("  1. Check ESP32 is powered on")
print("  2. Check ESP32 is on WiFi (192.168.109.68)")
print("  3. Re-upload firmware: cd firmware && pio run -t upload")
