"""
pc_control.py — Jarvis's hands. Every function here actually touches the PC.

Targets Windows (this is built for your ROG Strix). A few functions
(lock/sleep/shutdown, volume media-keys) are Windows-specific by design.
"""
import os
import subprocess
from datetime import datetime

import pyautogui

import config

pyautogui.FAILSAFE = True  # slam the mouse into a screen corner to abort a runaway action
SCREEN_W, SCREEN_H = pyautogui.size()


# ---------- Apps ----------
def open_app(name: str) -> str:
    """Also doubles as 'install X': if nothing else matches, checks the
    Downloads folder for an installer they've already grabbed and launches
    THAT — the actual install wizard still runs normally and still needs
    you to click through it yourself; this only saves you digging through
    Downloads and double-clicking it manually."""
    key = (name or "").strip().lower()
    if not key:
        return "Didn't catch what you wanted opened."

    # 1. Curated list first — fast, exact, deliberate.
    target = config.APP_PATHS.get(key)
    if target:
        try:
            os.system(f'start "" "{target}"')
            return f"Opened {name}."
        except Exception as e:
            return f"Couldn't open {name} ({e})."

    # 2. Not curated — search real Windows Start Menu shortcuts instead of
    #    guessing an .exe name. This is how Windows itself finds apps when
    #    you search the Start Menu, so it covers anything actually
    #    installed, not just what's hardcoded in config.py.
    shortcut = _find_start_menu_shortcut(key)
    if shortcut:
        try:
            os.startfile(shortcut)
            return f"Found {name} in your Start Menu and opened it."
        except Exception as e:
            return f"Found {name} but couldn't launch it ({e})."

    # 3. Not installed yet — check Downloads for an installer with a
    #    matching name and launch it. You still click through the actual
    #    install wizard yourself; this just saves the manual digging.
    installer = _find_downloads_installer(key)
    if installer:
        try:
            os.startfile(installer)
            return f"Found an installer for {name} in your Downloads and opened it \u2014 go ahead and click through the setup."
        except Exception as e:
            return f"Found an installer for {name} but couldn't launch it ({e})."

    # 4. Last resort — try it as a raw command. Works for anything that
    #    registers itself in Windows' own App Paths (many installers do
    #    this automatically), even without a curated entry or a Start Menu
    #    shortcut turning up.
    try:
        os.system(f'start "" "{name}"')
        return f"Tried opening {name} \u2014 let me know if that didn't actually work."
    except Exception as e:
        return f"Couldn't find or open {name} ({e})."


def _find_downloads_installer(query: str):
    """Searches the Downloads folder for an .exe/.msi whose name matches —
    deliberately NOT recursive and NOT searching the whole internet or
    anywhere else: only a file you already chose to download yourself,
    sitting in the one folder browsers save to by default."""
    downloads = os.path.join(os.path.expanduser("~"), "Downloads")
    if not os.path.isdir(downloads):
        return None
    best_partial = None
    try:
        for fname in os.listdir(downloads):
            lower = fname.lower()
            if not (lower.endswith(".exe") or lower.endswith(".msi")):
                continue
            stem = os.path.splitext(lower)[0]
            full_path = os.path.join(downloads, fname)
            if query == stem:
                return full_path
            if best_partial is None and query in stem:
                best_partial = full_path
    except Exception:
        pass
    return best_partial


def _find_start_menu_shortcut(query: str):
    """Searches both Start Menu shortcut folders (all-users and
    current-user) for a .lnk whose name matches the query. An exact name
    match returns immediately; otherwise the first partial match found is
    used. Returns a full path, or None if nothing turned up."""
    search_dirs = [
        os.path.join(os.environ.get("PROGRAMDATA", r"C:\ProgramData"), "Microsoft", "Windows", "Start Menu", "Programs"),
        os.path.join(os.environ.get("APPDATA", ""), "Microsoft", "Windows", "Start Menu", "Programs"),
    ]
    best_partial = None
    for base in search_dirs:
        if not base or not os.path.isdir(base):
            continue
        for root, _dirs, files in os.walk(base):
            for fname in files:
                if not fname.lower().endswith(".lnk"):
                    continue
                stem = os.path.splitext(fname)[0].lower()
                if query == stem:
                    return os.path.join(root, fname)
                if best_partial is None and query in stem:
                    best_partial = os.path.join(root, fname)
    return best_partial


def close_app(name: str) -> str:
    key = (name or "").strip().lower()
    target = config.APP_PATHS.get(key, name)
    exe = os.path.basename(target)
    if not exe.lower().endswith(".exe"):
        exe += ".exe"
    try:
        subprocess.run(["taskkill", "/IM", exe, "/F"], capture_output=True)
        return f"Closed {name}."
    except Exception as e:
        return f"Couldn't close {name} ({e})."


def open_url(url: str) -> str:
    url = (url or "").strip()
    if not url:
        return "Didn't catch what site you wanted."
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    try:
        os.system(f'start "" "{url}"')
        return f"Opening {url}."
    except Exception as e:
        return f"Couldn't open that ({e})."


def play_on_youtube(query: str) -> str:
    """Opens YouTube search results for the query — reliable, one click away.
    This does NOT visually find and click the exact video for you; that would
    need a vision model reading the screen, which is a separate, meaningfully
    more complex feature (see README)."""
    query = (query or "").strip()
    if not query:
        return "Didn't catch what you wanted to hear."
    import urllib.parse
    search_url = "https://www.youtube.com/results?search_query=" + urllib.parse.quote(query)
    try:
        os.system(f'start "" "{search_url}"')
        return f"Pulled up YouTube results for {query}."
    except Exception as e:
        return f"Couldn't get to YouTube ({e})."


# ---------- Cursor & clicks ----------
ZONES = {
    "center": (0.5, 0.5),
    "top left": (0.05, 0.05),
    "top right": (0.95, 0.05),
    "bottom left": (0.05, 0.95),
    "bottom right": (0.95, 0.95),
    "top": (0.5, 0.05),
    "bottom": (0.5, 0.95),
}


def move_cursor(zone: str = None, dx: int = 0, dy: int = 0) -> str:
    if zone and zone.lower() in ZONES:
        fx, fy = ZONES[zone.lower()]
        pyautogui.moveTo(int(SCREEN_W * fx), int(SCREEN_H * fy), duration=0.3)
        return f"Cursor moved to {zone}."
    x, y = pyautogui.position()
    pyautogui.moveTo(x + dx, y + dy, duration=0.2)
    return "Cursor moved."


def click(button: str = "left") -> str:
    pyautogui.click(button=button if button in ("left", "right", "middle") else "left")
    return f"{button.capitalize()} click."


def double_click() -> str:
    pyautogui.doubleClick()
    return "Double-clicked."


def scroll(amount: int = 10) -> str:
    pyautogui.scroll(int(amount) * 30)
    return "Scrolled."


def type_text(text: str) -> str:
    pyautogui.write(text or "", interval=0.02)
    return f"Typed: {text}"


def press_key(key: str) -> str:
    try:
        pyautogui.press(key)
        return f"Pressed {key}."
    except Exception as e:
        return f"Couldn't press {key} ({e})."


# ---------- Volume ----------
def set_volume(direction: str = None, steps: int = 5) -> str:
    key = {"up": "volumeup", "down": "volumedown"}.get((direction or "").lower())
    if key:
        for _ in range(steps):
            pyautogui.press(key)
        return f"Volume {direction}."
    return "Didn't catch a volume direction."


def mute() -> str:
    pyautogui.press("volumemute")
    return "Muted."


# ---------- Brightness ----------
def set_brightness(level=None, direction: str = None, step: int = 15) -> str:
    try:
        import screen_brightness_control as sbc
        if level:
            target = max(0, min(100, int(level)))
        elif direction:
            current = sbc.get_brightness()
            current = current[0] if isinstance(current, list) else current
            delta = step if direction == "up" else -step if direction == "down" else 0
            target = max(0, min(100, current + delta))
        else:
            target = 50
        sbc.set_brightness(target)
        return f"Brightness set to {target}%."
    except Exception as e:
        return f"Couldn't change brightness ({e}). Some laptop panels block external control."


# ---------- Power ----------
def lock_pc() -> str:
    import ctypes
    ctypes.windll.user32.LockWorkStation()
    return "Locked."


def sleep_pc() -> str:
    subprocess.run(["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"])
    return "Going to sleep."


def shutdown_pc(seconds: int = 10) -> str:
    subprocess.run(["shutdown", "/s", "/t", str(seconds)])
    return f"Shutting down in {seconds} seconds. Say 'cancel shutdown' to stop it."


def restart_pc(seconds: int = 10) -> str:
    subprocess.run(["shutdown", "/r", "/t", str(seconds)])
    return f"Restarting in {seconds} seconds. Say 'cancel shutdown' to stop it."


def cancel_shutdown() -> str:
    subprocess.run(["shutdown", "/a"])
    return "Shutdown cancelled."


# ---------- Misc ----------
def screenshot() -> str:
    folder = os.path.join(os.path.expanduser("~"), "Pictures", "Jarvis")
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, f"shot_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png")
    pyautogui.screenshot(path)
    return f"Screenshot saved to {path}."


def capture_screen_base64():
    """Screenshot as an in-memory base64 PNG for handing to a vision model —
    separate from screenshot() above, which saves a copy to disk for the
    user instead. Returns (base64_str_or_None, mime, error_or_None)."""
    import base64
    from io import BytesIO
    try:
        img = pyautogui.screenshot()
        buf = BytesIO()
        img.save(buf, format="PNG")
        return base64.b64encode(buf.getvalue()).decode("ascii"), "image/png", None
    except Exception as e:
        return None, "image/png", str(e)


def get_time() -> str:
    return datetime.now().strftime("It's %I:%M %p.")


# ---------- System stats ----------
_cpu_primed = False


def get_system_stats() -> dict:
    """CPU%, RAM%, temp (best-effort), and OS info for the UI's stats strip.
    Never raises — anything unavailable just comes back as None so the UI
    shows 'N/A' instead of breaking."""
    global _cpu_primed
    import platform as _platform

    stats = {
        "cpu_percent": None,
        "ram_percent": None,
        "ram_used_gb": None,
        "ram_total_gb": None,
        "temp_c": None,
        "os": f"{_platform.system()} {_platform.release()}",
    }

    try:
        import psutil
        # Always measure over a real (short) window. interval=None measures
        # "since the last call", which under Flask's threaded server is an
        # unreliable window and kept coming back as a flat 0%. 0.15s costs
        # nothing noticeable and always gives a true reading.
        stats["cpu_percent"] = round(psutil.cpu_percent(interval=0.15))
        mem = psutil.virtual_memory()
        stats["ram_percent"] = round(mem.percent)
        stats["ram_used_gb"] = round(mem.used / (1024 ** 3), 1)
        stats["ram_total_gb"] = round(mem.total / (1024 ** 3), 1)
    except Exception:
        pass

    try:
        stats["temp_c"] = _read_temp_c()
    except Exception:
        pass

    return stats


def open_code_in_terminal(code: str, language: str) -> str:
    """Saves code to a file and opens a real, visible terminal window
    already sitting in that folder — it does NOT run the code. You read it,
    then type the run command yourself if you want to. That's deliberate:
    this app already has broad PC control, so one-click automatic execution
    of AI-generated code is a real risk, not a convenience worth taking
    casually. This is the reviewed, human-in-the-loop version of 'run it'."""
    ext_map = {
        "python": "py", "py": "py", "javascript": "js", "js": "js",
        "batch": "bat", "bat": "bat", "cmd": "bat", "powershell": "ps1",
        "html": "html", "css": "css", "json": "json", "bash": "sh", "sh": "sh",
        "c": "c", "cpp": "cpp", "c++": "cpp", "java": "java", "sql": "sql",
    }
    ext = ext_map.get((language or "").strip().lower(), "txt")
    folder = os.path.join(os.environ.get("TEMP", "."), "jarvis_scripts")
    try:
        os.makedirs(folder, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"jarvis_script_{stamp}.{ext}"
        filepath = os.path.join(folder, filename)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(code)
    except Exception as e:
        return f"Couldn't save that script ({e})."

    try:
        msg = f"Saved as {filename} \u2014 review it, then run it yourself if you want to."
        subprocess.Popen(
            f'start "Jarvis Script" cmd /K "cd /d {folder} && echo {msg}"',
            shell=True,
        )
        return f"Saved to {filepath} and opened a terminal there \u2014 nothing runs until you tell it to."
    except Exception as e:
        return f"Saved to {filepath}, but couldn't open a terminal automatically ({e})."


# ---------- Media ----------
def media_control(command: str) -> str:
    """Play/pause, skip, previous — works with Spotify, YouTube, VLC, most
    players, since these are the standard Windows media keys."""
    keys = {
        "play": "playpause", "pause": "playpause", "playpause": "playpause",
        "next": "nexttrack", "skip": "nexttrack",
        "previous": "prevtrack", "back": "prevtrack", "prev": "prevtrack",
        "stop": "stop",
    }
    key = keys.get((command or "").strip().lower())
    if not key:
        return "Not sure what you wanted there — play, pause, next, or previous."
    try:
        pyautogui.press(key)
        return f"Done: {command}."
    except Exception as e:
        return f"Couldn't do that ({e})."


# ---------- Windows / desktop ----------
def window_control(command: str) -> str:
    """Snap, minimize, maximize, switch, or close the active window."""
    cmd = (command or "").strip().lower()
    try:
        if cmd in ("minimize", "minimise"):
            pyautogui.hotkey("win", "down")
            return "Minimized."
        if cmd in ("maximize", "maximise", "fullscreen"):
            pyautogui.hotkey("win", "up")
            return "Maximized."
        if cmd in ("snap left", "left"):
            pyautogui.hotkey("win", "left")
            return "Snapped left."
        if cmd in ("snap right", "right"):
            pyautogui.hotkey("win", "right")
            return "Snapped right."
        if cmd in ("show desktop", "desktop", "minimize all"):
            pyautogui.hotkey("win", "d")
            return "Showing the desktop."
        if cmd in ("switch", "next window", "alt tab"):
            pyautogui.hotkey("alt", "tab")
            return "Switched window."
        if cmd in ("close", "close window"):
            pyautogui.hotkey("alt", "f4")
            return "Closed that window."
        return "Not a window command I know."
    except Exception as e:
        return f"Couldn't do that ({e})."


# ---------- Files and folders ----------
_KNOWN_FOLDERS = {
    "downloads": "Downloads", "documents": "Documents", "desktop": "Desktop",
    "pictures": "Pictures", "music": "Music", "videos": "Videos",
}


def open_folder(name: str) -> str:
    """Opens a folder in File Explorer — either a known one by name
    (downloads, documents, desktop...) or a full path."""
    key = (name or "").strip().lower()
    if not key:
        return "Which folder?"
    folder = _KNOWN_FOLDERS.get(key)
    path = os.path.join(os.path.expanduser("~"), folder) if folder else os.path.expanduser(name)
    if not os.path.isdir(path):
        return f"Couldn't find a folder called {name}."
    try:
        os.startfile(path)
        return f"Opened {name}."
    except Exception as e:
        return f"Couldn't open it ({e})."


def find_file(query: str) -> str:
    """Searches your usual folders for a file by name and opens the best
    match. Read-only search — it never deletes or moves anything."""
    query = (query or "").strip().lower()
    if not query:
        return "What am I looking for?"
    home = os.path.expanduser("~")
    search_roots = [os.path.join(home, f) for f in _KNOWN_FOLDERS.values()]
    matches = []
    for root_dir in search_roots:
        if not os.path.isdir(root_dir):
            continue
        try:
            for root, _dirs, files in os.walk(root_dir):
                for fname in files:
                    if query in fname.lower():
                        matches.append(os.path.join(root, fname))
                        if len(matches) >= 40:
                            break
                if len(matches) >= 40:
                    break
        except Exception:
            continue
    if not matches:
        return f"Couldn't find anything matching '{query}'."
    # Prefer an exact-ish name match, else most recently modified.
    exact = [m for m in matches if os.path.splitext(os.path.basename(m))[0].lower() == query]
    best = exact[0] if exact else max(matches, key=lambda p: os.path.getmtime(p))
    try:
        os.startfile(best)
        extra = f" (found {len(matches)}, opened the closest match)" if len(matches) > 1 else ""
        return f"Opened {os.path.basename(best)}{extra}."
    except Exception as e:
        return f"Found {os.path.basename(best)} but couldn't open it ({e})."


def create_folder(name: str) -> str:
    """Makes a new folder on the Desktop. Creating things is safe;
    deleting is deliberately not offered."""
    name = (name or "").strip()
    if not name:
        return "What should I call it?"
    safe = "".join(c for c in name if c not in '<>:"/\\|?*')
    path = os.path.join(os.path.expanduser("~"), "Desktop", safe)
    try:
        os.makedirs(path, exist_ok=True)
        return f"Made a folder called {safe} on your Desktop."
    except Exception as e:
        return f"Couldn't create it ({e})."


# ---------- Clipboard ----------
def clipboard_read() -> str:
    try:
        result = subprocess.run(["powershell", "-NoProfile", "-Command", "Get-Clipboard"],
                                capture_output=True, text=True, timeout=5)
        text = (result.stdout or "").strip()
        return f"Clipboard says: {text}" if text else "Clipboard's empty."
    except Exception as e:
        return f"Couldn't read the clipboard ({e})."


def clipboard_write(text: str) -> str:
    text = text or ""
    if not text:
        return "Nothing to copy."
    try:
        subprocess.run(["clip"], input=text, text=True, timeout=5)
        return "Copied to your clipboard."
    except Exception as e:
        return f"Couldn't copy that ({e})."


# ---------- Coding ----------
_TOOL_CHECKS = {
    "python": ("python --version", "Python.Python.3.12"),
    "node": ("node --version", "OpenJS.NodeJS.LTS"),
    "nodejs": ("node --version", "OpenJS.NodeJS.LTS"),
    "npm": ("npm --version", "OpenJS.NodeJS.LTS"),
    "git": ("git --version", "Git.Git"),
    "vscode": ("code --version", "Microsoft.VisualStudioCode"),
    "vs code": ("code --version", "Microsoft.VisualStudioCode"),
    "java": ("java -version", "Oracle.JDK.21"),
    "docker": ("docker --version", "Docker.DockerDesktop"),
    "rust": ("rustc --version", "Rustlang.Rustup"),
    "go": ("go version", "GoLang.Go"),
}

_PROJECT_ROOT = os.path.join(os.path.expanduser("~"), "Desktop", "JarvisProjects")

_EXT_MAP = {
    "python": "py", "py": "py", "javascript": "js", "js": "js", "typescript": "ts",
    "html": "html", "css": "css", "json": "json", "batch": "bat", "bat": "bat",
    "powershell": "ps1", "bash": "sh", "sh": "sh", "c": "c", "cpp": "cpp",
    "c++": "cpp", "csharp": "cs", "java": "java", "sql": "sql", "rust": "rs",
    "go": "go", "ruby": "rb", "php": "php", "yaml": "yml", "markdown": "md",
}


def check_tool(name: str) -> str:
    """Is a dev tool installed? Returns a plain answer — and if it's
    missing, says so without installing anything. Installing is a separate,
    deliberate step the user has to agree to."""
    key = (name or "").strip().lower()
    if not key:
        return "Which tool?"
    check = _TOOL_CHECKS.get(key)
    cmd = check[0] if check else f"{key} --version"
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=10)
        output = ((result.stdout or "") + (result.stderr or "")).strip().splitlines()
        if result.returncode == 0 and output:
            return f"{name} is installed: {output[0]}"
        return f"{name} isn't installed. Want me to set it up?"
    except Exception:
        return f"{name} isn't installed. Want me to set it up?"


def install_tool(name: str) -> str:
    """Opens a terminal with the install command typed in and ready — the
    user presses Enter to actually run it. Deliberately not automatic:
    installing software system-wide should be a decision someone makes on
    purpose, not something that happens because a sentence was misheard."""
    key = (name or "").strip().lower()
    check = _TOOL_CHECKS.get(key)
    if not check:
        return f"I don't have a known installer for {name}. Search winget for it, or install it manually."
    package_id = check[1]
    command = f"winget install -e --id {package_id}"
    try:
        subprocess.Popen(
            f'start "Install {name}" cmd /K "echo Ready to install {name}. '
            f'Press Enter to run, or close this window to cancel. && '
            f'echo. && set /p x= && {command}"',
            shell=True,
        )
        return f"Opened a terminal ready to install {name} — press Enter there to go ahead, or just close it to cancel."
    except Exception as e:
        return f"Couldn't open the installer ({e}). Run this yourself if you want it: {command}"


def save_code_project(code: str, language: str, project_name: str) -> str:
    """Saves code as a real file in a real project folder on the Desktop
    (not a temp folder that gets wiped), then opens that folder so it's
    right there to work on."""
    if not (code or "").strip():
        return "No code to save."
    name = "".join(c for c in (project_name or "project").strip() if c not in '<>:"/\\|?*') or "project"
    ext = _EXT_MAP.get((language or "").strip().lower(), "txt")
    folder = os.path.join(_PROJECT_ROOT, name)
    filename = f"main.{ext}"
    path = os.path.join(folder, filename)
    try:
        os.makedirs(folder, exist_ok=True)
        # Don't clobber an existing file — number it instead.
        counter = 2
        while os.path.exists(path):
            path = os.path.join(folder, f"main_{counter}.{ext}")
            counter += 1
        with open(path, "w", encoding="utf-8") as f:
            f.write(code)
    except Exception as e:
        return f"Couldn't save it ({e})."

    try:
        # Prefer opening in VS Code if it's there; fall back to Explorer.
        result = subprocess.run("code --version", shell=True, capture_output=True, timeout=8)
        if result.returncode == 0:
            subprocess.Popen(f'code "{folder}"', shell=True)
            return f"Saved to {path} and opened the project in VS Code."
    except Exception:
        pass
    try:
        os.startfile(folder)
    except Exception:
        pass
    return f"Saved to {path} and opened the folder."
