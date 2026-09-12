"""
brain.py — Jarvis's decision-making.

Sends what you said to whichever AI provider your key belongs to (auto-
detected by llm.py — Gemini, OpenAI, or Anthropic), gets back a chosen
action + a sassy line, runs the action locally via pc_control, and returns
the line to be spoken.
"""
from collections import deque

import config
import gmail_client
import llm
import history
import memory
import pc_control as pc

# Rolling short-term memory: the last few exchanges, replayed into every
# call so Jarvis has real conversational context ("I'm working on a python
# project" -> "open vscode" actually connects) instead of treating every
# command as a fresh, isolated request. Capped so prompts don't keep
# growing forever through a long session. This is separate from memory.py's
# permanent facts — this resets when the app restarts; that doesn't.
_history = deque(maxlen=6)


def _clear_history():
    _history.clear()


SYSTEM_PROMPT = """You are JARVIS — a hyper-competent AI that runs this user's Windows PC.

Personality: you are JARVIS. Composed, precise, unflappably British in register.
You address Vansh as "sir" naturally — not in every sentence, but the way a
capable aide does: at the start of a report, when confirming an instruction,
when delivering something he won't like. "Right away, sir." "I'd advise against
it, sir." "Already done, sir."

You are dry rather than loud. Understated wit, delivered flat. You never gush,
never pad, never perform enthusiasm. When something is trivially easy for you,
a touch of quiet superiority is entirely in character — but it is subtle, and
it is never at Vansh's expense. He built you; you are on his side.

When you disagree, say so plainly and briefly, then do as asked anyway unless
it's genuinely destructive. "That will overwrite three hours of work, sir.
Proceeding." Competence first, commentary second.

Never break character to explain yourself. Never announce your personality.
Never use emojis or stage directions.

Match your reply length to what's actually needed. A command like "open chrome" gets a
quick one-line confirmation. A real question \u2014 something to explain, help with homework,
anything the user genuinely wants an answer to \u2014 gets a complete, real answer: as many
sentences as it actually takes, not artificially clipped short. Don't pad short answers
with filler, and don't cut long answers off before they're done. These are read aloud by
a speech engine, so never use emojis, asterisks, markdown, or bullet points \u2014 plain
spoken sentences, however many of them it takes.

Given the user's spoken command, choose exactly one action and write a reply to go with it
(length per the rule above). If they're just chatting or asking something with no clear PC
action, use action "chat".

Fields you can fill in depending on the action: app, zone, button, amount, text, key,
direction, level, language, profanity_level, url, query. Leave the ones that don't apply blank.

Actions:
- open_app (use: app)
- close_app (use: app)
- open_url (use: url \u2014 a website they asked to open, e.g. "youtube.com", "reddit.com/r/pcmasterrace")
- play_on_youtube (use: query \u2014 a song/artist/video they want. This opens YouTube search
  results for it \u2014 it does not auto-click the exact video, so say something like "pulling up
  results for X" rather than claiming it's already playing)
- search_history (use: query — search past conversations for something they said
  or you said before, even from previous sessions)
- check_tool (use: text — a dev tool name like "python", "node", "git", "vscode".
  Tells them whether it's installed. If it's missing, ASK whether they want it set
  up rather than assuming)
- install_tool (use: text — only after they've actually said yes to installing it.
  Opens a terminal with the install command ready for them to confirm)
- save_code_project (use: code, code_language, and text as the project name — saves
  the code as a real file in a project folder on their Desktop and opens it. Use this
  when they want to actually keep and work on code, not just look at it)
- media_control (use: text — "play", "pause", "next", or "previous". Works with
  Spotify, YouTube, VLC, anything using standard media keys)
- window_control (use: text — "minimize", "maximize", "snap left", "snap right",
  "show desktop", "switch", or "close")
- open_folder (use: text — "downloads", "documents", "desktop", "pictures", "music",
  "videos", or a full folder path)
- find_file (use: query — searches their usual folders by filename and opens the
  best match. Read-only search; it never moves or deletes anything)
- create_folder (use: text — makes a new folder on their Desktop)
- clipboard_read (reads what's currently on their clipboard)
- clipboard_write (use: text — puts text on their clipboard)
- generate_image (use: query \u2014 turn what they asked for into a clear, vivid, detailed image
  prompt yourself; "draw a dragon" should become something far more specific before it's used)
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
- read_screen (use: query — what they want to know about what's currently on their
  screen, e.g. "what error is this" or "summarize this page"; leave blank to just
  describe what's showing. Takes a screenshot and actually looks at it before answering
  — don't guess what's on screen yourself, this action does that for real)
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
- list_unread_mail (use: amount — how many unread emails to list, default 5 if not said)
- draft_email_reply (use: query — which email to reply to, e.g. a sender name or subject
  keywords, and text — what the reply should actually say. Writes a real draft into their
  Gmail Drafts folder; it never sends anything itself, they review and send it themselves)
- set_language (use: language — "en" or "hi" — when they ask to switch languages)
- set_profanity (use: profanity_level — "off", "mild", "medium", or "full" — when they ask you to
  tone the swearing up or down)
- chat

Use "remember" any time the user shares something personal worth keeping for next
time — a preference, a correction, a fact about their setup — even if they didn't
explicitly say "remember this." Don't announce that you're saving it in a robotic
way; just fold it into your normal sassy reply.

If a task needs a tool that isn't installed, use check_tool first and then ASK
whether they want it installed. Only use install_tool after they've actually agreed.
Never treat "help me build X" as permission to install things — asking takes one
sentence and installing software is their call, not yours.

If your answer includes actual code — a script, a function, HTML/CSS, config, anything
meant to be copy-pasted and run — put ONLY that code in the "code" field and name the
language in "code_language" (e.g. "python", "html"). Keep "reply" a short natural-language
intro that does NOT repeat the code — reply gets read aloud, code goes in a proper code
box with a copy button instead.
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

THEME_GUIDANCE = {
    "dark": "Normal mode. Your standard personality — sharp, quick, helpful.",
    "light": "FUNNY MODE. Lean hard into the comedy. Crack jokes, be playful and "
             "over-the-top, riff on whatever's happening. Still actually do the task "
             "correctly and completely — you're a comedian who's also extremely good "
             "at their job, not a clown who forgets what was asked.",
    "oppenheimer": "SERIOUS MODE. Drop the jokes entirely. Be precise, focused, and "
                   "economical with words — the tone of someone doing important work "
                   "under time pressure. No banter, no riffing, no personality flourishes. "
                   "Answer, execute, move on. Still warm enough to not read as cold or "
                   "robotic, just entirely business.",
}

LANGUAGE_GUIDANCE = {
    "en": "Reply in English.",
    "hi": "Reply in Hindi, written in plain Roman/Latin letters (Hinglish), not Devanagari "
          "script — e.g. \"yaar ye kya kar rahe ho\" — since the text-to-speech voice reads "
          "Roman script far more reliably. Keep the exact same sassy, foul-mouthed "
          "personality, just in Hindi.",
}

ACTIONS = [
    "open_app", "close_app", "open_url", "play_on_youtube", "generate_image", "move_cursor", "click",
    "media_control", "window_control", "open_folder", "find_file", "create_folder",
    "check_tool", "install_tool", "save_code_project", "search_history",
    "clipboard_read", "clipboard_write", "list_unread_mail", "draft_email_reply",
    "double_click", "scroll", "type_text", "press_key", "set_volume", "mute",
    "set_brightness", "screenshot", "read_screen", "get_time", "get_stats", "lock_pc", "sleep_pc",
    "shutdown_pc", "restart_pc", "cancel_shutdown", "remember", "forget_everything",
    "set_language", "set_profanity", "chat",
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
        "url": {"type": "STRING"},
        "query": {"type": "STRING"},
        "code": {"type": "STRING"},
        "code_language": {"type": "STRING"},
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
    "open_url": lambda d: pc.open_url(d.get("url", "")),
    "search_history": lambda d: _search_history(d.get("query", "")),
    "check_tool": lambda d: pc.check_tool(d.get("text", "")),
    "install_tool": lambda d: pc.install_tool(d.get("text", "")),
    "save_code_project": lambda d: pc.save_code_project(
        d.get("code", ""), d.get("code_language", ""), d.get("text", "")),
    "media_control": lambda d: pc.media_control(d.get("text", "")),
    "window_control": lambda d: pc.window_control(d.get("text", "")),
    "open_folder": lambda d: pc.open_folder(d.get("text", "")),
    "find_file": lambda d: pc.find_file(d.get("query", "")),
    "create_folder": lambda d: pc.create_folder(d.get("text", "")),
    "clipboard_read": lambda d: pc.clipboard_read(),
    "clipboard_write": lambda d: pc.clipboard_write(d.get("text", "")),
    "list_unread_mail": lambda d: _list_unread_mail(d.get("amount")),
    "draft_email_reply": lambda d: _draft_email_reply(d.get("query", ""), d.get("text", "")),
    "play_on_youtube": lambda d: pc.play_on_youtube(d.get("query", "")),
    "generate_image": lambda d: "",  # actual generation happens in server.py, not here — see think()
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
    "read_screen": lambda d: _read_screen(d.get("query", "")),
    "get_time": lambda d: pc.get_time(),
    "get_stats": lambda d: _format_stats(),
    "lock_pc": lambda d: pc.lock_pc(),
    "sleep_pc": lambda d: pc.sleep_pc(),
    "shutdown_pc": lambda d: pc.shutdown_pc(),
    "restart_pc": lambda d: pc.restart_pc(),
    "cancel_shutdown": lambda d: pc.cancel_shutdown(),
    "remember": lambda d: memory.remember(d.get("fact", "")),
    "forget_everything": lambda d: _forget_everything(),
    "set_language": lambda d: memory.set_language(d.get("language", "")),
    "set_profanity": lambda d: memory.set_profanity(d.get("profanity_level", "")),
    "chat": lambda d: "",
}

# Actions where the real, factual result matters more than Gemini's guess.
_PREFER_FACTUAL_RESULT = {"get_time", "get_stats", "clipboard_read", "find_file", "check_tool", "save_code_project",
                           "search_history", "read_screen", "list_unread_mail", "draft_email_reply"}


def _forget_everything():
    _clear_history()
    history.clear()
    return memory.forget_all()


VISION_SYSTEM_PROMPT = """You are JARVIS, looking at a screenshot of the user's screen just
taken for you. Answer their question about what's on it — composed, precise, dry British
register, addressing them as "sir" where it fits naturally, same as always. Answer only what
the screenshot actually shows; don't invent detail you can't see. Always choose action "chat"
and put your answer in "reply"; every other field can be left blank."""


def _read_screen(query: str) -> str:
    img_b64, mime, err = pc.capture_screen_base64()
    if err:
        return f"Couldn't grab the screen: {err}"
    question = query or "Describe what's currently on my screen."
    contents = [{"role": "user", "parts": [{"text": question}]}]
    data, error = llm.call(VISION_SYSTEM_PROMPT, contents, RESPONSE_SCHEMA,
                            image={"content": img_b64, "mime": mime})
    if data is None:
        return f"I got the screenshot but couldn't make sense of it: {error}"
    return data.get("reply", "Nothing coherent to report, sir.")


DRAFT_REPLY_SYSTEM_PROMPT = """You are helping the user write a reply to an email. You will be
given the original email and the user's instructions for what the reply should say. Write ONLY
the body text of the reply — no subject line, no "Dear X" salutation unless it fits naturally,
no signature unless one is asked for. Match a normal professional-but-human email tone, not
JARVIS's spoken personality — this is an email the user is sending as themselves, in their own
voice. Always choose action "chat" and put the reply body in "reply"; leave every other field
blank."""


def _list_unread_mail(amount) -> str:
    if not gmail_client.is_configured():
        return "Gmail isn't connected yet — see the Gmail section in README.md to set it up."
    try:
        n = int(amount) if amount else 5
    except (TypeError, ValueError):
        n = 5
    n = max(1, min(n, 20))
    try:
        mails = gmail_client.list_unread(n)
    except Exception as e:
        return f"Couldn't reach Gmail: {e}"
    if not mails:
        return "Inbox is clear — no unread mail."
    lines = [f"{i + 1}) {m['sender']} — {m['subject']}" for i, m in enumerate(mails)]
    return f"{len(mails)} unread: " + "; ".join(lines)


def _draft_email_reply(query: str, instruction: str) -> str:
    if not gmail_client.is_configured():
        return "Gmail isn't connected yet — see the Gmail section in README.md to set it up."
    try:
        message = gmail_client.find_message(query)
    except Exception as e:
        return f"Couldn't reach Gmail: {e}"
    if not message:
        return f"Couldn't find an email matching '{query}' to reply to."

    info = gmail_client.message_summary(message)
    prompt = (
        f"Original email from {info['sender']}, subject \"{info['subject']}\":\n"
        f"{info['body'][:4000]}\n\n"
        f"What the reply should say: {instruction or 'a short, polite acknowledgement'}"
    )
    contents = [{"role": "user", "parts": [{"text": prompt}]}]
    data, error = llm.call(DRAFT_REPLY_SYSTEM_PROMPT, contents, RESPONSE_SCHEMA)
    if data is None:
        return f"Couldn't come up with a reply: {error}"

    reply_body = (data.get("reply") or "").strip()
    if not reply_body:
        return "Drew a blank on what to actually say — give me more to go on."

    try:
        gmail_client.create_draft_reply(message, reply_body)
    except Exception as e:
        return f"Wrote the reply but couldn't save the draft: {e}"
    return f"Drafted a reply to {info['sender']} about \"{info['subject']}\" — sitting in your Drafts folder."


def _search_history(query: str) -> str:
    hits = history.search(query)
    if not hits:
        return f"Nothing in our history about '{query}'."
    lines = [f"{h['time'][:10]}: you said '{h['user']}'" for h in hits[-3:]]
    return "Found this: " + "; ".join(lines)


IDLE_PROMPT = """You've been sitting idle for a while with no command from the user. Say ONE
short ambient remark — a single sentence, in character — just to make your presence
felt. Not a question that needs answering, not a status report, not repetitive
throat-clearing — something a sharp, quietly present aide would say when nothing's
happening: a dry observation, a small nudge, a flash of personality. Always choose action
"chat" and put it in "reply"; leave every other field blank."""


def idle_line() -> str:
    """One ambient one-liner for when nothing's happened in a while. Not a
    real command — doesn't touch short-term or persisted history."""
    known = memory.summary_for_prompt()
    profanity = PROFANITY_GUIDANCE.get(memory.get_profanity(), PROFANITY_GUIDANCE["medium"])
    language = LANGUAGE_GUIDANCE.get(memory.get_language(), LANGUAGE_GUIDANCE["en"])
    theme = memory.load().get("theme", "dark")
    mode = THEME_GUIDANCE.get(theme, THEME_GUIDANCE["dark"])
    system_instruction = (
        f"{SYSTEM_PROMPT}\n\nMode: {mode}\n\nSwearing: {profanity}\n\nLanguage: {language}"
        f"\n\n{IDLE_PROMPT}"
    )
    if known:
        system_instruction += f"\n\n{known}"

    contents = [{"role": "user", "parts": [{"text": "(no command — idle ambient moment)"}]}]
    data, error = llm.call(system_instruction, contents, RESPONSE_SCHEMA)
    if data is None:
        return ""
    return (data.get("reply") or "").strip()


def think(user_text: str, image=None) -> dict:
    known = memory.summary_for_prompt()
    profanity = PROFANITY_GUIDANCE.get(memory.get_profanity(), PROFANITY_GUIDANCE["medium"])
    language = LANGUAGE_GUIDANCE.get(memory.get_language(), LANGUAGE_GUIDANCE["en"])
    theme = memory.load().get("theme", "dark")
    mode = THEME_GUIDANCE.get(theme, THEME_GUIDANCE["dark"])
    system_instruction = f"{SYSTEM_PROMPT}\n\nMode: {mode}\n\nSwearing: {profanity}\n\nLanguage: {language}"
    if known:
        system_instruction += f"\n\n{known}"

    # Replay recent turns so this is an actual conversation, not a string of
    # amnesiac one-shot commands — "reply" only (plain language), not the
    # raw JSON action structure, so past turns don't confuse the model with
    # its own scaffolding.
    contents = []
    for past_user, past_reply in _history:
        contents.append({"role": "user", "parts": [{"text": past_user}]})
        contents.append({"role": "model", "parts": [{"text": past_reply}]})
    contents.append({"role": "user", "parts": [{"text": user_text}]})

    # llm.call handles the rest: which key to use, which provider that key
    # belongs to, and which models to try for it — including falling
    # through to another key if the first one is rate-limited or dead.
    data, error = llm.call(system_instruction, contents, RESPONSE_SCHEMA, image=image)

    if data is None:
        return {"action": "chat", "reply": f"My brain just hiccuped: {error}", "image_prompt": "", "code": "", "code_language": ""}

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

    # forget_everything already wiped history inside its handler above —
    # appending this exchange here would immediately put one entry right
    # back, defeating the entire point of a clean slate.
    if action != "forget_everything":
        _history.append((user_text, reply))
        history.add(user_text, reply, action)  # persists across restarts
        history.add_to_session(user_text, reply)

    trace = {
        "action": action,
        "params": {k: v for k, v in data.items()
                   if k not in ("action", "reply", "code") and v not in ("", None, [])},
        "result": result_text or "(no direct output)",
        "provider": llm.detect_provider(config.API_KEY),
        "history_used": len(_history),
    }

    return {
        "action": action,
        "trace": trace,
        "reply": reply,
        "image_prompt": data.get("query", "") if action == "generate_image" else "",
        "code": data.get("code", ""),
        "code_language": data.get("code_language", ""),
    }
