"""
Tests for using Claude Code / Antigravity as Jarvis's brain (cli_brains.py).
No CLI is actually run: subprocess calls are faked.
"""
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

os.environ["APPDATA"] = tempfile.mkdtemp(prefix="jarvis_test_")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import brain  # noqa: E402
import cli_brains  # noqa: E402
import llm  # noqa: E402
import memory  # noqa: E402

CONTENTS = [{"role": "user", "parts": [{"text": "open crome"}]}]


def fake_proc(stdout, code=0, stderr=""):
    return mock.Mock(stdout=stdout, stderr=stderr, returncode=code)


class KeyTests(unittest.TestCase):
    def test_keys_are_recognised(self):
        self.assertEqual(llm.detect_provider("claude-code"), "claude-code")
        self.assertEqual(llm.detect_provider("Claude-Code:opus"), "claude-code")
        self.assertEqual(llm.detect_provider("antigravity:gemini-3.8-flash-high"), "antigravity")
        self.assertEqual(llm.detect_provider("AIzaSomething"), "gemini")
        self.assertFalse(cli_brains.is_cli_key("claude-codex"))

    def test_model_comes_from_key_or_default(self):
        self.assertEqual(cli_brains.parse_key("claude-code:opus"), ("claude-code", "opus"))
        self.assertEqual(cli_brains.parse_key("antigravity"), ("antigravity", "gemini-3.8-flash-low"))


class LockdownTests(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.object(cli_brains, "find_exe", side_effect=lambda n: rf"C:\bin\{n}.exe")
        patcher.start()
        self.addCleanup(patcher.stop)

    def run_cli(self, key, stdout):
        with mock.patch.object(cli_brains.subprocess, "run", return_value=fake_proc(stdout)) as run:
            data, err = cli_brains.call(key, "SYSTEM PROMPT", CONTENTS, brain.RESPONSE_SCHEMA, [])
        return data, err, run.call_args

    def test_claude_code_runs_with_no_tools_no_mcp_no_settings(self):
        out = json.dumps({"is_error": False, "structured_output": {"action": "open_app", "app": "chrome", "reply": "On it."}})
        data, err, (args, kwargs) = self.run_cli("claude-code", out)
        argv = args[0]
        self.assertIsNone(err)
        self.assertEqual(data["app"], "chrome")
        for flag, val in (("--tools", ""), ("--setting-sources", ""), ("--mcp-config", '{"mcpServers":{}}')):
            self.assertEqual(argv[argv.index(flag) + 1], val)
        for flag in ("--strict-mcp-config", "--no-session-persistence", "--disable-slash-commands", "--json-schema"):
            self.assertIn(flag, argv)
        self.assertNotIn("--dangerously-skip-permissions", argv)
        self.assertIn("open crome", kwargs["input"])                       # prompt goes in via stdin
        self.assertEqual(os.listdir(kwargs["cwd"]) if os.path.isdir(kwargs["cwd"]) else [], [])

    def test_antigravity_is_plan_mode_sandboxed_and_never_auto_approves(self):
        out = json.dumps({"status": "SUCCESS", "structured_output": {"action": "chat", "reply": "Evening."}})
        data, err, (args, kwargs) = self.run_cli("antigravity", out)
        argv = args[0]
        self.assertIsNone(err)
        self.assertIn("--sandbox", argv)
        self.assertEqual(argv[argv.index("--mode") + 1], "plan")
        self.assertNotIn("--dangerously-skip-permissions", argv)
        self.assertTrue(argv[1].startswith("-p=") and "open crome" in argv[1])
        self.assertFalse(kwargs.get("shell", False))

    def test_antigravity_prompt_fits_the_windows_command_line(self):
        long_history = [{"role": "user", "parts": [{"text": "x" * 5000}]} for _ in range(20)] + CONTENTS
        with mock.patch.object(cli_brains.subprocess, "run",
                               return_value=fake_proc('{"structured_output":{"action":"chat","reply":"ok"}}')) as run:
            cli_brains.call("antigravity", "S" * 9000, long_history, brain.RESPONSE_SCHEMA, [])
        prompt = run.call_args[0][0][1]
        self.assertLessEqual(len(prompt), cli_brains._MAX_ARG_CHARS + 3)
        self.assertIn("open crome", prompt)                                 # the newest turn survives

    def test_falls_back_to_loose_json_in_result_text(self):
        out = json.dumps({"result": 'Sure:\n```json\n{"action":"mute","reply":"Muted."}\n```'})
        data, err, _ = self.run_cli("claude-code", out)
        self.assertEqual(data["action"], "mute")

    def test_unknown_action_becomes_chat(self):
        out = json.dumps({"structured_output": {"action": "rm_rf_everything", "reply": "No."}})
        data, err, _ = self.run_cli("claude-code", out)
        self.assertEqual(data["action"], "chat")

    def test_cli_error_is_reported_not_raised(self):
        data, err, _ = self.run_cli("claude-code", json.dumps({"is_error": True, "result": "Not logged in"}))
        self.assertIsNone(data)
        self.assertIsInstance(err, cli_brains.CLIUnavailable)

    def test_images_go_to_another_brain(self):
        with mock.patch.object(cli_brains.subprocess, "run") as run:
            data, err = cli_brains.call("claude-code", "S", CONTENTS, brain.RESPONSE_SCHEMA, [], image=object())
        run.assert_not_called()
        self.assertIsInstance(err, cli_brains.CLIUnavailable)


class FallbackTests(unittest.TestCase):
    def test_a_failing_cli_hands_over_to_the_next_key(self):
        memory.set_api_keys(["claude-code", "AIzaBackup"])
        with mock.patch.object(cli_brains, "find_exe", return_value=None), \
             mock.patch.dict(llm.CALLERS, {"gemini": lambda *a, **k: ({"action": "chat", "reply": "Gemini here"}, None)}):
            data, err = llm.call("S", CONTENTS, brain.RESPONSE_SCHEMA)
        self.assertEqual(data["reply"], "Gemini here")

    def test_cli_keys_are_not_masked(self):
        import server
        self.assertEqual(server._mask_key("claude-code:opus"), "claude-code:opus")
        self.assertNotIn("abcdef", server._mask_key("sk-abcdefghijklmnop"))


if __name__ == "__main__":
    unittest.main()
