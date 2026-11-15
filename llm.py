"""
llm.py — talks to whichever AI provider your API key belongs to. Auto-detects
Gemini / OpenAI / Anthropic from the key's format, and every call_* function
returns the same thing: (parsed_dict_or_None, error_or_None), matching
brain.py's RESPONSE_SCHEMA — so brain.py doesn't need to know or care which
provider actually answered.

v1.07 adds Ollama (local models, no API key, nothing leaves the PC). It is
stored in the key list as a plain text entry -- "ollama", "ollama:qwen2.5",
or "ollama://host:11434/model" -- so it takes part in the normal fallback
chain: put it last as an offline backup, or use it on its own.

Only Gemini has had real end-to-end use so far. OpenAI and Anthropic support
is new — the request/response shapes are built from each provider's current
documented API, but if something doesn't work exactly right, that's the
most likely place to look first.
"""
import json
import re
import socket
import time
import urllib.error
import urllib.request

import config

_clients = {}

# Models Google/OpenAI/etc. told us are gone ("no longer available", 404) --
# skipped for the rest of the session so a retired name at the top of a
# config list doesn't cost an extra failed round-trip on every command.
_dead_models = set()

# Always tried after whatever config.py lists, so an old config.py (the
# installer never overwrites it) keeps working when Google retires a model.
_GEMINI_BUILTIN_FALLBACKS = ["gemini-3.8-flash", "gemini-3.7-flash", "gemini-2.5-flash", "gemini-2.0-flash"]

# What the last successful call() actually used -- shown in the trace panel so
# the BRAIN line is right even when a fallback key (or Ollama) answered.
last_call = {"provider": "", "model": ""}


def detect_provider(api_key: str) -> str:
    key = (api_key or "").strip()
    if key.lower().startswith("ollama"):
        return "ollama"
    if key.startswith("sk-ant-"):
        return "anthropic"
    if key.startswith("AIza"):
        return "gemini"
    if key.startswith("sk-or-"):
        return "openrouter"
    if key.startswith("sk-"):
        return "openai"
    return "gemini"  # best guess if the format doesn't match anything known


def reset_clients():
    """Call after the API key (or provider) changes, so a stale client for
    the old key isn't reused."""
    _clients.clear()
    _dead_models.clear()  # availability can differ per key


def _is_rate_limit_error(e) -> bool:
    msg = str(e).lower()
    return any(s in msg for s in ("429", "resource_exhausted", "quota", "rate limit", "rate-limit", "overloaded"))


def _is_transient_network_error(e) -> bool:
    """Connection-level failures (reset, dropped, DNS, timeout) -- not a bad
    key, not a bad model, nothing to do with the request itself."""
    msg = str(e).lower()
    return any(s in msg for s in (
        "10054", "10053", "10060", "forcibly closed", "connection reset", "connection aborted",
        "remote end closed", "remotedisconnected", "server disconnected", "connecterror",
        "connection error", "connection refused", "timed out", "timeout", "getaddrinfo failed",
        "name resolution", "network is unreachable", "eof occurred in violation",
    ))


def _friendly_network_error(e):
    if e is not None and not isinstance(e, OllamaUnavailable) and _is_transient_network_error(e):
        short = str(e).strip().splitlines()[0][:110]
        return RuntimeError(
            "I can't reach the AI service \u2014 the connection keeps getting cut "
            f"({short}). Check your internet, turn off any VPN, and allow Python through your "
            "firewall/antivirus. Adding Ollama as a key gives Jarvis an offline backup.")
    return e


def _is_model_gone_error(e) -> bool:
    """The *model name* is dead (retired / not available to this key) -- as
    opposed to the key being bad or the model being busy."""
    msg = str(e).lower()
    return any(s in msg for s in (
        "no longer available", "not_found", "404", "is not found", "model not found",
        "does not exist", "has been deprecated", "decommissioned", "not supported for generatecontent",
    ))


def _skip_to_next_model(e, model_name) -> bool:
    """Shared by every provider's model loop: True = try the next model."""
    if _is_rate_limit_error(e):
        return True
    if _is_model_gone_error(e):
        _dead_models.add(model_name)
        return True
    return False


def _no_model_error(provider):
    return RuntimeError(
        f"None of the configured {provider} models are available any more. "
        f"Update PROVIDER_MODELS in config.py to a current model name.")


def _to_json_schema_properties(schema):
    """Gemini's schema uses ALL-CAPS type names (STRING, OBJECT...); real
    JSON Schema (what OpenAI/Anthropic expect) uses lowercase."""
    props = {}
    for key, val in schema["properties"].items():
        val = dict(val)
        if isinstance(val.get("type"), str):
            val["type"] = val["type"].lower()
        if isinstance(val.get("enum"), list):
            val["enum"] = val["enum"]
        props[key] = val
    return props


def _contents_to_messages(contents, assistant_role="assistant"):
    messages = []
    for turn in contents:
        role = assistant_role if turn["role"] == "model" else turn["role"]
        messages.append({"role": role, "content": turn["parts"][0]["text"]})
    return messages


# ---------- Gemini ----------
def _gemini_client(api_key):
    cache_key = ("gemini", api_key)
    if cache_key not in _clients:
        from google import genai
        _clients[cache_key] = genai.Client(api_key=api_key)
    return _clients[cache_key]


def call_gemini(api_key, system_instruction, contents, schema, models, image=None):
    from google.genai import types
    gen_config = types.GenerateContentConfig(
        system_instruction=system_instruction,
        response_mime_type="application/json",
        response_schema=schema,
        temperature=0.9,
    )
    # Attach the image to the final user turn so the model actually sees it.
    if image and image.get("content"):
        import base64 as _b64
        try:
            raw = _b64.b64decode(image["content"])
            contents = list(contents)
            last = dict(contents[-1])
            last["parts"] = list(last["parts"]) + [
                {"inline_data": {"mime_type": image.get("mime", "image/png"), "data": raw}}
            ]
            contents[-1] = last
        except Exception:
            pass  # bad base64 shouldn't sink the whole request

    models = list(models) + [m for m in _GEMINI_BUILTIN_FALLBACKS if m not in models]
    last_error = None
    for model_name in models:
        if model_name in _dead_models:
            continue
        try:
            response = _gemini_client(api_key).models.generate_content(
                model=model_name, contents=contents, config=gen_config,
            )
            data = json.loads(response.text)
            last_call["model"] = model_name
            return data, None
        except Exception as e:
            last_error = e
            if _skip_to_next_model(e, model_name):
                continue
            break
    return None, last_error or _no_model_error("Gemini")


# ---------- OpenAI ----------
def _openai_client(api_key):
    cache_key = ("openai", api_key)
    if cache_key not in _clients:
        from openai import OpenAI
        # OpenRouter is OpenAI-compatible but on a different base URL.
        if api_key.startswith("sk-or-"):
            _clients[cache_key] = OpenAI(api_key=api_key, base_url="https://openrouter.ai/api/v1")
        else:
            _clients[cache_key] = OpenAI(api_key=api_key)
    return _clients[cache_key]


def call_openai(api_key, system_instruction, contents, schema, models, image=None):
    client = _openai_client(api_key)
    messages = [{"role": "system", "content": system_instruction}] + _contents_to_messages(contents)
    props = _to_json_schema_properties(schema)
    json_schema = {
        "type": "object",
        "properties": props,
        "required": list(props.keys()),
        "additionalProperties": False,
    }
    last_error = None
    for model_name in models:
        if model_name in _dead_models:
            continue
        try:
            response = client.chat.completions.create(
                model=model_name,
                messages=messages,
                response_format={
                    "type": "json_schema",
                    "json_schema": {"name": "jarvis_action", "strict": True, "schema": json_schema},
                },
                temperature=0.9,
            )
            data = json.loads(response.choices[0].message.content)
            last_call["model"] = model_name
            return data, None
        except Exception as e:
            last_error = e
            if _skip_to_next_model(e, model_name):
                continue
            break
    return None, last_error or _no_model_error("OpenAI")


# ---------- Anthropic (Claude) ----------
def _anthropic_client(api_key):
    cache_key = ("anthropic", api_key)
    if cache_key not in _clients:
        import anthropic
        _clients[cache_key] = anthropic.Anthropic(api_key=api_key)
    return _clients[cache_key]


def call_anthropic(api_key, system_instruction, contents, schema, models, image=None):
    client = _anthropic_client(api_key)
    messages = _contents_to_messages(contents)
    tool = {
        "name": "jarvis_action",
        "description": "Choose Jarvis's next action and fill in a spoken reply.",
        "input_schema": {
            "type": "object",
            "properties": _to_json_schema_properties(schema),
            "required": schema.get("required", []),
        },
    }
    last_error = None
    for model_name in models:
        if model_name in _dead_models:
            continue
        try:
            response = client.messages.create(
                model=model_name,
                max_tokens=1024,
                system=system_instruction,
                messages=messages,
                tools=[tool],
                tool_choice={"type": "tool", "name": "jarvis_action"},
            )
            for block in response.content:
                if block.type == "tool_use":
                    last_call["model"] = model_name
                    return block.input, None
            return None, RuntimeError("Claude didn't call the action tool")
        except Exception as e:
            last_error = e
            if _skip_to_next_model(e, model_name):
                continue
            break
    return None, last_error or _no_model_error("Claude")


# ---------- Ollama (local models) ----------
# Talks to a local Ollama server over plain HTTP using only the standard
# library, so there is nothing extra to pip install.
class OllamaUnavailable(RuntimeError):
    """Ollama can't answer right now (not running, no model pulled, timed
    out). That's neither a bug in Jarvis nor a dead cloud key -- it just means
    'try the next provider', which call() does."""


class _OllamaHTTPError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status
        self.message = message


_OLLAMA_DEFAULT_HOST = "http://127.0.0.1:11434"
# Good at following a JSON schema, roughly in order of preference. Anything
# you've pulled that isn't listed is still used if none of these are installed.
_OLLAMA_DEFAULT_PREFERRED = ["qwen2.5", "llama3.1", "llama3.2", "gemma3", "mistral", "phi4", "qwen3"]
_OLLAMA_VISION_HINTS = ("llava", "vision", "gemma3", "qwen2.5vl", "qwen2-vl", "minicpm-v",
                        "moondream", "bakllava", "mistral-small3")


def _ollama_cfg(name, default):
    # getattr, not config.X: the installer never overwrites an existing
    # config.py, so upgraders won't have the new settings in theirs.
    return getattr(config, name, default)


def _ollama_preferred(models_by_provider=None):
    if models_by_provider and models_by_provider.get("ollama"):
        return list(models_by_provider["ollama"])
    return list(_ollama_cfg("OLLAMA_PREFERRED_MODELS", _OLLAMA_DEFAULT_PREFERRED))


def _normalise_host(raw):
    """Accepts '127.0.0.1:11434', 'http://host:11434/', '0.0.0.0:11434'
    (Ollama's own OLLAMA_HOST env var often looks like that) and returns a
    clean http://host:port with no trailing slash."""
    raw = (raw or "").strip()
    if not raw:
        return _OLLAMA_DEFAULT_HOST
    if "://" not in raw:
        raw = "http://" + raw
    raw = raw.rstrip("/")
    raw = raw.replace("://0.0.0.0", "://127.0.0.1")
    # no port given -> Ollama's default
    if not re.search(r":\d+$", raw.split("://", 1)[1]):
        raw += ":11434"
    return raw


def ollama_default_host():
    return _normalise_host(_ollama_cfg("OLLAMA_HOST", "") or _OLLAMA_DEFAULT_HOST)


def parse_ollama_key(key):
    """'ollama' | 'ollama:model' | 'ollama://host:port' | 'ollama://host:port/model'
    -> (base_url, model_or_None)."""
    rest = (key or "").strip()[len("ollama"):]
    base, model = ollama_default_host(), None
    if rest.startswith("://"):
        hostport, _, mdl = rest[3:].partition("/")
        if hostport:
            base = _normalise_host(hostport)
        model = mdl.strip() or None
    elif rest.startswith(":"):
        model = rest[1:].strip() or None
    return base, model


def _ollama_http(base, path, payload=None, timeout=10):
    data, headers = None, {}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(base + path, data=data, headers=headers,
                                 method="POST" if payload is not None else "GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8", "replace")
        except Exception:
            pass
        msg = body
        try:
            msg = json.loads(body).get("error", body)
        except Exception:
            pass
        raise _OllamaHTTPError(e.code, msg or str(e))
    except (TimeoutError, socket.timeout):
        raise OllamaUnavailable(
            f"Ollama didn't answer within {timeout}s. A big model can take a while to load "
            f"the first time -- try again, or switch to a smaller model.")
    except (urllib.error.URLError, OSError) as e:
        reason = getattr(e, "reason", e)
        raise OllamaUnavailable(
            f"Can't reach Ollama at {base} ({reason}). Open the Ollama app, or run: ollama serve")


def _ollama_post_chat(base, payload, timeout):
    """POST /api/chat. If the model rejects the `think` flag (some thinking
    models only take named levels, and some builds reject it outright), retry
    once without it rather than failing the whole request."""
    try:
        return _ollama_http(base, "/api/chat", payload, timeout=timeout)
    except _OllamaHTTPError as e:
        if e.status == 400 and "think" in payload and "think" in e.message.lower():
            payload = {k: v for k, v in payload.items() if k != "think"}
            return _ollama_http(base, "/api/chat", payload, timeout=timeout)
        raise


def _is_embed_model(name):
    return "embed" in name.lower()


def _is_vision_model(name):
    n = name.lower()
    return any(h in n for h in _OLLAMA_VISION_HINTS)


def _name_matches(wanted, installed):
    w, n = wanted.lower(), installed.lower()
    return n == w or n.split(":")[0] == w


def ollama_installed_models(base=None):
    """Names of the chat-capable models pulled into Ollama. Raises
    OllamaUnavailable if the server can't be reached."""
    base = base or ollama_default_host()
    data = _ollama_http(base, "/api/tags", timeout=5)
    names = [m.get("name") or m.get("model") for m in data.get("models", [])]
    return [n for n in names if n and not _is_embed_model(n)]


def ollama_status(base=None):
    """For the UI: is Ollama up, and what can it run?"""
    base = base or ollama_default_host()
    try:
        version = _ollama_http(base, "/api/version", timeout=3).get("version", "")
        return {"running": True, "host": base, "version": version,
                "models": ollama_installed_models(base), "error": ""}
    except OllamaUnavailable as e:
        return {"running": False, "host": base, "version": "", "models": [], "error": str(e)}
    except Exception as e:
        return {"running": False, "host": base, "version": "", "models": [], "error": str(e)}


def _ollama_pick_models(base, explicit, preferred):
    """Ordered list of installed models worth trying. Uses the model named in
    the key if there is one, else your preferred list, else whatever is
    installed -- so 'ollama' with no model just works."""
    installed = ollama_installed_models(base)
    if explicit:
        for n in installed:
            if _name_matches(explicit, n):
                return [n]
        raise OllamaUnavailable(f"Ollama doesn't have '{explicit}' yet. Run: ollama pull {explicit}")
    if not installed:
        raise OllamaUnavailable("Ollama is running but has no models yet. Run: ollama pull llama3.2")
    ordered = []
    for pref in preferred:
        for n in installed:
            if _name_matches(pref, n) and n not in ordered:
                ordered.append(n)
    ordered += [n for n in installed if n not in ordered]
    return ordered


def _strip_think(text):
    # Reasoning models (qwen3, deepseek-r1...) may leak <think>...</think>.
    return re.sub(r"<think>.*?</think>", "", text or "", flags=re.S).strip()


def _parse_json_loose(text):
    text = _strip_think(text)
    try:
        return json.loads(text)
    except Exception:
        pass
    m = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.S)
    candidates = [m.group(1)] if m else []
    i, j = text.find("{"), text.rfind("}")
    if i != -1 and j > i:
        candidates.append(text[i:j + 1])
    for c in candidates:
        try:
            return json.loads(c)
        except Exception:
            continue
    return None


def _schema_hint(json_schema):
    lines = []
    for name, prop in json_schema["properties"].items():
        t = prop.get("type", "string")
        if prop.get("enum"):
            t += " (one of: " + ", ".join(prop["enum"]) + ")"
        lines.append(f"  {name}: {t}")
    return ("\n\nRespond with ONLY a single JSON object, no other text, using these fields "
            f"(required: {', '.join(json_schema.get('required', []))}):\n" + "\n".join(lines))


def _coerce(data, schema):
    """Small local models drift. Keep the result inside what brain.py expects."""
    props = schema.get("properties", {})
    if not isinstance(data, dict):
        return None
    action = props.get("action", {})
    if action.get("enum") and data.get("action") not in action["enum"]:
        data["action"] = "chat"
    if "reply" in props and not isinstance(data.get("reply"), str):
        data["reply"] = str(data.get("reply") or "Done.")
    return data


def call_ollama(api_key, system_instruction, contents, schema, models, image=None):
    """Same contract as the other call_* functions: (dict_or_None, error_or_None)."""
    try:
        base, explicit = parse_ollama_key(api_key)
        candidates = _ollama_pick_models(base, explicit, models or _ollama_preferred())
        if image and image.get("content"):
            # Vision-capable models first, if you have one installed.
            candidates.sort(key=lambda n: 0 if _is_vision_model(n) else 1)
    except OllamaUnavailable as e:
        return None, e
    except Exception as e:
        return None, OllamaUnavailable(str(e))

    props = _to_json_schema_properties(schema)
    json_schema = {"type": "object", "properties": props, "required": list(schema.get("required", []))}
    timeout = _ollama_cfg("OLLAMA_TIMEOUT", 180)
    keep_alive = _ollama_cfg("OLLAMA_KEEP_ALIVE", "30m")
    temperature = _ollama_cfg("OLLAMA_TEMPERATURE", 0.7)

    img_b64 = ""
    if image and image.get("content"):
        img_b64 = image["content"]
        if img_b64.startswith("data:") and "," in img_b64:
            img_b64 = img_b64.split(",", 1)[1]

    last_error = None
    for model in candidates[:3]:  # each cold model load is slow -- don't walk the whole list
        messages = [{"role": "system", "content": system_instruction}] + _contents_to_messages(contents)
        if img_b64:
            if _is_vision_model(model):
                messages[-1]["images"] = [img_b64]
            else:
                messages[-1]["content"] += ("\n\n(An image was attached, but this local model can't "
                                            "see images. Say so plainly instead of guessing.)")
        payload = {"model": model, "messages": messages, "stream": False, "think": False,
                   "format": json_schema, "keep_alive": keep_alive,
                   "options": {"temperature": temperature}}
        try:
            try:
                resp = _ollama_post_chat(base, payload, timeout)
            except _OllamaHTTPError as e:
                # Older Ollama (<0.5) only accepts format="json", not a schema.
                if e.status == 400 and "format" in e.message.lower():
                    messages[0]["content"] += _schema_hint(json_schema)
                    payload.update({"format": "json", "messages": messages})
                    resp = _ollama_post_chat(base, payload, timeout)
                else:
                    raise
            text = (resp.get("message") or {}).get("content", "")
            data = _coerce(_parse_json_loose(text), schema)
            if data is None and "action" in props and "reply" in props and _strip_think(text):
                data = {"action": "chat", "reply": _strip_think(text)}  # it answered in prose; fine
            if data is None:
                last_error = RuntimeError(f"{model} returned something Jarvis couldn't read.")
                continue
            last_call["model"] = model
            return data, None
        except _OllamaHTTPError as e:
            last_error = RuntimeError(f"Ollama ({model}): {e.message}")
            if e.status == 404:
                last_error = OllamaUnavailable(f"Ollama doesn't have '{model}'. Run: ollama pull {model}")
            continue
        except OllamaUnavailable as e:
            return None, e  # server gone or timed out -- other models won't fare better
    if last_error is None:
        last_error = OllamaUnavailable("Ollama gave no usable answer.")
    return None, last_error


CALLERS = {"gemini": call_gemini, "openai": call_openai, "anthropic": call_anthropic, "openrouter": call_openai, "ollama": call_ollama}


def _is_key_dead_error(e) -> bool:
    """Errors that mean 'this key itself is no good' rather than 'this
    model is momentarily busy' — no point retrying other models on the
    same key, move straight to the next key."""
    msg = str(e).lower()
    return any(s in msg for s in (
        "api key", "api_key", "invalid key", "unauthorized", "401", "403",
        "permission denied", "authentication", "billing", "suspended",
        "expired", "credit balance",
    ))


def call(system_instruction, contents, schema, models_by_provider=None, image=None):
    """Tries every stored API key in turn until one works.

    Order: starts at the last key known to work (so a dead first key isn't
    re-tried on every single request), then wraps around through the rest.
    Each key gets its own provider detected and its own model fallback
    list, so a Gemini key and an OpenAI key can sit side by side and each
    gets used correctly.

    Returns (data, error) exactly as before — brain.py doesn't need to know
    any of this happened.
    """
    import memory

    keys = memory.get_api_keys()
    if not keys:
        # Fall back to whatever's in config (env var / manual edit).
        keys = [config.API_KEY] if config.API_KEY else []
    if not keys:
        return None, RuntimeError("No API key set.")

    start = memory.get_active_key_index()
    order = list(range(start, len(keys))) + list(range(0, start))

    last_error = None
    for idx in order:
        api_key = keys[idx]
        provider = detect_provider(api_key)
        if provider == "ollama":
            models = _ollama_preferred(models_by_provider)
        else:
            models = (models_by_provider or config.PROVIDER_MODELS).get(
                provider, config.PROVIDER_MODELS["gemini"]
            )
            # A model named in settings (or JARVIS_MODEL) is tried first; if
            # this key's provider doesn't offer it, the normal list follows.
            override = (memory.load().get("model_override") or getattr(config, "MODEL_OVERRIDE", "")).strip()
            if override:
                models = [override] + [m for m in models if m != override]
        last_call["model"] = ""
        data, error = CALLERS[provider](api_key, system_instruction, contents, schema, models, image=image)
        if data is None and provider != "ollama" and _is_transient_network_error(error):
            # Often a stale pooled connection that the server already closed
            # (WinError 10054). Drop the cached client and try once more.
            _clients.clear()
            time.sleep(0.5)
            data, error = CALLERS[provider](api_key, system_instruction, contents, schema, models, image=image)
        if data is not None:
            last_call["provider"] = provider
            # Don't make a *backup* Ollama sticky: if a cloud key was only
            # rate-limited, the next request should try it again rather than
            # staying on the local model forever.
            if idx != start and provider != "ollama":
                # This key worked and the previous one didn't — start here
                # next time instead of walking the dead key again.
                memory.set_active_key_index(idx)
                config.API_KEY = api_key
            return data, None
        last_error = error
        # Ollama being down / out of models just means "try the next key".
        if isinstance(error, OllamaUnavailable):
            continue
        # Every model for this key's provider is retired -> another key
        # (maybe another provider) may still work.
        if _is_model_gone_error(error):
            continue
        # This provider is unreachable right now -> try the next key
        # (an Ollama backup doesn't need the internet at all).
        if _is_transient_network_error(error):
            continue
        # Rate-limited or dead key -> try the next key. Anything else
        # (malformed request, bug in our own code) would fail identically
        # on every key, so don't burn through all of them for nothing.
        if not (_is_rate_limit_error(error) or _is_key_dead_error(error)):
            break

    return None, _friendly_network_error(last_error)


def describe_last_call() -> str:
    """'ollama · qwen2.5:7b' / 'gemini' -- for the trace panel."""
    p = last_call.get("provider", "")
    m = last_call.get("model", "")
    return f"{p} \u00b7 {m}" if (p and m) else p



# ---------- plain-text calls (for the multi-agent room) ----------
# The main call() path is built around JSON-schema structured output, which is
# right for actions but wrong for free-form discussion. This is a simpler
# sibling: one system instruction, one user message, plain text back.
def call_text(api_key, system_instruction, user_content, model=None):
    """Returns (text, error). Never raises. Routes by the same provider
    detection as everything else; OpenRouter and OpenAI share the OpenAI SDK."""
    provider = detect_provider(api_key)
    try:
        if provider == "anthropic":
            client = _anthropic_client(api_key)
            mdl = model or config.PROVIDER_MODELS.get("anthropic", ["claude-haiku-4-5-20251001"])[0]
            resp = client.messages.create(
                model=mdl, max_tokens=1024,
                system=system_instruction,
                messages=[{"role": "user", "content": user_content}],
            )
            parts = [b.text for b in resp.content if getattr(b, "type", "") == "text"]
            return ("\n".join(parts).strip(), None)

        if provider == "ollama":
            base, explicit = parse_ollama_key(api_key)
            installed = ollama_installed_models(base)
            # An agent's saved model may belong to another provider; only
            # honour it if Ollama actually has it.
            wanted = next((n for n in installed if model and _name_matches(model, n)), None)
            mdl = wanted or _ollama_pick_models(base, explicit, _ollama_preferred())[0]
            resp = _ollama_post_chat(base, {
                "model": mdl, "stream": False, "think": False,
                "keep_alive": _ollama_cfg("OLLAMA_KEEP_ALIVE", "30m"),
                "options": {"temperature": _ollama_cfg("OLLAMA_TEMPERATURE", 0.7)},
                "messages": [{"role": "system", "content": system_instruction},
                             {"role": "user", "content": user_content}],
            }, _ollama_cfg("OLLAMA_TIMEOUT", 180))
            return (_strip_think((resp.get("message") or {}).get("content", "")), None)

        if provider == "gemini":
            from google.genai import types
            client = _gemini_client(api_key)
            wanted = [model] if model else []
            listed = list(config.PROVIDER_MODELS.get("gemini", []))
            candidates = wanted + [m for m in listed + _GEMINI_BUILTIN_FALLBACKS if m not in wanted]
            last_err = None
            for mdl in candidates:
                if mdl in _dead_models:
                    continue
                try:
                    resp = client.models.generate_content(
                        model=mdl, contents=[{"role": "user", "parts": [{"text": user_content}]}],
                        config=types.GenerateContentConfig(system_instruction=system_instruction, temperature=0.9),
                    )
                    return ((resp.text or "").strip(), None)
                except Exception as e:
                    last_err = e
                    if _skip_to_next_model(e, mdl):
                        continue
                    raise
            return ("", str(last_err or _no_model_error("Gemini")))

        # openai + openrouter both use the OpenAI SDK
        client = _openai_client(api_key)
        mdl = model or config.PROVIDER_MODELS.get(provider, ["gpt-4o-mini"])[0]
        resp = client.chat.completions.create(
            model=mdl,
            messages=[
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": user_content},
            ],
            temperature=0.9,
        )
        return (resp.choices[0].message.content.strip(), None)
    except _OllamaHTTPError as e:
        return ("", f"Ollama: {e.message}")
    except Exception as e:
        return ("", str(e))