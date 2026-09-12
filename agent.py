"""
agent.py — Jarvis's code-agent mode: a small tool-use loop that can read,
write, and list files inside a single project folder you pick, and run
shell commands there. This is a different shape from brain.py's one-shot
action dispatch — the model is called repeatedly, one tool call per turn,
with each result fed back in, until it signals "done" (or the step limit
below kicks in as a hard backstop against a confused loop).

Every provider llm.py supports is forced through the same JSON-schema
mechanism brain.py already uses for actions, rather than each provider's
own distinct native tool-calling protocol — that keeps this working
uniformly across Gemini/OpenAI/Anthropic without three separate multi-turn
tool-use implementations. Each turn is folded into a plain-text transcript
(model's tool call, then the tool's result) that gets replayed whole on
every subsequent call — see next_step() below.

Runs on config.AGENT_MODELS (the strongest model your key can reach), not
brain.py's fast default — this mode edits real files and can execute real
commands, so speed takes a back seat to getting it right.

run_command is the one tool this module will NOT execute on its own — see
server.py's /api/agent/confirm. Everything else here trusts the caller to
have already gated that.
"""
import os
import subprocess

import config
import llm

MAX_STEPS = 25  # hard ceiling so a confused model can't loop forever

TOOLS = ("read_file", "write_file", "list_dir", "run_command", "done")

AGENT_SYSTEM_PROMPT = """You are JARVIS operating in CODE AGENT mode. You have been given one
project folder to work in: {root}. You can read files, write files, list directories, and run
shell commands — all restricted to that folder and its subfolders; you cannot touch anything
outside it.

Work in small, deliberate steps. Each turn, choose exactly ONE tool call:
- read_file (path): read a file's contents.
- write_file (path, content): create or overwrite a file with the given content.
- list_dir (path): list a directory's contents. Use "." for the project root.
- run_command (command): run a shell command in the project folder. The user is shown this
  command and must approve it before it runs. Expect some turns to come back saying the user
  declined — if so, try a different approach rather than repeating the same command.
- done (message): call this once the task is actually finished. Put a short summary of what
  you did in "message".

Only fill in the fields the chosen tool actually needs; leave the rest blank. Explain your
reasoning briefly in "message" every turn, not just on "done" — it's shown to the user live as
you work, so make it informative enough to follow along, but don't pad it.

Never assume a command succeeded or a file looks a certain way — read the actual tool result
you're given back before deciding your next step."""

AGENT_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "tool": {"type": "STRING", "enum": list(TOOLS)},
        "path": {"type": "STRING"},
        "content": {"type": "STRING"},
        "command": {"type": "STRING"},
        "message": {"type": "STRING"},
    },
    "required": ["tool", "message"],
}


class AgentError(Exception):
    pass


def _safe_path(root: str, rel_path: str) -> str:
    """Resolves rel_path against root and refuses anything that escapes it —
    the whole point of "restricted to a single project folder". Blocks both
    ../ traversal and an absolute path pointing elsewhere."""
    rel_path = (rel_path or "").strip().lstrip("/\\") or "."
    root_abs = os.path.abspath(root)
    candidate = os.path.abspath(os.path.join(root_abs, rel_path))
    if candidate != root_abs and not candidate.startswith(root_abs + os.sep):
        raise AgentError(f"'{rel_path}' is outside the project folder — refusing.")
    return candidate


def read_file(root: str, path: str) -> str:
    full = _safe_path(root, path)
    if not os.path.isfile(full):
        return f"No file at {path}."
    try:
        with open(full, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
    except Exception as e:
        return f"Couldn't read {path}: {e}"
    if len(content) > 20000:
        return content[:20000] + f"\n...(truncated, {len(content)} chars total)"
    return content


def write_file(root: str, path: str, content: str) -> str:
    full = _safe_path(root, path)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    try:
        with open(full, "w", encoding="utf-8") as f:
            f.write(content or "")
    except Exception as e:
        return f"Couldn't write {path}: {e}"
    return f"Wrote {len(content or '')} chars to {path}."


def list_dir(root: str, path: str) -> str:
    full = _safe_path(root, path)
    if not os.path.isdir(full):
        return f"No directory at {path}."
    try:
        entries = sorted(os.listdir(full))
    except Exception as e:
        return f"Couldn't list {path}: {e}"
    if not entries:
        return "(empty)"
    return "\n".join((e + "/") if os.path.isdir(os.path.join(full, e)) else e for e in entries)


def run_command(root: str, command: str) -> str:
    """Actually executes a shell command in the project folder. The caller
    (server.py's /api/agent/confirm) is responsible for only reaching this
    after the user has approved it in the UI — this function itself does
    not gate on that."""
    command = (command or "").strip()
    if not command:
        return "No command given."
    try:
        result = subprocess.run(
            command, shell=True, cwd=os.path.abspath(root),
            capture_output=True, text=True, timeout=60,
        )
        out = ((result.stdout or "") + (result.stderr or "")).strip() or "(no output)"
        if len(out) > 4000:
            out = out[:4000] + "\n...(truncated)"
        return f"Exit code {result.returncode}. Output:\n{out}"
    except subprocess.TimeoutExpired:
        return "Command timed out after 60 seconds."
    except Exception as e:
        return f"Couldn't run command: {e}"


def next_step(root: str, goal: str, transcript: list) -> dict:
    """Asks the model for exactly one next tool call. `transcript` is a
    list of {"role": "model"|"user", "text": ...} entries the caller builds
    up across the loop — the running record of the task, with each tool
    call and result folded in as plain text so this works the same way
    across every provider llm.py supports."""
    system_instruction = AGENT_SYSTEM_PROMPT.format(root=os.path.abspath(root))
    contents = [{"role": "user", "parts": [{"text": f"Task: {goal}"}]}]
    for turn in transcript:
        contents.append({"role": turn["role"], "parts": [{"text": turn["text"]}]})

    data, error = llm.call(system_instruction, contents, AGENT_SCHEMA,
                            models_by_provider=config.AGENT_MODELS)
    if data is None:
        raise AgentError(str(error))
    if data.get("tool") not in TOOLS:
        raise AgentError(f"Model returned an unrecognized tool: {data.get('tool')!r}")
    return data
