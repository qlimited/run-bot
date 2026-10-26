import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from game_stats import capture_result, get_results, parse_result_text, save_result


class GameStatsTest(unittest.TestCase):
    def test_reads_only_result_value_rows(self):
        words = [
            {"text": "Coins", "x": 0.16, "y": 0.56},
            {"text": "1,234", "x": 0.86, "y": 0.56},
            {"text": "XP", "x": 0.15, "y": 0.68},
            {"text": "567", "x": 0.86, "y": 0.68},
            {"text": "99", "x": 0.86, "y": 0.33},
        ]
        self.assertEqual(parse_result_text(words), {"coins": 1234, "xp": 567})
        self.assertIsNone(parse_result_text(words[:-2]))

    def test_persists_results_per_device(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "results.sqlite3"
            save_result("device-a", 100, 20, path)
            save_result("device-b", 300, 40, path)
            save_result("device-a", 50, 10, path)
            a = get_results("device-a", db_path=path)
            b = get_results("device-b", db_path=path)
            self.assertEqual((a["count"], a["xp_total"], a["coins_total"]), (2, 150, 30))
            self.assertEqual([entry["xp"] for entry in a["recent"]], [50, 100])
            self.assertEqual((b["count"], b["xp_total"], b["coins_total"]), (1, 300, 40))

    def test_does_not_accept_a_brief_pause_in_coin_animation(self):
        clock = [0.0]
        readings = iter([{"xp": 50, "coins": value} for value in
                         (100, 100, 100, 150, 150, 150, 150, 150, 150)])

        def sleep(seconds):
            clock[0] += seconds

        with patch("game_stats.time.monotonic", side_effect=lambda: clock[0]), \
             patch("game_stats.time.sleep", side_effect=sleep), \
             patch("game_stats.device_capture_screen", return_value=object()), \
             patch("game_stats.read_result_screen", side_effect=lambda _: next(readings)):
            self.assertEqual(capture_result("127.0.0.1", 5555), {"xp": 50, "coins": 150})


if __name__ == "__main__":
    unittest.main()
