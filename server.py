"""
server.py — the bridge between the web UI (index.html) and the Python side
(the AI brain, PC control, TTS, memory). Runs locally only — SERVER_HOST is
127.0.0.1, so nothing outside this PC can reach it.
"""
import json
import os
import sys
import threading

from flask import Flask, jsonify, request, send_file

import agent as code_agent
import agents
import autopilot
import brain
import config
import history
import image_gen
import llm
import memory
import pc_control as pc
import simulator
import startup
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
SIM_GREETINGS = {
    "en": "Simulation online, sir. Nothing I do in here touches your real machine.",
    "hi": "Simulation online hai, sir. Yahan kuch bhi aapke asli PC ko nahi chhuega.",
}


@app.before_request
def _local_requests_only():
    """Binding to 127.0.0.1 keeps other machines out, but not other *websites*:
    any page open in the user's browser can still fire requests at
    http://127.0.0.1:<port>, and this API can type, click and shut the PC
    down. So refuse anything that isn't the Jarvis UI talking to itself --
    a foreign Origin (cross-site request) or a foreign Host (DNS rebinding)."""
    allowed_hosts = {f"127.0.0.1:{config.SERVER_PORT}", f"localhost:{config.SERVER_PORT}"}
    if request.host not in allowed_hosts:
        return jsonify({"ok": False, "error": "Forbidden host."}), 403
    origin = request.headers.get("Origin")
    if origin and origin not in {f"http://{h}" for h in allowed_hosts}:
        return jsonify({"ok": False, "error": "Cross-site requests are not allowed."}), 403
    if request.headers.get("Sec-Fetch-Site") == "cross-site" and request.method != "GET":
        return jsonify({"ok": False, "error": "Cross-site requests are not allowed."}), 403

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


def _boot_payload(data: dict) -> dict:
    """Everything the UI needs to bring itself up -- shared by /api/init
    and /api/setup so the two can't drift apart."""
    name = data.get("name") or "Boss"
    language = data.get("language", "en")
    simulating = simulator.is_enabled()
    greetings = SIM_GREETINGS if simulating else GREETINGS
    greeting_text = greetings.get(language, greetings["en"])
    summary = _provider_summary()
    return {
        "needs_setup": False,
        "name": name,
        "language": language,
        "profanity": data.get("profanity", "medium"),
        "theme": data.get("theme", "dark"),
        "idle_chatter": data.get("idle_chatter", True),
        "voice": data.get("voice", "") or config.EDGE_TTS_VOICE,
        "voice_options": getattr(config, "VOICE_OPTIONS", []),
        "voice_fx": data.get("voice_fx", "comms"),
        "provider": summary["active"],
        "providers": summary["providers"],
        "key_count": summary["key_count"],
        "login_available": _sb is not None,
        "email": data.get("user_email", ""),
        "version": getattr(config, "VERSION", ""),
        "model_override": data.get("model_override", ""),
        "agent_root": _default_agent_root(),
        "launch_at_startup": startup.is_enabled(),
        "simulation": simulating,
        "sim_state": simulator.snapshot() if simulating else None,
        "greeting_text": greeting_text,
        "greeting_audio": tts.speak_to_base64(greeting_text),
    }


@app.route("/api/init")
def api_init():
    data = memory.load()
    # Simulation mode needs no key: the offline core answers instead.
    can_think = bool(memory.get_api_keys()) or simulator.is_enabled()
    if not (can_think and data.get("name")):
        return jsonify({"needs_setup": True, "name": "", "language": data.get("language", "en"),
                         "profanity": data.get("profanity", "medium"), "theme": data.get("theme", "dark"),
                         "idle_chatter": data.get("idle_chatter", True),
                         "voice": data.get("voice", "") or config.EDGE_TTS_VOICE,
                         "voice_options": getattr(config, "VOICE_OPTIONS", []),
                         "voice_fx": data.get("voice_fx", "comms"),
                         "provider": "", "key_count": 0, "providers": [],
                         "login_available": _sb is not None, "email": "",
                         "version": getattr(config, "VERSION", ""),
                         "simulation": False, "sim_state": None,
                         "greeting_text": "", "greeting_audio": ""})
    return jsonify(_boot_payload(data))


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
    want_simulation = bool(body.get("simulation"))
    if not keys and not want_simulation:
        return jsonify({"ok": False, "error": "Add at least one API key."}), 400

    if keys:
        _apply_keys(keys)
    data = memory.load()
    data["name"] = name
    if want_simulation:
        data["simulation"] = True
    memory.save(data)
    return jsonify({"ok": True, **_boot_payload(memory.load())})


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
    simulating = simulator.is_enabled()
    if result.get("action") == "generate_image" and simulating:
        # Don't spend image-model quota on a dry run -- show a stand-in.
        image_b64, image_mime = simulator.placeholder_image(result.get("image_prompt") or text)
        result["reply"] = (result["reply"] + " This one is a simulated render, not a real generation.").strip()
    elif result.get("action") == "generate_image":
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
        "simulation": simulating,
        "sim_state": simulator.snapshot() if simulating else None,
    })


@app.route("/api/sim/state")
def api_sim_state():
    return jsonify({"simulation": simulator.is_enabled(), "sim_state": simulator.snapshot()})


@app.route("/api/sim/reset", methods=["POST"])
def api_sim_reset():
    return jsonify({"simulation": simulator.is_enabled(), "sim_state": simulator.reset()})


@app.route("/api/sim/wake", methods=["POST"])
def api_sim_wake():
    return jsonify({"simulation": simulator.is_enabled(), "sim_state": simulator.wake()})


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


# ---------- code mode (agent.py) ----------
# One session at a time, held in memory. The browser drives the loop: it asks
# for one step, shows it, and asks for the next -- so every action is visible
# as it happens and a stop request takes effect between steps.
_agent_lock = threading.Lock()
_agent = {"root": "", "goal": "", "transcript": [], "steps": 0, "pending": None, "done": True}


def _default_agent_root() -> str:
    return os.path.join(os.path.expanduser("~"), "Desktop", "JarvisProjects", "scratch")


def _resolve_agent_root(raw: str):
    """Returns (absolute_path, error). Refuses folders that are far too broad
    to hand to an agent that can write files -- a drive root, the user's
    whole home folder, or anything under Windows itself."""
    raw = (raw or "").strip().strip('"')
    if not raw:
        return None, "Pick a project folder first."
    root = os.path.abspath(os.path.expandvars(os.path.expanduser(raw)))
    home = os.path.abspath(os.path.expanduser("~"))
    windir = os.path.abspath(os.environ.get("WINDIR", r"C:\Windows"))
    tail = os.path.splitdrive(root)[1].strip("\\/")
    if not tail:
        return None, "That's an entire drive. Pick a specific project folder."
    if os.path.normcase(root) == os.path.normcase(home):
        return None, "That's your whole user folder. Pick a specific project folder inside it."
    if os.path.normcase(root + os.sep).startswith(os.path.normcase(windir + os.sep)):
        return None, "That's inside Windows. Pick a project folder somewhere else."
    if os.path.isfile(root):
        return None, "That's a file, not a folder."
    if not os.path.isdir(root):
        if simulator.is_enabled():
            return None, "That folder doesn't exist, and simulation mode won't create it."
        try:
            os.makedirs(root, exist_ok=True)
        except Exception as e:
            return None, f"Couldn't create that folder: {e}"
    return root, None


def _agent_record(call: dict, result: str):
    shown = {k: call.get(k, "") for k in ("tool", "path", "command", "message") if call.get(k)}
    if call.get("tool") == "write_file":
        shown["content"] = f"({len(call.get('content') or '')} chars written)"
    _agent["transcript"].append({"role": "model", "text": json.dumps(shown)})
    _agent["transcript"].append({"role": "user", "text": f"Result of {call.get('tool')}:\n{result}"})


def _agent_reply(call: dict, result: str, **extra):
    return jsonify({
        "ok": True, "step": _agent["steps"], "max_steps": code_agent.MAX_STEPS,
        "tool": call.get("tool", ""), "message": call.get("message", ""),
        "path": call.get("path", ""), "command": call.get("command", ""),
        "result": result, "needs_confirm": False, "done": _agent["done"],
        "simulated": False, **extra,
    })


@app.route("/api/agent/start", methods=["POST"])
def api_agent_start():
    body = request.get_json(force=True, silent=True) or {}
    goal = (body.get("goal") or "").strip()
    if not goal:
        return jsonify({"ok": False, "error": "Describe the task first."}), 400
    if not memory.get_api_keys():
        return jsonify({"ok": False, "error": "Code mode needs a real model \u2014 add an API key in settings. "
                                              "The offline simulation core can't write code."}), 400
    root, err = _resolve_agent_root(body.get("root"))
    if err:
        return jsonify({"ok": False, "error": err}), 400
    with _agent_lock:
        if body.get("continue") and _agent["root"] == root and _agent["transcript"]:
            _agent["transcript"].append({"role": "user", "text": f"New instruction from the user: {goal}"})
        else:
            _agent.update({"root": root, "goal": goal, "transcript": []})
        _agent.update({"steps": 0, "pending": None, "done": False})
    return jsonify({"ok": True, "root": root, "max_steps": code_agent.MAX_STEPS,
                    "simulated": simulator.is_enabled()})


@app.route("/api/agent/step", methods=["POST"])
def api_agent_step():
    with _agent_lock:
        if not _agent["root"] or _agent["done"]:
            return jsonify({"ok": False, "error": "No task is running."}), 400
        if _agent["pending"]:
            return jsonify({"ok": False, "error": "A command is still waiting for your approval."}), 400
        if _agent["steps"] >= code_agent.MAX_STEPS:
            _agent["done"] = True
            return jsonify({"ok": False, "error": f"Stopped at the {code_agent.MAX_STEPS}-step limit. "
                                                  "Send another instruction to keep going."}), 400
        try:
            call = code_agent.next_step(_agent["root"], _agent["goal"], _agent["transcript"])
        except code_agent.AgentError as e:
            return jsonify({"ok": False, "error": str(e)}), 502
        _agent["steps"] += 1
        tool = call["tool"]
        simulating = simulator.is_enabled()

        if tool == "done":
            _agent["done"] = True
            _agent_record(call, "Task marked as finished.")
            return _agent_reply(call, "")
        if tool == "run_command":
            if not (call.get("command") or "").strip():
                result = "No command given."
                _agent_record(call, result)
                return _agent_reply(call, result)
            _agent["pending"] = call           # nothing runs until /api/agent/confirm
            return _agent_reply(call, "", needs_confirm=True, simulated=simulating)

        simulated = False
        try:
            if tool == "read_file":
                result = code_agent.read_file(_agent["root"], call.get("path", ""))
            elif tool == "list_dir":
                result = code_agent.list_dir(_agent["root"], call.get("path", ""))
            elif simulating:
                code_agent._safe_path(_agent["root"], call.get("path", ""))   # still enforce the boundary
                result = (f"Simulation: would have written {len(call.get('content') or '')} chars to "
                          f"{call.get('path', '')}. Nothing was saved.")
                simulated = True
            else:
                result = code_agent.write_file(_agent["root"], call.get("path", ""), call.get("content", ""))
        except code_agent.AgentError as e:
            result = str(e)
        _agent_record(call, result)
        return _agent_reply(call, result, simulated=simulated)


@app.route("/api/agent/confirm", methods=["POST"])
def api_agent_confirm():
    body = request.get_json(force=True, silent=True) or {}
    with _agent_lock:
        call = _agent["pending"]
        if not call:
            return jsonify({"ok": False, "error": "There's no command waiting for approval."}), 400
        _agent["pending"] = None
        simulated = False
        if not body.get("approve"):
            result = "The user declined to run this command."
        elif simulator.is_enabled():
            result = "Simulation: the command was approved but not executed."
            simulated = True
        else:
            result = code_agent.run_command(_agent["root"], call.get("command", ""))
        _agent_record(call, result)
        return jsonify({"ok": True, "result": result, "simulated": simulated})


# ---------- autopilot (autopilot.py) ----------
# Runs on its own thread, not driven by the browser: the Jarvis window is
# minimised while it works, and a minimised page can't be trusted to keep a
# loop ticking. The UI just polls /status.

@app.route("/api/autopilot/start", methods=["POST"])
def api_autopilot_start():
    body = request.get_json(force=True, silent=True) or {}
    if simulator.is_enabled():
        return jsonify({"ok": False, "error": "Autopilot drives the real mouse and keyboard, and simulation "
                                              "mode promises nothing real happens. Switch simulation off first."}), 400
    if not memory.get_api_keys():
        return jsonify({"ok": False, "error": "Autopilot needs a vision-capable model \u2014 add an API key in settings."}), 400
    try:
        return jsonify({"ok": True, **autopilot.start(body.get("goal", ""))})
    except autopilot.AutopilotError as e:
        return jsonify({"ok": False, "error": str(e)}), 400


@app.route("/api/autopilot/status")
def api_autopilot_status():
    return jsonify({"ok": True, **autopilot.status()})


@app.route("/api/autopilot/stop", methods=["POST"])
def api_autopilot_stop():
    return jsonify({"ok": True, **autopilot.stop()})


@app.route("/favicon.ico")
def favicon():
    path = os.path.join(BASE_DIR, "jarvis.ico")
    if os.path.isfile(path):
        return send_file(path, mimetype="image/x-icon")
    return "", 204


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
    if "voice_fx" in body and body["voice_fx"] in ("off", "comms", "deep"):
        data = memory.load()
        data["voice_fx"] = body["voice_fx"]
        memory.save(data)
    if "launch_at_startup" in body:
        try:
            startup.set_enabled(bool(body["launch_at_startup"]))
        except OSError as e:
            return jsonify({"ok": False, "error": f"Windows wouldn't let me change that: {e}"}), 500
    if "model_override" in body:
        data = memory.load()
        data["model_override"] = str(body["model_override"] or "").strip()[:120]
        memory.save(data)
    if "simulation" in body:
        if not body["simulation"] and not memory.get_api_keys():
            return jsonify({"ok": False, "error": "Add an API key before leaving simulation \u2014 "
                                                  "without one there's no brain to run on."}), 400
        simulator.set_enabled(bool(body["simulation"]))
    # Never hand the stored API keys back to the page -- it has no use for them.
    safe = {k: v for k, v in memory.load().items() if k not in ("api_key", "api_keys")}
    safe.update({"ok": True, "simulation": simulator.is_enabled(), "sim_state": simulator.snapshot(),
                 "launch_at_startup": startup.is_enabled()})
    return jsonify(safe)


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
    if simulator.is_enabled():
        return jsonify({"ok": True, "simulated": True,
                        "message": "Simulation: no file was written and no terminal was opened."})
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
