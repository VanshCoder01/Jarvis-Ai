"""
Tests for the voice engines (tts.py) and conversational memory (brain.py).
Every network call is faked.
"""
import os
import sys
import tempfile
import unittest
from unittest import mock

os.environ["APPDATA"] = tempfile.mkdtemp(prefix="jarvis_test_")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import brain  # noqa: E402
import config  # noqa: E402
import memory  # noqa: E402
import tts  # noqa: E402


class VoiceEngineTests(unittest.TestCase):
    def setUp(self):
        memory.set_api_keys(["AIzaFakeGeminiKey"])
        memory.update(elevenlabs_key="", language="en")

    def test_engine_from_voice_id(self):
        self.assertEqual(tts.engine_of("en-GB-RyanNeural"), "edge")
        self.assertEqual(tts.engine_of("openai:fable"), "openai")
        self.assertEqual(tts.engine_of("eleven:JBFqnCBsd6RMkjVDRZzb"), "elevenlabs")

    def test_engines_unlock_with_keys(self):
        self.assertEqual(tts.available_engines(), {"edge": True, "openai": False, "elevenlabs": False})
        memory.set_api_keys(["AIzaFakeGeminiKey", "sk-proj-fakeopenai"])
        memory.update(elevenlabs_key="abc123")
        self.assertEqual(tts.available_engines(), {"edge": True, "openai": True, "elevenlabs": True})

    def test_premium_failure_falls_back_to_free_voice(self):
        async def fake_edge(text, voice):
            return b"EDGE:" + voice.encode()
        with mock.patch.object(tts, "_edge", side_effect=fake_edge):
            audio = tts.synthesize("hello", "openai:fable")       # no OpenAI key stored
        self.assertEqual(audio, b"EDGE:" + config.EDGE_TTS_VOICE.encode())
        self.assertIn("openai", tts.last_error)

    def test_openai_engine_used_when_key_present(self):
        memory.set_api_keys(["sk-proj-fakeopenai"])
        with mock.patch.object(tts, "_openai", return_value=b"OPENAI") as o:
            self.assertEqual(tts.synthesize("hello there", "openai:onyx"), b"OPENAI")
        o.assert_called_once_with("hello there", "onyx")

    def test_markup_is_not_read_aloud(self):
        self.assertEqual(tts._clean("**Done** - see https://x.com/a ```print(1)``` ok"),
                         "Done - see the link ok")

    def test_eleven_rejects_odd_voice_ids(self):
        memory.update(elevenlabs_key="abc123")
        with self.assertRaises(RuntimeError):
            tts._eleven("hi", "../../v1/user")

    def test_every_listed_voice_has_a_known_engine(self):
        for v in config.VOICE_OPTIONS:
            self.assertEqual(tts.engine_of(v["id"]), v["engine"], v)


class ConversationMemoryTests(unittest.TestCase):
    def setUp(self):
        brain._clear_history()
        memory.set_api_keys(["AIzaFakeGeminiKey"])
        memory.update(simulation=False)

    def _think(self, text, data):
        with mock.patch.object(brain.llm, "call", return_value=(data, None)) as call, \
             mock.patch.dict(brain.DISPATCH, {"open_app": lambda d: f"Opened {d['app']}."}):
            brain.think(text)
        return call.call_args[0][1]          # the `contents` sent to the model

    def test_follow_ups_see_what_was_actually_done(self):
        self._think("open crome", {"action": "open_app", "app": "chrome", "reply": "Right away."})
        contents = self._think("now close it", {"action": "chat", "reply": "Done."})
        model_turn = contents[1]["parts"][0]["text"]
        self.assertIn("Right away.", model_turn)
        self.assertIn("[did: open_app -> Opened chrome.]", model_turn)
        self.assertEqual(contents[-1]["parts"][0]["text"], "now close it")

    def test_prompt_is_not_hardcoded_to_one_person(self):
        self.assertNotIn("Vansh", brain.SYSTEM_PROMPT)
        self.assertIn("misheard", brain.SYSTEM_PROMPT)

    def test_prompt_knows_the_time(self):
        with mock.patch.object(brain.llm, "call", return_value=({"action": "chat", "reply": "Hi"}, None)) as call:
            brain.think("hello")
        self.assertIn("Right now it is", call.call_args[0][0])

    def test_reopening_a_session_restores_context(self):
        brain.load_session([{"user": "my dog is called Rex", "jarvis": "Noted, sir."}])
        contents = self._think("what's my dog called", {"action": "chat", "reply": "Rex."})
        self.assertEqual(contents[0]["parts"][0]["text"], "my dog is called Rex")


class ForgetTests(unittest.TestCase):
    def test_forget_keeps_keys_and_settings(self):
        memory.set_api_keys(["AIzaKeep"])
        memory.update(name="Sam", theme="light", elevenlabs_key="kept")
        memory.remember("likes jazz")
        memory.forget_all()
        data = memory.load()
        self.assertEqual(data["facts"], [])
        self.assertEqual(memory.get_api_keys(), ["AIzaKeep"])
        self.assertEqual((data["theme"], data["elevenlabs_key"], data["name"]), ("light", "kept", "Sam"))


if __name__ == "__main__":
    unittest.main()
