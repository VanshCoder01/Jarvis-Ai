"""
Tests for simulation mode: the virtual PC and the offline command core.

Run from the project folder with:  python -m unittest discover tests

APPDATA is pointed at a throwaway folder before anything is imported, so
these never read or write your real jarvis_memory.json.
"""
import os
import sys
import tempfile
import unittest

_TMP = tempfile.mkdtemp(prefix="jarvis_test_")
os.environ["APPDATA"] = _TMP
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import simulator  # noqa: E402


class OfflineBrainTests(unittest.TestCase):
    CASES = [
        ("open chrome", "open_app", {"app": "chrome"}),
        ("Jarvis, please open the calculator", "open_app", {"app": "calculator"}),
        ("open youtube", "open_url", {"url": "youtube.com"}),
        ("go to github.com/torvalds", "open_url", {"url": "github.com/torvalds"}),
        ("open my downloads folder", "open_folder", {"text": "downloads"}),
        ("close notepad", "close_app", {"app": "notepad"}),
        ("play lo-fi beats on youtube", "play_on_youtube", {"query": "lo-fi beats"}),
        ("pause", "media_control", {"text": "pause"}),
        ("volume up", "set_volume", {"direction": "up"}),
        ("turn the volume down", "set_volume", {"direction": "down"}),
        ("mute", "mute", {}),
        ("set brightness to 40", "set_brightness", {"level": 40}),
        ("dim the screen", "set_brightness", {"direction": "down"}),
        ("take a screenshot", "screenshot", {}),
        ("what time is it", "get_time", {}),
        ("how's my pc doing", "get_stats", {}),
        ("lock my pc", "lock_pc", {}),
        ("shut down", "shutdown_pc", {}),
        ("cancel shutdown", "cancel_shutdown", {}),
        ("restart the computer", "restart_pc", {}),
        ("type Hello World", "type_text", {"text": "Hello World"}),
        ("press enter", "press_key", {"key": "enter"}),
        ("scroll down", "scroll", {"amount": -10}),
        ("move the cursor to the top right", "move_cursor", {"zone": "top right"}),
        ("right click", "click", {"button": "right"}),
        ("snap left", "window_control", {"text": "snap left"}),
        ("create a folder called Mark 42", "create_folder", {"text": "Mark 42"}),
        ("remember that I prefer dark mode", "remember", {"fact": "I prefer dark mode"}),
        ("switch to hindi", "set_language", {"language": "hi"}),
        ("draw a dragon over a city", "generate_image", {"query": "dragon over a city"}),
        ("copy hello there to the clipboard", "clipboard_write", {"text": "hello there"}),
        ("any unread mail", "list_unread_mail", {}),
        ("tell me a story", "chat", {}),
    ]

    def test_commands_map_to_actions(self):
        for text, action, fields in self.CASES:
            with self.subTest(text=text):
                out = simulator.offline_think(text)
                self.assertEqual(out["action"], action)
                self.assertTrue(out["reply"])
                for key, value in fields.items():
                    self.assertEqual(out.get(key), value)

    def test_every_action_is_one_the_brain_knows(self):
        import ast
        path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "brain.py")
        with open(path, encoding="utf-8") as f:
            src = f.read()
        actions = None
        for node in ast.walk(ast.parse(src)):
            if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", "") == "ACTIONS":
                actions = set(ast.literal_eval(node.value))
        self.assertTrue(actions)
        for text, action, _ in self.CASES:
            self.assertIn(action, actions)
        for action in simulator.SIM_DISPATCH:
            self.assertIn(action, actions)


class VirtualPCTests(unittest.TestCase):
    def setUp(self):
        simulator.reset()

    def test_open_type_and_close(self):
        simulator.run("open_app", {"app": "notepad"})
        simulator.run("type_text", {"text": "hello"})
        snap = simulator.snapshot()
        self.assertEqual(len(snap["windows"]), 1)
        self.assertEqual(snap["windows"][0]["text"], "hello")
        simulator.run("close_app", {"app": "notepad"})
        self.assertEqual(simulator.snapshot()["windows"], [])

    def test_reopening_an_app_does_not_duplicate_it(self):
        simulator.run("open_app", {"app": "chrome"})
        simulator.run("open_app", {"app": "notepad"})
        simulator.run("open_app", {"app": "chrome"})
        wins = simulator.snapshot()["windows"]
        self.assertEqual([w["app"] for w in wins], ["Notepad", "Chrome"])

    def test_volume_and_brightness_stay_in_range(self):
        for _ in range(20):
            simulator.run("set_volume", {"direction": "up"})
        self.assertEqual(simulator.snapshot()["volume"], 100)
        for _ in range(20):
            simulator.run("set_volume", {"direction": "down"})
        self.assertEqual(simulator.snapshot()["volume"], 0)
        simulator.run("set_brightness", {"level": 999})
        self.assertEqual(simulator.snapshot()["brightness"], 100)
        simulator.run("set_brightness", {"level": 40, "direction": ""})
        self.assertEqual(simulator.snapshot()["brightness"], 40)

    def test_window_layouts(self):
        simulator.run("open_app", {"app": "chrome"})
        simulator.run("window_control", {"text": "snap left"})
        self.assertEqual(simulator.snapshot()["windows"][0]["layout"], "left")
        simulator.run("window_control", {"text": "show desktop"})
        self.assertEqual(simulator.snapshot()["windows"][0]["layout"], "min")

    def test_shutdown_can_be_cancelled(self):
        simulator.run("shutdown_pc", {})
        snap = simulator.snapshot()
        self.assertEqual(snap["power"], "shutdown_pending")
        self.assertGreater(snap["pending_seconds"], 0)
        simulator.run("cancel_shutdown", {})
        self.assertEqual(simulator.snapshot()["power"], "on")

    def test_shutdown_completes_and_clears_the_desktop(self):
        simulator.run("open_app", {"app": "chrome"})
        simulator.run("shutdown_pc", {})
        simulator._state["pending_until"] = 0.0       # fast-forward the countdown
        snap = simulator.snapshot()
        self.assertEqual(snap["power"], "off")
        self.assertEqual(snap["windows"], [])

    def test_actions_wake_a_locked_pc(self):
        simulator.run("lock_pc", {})
        self.assertEqual(simulator.snapshot()["power"], "locked")
        result = simulator.run("open_app", {"app": "chrome"})
        self.assertIn("Unlocked", result)
        self.assertEqual(simulator.snapshot()["power"], "on")

    def test_forget_everything_never_touches_real_memory(self):
        import memory
        memory.remember("keeps a spare suit in the garage")
        simulator.run("forget_everything", {})
        self.assertIn("keeps a spare suit in the garage", memory.load()["facts"])

    def test_placeholder_image_is_stable_svg(self):
        import base64
        a, mime = simulator.placeholder_image("a dragon <script>")
        b, _ = simulator.placeholder_image("a dragon <script>")
        self.assertEqual(a, b)
        self.assertEqual(mime, "image/svg+xml")
        svg = base64.b64decode(a).decode("utf-8")
        self.assertTrue(svg.startswith("<svg"))
        self.assertNotIn("<script>", svg)


if __name__ == "__main__":
    unittest.main()
