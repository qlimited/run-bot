import os
import time

import cv2

DEBUG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "debug_screens")


def save_debug_screen(screen):
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    filename = f"debug_screen_{timestamp}.png"
    os.makedirs(DEBUG_DIR, exist_ok=True)
    filepath = os.path.join(DEBUG_DIR, filename)
    # cv2.imwrite cannot open non-ASCII paths on Windows; writing the encoded bytes ourselves can.
    cv2.imencode(".png", screen)[1].tofile(filepath)
    print(f"💾 Saved screen to {filepath}")
