"""
cli_brains.py — let Jarvis think with an AI coding CLI you already have
installed and signed in to, instead of (or alongside) an API key:

  claude-code            Claude Code (`claude`), default model sonnet
  claude-code:opus       ...or any model alias / id Claude Code accepts
  antigravity            Google Antigravity CLI (`agy`), Gemini 3.8 Flash (low)
  antigravity:<model>    ...or any id from `agy models`

They go in the same key list as everything else, so they fall back to and
from your other keys. They use your existing subscription/sign-in.

These CLIs are agents that can run commands and edit files. Jarvis only
wants a decision from them -- Jarvis itself carries out the action -- and
what it sends them can include email text and screen contents written by
someone else. So they run boxed in:

  Claude Code   no tools at all (--tools ""), no MCP servers, no user
                settings or hooks, no saved session, Jarvis's own system
                prompt instead of Claude Code's (which also keeps each call
                ~1-2k tokens instead of ~200k), in an empty temp folder.
  Antigravity   plan mode, --sandbox, in an empty temp folder, and never
                --dangerously-skip-permissions: headless mode auto-denies
                any tool that needs permission.

Neither takes an image here, so screen reading and image attachments pass
to the next key in the list.
"""
import json
import os
import shutil
import subprocess
import tempfile
import time

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
_MAX_ARG_CHARS = 30000          # Windows caps a command line at 32,767

CLIS = {
    "claude-code": {"label": "Claude Code", "exe": "claude", "default_model": "sonnet", "timeout": 120,
                    "fallback_paths": [os.path.join(os.path.expanduser("~"), ".local", "bin", "claude.exe")]},
    "antigravity": {"label": "Antigravity", "exe": "agy", "default_model": "gemini-3.8-flash-low",
                    "timeout": 150,
                    "fallback_paths": [os.path.join(os.environ.get("LOCALAPPDATA", ""), "agy", "bin", "agy.exe")]},
}


class CLIUnavailable(Exception):
    """This CLI can't answer right now -- llm.call moves to the next key."""


def is_cli_key(key: str) -> bool:
    k = (key or "").strip().lower()
    return any(k == name or k.startswith(name + ":") for name in CLIS)


def parse_key(key: str):
    """'claude-code:opus' -> ('claude-code', 'opus'); 'antigravity' -> ('antigravity', default)."""
    k = (key or "").strip()
    name, _, model = k.partition(":")
    name = name.lower()
    if name not in CLIS:
        raise CLIUnavailable(f"Unknown CLI '{name}'.")
    return name, (model.strip() or CLIS[name]["default_model"])


def find_exe(name: str):
    spec = CLIS[name]
    found = shutil.which(spec["exe"])
    if found:
        return found
    return next((p for p in spec["fallback_paths"] if p and os.path.isfile(p)), None)


def status() -> dict:
    """For the UI: which CLIs are installed here."""
    out = {}
    for name, spec in CLIS.items():
        exe = find_exe(name)
        out[name] = {"label": spec["label"], "installed": bool(exe), "default_model": spec["default_model"]}
    return out


# ---------- prompt ----------
def _json_schema(schema):
    import llm
    return {"type": "object", "properties": llm._to_json_schema_properties(schema),
            "required": schema.get("required", [])}


def _transcript(contents, budget):
    """The conversation as plain text, oldest turns dropped first if it
    won't fit the budget."""
    lines = []
    for turn in contents:
        who = "JARVIS" if turn["role"] == "model" else "USER"
        lines.append(f"{who}: {turn['parts'][0]['text']}")
    while len(lines) > 1 and sum(len(x) + 2 for x in lines) > budget:
        lines.pop(0)
    return "\n\n".join(lines)


_RULES = ("\n\nYou are only the decision-maker. Never use tools, run commands, or read or write "
          "files: JARVIS carries out the action you choose. Answer with exactly one JSON object "
          "matching the schema and nothing else.")


# ---------- running ----------
def _run(argv, stdin_text, timeout):
    workdir = tempfile.mkdtemp(prefix="jarvis_cli_")      # empty: nothing there to read or touch
    try:
        proc = subprocess.run(argv, input=stdin_text, capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=timeout, cwd=workdir, creationflags=_NO_WINDOW)
    except subprocess.TimeoutExpired:
        raise CLIUnavailable(f"{os.path.basename(argv[0])} took longer than {timeout}s.")
    except OSError as e:
        raise CLIUnavailable(f"Couldn't start {os.path.basename(argv[0])}: {e}")
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
    return proc


def _result_from(out_text, schema):
    import llm
    try:
        payload = json.loads(out_text)
    except ValueError:
        payload = None
    if isinstance(payload, dict):
        if payload.get("is_error"):
            raise CLIUnavailable(str(payload.get("result") or "the CLI reported an error"))
        data = payload.get("structured_output")
        if not isinstance(data, dict):
            data = llm._parse_json_loose(str(payload.get("result") or payload.get("response") or ""))
    else:
        data = llm._parse_json_loose(out_text or "")
    data = llm._coerce(data, schema)
    if not data:
        raise CLIUnavailable("the CLI didn't return a usable answer")
    return data


def _claude(exe, model, system_instruction, contents, schema):
    fd, sys_file = tempfile.mkstemp(prefix="jarvis_sys_", suffix=".txt")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(system_instruction + _RULES)
    try:
        argv = [exe, "-p", "--output-format", "json", "--model", model,
                "--system-prompt-file", sys_file,
                "--tools", "", "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}',
                "--setting-sources", "", "--no-session-persistence", "--disable-slash-commands",
                "--json-schema", json.dumps(_json_schema(schema))]
        proc = _run(argv, _transcript(contents, 60000), CLIS["claude-code"]["timeout"])
    finally:
        try:
            os.remove(sys_file)
        except OSError:
            pass
    if proc.returncode != 0 and not proc.stdout.strip():
        raise CLIUnavailable(_short(proc.stderr) or f"claude exited with {proc.returncode}")
    return _result_from(proc.stdout, schema)


def _antigravity(exe, model, system_instruction, contents, schema):
    head = "SYSTEM:\n" + system_instruction + _RULES + "\n\nCONVERSATION:\n"
    prompt = head + _transcript(contents, max(2000, _MAX_ARG_CHARS - len(head) - 2000))
    if len(prompt) > _MAX_ARG_CHARS:
        prompt = prompt[-_MAX_ARG_CHARS:]
    timeout = CLIS["antigravity"]["timeout"]
    argv = [exe, "-p=" + prompt, "--mode", "plan", "--sandbox", "--model", model,
            "--output-format", "json", "--print-timeout", f"{timeout - 10}s",
            "--json-schema", json.dumps(_json_schema(schema))]
    proc = _run(argv, "", timeout)
    if proc.returncode != 0 and not proc.stdout.strip():
        raise CLIUnavailable(_short(proc.stderr) or f"agy exited with {proc.returncode}")
    return _result_from(proc.stdout, schema)


def _short(text):
    text = " ".join((text or "").split())
    return text[:300]


last_call = {"cli": "", "model": "", "seconds": 0.0}


def call(api_key, system_instruction, contents, schema, models, image=None):
    """Same contract as llm.call_gemini & co: returns (data, error)."""
    try:
        name, model = parse_key(api_key)
        if image is not None:
            raise CLIUnavailable(f"{CLIS[name]['label']} can't look at images here.")
        exe = find_exe(name)
        if not exe:
            raise CLIUnavailable(f"{CLIS[name]['label']} isn't installed on this PC.")
        started = time.monotonic()
        runner = _claude if name == "claude-code" else _antigravity
        data = runner(exe, model, system_instruction, contents, schema)
        last_call.update(cli=name, model=model, seconds=round(time.monotonic() - started, 1))
        import llm
        llm.last_call["model"] = model
        return data, None
    except CLIUnavailable as e:
        return None, e
    except Exception as e:                     # never let a CLI quirk crash a request
        return None, CLIUnavailable(str(e))
