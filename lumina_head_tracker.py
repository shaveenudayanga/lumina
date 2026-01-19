import cv2
import mediapipe as mp
import serial
import time
import math
import sys
import argparse
import os

# --- 1. CONFIGURATION ---
# Default serial port per OS. Update this if your device uses a different name.
if sys.platform == 'darwin':
    DEFAULT_SERIAL_PORT = '/dev/tty.SLAB_USBtoUART'  # common CP210x on macOS
elif sys.platform.startswith('linux'):
    DEFAULT_SERIAL_PORT = '/dev/ttyUSB0'  # common on Linux
elif sys.platform.startswith('win'):
    DEFAULT_SERIAL_PORT = 'COM3'  # common on Windows
else:
    DEFAULT_SERIAL_PORT = 'COM3'

DEFAULT_BAUD_RATE = 115200

# Command-line / environment overrides
parser = argparse.ArgumentParser(description='Lumina Head Tracker')
parser.add_argument('-p', '--port', default=os.getenv('LUMINA_SERIAL_PORT', DEFAULT_SERIAL_PORT), help='Serial port (override)')
parser.add_argument('-b', '--baud', type=int, default=int(os.getenv('LUMINA_BAUD', DEFAULT_BAUD_RATE)), help='Baud rate')
parser.add_argument('--no-arduino', action='store_true', dest='no_arduino', help='Run in simulation mode (do not open serial)')
parser.add_argument('--auto-detect', action='store_true', dest='auto_detect', help='Auto-detect serial port (prefers USB-serial adapters)')
args = parser.parse_args()

SERIAL_PORT = args.port
BAUD_RATE = args.baud

# === THE NEW ASPECT RATIO SETTINGS ===
# Height divided by Width.
# Normal Open Hand is usually 1.5 - 1.8
# Fist/Claw is usually 0.8 - 1.1
MIN_ASPECT_RATIO = 1.3 

# Still keep the finger straightness check (but less aggressive)
OPENNESS_THRESHOLD = 0.85 

# PHYSICS
PAN_GAIN = 0.05
TILT_GAIN = 0.05
DEADZONE = 40

# --- 2. HARDWARE SETUP ---
arduino = None
if getattr(args, 'no_arduino', False):
    print("⚠️ Simulation Mode (forced by --no-arduino)")
else:
    # Optionally auto-detect a useful serial port
    if getattr(args, 'auto_detect', False):
        detected = detect_serial_port()
        if detected:
            SERIAL_PORT = detected
            print(f"Using auto-detected port: {SERIAL_PORT}")
        else:
            print("No serial port auto-detected; using configured SERIAL_PORT")

    try:
        arduino = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=0.1)
        time.sleep(2)
        print("✅ Arduino Connected")
    except Exception as e:
        print(f"⚠️ Simulation Mode (serial error: {e})")
        arduino = None

# --- 3. AUTO-CAMERA ---
def get_camera():
    for index in [1, 0]:
        cap = cv2.VideoCapture(index)
        if cap.isOpened(): return cap
    sys.exit("❌ No Camera Found")

cap = get_camera()

# --- 4. MEDIAPIPE ---
mp_hands = mp.solutions.hands
hands = mp_hands.Hands(
    model_complexity=1,
    min_detection_confidence=0.8,
    min_tracking_confidence=0.8,
    max_num_hands=1
)
mp_draw = mp.solutions.drawing_utils

# --- 5. MATH HELPERS ---
def get_dist(p1, p2):
    return math.hypot(p1.x - p2.x, p1.y - p2.y)

def calculate_aspect_ratio(lm, w, h):
    """
    Calculates the Bounding Box of the hand.
    Returns: Ratio (Height / Width), Box Coordinates
    """
    x_coords = [l.x for l in lm]
    y_coords = [l.y for l in lm]
    
    min_x, max_x = min(x_coords), max(x_coords)
    min_y, max_y = min(y_coords), max(y_coords)
    
    box_w = (max_x - min_x) * w
    box_h = (max_y - min_y) * h
    
    if box_w == 0: return 0, (0,0,0,0)
    
    ratio = box_h / box_w
    return ratio, (int(min_x*w), int(min_y*h), int(max_x*w), int(max_y*h))

def calculate_finger_straightness(lm):
    # Simple "Weakest Link" check for straightness
    indices = [(5, 8), (9, 12), (13, 16), (17, 20)]
    scores = []
    
    for m, t in indices:
        mcp, pip, dip, tip = lm[m], lm[m+1], lm[m+2], lm[t]
        
        # Claw Check (2D): Tip closer to wrist than PIP?
        if get_dist(lm[0], tip) < get_dist(lm[0], pip): return 0.0
            
        total = get_dist(mcp, pip) + get_dist(pip, dip) + get_dist(dip, tip)
        curr = get_dist(mcp, tip)
        scores.append(curr / total if total > 0 else 0)

    return min(scores)

def is_palm_facing(lm, label):
    # Mirror view check
    thumb_x, pinky_x = lm[4].x, lm[20].x
    if label == "Right": return thumb_x < pinky_x 
    else: return thumb_x > pinky_x 

# --- 6. MAIN LOOP ---
current_pan = 90.0
current_tilt = 90.0

while cap.isOpened():
    success, img = cap.read()
    if not success: continue

    img = cv2.flip(img, 1)
    h, w, _ = img.shape
    center_x, center_y = w // 2, h // 2

    img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    results = hands.process(img_rgb)

    status_msg = "IDLE"
    status_color = (0, 0, 255)
    box_color = (0, 0, 255) # Red Box initially

    if results.multi_hand_landmarks:
        hand_lms = results.multi_hand_landmarks[0]
        label = results.multi_handedness[0].classification[0].label
        lm = hand_lms.landmark

        # --- VALIDATION ---
        is_upright = lm[0].y > lm[9].y
        is_palm = is_palm_facing(lm, label)
        straightness = calculate_finger_straightness(lm)
        
        # THE NEW ASPECT RATIO CHECK
        ratio, box = calculate_aspect_ratio(lm, w, h)
        is_tall_enough = ratio > MIN_ASPECT_RATIO

        # --- DECISION ---
        if is_palm and is_upright and is_tall_enough and straightness > OPENNESS_THRESHOLD:
            status_msg = f"LOCKED (Ratio: {ratio:.2f})"
            status_color = (0, 255, 0)
            box_color = (0, 255, 0) # Green Box

            # Movement
            hand_cx = int(lm[9].x * w)
            hand_cy = int(lm[9].y * h)
            error_x = hand_cx - center_x
            error_y = hand_cy - center_y

            if abs(error_x) > DEADZONE: current_pan -= error_x * PAN_GAIN 
            if abs(error_y) > DEADZONE: current_tilt += error_y * TILT_GAIN

            current_pan = max(0, min(180, current_pan))
            current_tilt = max(45, min(135, current_tilt))

            if arduino:
                cmd = f"P{int(current_pan)}T{int(current_tilt)}\n"
                arduino.write(cmd.encode())
                arduino.write(b"L100\n") 

            cv2.line(img, (center_x, center_y), (hand_cx, hand_cy), (0, 255, 0), 2)
            cv2.circle(img, (hand_cx, hand_cy), 10, (0, 255, 0), cv2.FILLED)

        else:
            if not is_palm: status_msg = "Show Palm"
            elif not is_tall_enough: status_msg = f"Open Wider (Ratio: {ratio:.2f})"
            elif straightness == 0: status_msg = "Straighten Fingers"
            else: status_msg = "Hold Upright"

        # DRAW VISUAL DEBUGGER
        cv2.rectangle(img, (box[0], box[1]), (box[2], box[3]), box_color, 2)
        mp_draw.draw_landmarks(img, hand_lms, mp_hands.HAND_CONNECTIONS)

    cv2.circle(img, (center_x, center_y), DEADZONE, (255, 255, 0), 1)
    cv2.rectangle(img, (0, 0), (w, 50), (0, 0, 0), cv2.FILLED)
    cv2.putText(img, status_msg, (20, 35), cv2.FONT_HERSHEY_SIMPLEX, 0.8, status_color, 2)
    
    cv2.imshow("Lumina Aspect Ratio Mode", img)
    if cv2.waitKey(1) & 0xFF == ord('q'): break

cap.release()
cv2.destroyAllWindows()