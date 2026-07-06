Jarvis — Voice-Controlled PC Assistant
A sassy, Grok-flavored voice assistant that actually controls your Windows PC —
moves your cursor, opens apps, adjusts volume/brightness, takes screenshots, locks
or sleeps the machine, and more, all through natural voice commands powered by Gemini.
A floating animated orb shows what it's doing (idle / listening / thinking / speaking).
This is a native Python app, not a browser page — that's on purpose. A webpage
can't touch your OS; this can, because it runs directly on your PC.
Setup
1. Install Python
You need Python 3.10+.
```
python --version
```
2. Install dependencies
Open a terminal in this folder and run:
```
pip install -r requirements.txt
```
If `pyaudio` fails to install (common on Windows), try:
```
pip install pipwin
pipwin install pyaudio
```
3. Get a free Gemini API key
Go to https://aistudio.google.com/app/apikey , sign in, click "Create API key."
4. Add your key
Open `config.py` and paste it in:
```python
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "PASTE_YOUR_KEY_HERE")
```
Or, safer — set it as an environment variable so it's never sitting in a file:
```
setx GEMINI_API_KEY "your-key-here"
```
(restart your terminal afterward so it picks up the new variable)
5. Run it
```
python main.py
```
A small glowing orb appears in the bottom-right of your screen.
How to use it
Press F9 anywhere, or click the orb, then speak your command.
Try: "open chrome", "take a screenshot", "move my cursor to the center",
"turn the volume up", "set brightness to 40", "what time is it", "lock my pc".
Right-click-drag the orb to reposition it.
To quit, close the terminal window Jarvis is running in (or Ctrl+C there).
Customizing
Add/fix an app: edit `APP_PATHS` in `config.py`. If an app won't open by
name, paste its full `.exe` path there instead.
Change the hotkey: edit `LISTEN_HOTKEY` in `config.py`.
Change the personality: edit `SYSTEM_PROMPT` in `brain.py` — make it nicer,
meaner, more formal, whatever you want.
Change the voice: run
```
  python -c "import voice; voice.list_voices()"
  ```
to see installed Windows voices, then set `TTS_VOICE_INDEX` in `config.py`.
Safety notes
`shutdown_pc` / `restart_pc` wait 10 seconds before actually happening — say
"cancel shutdown" during that window to stop it.
`close_app` force-quits (`taskkill /F`) — save your work before using it.
Don't commit `config.py` with your real API key to a public GitHub repo.
Troubleshooting
"No module named pyaudio" → see the pipwin fallback in step 2.
Hotkey doesn't respond → run your terminal as Administrator; the
`keyboard` library sometimes needs elevated permissions for global hotkeys.
Brightness control does nothing → some laptop panels/external monitors
don't support software brightness control — that's a hardware/driver limit,
not a bug here.
Mic not detected → run
```
  python -c "import speech_recognition as sr; print(sr.Microphone.list_microphone_names())"
  ```
and check your default recording device in Windows Sound settings.
"model not found" from Gemini → open `config.py` and change `MODEL_NAME`
to `"gemini-2.5-flash"`.
Ideas to take this further
Swap push-to-talk for an always-on wake word ("Hey Jarvis") using something
like openWakeWord, instead of pressing F9.
Build a small settings window instead of hand-editing `config.py`.
Add more actions: window snapping, media playback control, opening specific
files/folders.
Upgrade the voice with a more expressive TTS service (Azure, ElevenLabs) once
the free local voice starts feeling flat.
