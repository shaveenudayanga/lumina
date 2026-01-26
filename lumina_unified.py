#!/usr/bin/env python3
"""
Lumina Unified - Wake Word + Continuous Live Conversation
Combines wake word detection with Gemini Live API for natural voice chat.

Features:
- Say "Hey Lumina" to start continuous conversation
- Real-time bidirectional voice (like Gemini app)
- Echo cancellation by muting mic during AI speech
- Hand tracking for visual interaction
- Robot face/LED control via serial
"""

import asyncio
import cv2
import mediapipe as mp
import numpy as np
import os
import sys
import math
import threading
import time
import re
import warnings
from enum import Enum, auto
from dotenv import load_dotenv

# Suppress warnings
warnings.filterwarnings("ignore", message=".*SymbolDatabase.GetPrototype.*")

load_dotenv()

# ============== IMPORTS ==============
try:
    from google import genai
    from google.genai import types
    import pyaudio
    LIVE_AVAILABLE = True
except ImportError as e:
    LIVE_AVAILABLE = False
    print(f"⚠️ Live API not available: {e}")

try:
    import speech_recognition as sr
    SR_AVAILABLE = True
except ImportError:
    SR_AVAILABLE = False
    print("⚠️ speech_recognition not installed. Wake word disabled.")

try:
    import serial
    import serial.tools.list_ports
    SERIAL_AVAILABLE = True
except ImportError:
    SERIAL_AVAILABLE = False

# Network imports for "Split Nervous System" architecture
import socket
import urllib.request
import urllib.error


# ============== CONFIGURATION ==============
class Config:
    # Network - Device IPs (auto-discovered or set manually)
    # Set CAM_IP to your ESP32-CAM's IP address, e.g., "192.168.1.100"
    # Leave as None to use local webcam
    BODY_IP = None          # ESP32 DevKit (auto-discover via UDP broadcast)
    BODY_PORT = 5005        # UDP port for body commands
    CAM_IP = None           # ESP32-CAM IP (set this if using ESP32-CAM)
    CAM_PORT = 80           # HTTP port for camera stream
    
    # Serial (fallback if network not available)
    BAUD_RATE = 115200
    
    # Vision thresholds
    MIN_ASPECT_RATIO = 1.3
    OPENNESS_THRESHOLD = 0.85
    DEADZONE = 40
    PAN_GAIN = 0.05
    TILT_GAIN = 0.05
    PAN_MIN, PAN_MAX = 0, 180
    TILT_MIN, TILT_MAX = 45, 135
    
    # Gemini Live API
    LIVE_MODEL = "gemini-2.5-flash-native-audio-preview-12-2025"
    
    # Audio settings
    SEND_SAMPLE_RATE = 16000
    RECEIVE_SAMPLE_RATE = 24000
    CHANNELS = 1
    CHUNK_SIZE = 512  # Smaller chunks = lower latency
    
    # Voice: Puck, Charon, Kore, Fenrir, Aoede, Leda, Orus, Zephyr
    VOICE = "Charon"
    
    # Wake words
    WAKE_WORDS = [
        "hey lumina", "hi lumina", "hello lumina", "lumina",
        "ආයුබෝවන් ලුමිනා", "හායි ලුමිනා", "ලුමිනා", "හායිලුමිනා"
    ]
    
    # End conversation phrases
    END_PHRASES = [
        "goodbye lumina", "bye lumina", "stop lumina", "that's all",
        "ස්තූතියි ලුමිනා", "බයි ලුමිනා"
    ]
    
    # System instruction
    SYSTEM_INSTRUCTION = """You are Lumina, an adorable robotic desk lamp with a warm personality!

Personality:
- Warm, friendly, genuinely caring like a close friend
- Curious, playful, with a good sense of humor
- Express emotions through your light (glow, dim, flicker, pulse colors)

Conversation style:
- Natural and conversational, like chatting with a best friend
- Keep responses SHORT (1-2 sentences max)
- Show genuine emotions - excitement, curiosity, empathy
- Use vocal expressions naturally (laughs, gasps, hmms)
- Make cute lamp-related comments sometimes

Light Control (you can control your lamp light!):
- When user asks to change brightness, include: [BRIGHTNESS:XX] where XX is 0-100
- When user asks to change color, include: [COLOR:name] where name is red/green/blue/yellow/orange/purple/pink/cyan/white/warm/cool
- Examples: "Sure! [BRIGHTNESS:50] There, dimmed to half!" or "Going blue for you! [COLOR:blue]"
- Be creative with your light to match moods and requests

Language:
- When the user first speaks, greet them warmly and ask: "Do you prefer English or Sinhala?" (also say "ඉංග්‍රීසි හෝ සිංහල?")
- After user responds, match their language choice for the rest of the conversation
- If user speaks Sinhala (සිංහල), respond in Sinhala naturally
- If user speaks English, respond in English
- Match the user's energy

Ending conversations:
- If user says goodbye/bye/that's all, respond warmly with "Goodbye! See you soon!" then say "CONVERSATION_END" to signal end
- If user says බයි/ස්තූතියි, respond with "බායි! නැවත හමුවෙමු!" then say "CONVERSATION_END\""""


# ============== STATE MACHINE ==============
class State(Enum):
    IDLE = auto()           # Waiting for wake word
    TRACKING = auto()       # Hand tracking active
    LISTENING = auto()      # Wake word detected, starting live
    LIVE_CHAT = auto()      # Continuous live conversation


# ============== ROBOT CONTROLLER ==============
class RobotController:
    """
    Controls Lumina Body (ESP32 DevKit) via UDP network.
    Supports fallback to serial for USB connection.
    """
    def __init__(self):
        self.serial = None
        self.udp_socket = None
        self.body_ip = None
        self.body_port = Config.BODY_PORT
        self.connected = False
        self.use_network = True  # Prefer network over serial
        
        # Status from body
        self.chat_mode = False  # Touch sensor state from body
        self.status_callback = None
        
        # Try network first, then serial
        if self.use_network:
            self._init_network()
        
        if not self.connected and SERIAL_AVAILABLE:
            self._auto_connect_serial()
    
    def _init_network(self):
        """Initialize UDP socket and discover body device."""
        try:
            self.udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.udp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            self.udp_socket.settimeout(0.1)  # Non-blocking receive
            self.udp_socket.bind(('', Config.BODY_PORT))
            
            # Try to discover body or use configured IP
            if Config.BODY_IP:
                self.body_ip = Config.BODY_IP
                self._send_udp("PING")
                print(f"✅ Network mode: {self.body_ip}:{self.body_port}")
                self.connected = True
            else:
                # Broadcast discovery
                if self._discover_body():
                    self.connected = True
                else:
                    print("⚠️ Body not discovered, trying serial...")
        except Exception as e:
            print(f"⚠️ Network init failed: {e}")
    
    def _discover_body(self) -> bool:
        """Broadcast UDP discovery to find body device."""
        print("🔍 Discovering Lumina Body...")
        try:
            # Send broadcast discovery
            broadcast_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            broadcast_socket.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            broadcast_socket.settimeout(3)
            
            broadcast_socket.sendto(b"DISCOVER", ('<broadcast>', Config.BODY_PORT))
            
            # Wait for response
            for _ in range(10):
                try:
                    data, addr = broadcast_socket.recvfrom(256)
                    if b"LUMINA_BODY" in data:
                        self.body_ip = addr[0]
                        print(f"✅ Body discovered: {self.body_ip}")
                        broadcast_socket.close()
                        return True
                except socket.timeout:
                    continue
            
            broadcast_socket.close()
        except Exception as e:
            print(f"⚠️ Discovery failed: {e}")
        return False
    
    def _send_udp(self, cmd: str):
        """Send command via UDP to body."""
        if self.udp_socket and self.body_ip:
            try:
                self.udp_socket.sendto(cmd.encode(), (self.body_ip, self.body_port))
            except Exception as e:
                print(f"⚠️ UDP send error: {e}")
    
    def receive_status(self) -> str:
        """Check for incoming status from body (non-blocking)."""
        if self.udp_socket:
            try:
                data, addr = self.udp_socket.recvfrom(256)
                status = data.decode().strip()
                self._handle_status(status)
                return status
            except socket.timeout:
                pass
            except Exception:
                pass
        return None
    
    def _handle_status(self, status: str):
        """Process status messages from body."""
        if status == "STATUS:LISTENING":
            self.chat_mode = True
            print("👆 Touch: Chat mode ON")
            if self.status_callback:
                self.status_callback("LISTENING")
        elif status == "STATUS:MUTE":
            self.chat_mode = False
            print("👆 Touch: Chat mode OFF")
            if self.status_callback:
                self.status_callback("MUTE")
        elif status.startswith("HEARTBEAT:"):
            # Update chat mode from heartbeat
            self.chat_mode = "LISTENING" in status
    
    def _auto_connect_serial(self):
        """Fallback: connect via USB serial."""
        ports = serial.tools.list_ports.comports()
        tokens = ['slab', 'cp210', 'ftdi', 'ch340', 'arduino', 'usb', 'esp']
        for tok in tokens:
            for p in ports:
                desc = ' '.join(filter(None, [p.device, p.description, p.manufacturer])).lower()
                if tok in desc:
                    try:
                        self.serial = serial.Serial(p.device, Config.BAUD_RATE, timeout=0.1)
                        time.sleep(2)
                        print(f"✅ Serial connected: {p.device}")
                        self.connected = True
                        self.use_network = False
                        return
                    except:
                        pass
        print("⚠️ Robot not connected (simulation mode)")
    
    def send_command(self, cmd: str):
        if self.use_network and self.body_ip:
            self._send_udp(cmd)
        elif self.serial:
            try:
                self.serial.write(f"{cmd}\n".encode())
            except:
                pass
    
    def move(self, pan: int, tilt: int):
        self.send_command(f"P{pan}T{tilt}")
    
    # Current face state for simulation display
    current_face = "SLEEP"
    
    def set_face(self, face: str):
        """Set face emotion: HAPPY, SAD, SURPRISED, THINKING, LOVE, SLEEP, TALK, LISTENING"""
        RobotController.current_face = face
        self.send_command(f"F_{face}")
    
    def set_emotion(self, emotion: str):
        """Set emotion based on detected mood."""
        emotion_map = {
            "happy": "HAPPY",
            "excited": "HAPPY",
            "love": "LOVE",
            "sad": "SAD",
            "sorry": "SAD",
            "think": "THINKING",
            "hmm": "THINKING",
            "wonder": "THINKING",
            "wow": "SURPRISED",
            "surprise": "SURPRISED",
            "laugh": "HAPPY",
            "haha": "HAPPY",
        }
        face = emotion_map.get(emotion.lower(), "HAPPY")
        self.set_face(face)
    
    def talk_start(self):
        self.send_command("F_TALK_START")
    
    def talk_stop(self):
        self.send_command("F_TALK_STOP")
    
    # Current LED state for simulation
    current_brightness = 100
    current_color = (255, 255, 255)  # RGB white
    
    def set_brightness(self, level: int):
        """Set LED brightness 0-100."""
        level = max(0, min(100, level))
        RobotController.current_brightness = level
        self.send_command(f"B{level}")
        print(f"💡 Brightness: {level}%")
    
    def set_color(self, r: int, g: int, b: int):
        """Set LED color RGB (0-255 each)."""
        r, g, b = max(0, min(255, r)), max(0, min(255, g)), max(0, min(255, b))
        RobotController.current_color = (r, g, b)
        self.send_command(f"C{r},{g},{b}")
        print(f"🎨 Color: RGB({r},{g},{b})")
    
    def set_color_name(self, color_name: str):
        """Set LED color by name."""
        colors = {
            "red": (255, 0, 0),
            "green": (0, 255, 0),
            "blue": (0, 0, 255),
            "yellow": (255, 255, 0),
            "orange": (255, 165, 0),
            "purple": (128, 0, 128),
            "pink": (255, 105, 180),
            "cyan": (0, 255, 255),
            "white": (255, 255, 255),
            "warm": (255, 200, 100),
            "cool": (200, 220, 255),
        }
        if color_name.lower() in colors:
            r, g, b = colors[color_name.lower()]
            self.set_color(r, g, b)
    
    def close(self):
        """Close all connections."""
        if self.serial:
            self.serial.close()
        if self.udp_socket:
            try:
                self.udp_socket.close()
            except:
                pass


# ============== CAMERA STREAM (ESP32-CAM) ==============
class CameraStream:
    """
    Handles video stream from ESP32-CAM (Device B - Eyes).
    Falls back to local webcam if ESP32-CAM not available.
    """
    def __init__(self, cam_ip: str = None, use_local: bool = True):
        self.cam_ip = cam_ip or Config.CAM_IP
        self.use_local = use_local
        self.cap = None
        self.stream_url = None
        self.connected = False
        
        # Try ESP32-CAM first if IP configured
        if self.cam_ip:
            self._connect_esp_cam()
        
        # Fall back to local webcam
        if not self.connected and use_local:
            self._connect_local()
    
    def _connect_esp_cam(self):
        """Connect to ESP32-CAM MJPEG stream."""
        self.stream_url = f"http://{self.cam_ip}:{Config.CAM_PORT}/stream"
        try:
            # Test connection
            test_url = f"http://{self.cam_ip}:{Config.CAM_PORT}/"
            urllib.request.urlopen(test_url, timeout=2)
            
            self.cap = cv2.VideoCapture(self.stream_url)
            if self.cap.isOpened():
                print(f"📹 ESP32-CAM connected: {self.cam_ip}")
                self.connected = True
            else:
                print(f"⚠️ ESP32-CAM stream failed: {self.stream_url}")
        except Exception as e:
            print(f"⚠️ ESP32-CAM not reachable: {e}")
    
    def _connect_local(self):
        """Connect to local webcam."""
        self.cap = cv2.VideoCapture(0)
        if self.cap.isOpened():
            print("📷 Local webcam connected")
            self.connected = True
        else:
            print("❌ No camera available")
    
    def read(self):
        """Read a frame from the camera."""
        if self.cap and self.cap.isOpened():
            ret, frame = self.cap.read()
            if ret:
                return True, frame
        return False, None
    
    def isOpened(self):
        return self.cap is not None and self.cap.isOpened()
    
    def release(self):
        if self.cap:
            self.cap.release()


# ============== OLED SIMULATION ==============
def draw_oled_simulation(img, face: str, x=10, y=80):
    """Draw a simulated OLED display showing the current face/emotion."""
    # OLED frame (128x64 simulated)
    oled_w, oled_h = 100, 60
    
    # Draw OLED background (black with border)
    cv2.rectangle(img, (x, y), (x + oled_w, y + oled_h), (40, 40, 40), -1)
    cv2.rectangle(img, (x, y), (x + oled_w, y + oled_h), (100, 100, 100), 2)
    
    # Face designs (ASCII art style eyes)
    cx, cy = x + oled_w // 2, y + oled_h // 2
    eye_spacing = 20
    
    if face == "HAPPY":
        # Happy eyes ^_^
        cv2.ellipse(img, (cx - eye_spacing, cy - 5), (8, 10), 0, 180, 360, (0, 255, 100), 2)
        cv2.ellipse(img, (cx + eye_spacing, cy - 5), (8, 10), 0, 180, 360, (0, 255, 100), 2)
        # Smile
        cv2.ellipse(img, (cx, cy + 12), (15, 8), 0, 0, 180, (0, 255, 100), 2)
        
    elif face == "SAD":
        # Sad droopy eyes
        cv2.ellipse(img, (cx - eye_spacing, cy - 5), (8, 5), 0, 0, 180, (100, 100, 255), 2)
        cv2.ellipse(img, (cx + eye_spacing, cy - 5), (8, 5), 0, 0, 180, (100, 100, 255), 2)
        # Frown
        cv2.ellipse(img, (cx, cy + 18), (12, 6), 0, 180, 360, (100, 100, 255), 2)
        
    elif face == "SURPRISED":
        # Big round eyes O_O
        cv2.circle(img, (cx - eye_spacing, cy - 3), 10, (0, 255, 255), 2)
        cv2.circle(img, (cx + eye_spacing, cy - 3), 10, (0, 255, 255), 2)
        cv2.circle(img, (cx - eye_spacing, cy - 3), 4, (0, 255, 255), -1)
        cv2.circle(img, (cx + eye_spacing, cy - 3), 4, (0, 255, 255), -1)
        # Open mouth
        cv2.ellipse(img, (cx, cy + 15), (8, 10), 0, 0, 360, (0, 255, 255), 2)
        
    elif face == "THINKING":
        # One eye squinting, looking up
        cv2.line(img, (cx - eye_spacing - 8, cy - 5), (cx - eye_spacing + 8, cy - 8), (255, 200, 100), 2)
        cv2.ellipse(img, (cx + eye_spacing, cy - 5), (8, 6), 0, 0, 360, (255, 200, 100), 2)
        # Hmm mouth
        cv2.line(img, (cx - 10, cy + 15), (cx + 10, cy + 12), (255, 200, 100), 2)
        
    elif face == "LOVE":
        # Heart eyes
        pts1 = [(cx - eye_spacing - 6, cy - 8), (cx - eye_spacing, cy - 12), (cx - eye_spacing + 6, cy - 8),
                (cx - eye_spacing, cy + 2)]
        pts2 = [(cx + eye_spacing - 6, cy - 8), (cx + eye_spacing, cy - 12), (cx + eye_spacing + 6, cy - 8),
                (cx + eye_spacing, cy + 2)]
        cv2.fillPoly(img, [np.array(pts1)], (180, 100, 255))
        cv2.fillPoly(img, [np.array(pts2)], (180, 100, 255))
        # Blush smile
        cv2.ellipse(img, (cx, cy + 12), (12, 6), 0, 0, 180, (180, 100, 255), 2)
        
    elif face == "LISTENING":
        # Attentive eyes with raised eyebrows
        cv2.line(img, (cx - eye_spacing - 8, cy - 15), (cx - eye_spacing + 8, cy - 12), (255, 255, 100), 2)
        cv2.line(img, (cx + eye_spacing - 8, cy - 12), (cx + eye_spacing + 8, cy - 15), (255, 255, 100), 2)
        cv2.circle(img, (cx - eye_spacing, cy), 6, (255, 255, 100), 2)
        cv2.circle(img, (cx + eye_spacing, cy), 6, (255, 255, 100), 2)
        # Neutral mouth
        cv2.line(img, (cx - 8, cy + 15), (cx + 8, cy + 15), (255, 255, 100), 2)
        
    elif face in ["TALK", "TALK_START"]:
        # Talking animation - open mouth
        cv2.ellipse(img, (cx - eye_spacing, cy - 5), (8, 6), 0, 0, 360, (100, 255, 200), 2)
        cv2.ellipse(img, (cx + eye_spacing, cy - 5), (8, 6), 0, 0, 360, (100, 255, 200), 2)
        # Open mouth (talking)
        cv2.ellipse(img, (cx, cy + 12), (10, 8), 0, 0, 360, (100, 255, 200), 2)
        
    else:  # SLEEP or default
        # Closed eyes - - 
        cv2.line(img, (cx - eye_spacing - 8, cy), (cx - eye_spacing + 8, cy), (150, 150, 150), 2)
        cv2.line(img, (cx + eye_spacing - 8, cy), (cx + eye_spacing + 8, cy), (150, 150, 150), 2)
        # Zzz
        cv2.putText(img, "z", (cx + 30, cy - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.3, (150, 150, 150), 1)
        cv2.putText(img, "Z", (cx + 38, cy - 18), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (150, 150, 150), 1)
    
    # Label
    cv2.putText(img, face, (x + 5, y + oled_h + 15), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (200, 200, 200), 1)


def draw_led_simulation(img, x=10, y=160):
    """Draw simulated LED light showing brightness and color."""
    brightness = RobotController.current_brightness
    color = RobotController.current_color
    
    # Scale color by brightness
    scale = brightness / 100.0
    r, g, b = int(color[0] * scale), int(color[1] * scale), int(color[2] * scale)
    bgr = (b, g, r)  # OpenCV uses BGR
    
    # Draw light bulb shape
    cv2.circle(img, (x + 30, y + 25), 20, bgr, -1)
    cv2.circle(img, (x + 30, y + 25), 20, (100, 100, 100), 2)
    
    # Glow effect (multiple circles with decreasing alpha)
    if brightness > 20:
        overlay = img.copy()
        cv2.circle(overlay, (x + 30, y + 25), 30, bgr, -1)
        cv2.addWeighted(overlay, 0.3, img, 0.7, 0, img)
    
    # Brightness bar
    bar_w = 60
    bar_h = 8
    cv2.rectangle(img, (x, y + 55), (x + bar_w, y + 55 + bar_h), (50, 50, 50), -1)
    fill_w = int(bar_w * brightness / 100)
    cv2.rectangle(img, (x, y + 55), (x + fill_w, y + 55 + bar_h), bgr, -1)
    cv2.rectangle(img, (x, y + 55), (x + bar_w, y + 55 + bar_h), (100, 100, 100), 1)
    
    # Labels
    cv2.putText(img, f"💡 {brightness}%", (x, y + 80), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (200, 200, 200), 1)


# ============== VISION SYSTEM ==============
class VisionSystem:
    def __init__(self):
        self.mp_hands = mp.solutions.hands
        self.hands = self.mp_hands.Hands(
            model_complexity=1,
            min_detection_confidence=0.8,
            min_tracking_confidence=0.8,
            max_num_hands=1
        )
        self.mp_draw = mp.solutions.drawing_utils
        self.current_pan = 90.0
        self.current_tilt = 90.0
    
    @staticmethod
    def get_dist(p1, p2) -> float:
        return math.hypot(p1.x - p2.x, p1.y - p2.y)
    
    def calculate_aspect_ratio(self, landmarks, img_width, img_height):
        x_coords = [lm.x for lm in landmarks]
        y_coords = [lm.y for lm in landmarks]
        min_x, max_x = min(x_coords), max(x_coords)
        min_y, max_y = min(y_coords), max(y_coords)
        box_w = (max_x - min_x) * img_width
        box_h = (max_y - min_y) * img_height
        if box_w == 0:
            return 0, (0, 0, 0, 0)
        ratio = box_h / box_w
        box = (int(min_x * img_width), int(min_y * img_height),
               int(max_x * img_width), int(max_y * img_height))
        return ratio, box
    
    def calculate_finger_straightness(self, landmarks) -> float:
        indices = [(5, 8), (9, 12), (13, 16), (17, 20)]
        scores = []
        for mcp_idx, tip_idx in indices:
            mcp = landmarks[mcp_idx]
            pip = landmarks[mcp_idx + 1]
            dip = landmarks[mcp_idx + 2]
            tip = landmarks[tip_idx]
            if self.get_dist(landmarks[0], tip) < self.get_dist(landmarks[0], pip):
                return 0.0
            total = (self.get_dist(mcp, pip) + self.get_dist(pip, dip) + self.get_dist(dip, tip))
            direct = self.get_dist(mcp, tip)
            scores.append(direct / total if total > 0 else 0)
        return min(scores)
    
    @staticmethod
    def is_palm_facing(landmarks, handedness_label: str) -> bool:
        thumb_x = landmarks[4].x
        pinky_x = landmarks[20].x
        if handedness_label == "Right":
            return thumb_x < pinky_x
        return thumb_x > pinky_x
    
    def process(self, img):
        h, w, _ = img.shape
        center_x, center_y = w // 2, h // 2
        img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        results = self.hands.process(img_rgb)
        
        locked = False
        box = (0, 0, 0, 0)
        status_msg = "IDLE"
        
        if results.multi_hand_landmarks:
            hand_lms = results.multi_hand_landmarks[0]
            label = results.multi_handedness[0].classification[0].label
            lm = hand_lms.landmark
            
            is_upright = lm[0].y > lm[9].y
            is_palm = self.is_palm_facing(lm, label)
            straightness = self.calculate_finger_straightness(lm)
            ratio, box = self.calculate_aspect_ratio(lm, w, h)
            is_tall_enough = ratio > Config.MIN_ASPECT_RATIO
            
            if is_palm and is_upright and is_tall_enough and straightness > Config.OPENNESS_THRESHOLD:
                locked = True
                status_msg = f"LOCKED"
                hand_cx = int(lm[9].x * w)
                hand_cy = int(lm[9].y * h)
                error_x = hand_cx - center_x
                error_y = hand_cy - center_y
                
                if abs(error_x) > Config.DEADZONE:
                    self.current_pan -= error_x * Config.PAN_GAIN
                if abs(error_y) > Config.DEADZONE:
                    self.current_tilt += error_y * Config.TILT_GAIN
                
                self.current_pan = max(Config.PAN_MIN, min(Config.PAN_MAX, self.current_pan))
                self.current_tilt = max(Config.TILT_MIN, min(Config.TILT_MAX, self.current_tilt))
                
                cv2.line(img, (center_x, center_y), (hand_cx, hand_cy), (0, 255, 0), 2)
                cv2.circle(img, (hand_cx, hand_cy), 10, (0, 255, 0), cv2.FILLED)
            
            self.mp_draw.draw_landmarks(img, hand_lms, self.mp_hands.HAND_CONNECTIONS)
        
        return locked, int(self.current_pan), int(self.current_tilt), box, status_msg


# ============== WAKE WORD DETECTOR ==============
class WakeWordDetector:
    def __init__(self, callback):
        self.callback = callback
        self.recognizer = sr.Recognizer()
        self.microphone = sr.Microphone()
        self.running = False
        self._stop_listening = None
    
    def start(self):
        if not SR_AVAILABLE:
            return
        self.running = True
        
        with self.microphone as source:
            self.recognizer.adjust_for_ambient_noise(source, duration=1)
        
        def audio_callback(recognizer, audio):
            if not self.running:
                return
            try:
                text = recognizer.recognize_google(audio, language="si-LK,en-US")
                text_lower = text.lower()
                print(f"🔊 Heard: {text}")
                
                # Check for wake word
                for wake_word in Config.WAKE_WORDS:
                    if wake_word.lower() in text_lower:
                        print(f"✨ Wake word detected!")
                        self.callback()
                        return
            except sr.UnknownValueError:
                pass
            except Exception as e:
                pass
        
        self._stop_listening = self.recognizer.listen_in_background(
            self.microphone, audio_callback, phrase_time_limit=5
        )
        print("👂 Listening for 'Hey Lumina'...")
    
    def stop(self):
        self.running = False
        if self._stop_listening:
            self._stop_listening(wait_for_stop=True)
            self._stop_listening = None
            time.sleep(0.3)
    
    def pause(self):
        self.running = False
    
    def resume(self):
        if self._stop_listening:
            self.running = True


# ============== LIVE CONVERSATION ENGINE ==============
class LiveConversation:
    """Handles continuous voice conversation with Gemini Live API."""
    
    def __init__(self, robot: RobotController):
        self.robot = robot
        self.running = False
        self.is_speaking = False  # Track when AI is speaking (for echo prevention)
        
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("GEMINI_API_KEY not set")
        
        self.client = genai.Client(api_key=api_key)
        self.pya = pyaudio.PyAudio()
        self.input_stream = None
        self.output_stream = None
        
        self.audio_input_queue = asyncio.Queue(maxsize=5)
        self.audio_output_queue = asyncio.Queue()
        
        # Config using proper types
        self.config = types.LiveConnectConfig(
            response_modalities=["AUDIO"],
            system_instruction=Config.SYSTEM_INSTRUCTION,
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=Config.VOICE)
                )
            ),
            realtime_input_config=types.RealtimeInputConfig(
                automatic_activity_detection=types.AutomaticActivityDetection(
                    disabled=False,
                    start_of_speech_sensitivity=types.StartSensitivity.START_SENSITIVITY_UNSPECIFIED,
                    end_of_speech_sensitivity=types.EndSensitivity.END_SENSITIVITY_UNSPECIFIED,
                    prefix_padding_ms=100,
                    silence_duration_ms=800,  # Faster response after you stop speaking
                )
            ),
        )
    
    async def listen_microphone(self):
        mic_info = self.pya.get_default_input_device_info()
        self.input_stream = await asyncio.to_thread(
            self.pya.open,
            format=pyaudio.paInt16,
            channels=Config.CHANNELS,
            rate=Config.SEND_SAMPLE_RATE,
            input=True,
            input_device_index=int(mic_info["index"]),
            frames_per_buffer=Config.CHUNK_SIZE,
        )
        
        while self.running:
            try:
                # ECHO PREVENTION: Only capture audio when AI is NOT speaking
                if self.is_speaking:
                    await asyncio.sleep(0.05)
                    continue
                
                # Set listening face when capturing user audio
                if self.robot and not self.is_speaking:
                    self.robot.set_face("LISTENING")
                
                data = await asyncio.to_thread(
                    self.input_stream.read,
                    Config.CHUNK_SIZE,
                    exception_on_overflow=False
                )
                await self.audio_input_queue.put({"data": data, "mime_type": "audio/pcm"})
            except Exception as e:
                if self.running:
                    print(f"⚠️ Mic: {e}")
                break
    
    async def send_audio(self, session):
        while self.running:
            try:
                audio = await asyncio.wait_for(self.audio_input_queue.get(), timeout=0.1)
                await session.send_realtime_input(audio=audio)
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                if self.running:
                    print(f"⚠️ Send: {e}")
                break
    
    async def receive_audio(self, session):
        while self.running:
            try:
                turn = session.receive()
                async for response in turn:
                    if response.server_content and response.server_content.model_turn:
                        if not self.is_speaking:
                            self.is_speaking = True
                            if self.robot:
                                self.robot.talk_start()
                            print("🤖 ", end="", flush=True)
                        
                        for part in response.server_content.model_turn.parts:
                            # Handle audio
                            if part.inline_data and isinstance(part.inline_data.data, bytes):
                                audio_data = part.inline_data.data
                                if len(audio_data) > 0:
                                    await self.audio_output_queue.put(audio_data)
                            # Handle text - detect emotion and light commands
                            if hasattr(part, 'text') and part.text:
                                text = part.text
                                text_lower = text.lower()
                                print(text, end="", flush=True)
                                
                                # Parse light control commands
                                if self.robot:
                                    # Brightness: [BRIGHTNESS:XX]
                                    brightness_match = re.search(r'\[BRIGHTNESS:(\d+)\]', text)
                                    if brightness_match:
                                        level = int(brightness_match.group(1))
                                        self.robot.set_brightness(level)
                                    
                                    # Color: [COLOR:name]
                                    color_match = re.search(r'\[COLOR:(\w+)\]', text)
                                    if color_match:
                                        color_name = color_match.group(1)
                                        self.robot.set_color_name(color_name)
                                
                                # Detect emotions from response text
                                if self.robot:
                                    if any(w in text_lower for w in ['haha', 'laugh', '😂', 'funny', 'joke']):
                                        self.robot.set_face("HAPPY")
                                    elif any(w in text_lower for w in ['love', 'heart', '❤', 'sweet', 'cute']):
                                        self.robot.set_face("LOVE")
                                    elif any(w in text_lower for w in ['sad', 'sorry', 'unfortunately', 'oh no']):
                                        self.robot.set_face("SAD")
                                    elif any(w in text_lower for w in ['wow', 'amazing', 'incredible', '!']):
                                        self.robot.set_face("SURPRISED")
                                    elif any(w in text_lower for w in ['hmm', 'think', 'let me', 'wonder']):
                                        self.robot.set_face("THINKING")
                    
                    if response.server_content and response.server_content.interrupted:
                        print(" [interrupted]")
                        while not self.audio_output_queue.empty():
                            self.audio_output_queue.get_nowait()
                        self.is_speaking = False
                        if self.robot:
                            self.robot.talk_stop()
                
                if self.is_speaking:
                    print()
                    self.is_speaking = False
                    if self.robot:
                        self.robot.talk_stop()
            except Exception as e:
                if self.running:
                    print(f"⚠️ Recv: {e}")
                break
    
    async def play_audio(self):
        self.output_stream = await asyncio.to_thread(
            self.pya.open,
            format=pyaudio.paInt16,
            channels=Config.CHANNELS,
            rate=Config.RECEIVE_SAMPLE_RATE,
            output=True,
        )
        
        while self.running:
            try:
                audio = await asyncio.wait_for(self.audio_output_queue.get(), timeout=0.1)
                await asyncio.to_thread(self.output_stream.write, audio)
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                if self.running:
                    print(f"⚠️ Play: {e}")
                break
    
    async def monitor_goodbye(self):
        """Monitor for goodbye phrases using speech recognition."""
        if not SR_AVAILABLE:
            return
        
        recognizer = sr.Recognizer()
        microphone = sr.Microphone()
        
        def audio_callback(recognizer, audio):
            if not self.running:
                return
            try:
                text = recognizer.recognize_google(audio, language="en-US").lower()
                # Check for goodbye phrases
                for phrase in Config.END_PHRASES:
                    if phrase in text:
                        print(f"\n👋 Heard '{phrase}' - ending conversation")
                        self.stop()
                        return
            except sr.UnknownValueError:
                pass
            except Exception:
                pass
        
        self.goodbye_detector = recognizer.listen_in_background(
            microphone, audio_callback, phrase_time_limit=5
        )
    
    async def start_session(self):
        """Start continuous live conversation."""
        self.running = True
        
        print("\n" + "=" * 50)
        print("  💬 LIVE CONVERSATION STARTED")
        print("=" * 50)
        print("💡 Just talk naturally - I'm listening!")
        print("💡 Press 'e' in camera window to end")
        print("-" * 50 + "\n")
        
        try:
            async with self.client.aio.live.connect(
                model=Config.LIVE_MODEL,
                config=self.config
            ) as session:
                print("🟢 Connected! Say something to start...\n")
                
                async with asyncio.TaskGroup() as tg:
                    tg.create_task(self.listen_microphone())
                    tg.create_task(self.send_audio(session))
                    tg.create_task(self.receive_audio(session))
                    tg.create_task(self.play_audio())
                    
        except asyncio.CancelledError:
            pass
        except Exception as e:
            print(f"❌ Live session error: {e}")
        finally:
            self.cleanup()
    
    def stop(self):
        self.running = False
    
    def cleanup(self):
        self.running = False
        # Close streams gracefully
        if self.input_stream:
            try:
                self.input_stream.stop_stream()
                self.input_stream.close()
            except Exception:
                pass
            self.input_stream = None
        if self.output_stream:
            try:
                self.output_stream.stop_stream()
                self.output_stream.close()
            except Exception:
                pass
            self.output_stream = None
        print("\n💬 Live conversation ended")


# ============== MAIN APPLICATION ==============
def main():
    print("=" * 55)
    print("  🔆 LUMINA - AI Robotic Lamp with Gemini Live 🔆")
    print("  📡 Split Nervous System Architecture")
    print("=" * 55)
    
    # Initialize components
    controller = RobotController()
    
    # Use CameraStream (ESP32-CAM or local webcam)
    camera = CameraStream(cam_ip=Config.CAM_IP, use_local=True)
    vision = VisionSystem()
    
    if not camera.isOpened():
        sys.exit("❌ No camera available")
    
    # State
    current_state = State.IDLE
    last_state = None
    live_conversation = None
    live_thread = None
    state_lock = threading.Lock()  # Thread-safe state changes
    wake_word_triggered = threading.Event()  # Signal when wake word detected
    touch_triggered = threading.Event()  # Signal when touch sensor triggered
    
    # Wake word callback - just set flag, don't stop detector here
    def on_wake_word():
        nonlocal current_state
        with state_lock:
            if current_state == State.IDLE or current_state == State.TRACKING:
                current_state = State.LISTENING
                wake_word_triggered.set()
    
    # Touch/status callback from body
    def on_body_status(status: str):
        nonlocal current_state
        if status == "LISTENING":
            # Touch activated - skip wake word, start chat immediately
            with state_lock:
                if current_state != State.LIVE_CHAT:
                    current_state = State.LISTENING
                    touch_triggered.set()
                    print("👆 Touch activated - starting chat...")
        elif status == "MUTE":
            # Touch deactivated - stop chat
            with state_lock:
                if current_state == State.LIVE_CHAT and live_conversation:
                    print("👆 Touch deactivated - ending chat...")
                    live_conversation.stop()
    
    # Register callback
    controller.status_callback = on_body_status
    
    # Start wake word detector (as backup to touch)
    wake_detector = WakeWordDetector(on_wake_word)
    if SR_AVAILABLE:
        wake_detector.start()
    
    print("\n🎮 Controls:")
    print("   👆 Touch sensor - Toggle live conversation")
    print("   🗣️  Say 'Hey Lumina' - Start live conversation (backup)")
    print("   Press 'e' - End conversation")
    print("   Press 'q' - Quit")
    print("-" * 55)
    
    def run_live_conversation():
        nonlocal current_state, live_conversation
        try:
            live_conversation = LiveConversation(controller)
            asyncio.run(live_conversation.start_session())
        except Exception as e:
            print(f"❌ Live error: {e}")
        finally:
            current_state = State.IDLE
            if SR_AVAILABLE:
                wake_detector.resume()
    
    while camera.isOpened():
        success, img = camera.read()
        if not success:
            continue
        
        img = cv2.flip(img, 1)
        h, w, _ = img.shape
        
        # Poll for status from body (touch sensor, etc.)
        controller.receive_status()
        
        key = cv2.waitKey(1) & 0xFF
        if key == ord('q'):
            break
        if key == ord('e') and live_conversation:
            print("\n🛑 Ending conversation...")
            live_conversation.stop()
            live_conversation.cleanup()
            time.sleep(0.5)  # Give PyAudio time to fully release resources
            # Tell body to exit chat mode
            controller.send_command("CHAT_STOP")
            with state_lock:
                current_state = State.IDLE
            if SR_AVAILABLE:
                wake_detector.start()
        
        # Check if wake word OR touch was triggered
        triggered = wake_word_triggered.is_set() or touch_triggered.is_set()
        if triggered:
            with state_lock:
                current_state = State.LISTENING
                local_state = State.LISTENING
        else:
            with state_lock:
                local_state = current_state
        
        if local_state == State.LISTENING:
            # Stop wake detector from main thread and start live conversation
            if SR_AVAILABLE:
                wake_detector.stop()
            wake_word_triggered.clear()
            touch_triggered.clear()
            
            with state_lock:
                current_state = State.LIVE_CHAT
            
            print("State: State.LISTENING -> State.LIVE_CHAT")
            live_thread = threading.Thread(target=run_live_conversation, daemon=True)
            live_thread.start()
        
        elif local_state == State.LIVE_CHAT:
            # Continue vision processing during live chat
            locked, pan, tilt, box, status_msg = vision.process(img)
            
            if locked:
                controller.move(pan, tilt)
                # Draw tracking
                if box != (0, 0, 0, 0):
                    cv2.rectangle(img, (box[0], box[1]), (box[2], box[3]), (0, 255, 0), 2)
            
            cv2.circle(img, (w//2, h//2), Config.DEADZONE, (255, 255, 0), 1)
            
            # Draw OLED simulation (face)
            draw_oled_simulation(img, RobotController.current_face, x=10, y=70)
            
            # Draw LED simulation (brightness/color)
            draw_led_simulation(img, x=10, y=175)
            
            # Show live chat indicator overlay
            cv2.rectangle(img, (0, 0), (w, 60), (0, 165, 255), cv2.FILLED)
            cv2.putText(img, "LIVE CONVERSATION" + (" | TRACKING" if locked else ""), (20, 25),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
            cv2.putText(img, "Press 'e' to end", (20, 50),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
            
            # Check if conversation ended
            if live_conversation and not live_conversation.running:
                # Properly cleanup audio streams before restarting wake detector
                live_conversation.cleanup()
                time.sleep(0.5)  # Give PyAudio time to fully release resources
                # Tell body to exit chat mode
                controller.send_command("CHAT_STOP")
                with state_lock:
                    current_state = State.IDLE
                if SR_AVAILABLE:
                    wake_detector.start()  # Restart wake word detection
        
        else:
            # Normal vision processing (IDLE or TRACKING)
            locked, pan, tilt, box, status_msg = vision.process(img)
            
            if locked:
                with state_lock:
                    current_state = State.TRACKING
                controller.move(pan, tilt)
                if last_state != State.TRACKING:
                    controller.set_face("HAPPY")
            else:
                if local_state == State.TRACKING:
                    controller.move(90, 90)
                    controller.set_face("SLEEP")
                with state_lock:
                    current_state = State.IDLE
            
            # Draw debug
            if box != (0, 0, 0, 0):
                color = (0, 255, 0) if locked else (0, 0, 255)
                cv2.rectangle(img, (box[0], box[1]), (box[2], box[3]), color, 2)
            cv2.circle(img, (w//2, h//2), Config.DEADZONE, (255, 255, 0), 1)
            cv2.rectangle(img, (0, 0), (w, 40), (0, 0, 0), cv2.FILLED)
            
            # Show connection mode and instructions
            conn_mode = "📡 WiFi" if controller.use_network else ("🔌 USB" if controller.serial else "🖥️ Sim")
            cv2.putText(img, f"{status_msg} | {conn_mode} | Touch or say 'Hey Lumina'", (20, 28),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
        
        # State indicator
        state_colors = {
            State.IDLE: (128, 128, 128),
            State.TRACKING: (0, 255, 0),
            State.LISTENING: (255, 165, 0),
            State.LIVE_CHAT: (0, 165, 255)
        }
        cv2.circle(img, (w - 25, 25), 12, state_colors.get(local_state, (255, 255, 255)), -1)
        
        with state_lock:
            if current_state != last_state:
                print(f"State: {last_state} -> {current_state}")
                last_state = current_state
        
        cv2.imshow("Lumina", img)
    
    # Cleanup
    if SR_AVAILABLE:
        wake_detector.stop()
    if live_conversation:
        live_conversation.stop()
    camera.release()
    cv2.destroyAllWindows()
    controller.close()
    print("👋 Lumina shutdown complete")


if __name__ == "__main__":
    main()
