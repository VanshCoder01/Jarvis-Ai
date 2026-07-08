"""
server.py — the bridge between the web UI (index.html) and the Python side
(Gemini brain, PC control, TTS, memory). Runs locally only — SERVER_HOST is
127.0.0.1, so nothing outside this PC can reach it.
"""
import os

from flask import Flask, jsonify, request, send_file

import brain
import config
import memory
import pc_control as pc
import tts

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

app = Flask(__name__)

GREETINGS = {
    "en": "Systems online. Good to see you, {name}.",
    "hi": "Systems online hain. Accha laga aapko dekhkar, {name}.",
}


@app.route("/")
def index():
    return send_file(os.path.join(BASE_DIR, "index.html"))


@app.route("/api/init")
def api_init():
    data = memory.load()
    name = data.get("name") or "Boss"
    language = data.get("language", "en")
    greeting_text = GREETINGS.get(language, GREETINGS["en"]).format(name=name)
    return jsonify({
        "name": name,
        "language": language,
        "profanity": data.get("profanity", "medium"),
        "greeting_text": greeting_text,
        "greeting_audio": tts.speak_to_base64(greeting_text),
    })


@app.route("/api/command", methods=["POST"])
def api_command():
    body = request.get_json(force=True, silent=True) or {}
    text = (body.get("text") or "").strip()
    if not text:
        return jsonify({"action": "chat", "reply": "", "audio": "", "language": memory.get_language()})

    result = brain.think(text)
    audio_b64 = tts.speak_to_base64(result["reply"])
    return jsonify({
        "action": result["action"],
        "reply": result["reply"],
        "audio": audio_b64,
        "language": memory.get_language(),
    })


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
    return jsonify(memory.load())


def run():
    app.run(host=config.SERVER_HOST, port=config.SERVER_PORT, debug=False, use_reloader=False, threaded=True)
