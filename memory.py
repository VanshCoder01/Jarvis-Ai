"""
memory.py — Jarvis's long-term memory.

Everything here lives in one small JSON file (jarvis_memory.json) saved next
to these scripts: your API key (so you're never asked twice), your name, and
any facts Jarvis has picked up about you. Delete the file any time for a
clean slate, or just say "forget everything about me."
"""
import json
import os

_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "jarvis_memory.json")

_DEFAULTS = {"api_key": "", "name": "", "facts": [], "language": "en", "profanity": "medium"}


def load() -> dict:
    if os.path.exists(_PATH):
        try:
            with open(_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            for key, default in _DEFAULTS.items():
                data.setdefault(key, default)
            return data
        except Exception:
            pass  # corrupt/unreadable file — fall back to a clean slate
    return dict(_DEFAULTS)


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
