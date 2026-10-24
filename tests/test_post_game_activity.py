"""Post-game Gift Draw and heart-visit scheduling without a device."""

import contextlib
import io
import unittest
from unittest.mock import patch

import bot


class FriendLives:
    def __init__(self, calls):
        self.calls = calls

    def run(self):
        self.calls.append("friends")
        return True


class PostGameActivityTest(unittest.TestCase):
    def test_gifts_and_friend_hearts_alternate(self):
        calls = []
        friends = FriendLives(calls)
        with patch.object(bot, "draw_gifts", side_effect=lambda max_gifts: calls.append(("gifts", max_gifts))), \
             patch.object(bot, "handle_quick_receive_and_send_lives", side_effect=lambda: calls.append("mail")), \
             contextlib.redirect_stdout(io.StringIO()):
            next_task = "gifts"
            for _ in range(4):
                next_task, used_mailbox = bot.run_post_game_activity(next_task, friends, False)
                self.assertFalse(used_mailbox)
        self.assertEqual(calls, [("gifts", 5), "friends", ("gifts", 5), "friends"])

    def test_due_mailbox_uses_heart_turn_only(self):
        calls = []
        with patch.object(bot, "draw_gifts", side_effect=lambda max_gifts: calls.append(("gifts", max_gifts))), \
             patch.object(bot, "handle_quick_receive_and_send_lives", side_effect=lambda: calls.append("mail")), \
             contextlib.redirect_stdout(io.StringIO()):
            next_task, used_mailbox = bot.run_post_game_activity("gifts", FriendLives(calls), True)
            self.assertEqual((next_task, used_mailbox), ("hearts", False))
            next_task, used_mailbox = bot.run_post_game_activity(next_task, FriendLives(calls), True)
        self.assertEqual((next_task, used_mailbox), ("gifts", True))
        self.assertEqual(calls, [("gifts", 5), "mail"])

    def test_disabled_hearts_only_draws_gifts_even_when_mailbox_is_due(self):
        calls = []
        friends = FriendLives(calls)
        with patch.object(bot, "draw_gifts", side_effect=lambda max_gifts: calls.append(("gifts", max_gifts))), \
             patch.object(bot, "handle_quick_receive_and_send_lives", side_effect=lambda: calls.append("mail")), \
             contextlib.redirect_stdout(io.StringIO()):
            next_task = "gifts"
            for _ in range(3):
                next_task, used_mailbox = bot.run_post_game_activity(next_task, friends, True, False)
                self.assertEqual(next_task, "gifts")
                self.assertFalse(used_mailbox)
        self.assertEqual(calls, [("gifts", 5)] * 3)


if __name__ == "__main__":
    unittest.main()
