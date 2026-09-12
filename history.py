"""
history.py — persistent conversation history.

brain.py keeps a short rolling window in memory for context, but that dies
when the app closes. This keeps a real transcript on disk so past
conversations are still there tomorrow, and the UI can restore what you
were last talking about instead of opening blank every time.

Lives alongside jarvis_memory.json in %APPDATA%\\Jarvis\\.
"""
import json
import os
from datetime import datetime

_APPDATA = os.environ.get("APPDATA") or os.path.expanduser("~")
_DIR = os.path.join(_APPDATA, "Jarvis")
os.makedirs(_DIR, exist_ok=True)
_PATH = os.path.join(_DIR, "jarvis_history.json")

# Keep the file from growing without limit over months of use.
MAX_ENTRIES = 500


def load() -> list:
    if not os.path.exists(_PATH):
        return []
    try:
        with open(_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception:
        return []  # corrupt file shouldn't take the whole app down


def _save(entries: list):
    try:
        with open(_PATH, "w", encoding="utf-8") as f:
            json.dump(entries[-MAX_ENTRIES:], f, indent=2)
    except Exception:
        pass  # never let a failed write break a conversation


def add(user_text: str, reply: str, action: str = ""):
    entries = load()
    entries.append({
        "time": datetime.now().isoformat(timespec="seconds"),
        "user": user_text,
        "jarvis": reply,
        "action": action,
    })
    _save(entries)


def recent(count: int = 20) -> list:
    return load()[-count:]


def search(query: str, limit: int = 20) -> list:
    q = (query or "").strip().lower()
    if not q:
        return []
    hits = [e for e in load() if q in e.get("user", "").lower() or q in e.get("jarvis", "").lower()]
    return hits[-limit:]


def clear() -> str:
    _save([])
    return "Conversation history wiped."


# ---------- sessions ----------
_SESS_PATH = os.path.join(_DIR, "jarvis_sessions.json")


def _load_sessions() -> dict:
    if not os.path.exists(_SESS_PATH):
        return {"active": "", "sessions": []}
    try:
        with open(_SESS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        data.setdefault("active", "")
        data.setdefault("sessions", [])
        return data
    except Exception:
        return {"active": "", "sessions": []}


def _save_sessions(data: dict):
    try:
        with open(_SESS_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception:
        pass


def list_sessions() -> dict:
    """Pinned sessions first, then most recent. The UI renders this directly."""
    data = _load_sessions()
    sess = data["sessions"]
    sess.sort(key=lambda s: (not s.get("pinned"), s.get("updated", "")), reverse=False)
    sess.sort(key=lambda s: s.get("pinned", False), reverse=True)
    return {"active": data.get("active", ""), "sessions": sess}


def new_session(title: str = "") -> str:
    import uuid
    data = _load_sessions()
    sid = uuid.uuid4().hex[:12]
    data["sessions"].insert(0, {
        "id": sid,
        "title": title or "New session",
        "pinned": False,
        "created": datetime.now().isoformat(timespec="seconds"),
        "updated": datetime.now().isoformat(timespec="seconds"),
        "entries": [],
    })
    data["active"] = sid
    _save_sessions(data)
    return sid


def active_session_id() -> str:
    data = _load_sessions()
    if not data.get("active") or not any(s["id"] == data["active"] for s in data["sessions"]):
        return new_session()
    return data["active"]


def set_active(sid: str) -> bool:
    data = _load_sessions()
    if not any(s["id"] == sid for s in data["sessions"]):
        return False
    data["active"] = sid
    _save_sessions(data)
    return True


def toggle_pin(sid: str) -> bool:
    data = _load_sessions()
    for s in data["sessions"]:
        if s["id"] == sid:
            s["pinned"] = not s.get("pinned", False)
            _save_sessions(data)
            return s["pinned"]
    return False


def delete_session(sid: str) -> bool:
    data = _load_sessions()
    before = len(data["sessions"])
    data["sessions"] = [s for s in data["sessions"] if s["id"] != sid]
    if data.get("active") == sid:
        data["active"] = data["sessions"][0]["id"] if data["sessions"] else ""
    _save_sessions(data)
    return len(data["sessions"]) < before


def add_to_session(user_text: str, reply: str):
    """Appends to the active session and auto-titles it from the first
    thing actually said, so the list isn't a wall of 'New session'."""
    data = _load_sessions()
    sid = data.get("active")
    if not sid or not any(s["id"] == sid for s in data["sessions"]):
        sid = new_session()
        data = _load_sessions()
    for s in data["sessions"]:
        if s["id"] == sid:
            s["entries"].append({
                "time": datetime.now().isoformat(timespec="seconds"),
                "user": user_text, "jarvis": reply,
            })
            s["entries"] = s["entries"][-200:]
            s["updated"] = datetime.now().isoformat(timespec="seconds")
            if s["title"] == "New session" and user_text.strip():
                t = user_text.strip()
                s["title"] = (t[:34] + "\u2026") if len(t) > 34 else t
            break
    _save_sessions(data)


def session_entries(sid: str) -> list:
    for s in _load_sessions()["sessions"]:
        if s["id"] == sid:
            return s.get("entries", [])
    return []
