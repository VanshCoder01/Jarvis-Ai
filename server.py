"""
server.py — the bridge between the web UI (index.html) and the Python side
(the AI brain, PC control, TTS, memory). Runs locally only — SERVER_HOST is
127.0.0.1, so nothing outside this PC can reach it.
"""
import os
import sys

from flask import Flask, jsonify, request, send_file

import agents
import brain
import config
import history
import image_gen
import llm
import memory
import pc_control as pc
import tts

# When bundled into a onefile .exe (PyInstaller), files ship inside a
# temporary extraction folder at sys._MEIPASS, not next to this script —
# __file__-based paths silently point at the wrong place there otherwise.
if getattr(sys, "frozen", False):
    BASE_DIR = sys._MEIPASS
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

app = Flask(__name__)

GREETINGS = {
    "en": "All systems initialized and online. Welcome back, sir.",
    "hi": "Sabhi systems online hain, sir. Welcome back.",
}

# Pick up previously-saved keys from earlier runs, in addition to whatever's
# already in config.py / the environment.
_saved_keys = memory.get_api_keys()
if _saved_keys:
    config.API_KEY = _saved_keys[memory.get_active_key_index()]
elif config.API_KEY:
    memory.set_api_keys([config.API_KEY])

# Supabase (optional) — only activates if config.py actually has a URL/key
# set. Everything else in the app works fine without this configured at all.
_sb = None
if getattr(config, "SUPABASE_URL", "") and getattr(config, "SUPABASE_ANON_KEY", ""):
    try:
        from supabase import create_client
        _sb = create_client(config.SUPABASE_URL, config.SUPABASE_ANON_KEY)
    except Exception:
        _sb = None  # supabase package not installed, or bad credentials — login just won't be offered


def _provider_summary():
    """What providers the stored keys cover — shown in the settings panel
    so it's obvious at a glance what the fallback chain actually is."""
    keys = memory.get_api_keys()
    if not keys:
        return {"providers": [], "key_count": 0, "active": ""}
    providers = [llm.detect_provider(k) for k in keys]
    active_idx = memory.get_active_key_index()
    return {
        "providers": providers,
        "key_count": len(keys),
        "active": providers[active_idx] if active_idx < len(providers) else providers[0],
    }


@app.route("/")
def index():
    return send_file(os.path.join(BASE_DIR, "index.html"))


@app.route("/api/init")
def api_init():
    data = memory.load()
    has_key = bool(memory.get_api_keys())
    has_name = bool(data.get("name"))
    needs_setup = not (has_key and has_name)

    if needs_setup:
        return jsonify({"needs_setup": True, "name": "", "language": data.get("language", "en"),
                         "profanity": data.get("profanity", "medium"), "theme": data.get("theme", "dark"),
                         "idle_chatter": data.get("idle_chatter", True),
                         "provider": "", "key_count": 0, "providers": [],
                         "login_available": _sb is not None, "email": "",
                         "greeting_text": "", "greeting_audio": ""})

    name = data.get("name") or "Boss"
    language = data.get("language", "en")
    greeting_text = GREETINGS.get(language, GREETINGS["en"]).format(name=name)
    summary = _provider_summary()
    return jsonify({
        "needs_setup": False,
        "name": name,
        "language": language,
        "profanity": data.get("profanity", "medium"),
        "theme": data.get("theme", "dark"),
        "idle_chatter": data.get("idle_chatter", True),
        "voice": data.get("voice", "") or config.EDGE_TTS_VOICE,
        "voice_options": getattr(config, "VOICE_OPTIONS", []),
        "provider": summary["active"],
        "providers": summary["providers"],
        "key_count": summary["key_count"],
        "login_available": _sb is not None,
        "email": data.get("user_email", ""),
        "greeting_text": greeting_text,
        "greeting_audio": tts.speak_to_base64(greeting_text),
    })


def _apply_keys(keys: list):
    """Shared by /api/setup and the settings-panel key manager below —
    saves the key list, points config at the one that should be tried
    first, and drops any cached clients so a stale one for the old key
    isn't reused."""
    memory.set_api_keys(keys)
    config.API_KEY = keys[0] if keys else ""
    llm.reset_clients()


def _mask_key(key: str) -> str:
    key = key or ""
    if len(key) <= 8:
        return "*" * len(key)
    return f"{key[:4]}…{key[-4:]}"


def _keys_payload():
    """Per-key detail for the settings panel's API KEYS list — masked, not
    the raw key, since once stored there's no need to ever show it in full
    again."""
    keys = memory.get_api_keys()
    active_idx = memory.get_active_key_index()
    providers = [llm.detect_provider(k) for k in keys]
    entries = [
        {"index": i, "provider": providers[i], "masked": _mask_key(k), "active": i == active_idx}
        for i, k in enumerate(keys)
    ]
    return {
        "keys": entries,
        "key_count": len(entries),
        "providers": providers,
        "active_provider": providers[active_idx] if providers else "",
    }


@app.route("/api/keys")
def api_keys_list():
    return jsonify(_keys_payload())


@app.route("/api/keys/add", methods=["POST"])
def api_keys_add():
    body = request.get_json(force=True, silent=True) or {}
    new_key = (body.get("api_key") or "").strip()
    if not new_key:
        return jsonify({"ok": False, "error": "No key provided."}), 400
    keys = memory.get_api_keys()
    if new_key in keys:
        return jsonify({"ok": False, "error": "That key is already stored."}), 400
    keys.append(new_key)
    _apply_keys(keys)
    return jsonify({"ok": True, **_keys_payload()})


@app.route("/api/keys/remove", methods=["POST"])
def api_keys_remove():
    body = request.get_json(force=True, silent=True) or {}
    try:
        index = int(body.get("index"))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "Bad key index."}), 400
    keys = memory.get_api_keys()
    if not (0 <= index < len(keys)):
        return jsonify({"ok": False, "error": "No key at that position."}), 400
    if len(keys) == 1:
        return jsonify({"ok": False, "error": "Can't remove your last key — add a replacement first."}), 400
    keys.pop(index)
    _apply_keys(keys)
    return jsonify({"ok": True, **_keys_payload()})


@app.route("/api/setup", methods=["POST"])
def api_setup():
    body = request.get_json(force=True, silent=True) or {}
    raw_keys = body.get("api_keys")
    if raw_keys is None:
        raw_keys = body.get("api_key", "")
    if isinstance(raw_keys, str):
        # The setup box accepts one key per line — split them apart.
        raw_keys = [line for line in raw_keys.replace(",", "\n").splitlines()]
    keys = [k.strip() for k in raw_keys if k and k.strip()]

    name = (body.get("name") or "").strip() or "Boss"
    if not keys:
        return jsonify({"ok": False, "error": "Add at least one API key."}), 400

    _apply_keys(keys)
    data = memory.load()
    data["name"] = name
    memory.save(data)

    language = data.get("language", "en")
    greeting_text = GREETINGS.get(language, GREETINGS["en"]).format(name=name)
    summary = _provider_summary()
    return jsonify({
        "ok": True,
        "name": name,
        "language": language,
        "profanity": data.get("profanity", "medium"),
        "theme": data.get("theme", "dark"),
        "idle_chatter": data.get("idle_chatter", True),
        "voice": data.get("voice", "") or config.EDGE_TTS_VOICE,
        "voice_options": getattr(config, "VOICE_OPTIONS", []),
        "provider": summary["active"],
        "providers": summary["providers"],
        "key_count": summary["key_count"],
        "login_available": _sb is not None,
        "email": data.get("user_email", ""),
        "greeting_text": greeting_text,
        "greeting_audio": tts.speak_to_base64(greeting_text),
    })


@app.route("/api/command", methods=["POST"])
def api_command():
    body = request.get_json(force=True, silent=True) or {}
    text = (body.get("text") or "").strip()
    if not text:
        return jsonify({"action": "chat", "reply": "", "audio": "", "image": "", "image_mime": "", "language": memory.get_language()})

    # An attached file becomes context for this one message. Text files get
    # their contents inlined; images are handed to the vision path if the
    # active provider supports it.
    attachment = body.get("attachment") or None
    prompt = text
    if attachment and attachment.get("kind") == "text":
        content = (attachment.get("content") or "")[:60000]
        prompt = (
            f"The user attached a file called {attachment.get('name','file')}. "
            f"Its contents are between the markers below.\n"
            f"--- FILE START ---\n{content}\n--- FILE END ---\n\n"
            f"Their message: {text}"
        )
    elif attachment and attachment.get("kind") == "image":
        prompt = (
            f"The user attached an image called {attachment.get('name','image')}. "
            f"Their message: {text}"
        )

    result = brain.think(prompt, image=attachment if (attachment and attachment.get("kind") == "image") else None)

    image_b64 = ""
    image_mime = ""
    if result.get("action") == "generate_image":
        img_b64, img_mime, saved_path, err = image_gen.generate(result.get("image_prompt") or text)
        if img_b64:
            image_b64 = img_b64
            image_mime = img_mime
        elif err:
            result["reply"] = (result["reply"] + f" Though it actually failed: {err}").strip()

    audio_b64 = tts.speak_to_base64(result["reply"])
    return jsonify({
        "action": result["action"],
        "reply": result["reply"],
        "audio": audio_b64,
        "image": image_b64,
        "image_mime": image_mime,
        "trace": result.get("trace", {}),
        "code": result.get("code", ""),
        "code_language": result.get("code_language", ""),
        "language": memory.get_language(),
    })


@app.route("/api/history")
def api_history():
    return jsonify({"entries": history.recent(30)})


@app.route("/api/sessions")
def api_sessions():
    data = history.list_sessions()
    # Don't ship every message of every session to the UI — just the meta.
    slim = [{"id": x["id"], "title": x["title"], "pinned": x.get("pinned", False),
             "updated": x.get("updated", ""), "count": len(x.get("entries", []))}
            for x in data["sessions"]]
    return jsonify({"active": data["active"] or history.active_session_id(), "sessions": slim})


@app.route("/api/session_action", methods=["POST"])
def api_session_action():
    body = request.get_json(force=True, silent=True) or {}
    act = body.get("action", "")
    sid = body.get("id", "")
    if act == "new":
        new_id = history.new_session()
        brain._clear_history()
        return jsonify({"ok": True, "active": new_id, "entries": []})
    if act == "select" and history.set_active(sid):
        brain._clear_history()
        return jsonify({"ok": True, "active": sid, "entries": history.session_entries(sid)})
    if act == "pin":
        return jsonify({"ok": True, "pinned": history.toggle_pin(sid)})
    if act == "delete":
        history.delete_session(sid)
        return jsonify({"ok": True, "active": history.active_session_id()})
    return jsonify({"ok": False, "error": "unknown action"}), 400


@app.route("/api/agents", methods=["GET", "POST", "DELETE"])
def api_agents():
    if request.method == "GET":
        return jsonify({"agents": agents.list_agents()})
    body = request.get_json(force=True, silent=True) or {}
    if request.method == "DELETE":
        return jsonify({"ok": agents.delete_agent(body.get("id", ""))})
    return jsonify({"ok": True, "agent": agents.save_agent(body)})


@app.route("/api/agent_models")
def api_agent_models():
    # The models the current key's provider offers, for the agent editor dropdown.
    import llm
    provider = llm.detect_provider(config.API_KEY)
    return jsonify({"models": config.PROVIDER_MODELS.get(provider, [])})


@app.route("/api/agents/run", methods=["POST"])
def api_agents_run():
    body = request.get_json(force=True, silent=True) or {}
    transcript = agents.run_discussion(
        task=body.get("task", ""),
        agent_ids=body.get("agent_ids", []),
        rounds=body.get("rounds", 2),
        lead_id=body.get("lead_id", ""),
    )
    return jsonify({"transcript": transcript})


@app.route("/api/stats")
def api_stats():
    return jsonify(pc.get_system_stats())


@app.route("/api/settings", methods=["POST"])
def api_settings():
    body = request.get_json(force=True, silent=True) or {}
    if "language" in body:
        memory.set_language(body["language"])
    if "profanity" in body:
        memory.set_profanity(body["profanity"])
    if "voice" in body:
        memory.set_voice(body["voice"])
    if "theme" in body:
        data = memory.load()
        data["theme"] = body["theme"]
        memory.save(data)
    if "idle_chatter" in body:
        memory.set_idle_chatter(bool(body["idle_chatter"]))
    return jsonify(memory.load())


@app.route("/api/idle_line")
def api_idle_line():
    """Called by the UI after a stretch of no commands. Server-side gate on
    top of the client's own toggle check, so a stray timer race can't speak
    a line right after the user switches idle chatter off."""
    if not memory.get_idle_chatter():
        return jsonify({"reply": "", "audio": ""})
    reply = brain.idle_line()
    if not reply:
        return jsonify({"reply": "", "audio": ""})
    return jsonify({"reply": reply, "audio": tts.speak_to_base64(reply)})


@app.route("/api/open_terminal", methods=["POST"])
def api_open_terminal():
    body = request.get_json(force=True, silent=True) or {}
    code = body.get("code") or ""
    language = body.get("language") or ""
    if not code.strip():
        return jsonify({"ok": False, "error": "No code to open."}), 400
    result = pc.open_code_in_terminal(code, language)
    return jsonify({"ok": True, "message": result})


@app.route("/api/login_url")
def api_login_url():
    if not _sb:
        return jsonify({"url": "", "error": "Supabase isn't configured yet."}), 400
    try:
        res = _sb.auth.sign_in_with_oauth({
            "provider": "google",
            "options": {"redirect_to": f"http://127.0.0.1:{config.SERVER_PORT}"},
        })
        return jsonify({"url": res.url})
    except Exception as e:
        return jsonify({"url": "", "error": str(e)}), 500


@app.route("/api/session", methods=["POST"])
def api_session():
    if not _sb:
        return jsonify({"ok": False, "error": "Supabase isn't configured yet."}), 400
    body = request.get_json(force=True, silent=True) or {}
    token = body.get("access_token", "")
    try:
        user = _sb.auth.get_user(token)
        data = memory.load()
        data["user_email"] = user.user.email
        memory.save(data)
        return jsonify({"ok": True, "email": user.user.email})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 401


@app.route("/api/logout", methods=["POST"])
def api_logout():
    data = memory.load()
    data["user_email"] = ""
    memory.save(data)
    return jsonify({"ok": True})


def run():
    app.run(host=config.SERVER_HOST, port=config.SERVER_PORT, debug=False, use_reloader=False, threaded=True)
