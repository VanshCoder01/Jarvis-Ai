"""
autopilot.py — Jarvis operating the PC the way a person does: look at the
screen, decide on one mouse or keyboard action, do it, look again.

Each step is: take a screenshot -> send it to a vision-capable model with the
goal and what has been done so far -> get back exactly one action -> perform
it with pyautogui -> repeat, until the model says it is done, the user stops
it, or the step limit is hit.

This drives the REAL mouse and keyboard, so it is deliberately boxed in:

- It only ever runs when the user starts it from the UI with a written goal.
- It refuses to run in simulation mode (which promises nothing real happens).
- One run at a time, capped at MAX_STEPS.
- STOP in the UI takes effect before the next action.
- pyautogui's failsafe stays on: shove the mouse into the top-left corner of
  the screen and the run aborts immediately. That works even if the Jarvis
  window is buried.
- The model is told not to do irreversible things (buying, sending, deleting,
  entering passwords) unless the goal explicitly asks for exactly that.

Needs a key for a model that can see images (Gemini, OpenAI and Anthropic
models in config.py all can; most small local Ollama models cannot).
"""
import base64
import ctypes
import threading
import time
from io import BytesIO

import pyautogui

import llm

MAX_STEPS = 30
SHOT_MAX_WIDTH = 1366          # screenshots are downscaled to this before upload
SETTLE_SECONDS = 0.9           # pause after an action so the screen can react

ACTIONS = ("click", "double_click", "right_click", "move", "type", "key",
           "hotkey", "scroll", "wait", "done")

SYSTEM_PROMPT = """You are JARVIS in AUTOPILOT mode, operating a Windows PC for the user by
looking at screenshots and controlling the mouse and keyboard, exactly as a person would.

Each turn you receive the current screenshot. Choose exactly ONE action:
- click / double_click / right_click (x, y): at that point on the screen.
- move (x, y): move the pointer there without clicking (e.g. to reveal a hover menu).
- type (text): type text at the current keyboard focus. Click the field first if it isn't focused.
- key (keys): press one key, e.g. "enter", "tab", "escape", "win", "backspace", "down".
- hotkey (keys): a combination joined with +, e.g. "ctrl+l", "alt+tab", "ctrl+shift+esc".
- scroll (amount): positive scrolls up, negative scrolls down; 3 is about one notch group.
- wait: do nothing for a moment, when something is still loading.
- done: the goal is achieved, or cannot be achieved. Explain which in "message".

Coordinates are NORMALISED: x and y each run from 0 to 1000, where (0,0) is the top-left
corner of the screenshot and (1000,1000) is the bottom-right. Aim for the centre of the
thing you want to hit.

Rules:
- Look at the screenshot before every decision. Never assume the last action worked; if the
  screen did not change the way you expected, try a different approach instead of repeating it.
- Prefer the keyboard when it is more reliable: press "win" and type an app name to launch it,
  use ctrl+l to focus a browser address bar.
- Put a short plain-language note of what you are doing and why in "message" every turn. The
  user reads these live.
- Do not do anything irreversible or consequential unless the goal explicitly asks for exactly
  that: no purchases, no sending messages or emails, no deleting files, no changing account or
  security settings. Never type a password or payment details. If the goal needs one of those,
  stop with "done" and say what the user has to do themselves.
- Do not interact with the J.A.R.V.I.S assistant window itself.
- When the goal is complete, use "done" straight away. Do not keep going."""

SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "action": {"type": "STRING", "enum": list(ACTIONS)},
        "x": {"type": "INTEGER"},
        "y": {"type": "INTEGER"},
        "text": {"type": "STRING"},
        "keys": {"type": "STRING"},
        "amount": {"type": "INTEGER"},
        "message": {"type": "STRING"},
    },
    "required": ["action", "message"],
}

_KEY_ALIASES = {"windows": "win", "super": "win", "cmd": "win", "control": "ctrl", "return": "enter",
                "esc": "escape", "del": "delete", "pgup": "pageup", "pgdn": "pagedown",
                "arrowup": "up", "arrowdown": "down", "arrowleft": "left", "arrowright": "right"}

_lock = threading.Lock()
_state = {"running": False, "goal": "", "steps": [], "status": "idle", "error": "",
          "stop": False, "run_id": 0}


class AutopilotError(Exception):
    pass


# ---------- pieces (kept small so they can be tested without a screen) ----------

def to_pixels(x, y, width: int, height: int):
    """Normalised 0-1000 coordinates -> real pixels, clamped a few pixels in
    from every edge so a slightly-off answer can never land in a screen
    corner and trip the failsafe by accident."""
    try:
        nx, ny = float(x), float(y)
    except (TypeError, ValueError):
        raise AutopilotError("The model gave no usable coordinates.")
    px = int(round(max(0.0, min(1000.0, nx)) / 1000.0 * (width - 1)))
    py = int(round(max(0.0, min(1000.0, ny)) / 1000.0 * (height - 1)))
    return max(4, min(width - 5, px)), max(4, min(height - 5, py))


def parse_keys(raw: str) -> list:
    keys = []
    for part in (raw or "").lower().replace(" ", "").split("+"):
        part = _KEY_ALIASES.get(part, part)
        if not part:
            continue
        if part not in pyautogui.KEYBOARD_KEYS:
            raise AutopilotError(f"'{part}' isn't a key I can press.")
        keys.append(part)
    if not keys:
        raise AutopilotError("No key was named.")
    return keys


def describe(step: dict) -> str:
    """One line of history fed back to the model on later turns."""
    a = step.get("action", "")
    if a in ("click", "double_click", "right_click", "move"):
        what = f"{a} at ({step.get('x')}, {step.get('y')})"
    elif a == "type":
        what = f"type {step.get('text', '')!r}"
    elif a in ("key", "hotkey"):
        what = f"{a} {step.get('keys', '')}"
    elif a == "scroll":
        what = f"scroll {step.get('amount')}"
    else:
        what = a
    return f"{what} -- {step.get('message', '')}".strip()


def capture():
    """(base64 JPEG, mime, screen_width, screen_height)."""
    img = pyautogui.screenshot()
    width, height = pyautogui.size()
    if img.width > SHOT_MAX_WIDTH:
        img = img.resize((SHOT_MAX_WIDTH, round(img.height * SHOT_MAX_WIDTH / img.width)))
    buf = BytesIO()
    img.convert("RGB").save(buf, format="JPEG", quality=72)
    return base64.b64encode(buf.getvalue()).decode("ascii"), "image/jpeg", width, height


def _type(text: str):
    if text.isascii():
        pyautogui.write(text, interval=0.018)
        return
    # pyautogui.write drops anything it has no key for (accents, Hindi, emoji),
    # so non-ASCII text goes through the clipboard instead.
    import pc_control
    pc_control.clipboard_write(text)
    pyautogui.hotkey("ctrl", "v")


def perform(step: dict, width: int, height: int) -> str:
    """Carry out one action on the real machine."""
    action = step.get("action")
    if action in ("click", "double_click", "right_click", "move"):
        px, py = to_pixels(step.get("x"), step.get("y"), width, height)
        # A visible, eased glide rather than a teleport: easier to follow,
        # and gives the user time to hit the failsafe corner.
        pyautogui.moveTo(px, py, duration=0.45, tween=pyautogui.easeInOutQuad)
        if action == "click":
            pyautogui.click()
        elif action == "double_click":
            pyautogui.doubleClick()
        elif action == "right_click":
            pyautogui.click(button="right")
        return f"{action.replace('_', ' ')} at {px}, {py}"
    if action == "type":
        text = step.get("text") or ""
        if not text:
            raise AutopilotError("Nothing to type.")
        _type(text)
        return f"typed {len(text)} characters"
    if action == "key":
        keys = parse_keys(step.get("keys") or step.get("text"))
        pyautogui.press(keys[0])
        return f"pressed {keys[0]}"
    if action == "hotkey":
        keys = parse_keys(step.get("keys") or step.get("text"))
        pyautogui.hotkey(*keys)
        return "pressed " + "+".join(keys)
    if action == "scroll":
        try:
            amount = int(step.get("amount") or -3)
        except (TypeError, ValueError):
            amount = -3
        amount = max(-15, min(15, amount))
        pyautogui.scroll(amount * 120)
        return f"scrolled {'up' if amount > 0 else 'down'}"
    if action == "wait":
        time.sleep(1.5)
        return "waited"
    raise AutopilotError(f"Unknown action: {action!r}")


def decide(goal: str, done_so_far: list, shot_b64: str, mime: str) -> dict:
    history = "\n".join(f"{i + 1}. {line}" for i, line in enumerate(done_so_far)) or "(nothing yet)"
    prompt = (f"Goal: {goal}\n\nActions taken so far:\n{history}\n\n"
              "The attached image is the screen right now. What is the single next action?")
    contents = [{"role": "user", "parts": [{"text": prompt}]}]
    data, error = llm.call(SYSTEM_PROMPT, contents, SCHEMA, image={"content": shot_b64, "mime": mime})
    if data is None:
        raise AutopilotError(str(error))
    if data.get("action") not in ACTIONS:
        raise AutopilotError(f"The model chose an action I don't have: {data.get('action')!r}")
    return data


# ---------- the Jarvis window: get it out of the way, bring it back after ----------

def _jarvis_window():
    try:
        user32 = ctypes.windll.user32
        hwnd = user32.GetForegroundWindow()
        buf = ctypes.create_unicode_buffer(256)
        user32.GetWindowTextW(hwnd, buf, 256)
        return hwnd if "J.A.R.V.I.S" in buf.value else None
    except Exception:
        return None


def _show(hwnd, minimized: bool):
    if not hwnd:
        return
    try:
        ctypes.windll.user32.ShowWindow(hwnd, 6 if minimized else 9)   # SW_MINIMIZE / SW_RESTORE
    except Exception:
        pass


# ---------- run control ----------

def status() -> dict:
    with _lock:
        return {"running": _state["running"], "goal": _state["goal"], "status": _state["status"],
                "error": _state["error"], "steps": list(_state["steps"]), "max_steps": MAX_STEPS}


def stop():
    with _lock:
        if _state["running"]:
            _state["stop"] = True
            _state["status"] = "stopping"
    return status()


def start(goal: str) -> dict:
    goal = (goal or "").strip()
    if not goal:
        raise AutopilotError("Tell me what to do first.")
    with _lock:
        if _state["running"]:
            raise AutopilotError("Autopilot is already running.")
        _state.update({"running": True, "goal": goal, "steps": [], "status": "running",
                       "error": "", "stop": False, "run_id": _state["run_id"] + 1})
    hwnd = _jarvis_window()
    threading.Thread(target=_run, args=(goal, hwnd), daemon=True).start()
    return status()


def _finish(final_status: str, error: str = ""):
    with _lock:
        _state.update({"running": False, "status": final_status, "error": error, "stop": False})


def _run(goal: str, hwnd):
    pyautogui.FAILSAFE = True
    _show(hwnd, minimized=True)
    time.sleep(0.6)
    lines = []
    try:
        for number in range(1, MAX_STEPS + 1):
            if _state["stop"]:
                _finish("stopped")
                return
            shot, mime, width, height = capture()
            step = decide(goal, lines, shot, mime)
            if _state["stop"]:
                _finish("stopped")
                return
            entry = {"n": number, "action": step["action"], "message": step.get("message", ""),
                     "x": step.get("x"), "y": step.get("y"), "text": step.get("text", ""),
                     "keys": step.get("keys", ""), "amount": step.get("amount"), "result": ""}
            if step["action"] == "done":
                with _lock:
                    _state["steps"].append(entry)
                _finish("done")
                return
            try:
                entry["result"] = perform(step, width, height)
            except AutopilotError as e:
                entry["result"] = f"couldn't do that: {e}"
            with _lock:
                _state["steps"].append(entry)
            lines.append(describe(step) + (f" [{entry['result']}]" if entry["result"].startswith("couldn't") else ""))
            time.sleep(SETTLE_SECONDS)
        _finish("limit", f"Stopped at the {MAX_STEPS}-step limit.")
    except pyautogui.FailSafeException:
        _finish("stopped", "Aborted: the mouse was moved to the top-left corner.")
    except AutopilotError as e:
        _finish("error", str(e))
    except Exception as e:   # never leave the run flagged as live
        _finish("error", f"Unexpected failure: {e}")
    finally:
        _show(hwnd, minimized=False)
