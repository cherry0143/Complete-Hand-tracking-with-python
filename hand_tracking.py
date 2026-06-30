"""
╔══════════════════════════════════════════════════════════════════════════════╗
║                    NEXUS-7  //  AIR DRAW TERMINAL                          ║
║              Smooth Drawing Experience • Full Python                        ║
╠══════════════════════════════════════════════════════════════════════════════╣
║  GESTURES:                                                                  ║
║   ☝  Index finger only     → DRAW (clean solid lines)                      ║
║   🤏  Thumb + Index Pinch   → MOVE/DRAG canvas (high-accuracy normalized)   ║
║   ✋  One open palm (5 fingers) → RUNTIME ERASER (wipes drawings under palm) ║
║   🙌  Two hands shown      → CLEAR entire canvas completely (anti-ghosting)║
║   🤘  Index + Pinky         → CYCLE active color                            ║
║                                                                              ║
║  KEYBOARD:                                                                  ║
║   1-6    → Jump to color directly                                           ║
║   C      → Clear canvas                                                     ║
║   S      → Save screenshot                                                  ║
║   ESC    → Exit                                                             ║
╚══════════════════════════════════════════════════════════════════════════════╝

INSTALL:
    pip install opencv-python mediapipe numpy

RUN:
    python hand_tracking.py
"""

import cv2
import numpy as np
import mediapipe as mp
import math
import time

# ─────────────────────────────────────────────────────────────────────────────
#  MEDIAPIPE SETUP  —  High Accuracy Tracking at High Frame Rates (60 FPS)
# ─────────────────────────────────────────────────────────────────────────────
mp_hands   = mp.solutions.hands
mp_drawing = mp.solutions.drawing_utils
mp_styles  = mp.solutions.drawing_styles

hands = mp_hands.Hands(
    max_num_hands=2,
    model_complexity=1,
    min_detection_confidence=0.65,
    min_tracking_confidence=0.65
)

# ─────────────────────────────────────────────────────────────────────────────
#  CAMERA
# ─────────────────────────────────────────────────────────────────────────────
cap = cv2.VideoCapture(0)
cap.set(cv2.CAP_PROP_FRAME_WIDTH,  1280)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
cap.set(cv2.CAP_PROP_FPS, 60)

ret, test = cap.read()
if not ret:
    print("[ERROR] Camera not found.")
    exit()

H_CAM, W_CAM = test.shape[:2]

# ─────────────────────────────────────────────────────────────────────────────
#  STATE
# ─────────────────────────────────────────────────────────────────────────────
canvas = np.zeros((H_CAM, W_CAM, 3), dtype=np.uint8)

prev_x, prev_y = None, None
smooth_x, smooth_y = 0, 0
smooth_pinch_x, smooth_pinch_y = 0, 0

# Higher ALPHA = zero drawing lag. (0.55 for immediate cursor tracking)
ALPHA = 0.55

mode        = 0
MODE_NAMES  = [
    "01 // CYAN",
    "02 // RED",
    "03 // GREEN",
    "04 // GOLD YELLOW",
    "05 // MAGENTA",
    "06 // WHITE",
]
NUM_MODES   = len(MODE_NAMES)

# Solid colors in BGR format
COLORS = [
    (255, 255, 0),    # Cyan
    (0, 0, 255),      # Red
    (0, 255, 0),      # Green
    (0, 200, 255),    # Gold Yellow
    (255, 0, 255),    # Magenta
    (255, 255, 255)   # White
]

shockwaves  = []
frame_count    = 0
mode_stamp     = 0.0
gesture_stamp  = 0.0
last_gesture   = ""
is_drawing     = False
is_moving      = False
is_erasing     = False
screenshot_flash = 0

# Track drag start/offset
prev_pinch_x, prev_pinch_y = None, None

# Anti-ghosting counter for clearing canvas (requires consecutive frames to trigger)
two_hand_clear_count = 0

# ─────────────────────────────────────────────────────────────────────────────
#  ROTATION-INVARIANT HIGH-ACCURACY GESTURE DETECTION
# ─────────────────────────────────────────────────────────────────────────────
def get_dist(p1, p2):
    return math.hypot(p1[0] - p2[0], p1[1] - p2[1])

def fingers_up(lm):
    """
    Detect extended fingers using a rotation-invariant distance method.
    Compares the distance from the wrist to the tip vs the wrist to the pip joint.
    """
    f = []
    wrist = lm[0]
    
    # Thumb: tip (4) distance to pinky knuckle base (17) vs thumb base (3) to 17
    f.append(1 if get_dist(lm[4], lm[17]) > get_dist(lm[3], lm[17]) else 0)
    
    # Four fingers: check if tip is further from the wrist than the pip joint
    for tip, pip in zip([8, 12, 16, 20], [6, 10, 14, 18]):
        f.append(1 if get_dist(lm[tip], wrist) > get_dist(lm[pip], wrist) else 0)
        
    return f   # [thumb, index, middle, ring, pinky]

# ─────────────────────────────────────────────────────────────────────────────
#  SHOCKWAVE (Visual feedback for clearing canvas)
# ─────────────────────────────────────────────────────────────────────────────
def spawn_shockwave():
    shockwaves.append({"r": 10, "life": 1.0})

def update_shockwaves(frame):
    dead = []
    cx, cy = W_CAM // 2, H_CAM // 2
    for sw in shockwaves:
        sw["r"]    += 28
        sw["life"] -= 0.06
        if sw["life"] <= 0:
            dead.append(sw)
            continue
        a   = int(255 * sw["life"])
        col = (0, a, int(a * 0.7))
        cv2.circle(frame, (cx, cy), int(sw["r"]), col, 2, cv2.LINE_AA)
        cv2.circle(frame, (cx, cy), max(1, int(sw["r"]) - 10),
                   (0, int(a * 0.4), a), 1, cv2.LINE_AA)
    for s in dead:
        shockwaves.remove(s)

# ─────────────────────────────────────────────────────────────────────────────
#  DRAW STROKE  — Clean Solid lines
# ─────────────────────────────────────────────────────────────────────────────
def draw_stroke(layer, x1, y1, x2, y2):
    dist = math.hypot(x2 - x1, y2 - y1)
    if dist < 1.0:
        return

    x1, y1, x2, y2 = int(x1), int(y1), int(x2), int(y2)
    col = COLORS[mode]
    
    # Simple solid clean drawing line (8px thickness)
    cv2.line(layer, (x1, y1), (x2, y2), col, 8, cv2.LINE_AA)

# ─────────────────────────────────────────────────────────────────────────────
#  RUNTIME ERASER
# ─────────────────────────────────────────────────────────────────────────────
def run_runtime_eraser(frame, layer, cx, cy, radius):
    cv2.circle(layer, (cx, cy), radius, (0, 0, 0), -1)
    
    # Beautiful holographic scanner ring indicating erasing
    cv2.circle(frame, (cx, cy), radius, (0, 100, 255), 2, cv2.LINE_AA)
    t = (math.sin(time.time() * 8) + 1) / 2
    glow_col = (0, int(120 + 135 * t), 255)
    cv2.circle(frame, (cx, cy), radius + 4, glow_col, 1, cv2.LINE_AA)
    
    cv2.putText(frame, "PALM WIPER", (cx - 45, cy - radius - 12),
                cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 150, 255), 1, cv2.LINE_AA)

# ─────────────────────────────────────────────────────────────────────────────
#  HUD OVERLAY
# ─────────────────────────────────────────────────────────────────────────────
def draw_hud(frame, fps):
    t_now = time.time()

    # ── Top bar
    overlay = frame.copy()
    cv2.rectangle(overlay, (0, 0), (W_CAM, 52), (5, 5, 15), -1)
    cv2.addWeighted(overlay, 0.75, frame, 0.25, 0, frame)
    cv2.rectangle(frame, (0, 50), (W_CAM, 52), (0, 180, 255), -1)

    # Active Color Name Indicator
    pulse = int(200 + 55 * math.sin(t_now * 3))
    col   = COLORS[mode]
    cv2.putText(frame, f"NEXUS-7  //  COLOR: {MODE_NAMES[mode]}",
                (16, 33), cv2.FONT_HERSHEY_SIMPLEX, 0.70, col, 2, cv2.LINE_AA)

    # Status
    if is_erasing:
        status_text = "ERASING"
        status_col = (0, 100, 255)
    elif is_moving:
        status_text = "DRAGGING CANVAS"
        status_col = (0, 220, 255)
    elif is_drawing:
        status_text = "DRAWING"
        status_col = (0, 255, 100)
    else:
        status_text = "STANDBY"
        status_col = (180, 180, 180)

    cv2.putText(frame, status_text, (W_CAM - 240, 33),
                cv2.FONT_HERSHEY_SIMPLEX, 0.55, status_col, 1, cv2.LINE_AA)

    # FPS
    cv2.putText(frame, f"{int(fps)} fps", (W_CAM - 90, 33),
                cv2.FONT_HERSHEY_SIMPLEX, 0.50, (0, 180, 120), 1, cv2.LINE_AA)

    # ── Bottom bar
    overlay2 = frame.copy()
    cv2.rectangle(overlay2, (0, H_CAM - 44), (W_CAM, H_CAM), (5, 5, 15), -1)
    cv2.addWeighted(overlay2, 0.75, frame, 0.25, 0, frame)
    cv2.rectangle(frame, (0, H_CAM - 44), (W_CAM, H_CAM - 42), (0, 180, 255), -1)

    hints = "☝ DRAW   🤏 PINCH TO MOVE   ✋ ONE PALM = ERASER   🙌 TWO HANDS = CLEAR ALL   [S] SAVE   [ESC] EXIT"
    cv2.putText(frame, hints, (16, H_CAM - 14),
                cv2.FONT_HERSHEY_SIMPLEX, 0.40, (0, 160, 210), 1, cv2.LINE_AA)

    # ── Mode indicators
    for i in range(NUM_MODES):
        dot_x = W_CAM - 20 - i * 16
        if i == mode:
            cv2.circle(frame, (dot_x, H_CAM - 16), 5, COLORS[i], -1)
            cv2.circle(frame, (dot_x, H_CAM - 16), 7, (255, 255, 255), 1)
        else:
            cv2.circle(frame, (dot_x, H_CAM - 16), 3, (60, 60, 60), -1)

    # ── Corner accent brackets
    blen = 28
    bcol = (0, 160, 255)
    bw   = 2
    corners_pts = [
        ((4, 54), (4 + blen, 54), (4, 54 + blen)),
        ((W_CAM - 4, 54), (W_CAM - 4 - blen, 54), (W_CAM - 4, 54 + blen)),
        ((4, H_CAM - 46), (4 + blen, H_CAM - 46), (4, H_CAM - 46 - blen)),
        ((W_CAM - 4, H_CAM - 46), (W_CAM - 4 - blen, H_CAM - 46), (W_CAM - 4, H_CAM - 46 - blen)),
    ]
    for corner, p1, p2 in corners_pts:
        cv2.line(frame, corner, p1, bcol, bw)
        cv2.line(frame, corner, p2, bcol, bw)

    # ── Cursor feedback
    if is_drawing:
        cx_, cy_ = smooth_x, smooth_y
        size = 12
        cv2.line(frame, (cx_ - size, cy_), (cx_ + size, cy_), col, 1, cv2.LINE_AA)
        cv2.line(frame, (cx_, cy_ - size), (cx_, cy_ + size), col, 1, cv2.LINE_AA)
        cv2.circle(frame, (cx_, cy_), 4, (255, 255, 255), 1, cv2.LINE_AA)

    elif is_moving:
        cx_, cy_ = smooth_pinch_x, smooth_pinch_y
        cv2.rectangle(frame, (cx_ - 15, cy_ - 15), (cx_ + 15, cy_ + 15), (0, 220, 255), 1, cv2.LINE_AA)
        cv2.circle(frame, (cx_, cy_), 3, (0, 255, 255), -1)
        for dx, dy in [(-20, 0), (20, 0), (0, -20), (0, 20)]:
            cv2.line(frame, (cx_, cy_), (cx_ + dx, cy_ + dy), (0, 180, 255), 1)

    # ── Mode switch banner
    if t_now - mode_stamp < 1.4:
        frac = 1.0 - (t_now - mode_stamp) / 1.4
        bh = 62
        by = H_CAM // 2 - bh // 2
        banner = frame.copy()
        cv2.rectangle(banner, (100, by), (W_CAM - 100, by + bh), (5, 15, 35), -1)
        cv2.rectangle(banner, (100, by),     (W_CAM - 100, by + 1),      (0, 180, 255), -1)
        cv2.rectangle(banner, (100, by + bh - 1), (W_CAM - 100, by + bh), (0, 180, 255), -1)
        cv2.addWeighted(banner, frac * 0.88, frame, 1 - frac * 0.88, 0, frame)
        text_col = COLORS[mode]
        cv2.putText(frame, f"COLOR: {MODE_NAMES[mode]}",
                    (130, by + 38), cv2.FONT_HERSHEY_SIMPLEX, 0.85, text_col, 2, cv2.LINE_AA)

    # ── Gesture flash
    if t_now - gesture_stamp < 0.9 and last_gesture:
        frac = 1.0 - (t_now - gesture_stamp) / 0.9
        col2 = (0, int(255 * frac), int(180 * frac))
        tw   = cv2.getTextSize(last_gesture, cv2.FONT_HERSHEY_SIMPLEX, 0.70, 2)[0][0]
        tx   = (W_CAM - tw) // 2
        cv2.putText(frame, last_gesture, (tx, 88),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.70, col2, 2, cv2.LINE_AA)

    # ── Screenshot flash
    global screenshot_flash
    if screenshot_flash > 0:
        white = np.full_like(frame, 255)
        cv2.addWeighted(white, screenshot_flash / 12.0, frame, 1 - screenshot_flash / 12.0, 0, frame)
        screenshot_flash -= 1


# ─────────────────────────────────────────────────────────────────────────────
#  MERGE canvas onto frame
# ─────────────────────────────────────────────────────────────────────────────
def merge(frame, layer):
    gray = cv2.cvtColor(layer, cv2.COLOR_BGR2GRAY)
    _, mask = cv2.threshold(gray, 10, 255, cv2.THRESH_BINARY)
    mask_inv = cv2.bitwise_not(mask)
    bg = cv2.bitwise_and(frame, cv2.cvtColor(mask_inv, cv2.COLOR_GRAY2BGR))
    fg = cv2.bitwise_and(layer, cv2.cvtColor(mask,     cv2.COLOR_GRAY2BGR))
    return cv2.add(bg, fg)


# ─────────────────────────────────────────────────────────────────────────────
#  MAIN LOOP
# ─────────────────────────────────────────────────────────────────────────────
prev_time  = time.time()
fps_smooth = 60.0

print("\n[NEXUS-7] Starting... Press ESC to exit.\n")

while True:
    ret, frame = cap.read()
    if not ret:
        break

    frame = cv2.flip(frame, 1)

    # ── FPS Tracking
    now       = time.time()
    raw_fps   = 1.0 / max(0.001, now - prev_time)
    fps_smooth = 0.95 * fps_smooth + 0.05 * raw_fps
    prev_time  = now
    frame_count += 1

    # ── Full Resolution RGB Frame for high accuracy landmark tracking
    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    results = hands.process(rgb)

    # Reset frame state flags
    is_drawing = False
    is_moving  = False
    is_erasing = False

    # Check for visible hands
    if results.multi_hand_landmarks:
        num_hands = len(results.multi_hand_landmarks)

        # ── 🙌 TWO HANDS = CLEAR ALL DRAWINGS COMPLETELY (Requires 10 consecutive frames to prevent ghost clears)
        if num_hands == 2:
            two_hand_clear_count += 1
            if two_hand_clear_count >= 10:
                canvas[:] = 0
                spawn_shockwave()
                prev_x, prev_y = None, None
                prev_pinch_x, prev_pinch_y = None, None
                last_gesture   = ">> BOTH HANDS: CANVAS CLEARED <<"
                gesture_stamp  = time.time()
                two_hand_clear_count = 0
        
        # ── ONE HAND = CONTROL
        elif num_hands == 1:
            two_hand_clear_count = 0  # Reset counter immediately if only 1 hand is present
            handLms = results.multi_hand_landmarks[0]
            lm = [(int(l.x * W_CAM), int(l.y * H_CAM)) for l in handLms.landmark]

            # Rotation-invariant finger extended states
            fingers = fingers_up(lm)
            fcount  = sum(fingers)
            
            # Key landmark points
            ix, iy = lm[8]  # index tip
            tx, ty = lm[4]  # thumb tip

            # Smooth cursor position (with high ALPHA 0.55 for zero drawing lag)
            smooth_x = int(ALPHA * ix + (1 - ALPHA) * smooth_x)
            smooth_y = int(ALPHA * iy + (1 - ALPHA) * smooth_y)

            # Calculate hand size for distance normalization
            hand_size = max(1.0, get_dist(lm[0], lm[9]))
            pinch_dist_norm = get_dist(lm[4], lm[8]) / hand_size

            # ── 1. PINCH TO MOVE CANVAS (High accuracy normalized check)
            if pinch_dist_norm < 0.35:
                is_moving = True
                prev_x, prev_y = None, None  # break drawing path
                
                # Center of pinch coordinates
                cx = (lm[4][0] + lm[8][0]) // 2
                cy = (lm[4][1] + lm[8][1]) // 2

                if prev_pinch_x is None:
                    smooth_pinch_x, smooth_pinch_y = cx, cy
                else:
                    # Smooth panning movement
                    smooth_pinch_x = int(0.30 * cx + 0.70 * smooth_pinch_x)
                    smooth_pinch_y = int(0.30 * cy + 0.70 * smooth_pinch_y)

                if prev_pinch_x is not None:
                    dx = smooth_pinch_x - prev_pinch_x
                    dy = smooth_pinch_y - prev_pinch_y
                    if dx != 0 or dy != 0:
                        # Translate canvas
                        M = np.float32([[1, 0, dx], [0, 1, dy]])
                        canvas = cv2.warpAffine(canvas, M, (W_CAM, H_CAM))
                        
                prev_pinch_x, prev_pinch_y = smooth_pinch_x, smooth_pinch_y

            # ── 2. GENERAL CONTROL STATES (when not pinching)
            else:
                prev_pinch_x, prev_pinch_y = None, None

                # ✋ ONE OPEN PALM = RUNTIME ERASER (wipes specific parts under palm)
                if fcount == 5:
                    is_erasing = True
                    prev_x, prev_y = None, None
                    
                    # Erase center is palm center (landmark 9)
                    cx, cy = lm[9]
                    # Dynamic radius proportional to hand size on screen
                    erase_radius = int(hand_size * 1.3)
                    run_runtime_eraser(frame, canvas, cx, cy, erase_radius)

                # 🤘 INDEX + PINKY = CYCLE MODE
                elif fingers[1] == 1 and fingers[4] == 1 and fingers[2] == 0 and fingers[3] == 0:
                    if time.time() - mode_stamp > 0.8:
                        mode       = (mode + 1) % NUM_MODES
                        mode_stamp = time.time()
                        last_gesture  = f">> {MODE_NAMES[mode]} <<"
                        gesture_stamp = time.time()
                    prev_x, prev_y = None, None

                # ☝ INDEX ONLY = DRAW
                elif fingers[1] == 1 and fcount == 1:
                    is_drawing = True
                    if prev_x is None:
                        prev_x, prev_y = smooth_x, smooth_y

                    draw_stroke(canvas, prev_x, prev_y, smooth_x, smooth_y)
                    prev_x, prev_y = smooth_x, smooth_y

                # OTHER GESTURES = STANDBY
                else:
                    prev_x, prev_y = None, None
    else:
        prev_x, prev_y = None, None
        prev_pinch_x, prev_pinch_y = None, None
        two_hand_clear_count = 0  # Reset counter immediately if hands are lost

    # ── MERGE canvas onto frame
    frame = merge(frame, canvas)

    # ── Shockwaves
    update_shockwaves(frame)

    # ── HUD
    draw_hud(frame, fps_smooth)

    # ── Show
    cv2.imshow("NEXUS-7  //  AIR DRAW", frame)

    # ── KEYBOARD
    key = cv2.waitKey(1) & 0xFF
    if key == 27:    # ESC
        break
    elif key == ord('c') or key == ord('C'):
        canvas[:] = 0
        spawn_shockwave()
        last_gesture  = ">> CANVAS CLEARED <<"
        gesture_stamp = time.time()
    elif key == ord('s') or key == ord('S'):
        fname = f"nexus_draw_{int(time.time())}.png"
        cv2.imwrite(fname, frame)
        print(f"[SAVED] {fname}")
        screenshot_flash = 12
        last_gesture  = f">> SAVED: {fname} <<"
        gesture_stamp = time.time()
    elif key == ord('1'): mode = 0; mode_stamp = time.time()
    elif key == ord('2'): mode = 1; mode_stamp = time.time()
    elif key == ord('3'): mode = 2; mode_stamp = time.time()
    elif key == ord('4'): mode = 3; mode_stamp = time.time()
    elif key == ord('5'): mode = 4; mode_stamp = time.time()
    elif key == ord('6'): mode = 5; mode_stamp = time.time()

# ── CLEANUP
cap.release()
cv2.destroyAllWindows()
print("\n[NEXUS-7] Session ended.\n")
