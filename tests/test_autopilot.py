"""
Tests for autopilot's coordinate/key handling and its run loop.

The model, the screenshot and the mouse are all replaced with fakes here, so
running these never moves the real pointer or presses a real key.
"""
import os
import sys
import tempfile
import time
import unittest

os.environ.setdefault("APPDATA", tempfile.mkdtemp(prefix="jarvis_test_"))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    import pyautogui
    import autopilot
except Exception as e:  # pyautogui needs a desktop session
    raise unittest.SkipTest(f"pyautogui unavailable: {e}")


class HelperTests(unittest.TestCase):
    def test_normalised_coordinates_map_to_pixels(self):
        self.assertEqual(autopilot.to_pixels(500, 500, 1921, 1081), (960, 540))

    def test_coordinates_never_land_in_a_corner(self):
        # (0,0) is pyautogui's failsafe corner: a sloppy answer must not trip it
        self.assertEqual(autopilot.to_pixels(0, 0, 1920, 1080), (4, 4))
        self.assertEqual(autopilot.to_pixels(5000, -40, 1920, 1080), (1915, 4))

    def test_missing_coordinates_are_an_error(self):
        with self.assertRaises(autopilot.AutopilotError):
            autopilot.to_pixels(None, 10, 1920, 1080)

    def test_keys_are_normalised_and_validated(self):
        self.assertEqual(autopilot.parse_keys("Ctrl + Shift+Esc"), ["ctrl", "shift", "escape"])
        self.assertEqual(autopilot.parse_keys("Windows"), ["win"])
        with self.assertRaises(autopilot.AutopilotError):
            autopilot.parse_keys("ctrl+banana")
        with self.assertRaises(autopilot.AutopilotError):
            autopilot.parse_keys("")


class RunLoopTests(unittest.TestCase):
    def setUp(self):
        self._real = (autopilot.capture, autopilot.decide, autopilot.perform,
                      autopilot._jarvis_window, autopilot.SETTLE_SECONDS)
        autopilot.capture = lambda: ("", "image/jpeg", 1920, 1080)
        autopilot._jarvis_window = lambda: None
        autopilot.SETTLE_SECONDS = 0
        self.performed = []
        autopilot.perform = lambda step, w, h: self.performed.append(step["action"]) or "ok"

    def tearDown(self):
        self._wait()
        (autopilot.capture, autopilot.decide, autopilot.perform,
         autopilot._jarvis_window, autopilot.SETTLE_SECONDS) = self._real

    def _wait(self):
        deadline = time.time() + 5
        while autopilot.status()["running"] and time.time() < deadline:
            time.sleep(0.01)
        self.assertFalse(autopilot.status()["running"])

    def test_runs_until_the_model_says_done(self):
        script = iter([{"action": "hotkey", "keys": "win", "message": "open start"},
                       {"action": "type", "text": "notepad", "message": "search"},
                       {"action": "done", "message": "finished"}])
        seen_history = []

        def decide(goal, lines, shot, mime):
            seen_history.append(list(lines))
            return next(script)
        autopilot.decide = decide
        autopilot.start("open notepad")
        self._wait()
        st = autopilot.status()
        self.assertEqual(st["status"], "done")
        self.assertEqual([s["action"] for s in st["steps"]], ["hotkey", "type", "done"])
        self.assertEqual(self.performed, ["hotkey", "type"])       # "done" performs nothing
        self.assertEqual(len(seen_history[2]), 2)                  # earlier actions are fed back

    def test_step_limit_stops_a_model_that_never_finishes(self):
        autopilot.decide = lambda *a: {"action": "wait", "message": "hmm"}
        autopilot.start("loop forever")
        self._wait()
        st = autopilot.status()
        self.assertEqual(st["status"], "limit")
        self.assertEqual(len(st["steps"]), autopilot.MAX_STEPS)

    def test_stop_takes_effect_before_the_next_action(self):
        def decide(*a):
            autopilot.stop()
            return {"action": "click", "x": 1, "y": 1, "message": "about to click"}
        autopilot.decide = decide
        autopilot.start("click something")
        self._wait()
        self.assertEqual(autopilot.status()["status"], "stopped")
        self.assertEqual(self.performed, [])

    def test_failsafe_corner_aborts_the_run(self):
        autopilot.decide = lambda *a: {"action": "click", "x": 1, "y": 1, "message": "click"}

        def perform(step, w, h):
            raise pyautogui.FailSafeException("corner")
        autopilot.perform = perform
        autopilot.start("anything")
        self._wait()
        st = autopilot.status()
        self.assertEqual(st["status"], "stopped")
        self.assertIn("top-left corner", st["error"])

    def test_model_failure_ends_the_run_cleanly(self):
        def decide(*a):
            raise autopilot.AutopilotError("No API key set.")
        autopilot.decide = decide
        autopilot.start("anything")
        self._wait()
        self.assertEqual(autopilot.status()["status"], "error")

    def test_only_one_run_at_a_time(self):
        gate = {"open": False}

        def decide(*a):
            while not gate["open"]:
                time.sleep(0.01)
            return {"action": "done", "message": "ok"}
        autopilot.decide = decide
        autopilot.start("first")
        with self.assertRaises(autopilot.AutopilotError):
            autopilot.start("second")
        gate["open"] = True


if __name__ == "__main__":
    unittest.main()
