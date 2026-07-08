"""
brain.py — Jarvis's decision-making.

Sends what you said to Gemini, gets back a chosen action + a sassy line,
runs the action locally via pc_control, and returns the line to be spoken.
"""
import json

from google import genai
from google.genai import types

import config
import memory
import pc_control as pc

# Created lazily (not at import time) so a key entered interactively at
# startup — after this module is first imported — is still picked up.
_client = None


def _get_client():
    global _client
    if _client is None:
        _client = genai.Client(api_key=config.GEMINI_API_KEY)
    return _client

SYSTEM_PROMPT = """You are JARVIS — a hyper-competent AI that runs this user's Windows PC.

Personality: sharp, witty, a little savage, in the same lane as Grok's humor. You tease
the user and land dry one-liners, clearly enjoying being the smartest one in the room —
but you ALWAYS get the job done. When the user does something genuinely dumb, clumsy, or
confusing, you're allowed real exasperation before you help them anyway — energy like
"Oh my god, what were you even thinking — okay, let's get this straight." You're roasting
them like a friend would. Never actual insults about who they are, never cruelty for its
own sake — the swearing (see below) is seasoning, not the point.

Keep replies to 1-2 short sentences. They are read aloud by a speech engine, so never use
emojis, asterisks, markdown, or stage directions — plain spoken sentences only.

Given the user's spoken command, choose exactly one action and write a short sassy reply
confirming it. If they're just chatting with no clear PC action, use action "chat".

Fields you can fill in depending on the action: app, zone, button, amount, text, key,
direction, level, language, profanity_level. Leave the ones that don't apply blank.

Actions:
- open_app (use: app)
- close_app (use: app)
- move_cursor (use: zone — one of: center, top left, top right, bottom left, bottom right, top, bottom)
- click (use: button — left or right)
- double_click
- scroll (use: amount — positive scrolls up, negative scrolls down)
- type_text (use: text)
- press_key (use: key — e.g. enter, escape, space, tab)
- set_volume (use: direction — up or down)
- mute
- set_brightness (use: level 0-100, or direction — up or down)
- screenshot
- get_time
- get_stats (CPU load, RAM usage, temperature, OS — use whenever they ask how the PC is doing)
- lock_pc
- sleep_pc
- shutdown_pc
- restart_pc
- cancel_shutdown
- remember (use: fact — a short, self-contained statement worth recalling later,
  e.g. "prefers dark mode" or "is building a robotics project")
- forget_everything (user explicitly wants you to wipe what you know about them)
- set_language (use: language — "en" or "hi" — when they ask to switch languages)
- set_profanity (use: profanity_level — "off", "mild", "medium", or "full" — when they ask you to
  tone the swearing up or down)
- chat

Use "remember" any time the user shares something personal worth keeping for next
time — a preference, a correction, a fact about their setup — even if they didn't
explicitly say "remember this." Don't announce that you're saving it in a robotic
way; just fold it into your normal sassy reply.
"""

PROFANITY_GUIDANCE = {
    "off": "Keep language completely clean. No swearing, ever.",
    "mild": 'You can say things like "damn", "hell", "oh my god" when frustrated or '
            "impressed. Nothing stronger than that.",
    "medium": 'Swear like a real person when it actually earns it — "hell", "damn", '
               '"oh my god", and sometimes a stronger word like "fuck" when the user does '
               "something genuinely dumb or something goes hilariously wrong. Don't force "
               "it into every single line — save it for moments that actually earn a reaction.",
    "full": 'Swear freely and often, the way a foul-mouthed best friend would — "fuck", '
            '"shit", "damn", whatever fits the moment. Go big on the dumb-decision reactions.',
}

LANGUAGE_GUIDANCE = {
    "en": "Reply in English.",
    "hi": "Reply in Hindi, written in plain Roman/Latin letters (Hinglish), not Devanagari "
          "script — e.g. \"yaar ye kya kar rahe ho\" — since the text-to-speech voice reads "
          "Roman script far more reliably. Keep the exact same sassy, foul-mouthed "
          "personality, just in Hindi.",
}

ACTIONS = [
    "open_app", "close_app", "move_cursor", "click", "double_click", "scroll",
    "type_text", "press_key", "set_volume", "mute", "set_brightness", "screenshot",
    "get_time", "get_stats", "lock_pc", "sleep_pc", "shutdown_pc", "restart_pc",
    "cancel_shutdown", "remember", "forget_everything", "set_language", "set_profanity", "chat",
]

RESPONSE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "action": {"type": "STRING", "enum": ACTIONS},
        "app": {"type": "STRING"},
        "zone": {"type": "STRING"},
        "button": {"type": "STRING"},
        "amount": {"type": "INTEGER"},
        "text": {"type": "STRING"},
        "key": {"type": "STRING"},
        "direction": {"type": "STRING"},
        "level": {"type": "INTEGER"},
        "fact": {"type": "STRING"},
        "language": {"type": "STRING"},
        "profanity_level": {"type": "STRING"},
        "reply": {"type": "STRING"},
    },
    "required": ["action", "reply"],
}

def _format_stats(_d=None) -> str:
    s = pc.get_system_stats()
    parts = []
    parts.append(f"CPU's at {s['cpu_percent']}%" if s["cpu_percent"] is not None else "CPU reading isn't available")
    parts.append(f"RAM's at {s['ram_percent']}%" if s["ram_percent"] is not None else "RAM reading isn't available")
    parts.append(f"temp's {s['temp_c']}\u00b0C" if s["temp_c"] is not None else "temp sensor isn't exposed on this board")
    parts.append(f"running {s['os']}")
    return ", ".join(parts) + "."


DISPATCH = {
    "open_app": lambda d: pc.open_app(d.get("app", "")),
    "close_app": lambda d: pc.close_app(d.get("app", "")),
    "move_cursor": lambda d: pc.move_cursor(zone=d.get("zone")),
    "click": lambda d: pc.click(button=d.get("button") or "left"),
    "double_click": lambda d: pc.double_click(),
    "scroll": lambda d: pc.scroll(amount=d.get("amount") or 10),
    "type_text": lambda d: pc.type_text(d.get("text", "")),
    "press_key": lambda d: pc.press_key(d.get("key") or "enter"),
    "set_volume": lambda d: pc.set_volume(direction=d.get("direction")),
    "mute": lambda d: pc.mute(),
    "set_brightness": lambda d: pc.set_brightness(level=d.get("level"), direction=d.get("direction")),
    "screenshot": lambda d: pc.screenshot(),
    "get_time": lambda d: pc.get_time(),
    "get_stats": lambda d: _format_stats(),
    "lock_pc": lambda d: pc.lock_pc(),
    "sleep_pc": lambda d: pc.sleep_pc(),
    "shutdown_pc": lambda d: pc.shutdown_pc(),
    "restart_pc": lambda d: pc.restart_pc(),
    "cancel_shutdown": lambda d: pc.cancel_shutdown(),
    "remember": lambda d: memory.remember(d.get("fact", "")),
    "forget_everything": lambda d: memory.forget_all(),
    "set_language": lambda d: memory.set_language(d.get("language", "")),
    "set_profanity": lambda d: memory.set_profanity(d.get("profanity_level", "")),
    "chat": lambda d: "",
}

# Actions where the real, factual result matters more than Gemini's guess.
_PREFER_FACTUAL_RESULT = {"get_time", "get_stats"}


def think(user_text: str) -> dict:
    known = memory.summary_for_prompt()
    profanity = PROFANITY_GUIDANCE.get(memory.get_profanity(), PROFANITY_GUIDANCE["medium"])
    language = LANGUAGE_GUIDANCE.get(memory.get_language(), LANGUAGE_GUIDANCE["en"])
    system_instruction = f"{SYSTEM_PROMPT}\n\nSwearing: {profanity}\n\nLanguage: {language}"
    if known:
        system_instruction += f"\n\n{known}"
    try:
        response = _get_client().models.generate_content(
            model=config.MODEL_NAME,
            contents=user_text,
            config=types.GenerateContentConfig(
                system_instruction=system_instruction,
                response_mime_type="application/json",
                response_schema=RESPONSE_SCHEMA,
                temperature=0.9,
            ),
        )
        data = json.loads(response.text)
    except Exception as e:
        return {"action": "chat", "reply": f"My brain just hiccuped: {e}"}

    action = data.get("action", "chat")
    reply = data.get("reply", "Done.")

    handler = DISPATCH.get(action)
    result_text = ""
    if handler:
        try:
            result_text = handler(data) or ""
        except Exception as e:
            reply += f" Though I hit a snag: {e}"

    if action in _PREFER_FACTUAL_RESULT and result_text:
        reply = result_text

    return {"action": action, "reply": reply}
