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
import sys
import requests
from enum import Enum, auto
from dotenv import load_dotenv

# Suppress warnings
warnings.filterwarnings("ignore", message=".*SymbolDatabase.GetPrototype.*")

# Python 3.11+ has native TaskGroup, older versions need polyfill
if sys.version_info < (3, 11, 0):
    try:
        import taskgroup
        import exceptiongroup
        asyncio.TaskGroup = taskgroup.TaskGroup
        asyncio.ExceptionGroup = exceptiongroup.ExceptionGroup
    except ImportError:
        print("⚠️ Python < 3.11 detected. Install: pip install taskgroup exceptiongroup")

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
    BODY_IP = "10.32.11.48"  # ESP32 DevKit body IP (UPDATED!)
    BODY_PORT = 5005        # UDP port for body commands
    AUDIO_IN_PORT = 5006    # Port to receive audio FROM ESP32 mic
    AUDIO_OUT_PORT = 5007   # Port to send audio TO ESP32 speaker
    CAM_IP = "10.32.11.55"  # ESP32-CAM IP (lumina-cam.local)
    CAM_PORT = 80           # HTTP port for camera stream
    
    # Serial (fallback if network not available)
    BAUD_RATE = 115200
    
    # Vision thresholds
    MIN_ASPECT_RATIO = 1.3
    OPENNESS_THRESHOLD = 0.85
    DEADZONE = 30  # Reduced for faster response
    # Verticality thresholds for palm/nails detection
    VERTICALITY_RATIO = 1.5   # abs(dy) / (abs(dx)+eps) must exceed this to be considered vertical
    VERTICAL_DY = 0.02        # minimum absolute normalized dy to consider as up/down

    # Servo tracking settings - adjusted for smooth 180° servos
    PAN_GAIN = 0.15   # Increased for more responsive tracking
    TILT_GAIN = 0.30  # Increased 1.5x for more sensitive vertical tracking
    SMOOTHING = 0.5   # Lower = faster response (was 0.7)
    PAN_MIN, PAN_MAX = 30, 150  # Safe range for 180° servos
    TILT_MIN, TILT_MAX = 60, 120  # REDUCED - physical mount limits!
    
    # Gemini Live API
    LIVE_MODEL = "gemini-2.5-flash-native-audio-preview-01-2026"
    
    # Audio settings
    SEND_SAMPLE_RATE = 16000
    RECEIVE_SAMPLE_RATE = 24000
    CHANNELS = 1
    CHUNK_SIZE = 512  # Smaller chunks = lower latency
    
    # Audio source: True = use ESP32 mic/speaker, False = use Mac mic/speaker
    USE_ESP32_AUDIO = False
    
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
        
        # Servo rate limiting - prevent flooding commands
        self._last_pan = 90
        self._last_tilt = 90
        self._last_move_time = 0
        self._move_interval = 0.02  # 20ms between move commands (faster tracking)
        
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
                # Try resolving hostname early so subsequent sends use an IP
                self._resolve_body_ip()
                self._send_udp("PING")
                # Enable servos on startup
                self._send_udp("SERVO_ENABLE")
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
    
    def _resolve_body_ip(self) -> bool:
        """Try to resolve a hostname (e.g., lumina.local) to an IP address.
        Returns True if resolved (and updates self.body_ip), False otherwise."""
        try:
            # Only attempt resolution if body_ip looks like a hostname
            if not self.body_ip:
                return False
            # If already an IP address, this will be a no-op
            ip = socket.gethostbyname(self.body_ip)
            if ip and ip != self.body_ip:
                print(f"🔍 Resolved body hostname {self.body_ip} -> {ip}")
                self.body_ip = ip
            return True
        except Exception as e:
            print(f"⚠️ Failed to resolve body hostname '{self.body_ip}': {e}")
            return False

    def _send_udp(self, cmd: str):
        """Send command via UDP to body. Attempts to resolve hostname on failure."""
        if self.udp_socket and self.body_ip:
            try:
                self.udp_socket.sendto(cmd.encode(), (self.body_ip, self.body_port))
            except socket.gaierror as e:
                # Name resolution failed - try to resolve explicitly and retry once
                print(f"⚠️ UDP send error: {e} - attempting to resolve hostname")
                if self._resolve_body_ip():
                    try:
                        self.udp_socket.sendto(cmd.encode(), (self.body_ip, self.body_port))
                        return
                    except Exception as e2:
                        print(f"⚠️ UDP send error after resolve: {e2}")
                else:
                    print("⚠️ Unable to resolve body hostname; disabling network sends until fixed")
                    self.use_network = False
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
        """Move servos with rate limiting and duplicate filtering."""
        now = time.time()
        
        # Skip if same position as last time
        if pan == self._last_pan and tilt == self._last_tilt:
            return
        
        # Skip if sending too fast (rate limiting)
        if now - self._last_move_time < self._move_interval:
            return
        
        # Send command and update tracking
        self._last_pan = pan
        self._last_tilt = tilt
        self._last_move_time = now
        # Use new servo command format for smooth 180° position control
        print(f"SENDING: SERVO_PAN:{pan}")
        self.send_command(f"SERVO_PAN:{pan}")
        print(f"SENDING: SERVO_TILT:{tilt}")
        self.send_command(f"SERVO_TILT:{tilt}")
    
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


# ============== MJPEG STREAM READER ==============
class MJPEGStreamReader:
    """Custom MJPEG stream reader for ESP32-CAM."""
    def __init__(self, url):
        self.url = url
        self.stream = None
        self.opened = False
        self._connect()
    
    def _connect(self):
        try:
            self.stream = requests.get(self.url, stream=True, timeout=5)
            if self.stream.status_code == 200:
                self.opened = True
                self.bytes_buffer = bytes()
        except Exception as e:
            print(f"MJPEG connection failed: {e}")
            self.opened = False
    
    def isOpened(self):
        return self.opened
    
    def read(self):
        if not self.opened:
            return False, None
        
        try:
            # Read chunks from stream
            for chunk in self.stream.iter_content(chunk_size=1024):
                self.bytes_buffer += chunk
                
                # Find JPEG boundaries
                a = self.bytes_buffer.find(b'\xff\xd8')  # JPEG start
                b = self.bytes_buffer.find(b'\xff\xd9')  # JPEG end
                
                if a != -1 and b != -1:
                    jpg = self.bytes_buffer[a:b+2]
                    self.bytes_buffer = self.bytes_buffer[b+2:]
                    
                    # Decode JPEG
                    frame = cv2.imdecode(np.frombuffer(jpg, dtype=np.uint8), cv2.IMREAD_COLOR)
                    if frame is not None:
                        return True, frame
            return False, None
        except Exception as e:
            self.opened = False
            return False, None
    
    def release(self):
        self.opened = False
        if self.stream:
            self.stream.close()


# ============== CAMERA STREAM (ESP32-CAM) ==============
class CameraStream:
    """
    Handles video stream from ESP32-CAM (Device B - Eyes).
    Falls back to local webcam if ESP32-CAM not available.
    """
    def __init__(self, cam_ip: str = None, use_local: bool = True):
        self.cam_ip = cam_ip
        self.use_local = use_local
        self.cap = None
        self.stream_url = None
        self.connected = False
        self.source = "none"
        
        # Try ESP32-CAM first if IP configured (not None and not empty)
        if self.cam_ip and self.cam_ip.strip():
            self._connect_esp_cam()
        else:
            print("ℹ️ ESP32-CAM IP not set, using local webcam")
        
        # Fall back to local webcam
        if not self.connected and use_local:
            self._connect_local()
    
    def _connect_esp_cam(self):
        """Connect to ESP32-CAM MJPEG stream with custom reader."""
        self.stream_url = f"http://{self.cam_ip}:{Config.CAM_PORT}/stream"
        print(f"🔍 Trying ESP32-CAM at {self.cam_ip}...")
        try:
            # Test connection with short timeout
            test_url = f"http://{self.cam_ip}:{Config.CAM_PORT}/"
            urllib.request.urlopen(test_url, timeout=3)
            
            # Use custom MJPEG reader for ESP32-CAM
            self.cap = MJPEGStreamReader(self.stream_url)
            if self.cap.isOpened():
                print(f"📹 ESP32-CAM connected: {self.cam_ip}")
                self.connected = True
                self.source = "esp32cam"
            else:
                print(f"⚠️ ESP32-CAM stream failed: {self.stream_url}")
                print("   Hint: Make sure ESP32-CAM is powered and on same network")
        except urllib.error.URLError as e:
            print(f"⚠️ ESP32-CAM not reachable at {self.cam_ip}")
            print(f"   Error: {e.reason}")
            print("   Hint: Check if ESP32-CAM is powered and connected to WiFi")
        except Exception as e:
            print(f"⚠️ ESP32-CAM connection error: {e}")
    
    def _connect_local(self):
        """Connect to local webcam with low latency settings."""
        print("🔍 Trying local webcam...")
        self.cap = cv2.VideoCapture(0)
        if self.cap.isOpened():
            # Optimize for low latency
            self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
            self.cap.set(cv2.CAP_PROP_FPS, 30)
            print("📷 Local webcam connected")
            self.connected = True
            self.source = "local"
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
    
    def get_source(self):
        """Return camera source type: 'esp32cam', 'local', or 'none'"""
        return self.source
    
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
        # Smoothed hand position for filtering jitter
        self.smoothed_hand_x = None
        self.smoothed_hand_y = None
    
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
    
    def check_fingers_together(self, landmarks) -> bool:
        """Check if fingers are close together (no gaps between them).
        Returns True if all adjacent finger tips are within a threshold distance."""
        finger_tips = [landmarks[8], landmarks[12], landmarks[16], landmarks[20]]  # index, middle, ring, pinky tips
        max_gap = 0.08  # Maximum normalized distance between adjacent fingertips
        
        for i in range(len(finger_tips) - 1):
            gap = self.get_dist(finger_tips[i], finger_tips[i + 1])
            if gap > max_gap:
                return False
        return True
    
    @staticmethod
    def is_palm_facing(landmarks, handedness_label: str) -> (bool, tuple):
        """Return (is_facing, normal) where is_facing is True if palm faces camera.

        Uses a 3D cross-product between the wrist->index_mcp and wrist->pinky_mcp
        vectors to compute a palm normal. The sign of the normal's z component
        indicates facing direction (heuristic for MediaPipe coords). This function
        returns both a boolean and the computed normal for visualization.
        Falls back to the simple thumb/pinky heuristic on error.
        """
        try:
            p0 = landmarks[0]
            p5 = landmarks[5]
            p17 = landmarks[17]
            # Vectors from wrist to index_mcp and wrist to pinky_mcp
            v1 = (p5.x - p0.x, p5.y - p0.y, p5.z - p0.z)
            v2 = (p17.x - p0.x, p17.y - p0.y, p17.z - p0.z)
            # Cross product v1 x v2
            nx = v1[1] * v2[2] - v1[2] * v2[1]
            ny = v1[2] * v2[0] - v1[0] * v2[2]
            nz = v1[0] * v2[1] - v1[1] * v2[0]
            # small threshold to avoid noise
            thresh = 1e-4
            if handedness_label == "Right":
                facing = nz < -thresh
            else:
                facing = nz > thresh
            return facing, (nx, ny, nz)
        except Exception:
            # Fallback to simple heuristic if something goes wrong
            thumb_x = landmarks[4].x
            pinky_x = landmarks[20].x
            if handedness_label == "Right":
                return thumb_x < pinky_x, (0.0, 0.0, -1.0)
            return thumb_x > pinky_x, (0.0, 0.0, 1.0)
    
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
            
            # Determine palm facing and get normal for visualization
            is_palm, normal = self.is_palm_facing(lm, label)
            nx, ny, nz = normal
            straightness = self.calculate_finger_straightness(lm)
            fingers_together = self.check_fingers_together(lm)
            ratio, box = self.calculate_aspect_ratio(lm, w, h)
            is_tall_enough = ratio > Config.MIN_ASPECT_RATIO

            # Draw palm normal arrow and nz value for debugging
            wrist_x = int(lm[0].x * w)
            wrist_y = int(lm[0].y * h)
            # Project normal to 2D (flip y because image coords)
            arrow_end = (wrist_x + int(nx * 200), wrist_y - int(ny * 200))
            color = (0, 255, 0) if is_palm else (0, 0, 255)
            cv2.arrowedLine(img, (wrist_x, wrist_y), arrow_end, color, 2, tipLength=0.3)
            cv2.putText(img, f"nz={nz:.3f}", (wrist_x + 8, wrist_y - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1)

            # Compute wrist->middle_tip direction for visualization
            mid_tip = lm[12]
            dx = mid_tip.x - lm[0].x
            dy = mid_tip.y - lm[0].y

            # Handle nails (back-of-hand) detection - accept any rotation IF fingers straight and together
            nails_locked = False
            nails_state = 'NAILS'
            if not is_palm and straightness > Config.OPENNESS_THRESHOLD and fingers_together:
                nails_locked = True
                cv2.putText(img, nails_state, (wrist_x + 8, wrist_y + 20), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 200, 0), 2)

            # For palm-facing, accept any rotation (360°) IF palm faces, hand open, fingers straight AND together
            palm_locked = False
            palm_state = 'PALM'
            if is_palm and is_tall_enough and straightness > Config.OPENNESS_THRESHOLD and fingers_together:
                palm_locked = True
                cv2.putText(img, palm_state, (wrist_x + 8, wrist_y + 40), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 240, 160), 2)

            # Final acceptance: either palm or nails at any rotation, but only when fingers straight and together
            if palm_locked or nails_locked:
                locked = True
                status_msg = f"LOCKED"
                if nails_locked:
                    raw_hand_cx = int((lm[0].x + lm[12].x) / 2 * w)
                    raw_hand_cy = int((lm[0].y + lm[12].y) / 2 * h)
                else:
                    raw_hand_cx = int(lm[9].x * w)
                    raw_hand_cy = int(lm[9].y * h)
                
                # Apply low-pass filter to smooth hand position (reduces jitter)
                if self.smoothed_hand_x is None:
                    self.smoothed_hand_x = raw_hand_cx
                    self.smoothed_hand_y = raw_hand_cy
                else:
                    self.smoothed_hand_x = Config.SMOOTHING * self.smoothed_hand_x + (1 - Config.SMOOTHING) * raw_hand_cx
                    self.smoothed_hand_y = Config.SMOOTHING * self.smoothed_hand_y + (1 - Config.SMOOTHING) * raw_hand_cy
                
                hand_cx = int(self.smoothed_hand_x)
                hand_cy = int(self.smoothed_hand_y)
                
                # DIRECT MAPPING: Map hand screen position directly to servo angle
                # (Fixed camera mode - servo doesn't move camera view)
                # hand_cx: 0 (left edge) -> w (right edge)
                # Map to: PAN_MIN -> PAN_MAX
                target_pan = Config.PAN_MIN + (hand_cx / w) * (Config.PAN_MAX - Config.PAN_MIN)
                target_tilt = Config.TILT_MIN + (hand_cy / h) * (Config.TILT_MAX - Config.TILT_MIN)
                
                # Smooth transition to target (prevents sudden jumps)
                self.current_pan = Config.SMOOTHING * self.current_pan + (1 - Config.SMOOTHING) * target_pan
                self.current_tilt = Config.SMOOTHING * self.current_tilt + (1 - Config.SMOOTHING) * target_tilt
                
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
        if self._stop_listening is not None:
            return  # Already running
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
        """Stop the wake-word background listener."""
        self.running = False
        # Stop background listening if active
        if self._stop_listening:
            try:
                self._stop_listening(wait_for_stop=False)
            except Exception:
                pass
            self._stop_listening = None

    def cleanup(self):
        """Cleanup wake word detector resources."""
        self.running = False
        # Stop background listening and release resources
        if self._stop_listening:
            try:
                self._stop_listening(wait_for_stop=True)
            except Exception:
                pass
            self._stop_listening = None


# ============== GEMINI LIVE API CONVERSATION ==============
class LiveConversation:
    """
    Handles Gemini Live API bidirectional voice conversation.
    Supports both Mac audio (default) and ESP32 audio (via UDP).
    """
    
    def __init__(self, robot_controller, use_esp32_audio=False):
        self.robot = robot_controller
        self.running = False
        self.client = None
        self.session = None
        self.use_esp32_audio = use_esp32_audio
        
        if not LIVE_AVAILABLE:
            raise RuntimeError("google-genai not installed. Run: pip install google-genai")
        
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise RuntimeError("GEMINI_API_KEY not set in environment")
        
        # Use v1alpha API version for native audio
        self.client = genai.Client(api_key=api_key, http_options={'api_version': 'v1alpha'})
        
        # Audio setup for Mac
        self.pya = pyaudio.PyAudio()
        self.mic_stream = None
        self.speaker_stream = None
        
        # UDP sockets for ESP32 audio
        self.esp32_mic_socket = None   # Receive mic audio from ESP32
        self.esp32_speaker_socket = None  # Send speaker audio to ESP32
        
        # Queues for async audio
        self.audio_in_queue = None  # Audio from Gemini to play
        self.audio_out_queue = None  # Audio from mic to send
    
    async def _listen_audio_mac(self):
        """Capture audio from Mac microphone."""
        try:
            mic_info = self.pya.get_default_input_device_info()
            self.mic_stream = await asyncio.to_thread(
                self.pya.open,
                format=pyaudio.paInt16,
                channels=Config.CHANNELS,
                rate=Config.SEND_SAMPLE_RATE,
                input=True,
                input_device_index=mic_info["index"],
                frames_per_buffer=Config.CHUNK_SIZE
            )
            
            print(f"🎤 Mac Mic: {mic_info['name']}")
            
            while self.running:
                audio_data = await asyncio.to_thread(
                    self.mic_stream.read, Config.CHUNK_SIZE, False
                )
                await self.audio_out_queue.put({
                    "data": audio_data,
                    "mime_type": "audio/pcm"
                })
                
        except Exception as e:
            print(f"❌ Mac mic error: {e}")
        finally:
            if self.mic_stream:
                self.mic_stream.stop_stream()
                self.mic_stream.close()
    
    async def _listen_audio_esp32(self):
        """Receive audio from ESP32 microphone via UDP."""
        try:
            self.esp32_mic_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.esp32_mic_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.esp32_mic_socket.bind(('', Config.AUDIO_IN_PORT))
            self.esp32_mic_socket.settimeout(0.1)  # 100ms timeout
            
            print(f"🎤 ESP32 Mic: listening on port {Config.AUDIO_IN_PORT}")
            
            while self.running:
                try:
                    audio_data, addr = self.esp32_mic_socket.recvfrom(2048)
                    if audio_data:
                        await self.audio_out_queue.put({
                            "data": audio_data,
                            "mime_type": "audio/pcm"
                        })
                except socket.timeout:
                    await asyncio.sleep(0.001)
                except BlockingIOError:
                    await asyncio.sleep(0.01)
                except Exception as e:
                    if self.running:
                        await asyncio.sleep(0.01)
                        
        except Exception as e:
            print(f"❌ ESP32 mic error: {e}")
        finally:
            if self.esp32_mic_socket:
                self.esp32_mic_socket.close()
    
    async def _send_audio(self):
        """Send queued audio to Gemini Live."""
        while self.running:
            try:
                audio_msg = await self.audio_out_queue.get()
                await self.session.send_realtime_input(audio=audio_msg)
            except Exception as e:
                if self.running:
                    print(f"❌ Send error: {e}")
    
    async def _receive_audio(self):
        """Receive audio responses from Gemini and queue for playback."""
        try:
            while self.running:
                turn = self.session.receive()
                async for response in turn:
                    if not self.running:
                        break
                    
                    # Handle audio data
                    if response.data:
                        self.audio_in_queue.put_nowait(response.data)
                        # Tell robot we're speaking
                        if self.robot:
                            self.robot.talk_start()
                        continue
                    
                    # Handle text (for debugging)
                    if response.text:
                        print(f"🤖 {response.text}")
                        # Parse for light control commands
                        self._parse_light_commands(response.text)
                
                # Turn complete - stop talking animation
                if self.robot:
                    self.robot.talk_stop()
                
                # Clear audio queue on turn complete (for interruptions)
                while not self.audio_in_queue.empty():
                    self.audio_in_queue.get_nowait()
                    
        except Exception as e:
            if self.running:
                print(f"❌ Receive error: {e}")
    
    async def _play_audio_mac(self):
        """Play audio from Gemini through Mac speakers."""
        try:
            self.speaker_stream = await asyncio.to_thread(
                self.pya.open,
                format=pyaudio.paInt16,
                channels=Config.CHANNELS,
                rate=Config.RECEIVE_SAMPLE_RATE,
                output=True
            )
            
            print("🔊 Mac Speaker active")
            
            while self.running:
                audio_bytes = await self.audio_in_queue.get()
                await asyncio.to_thread(self.speaker_stream.write, audio_bytes)
                
        except Exception as e:
            if self.running:
                print(f"❌ Mac speaker error: {e}")
        finally:
            if self.speaker_stream:
                try:
                    self.speaker_stream.stop_stream()
                except Exception:
                    pass  # Ignore errors during cleanup
                try:
                    self.speaker_stream.close()
                except Exception:
                    pass  # Ignore errors during cleanup
    
    async def _play_audio_esp32(self):
        """Send audio from Gemini to ESP32 speaker via UDP."""
        try:
            self.esp32_speaker_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            
            # Get ESP32 body IP
            esp32_ip = self.robot.body_ip if self.robot and self.robot.body_ip else Config.BODY_IP
            
            print(f"🔊 ESP32 Speaker: sending to {esp32_ip}:{Config.AUDIO_OUT_PORT}")
            
            # ESP32 uses 16kHz, Gemini sends at 24kHz - need to resample
            esp32_sample_rate = 16000
            resample_ratio = esp32_sample_rate / Config.RECEIVE_SAMPLE_RATE  # 16000/24000 = 0.666
            
            while self.running:
                audio_bytes = await self.audio_in_queue.get()
                
                # Resample audio from 24kHz to 16kHz using linear interpolation
                import struct
                samples = struct.unpack(f'<{len(audio_bytes)//2}h', audio_bytes)
                
                # Simple decimation with linear interpolation
                new_length = int(len(samples) * resample_ratio)
                resampled = []
                for i in range(new_length):
                    src_index = i / resample_ratio
                    idx0 = int(src_index)
                    idx1 = min(idx0 + 1, len(samples) - 1)
                    frac = src_index - idx0
                    value = int(samples[idx0] * (1 - frac) + samples[idx1] * frac)
                    resampled.append(value)
                
                resampled_bytes = struct.pack(f'<{len(resampled)}h', *resampled)
                
                # Send audio in chunks (UDP has size limits)
                chunk_size = 1024
                for i in range(0, len(resampled_bytes), chunk_size):
                    chunk = resampled_bytes[i:i+chunk_size]
                    try:
                        self.esp32_speaker_socket.sendto(chunk, (esp32_ip, Config.AUDIO_OUT_PORT))
                        await asyncio.sleep(0.001)  # Pace the sending to avoid buffer overflow
                    except Exception:
                        pass
                
        except Exception as e:
            if self.running:
                print(f"❌ ESP32 speaker error: {e}")
        finally:
            if self.esp32_speaker_socket:
                self.esp32_speaker_socket.close()
    
    def _parse_light_commands(self, text: str):
        """Parse and execute light control commands from Gemini's response."""
        # Brightness command: [BRIGHTNESS:50]
        brightness_match = re.search(r'\[BRIGHTNESS:(\d+)\]', text)
        if brightness_match and self.robot:
            level = int(brightness_match.group(1))
            self.robot.set_brightness(level)
        
        # Color command: [COLOR:blue]
        color_match = re.search(r'\[COLOR:(\w+)\]', text)
        if color_match and self.robot:
            self.robot.set_color_name(color_match.group(1))
        
        # End conversation
        if "CONVERSATION_END" in text:
            print("👋 Gemini ended conversation")
            self.stop()
    
    async def start_session(self):
        """Start the Live API session with audio streaming."""
        self.running = True
        audio_mode = "ESP32" if self.use_esp32_audio else "Mac"
        print(f"\n🎙️  Starting Gemini Live conversation ({audio_mode} audio)...")
        
        if self.robot:
            self.robot.set_face("LISTENING")
            # If using ESP32 audio, tell it to start streaming
            if self.use_esp32_audio:
                print("📡 Starting ESP32 audio streaming...")
                self.robot.send_command("AUDIO_START")
                await asyncio.sleep(0.5)  # Wait for ESP32 to initialize
        
        try:
            config = {
                "response_modalities": ["AUDIO"],
                "speech_config": {
                    "voice_config": {
                        "prebuilt_voice_config": {"voice_name": Config.VOICE}
                    }
                },
                "system_instruction": Config.SYSTEM_INSTRUCTION
            }
            
            async with self.client.aio.live.connect(model=Config.LIVE_MODEL, config=config) as session:
                self.session = session
                print("✅ Connected to Gemini Live")
                
                # Initialize queues
                self.audio_in_queue = asyncio.Queue()
                self.audio_out_queue = asyncio.Queue(maxsize=5)
                
                async with asyncio.TaskGroup() as tg:
                    # Start audio tasks based on mode
                    if self.use_esp32_audio:
                        tg.create_task(self._listen_audio_esp32())
                        tg.create_task(self._play_audio_esp32())
                    else:
                        tg.create_task(self._listen_audio_mac())
                        tg.create_task(self._play_audio_mac())
                    
                    tg.create_task(self._send_audio())
                    tg.create_task(self._receive_audio())
                    
                    # Keep running until stopped
                    while self.running:
                        await asyncio.sleep(0.1)
                    
                    # Cancel all tasks when stopped
                    raise asyncio.CancelledError("User stopped conversation")
                
        except asyncio.CancelledError:
            pass
        except Exception as e:
            print(f"❌ Live session error: {e}")
            import traceback
            traceback.print_exc()
        finally:
            self.running = False
            # Stop ESP32 audio streaming
            if self.use_esp32_audio and self.robot:
                self.robot.send_command("AUDIO_STOP")
            if self.robot:
                self.robot.set_face("HAPPY")
            print("💬 Live session ended")
    
    def stop(self):
        """Stop the live conversation."""
        self.running = False
    
    def cleanup(self):
        """Cleanup audio resources after conversation ends."""
        self.running = False
        # Cleanup Mac audio streams
        if self.mic_stream:
            try:
                self.mic_stream.stop_stream()
                self.mic_stream.close()
            except:
                pass
        if self.speaker_stream:
            try:
                self.speaker_stream.stop_stream()
                self.speaker_stream.close()
            except:
                pass
        # Cleanup ESP32 audio sockets
        if self.esp32_mic_socket:
            try:
                self.esp32_mic_socket.close()
            except:
                pass
            self.esp32_mic_socket = None
        if self.esp32_speaker_socket:
            try:
                self.esp32_speaker_socket.close()
            except:
                pass
            self.esp32_speaker_socket = None
        # Stop ESP32 audio streaming
        if self.use_esp32_audio and self.robot:
            self.robot.send_command("AUDIO_STOP")


# ============== MAIN APPLICATION ==============
def main():
    print("=" * 55)
    print("  🔆 LUMINA - AI Robotic Lamp with Gemini Live 🔆")
    print("  📡 Split Nervous System Architecture")
    print("=" * 55)
    
    # Initialize components
    controller = RobotController()
    
    # Send startup greeting to eyes display
    controller.send_command("TEXT:Hi Lumina")
    
    # Use CameraStream (ESP32-CAM or local webcam)
    # use_local=False means use ESP-CAM if CAM_IP is set
    use_local = not bool(Config.CAM_IP)
    camera = CameraStream(cam_ip=Config.CAM_IP, use_local=use_local)
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
    
    # Touch/status callback from body - DISABLED
    # def on_body_status(status: str):
    #     nonlocal current_state
    #     if status == "LISTENING":
    #         # Touch activated - skip wake word, start chat immediately
    #         with state_lock:
    #             if current_state != State.LIVE_CHAT:
    #                 current_state = State.LISTENING
    #                 touch_triggered.set()
    #                 print("👆 Touch activated - starting chat...")
    #     elif status == "MUTE":
    #         # Touch deactivated - stop chat
    #         with state_lock:
    #             if current_state == State.LIVE_CHAT and live_conversation:
    #                 print("👆 Touch deactivated - ending chat...")
    #                 live_conversation.stop()
    
    # Register callback - DISABLED
    # controller.status_callback = on_body_status
    
    # Start wake word detector (as backup to touch)
    wake_detector = WakeWordDetector(on_wake_word)
    if SR_AVAILABLE:
        wake_detector.start()
    
    print("\n🎮 Controls:")
    print("   �️  Say 'Hey Lumina' - Start live conversation")
    print("   Press 'v' - Start live conversation (manual)")
    print("   Press 'e' - End conversation")
    print("   Press 'q' - Quit")
    print("-" * 55)
    
    def run_live_conversation():
        nonlocal current_state, live_conversation
        try:
            live_conversation = LiveConversation(controller, use_esp32_audio=Config.USE_ESP32_AUDIO)
            asyncio.run(live_conversation.start_session())
        except Exception as e:
            print(f"❌ Live error: {e}")
            import traceback
            traceback.print_exc()
        finally:
            current_state = State.IDLE
            # Wake detector continues running in background, no need to resume
    
    while camera.isOpened():
        success, img = camera.read()
        if not success:
            continue
        
        img = cv2.flip(img, 1)
        h, w, _ = img.shape
        
        # Poll for status from body (disabled for now)
        # controller.receive_status()
        
        key = cv2.waitKey(1) & 0xFF
        if key == ord('q'):
            break
        if key == ord('v') and not live_conversation:
            # Manual start (useful when no touch sensor available)
            print("\n🟢 Manual start requested (key 'v')")
            wake_word_triggered.set()
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
        
        # Check if wake word was triggered (touch disabled)
        triggered = wake_word_triggered.is_set()
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
            # touch_triggered.clear()  # Disabled
            
            with state_lock:
                current_state = State.LIVE_CHAT
            
            print("State: State.LISTENING -> State.LIVE_CHAT")
            live_thread = threading.Thread(target=run_live_conversation, daemon=True)
            live_thread.start()
        
        elif local_state == State.LIVE_CHAT:
            # Continue vision processing during live chat
            locked, pan, tilt, box, status_msg = vision.process(img)
            
            # Only send move commands if hand gesture is LOCKED (proper palm gesture)
            # This prevents servo from moving randomly during conversation
            if locked:
                controller.move(pan, tilt)
                # Draw tracking
                if box != (0, 0, 0, 0):
                    cv2.rectangle(img, (box[0], box[1]), (box[2], box[3]), (0, 255, 0), 2)
            # If not locked, don't send any servo commands - servo holds last position
            
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
                print(f"DEBUG: pan={pan}, tilt={tilt}")  # Debug output
                controller.move(pan, tilt)
                if last_state != State.TRACKING:
                    controller.set_face("HAPPY")
            else:
                # Keep servo at last position when hand removed (don't reset to 90)
                if local_state == State.TRACKING:
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
            cv2.putText(img, f"{status_msg} | {conn_mode} | Say 'Hey Lumina' or press 'v'", (20, 28),
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
