"""
tts.py — Jarvis's voice. Three engines, picked by the voice id prefix:

  en-GB-RyanNeural        Microsoft neural voices via edge-tts. Free, no key.
  openai:fable            OpenAI gpt-4o-mini-tts. Uses an OpenAI key you've
                          already added. Takes a written direction for HOW to
                          speak, which is what makes it sound like a person.
  eleven:<voice id>       ElevenLabs. The most human-sounding; needs its own
                          key (settings > VOICE > ELEVENLABS KEY).

A premium engine that fails (no credit, offline, bad key) falls back to the
free voice, so Jarvis never goes silent. Speech recognition (listening) is
not here -- it happens in the browser via the Web Speech API.
"""
import asyncio
import base64
import io
import json
import re
import urllib.error
import urllib.request

import edge_tts

import config
import memory

# How Jarvis should sound, for the engine that accepts a direction.
_DIRECTION = {
    "dark": ("Voice: a composed, quietly witty British AI butler. Measured, unhurried pace; warm, "
             "low register; crisp diction. Dry humour delivered deadpan, never theatrical. "
             "Sound like a real person talking to someone they know well, not an announcer."),
    "light": ("Voice: the same British AI butler, but clearly enjoying himself - playful, lively "
              "timing, a smile you can hear. Still natural and conversational."),
    "oppenheimer": ("Voice: calm, focused, low and serious. Economical delivery with deliberate "
                    "pauses, like someone briefing during something important."),
}
_DIRECTION_HI = ("Speak natural, relaxed Hinglish with an Indian accent, like a witty friend - "
                 "conversational rhythm, not a newsreader.")

_ELEVEN_MODEL = "eleven_multilingual_v2"


def _clean(text: str) -> str:
    """Speech engines read markup literally; strip what would sound wrong."""
    text = re.sub(r"```.*?```", " ", text, flags=re.S)
    text = re.sub(r"[*_#`>]+", "", text)
    text = re.sub(r"https?://\S+", "the link", text)
    return " ".join(text.split())


# ---------- engines ----------
async def _edge(text: str, voice: str) -> bytes:
    communicate = edge_tts.Communicate(text, voice, rate=config.EDGE_TTS_RATE, pitch=config.EDGE_TTS_PITCH)
    buf = io.BytesIO()
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            buf.write(chunk["data"])
    return buf.getvalue()


def _openai_key():
    import llm
    return next((k for k in memory.get_api_keys() if llm.detect_provider(k) == "openai"), "")


def _openai(text: str, voice: str) -> bytes:
    key = _openai_key()
    if not key:
        raise RuntimeError("no OpenAI key stored")
    from openai import OpenAI
    hindi = memory.get_language() == "hi"
    direction = _DIRECTION_HI if hindi else _DIRECTION.get(memory.load().get("theme", "dark"), _DIRECTION["dark"])
    resp = OpenAI(api_key=key, timeout=30).audio.speech.create(
        model=getattr(config, "OPENAI_TTS_MODEL", "gpt-4o-mini-tts"),
        voice=voice, input=text, instructions=direction, response_format="mp3",
    )
    return resp.content


def _eleven(text: str, voice_id: str) -> bytes:
    key = (memory.load().get("elevenlabs_key") or "").strip()
    if not key:
        raise RuntimeError("no ElevenLabs key stored")
    if not re.fullmatch(r"[A-Za-z0-9]{10,40}", voice_id):
        raise RuntimeError("bad ElevenLabs voice id")
    req = urllib.request.Request(
        f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}?output_format=mp3_44100_128",
        method="POST",
        headers={"xi-api-key": key, "Content-Type": "application/json", "Accept": "audio/mpeg"},
        data=json.dumps({
            "text": text, "model_id": _ELEVEN_MODEL,
            "voice_settings": {"stability": 0.45, "similarity_boost": 0.8, "style": 0.25,
                               "use_speaker_boost": True},
        }).encode("utf-8"),
    )
    try:
        with urllib.request.urlopen(req, timeout=40) as r:
            return r.read()
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:200]
        raise RuntimeError(f"ElevenLabs said {e.code}: {detail}")


# ---------- public ----------
def current_voice() -> str:
    return memory.get_voice() or config.EDGE_TTS_VOICE


def engine_of(voice: str) -> str:
    if voice.startswith("openai:"):
        return "openai"
    if voice.startswith("eleven:"):
        return "elevenlabs"
    return "edge"


def available_engines() -> dict:
    return {"edge": True, "openai": bool(_openai_key()),
            "elevenlabs": bool((memory.load().get("elevenlabs_key") or "").strip())}


last_error = ""


def synthesize(text: str, voice: str = None) -> bytes:
    """mp3 bytes for text in the chosen voice, falling back to the free
    voice if a premium engine fails. Raises only if even that fails."""
    global last_error
    text = _clean(text)
    voice = voice or current_voice()
    hindi = memory.get_language() == "hi"
    engine = engine_of(voice)
    if engine != "edge":
        try:
            if engine == "openai":
                return _openai(text, voice.split(":", 1)[1])
            return _eleven(text, voice.split(":", 1)[1])
        except Exception as e:
            last_error = f"{engine}: {e}"
            print(f"(tts) {last_error} -- falling back to the free voice")
        voice = config.EDGE_TTS_VOICE
    if hindi:
        voice = config.EDGE_TTS_VOICE_HINDI
    return asyncio.run(_edge(text, voice))


def speak_to_base64(text: str, voice: str = None) -> str:
    """Returns an mp3 as a base64 string the browser can play directly,
    or '' if generation fails (e.g. no internet) -- the UI just shows the
    text in that case instead of playing audio."""
    if not text:
        return ""
    try:
        return base64.b64encode(synthesize(text, voice)).decode("ascii")
    except Exception:
        return ""
