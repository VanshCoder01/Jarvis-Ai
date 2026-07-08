# Jarvis — Voice-Controlled PC Assistant

A sassy, Grok-flavored voice assistant with a real animated HUD interface. It
controls your Windows PC — opens apps, moves your cursor, adjusts volume and
brightness, takes screenshots, locks or sleeps the machine, reads out CPU/RAM/
temp — all through natural voice commands powered by Gemini, with neural
text-to-speech (not the robotic Windows default) and switchable English/Hindi.

**How it's built**: a small local Python server (Flask) does the real work —
talks to Gemini, controls your PC, generates speech — and opens a webpage in
your browser as the interface. Speech *recognition* (you talking to it)
happens in the browser itself using Chrome/Edge's built-in speech engine, so
there's no fragile microphone library to install. The page only talks to
`127.0.0.1` (this PC) — nothing is exposed to your network or the internet.

## Setup

### 1. Install Python
You need Python 3.10+.
```
python --version
```

### 2. Install dependencies
Open a terminal in this folder and run:
```
pip install -r requirements.txt
```
This is a much shorter list than voice-assistant projects usually need —
no `pyaudio`, no `keyboard`, no `pyttsx3` — because the browser now handles
both listening and (partly) the interface.

### 3. Get a free Gemini API key
Go to https://aistudio.google.com/app/apikey , sign in, click "Create API key."

### 4. Run it
```
python main.py
```
or just double-click **`run.bat`**.

**First run only**, the console will ask for that API key and your name, then
remembers both — you won't be asked again. After that, your browser opens
automatically to the Jarvis interface, and it greets you out loud.

(If you'd rather not type the key into the console, paste it into
`GEMINI_API_KEY` in `config.py`, or set it as an environment variable with
`setx GEMINI_API_KEY "your-key-here"` — either skips the prompt.)

## How to use it
- **Say "Jarvis"** anytime and it starts listening — no button needed. The
  first time, your browser will ask for microphone permission; allow it.
- Or click the **mic button** to talk without saying the wake word.
- Or just **type** in the box and hit enter.
- Try: "open chrome," "take a screenshot," "move my cursor to the center,"
  "turn the volume up," "set brightness to 40," "how's my PC doing," "lock my
  PC," "remember that I prefer dark mode," "switch to Hindi," "tone down the
  swearing."
- The **speaker icon** (top right) mutes Jarvis's spoken replies if you want
  text-only. The **settings icon** opens a panel to switch language or
  profanity level directly, without needing to say it.
- To quit, close the terminal window Jarvis is running in (or Ctrl+C there).

## Memory
Jarvis saves your API key, name, language, profanity level, and anything
worth remembering (say "remember that..." or just mention a preference) to
`jarvis_memory.json`, created next to these scripts on first run. Loaded back
in every time Jarvis starts, so it keeps knowing you across restarts.
- **Reset everything**: say "forget everything about me," or delete
  `jarvis_memory.json` and Jarvis will ask its setup questions again.
- **This file contains your API key in plain text** — it's already in
  `.gitignore`. Don't share it or upload it anywhere.

## Language and personality
- **English/Hindi**: say "switch to Hindi" / "switch to English," or use the
  settings panel. Hindi replies come out as Hinglish (Roman letters, not
  Devanagari) — this is deliberate, since it's what the fallback English
  voice can actually pronounce. See the TTS note below if you want proper
  Devanagari + a real Hindi voice.
- **Profanity**: four levels — off / mild / medium / full — set in the
  settings panel or by voice ("stop swearing," "you can swear more"). Default
  is medium: real reactions to genuinely dumb moments, not a curse word in
  every sentence.

## Voice quality
Replies are spoken with Microsoft's edge-tts neural voices (free, no API key)
instead of the robotic default Windows voice — the difference is real. Set
`EDGE_TTS_VOICE` in `config.py` to change it; browse options at
https://tts.travisvn.com. This needs internet, same as the Gemini calls.

## System stats
CPU% and RAM% use `psutil` and are reliable everywhere. **CPU temperature is
best-effort** — it reads through Windows' standard WMI thermal sensor, which
a lot of laptop boards (including plenty of gaming laptops) simply don't
expose. If it always shows N/A on your ROG Strix, that's your board, not a
bug — install [LibreHardwareMonitor](https://github.com/LibreHardwareMonitor/LibreHardwareMonitor)
for reliable temps; wiring that in as a data source is a natural next step
if you want it.

## Customizing
- **Add/fix an app**: edit `APP_PATHS` in `config.py`. If an app won't open by
  name, paste its full `.exe` path there instead.
- **Change the personality**: edit `SYSTEM_PROMPT` in `brain.py`.
- **Change the port**: edit `SERVER_PORT` in `config.py` if `8731` is already
  used by something else on your PC.

## Safety notes
- `shutdown_pc` / `restart_pc` wait 10 seconds before actually happening — say
  "cancel shutdown" during that window to stop it.
- `close_app` force-quits (`taskkill /F`) — save your work before using it.
- Don't commit `config.py` with your real API key to a public GitHub repo
  (though the key now defaults to living in `jarvis_memory.json` instead,
  which is already gitignored).

## Troubleshooting
- **Voice input does nothing** → speech recognition only works in real
  Chrome or Edge — if `main.py` somehow opened a different default browser,
  or a browser without it, open `http://127.0.0.1:8731` manually in Chrome
  or Edge instead.
- **Mic permission popup never appeared** → check your browser's site
  settings for `127.0.0.1:8731` and allow microphone access manually.
- **"model not found" from Gemini** → open `config.py` and change
  `MODEL_NAME` to `"gemini-2.5-flash"`.
- **Brightness control does nothing** → some laptop panels/external monitors
  don't support software brightness control — a hardware/driver limit, not a
  bug here.
- **Port already in use** → change `SERVER_PORT` in `config.py`.

### About pywebview (why this doesn't use a chrome-less app window)
An earlier version of this used `pywebview` for a cleaner, browser-chrome-free
window matching a HUD mockup look. It was dropped: on Windows, pywebview
renders through WebView2, which has a known, still-open bug where the
browser's built-in speech recognition doesn't work inside it (Microsoft's
own WebView2Feedback tracker, issue #1613). Since talking to Jarvis is the
entire point, a normal browser tab with a working mic beats a slicker window
with a dead one. If you want to try it anyway (e.g. you mainly plan to type,
not talk): `pip install pywebview`, then swap the `webbrowser.open(url)` line
in `main.py` for a `webview.create_window(...)` / `webview.start()` call.

## Ideas to take this further
- Wire in LibreHardwareMonitor for real GPU/CPU temps instead of the
  best-effort WMI read.
- Add more actions: window snapping, media playback control, opening specific
  files/folders.
- A proper Devanagari Hindi voice: install a Hindi voice pack in Windows
  Settings and route Hindi replies through the local SAPI voice instead of
  edge-tts for that mode.
