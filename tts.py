"""
tts.py — Jarvis's voice, upgraded. Uses edge-tts (Microsoft's neural voices —
free, no API key) instead of the robotic default Windows SAPI voice. Needs
internet, same as the Gemini calls do.

Speech recognition (listening) isn't here anymore — it now happens directly
in the browser via the Web Speech API, which sidesteps pyaudio entirely
(that was the exact dependency giving install trouble before).
"""
import asyncio
import base64
import io

import edge_tts

import config
import memory


async def _generate(text: str, voice: str) -> bytes:
    communicate = edge_tts.Communicate(text, voice)
    buf = io.BytesIO()
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            buf.write(chunk["data"])
    return buf.getvalue()


def speak_to_base64(text: str) -> str:
    """Returns an mp3 as a base64 string the browser can play directly,
    or '' if generation fails (e.g. no internet) — the UI just shows the
    text in that case instead of playing audio."""
    if not text:
        return ""
    voice = config.EDGE_TTS_VOICE_HINDI if memory.get_language() == "hi" else config.EDGE_TTS_VOICE
    try:
        audio_bytes = asyncio.run(_generate(text, voice))
        return base64.b64encode(audio_bytes).decode("ascii")
    except Exception:
        return ""
