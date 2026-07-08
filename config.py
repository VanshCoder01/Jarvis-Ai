"""
config.py — static settings. Your API key isn't here anymore; it's asked for
once on first run and saved to jarvis_memory.json (see memory.py).
"""
import os

# Gemini model. gemini-2.5-flash is a safe, well-established fallback if
# this ever 404s on your account.
MODEL_NAME = "gemini-3.5-flash"

# Sometimes useful to set GEMINI_API_KEY as a real environment variable
# instead of typing it into the console every fresh install — this picks
# it up automatically if present. Leave blank otherwise; setup will ask.
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")

# Local web server Jarvis's UI runs on. Only reachable from this PC.
SERVER_HOST = "127.0.0.1"
SERVER_PORT = 8731

# edge-tts voice for spoken replies — a real neural voice, not the robotic
# default Windows one. Browse more at: https://tts.travisvn.com
# A few good fits for a "Jarvis" character:
#   en-GB-RyanNeural    — British male, calm and precise (default)
#   en-US-GuyNeural      — American male
#   en-GB-SoniaNeural    — British female
EDGE_TTS_VOICE = "en-GB-RyanNeural"
EDGE_TTS_VOICE_HINDI = "hi-IN-MadhurNeural"  # used automatically in Hindi mode

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
