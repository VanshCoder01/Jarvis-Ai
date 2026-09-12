"""
main.py — starts Jarvis: the local Flask backend, then the app window.

First-run setup (API key + name) now happens in the web UI itself, not the
console — this keeps things working even when this is eventually packaged
as a windowed .exe with no visible console at all.

Run with:  python main.py   (or double-click run.bat)
"""
import os
import subprocess
import sys
import threading
import time
import webbrowser

# In a --noconsole PyInstaller build, Windows can leave stdout/stderr as
# None — a bare print() against that crashes immediately, before anything
# else even gets a chance to run. Route output to a log file instead so
# print() stays safe either way (console or windowed build).
if sys.stdout is None or sys.stderr is None:
    _log_dir = os.path.join(os.environ.get("APPDATA", "."), "Jarvis")
    os.makedirs(_log_dir, exist_ok=True)
    _log_file = open(os.path.join(_log_dir, "jarvis_log.txt"), "a", encoding="utf-8")
    sys.stdout = _log_file
    sys.stderr = _log_file

import config
import server


def _find_chromium_browser():
    """Finds a real Chrome or Edge install (not WebView2) so the UI can
    launch without browser chrome via --app= mode while keeping full speech
    recognition support — WebView2 (what pywebview uses) has a known,
    still-open bug where that doesn't work; a real Chrome/Edge process does
    not have that problem, since it's the same engine a normal tab uses."""
    import shutil
    candidates = []
    for exe_name in ("chrome.exe", "msedge.exe"):
        found = shutil.which(exe_name)
        if found:
            candidates.append(found)
        try:
            import winreg
            key_path = rf"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\{exe_name}"
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key_path) as key:
                path, _ = winreg.QueryValueEx(key, None)
                if path:
                    candidates.append(path)
        except Exception:
            pass

    candidates += [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    ]

    for path in candidates:
        if path and os.path.isfile(path):
            return path
    return None


def _open_window(url: str):
    """Opens the UI in a clean, chrome-less window via a real Chrome/Edge
    install if one can be found — falls back to your normal default browser
    otherwise (Jarvis still fully works either way, just as a regular tab)."""
    browser_exe = _find_chromium_browser()
    if browser_exe:
        try:
            subprocess.Popen([browser_exe, f"--app={url}", "--window-size=1180,780"])
            return
        except Exception as e:
            print(f"(Couldn't open the app-mode window ({e}) — opening a normal browser tab instead.)")
    webbrowser.open(url)


def _wait_for_server(url: str, timeout: float = 20.0) -> bool:
    """Polls the server until it actually responds instead of guessing a
    fixed delay — avoids opening the browser before Flask has finished
    starting (imports + first-time antivirus file scans can make this take
    longer than you'd expect on some machines)."""
    import urllib.request
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            urllib.request.urlopen(url, timeout=1)
            return True
        except Exception:
            time.sleep(0.25)
    return False


if __name__ == "__main__":
    try:
        server_thread = threading.Thread(target=server.run, daemon=True)
        server_thread.start()

        url = f"http://{config.SERVER_HOST}:{config.SERVER_PORT}"
        if not _wait_for_server(url):
            print(f"(Server's taking a while to start \u2014 opening {url} anyway; reload if it doesn't load right away.)")
        print(f"Jarvis is running at {url}  (close this window, or Ctrl+C here, to quit)")
        _open_window(url)

        # Without this, the script simply finishes here, and since the
        # server runs on a daemon thread, the whole process would exit
        # immediately afterward — killing Flask out from under the browser
        # a moment after it opens. join() blocks for as long as the server
        # thread is alive (effectively forever) and Ctrl+C still works.
        server_thread.join()
    except KeyboardInterrupt:
        pass
    except Exception:
        import traceback
        log_dir = os.path.join(os.environ.get("APPDATA", "."), "Jarvis")
        os.makedirs(log_dir, exist_ok=True)
        log_path = os.path.join(log_dir, "crash_log.txt")
        with open(log_path, "w", encoding="utf-8") as f:
            f.write(traceback.format_exc())
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(
                0, f"Jarvis hit an error and had to close.\n\nDetails saved to:\n{log_path}",
                "Jarvis", 0x10,
            )
        except Exception:
            print(traceback.format_exc())
