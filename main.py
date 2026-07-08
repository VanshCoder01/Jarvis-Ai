"""
main.py — starts Jarvis: first-run setup (API key + name), the local Flask
backend, then the app window itself.

Run with:  python main.py   (or double-click run.bat)
"""
import threading
import time
import webbrowser

import config
import memory
import server


def _ensure_setup() -> str:
    """Runs once on first launch: gets an API key and a name out of the user
    and saves both to jarvis_memory.json. Every run after this one is silent
    and skips straight past. Returns the name to greet on startup."""
    data = memory.load()

    key = config.GEMINI_API_KEY or data.get("api_key", "")
    if not key:
        print("=" * 56)
        print(" First-time setup - Jarvis needs a free Gemini API key.")
        print(" Get one at: https://aistudio.google.com/app/apikey")
        print("=" * 56)
        while not key:
            key = input("Paste your Gemini API key: ").strip()
        data["api_key"] = key
        memory.save(data)
    config.GEMINI_API_KEY = key  # brain.py reads this lazily, so this is picked up fine

    if not data.get("name"):
        name = input("What should I call you? ").strip()
        data["name"] = name or "Boss"
        memory.save(data)

    return data["name"]


def _open_window(url: str):
    """Opens the UI in your default browser (Chrome/Edge). Deliberately NOT
    using pywebview here — its Windows backend (WebView2) has a known,
    still-open bug where the browser's built-in speech recognition doesn't
    work inside it. Since voice input is the whole point of this app, a
    normal browser tab (with working voice) beats a chrome-less window with
    a broken mic. See README for the tradeoff if you want to try pywebview
    anyway."""
    webbrowser.open(url)


if __name__ == "__main__":
    user_name = _ensure_setup()

    server_thread = threading.Thread(target=server.run, daemon=True)
    server_thread.start()
    time.sleep(0.6)  # give Flask a moment to bind the port before we load it

    url = f"http://{config.SERVER_HOST}:{config.SERVER_PORT}"
    print(f"Jarvis is running at {url}  (Ctrl+C here to quit)")
    _open_window(url)
