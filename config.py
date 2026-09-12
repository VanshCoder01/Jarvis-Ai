"""
config.py — static settings. Your API key isn't here anymore; it's asked for
once in the web UI on first run and saved to jarvis_memory.json (see memory.py).
"""
import os

# Works with a Gemini, OpenAI, or Anthropic key — llm.py auto-detects which
# one you gave it from the key's format and routes accordingly. Each
# provider gets its own model fallback list: if the first one comes back
# rate-limited, the next is tried automatically instead of just failing.
PROVIDER_MODELS = {
    "gemini": ["gemini-2.5-flash", "gemini-2.5-flash-lite", "gemini-2.0-flash"],
    "openai": ["gpt-5.4-mini", "gpt-4o-mini", "gpt-4o-2024-08-06"],
    "anthropic": ["claude-haiku-4-5-20251001", "claude-sonnet-5"],
    "openrouter": ["meta-llama/llama-3.3-70b-instruct:free",
                   "google/gemini-2.0-flash-exp:free",
                   "deepseek/deepseek-chat:free"],
}
# Kept for backward reference; llm.py picks the right list from
# PROVIDER_MODELS above based on your actual key, not this directly.
MODEL_FALLBACKS = PROVIDER_MODELS["gemini"]

# Sometimes useful to set this as a real environment variable instead of
# typing it in once — picked up automatically if present. Leave blank
# otherwise; first-run setup in the browser will ask. (JARVIS_API_KEY is
# the current name; GEMINI_API_KEY still works too, for anyone who already
# set that one before multi-provider support existed.)
API_KEY = os.environ.get("JARVIS_API_KEY", "") or os.environ.get("GEMINI_API_KEY", "")

# Local web server Jarvis's UI runs on. Only reachable from this PC.
SERVER_HOST = "127.0.0.1"
SERVER_PORT = 8731

# edge-tts voice for spoken replies — a real neural voice, not the robotic
# default Windows one. Preview options at https://tts.travisvn.com before
# picking. A few good fits for a "Jarvis" character:
#   en-GB-RyanNeural    — British male, calm and precise (default)
#   en-GB-ThomasNeural   — British male, alternative tone
#   en-US-GuyNeural       — American male
EDGE_TTS_VOICE = "en-GB-RyanNeural"

# Selectable from the settings panel. Labels are what the UI shows.
VOICE_OPTIONS = [
    {"id": "en-GB-RyanNeural",    "label": "RYAN",   "note": "British male \u2014 calm, precise"},
    {"id": "en-GB-ThomasNeural",  "label": "THOMAS", "note": "British male \u2014 warmer"},
    {"id": "en-US-GuyNeural",     "label": "GUY",    "note": "American male \u2014 deeper"},
    {"id": "en-AU-WilliamNeural", "label": "WILL",   "note": "Australian male \u2014 dry"},
]
EDGE_TTS_VOICE_HINDI = "hi-IN-MadhurNeural"  # used automatically in Hindi mode

# Slightly slower and slightly lower-pitched than default — pulls the
# delivery toward "measured and precise" rather than the voice's normal
# chattier default pace. Purely a style knob: format is "+N%"/"-N%" for
# rate and "+NHz"/"-NHz" for pitch. Push these further at your own risk —
# too much either way starts sounding unnatural rather than more composed.
EDGE_TTS_RATE = "-8%"
EDGE_TTS_PITCH = "-4Hz"

# Image generation stays on Gemini regardless of which provider you're
# chatting with — gemini-2.5-flash-image ("Nano Banana") is the one with an
# actual free tier (~500/day). If your key isn't a Gemini key, image
# generation just won't work until you add one (see IMAGE_GEMINI_API_KEY).
IMAGE_MODEL = "gemini-2.5-flash-image"
# Only used if your main API_KEY above isn't a Gemini key — lets image
# generation keep working even when you're chatting through OpenAI/Anthropic.
# Leave blank to just use API_KEY (works automatically when that IS Gemini).
IMAGE_GEMINI_API_KEY = os.environ.get("IMAGE_GEMINI_API_KEY", "")

# Map spoken app names to what actually launches them. Windows resolves a lot
# of these by name alone via its "App Paths" registry (that's why "chrome.exe"
# works without a full path) — but if one of yours won't open, paste its full
# path here instead, e.g. r"C:\Program Files\Whatever\app.exe".
APP_PATHS = {
    "notepad": "notepad.exe",
    "calculator": "calc.exe",
    "calc": "calc.exe",
    "file explorer": "explorer.exe",
    "explorer": "explorer.exe",
    "files": "explorer.exe",
    "paint": "mspaint.exe",
    "task manager": "taskmgr.exe",
    "chrome": "chrome.exe",
    "google chrome": "chrome.exe",
    "edge": "msedge.exe",
    "spotify": "spotify.exe",
    "steam": "steam.exe",
    "discord": "discord.exe",
    "vscode": "code.exe",
    "vs code": "code.exe",
    "visual studio code": "code.exe",
}
