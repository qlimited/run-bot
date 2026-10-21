import math
import random
import threading
import time
from collections import deque
from dataclasses import dataclass

from adb import device_tap, safe_device_tap, safe_device_scroll, device_capture_screen
from config import (
    ACCEPT_ALL_LIVES_RECEIVED_AND_SENT_BUTTON,
    ACCEPT_CONGRATULATIONS_BUTTON,
    ACCEPT_DAILY_CHECKIN_BOOST_SET_BUTTON,
    ACCEPT_DAILY_CHECKIN_BUTTON,
    ACCEPT_DAILY_TREASURE_BUTTON,
    ACCEPT_DAILY_NEW_BUTTON,
    ACCEPT_ENTER_LEAGUE_BUTTON,
    ACCEPT_LEAGUE_RESULTS_BUTTON,
    ACCEPT_LEVEL_UP_BUTTON,
    ACCEPT_MYSTERY_BOX_BUTTON,
    ACCEPT_OVERTAKE_BREAK_SCORE_BUTTON,
    ACCEPT_PREVIOUS_RANK_RESULTS_BUTTON,
    ACCEPT_TOO_MANY_TREASURES_BUTTON,
    ALL_LIVES_RECEIVED_AND_SENT_REGION,
    ALL_LIVES_RECEIVED_AND_SENT_TEMPLATE,
    CLOSE_ANNOUNCEMENT_DIALOG_BUTTON,
    CLOSE_SEND_LIFE_DIALOG_BUTTON,
    COMPLETE_FINISH_BUTTON,
    CONFIRM_SEND_LIFE_BUTTON,
    CONFIRM_SEND_LIFE_REGION,
    CONFIRM_SEND_LIFE_TEMPLATE,
    COOKIE_RELAY_ITEM,
    COOKIE_RELAY_USE_BUTTON,
    COOKIE_X,
    DEVICE_IP,
    DEVICE_PORT,
    EXIT_GAME_SETTINGS_BUTTON,
    EXIT_PARTY_RUN_MODE_BUTTON,
    FAST_START_ITEM,
    FAST_START_USE_BUTTON,
    FRIEND_BOTTOM_LEADERBOARD_REGION,
    FRIEND_BOTTOM_LEADERBOARD_TEMPLATE,
    FRIEND_INFO_CLOSE_BUTTON,
    FRIEND_ACCEPT_REGION,
    FRIEND_ACCEPT_TEMPLATE,
    FRIEND_ADD_PER_VISIT,
    FRIEND_ADD_REST_SECONDS,
    FRIEND_FIND_REQUEST_REGION,
    FRIEND_FIND_REQUEST_TEMPLATE,
    FRIEND_LIFE_MAX_PER_VISIT,
    FRIEND_LIFE_REST_SECONDS,
    FRIEND_LIST_CENTER,
    FRIEND_LIST_FULL_TOAST_REGION,
    FRIEND_LIST_FULL_TOAST_TEMPLATE,
    FRIEND_REJECT_REGION,
    FRIEND_REJECT_TEMPLATE,
    FRIEND_REQUEST_ROW_X,
    FRIEND_REQUEST_SENT_TOAST_REGION,
    FRIEND_REQUEST_SENT_TOAST_TEMPLATE,
    FRIENDS_BUTTON,
    FRIENDS_CLOSE_BUTTON,
    FRIENDS_FIND_REFRESH_BUTTON,
    FRIENDS_FIND_TAB,
    FRIENDS_MANAGE_REGION,
    FRIENDS_MANAGE_TEMPLATE,
    FRIENDS_REQUEST_TAB,
    FRIEND_SEND_LIFE_REGION,
    FRIEND_SEND_LIFE_TEMPLATE,
    FRIEND_TOP_LEADERBOARD_REGION,
    FRIEND_TOP_LEADERBOARD_TEMPLATE,
    INACTIVE_RELOAD_BUTTON,
    JUMP_INTERVAL_BOUNDS,
    JUMP_INTERVAL_MEDIAN,
    JUMP_INTERVAL_SIGMA,
    JUMP_MEMORY,
    JUMP_MIN_SEPARATION,
    JUMP_RISE_SECONDS,
    JUMP_TAP_REGION,
    MAIL_BOX_BUTTON,
    MAIL_BOX_LIVES_TAB_BUTTON,
    MAIL_BOX_CLOSE_BUTTON,
    MESSAGE_SENT_REGION,
    MESSAGE_SENT_TEMPLATE,
    MULTI_BUY_BUTTON,
    MULTI_PURCHASE_BUTTON,
    NO_LIVES_TO_RECEIVE_REGION,
    NO_LIVES_TO_RECEIVE_TEMPLATE,
    NO_LIVES_TO_RECEIVE_TEMPLATE,
    PLAY_BUTTON,
    PURCHASE_BUTTON,
    QUICK_RECEIVE_AND_SEND_LIVES_BUTTON,
    RANDOM_BOOST_ITEM,
    RANDOM_BOOST_REGION,
    RELIC_CLAIM_BUTTON,
    RELIC_CLOSE_BUTTON,
    RELIC_COMPLETE_BUTTON,
    RUN_BOX_DEFAULT_SPEED,
    RUN_BOX_PASS_MARGIN,
    START_BUTTON,
    CONNECTION_LOST_RELOAD_BUTTON,
    TAP_LATENCY_SECONDS,
    TOP_BOOSTS,
)
from detection import (
    detect_anti_bot_odd_cards, detect_stage, detect_templates, find_all_templates, is_friend_info_open, is_friend_list_full, is_top_boost_on,
    region_changed,
)
from config import (
    ANTI_BOT_CARD_POS_1, ANTI_BOT_CARD_POS_2, ANTI_BOT_CARD_POS_3,
    ANTI_BOT_CARD_POS_4, ANTI_BOT_CARD_POS_5, ANTI_BOT_CARD_POS_6,
    ANTI_BOT_CARD_WIDTH, ANTI_BOT_CARD_HEIGHT,
)

def start_game():
    print("🏁 Starting the game...")
    safe_device_tap(DEVICE_IP, DEVICE_PORT, START_BUTTON[0], START_BUTTON[1])
    time.sleep(random.uniform(0.8, 1.4))


def play_game():
    print("🎮 Playing the game...")
    safe_device_tap(DEVICE_IP, DEVICE_PORT, PLAY_BUTTON[0], PLAY_BUTTON[1])
    time.sleep(random.uniform(0.8, 1.4))


def set_top_boosts(wanted):
    screen = device_capture_screen(DEVICE_IP, DEVICE_PORT)
    for key, name, (x, y), region in TOP_BOOSTS:
        current = "ON" if is_top_boost_on(screen, region) else "OFF"
        target = "ON" if wanted[key] else "OFF"
        if current == target:
            print(f"🧪 {name}: {current}")
            continue
        print(f"🧪 {name}: {current} → {target}")
        safe_device_tap(DEVICE_IP, DEVICE_PORT, x, y)
        time.sleep(random.uniform(0.8, 1.4))


@dataclass
class _Box:
    x: int
    seen_at: float
    handled: bool = False


def _jump_interval():
    low, high = JUMP_INTERVAL_BOUNDS
    return min(max(random.lognormvariate(math.log(JUMP_INTERVAL_MEDIAN), JUMP_INTERVAL_SIGMA), low), high)


def _random_jump_point(recent):
    x1, y1, x2, y2 = JUMP_TAP_REGION
    best, best_gap = None, -1.0
    for _ in range(50):
        point = (random.randint(x1, x2), random.randint(y1, y2))
        gap = min((math.dist(point, p) for p in recent), default=math.inf)
        if gap >= JUMP_MIN_SEPARATION:
            return point
        if gap > best_gap:
            best, best_gap = point, gap
    return best


class JumpController:
    """The only source of jump taps during a run: random left-side jumps, plus one timed jump per reachable box."""

    def __init__(self):
        self._cond = threading.Condition()
        self._stopping = False
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._recent = deque(maxlen=JUMP_MEMORY)
        self._next_random = 0.0
        self._hold_until = 0.0
        self._box = None
        self._plan = None  # (fire_at, box)

    def start(self):
        self._next_random = time.monotonic() + _jump_interval()
        self._thread.start()

    def stop(self):
        with self._cond:
            self._stopping = True
            self._cond.notify()
        self._thread.join()

    def observe_box(self, center, seen_at):
        """Feed one screenshot's box sighting (None when absent); seen_at is when the capture was requested."""
        if center is None:
            return
        cx, cy = center
        with self._cond:
            box = self._box
            is_new = box is None or cx > box.x + 250 or seen_at - box.seen_at > 1.5
            speed = RUN_BOX_DEFAULT_SPEED
            if is_new:
                box = self._box = _Box(cx, seen_at)
            else:
                dx, dt = box.x - cx, seen_at - box.seen_at
                if dx > 0 and dt > 0:
                    speed = dx / dt
                box.x, box.seen_at = cx, seen_at
            arrival = seen_at + (cx - COOKIE_X) / speed
            self._hold_until = max(self._hold_until, arrival + RUN_BOX_PASS_MARGIN)

            # Boxes bob between y≈195 and 413, always above a standing cookie, so every box needs a jump.
            # Peaking at arrival sweeps the cookie through that whole band while the box overlaps it.
            if not box.handled:
                now = time.monotonic()
                if arrival > now:
                    self._plan = (max(arrival - JUMP_RISE_SECONDS - TAP_LATENCY_SECONDS, now), box)
                else:
                    box.handled = True
            self._cond.notify()
        if is_new:
            print(f"📦 Box spotted at ({cx}, {cy}), holding random jumps")

    def _take_point(self):
        point = _random_jump_point(self._recent)
        self._recent.append(point)
        return point

    def _next_tap(self):
        """Block until a tap is due. Returns (point, for_box), or None once stopping."""
        with self._cond:
            while not self._stopping:
                now = time.monotonic()
                if self._plan and now >= self._plan[0]:
                    self._plan[1].handled = True
                    self._plan = None
                    return self._take_point(), True
                if now >= self._next_random:
                    self._next_random = now + _jump_interval()
                    if now >= self._hold_until:
                        return self._take_point(), False
                    continue
                due = self._next_random if self._plan is None else min(self._next_random, self._plan[0])
                self._cond.wait(due - now)
            return None

    def _run(self):
        while tap := self._next_tap():
            point, for_box = tap
            if for_box:
                print("📦 Jump for box")
            device_tap(DEVICE_IP, DEVICE_PORT, *point)


def purchase_fast_start():
    print("🛒 Purchasing Fast Start...")
    safe_device_tap(DEVICE_IP, DEVICE_PORT, FAST_START_ITEM[0], FAST_START_ITEM[1])
    time.sleep(random.uniform(0.8, 1.4))
    safe_device_tap(DEVICE_IP, DEVICE_PORT, PURCHASE_BUTTON[0], PURCHASE_BUTTON[1])
    time.sleep(random.uniform(1, 2))


def purchase_cookie_relay():
    print("🛒 Purchasing Cookie Relay...")
    safe_device_tap(DEVICE_IP, DEVICE_PORT, COOKIE_RELAY_ITEM[0], COOKIE_RELAY_ITEM[1])
    time.sleep(random.uniform(0.8, 1.4))
    safe_device_tap(DEVICE_IP, DEVICE_PORT, PURCHASE_BUTTON[0], PURCHASE_BUTTON[1])
    time.sleep(random.uniform(1, 2))


def purchase_random_boost():
    print("🛒 Purchasing Random Boost...")
    safe_device_tap(DEVICE_IP, DEVICE_PORT, RANDOM_BOOST_ITEM[0], RANDOM_BOOST_ITEM[1])
    time.sleep(random.uniform(0.8, 1.4))
    safe_device_tap(DEVICE_IP, DEVICE_PORT, PURCHASE_BUTTON[0], PURCHASE_BUTTON[1])
    time.sleep(random.uniform(1, 2))


def purchase_desired_random_boost(desired_template, desired_name):
    print("🛒 Purchasing Desired Random Boost...")
    safe_device_tap(DEVICE_IP, DEVICE_PORT, RANDOM_BOOST_ITEM[0], RANDOM_BOOST_ITEM[1])
    time.sleep(random.uniform(0.8, 1.4))
    safe_device_tap(DEVICE_IP, DEVICE_PORT, MULTI_PURCHASE_BUTTON[0], MULTI_PURCHASE_BUTTON[1])
    time.sleep(random.uniform(1, 2))
    safe_device_tap(DEVICE_IP, DEVICE_PORT, MULTI_BUY_BUTTON[0], MULTI_BUY_BUTTON[1])
    time.sleep(random.uniform(0.8, 1.4))
    print(f"🔍 Waiting for desired boost to be detected: {desired_name}...")
    timeout = 30
    start_time = time.time()
    while True:
        if time.time() - start_time > timeout:
            print(f"⏰ Timeout: Could not detect desired boost '{desired_name}' within {timeout} seconds.")
            print("⚠️ Skipping Desired Random Boost. Please verify your in-game boost config is correct.")
            return
        screen = device_capture_screen(DEVICE_IP, DEVICE_PORT)
        if detect_templates(screen, desired_template, RANDOM_BOOST_REGION):
            print(f"✅ Desired Boost detected: {desired_name}!")
            break
        time.sleep(0.5)


def using_fast_start():
    print("⚡ Using Fast Start...")
    safe_device_tap(DEVICE_IP, DEVICE_PORT, FAST_START_USE_BUTTON[0], FAST_START_USE_BUTTON[1])
    time.sleep(random.uniform(0.8, 1.2))


def using_cookie_relay():
    print("🍪 Using Cookie Relay...")
    safe_device_tap(DEVICE_IP, DEVICE_PORT, COOKIE_RELAY_USE_BUTTON[0], COOKIE_RELAY_USE_BUTTON[1])
    time.sleep(random.uniform(0.8, 1.2))


def complete_finish():
    print("🏆 Completing the game...")
    safe_device_tap(DEVICE_IP, DEVICE_PORT, COMPLETE_FINISH_BUTTON[0], COMPLETE_FINISH_BUTTON[1])
    time.sleep(random.uniform(0.8, 1.4))


def accept_mystery_box():
    print("🎁 Accepting Mystery Box...")
    safe_device_tap(DEVICE_IP, DEVICE_PORT, ACCEPT_MYSTERY_BOX_BUTTON[0], ACCEPT_MYSTERY_BOX_BUTTON[1])
    time.sleep(random.uniform(0.8, 1.4))


def accept_congratulations():
    print("🎉 Accepting Congratulations...")
    safe_device_tap(DEVICE_IP, DEVICE_PORT, ACCEPT_CONGRATULATIONS_BUTTON[0], ACCEPT_CONGRATULATIONS_BUTTON[1])
    time.sleep(random.uniform(0.8, 1.4))


def accept_level_up():
    print("⬆️ Accepting Level Up...")
    safe_device_tap(DEVICE_IP, DEVICE_PORT, ACCEPT_LEVEL_UP_BUTTON[0], ACCEPT_LEVEL_UP_BUTTON[1])
    time.sleep(random.uniform(0.8, 1.4))


def accept_daily_checkin():
    print("📅 Accepting Daily Check-in...")
    safe_device_tap(DEVICE_IP, DEVICE_PORT, ACCEPT_DAILY_CHECKIN_BUTTON[0], ACCEPT_DAILY_CHECKIN_BUTTON[1])
    time.sleep(random.uniform(0.8, 1.4))


def accept_daily_checkin_boost_set():
    print("📅 Accepting Daily Check-in Boost Set...")
    safe_device_tap(DEVICE_IP, DEVICE_PORT, ACCEPT_DAILY_CHECKIN_BOOST_SET_BUTTON[0], ACCEPT_DAILY_CHECKIN_BOOST_SET_BUTTON[1])
    time.sleep(random.uniform(0.8, 1.4))


def accept_daily_treasure():
    print("💎 Accepting Daily Treasure...")
    safe_device_tap(DEVICE_IP, DEVICE_PORT, ACCEPT_DAILY_TREASURE_BUTTON[0], ACCEPT_DAILY_TREASURE_BUTTON[1])
    time.sleep(random.uniform(0.8, 1.4))


def accept_daily_new():
    print("📰 Accepting Daily New...")
    safe_device_tap(DEVICE_IP, DEVICE_PORT, ACCEPT_DAILY_NEW_BUTTON[0], ACCEPT_DAILY_NEW_BUTTON[1])
    time.sleep(random.uniform(0.8, 1.4))


def accept_enter_league():
    print("🏆 Accepting Enter League...")
    safe_device_tap(DEVICE_IP, DEVICE_PORT, ACCEPT_ENTER_LEAGUE_BUTTON[0], ACCEPT_ENTER_LEAGUE_BUTTON[1])
    time.sleep(random.uniform(0.8, 1.4))


def accept_league_results():
    print("🏆 Accepting League Results...")
    safe_device_tap(DEVICE_IP, DEVICE_PORT, ACCEPT_LEAGUE_RESULTS_BUTTON[0], ACCEPT_LEAGUE_RESULTS_BUTTON[1])
    time.sleep(random.uniform(0.8, 1.4))


def accept_previous_rank_results():
    print("🏆 Accepting Previous Rank Results...")
    safe_device_tap(DEVICE_IP, DEVICE_PORT, ACCEPT_PREVIOUS_RANK_RESULTS_BUTTON[0], ACCEPT_PREVIOUS_RANK_RESULTS_BUTTON[1])
    time.sleep(random.uniform(0.8, 1.4))

def accept_too_many_treasures():
    print("💎 Accepting Too Many Treasures...")
    safe_device_tap(DEVICE_IP, DEVICE_PORT, ACCEPT_TOO_MANY_TREASURES_BUTTON[0], ACCEPT_TOO_MANY_TREASURES_BUTTON[1])
    time.sleep(random.uniform(0.8, 1.4))

def accept_overtake_break_score():
    print("🏆 Accepting Overtake Break Score...")
    safe_device_tap(DEVICE_IP, DEVICE_PORT, ACCEPT_OVERTAKE_BREAK_SCORE_BUTTON[0], ACCEPT_OVERTAKE_BREAK_SCORE_BUTTON[1])
    time.sleep(random.uniform(0.8, 1.4))

def open_relic_complete():
    print("🏺 Opening Relic Complete...")
    safe_device_tap(DEVICE_IP, DEVICE_PORT, RELIC_COMPLETE_BUTTON[0], RELIC_COMPLETE_BUTTON[1])
    time.sleep(random.uniform(0.8, 1.4))


def accept_relic_claim():
    print("🏺 Accepting Relic Claim...")
    safe_device_tap(DEVICE_IP, DEVICE_PORT, RELIC_CLAIM_BUTTON[0], RELIC_CLAIM_BUTTON[1])
    time.sleep(random.uniform(0.8, 1.4))
    safe_device_tap(DEVICE_IP, DEVICE_PORT, RELIC_CLOSE_BUTTON[0], RELIC_CLOSE_BUTTON[1])
    time.sleep(random.uniform(10, 15))


def handle_anti_bot(screen):
    print("🤖 Solving Anti-Bot captcha...")
    card_coords = [
        ANTI_BOT_CARD_POS_1, ANTI_BOT_CARD_POS_2, ANTI_BOT_CARD_POS_3,
        ANTI_BOT_CARD_POS_4, ANTI_BOT_CARD_POS_5, ANTI_BOT_CARD_POS_6,
    ]

    odd_indices = detect_anti_bot_odd_cards(screen)
    card_nums = [i + 1 for i in odd_indices]
    print(f"🃏 Found odd cards: Card {card_nums[0]} and Card {card_nums[1]}")

    for idx in odd_indices:
        cx, cy = card_coords[idx]
        # random tap position inside the card, with a small margin
        margin = 20
        tx = random.randint(cx + margin, cx + ANTI_BOT_CARD_WIDTH - margin)
        ty = random.randint(cy + margin, cy + ANTI_BOT_CARD_HEIGHT - margin)
        print(f"  👆 Tapping Card {idx + 1} at ({tx}, {ty})")
        safe_device_tap(DEVICE_IP, DEVICE_PORT, tx, ty)
        time.sleep(random.uniform(10, 15))

    print("✅ Anti-Bot captcha solved!")
    time.sleep(random.uniform(0.8, 1.4))


def handle_connection_lost():
    print("🔌 Handling Connection Lost...")
    safe_device_tap(DEVICE_IP, DEVICE_PORT, CONNECTION_LOST_RELOAD_BUTTON[0], CONNECTION_LOST_RELOAD_BUTTON[1])
    time.sleep(random.uniform(10, 15))


def handle_inactive():
    print("💤 Handling Inactive state...")
    safe_device_tap(DEVICE_IP, DEVICE_PORT, INACTIVE_RELOAD_BUTTON[0], INACTIVE_RELOAD_BUTTON[1])
    time.sleep(random.uniform(10, 15))


_FRIEND_LIST_TOP_SWIPES = 25
# Enough to cover a 70+ friend list end to end in case the game scrolls it back to the top between games.
_FRIEND_LIST_SCAN_SWIPES = 35
_DIALOG_TIMEOUT = 3.0


def _capture():
    return device_capture_screen(DEVICE_IP, DEVICE_PORT)


def _on_main_menu(screen):
    return not is_friend_info_open(screen) and detect_stage(screen, ["MAINMENU"]) == "MAINMENU"


def close_friend_info():
    """Dismiss Friend's Info and verify that the unobstructed main menu returns."""
    for _ in range(2):
        if not is_friend_info_open(_capture()):
            return _on_main_menu(_capture())
        safe_device_tap(DEVICE_IP, DEVICE_PORT, *FRIEND_INFO_CLOSE_BUTTON)
        if _wait_for(_on_main_menu):
            return True
    return False


def _wait_for(predicate, timeout=_DIALOG_TIMEOUT):
    deadline = time.monotonic() + timeout
    while not predicate(_capture()):
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.3)
    return True


def _swipe_friend_list(toward_top, travel, duration):
    x, y = FRIEND_LIST_CENTER
    # safe_device_scroll swipes 2 * distance centred on (x, y), so the finger stays inside the list.
    safe_device_scroll(DEVICE_IP, DEVICE_PORT, x, y, "down" if toward_top else "up", travel // 2, duration)
    time.sleep(random.uniform(0.8, 1.4))


def _send_life_to(button):
    """Tap one friend's send button and step through both dialogs. Returns why it failed, or None."""
    x, y, w, h = button
    safe_device_tap(DEVICE_IP, DEVICE_PORT, x + w // 2, y + h // 2)
    if not _wait_for(lambda s: detect_templates(s, CONFIRM_SEND_LIFE_TEMPLATE, CONFIRM_SEND_LIFE_REGION)):
        return "send dialog did not open"
    time.sleep(random.uniform(0.8, 1.4))
    safe_device_tap(DEVICE_IP, DEVICE_PORT, *CONFIRM_SEND_LIFE_BUTTON)
    if not _wait_for(lambda s: detect_templates(s, MESSAGE_SENT_TEMPLATE, MESSAGE_SENT_REGION)):
        return "message-sent dialog did not open"
    time.sleep(random.uniform(0.8, 1.4))
    safe_device_tap(DEVICE_IP, DEVICE_PORT, *CLOSE_SEND_LIFE_DIALOG_BUTTON)
    if not _wait_for(_on_main_menu):
        return "main menu did not come back"
    time.sleep(random.uniform(0.8, 1.4))
    return None


class FriendLifeSender:
    """Sends a few lives from the main-menu friend list per visit, resuming the scan where the last visit stopped."""

    def __init__(self):
        self.restart_from_top = True
        self._rest_until = 0.0

    def run(self):
        """One main-menu visit. Returns whether the screen is still on the main menu afterwards."""
        if time.monotonic() < self._rest_until:
            return True
        sent, outcome = self._visit(FRIEND_LIFE_MAX_PER_VISIT)
        print(f"💌 Friend lives: sent {sent} this visit, {outcome}")
        return _on_main_menu(_capture())

    def _visit(self, limit):
        if self.restart_from_top:
            for _ in range(_FRIEND_LIST_TOP_SWIPES):
                screen = _capture()
                if not _on_main_menu(screen):
                    return 0, "left the main menu"
                if detect_templates(screen, FRIEND_TOP_LEADERBOARD_TEMPLATE, FRIEND_TOP_LEADERBOARD_REGION):
                    break
                _swipe_friend_list(toward_top=True, travel=340, duration=250)
            else:
                print("⚠️ Friend list top not found, scanning from here")
            self.restart_from_top = False

        sent = 0
        swipes = 0
        while sent < limit:
            screen = _capture()
            if not _on_main_menu(screen):
                return sent, "left the main menu"
            buttons = find_all_templates(screen, FRIEND_SEND_LIFE_TEMPLATE, FRIEND_SEND_LIFE_REGION)
            if buttons:
                failure = _send_life_to(random.choice(buttons))
                if failure:
                    return sent, failure
                sent += 1
                print(f"💌 Sent life ({sent}/{limit})")
            elif detect_templates(screen, FRIEND_BOTTOM_LEADERBOARD_TEMPLATE, FRIEND_BOTTOM_LEADERBOARD_REGION):
                self._rest_until = time.monotonic() + FRIEND_LIFE_REST_SECONDS
                self.restart_from_top = True
                return sent, f"everyone sent, resting {FRIEND_LIFE_REST_SECONDS // 60} min"
            elif swipes == _FRIEND_LIST_SCAN_SWIPES:
                return sent, "scroll limit reached"
            else:
                swipes += 1
                # A button stays fully inside FRIEND_SEND_LIFE_REGION over ~287 px of scroll; shorter swipes never skip one.
                _swipe_friend_list(toward_top=False, travel=random.randint(200, 260), duration=random.randint(400, 600))
        return sent, "visit limit reached"


_TOAST_TIMEOUT = 2.5
# Every Request-tab pass adds a friend, removes a full requester's row, or ends the visit; this caps the removals.
_REQUEST_TAB_PASSES = 10
_SAME_ROW_PX = 15


def _centre(box):
    x, y, w, h = box
    return x + w // 2, y + h // 2


def _tap(point):
    safe_device_tap(DEVICE_IP, DEVICE_PORT, *point)


def _showing(template, region):
    return lambda screen: bool(detect_templates(screen, template, region))


_friends_dialog_open = _showing(FRIENDS_MANAGE_TEMPLATE, FRIENDS_MANAGE_REGION)
_list_full_toast = _showing(FRIEND_LIST_FULL_TOAST_TEMPLATE, FRIEND_LIST_FULL_TOAST_REGION)
_request_sent_toast = _showing(FRIEND_REQUEST_SENT_TOAST_TEMPLATE, FRIEND_REQUEST_SENT_TOAST_REGION)


def _reject_full_requester(accept):
    """Reject the request whose Accept just showed the full-list toast. Returns why it failed, or None."""
    if not _wait_for(lambda s: not _list_full_toast(s)):
        return "full-list toast did not clear"
    screen = _capture()
    accept_y = _centre(accept)[1]
    rejects = [r for r in find_all_templates(screen, FRIEND_REJECT_TEMPLATE, FRIEND_REJECT_REGION)
               if abs(_centre(r)[1] - accept_y) <= _SAME_ROW_PX]
    if not rejects:
        return "no Reject on the full requester's row"
    _, y, _, h = accept
    row = (FRIEND_REQUEST_ROW_X[0], y, FRIEND_REQUEST_ROW_X[1], y + h)
    _tap(_centre(rejects[0]))
    # The rows below shift up into the removed one, so its picture changes whether or not another request follows.
    if not _wait_for(lambda s: region_changed(screen, s, row), _TOAST_TIMEOUT):
        return "rejected request did not go away"
    print("🤝 Rejected request from a full friend list")
    time.sleep(random.uniform(0.8, 1.4))
    return None


def _leave_friends_dialog():
    """Close the Friends dialog if it is up. Returns whether the main menu is back."""
    for _ in range(2):
        if not _friends_dialog_open(_capture()):
            break
        _tap(FRIENDS_CLOSE_BUTTON)
        time.sleep(random.uniform(0.8, 1.4))
    return _wait_for(_on_main_menu)


class FriendAdder:
    """Accepts incoming friend requests, then sends new ones from the Find tab, a few per main-menu visit."""

    def __init__(self):
        self._rest_until = 0.0

    def run(self):
        """One main-menu visit. Returns whether the screen is back on the main menu afterwards."""
        if time.monotonic() < self._rest_until:
            return True
        target = random.randint(*FRIEND_ADD_PER_VISIT)
        _tap(FRIENDS_BUTTON)
        if _wait_for(_friends_dialog_open):
            added, outcome = self._visit(target)
        else:
            added, outcome = 0, "friends dialog did not open"
        print(f"🤝 Friends: added {added}/{target} this visit, {outcome}")
        return _leave_friends_dialog()

    def _blocked(self, screen):
        if is_friend_info_open(screen):
            return "friend info open"
        if not _friends_dialog_open(screen):
            return "friends dialog closed"
        if is_friend_list_full(screen):
            self._rest_until = time.monotonic() + FRIEND_ADD_REST_SECONDS
            return f"friend list full, resting {FRIEND_ADD_REST_SECONDS // 60} min"
        return None

    def _visit(self, target):
        time.sleep(random.uniform(0.8, 1.4))
        failure = self._blocked(_capture())
        if failure:
            return 0, failure

        added = 0
        _tap(FRIENDS_REQUEST_TAB)
        time.sleep(random.uniform(0.8, 1.4))
        for _ in range(_REQUEST_TAB_PASSES):
            screen = _capture()
            failure = self._blocked(screen)
            if failure:
                return added, failure
            accepts = find_all_templates(screen, FRIEND_ACCEPT_TEMPLATE, FRIEND_ACCEPT_REGION)
            if not accepts:
                break
            accept = min(accepts, key=lambda box: box[1])
            _tap(_centre(accept))
            if _wait_for(_list_full_toast, _TOAST_TIMEOUT):
                failure = _reject_full_requester(accept)
                if failure:
                    return added, failure
                continue
            added += 1
            print(f"🤝 Accepted friend request ({added}/{target})")
            if added == target:
                return added, "visit target reached"
            time.sleep(random.uniform(0.8, 1.4))

        _tap(FRIENDS_FIND_TAB)
        time.sleep(random.uniform(0.8, 1.4))
        refreshed = False
        while added < target:
            screen = _capture()
            failure = self._blocked(screen)
            if failure:
                return added, failure
            buttons = find_all_templates(screen, FRIEND_FIND_REQUEST_TEMPLATE, FRIEND_FIND_REQUEST_REGION)
            if not buttons:
                if refreshed:
                    return added, "no one left to request"
                refreshed = True
                _tap(FRIENDS_FIND_REFRESH_BUTTON)
                time.sleep(random.uniform(1.5, 2.5))
                continue
            _tap(_centre(random.choice(buttons)))
            if not _wait_for(_request_sent_toast, _TOAST_TIMEOUT):
                return added, "friend request not confirmed"
            added += 1
            print(f"🤝 Sent friend request ({added}/{target})")
            if not _wait_for(lambda s: not _request_sent_toast(s)):
                return added, "request-sent toast did not clear"
            time.sleep(random.uniform(0.8, 1.4))
        return added, "visit target reached"


def handle_quick_receive_and_send_lives():
    print("✉️ Handling Quick Receive and Send Lives...")
    time.sleep(random.uniform(0.8, 1.4))
    # Tap the "Mail" button
    safe_device_tap(DEVICE_IP, DEVICE_PORT, MAIL_BOX_BUTTON[0], MAIL_BOX_BUTTON[1])
    time.sleep(random.uniform(0.8, 1.4))
    # Tap the "Lives" tab
    safe_device_tap(DEVICE_IP, DEVICE_PORT, MAIL_BOX_LIVES_TAB_BUTTON[0], MAIL_BOX_LIVES_TAB_BUTTON[1])
    time.sleep(random.uniform(0.8, 1.4))
    screen = device_capture_screen(DEVICE_IP, DEVICE_PORT)
    # No lives to receive
    if detect_templates(screen, NO_LIVES_TO_RECEIVE_TEMPLATE, NO_LIVES_TO_RECEIVE_REGION):
        print("✉️ No lives to receive. Proceeding to send lives...")
        # Close the mail dialog
        safe_device_tap(DEVICE_IP, DEVICE_PORT, MAIL_BOX_CLOSE_BUTTON[0], MAIL_BOX_CLOSE_BUTTON[1])
        return
    # Receive all lives
    print("✉️ Receiving all lives...")
    safe_device_tap(DEVICE_IP, DEVICE_PORT, QUICK_RECEIVE_AND_SEND_LIVES_BUTTON[0], QUICK_RECEIVE_AND_SEND_LIVES_BUTTON[1])
    time.sleep(random.uniform(0.8, 1.4))
    # Tap all send life buttons
    while True:
        # Check if all lifes received and sent!, so break the loop
        screen = device_capture_screen(DEVICE_IP, DEVICE_PORT)
        all_lives_received_and_sent = detect_templates(screen, ALL_LIVES_RECEIVED_AND_SENT_TEMPLATE, ALL_LIVES_RECEIVED_AND_SENT_REGION)
        if all_lives_received_and_sent:
            print("✉️ All lives received and sent. Done!")
            # Tap the "Confirm" button
            safe_device_tap(DEVICE_IP, DEVICE_PORT, ACCEPT_ALL_LIVES_RECEIVED_AND_SENT_BUTTON[0], ACCEPT_ALL_LIVES_RECEIVED_AND_SENT_BUTTON[1])
            time.sleep(random.uniform(0.8, 1.4))
            # Close the mail dialog
            safe_device_tap(DEVICE_IP, DEVICE_PORT, MAIL_BOX_CLOSE_BUTTON[0], MAIL_BOX_CLOSE_BUTTON[1])
            time.sleep(random.uniform(0.8, 1.4))
            break
        # Send lifes to friends
        confirm_send_life_button_coords = detect_templates(screen, CONFIRM_SEND_LIFE_TEMPLATE, CONFIRM_SEND_LIFE_REGION)
        if confirm_send_life_button_coords:
            print("✉️ Sending lives to friends...")
            safe_device_tap(DEVICE_IP, DEVICE_PORT, CONFIRM_SEND_LIFE_BUTTON[0], CONFIRM_SEND_LIFE_BUTTON[1])
            time.sleep(random.uniform(0.8, 1.4))
    print("✉️ Quick Receive and Send Lives completed.")


def close_announcement_dialog():
    print("🖱️ Closing announcement dialog...")
    for i in range(5):
        print(f"🖱️ Tapping close announcement dialog button {i+1}/5")
        safe_device_tap(DEVICE_IP, DEVICE_PORT, CLOSE_ANNOUNCEMENT_DIALOG_BUTTON[0], CLOSE_ANNOUNCEMENT_DIALOG_BUTTON[1])
        time.sleep(random.uniform(0.8, 1.4))
    time.sleep(random.uniform(0.8, 1.4))
    device_screen = device_capture_screen(DEVICE_IP, DEVICE_PORT)
    if detect_stage(device_screen, ["PARTY_RUN"]) == "PARTY_RUN":
        close_party_run_mode()
    elif detect_stage(device_screen, ["GAME_SETTINGS"]) == "GAME_SETTINGS":
        close_game_settings()


def close_party_run_mode():
    print("🖱️ Closing Party Run mode...")
    safe_device_tap(DEVICE_IP, DEVICE_PORT, EXIT_PARTY_RUN_MODE_BUTTON[0], EXIT_PARTY_RUN_MODE_BUTTON[1])
    time.sleep(random.uniform(0.8, 1.4))


def close_game_settings():
    print("🖱️ Closing Game Settings...")
    safe_device_tap(DEVICE_IP, DEVICE_PORT, EXIT_GAME_SETTINGS_BUTTON[0], EXIT_GAME_SETTINGS_BUTTON[1])
    time.sleep(random.uniform(0.8, 1.4))
