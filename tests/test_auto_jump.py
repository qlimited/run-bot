"""The box detector must not suspend random jumps for the rest of a run."""

import contextlib
import io
import threading
import time
import unittest
from unittest.mock import patch

import actions


class AutoJumpTest(unittest.TestCase):
    def test_random_jump_continues_while_box_is_still_approaching(self):
        controller = actions.JumpController()
        with contextlib.redirect_stdout(io.StringIO()):
            controller.observe_box((1200, 300), time.monotonic())
        self.assertIsNotNone(controller._plan)
        controller._next_random = time.monotonic() - 1
        result = []
        with patch.object(actions.random, "random", return_value=1.0):
            worker = threading.Thread(target=lambda: result.append(controller._next_tap()), daemon=True)
            worker.start()
            worker.join(0.5)
            with controller._cond:
                controller._stopping = True
                controller._cond.notify_all()
            worker.join(1)
        self.assertTrue(result, "random jump was delayed while the box was approaching")
        self.assertIsNotNone(result[0], "random jump was delayed while the box was approaching")
        self.assertFalse(result[0][1])
        self.assertEqual(result[0][2], 0.0)


if __name__ == "__main__":
    unittest.main()
