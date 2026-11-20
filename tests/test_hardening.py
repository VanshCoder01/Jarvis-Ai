"""
Tests for the safety fixes: atomic JSON storage, no shell injection in
pc_control.

APPDATA is pointed at a throwaway folder before anything is imported, so
these never read or write your real jarvis_memory.json.
"""
import json
import os
import sys
import tempfile
import threading
import unittest
from unittest import mock

_TMP = tempfile.mkdtemp(prefix="jarvis_test_")
os.environ["APPDATA"] = _TMP
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import memory  # noqa: E402
import storage  # noqa: E402


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.path = os.path.join(tempfile.mkdtemp(dir=_TMP), "x.json")

    def test_round_trip(self):
        storage.write_json(self.path, {"a": 1})
        self.assertEqual(storage.read_json(self.path, dict), {"a": 1})

    def test_missing_file_gives_default(self):
        self.assertEqual(storage.read_json(self.path, list), [])

    def test_corrupt_file_is_kept_aside_not_lost(self):
        with open(self.path, "w") as f:
            f.write('{"api_keys": ["sk-abc"')          # truncated mid-write
        self.assertEqual(storage.read_json(self.path, dict), {})
        backups = [n for n in os.listdir(os.path.dirname(self.path)) if ".corrupt-" in n]
        self.assertEqual(len(backups), 1)
        with open(os.path.join(os.path.dirname(self.path), backups[0])) as f:
            self.assertIn("sk-abc", f.read())

    def test_no_temp_files_left_behind(self):
        for i in range(5):
            storage.write_json(self.path, {"i": i})
        self.assertEqual(os.listdir(os.path.dirname(self.path)), ["x.json"])


class MemoryConcurrencyTests(unittest.TestCase):
    def test_keys_survive_concurrent_saves(self):
        """The old open('w') save let a reader see an empty file, fall back
        to defaults and write them back, wiping the stored keys."""
        memory.set_api_keys(["key-one", "key-two"])
        errors = []

        def churn(n):
            try:
                for i in range(40):
                    memory.update(theme="dark" if i % 2 else "light")
                    memory.set_voice(f"v{n}-{i}")
                    if memory.get_api_keys() != ["key-one", "key-two"]:
                        errors.append("keys changed")
            except Exception as e:  # pragma: no cover
                errors.append(repr(e))

        threads = [threading.Thread(target=churn, args=(n,)) for n in range(6)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(errors, [])
        self.assertEqual(memory.get_api_keys(), ["key-one", "key-two"])

    def test_remember_from_many_threads_keeps_every_fact(self):
        memory.forget_all()
        threads = [threading.Thread(target=memory.remember, args=(f"fact {i}",)) for i in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(len(memory.load()["facts"]), 20)


@unittest.skipUnless(sys.platform == "win32", "pc_control is Windows-only")
class NoShellInjectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import pc_control
        cls.pc = pc_control

    def test_url_is_never_handed_to_a_shell(self):
        with mock.patch.object(self.pc.os, "startfile") as sf, \
             mock.patch.object(self.pc.os, "system") as system:
            self.pc.open_url('https://example.com" & calc & "')
            self.pc.open_url("example.com")
        system.assert_not_called()
        sf.assert_called_once_with("https://example.com")

    def test_non_web_schemes_are_refused(self):
        with mock.patch.object(self.pc.os, "startfile") as sf:
            for bad in ("file:///C:/Windows/System32/cmd.exe", "javascript:alert(1)",
                        "ms-settings:privacy", "https://", "https://a.com\nfoo"):
                self.pc.open_url(bad)
        sf.assert_not_called()

    def test_open_app_fallback_uses_startfile(self):
        with mock.patch.object(self.pc, "_find_start_menu_shortcut", return_value=None), \
             mock.patch.object(self.pc, "_find_downloads_installer", return_value=None), \
             mock.patch.object(self.pc.os, "system") as system, \
             mock.patch.object(self.pc.os, "startfile") as sf:
            self.pc.open_app('foo" & calc & "')
        system.assert_not_called()
        sf.assert_called_once()

    def test_check_tool_refuses_shell_metacharacters(self):
        with mock.patch.object(self.pc.subprocess, "run") as run:
            reply = self.pc.check_tool("git & calc")
        run.assert_not_called()
        self.assertIn("isn't a tool name", reply)

    def test_check_tool_runs_without_shell(self):
        with mock.patch.object(self.pc.shutil, "which", return_value=r"C:\git\git.exe"), \
             mock.patch.object(self.pc.subprocess, "run") as run:
            run.return_value = mock.Mock(returncode=0, stdout="git version 2.4", stderr="")
            self.assertIn("installed", self.pc.check_tool("git"))
        args, kwargs = run.call_args
        self.assertEqual(args[0], [r"C:\git\git.exe", "--version"])
        self.assertFalse(kwargs.get("shell", False))


if __name__ == "__main__":
    unittest.main()
