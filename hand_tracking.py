"""
╔══════════════════════════════════════════════════════════════════════════════╗
║                    NEXUS-7  //  AIR DRAW TERMINAL                          ║
║              Futuristic Camera Drawing Experience • Full Python             ║
╠══════════════════════════════════════════════════════════════════════════════╣
║  GESTURES:                                                                  ║
║   ☝  Index finger only     → DRAW in current mode                          ║
║   ✌  Index + Middle        → ERASE (holographic eraser circle)             ║
║   🤘  Index + Pinky         → CYCLE to next animation mode                  ║
║   ✋  All 5 fingers          → CLEAR canvas with shockwave                   ║
║   ✊  Fist (0 fingers)       → PAUSE / freeze drawing                        ║
║                                                                              ║
║  KEYBOARD:                                                                  ║
║   1-6    → Jump to mode directly                                            ║
║   C      → Clear canvas                                                     ║
║   S      → Save screenshot                                                  ║
║   ESC    → Exit                                                             ║
╠══════════════════════════════════════════════════════════════════════════════╣
║  MODES:                                                                     ║
║   1. PLASMA LASER   — Electric arc with pulsing energy rings               ║
║   2. NEON RAINBOW   — Smooth HSV color cycling thick brush                  ║
║   3. FIRE INFERNO   — Upward flame particles + ember glow                   ║
║   4. STARFIELD      — Star trails + constellation burst                     ║
║   5. GLITCH INK     — RGB channel split + digital pixel scatter             ║
║   6. LIGHTNING      — Branching electric bolt fractal                       ║
╚══════════════════════════════════════════════════════════════════════════════╝

INSTALL:
    pip install opencv-python mediapipe numpy

RUN:
    python nexus_draw.py
"""

import cv2
import numpy as np
import mediapipe as mp
import math
import random
import time
import os

# ─────────────────────────────────────────────────────────────────────────────
#  MEDIAPIPE SETUP
# ─────────────────────────────────────────────────────────────────────────────
mp_hands   = mp.solutions.hands
mp_drawing = mp.solutions.drawing_utils
mp_styles  = mp.solutions.drawing_styles

hands = mp_hands.Hands(
    max_num_hands=1,
    min_detection_confidence=0.75,
    min_tracking_confidence=0.75
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
canvas      = np.zeros((H_CAM, W_CAM, 3), dtype=np.uint8)
overlay_fx  = np.zeros((H_CAM, W_CAM, 3), dtype=np.uint8)  # transient fx layer

prev_x, prev_y = None, None
smooth_x, smooth_y = 0, 0
ALPHA = 0.38   # EMA smoothing factor

hue         = 0
mode        = 0
MODE_NAMES  = [
    "01 // PLASMA LASER",
    "02 // NEON RAINBOW",
    "03 // FIRE INFERNO",
    "04 // STARFIELD",
    "05 // GLITCH INK",
    "06 // LIGHTNING",
]
NUM_MODES   = len(MODE_NAMES)

particles   = []
rings       = []
shockwaves  = []
lightning_bolts = []

frame_count    = 0
mode_stamp     = 0.0
gesture_stamp  = 0.0
last_gesture   = ""
is_drawing     = False
glitch_timer   = 0
screenshot_flash = 0

# ─────────────────────────────────────────────────────────────────────────────
#  DECAY RATES PER MODE  (how fast old strokes fade)
# ─────────────────────────────────────────────────────────────────────────────
MODE_DECAY = [0.96, 0.97, 0.93, 0.98, 0.95, 0.96]

# ─────────────────────────────────────────────────────────────────────────────
#  FINGER DETECTION
# ─────────────────────────────────────────────────────────────────────────────
def fingers_up(lm):
    f = []
    # Thumb (compare x for mirrored cam)
    f.append(1 if lm[4][0] < lm[3][0] else 0)
    # Four fingers compare y tip vs pip
    for tip in [8, 12, 16, 20]:
        f.append(1 if lm[tip][1] < lm[tip - 2][1] else 0)
    return f   # [thumb, index, middle, ring, pinky]


# ─────────────────────────────────────────────────────────────────────────────
#  PARTICLES
# ─────────────────────────────────────────────────────────────────────────────
def spawn_particles(x, y, burst=False):
    count = {0:8, 1:5, 2:14, 3:16, 4:5, 5:10}[mode]
    if burst:
        count *= 4
    for _ in range(count):
        angle = random.uniform(0, 2 * math.pi)
        speed = random.uniform(1.5, 5.0) if burst else random.uniform(0.8, 3.0)

        # Fire rises
        if mode == 2:
            angle = random.uniform(math.pi * 1.1, math.pi * 1.9)
            speed = random.uniform(1.5, 4.5)

        particles.append({
            "x": x + random.randint(-4, 4),
            "y": y + random.randint(-4, 4),
            "vx": math.cos(angle) * speed,
            "vy": math.sin(angle) * speed,
            "life": random.randint(10, 24),
            "max": 24,
            "mode": mode,
            "hue": hue,
            "size": random.uniform(1.5, 5.0),
        })


def update_particles(layer):
    dead = []
    for p in particles:
        p["x"] += p["vx"]
        p["y"] += p["vy"]
        p["vx"] *= 0.95
        p["vy"] *= 0.95
        if p["mode"] == 2:
            p["vy"] -= 0.18   # fire anti-gravity
        else:
            p["vy"] += 0.06   # gravity
        p["life"] -= 1

        if p["life"] <= 0:
            dead.append(p)
            continue

        t   = p["life"] / p["max"]
        sz  = max(1, int(p["size"] * t))
        px_ = int(p["x"])
        py_ = int(p["y"])
        m   = p["mode"]

        if m == 0:   # Plasma - white→cyan→blue
            if t > 0.6:
                col = (int(255*t), int(220*t), int(180*t))
            else:
                col = (int(200*t), int(120*t), 0)
        elif m == 1: # Rainbow
            h_ = int(p["hue"]) % 180
            bgr = cv2.cvtColor(np.uint8([[[h_, 255, int(255*t)]]]),
                               cv2.COLOR_HSV2BGR)[0][0]
            col = tuple(int(c) for c in bgr)
        elif m == 2: # Fire
            col = (0, int(80*t*t), int(255*t))
        elif m == 3: # Star
            v = int(255 * t)
            col = (v, v, v)
        elif m == 4: # Glitch
            col = (int(255*t), 0, int(200*t))
        else:        # Lightning
            col = (int(255*t), int(255*t), int(100*t))

        cv2.circle(layer, (px_, py_), sz, col, -1)

    for p in dead:
        particles.remove(p)


# ─────────────────────────────────────────────────────────────────────────────
#  ENERGY RINGS
# ─────────────────────────────────────────────────────────────────────────────
def spawn_ring(x, y, color, max_r=40, speed=3):
    rings.append({"x": x, "y": y, "r": 4, "max": max_r,
                  "speed": speed, "color": color, "life": 1.0})


def update_rings(layer):
    dead = []
    for rng in rings:
        rng["r"]    += rng["speed"]
        rng["life"] -= 0.07
        if rng["life"] <= 0 or rng["r"] > rng["max"]:
            dead.append(rng)
            continue
        a = int(255 * rng["life"])
        col = tuple(min(255, int(c * rng["life"])) for c in rng["color"])
        cv2.circle(layer, (rng["x"], rng["y"]), int(rng["r"]), col, 1, cv2.LINE_AA)
    for r in dead:
        rings.remove(r)


# ─────────────────────────────────────────────────────────────────────────────
#  SHOCKWAVE (on clear)
# ─────────────────────────────────────────────────────────────────────────────
def spawn_shockwave():
    shockwaves.append({"r": 10, "life": 1.0})


def update_shockwaves(frame):
    dead = []
    cx, cy = W_CAM // 2, H_CAM // 2
    for sw in shockwaves:
        sw["r"]    += 35
        sw["life"] -= 0.05
        if sw["life"] <= 0:
            dead.append(sw)
            continue
        a   = int(255 * sw["life"])
        col = (a, int(a * 0.8), 0)
        cv2.circle(frame, (cx, cy), int(sw["r"]), col, 2, cv2.LINE_AA)
        cv2.circle(frame, (cx, cy), max(1, int(sw["r"]) - 8),
                   (0, int(a * 0.5), a), 1, cv2.LINE_AA)
    for s in dead:
        shockwaves.remove(s)


# ─────────────────────────────────────────────────────────────────────────────
#  LIGHTNING FRACTAL
# ─────────────────────────────────────────────────────────────────────────────
def draw_lightning_branch(layer, x1, y1, x2, y2, depth, width):
    if depth == 0 or width < 1:
        return
    mid_x = (x1 + x2) // 2 + random.randint(-20, 20)
    mid_y = (y1 + y2) // 2 + random.randint(-20, 20)

    bright = min(255, 100 + depth * 40)
    col = (int(bright * 0.6), int(bright * 0.9), bright)

    cv2.line(layer, (x1, y1), (mid_x, mid_y), col, width, cv2.LINE_AA)
    cv2.line(layer, (mid_x, mid_y), (x2, y2), col, width, cv2.LINE_AA)

    draw_lightning_branch(layer, x1, y1, mid_x, mid_y, depth - 1, width - 1)
    draw_lightning_branch(layer, mid_x, mid_y, x2, y2, depth - 1, width - 1)

    if depth > 2 and random.random() < 0.4:
        bx = mid_x + random.randint(-60, 60)
        by = mid_y + random.randint(-60, 60)
        draw_lightning_branch(layer, mid_x, mid_y, bx, by, depth - 2, max(1, width - 1))


# ─────────────────────────────────────────────────────────────────────────────
#  DRAW STROKE  (core per-mode brush)
# ─────────────────────────────────────────────────────────────────────────────
def draw_stroke(layer, x1, y1, x2, y2):
    global hue

    if mode == 0:  # ── PLASMA LASER
        # Outer glow
        cv2.line(layer, (x1,y1),(x2,y2), (0, 40, 80),   10, cv2.LINE_AA)
        cv2.line(layer, (x1,y1),(x2,y2), (0, 160, 255),  5, cv2.LINE_AA)
        cv2.line(layer, (x1,y1),(x2,y2), (160, 230, 255),2, cv2.LINE_AA)
        cv2.line(layer, (x1,y1),(x2,y2), (255, 255, 255), 1, cv2.LINE_AA)
        # Hot tip
        cv2.circle(layer, (x2,y2), 7, (255, 255, 255), -1)
        cv2.circle(layer, (x2,y2), 12, (0, 180, 255), 2)
        spawn_ring(x2, y2, (0, 200, 255), max_r=35, speed=4)

    elif mode == 1:  # ── NEON RAINBOW
        bgr = cv2.cvtColor(np.uint8([[[int(hue)%180, 230, 255]]]),
                           cv2.COLOR_HSV2BGR)[0][0]
        col = tuple(int(c) for c in bgr)
        dim = tuple(c // 4 for c in col)
        cv2.line(layer, (x1,y1),(x2,y2), dim, 12, cv2.LINE_AA)
        cv2.line(layer, (x1,y1),(x2,y2), col,  5, cv2.LINE_AA)
        cv2.line(layer, (x1,y1),(x2,y2), (255,255,255), 1, cv2.LINE_AA)
        cv2.circle(layer, (x2,y2), 6, (255,255,255), -1)

    elif mode == 2:  # ── FIRE INFERNO
        cv2.line(layer, (x1,y1),(x2,y2), (0, 0, 60),   12, cv2.LINE_AA)
        cv2.line(layer, (x1,y1),(x2,y2), (0, 30, 200),  7, cv2.LINE_AA)
        cv2.line(layer, (x1,y1),(x2,y2), (0, 120, 255), 4, cv2.LINE_AA)
        cv2.line(layer, (x1,y1),(x2,y2), (80, 220, 255),2, cv2.LINE_AA)
        cv2.line(layer, (x1,y1),(x2,y2), (255, 255, 200),1, cv2.LINE_AA)
        cv2.circle(layer, (x2,y2), 5, (255, 255, 255), -1)

    elif mode == 3:  # ── STARFIELD
        cv2.line(layer, (x1,y1),(x2,y2), (20,20,60), 5, cv2.LINE_AA)
        cv2.line(layer, (x1,y1),(x2,y2), (180,180,255), 2, cv2.LINE_AA)
        # 8-point star burst at tip
        for ang in range(0, 360, 45):
            rad = math.radians(ang)
            ex  = int(x2 + math.cos(rad) * 10)
            ey  = int(y2 + math.sin(rad) * 10)
            ex2 = int(x2 + math.cos(rad) * 5)
            ey2 = int(y2 + math.sin(rad) * 5)
            cv2.line(layer, (x2,y2),(ex,ey),  (255,255,255), 1, cv2.LINE_AA)
            cv2.line(layer, (x2,y2),(ex2,ey2),(180,180,255), 1, cv2.LINE_AA)
        cv2.circle(layer, (x2,y2), 4, (255,255,255), -1)
        spawn_ring(x2, y2, (200, 200, 255), max_r=20, speed=2)

    elif mode == 4:  # ── GLITCH INK
        # RGB channel split
        cv2.line(layer, (x1+6,y1),(x2+6,y2), (0, 0, 220),   3, cv2.LINE_AA)
        cv2.line(layer, (x1-6,y1),(x2-6,y2), (180, 0, 0),   3, cv2.LINE_AA)
        cv2.line(layer, (x1,y1+3),(x2,y2+3), (0, 180, 0),   2, cv2.LINE_AA)
        cv2.line(layer, (x1,y1),(x2,y2),      (255,255,255), 1, cv2.LINE_AA)
        # Glitch pixel scatter
        for _ in range(5):
            gx = x2 + random.randint(-25, 25)
            gy = y2 + random.randint(-10, 10)
            gw = random.randint(3, 14)
            col = (random.randint(0,255), 0, random.randint(150,255))
            cv2.rectangle(layer, (gx,gy), (gx+gw, gy+2), col, -1)

    elif mode == 5:  # ── LIGHTNING
        draw_lightning_branch(layer, x1, y1, x2, y2, depth=4, width=3)
        # Static core dot
        cv2.circle(layer, (x2,y2), 5, (255, 255, 180), -1)
        cv2.circle(layer, (x2,y2), 9, (100, 200, 255), 1)
        if random.random() < 0.3:
            spawn_ring(x2, y2, (200, 255, 255), max_r=25, speed=5)


# ─────────────────────────────────────────────────────────────────────────────
#  HOLOGRAPHIC ERASER
# ─────────────────────────────────────────────────────────────────────────────
def draw_eraser(frame, layer, x, y):
    cv2.circle(layer, (x,y), 30, (0,0,0), -1)
    # Visual ring on camera frame
    cv2.circle(frame, (x,y), 30, (0, 255, 180), 2, cv2.LINE_AA)
    cv2.circle(frame, (x,y), 28, (0, 120, 90), 1, cv2.LINE_AA)
    t = (math.sin(time.time() * 8) + 1) / 2
    col = (0, int(80 + 175*t), int(120 + 135*t))
    cv2.circle(frame, (x,y), 32, col, 1, cv2.LINE_AA)
    cv2.putText(frame, "ERASE", (x-22, y-36),
                cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0,255,180), 1, cv2.LINE_AA)


# ─────────────────────────────────────────────────────────────────────────────
#  SCANLINE OVERLAY (futuristic CRT effect)
# ─────────────────────────────────────────────────────────────────────────────
def apply_scanlines(frame, intensity=18):
    for y in range(0, H_CAM, 4):
        cv2.line(frame, (0,y), (W_CAM,y), (0,0,0), 1)
    # Subtle vignette
    vx = np.zeros((H_CAM, W_CAM), dtype=np.float32)
    cx, cy = W_CAM//2, H_CAM//2
    for y in range(H_CAM):
        for x in range(0, W_CAM, 80):  # sparse for speed
            d = math.sqrt((x-cx)**2 + (y-cy)**2)
            vx[y,x] = max(0, 1 - (d / max(cx,cy)) * 0.6)
    # Fast vignette using multiply on corners
    corners = [
        (slice(0,120), slice(0,200)),
        (slice(0,120), slice(W_CAM-200,W_CAM)),
        (slice(H_CAM-120,H_CAM), slice(0,200)),
        (slice(H_CAM-120,H_CAM), slice(W_CAM-200,W_CAM)),
    ]
    for s1, s2 in corners:
        frame[s1,s2] = (frame[s1,s2] * 0.6).astype(np.uint8)


# ─────────────────────────────────────────────────────────────────────────────
#  GLITCH FRAME EFFECT
# ─────────────────────────────────────────────────────────────────────────────
def apply_glitch(frame):
    for _ in range(random.randint(3, 8)):
        y     = random.randint(0, H_CAM - 1)
        h_    = random.randint(2, 10)
        shift = random.randint(-30, 30)
        strip = frame[y:y+h_, :].copy()
        frame[y:y+h_, :] = np.roll(strip, shift, axis=1)
    # Random color band
    y2 = random.randint(0, H_CAM - 20)
    frame[y2:y2+4, :, 0] = np.clip(frame[y2:y2+4, :, 0] + 80, 0, 255)


# ─────────────────────────────────────────────────────────────────────────────
#  HUD OVERLAY
# ─────────────────────────────────────────────────────────────────────────────
def draw_hud(frame, fps):
    t_now = time.time()

    # ── Top bar
    cv2.rectangle(frame, (0,0), (W_CAM, 52), (0,0,0), -1)
    cv2.rectangle(frame, (0,50), (W_CAM, 52), (0,200,255), -1)

    # Mode name with animated glow pulse
    pulse = int(180 + 75 * math.sin(t_now * 4))
    col   = (0, pulse, 255)
    cv2.putText(frame, f"NEXUS-7  //  {MODE_NAMES[mode]}",
                (16, 34), cv2.FONT_HERSHEY_SIMPLEX, 0.75, col, 2, cv2.LINE_AA)

    # FPS top-right
    cv2.putText(frame, f"FPS:{int(fps):03d}", (W_CAM-110, 34),
                cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0,255,120), 1, cv2.LINE_AA)

    # ── Bottom bar
    cv2.rectangle(frame, (0, H_CAM-46), (W_CAM, H_CAM), (0,0,0), -1)
    cv2.rectangle(frame, (0, H_CAM-46), (W_CAM, H_CAM-44), (0,200,255), -1)

    hints = "☝DRAW  ✌ERASE  🤘NEXT MODE  ✋CLEAR  [S]SAVE  [ESC]EXIT"
    cv2.putText(frame, hints, (16, H_CAM-16),
                cv2.FONT_HERSHEY_SIMPLEX, 0.42, (0,180,220), 1, cv2.LINE_AA)

    # ── Mode dots (bottom right)
    for i in range(NUM_MODES):
        dot_x = W_CAM - 24 - i * 18
        if i == mode:
            cv2.circle(frame, (dot_x, H_CAM-16), 6, (0,255,255), -1)
            cv2.circle(frame, (dot_x, H_CAM-16), 8, (0,180,200), 1)
        else:
            cv2.circle(frame, (dot_x, H_CAM-16), 4, (0,80,100), -1)

    # ── Animated corner brackets
    blen = 30
    bcol = (0, 200, 255)
    bw   = 2
    corners_pts = [
        ((0,0), (blen,0), (0,blen)),
        ((W_CAM,0), (W_CAM-blen,0), (W_CAM,blen)),
        ((0,H_CAM), (blen,H_CAM), (0,H_CAM-blen)),
        ((W_CAM,H_CAM), (W_CAM-blen,H_CAM), (W_CAM,H_CAM-blen)),
    ]
    for corner, p1, p2 in corners_pts:
        cv2.line(frame, corner, p1, bcol, bw)
        cv2.line(frame, corner, p2, bcol, bw)

    # ── Crosshair at finger tip (while drawing)
    if is_drawing:
        cx, cy = smooth_x, smooth_y
        size   = 14
        cv2.line(frame, (cx-size,cy),(cx+size,cy),(0,255,255),1,cv2.LINE_AA)
        cv2.line(frame, (cx,cy-size),(cx,cy+size),(0,255,255),1,cv2.LINE_AA)
        cv2.circle(frame, (cx,cy), 5, (255,255,255), 1, cv2.LINE_AA)

    # ── Mode switch banner
    if t_now - mode_stamp < 1.6:
        frac = 1.0 - (t_now - mode_stamp) / 1.6
        alpha_v = frac
        bh = 70
        by = H_CAM//2 - bh//2
        overlay = frame.copy()
        cv2.rectangle(overlay, (80, by), (W_CAM-80, by+bh), (0,20,40), -1)
        cv2.rectangle(overlay, (80, by), (W_CAM-80, by+1),  (0,200,255), -1)
        cv2.rectangle(overlay, (80, by+bh-1),(W_CAM-80,by+bh),(0,200,255),-1)
        cv2.addWeighted(overlay, alpha_v * 0.85, frame, 1 - alpha_v * 0.85, 0, frame)
        text_col = (0, int(255*frac), int(200*frac))
        cv2.putText(frame, f"MODE  {MODE_NAMES[mode]}",
                    (110, by + 42), cv2.FONT_HERSHEY_SIMPLEX, 0.9, text_col, 2, cv2.LINE_AA)

    # ── Gesture label flash
    if t_now - gesture_stamp < 0.8 and last_gesture:
        frac = 1.0 - (t_now - gesture_stamp) / 0.8
        col2 = (0, int(255*frac), int(180*frac))
        cv2.putText(frame, last_gesture, (W_CAM//2 - 80, 90),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.75, col2, 2, cv2.LINE_AA)

    # ── Screenshot flash
    global screenshot_flash
    if screenshot_flash > 0:
        white = np.full_like(frame, 255)
        cv2.addWeighted(white, screenshot_flash / 10.0, frame, 1 - screenshot_flash / 10.0, 0, frame)
        screenshot_flash -= 1

    # ── Animated scan line sweep
    sweep_y = int((t_now * 80) % H_CAM)
    cv2.line(frame, (0, sweep_y), (W_CAM, sweep_y), (0, 80, 120), 1)

    # ── Data stream (right side decorative)
    chars = "01"
    for row in range(6, H_CAM - 60, 18):
        if random.random() < 0.04:
            val = "".join(random.choices(chars, k=6))
            bright = random.randint(30, 80)
            cv2.putText(frame, val, (W_CAM-70, row),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.28,
                        (0, bright, bright//2), 1, cv2.LINE_AA)


# ─────────────────────────────────────────────────────────────────────────────
#  MERGE CANVAS ONTO FRAME
# ─────────────────────────────────────────────────────────────────────────────
def merge(frame, layer):
    gray = cv2.cvtColor(layer, cv2.COLOR_BGR2GRAY)
    _, mask = cv2.threshold(gray, 8, 255, cv2.THRESH_BINARY)
    mask_inv = cv2.bitwise_not(mask)
    bg = cv2.bitwise_and(frame, cv2.cvtColor(mask_inv, cv2.COLOR_GRAY2BGR))
    fg = cv2.bitwise_and(layer, cv2.cvtColor(mask,     cv2.COLOR_GRAY2BGR))
    return cv2.add(bg, fg)


# ─────────────────────────────────────────────────────────────────────────────
#  CANVAS FADE (trail persistence per mode)
# ─────────────────────────────────────────────────────────────────────────────
def fade_canvas():
    decay = MODE_DECAY[mode]
    np.multiply(canvas, decay, out=canvas, casting="unsafe")
    canvas[:] = canvas.astype(np.uint8)


# ─────────────────────────────────────────────────────────────────────────────
#  MAIN LOOP
# ─────────────────────────────────────────────────────────────────────────────
prev_time = time.time()
fps_smooth = 30.0

print("\n[NEXUS-7] Starting... Press ESC to exit.\n")

while True:
    ret, frame = cap.read()
    if not ret:
        break

    frame = cv2.flip(frame, 1)

    # ── FPS
    now      = time.time()
    raw_fps  = 1.0 / max(0.001, now - prev_time)
    fps_smooth = 0.9 * fps_smooth + 0.1 * raw_fps
    prev_time = now
    frame_count += 1

    # ── Hand detection
    rgb     = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    results = hands.process(rgb)

    if results.multi_hand_landmarks:
        for handLms in results.multi_hand_landmarks:

            lm = [(int(l.x * W_CAM), int(l.y * H_CAM))
                  for l in handLms.landmark]

            fingers = fingers_up(lm)
            fcount  = sum(fingers)
            ix, iy  = lm[8]   # index tip

            # Smooth
            smooth_x = int(ALPHA * ix + (1 - ALPHA) * smooth_x)
            smooth_y = int(ALPHA * iy + (1 - ALPHA) * smooth_y)

            # ── GESTURE: ALL 5 = CLEAR + SHOCKWAVE
            if fcount == 5:
                canvas[:] = 0
                particles.clear()
                rings.clear()
                spawn_shockwave()
                prev_x, prev_y = None, None
                last_gesture   = ">> CANVAS CLEARED <<"
                gesture_stamp  = time.time()
                is_drawing     = False

            # ── GESTURE: INDEX + PINKY = NEXT MODE
            elif fingers[1] == 1 and fingers[4] == 1 and fingers[2] == 0 and fingers[3] == 0:
                if time.time() - mode_stamp > 0.8:
                    mode       = (mode + 1) % NUM_MODES
                    mode_stamp = time.time()
                    last_gesture  = f">> {MODE_NAMES[mode]} <<"
                    gesture_stamp = time.time()
                prev_x, prev_y = None, None
                is_drawing     = False

            # ── GESTURE: INDEX + MIDDLE = ERASE
            elif fingers[1] == 1 and fingers[2] == 1 and fcount == 2:
                draw_eraser(frame, canvas, smooth_x, smooth_y)
                prev_x, prev_y = None, None
                is_drawing     = False

            # ── GESTURE: INDEX ONLY = DRAW
            elif fingers[1] == 1 and fcount == 1:
                is_drawing = True
                if prev_x is None:
                    prev_x, prev_y = smooth_x, smooth_y

                draw_stroke(canvas, prev_x, prev_y, smooth_x, smooth_y)
                spawn_particles(smooth_x, smooth_y)
                prev_x, prev_y = smooth_x, smooth_y
                hue = (hue + 3) % 180

            # ── FIST = PAUSE
            elif fcount == 0:
                prev_x, prev_y = None, None
                is_drawing     = False

            else:
                prev_x, prev_y = None, None
                is_drawing     = False

            # Draw hand skeleton (subtle)
            mp_drawing.draw_landmarks(
                frame, handLms, mp_hands.HAND_CONNECTIONS,
                mp_drawing.DrawingSpec(color=(0,80,100), thickness=1, circle_radius=2),
                mp_drawing.DrawingSpec(color=(0,150,180), thickness=1)
            )
    else:
        prev_x, prev_y = None, None
        is_drawing     = False

    # ── UPDATES
    update_particles(canvas)
    update_rings(canvas)

    # ── MERGE canvas onto frame
    frame = merge(frame, canvas)

    # ── Shockwaves on top of merged frame
    update_shockwaves(frame)

    # ── Glitch (mode 4 triggers more)
    if mode == 4 and random.random() < 0.25:
        apply_glitch(frame)
    elif random.random() < 0.015:
        apply_glitch(frame)

    # ── Show
    cv2.imshow("NEXUS-7  //  AIR DRAW TERMINAL", frame)

    # ── KEYBOARD
    key = cv2.waitKey(1) & 0xFF
    if key == 27:    # ESC
        break
    elif key == ord('c') or key == ord('C'):
        canvas[:] = 0
        particles.clear()
        spawn_shockwave()
    elif key == ord('s') or key == ord('S'):
        fname = f"nexus_draw_{int(time.time())}.png"
        cv2.imwrite(fname, frame)
        print(f"[SAVED] {fname}")
        screenshot_flash = 10
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










# OUTPUT COMMAND:
#  /opt/homebrew/bin/python3.10 hand_tracking.py       