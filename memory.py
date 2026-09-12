"""
memory.py — Jarvis's long-term memory.

Everything here lives in one small JSON file (jarvis_memory.json): your API
key (so you're never asked twice), your name, and any facts Jarvis has
picked up about you. Delete the file any time for a clean slate, or just say
"forget everything about me."

Stored in %APPDATA%\\Jarvis\\ rather than next to the script — this matters
once this runs as a packaged .exe: a script's own folder can be read-only
(e.g. installed under Program Files) and, for a PyInstaller onefile build,
doesn't even reliably exist as a stable path at all (the exe unpacks itself
into a fresh temp folder every launch). AppData is always per-user writable
and always persists.
"""
import json
import os

_APPDATA = os.environ.get("APPDATA") or os.path.expanduser("~")
_DIR = os.path.join(_APPDATA, "Jarvis")
os.makedirs(_DIR, exist_ok=True)
_PATH = os.path.join(_DIR, "jarvis_memory.json")

_DEFAULTS = {"api_key": "", "api_keys": [], "active_key_index": 0, "name": "", "facts": [],
             "language": "en", "profanity": "medium", "theme": "dark", "voice": "",
             "idle_chatter": True}


def load() -> dict:
    if os.path.exists(_PATH):
        try:
            with open(_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            for key, default in _DEFAULTS.items():
                data.setdefault(key, default)
            # Migrate anyone upgrading from the single-key version: their
            # existing api_key becomes the first entry in the new list, so
            # nobody has to re-enter a key they already set up.
            if data.get("api_key") and not data.get("api_keys"):
                data["api_keys"] = [data["api_key"]]
            return data
        except Exception:
            pass  # corrupt/unreadable file — fall back to a clean slate
    return dict(_DEFAULTS)


def get_api_keys() -> list:
    """All stored keys, in the order they should be tried."""
    data = load()
    keys = [k for k in data.get("api_keys", []) if k]
    if not keys and data.get("api_key"):
        keys = [data["api_key"]]
    return keys


def set_api_keys(keys: list):
    """Replaces the whole key list. Resets the active pointer, since the
    old index may not mean anything against a different list."""
    cleaned = []
    for k in keys:
        k = (k or "").strip()
        if k and k not in cleaned:  # dedupe, keep order
            cleaned.append(k)
    data = load()
    data["api_keys"] = cleaned
    data["api_key"] = cleaned[0] if cleaned else ""  # keep the old field in sync
    data["active_key_index"] = 0
    save(data)
    return cleaned


def get_active_key_index() -> int:
    data = load()
    idx = data.get("active_key_index", 0)
    keys = get_api_keys()
    if not keys:
        return 0
    return idx if 0 <= idx < len(keys) else 0


def set_active_key_index(index: int):
    """Remembers which key last worked, so the next request starts there
    instead of re-trying keys already known to be dead."""
    data = load()
    data["active_key_index"] = index
    keys = get_api_keys()
    if 0 <= index < len(keys):
        data["api_key"] = keys[index]  # keep the legacy field pointing at the live key
    save(data)


def save(data: dict):
    with open(_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def remember(fact: str) -> str:
    fact = (fact or "").strip()
    if not fact:
        return "There was nothing there to remember."
    data = load()
    if fact not in data["facts"]:
        data["facts"].append(fact)
        save(data)
    return f"Noted: {fact}"


def forget_all() -> str:
    save(dict(_DEFAULTS))
    return "Wiped everything I knew about you. Fresh start."


def get_voice() -> str:
    return load().get("voice", "") or ""


def set_voice(voice_id: str) -> str:
    data = load()
    data["voice"] = (voice_id or "").strip()
    save(data)
    return "Voice updated."


def get_language() -> str:
    return load().get("language", "en")


def set_language(lang: str) -> str:
    lang = (lang or "").strip().lower()
    if lang not in ("en", "hi"):
        return "I only know English and Hindi right now."
    data = load()
    data["language"] = lang
    save(data)
    return "Switched to Hindi." if lang == "hi" else "Switched to English."


def get_profanity() -> str:
    return load().get("profanity", "medium")


def set_profanity(level: str) -> str:
    level = (level or "").strip().lower()
    if level not in ("off", "mild", "medium", "full"):
        return "That's not a profanity level I recognize."
    data = load()
    data["profanity"] = level
    save(data)
    return f"Profanity level set to {level}."


def get_idle_chatter() -> bool:
    return bool(load().get("idle_chatter", True))


def set_idle_chatter(enabled: bool) -> str:
    data = load()
    data["idle_chatter"] = bool(enabled)
    save(data)
    return "Idle chatter enabled." if enabled else "Idle chatter disabled."


def summary_for_prompt() -> str:
    """Short block spliced into Jarvis's system prompt so it has context
    on who you are without you repeating yourself every session."""
    data = load()
    lines = []
    if data.get("name"):
        lines.append(f"The user's name is {data['name']}. Address them by name occasionally.")
    if data.get("facts"):
        lines.append("Known facts/preferences about the user, remembered from earlier sessions:")
        lines.extend(f"- {f}" for f in data["facts"][-20:])  # keep the prompt lean
    return "\n".join(lines)
