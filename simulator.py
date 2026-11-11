"""
simulator.py — Simulation mode.

Two things live here, and they are independent of each other:

1. A VIRTUAL PC. While simulation is switched on, every action that would
   touch the real machine (opening apps, moving the cursor, typing, volume,
   brightness, lock / sleep / shutdown, clipboard, folders, Gmail drafts...)
   is routed here instead. Nothing real happens: the action is applied to an
   in-memory model of a desktop, and the UI draws that model live in the
   SIMULATION DECK. Read-only actions (the time, real CPU/RAM stats, history
   search) still run for real, because they are harmless and more useful that
   way.

2. An OFFLINE BRAIN. A small rule-based intent parser that turns a typed or
   spoken command into the same {action, reply, ...} shape the LLM returns.
   It is used when there is no API key at all (so Jarvis can be tried with
   zero setup), and as a fallback if the LLM call fails while simulating. It
   is deliberately simple: it recognises commands, it does not hold a real
   conversation.

The virtual PC is per-process and resets when Jarvis restarts.
"""
import base64
import hashlib
import re
import threading
import time
from datetime import datetime

import memory

_lock = threading.Lock()

SHUTDOWN_DELAY_SECONDS = 10
MAX_WINDOWS = 6
MAX_LOG = 8

ZONES = {
    "center": (50, 50), "top left": (12, 14), "top right": (88, 14),
    "bottom left": (12, 84), "bottom right": (88, 84), "top": (50, 12), "bottom": (50, 86),
}

# Apps the virtual desktop knows how to dress up. Anything else still opens,
# as a generic window.
_APP_KINDS = {
    "chrome": "browser", "google chrome": "browser", "edge": "browser", "firefox": "browser",
    "browser": "browser", "notepad": "editor", "vscode": "editor", "vs code": "editor",
    "visual studio code": "editor", "word": "editor", "spotify": "media", "vlc": "media",
    "youtube": "browser", "calculator": "tool", "calc": "tool", "task manager": "tool",
    "file explorer": "files", "explorer": "files", "files": "files", "terminal": "terminal",
    "cmd": "terminal", "powershell": "terminal", "paint": "tool", "discord": "chat",
    "steam": "tool", "gmail": "browser",
}

_FAKE_INBOX = [
    ("Pepper Potts", "Board meeting moved to 3 PM"),
    ("Happy Hogan", "Car is ready when you are"),
    ("Stark Industries IT", "Scheduled maintenance tonight"),
    ("Colonel Rhodes", "Lunch on Thursday?"),
    ("Dr. Banner", "Those gamma readings you asked for"),
]


def _fresh_state() -> dict:
    return {
        "power": "on",            # on | locked | sleeping | shutdown_pending | restart_pending | off
        "pending_until": 0.0,     # epoch seconds, for the two *_pending states
        "windows": [],            # [{id, app, title, kind, detail, text, layout}]
        "next_id": 1,
        "volume": 55,
        "muted": False,
        "brightness": 80,
        "cursor": {"x": 50, "y": 50},
        "media": "stopped",       # stopped | playing | paused
        "now_playing": "",
        "clipboard": "",
        "folders": [],
        "screenshots": 0,
        "drafts": 0,
        "flash": 0,               # bumped on every screenshot so the UI can flash once
        "click": 0,               # bumped on every click so the UI can ripple once
        "log": [],                # most recent events, newest last
    }


_state = _fresh_state()


# ---------- switch ----------

def is_enabled() -> bool:
    return bool(memory.load().get("simulation", False))


def set_enabled(enabled: bool) -> str:
    data = memory.load()
    data["simulation"] = bool(enabled)
    memory.save(data)
    return "Simulation mode engaged." if enabled else "Simulation mode disengaged."


# ---------- state helpers ----------

def _log(event: str):
    _state["log"].append({"t": datetime.now().strftime("%H:%M:%S"), "event": event})
    del _state["log"][:-MAX_LOG]


def _settle():
    """Resolve a pending shutdown/restart whose countdown has run out."""
    if _state["power"] in ("shutdown_pending", "restart_pending") and time.time() >= _state["pending_until"]:
        restarting = _state["power"] == "restart_pending"
        _state["windows"] = []
        _state["media"] = "stopped"
        _state["now_playing"] = ""
        _state["pending_until"] = 0.0
        _state["power"] = "on" if restarting else "off"
        _log("Virtual PC restarted" if restarting else "Virtual PC powered off")


def _wake() -> str:
    """Most actions need a running, unlocked desktop. Rather than refusing,
    bring the virtual PC back first and say so in the result."""
    _settle()
    power = _state["power"]
    if power == "on" or power.endswith("_pending"):
        return ""
    _state["power"] = "on"
    note = {"locked": "Unlocked the virtual PC first. ",
            "sleeping": "Woke the virtual PC first. ",
            "off": "Booted the virtual PC first. "}.get(power, "")
    _log(note.strip())
    return note


def _focused():
    visible = [w for w in _state["windows"] if w["layout"] != "min"]
    return visible[-1] if visible else None


def _find_window(name: str):
    name = (name or "").strip().lower()
    if not name:
        return None
    for w in reversed(_state["windows"]):
        if name in w["app"].lower() or w["app"].lower() in name:
            return w
    return None


def _open_window(app: str, title: str = "", kind: str = "", detail: str = "") -> dict:
    app = (app or "App").strip() or "App"
    existing = _find_window(app)
    if existing:
        _state["windows"].remove(existing)
        _state["windows"].append(existing)   # bring to front
        if existing["layout"] == "min":
            existing["layout"] = "normal"
        if title:
            existing["title"] = title
        if detail:
            existing["detail"] = detail
        return existing
    win = {
        "id": _state["next_id"], "app": app.title() if app.islower() else app,
        "title": title or (app.title() if app.islower() else app),
        "kind": kind or _APP_KINDS.get(app.lower(), "app"),
        "detail": detail, "text": "", "layout": "normal",
    }
    _state["next_id"] += 1
    _state["windows"].append(win)
    del _state["windows"][:-MAX_WINDOWS]
    return win


def snapshot() -> dict:
    """What the UI draws. Safe to call any time."""
    with _lock:
        _settle()
        snap = {k: v for k, v in _state.items() if k not in ("next_id", "pending_until")}
        snap["windows"] = [dict(w) for w in _state["windows"]]
        snap["cursor"] = dict(_state["cursor"])
        snap["log"] = list(_state["log"])
        snap["folders"] = list(_state["folders"])
        snap["pending_seconds"] = (
            max(0, round(_state["pending_until"] - time.time()))
            if _state["power"].endswith("_pending") else 0
        )
        return snap


def reset() -> dict:
    global _state
    with _lock:
        _state = _fresh_state()
        _log("Virtual PC reset")
    return snapshot()


# ---------- simulated actions ----------
# Each takes the action dict the brain produced and returns a plain-language
# result, exactly like the real handlers in pc_control do.

def _open_app(d):
    note = _wake()
    name = (d.get("app") or "").strip()
    if not name:
        return "No app was named."
    win = _open_window(name)
    _log(f"Opened {win['app']}")
    return f"{note}Opened {win['app']} on the virtual desktop."


def _close_app(d):
    note = _wake()
    name = (d.get("app") or "").strip()
    win = _find_window(name) if name else _focused()
    if not win:
        return f"{note}{name or 'That'} isn't open on the virtual desktop."
    _state["windows"].remove(win)
    if win["kind"] == "media" or (_state["now_playing"] and "youtube" in win["title"].lower()):
        _state["media"], _state["now_playing"] = "stopped", ""
    _log(f"Closed {win['app']}")
    return f"{note}Closed {win['app']}."


def _open_url(d):
    note = _wake()
    url = (d.get("url") or "").strip()
    if not url:
        return "No address was given."
    shown = re.sub(r"^https?://", "", url).rstrip("/")
    _open_window("Browser", title=shown, kind="browser", detail=shown)
    _log(f"Navigated to {shown}")
    return f"{note}Opened {shown} in the virtual browser."


def _play_on_youtube(d):
    note = _wake()
    query = (d.get("query") or "").strip()
    if not query:
        return "Nothing to search for."
    _open_window("Browser", title=f"YouTube — {query}", kind="browser",
                 detail=f"youtube.com/results?search_query={query.replace(' ', '+')}")
    _state["media"], _state["now_playing"] = "playing", query
    _log(f"YouTube: {query}")
    return f"{note}Pulled up YouTube results for '{query}' in the virtual browser."


def _move_cursor(d):
    note = _wake()
    zone = (d.get("zone") or "center").strip().lower()
    x, y = ZONES.get(zone, ZONES["center"])
    _state["cursor"] = {"x": x, "y": y}
    _log(f"Cursor → {zone}")
    return f"{note}Moved the virtual cursor to the {zone}."


def _click(d):
    note = _wake()
    button = (d.get("button") or "left").strip().lower()
    _state["click"] += 1
    _log(f"{button.title()} click")
    return f"{note}{button.title()}-clicked at the virtual cursor."


def _double_click(d):
    note = _wake()
    _state["click"] += 1
    _log("Double click")
    return f"{note}Double-clicked at the virtual cursor."


def _scroll(d):
    note = _wake()
    try:
        amount = int(d.get("amount") or 10)
    except (TypeError, ValueError):
        amount = 10
    direction = "up" if amount >= 0 else "down"
    _log(f"Scrolled {direction}")
    return f"{note}Scrolled {direction} in the virtual window."


def _type_text(d):
    note = _wake()
    text = d.get("text") or ""
    if not text:
        return "Nothing to type."
    win = _focused() or _open_window("Notepad")
    win["text"] = (win["text"] + text)[-400:]
    _log(f"Typed {len(text)} chars into {win['app']}")
    return f"{note}Typed that into {win['app']}."


def _press_key(d):
    note = _wake()
    key = (d.get("key") or "enter").strip().lower()
    win = _focused()
    if win and key == "enter" and win["text"]:
        win["text"] = (win["text"] + "\n")[-400:]
    _log(f"Pressed {key}")
    return f"{note}Pressed {key}."


def _set_volume(d):
    note = _wake()
    direction = (d.get("direction") or "up").strip().lower()
    step = -10 if direction == "down" else 10
    _state["volume"] = max(0, min(100, _state["volume"] + step))
    if step > 0:
        _state["muted"] = False
    _log(f"Volume {_state['volume']}%")
    return f"{note}Virtual volume is now {_state['volume']}%."


def _mute(d):
    note = _wake()
    _state["muted"] = not _state["muted"]
    _log("Muted" if _state["muted"] else "Unmuted")
    return f"{note}{'Muted' if _state['muted'] else 'Unmuted'} the virtual speakers."


def _set_brightness(d):
    note = _wake()
    level = d.get("level")
    direction = (d.get("direction") or "").strip().lower()
    try:
        # 0 is what an LLM sends for "field not used", so only trust an
        # explicit level when no direction was given alongside it.
        level = int(level) if level not in (None, "") else None
    except (TypeError, ValueError):
        level = None
    if direction in ("up", "down"):
        _state["brightness"] += 15 if direction == "up" else -15
    elif level is not None:
        _state["brightness"] = level
    _state["brightness"] = max(5, min(100, _state["brightness"]))
    _log(f"Brightness {_state['brightness']}%")
    return f"{note}Virtual brightness is now {_state['brightness']}%."


def _screenshot(d):
    note = _wake()
    _state["screenshots"] += 1
    _state["flash"] += 1
    _log(f"Screenshot #{_state['screenshots']}")
    return f"{note}Captured virtual screenshot number {_state['screenshots']}. Nothing was saved to disk."


def _describe_screen() -> str:
    power = _state["power"]
    if power != "on" and not power.endswith("_pending"):
        return f"The virtual PC is {power}."
    wins = [w for w in _state["windows"] if w["layout"] != "min"]
    if not wins:
        return "The virtual desktop is empty — no windows open."
    names = ", ".join(w["title"] for w in wins)
    front = wins[-1]
    extra = f" The focused window is {front['title']}."
    if front["text"]:
        extra += f" It contains the text: {front['text'].strip()[:160]}"
    return f"{len(wins)} window{'s' if len(wins) != 1 else ''} open on the virtual desktop: {names}.{extra}"


def _read_screen(d):
    return _describe_screen()


def _lock_pc(d):
    _settle()
    _state["power"] = "locked"
    _log("Locked")
    return "Virtual PC locked."


def _sleep_pc(d):
    _settle()
    _state["power"] = "sleeping"
    _log("Sleeping")
    return "Virtual PC is asleep."


def _shutdown_pc(d):
    _wake()
    _state["power"] = "shutdown_pending"
    _state["pending_until"] = time.time() + SHUTDOWN_DELAY_SECONDS
    _log("Shutdown countdown started")
    return f"Virtual shutdown in {SHUTDOWN_DELAY_SECONDS} seconds. Say 'cancel shutdown' to stop it."


def _restart_pc(d):
    _wake()
    _state["power"] = "restart_pending"
    _state["pending_until"] = time.time() + SHUTDOWN_DELAY_SECONDS
    _log("Restart countdown started")
    return f"Virtual restart in {SHUTDOWN_DELAY_SECONDS} seconds. Say 'cancel shutdown' to stop it."


def _cancel_shutdown(d):
    _settle()
    if not _state["power"].endswith("_pending"):
        return "There's no virtual shutdown pending."
    _state["power"] = "on"
    _state["pending_until"] = 0.0
    _log("Shutdown cancelled")
    return "Virtual shutdown cancelled."


def _media_control(d):
    note = _wake()
    cmd = (d.get("text") or "").strip().lower()
    if cmd in ("pause", "stop"):
        _state["media"] = "paused" if _state["now_playing"] else "stopped"
    elif cmd in ("next", "previous"):
        _state["media"] = "playing"
        _state["now_playing"] = f"{cmd} track"
    else:
        cmd = "play"
        _state["media"] = "playing"
        _state["now_playing"] = _state["now_playing"] or "your queue"
    _log(f"Media: {cmd}")
    return f"{note}Virtual media: {cmd}."


def _window_control(d):
    note = _wake()
    cmd = (d.get("text") or "").strip().lower()
    if cmd == "show desktop":
        for w in _state["windows"]:
            w["layout"] = "min"
        _log("Show desktop")
        return f"{note}Minimized everything on the virtual desktop."
    win = _focused()
    if cmd == "switch":
        visible = [w for w in _state["windows"] if w["layout"] != "min"]
        if len(visible) < 2:
            return f"{note}There's nothing else to switch to."
        back = visible[0]
        _state["windows"].remove(back)
        _state["windows"].append(back)
        _log(f"Switched to {back['app']}")
        return f"{note}Switched to {back['app']}."
    if not win:
        return f"{note}No window is open on the virtual desktop."
    if cmd == "close":
        _state["windows"].remove(win)
        _log(f"Closed {win['app']}")
        return f"{note}Closed {win['app']}."
    layout = {"minimize": "min", "maximize": "max", "snap left": "left", "snap right": "right"}.get(cmd)
    if not layout:
        return f"{note}I don't know the window command '{cmd}'."
    win["layout"] = layout
    _log(f"{win['app']}: {cmd}")
    return f"{note}{win['app']}: {cmd}."


def _open_folder(d):
    note = _wake()
    name = (d.get("text") or "documents").strip()
    label = name.replace("\\", "/").rstrip("/").split("/")[-1].title() or "Folder"
    _open_window("File Explorer", title=f"File Explorer — {label}", kind="files", detail=label)
    _log(f"Opened folder {label}")
    return f"{note}Opened the {label} folder on the virtual desktop."


def _find_file(d):
    query = (d.get("query") or "").strip()
    if not query:
        return "Nothing to search for."
    _log(f"Searched files: {query}")
    return (f"Simulated search for '{query}'. Your real folders were not read — "
            "switch simulation off to search them.")


def _create_folder(d):
    note = _wake()
    name = (d.get("text") or "New Folder").strip() or "New Folder"
    if name not in _state["folders"]:
        _state["folders"].append(name)
        del _state["folders"][:-8]
    _log(f"Created folder {name}")
    return f"{note}Created a folder called '{name}' on the virtual desktop."


def _clipboard_read(d):
    clip = _state["clipboard"]
    return f"The virtual clipboard holds: {clip}" if clip else "The virtual clipboard is empty."


def _clipboard_write(d):
    _state["clipboard"] = (d.get("text") or "")[:300]
    _log("Clipboard updated")
    return "Copied that to the virtual clipboard."


def _install_tool(d):
    name = (d.get("text") or "that tool").strip()
    _log(f"Install skipped: {name}")
    return f"Simulation: would have opened a terminal with the install command for {name}. Nothing was installed."


def _save_code_project(d):
    note = _wake()
    name = (d.get("text") or "project").strip() or "project"
    win = _open_window("VS Code", title=f"VS Code — {name}", kind="editor")
    win["text"] = (d.get("code") or "")[:400]
    _log(f"Opened project {name}")
    return f"{note}Simulation: opened '{name}' in a virtual editor. No files were written to disk."


def _list_unread_mail(d):
    try:
        n = int(d.get("amount") or 5)
    except (TypeError, ValueError):
        n = 5
    mails = _FAKE_INBOX[:max(1, min(n, len(_FAKE_INBOX)))]
    lines = [f"{i + 1}) {sender} — {subject}" for i, (sender, subject) in enumerate(mails)]
    _log("Checked simulated inbox")
    return f"{len(mails)} unread in the simulated inbox: " + "; ".join(lines)


def _draft_email_reply(d):
    target = (d.get("query") or "the latest email").strip()
    _state["drafts"] += 1
    _log(f"Draft #{_state['drafts']}")
    return f"Simulation: drafted a reply to {target}. Nothing was written to your real Gmail."


def _forget_everything(d):
    _log("Memory wipe skipped")
    return "Simulation: I would have wiped everything I know about you. Your real memory is untouched."


def _generate_image(d):
    return ""   # the picture itself is produced by placeholder_image(), called from server.py


SIM_DISPATCH = {
    "open_app": _open_app, "close_app": _close_app, "open_url": _open_url,
    "play_on_youtube": _play_on_youtube, "move_cursor": _move_cursor, "click": _click,
    "double_click": _double_click, "scroll": _scroll, "type_text": _type_text,
    "press_key": _press_key, "set_volume": _set_volume, "mute": _mute,
    "set_brightness": _set_brightness, "screenshot": _screenshot, "read_screen": _read_screen,
    "lock_pc": _lock_pc, "sleep_pc": _sleep_pc, "shutdown_pc": _shutdown_pc,
    "restart_pc": _restart_pc, "cancel_shutdown": _cancel_shutdown,
    "media_control": _media_control, "window_control": _window_control,
    "open_folder": _open_folder, "find_file": _find_file, "create_folder": _create_folder,
    "clipboard_read": _clipboard_read, "clipboard_write": _clipboard_write,
    "install_tool": _install_tool, "save_code_project": _save_code_project,
    "list_unread_mail": _list_unread_mail, "draft_email_reply": _draft_email_reply,
    "forget_everything": _forget_everything, "generate_image": _generate_image,
}

# Simulated actions whose result is the actual answer, not just a confirmation.
PREFER_RESULT = {"read_screen", "clipboard_read", "find_file", "list_unread_mail",
                 "draft_email_reply", "forget_everything", "install_tool", "save_code_project"}


def handles(action: str) -> bool:
    return action in SIM_DISPATCH


def run(action: str, data: dict) -> str:
    """Apply one action to the virtual PC and return its result text."""
    handler = SIM_DISPATCH.get(action)
    if not handler:
        return ""
    with _lock:
        return handler(data or {}) or ""


def wake() -> dict:
    """Unlock / wake / boot the virtual PC (clicking its lock screen in the UI)."""
    with _lock:
        _wake()
    return snapshot()


def placeholder_image(prompt: str):
    """A deterministic abstract SVG standing in for a generated image, so the
    image flow can be demonstrated without spending image-model quota.
    Returns (base64, mime)."""
    digest = hashlib.sha256((prompt or "jarvis").encode("utf-8")).digest()
    hue = digest[0] * 360 // 256
    shapes = []
    for i in range(7):
        b = digest[1 + i * 4: 5 + i * 4]
        cx, cy = 40 + b[0] * 432 // 255, 40 + b[1] * 304 // 255
        r = 30 + b[2] * 110 // 255
        h = (hue + b[3] * 90 // 255) % 360
        shapes.append(f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="hsl({h},80%,60%)" opacity="0.32"/>')
    label = re.sub(r"[<>&\"']", "", (prompt or "").strip())[:54]
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 384" width="512" height="384">'
        f'<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1">'
        f'<stop offset="0" stop-color="hsl({hue},60%,12%)"/>'
        f'<stop offset="1" stop-color="hsl({(hue + 60) % 360},70%,6%)"/></linearGradient>'
        '<filter id="b"><feGaussianBlur stdDeviation="18"/></filter></defs>'
        '<rect width="512" height="384" fill="url(#g)"/>'
        f'<g filter="url(#b)">{"".join(shapes)}</g>'
        '<rect x="14" y="14" width="484" height="356" fill="none" stroke="rgba(255,255,255,.25)"/>'
        '<text x="28" y="44" font-family="monospace" font-size="12" letter-spacing="3" '
        'fill="rgba(255,255,255,.75)">SIMULATED RENDER</text>'
        f'<text x="28" y="352" font-family="monospace" font-size="13" fill="rgba(255,255,255,.9)">{label}</text>'
        '</svg>'
    )
    return base64.b64encode(svg.encode("utf-8")).decode("ascii"), "image/svg+xml"


# ---------- offline brain ----------

_SITES = {"youtube": "youtube.com", "google": "google.com", "gmail": "mail.google.com",
          "github": "github.com", "reddit": "reddit.com", "twitter": "x.com", "x": "x.com",
          "wikipedia": "wikipedia.org", "netflix": "netflix.com", "amazon": "amazon.com",
          "instagram": "instagram.com", "whatsapp": "web.whatsapp.com", "chatgpt": "chatgpt.com"}
_FOLDERS = ("downloads", "documents", "desktop", "pictures", "music", "videos")

IDLE_LINES = [
    "All quiet on the virtual front, sir.",
    "Simulation holding steady. Nothing has caught fire, real or otherwise.",
    "I remain at your disposal, sir, in a strictly hypothetical capacity.",
    "The virtual desktop is immaculate. I take a certain pride in that.",
    "Standing by, sir. The sandbox is yours whenever you want it.",
]

HELP_TEXT = (
    "I'm running on the offline simulation core, sir, so I recognise commands rather than "
    "conversation. Try: open chrome, play lo-fi on youtube, volume up, set brightness to 40, "
    "type hello world, take a screenshot, snap left, lock my PC, or shut down. "
    "Everything happens on the virtual desktop, not your real one. "
    "Add an API key in settings for the full brain."
)


def _clean(text: str, keep_punctuation: bool = False) -> str:
    text = (text or "").strip()
    text = re.sub(r"^(hey |ok |okay )?jarvis[,:]?\s*", "", text, flags=re.I)
    text = re.sub(r"^(please|can you|could you|would you|will you|kindly)\s+", "", text, flags=re.I)
    return text.strip() if keep_punctuation else text.strip().rstrip(".!?").strip()


def _strip_article(s: str) -> str:
    return re.sub(r"^(the|my|a|an|up)\s+", "", s.strip(), flags=re.I).strip()


def offline_think(user_text: str) -> dict:
    """Rule-based stand-in for the LLM: returns {action, reply, ...fields}."""
    raw = _clean(user_text)
    t = raw.lower()

    def out(action, reply, **fields):
        return {"action": action, "reply": reply, **fields}

    if not t:
        return out("chat", "I didn't catch that, sir.")

    # --- power (cancel first: "cancel shutdown" contains "shutdown") ---
    if re.search(r"\b(cancel|abort|stop)\b.*\b(shut ?down|restart|reboot)\b", t):
        return out("cancel_shutdown", "Standing down, sir.")
    if re.search(r"\b(shut ?down|power off|turn off (the |my )?(pc|computer|laptop))\b", t):
        return out("shutdown_pc", "Shutting down in ten seconds, sir. Say cancel shutdown if you reconsider.")
    if re.search(r"\b(restart|reboot)\b", t):
        return out("restart_pc", "Restarting in ten seconds, sir.")
    if re.search(r"\b(unlock|wake up|wake (the |my )?(pc|computer|laptop)|power on|boot( up)?)\b", t):
        wake()   # there is no real-world "unlock" action; this only exists on the virtual PC
        return out("chat", "The virtual PC is up and unlocked, sir.")
    if re.search(r"\block\b", t):
        return out("lock_pc", "Locked, sir.")
    if re.search(r"\b(sleep|hibernate)\b", t):
        return out("sleep_pc", "Putting it to sleep, sir.")

    # --- settings ---
    if "hindi" in t and re.search(r"\b(switch|speak|talk|change|reply)\b", t):
        return out("set_language", "Hindi mode, sir.", language="hi")
    if "english" in t and re.search(r"\b(switch|speak|talk|change|reply)\b", t):
        return out("set_language", "English it is, sir.", language="en")
    if re.search(r"\b(stop|no|quit) (swearing|cursing)\b|\bclean language\b", t):
        return out("set_profanity", "Perfectly civil from here on, sir.", profanity_level="off")
    if re.search(r"\b(swear|curse) more\b", t):
        return out("set_profanity", "As you wish, sir.", profanity_level="full")

    # --- memory ---
    if re.search(r"\bforget everything\b", t):
        return out("forget_everything", "Understood, sir.")
    m = re.match(r"remember (?:that )?(.+)", raw, flags=re.I)
    if m:
        return out("remember", "Noted, sir.", fact=m.group(1).strip())

    # --- info ---
    if re.search(r"\b(what(?:'s| is) the time|what time|current time|the time)\b", t):
        return out("get_time", "One moment, sir.")
    if re.search(r"\b(cpu|ram|memory usage|temperature|stats|how(?:'s| is) my (pc|computer|laptop|system))\b", t):
        return out("get_stats", "Reading the sensors, sir.")
    if re.search(r"\b(what(?:'s| is) on (my|the) screen|read (my|the) screen|describe (my|the) screen)\b", t):
        return out("read_screen", "Having a look, sir.", query="")
    if re.search(r"\bclipboard\b", t):
        m = re.match(r"(?:copy|put|save) (.+?) (?:to|on|in|into) (?:the |my )?clipboard", raw, flags=re.I)
        if m:
            return out("clipboard_write", "Copied, sir.", text=m.group(1).strip())
        return out("clipboard_read", "Checking the clipboard, sir.")

    # --- mail ---
    m = re.match(r"(?:draft|write) (?:a |an )?(?:reply|response|email) to (.+?)(?: saying (.+))?$", raw, flags=re.I)
    if m:
        return out("draft_email_reply", "Drafting it now, sir.", query=m.group(1).strip(),
                   text=(m.group(2) or "").strip())
    if re.search(r"\b(inbox|unread|e-?mails?|mail)\b", t):
        return out("list_unread_mail", "Checking your inbox, sir.", amount=5)

    # --- image ---
    m = re.match(r"(?:generate|draw|create|make|paint)(?: me)? (?:an? )?(?:image|picture|photo|drawing|painting)?"
                 r"(?: of)?\s*(.+)", raw, flags=re.I)
    if m and re.search(r"\b(generate|draw|paint|image|picture|photo)\b", t) and "folder" not in t:
        subject = m.group(1).strip() or "something abstract"
        return out("generate_image", f"Rendering {subject}, sir.", query=subject)

    # --- audio / display ---
    if re.search(r"\bunmute\b|\bmute\b", t):
        return out("mute", "Done, sir.")
    if re.search(r"\b(volume|louder|quieter|turn it (up|down)|sound)\b", t):
        down = bool(re.search(r"\b(down|lower|quieter|decrease|reduce|softer)\b", t))
        return out("set_volume", "Volume adjusted, sir.", direction="down" if down else "up")
    if re.search(r"\b(brightness|brighter|dim|dimmer)\b", t):
        m = re.search(r"(\d{1,3})", t)
        if m:
            return out("set_brightness", "Brightness set, sir.", level=int(m.group(1)), direction="")
        down = bool(re.search(r"\b(down|lower|dim|dimmer|decrease|reduce)\b", t))
        return out("set_brightness", "Brightness adjusted, sir.", direction="down" if down else "up")
    if re.search(r"\bscreen ?shot\b|\bcapture (the |my )?screen\b", t):
        return out("screenshot", "Captured, sir.")

    # --- media ---
    m = re.match(r"play (.+?)(?: on youtube)?$", raw, flags=re.I)
    if m and m.group(1).lower() not in ("music", "it", "the music", "song", "the song"):
        query = m.group(1).strip()
        return out("play_on_youtube", f"Pulling up results for {query}, sir.", query=query)
    if re.search(r"\b(pause|resume|next (song|track)|previous (song|track)|skip)\b|^play\b|^next$|^previous$", t):
        cmd = ("pause" if "pause" in t else "next" if re.search(r"\b(next|skip)\b", t)
               else "previous" if "previous" in t else "play")
        return out("media_control", "Done, sir.", text=cmd)

    # --- windows ---
    for phrase, cmd in (("show desktop", "show desktop"), ("snap left", "snap left"),
                        ("snap right", "snap right"), ("minimi", "minimize"),
                        ("maximi", "maximize"), ("switch window", "switch"), ("alt tab", "switch")):
        if phrase in t:
            return out("window_control", "Done, sir.", text=cmd)

    # --- mouse / keyboard ---
    # match against the un-trimmed text: "type Hello." should keep its full stop
    m = re.match(r"type (?:out )?(.+)", _clean(user_text, keep_punctuation=True), flags=re.I | re.S)
    if m:
        return out("type_text", "Typed, sir.", text=m.group(1).strip().strip("\"'"))
    m = re.match(r"(?:press|hit) (?:the )?(.+?)(?: key)?$", raw, flags=re.I)
    if m:
        return out("press_key", "Pressed, sir.", key=m.group(1).strip().lower())
    if re.search(r"\bscroll\b", t):
        return out("scroll", "Scrolling, sir.", amount=10 if "up" in t else -10)
    if re.search(r"\bdouble[- ]click\b", t):
        return out("double_click", "Done, sir.")
    if re.search(r"\b(move|put|send)\b.*\b(cursor|mouse|pointer)\b", t):
        zone = next((z for z in sorted(ZONES, key=len, reverse=True) if z in t), "center")
        if zone == "center" and re.search(r"\b(middle|centre)\b", t):
            zone = "center"
        return out("move_cursor", f"Cursor to the {zone}, sir.", zone=zone)
    if re.search(r"\bclick\b", t):
        return out("click", "Clicked, sir.", button="right" if "right" in t else "left")

    # --- files / folders ---
    m = re.match(r"(?:create|make|new) (?:a |an )?(?:new )?folder(?: (?:called|named))?\s*(.*)", raw, flags=re.I)
    if m:
        name = m.group(1).strip().strip("\"'") or "New Folder"
        return out("create_folder", f"Folder {name} created, sir.", text=name)
    m = re.match(r"(?:find|search for|locate|look for) (?:the |my |a )?(?:file )?(?:called |named )?(.+)", raw, flags=re.I)
    if m:
        return out("find_file", "Searching, sir.", query=m.group(1).strip())

    # --- open / close ---
    m = re.match(r"(?:open|launch|start|run|go to|visit|bring up|pull up|fire up) (.+)", raw, flags=re.I)
    if m:
        target = _strip_article(m.group(1))
        low = target.lower()
        folder = next((f for f in _FOLDERS if low in (f, f + " folder")), None)
        if folder or low.endswith(" folder"):
            return out("open_folder", "Right away, sir.", text=folder or low[:-7].strip())
        if low in _SITES:
            return out("open_url", "Right away, sir.", url=_SITES[low])
        if re.search(r"^[\w.-]+\.[a-z]{2,}(/\S*)?$", low):
            return out("open_url", "Right away, sir.", url=low)
        return out("open_app", "Right away, sir.", app=target)
    m = re.match(r"(?:close|quit|exit|kill|end) (.+)", raw, flags=re.I)
    if m:
        return out("close_app", "Closed, sir.", app=_strip_article(m.group(1)))

    # --- small talk ---
    if re.search(r"\b(help|what can you do|commands|what do you do)\b", t):
        return out("chat", HELP_TEXT)
    if re.match(r"(hi|hello|hey|good (morning|afternoon|evening))\b", t):
        return out("chat", "Good to see you, sir. The simulation is live — give me something to do.")
    if re.search(r"\b(who are you|your name)\b", t):
        return out("chat", "JARVIS, sir. Currently running on the offline simulation core, "
                           "which is to say: all of the manners, a fraction of the intellect.")
    if re.search(r"\b(thanks|thank you|cheers)\b", t):
        return out("chat", "Always, sir.")
    if re.search(r"\bsimulat", t):
        return out("chat", "In simulation mode nothing I do touches your real machine, sir. "
                           "Every action lands on the virtual desktop in the simulation deck instead.")

    return out("chat", "The offline simulation core only understands commands, sir — say help "
                       "for the list, or add an API key in settings to bring the full brain online.")
