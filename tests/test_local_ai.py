"""
Tests for the local-model picker and installer (local_ai.py). Hardware,
Ollama and the network are all faked -- nothing is installed or downloaded.
"""
import os
import sys
import tempfile
import time
import unittest
from unittest import mock

os.environ["APPDATA"] = tempfile.mkdtemp(prefix="jarvis_test_")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import local_ai  # noqa: E402

_NO_OLLAMA = {"running": False, "models": []}


def hw(ram=16, vram=0.0, gpu="", disk=200):
    return {"ram_gb": ram, "gpu": gpu, "vram_gb": vram, "free_disk_gb": disk}


@mock.patch.object(local_ai.llm, "ollama_status", return_value=_NO_OLLAMA)
@mock.patch.object(local_ai, "_find_ollama_exe", return_value=None)
class RecommendTests(unittest.TestCase):
    def pick(self, **kw):
        return local_ai.recommend(hw(**kw))["recommended"]

    def test_picks_by_graphics_memory(self, *_):
        self.assertEqual(self.pick(vram=24, gpu="RTX 4090"), "qwen2.5:32b")
        self.assertEqual(self.pick(vram=12, gpu="RTX 4070"), "qwen2.5:14b")
        self.assertEqual(self.pick(vram=8, gpu="RTX 4060"), "qwen2.5:7b")
        self.assertEqual(self.pick(vram=4, gpu="GTX 1650"), "qwen2.5:3b")

    def test_cpu_only_never_goes_past_7b(self, *_):
        self.assertEqual(self.pick(ram=64), "qwen2.5:7b")
        self.assertEqual(self.pick(ram=8), "qwen2.5:3b")
        self.assertEqual(self.pick(ram=4), "qwen2.5:1.5b")

    def test_tiny_machine_still_gets_something(self, *_):
        self.assertEqual(self.pick(ram=2), "qwen2.5:1.5b")

    def test_flags_models_that_wont_fit_on_disk(self, *_):
        opts = {o["id"]: o["fit"] for o in local_ai.recommend(hw(vram=24, gpu="x", disk=8))["options"]}
        self.assertEqual(opts["qwen2.5:32b"], "no disk space")
        self.assertEqual(opts["qwen2.5:1.5b"], "good")


class InstallFlowTests(unittest.TestCase):
    def setUp(self):
        local_ai._status.update(state="idle", model="", message="", progress=0.0, error="")

    def wait(self):
        for _ in range(200):
            if local_ai.status()["state"] in ("done", "error"):
                return local_ai.status()
            time.sleep(0.02)
        self.fail("installer thread never finished")

    def test_rejects_models_not_in_catalogue(self):
        for bad in ("evil", "qwen2.5:7b; calc", ""):
            with self.assertRaises(ValueError):
                local_ai.start(bad)

    def test_installs_ollama_then_pulls(self):
        running = {"v": False}
        with mock.patch.object(local_ai, "_find_ollama_exe", side_effect=lambda: "ollama.exe" if running["v"] else None), \
             mock.patch.object(local_ai, "_install_ollama", side_effect=lambda: running.update(v=True)) as inst, \
             mock.patch.object(local_ai.llm, "ollama_status", side_effect=lambda: {"running": running["v"], "models": []}), \
             mock.patch.object(local_ai.llm, "ollama_installed_models", return_value=[]), \
             mock.patch.object(local_ai, "_pull") as pull:
            local_ai.start("qwen2.5:7b")
            st = self.wait()
        self.assertEqual(st["state"], "done", st)
        inst.assert_called_once()
        pull.assert_called_once_with("qwen2.5:7b")

    def test_skips_download_if_model_already_there(self):
        with mock.patch.object(local_ai, "_find_ollama_exe", return_value="ollama.exe"), \
             mock.patch.object(local_ai.llm, "ollama_status", return_value={"running": True, "models": []}), \
             mock.patch.object(local_ai.llm, "ollama_installed_models", return_value=["qwen2.5:7b"]), \
             mock.patch.object(local_ai, "_pull") as pull:
            local_ai.start("qwen2.5:7b")
            st = self.wait()
        self.assertEqual(st["state"], "done")
        pull.assert_not_called()

    def test_errors_are_reported_not_raised(self):
        with mock.patch.object(local_ai, "_find_ollama_exe", return_value=None), \
             mock.patch.object(local_ai.llm, "ollama_status", return_value=_NO_OLLAMA), \
             mock.patch.object(local_ai, "_install_ollama", side_effect=RuntimeError("winget said no")):
            local_ai.start("qwen2.5:3b")
            st = self.wait()
        self.assertEqual(st["state"], "error")
        self.assertIn("winget said no", st["error"])


class PullStreamTests(unittest.TestCase):
    """_pull against a fake Ollama that streams NDJSON like the real one."""
    def serve(self, lines):
        import http.server
        import json as _json
        import threading

        class H(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                self.rfile.read(int(self.headers.get("Content-Length", 0)))
                self.send_response(200)
                self.send_header("Content-Type", "application/x-ndjson")
                self.end_headers()
                for ln in lines:
                    self.wfile.write((_json.dumps(ln) + chr(10)).encode())

            def log_message(self, *a):
                pass

        srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.server_close)
        self.addCleanup(srv.shutdown)
        return f"http://127.0.0.1:{srv.server_address[1]}"

    def test_progress_and_success(self):
        base = self.serve([
            {"status": "pulling manifest"},
            {"status": "pulling a", "digest": "a", "total": 1000, "completed": 500},
            {"status": "pulling b", "digest": "b", "total": 1000, "completed": 1000},
            {"status": "success"},
        ])
        seen = []
        with mock.patch.object(local_ai.llm, "ollama_default_host", return_value=base),              mock.patch.object(local_ai, "_set", side_effect=lambda **kw: seen.append(kw)):
            local_ai._pull("qwen2.5:1.5b")
        self.assertAlmostEqual(seen[-1]["progress"], 0.75)

    def test_error_line_raises(self):
        base = self.serve([{"error": "pull model manifest: file does not exist"}])
        with mock.patch.object(local_ai.llm, "ollama_default_host", return_value=base):
            with self.assertRaisesRegex(RuntimeError, "does not exist"):
                local_ai._pull("qwen2.5:1.5b")

    def test_stream_ending_early_raises(self):
        base = self.serve([{"status": "pulling a", "digest": "a", "total": 10, "completed": 3}])
        with mock.patch.object(local_ai.llm, "ollama_default_host", return_value=base):
            with self.assertRaisesRegex(RuntimeError, "ended early"):
                local_ai._pull("qwen2.5:1.5b")


if __name__ == "__main__":
    unittest.main()
