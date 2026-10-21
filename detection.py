import os

import cv2
import numpy as np

from config import (
    ANTI_BOT_CARD_HEIGHT,
    ANTI_BOT_CARD_POS_6,
    ANTI_BOT_CARD_WIDTH,
    ANTI_BOT_CARD_POS_1,
    ANTI_BOT_CARD_POS_2,
    ANTI_BOT_CARD_POS_3,
    ANTI_BOT_CARD_POS_4,
    ANTI_BOT_CARD_POS_5,
    ANTI_BOT_CARD_POS_6,
    BOOST_TEMPLATES,
    FRIEND_INFO_REGION,
    FRIEND_INFO_TEMPLATE,
    FRIEND_COUNT_REGION,
    FRIEND_COUNT_SLASH_TEMPLATE,
    MATCH_THRESHOLD,
    RUN_BOX_SEARCH_REGION,
    RUN_BOX_TEMPLATE,
    RUN_BOX_THRESHOLD,
    STAGE_REGIONS,
    STAGE_TEMPLATES,
    TEMPLATE_DIR,
    TOP_BOOST_ON_MAX_HUE,
)


_template_cache: dict = {}
_template_gray_cache: dict = {}


def _get_template(filename):
    """Return cached template image, loading from disk on first access."""
    if filename not in _template_cache:
        path = os.path.join(TEMPLATE_DIR, filename)
        # cv2.imread cannot open non-ASCII paths on Windows (e.g. a Thai user name); decoding the bytes can.
        image = cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_UNCHANGED) if os.path.isfile(path) else None
        _template_cache[filename] = _normalize(image)
    return _template_cache[filename]


def _get_template_gray(filename):
    """Return cached grayscale template image, loading from disk on first access."""
    if filename not in _template_gray_cache:
        template = _get_template(filename)
        _template_gray_cache[filename] = cv2.cvtColor(template, cv2.COLOR_BGR2GRAY) if template is not None else None
    return _template_gray_cache[filename]


def load_templates():
    """Pre-warm the template cache with all stage and boost templates at startup."""
    for template_files in STAGE_TEMPLATES.values():
        for filename in template_files:
            _get_template_gray(filename)
    for template_files in BOOST_TEMPLATES:
        for filename in template_files:
            _get_template_gray(filename)
    for filename in RUN_BOX_TEMPLATE:
        _get_template_gray(filename)
    for filename in FRIEND_INFO_TEMPLATE:
        _get_template_gray(filename)


def _normalize(img):
    """Ensure image is BGR uint8 (3-channel). Returns None if conversion fails."""
    if img is None:
        return None
    if img.dtype != np.uint8:
        return None
    if img.ndim == 2:
        return cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    if img.ndim == 3 and img.shape[2] == 4:
        return cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
    if img.ndim == 3 and img.shape[2] == 3:
        return img
    return None


def _normalize_gray(img):
    normalized = _normalize(img)
    if normalized is None:
        return None
    return cv2.cvtColor(normalized, cv2.COLOR_BGR2GRAY)


def _crop_region(img, region):
    if region is None:
        return img
    x1, y1, x2, y2 = region
    return img[y1:y2, x1:x2]


def detect_templates(screen, template_files, region=None, threshold=MATCH_THRESHOLD):
    screen_gray = _normalize_gray(screen)
    if screen_gray is None:
        return []
    screen_gray = _crop_region(screen_gray, region)
    offset_x, offset_y = (region[0], region[1]) if region is not None else (0, 0)
    matches = []
    for filename in template_files:
        template = _get_template_gray(filename)
        if template is None:
            continue
        result = cv2.matchTemplate(screen_gray, template, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(result)
        if max_val >= threshold:
            th, tw = template.shape[:2]
            x = max_loc[0] + offset_x
            y = max_loc[1] + offset_y
            matches.append((x, y, tw, th))
    return matches


def is_friend_info_open(screen):
    """Recognize the Friend's Info title before the main menu behind it."""
    return bool(detect_templates(screen, FRIEND_INFO_TEMPLATE, FRIEND_INFO_REGION, threshold=0.9))


def find_all_templates(screen, template_files, region=None, threshold=MATCH_THRESHOLD):
    """Every non-overlapping (x, y, w, h) match above threshold, best first."""
    screen_gray = _normalize_gray(screen)
    if screen_gray is None:
        return []
    screen_gray = _crop_region(screen_gray, region)
    offset_x, offset_y = (region[0], region[1]) if region is not None else (0, 0)
    matches = []
    for filename in template_files:
        template = _get_template_gray(filename)
        if template is None or screen_gray.shape[0] < template.shape[0] or screen_gray.shape[1] < template.shape[1]:
            continue
        th, tw = template.shape[:2]
        result = cv2.matchTemplate(screen_gray, template, cv2.TM_CCOEFF_NORMED)
        while True:
            _, max_val, _, (mx, my) = cv2.minMaxLoc(result)
            if max_val < threshold:
                break
            matches.append((max_val, (mx + offset_x, my + offset_y, tw, th)))
            result[max(my - th + 1, 0):my + th, max(mx - tw + 1, 0):mx + tw] = -1
    return [box for _, box in sorted(matches, key=lambda m: -m[0])]


def find_run_box(screen):
    """Return the centre (x, y) of the in-run "?" box on screen, or None."""
    matches = detect_templates(screen, RUN_BOX_TEMPLATE, RUN_BOX_SEARCH_REGION, RUN_BOX_THRESHOLD)
    if not matches:
        return None
    x, y, w, h = matches[0]
    return (x + w // 2, y + h // 2)


def detect_stage(screen, stage_names=None, exclude=None):
    screen_gray = _normalize_gray(screen)
    if screen_gray is None:
        return None
    if stage_names is None:
        stage_names = STAGE_TEMPLATES.keys()
    if exclude:
        stage_names = [s for s in stage_names if s not in exclude]
    for stage_name in stage_names:
        template_files = STAGE_TEMPLATES.get(stage_name)
        if not template_files:
            continue
        search_area = _crop_region(screen_gray, STAGE_REGIONS.get(stage_name))
        for filename in template_files:
            template = _get_template_gray(filename)
            if template is None:
                continue
            if (
                search_area.shape[0] < template.shape[0]
                or search_area.shape[1] < template.shape[1]
            ):
                continue
            result = cv2.matchTemplate(search_area, template, cv2.TM_CCOEFF_NORMED)
            _, max_val, _, _ = cv2.minMaxLoc(result)
            if max_val >= MATCH_THRESHOLD:
                return stage_name
    return None


def is_top_boost_on(screen, region):
    crop = _crop_region(_normalize(screen), region)
    mean_hue = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)[:, :, 0].mean()
    return mean_hue < TOP_BOOST_ON_MAX_HUE


# Digits are a white fill inside a dark outline on a ~75-gray panel; a toast dims them below this, reading as not full.
_COUNT_INK_MIN_GRAY = 200
_COUNT_WIDTH_TOLERANCE = 2
# Equal numbers correlate at 1.0; width-matched numbers differing in one digit stay below 0.75.
_COUNT_MIN_CORRELATION = 0.9


def _ink_box(mask):
    ys, xs = np.nonzero(mask)
    return mask[ys.min():ys.max() + 1, xs.min():xs.max() + 1] if len(xs) else None


def is_friend_list_full(screen):
    """Whether the Friends dialog's "count/max" reads count == max, judged by comparing the two numbers' glyphs."""
    gray = _crop_region(_normalize_gray(screen), FRIEND_COUNT_REGION)
    slash = _get_template_gray(FRIEND_COUNT_SLASH_TEMPLATE)
    _, score, _, (slash_x, _) = cv2.minMaxLoc(cv2.matchTemplate(gray, slash, cv2.TM_CCOEFF_NORMED))
    if score < MATCH_THRESHOLD:
        return False
    ink = (gray > _COUNT_INK_MIN_GRAY).astype(np.uint8) * 255
    count = _ink_box(ink[:, :slash_x + 1])
    maximum = _ink_box(ink[:, slash_x + slash.shape[1] - 1:])
    if count is None or maximum is None:
        return False
    if any(abs(a - b) > _COUNT_WIDTH_TOLERANCE for a, b in zip(count.shape, maximum.shape)):
        return False
    pad = _COUNT_WIDTH_TOLERANCE + 1
    maximum = cv2.copyMakeBorder(maximum, pad, pad, pad, pad, cv2.BORDER_CONSTANT, value=0)
    return cv2.matchTemplate(maximum, count, cv2.TM_CCOEFF_NORMED).max() >= _COUNT_MIN_CORRELATION


def region_changed(before, after, region):
    """Whether region shows different content on two screens; a dim overlay alone doesn't count."""
    a, b = (_crop_region(_normalize_gray(s), region) for s in (before, after))
    return not cv2.matchTemplate(a, b, cv2.TM_CCOEFF_NORMED)[0][0] >= MATCH_THRESHOLD


def detect_anti_bot_odd_cards(screen):
    """
    Return 0-based indices of the 2 cards that differ from the majority 4.

    Strategy:
      1. Crop each card region.
      2. Build a pairwise HSV-histogram similarity matrix (6x6).
      3. For each card, compute its average similarity to all others.
      4. The 2 cards with the lowest average similarity are the odd ones.
    """

    # Define card coordinates based on config constants
    card_coords = [
        ANTI_BOT_CARD_POS_1,
        ANTI_BOT_CARD_POS_2,
        ANTI_BOT_CARD_POS_3,
        ANTI_BOT_CARD_POS_4,
        ANTI_BOT_CARD_POS_5,
        ANTI_BOT_CARD_POS_6,
    ]

    # Crop card regions as grayscale for structural comparison
    screen_bgr = _normalize(screen)
    crops = []
    for cx, cy in card_coords:
        crop = screen_bgr[cy:cy + ANTI_BOT_CARD_HEIGHT, cx:cx + ANTI_BOT_CARD_WIDTH]
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        crops.append(gray)

    # Pairwise structural similarity via normalized cross-correlation
    n = len(crops)
    sim = np.zeros((n, n), dtype=np.float32)
    for i in range(n):
        for j in range(n):
            if i != j:
                result = cv2.matchTemplate(crops[i], crops[j], cv2.TM_CCOEFF_NORMED)
                sim[i][j] = result[0][0]

    # Average similarity of each card against all others (excluding self)
    avg_sim = sim.sum(axis=1) / (n - 1)
    print("🔍 Analyzing card similarity...")
    for idx, s in enumerate(avg_sim):
        print(f"  Card {idx + 1}: similarity score {s:.2f}")

    # The 2 cards with the lowest average similarity are the odd ones
    odd_indices = list(np.argsort(avg_sim)[:2])
    return odd_indices
