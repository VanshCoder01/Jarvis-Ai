"""
llm.py — talks to whichever AI provider your API key belongs to. Auto-detects
Gemini / OpenAI / Anthropic from the key's format, and every call_* function
returns the same thing: (parsed_dict_or_None, error_or_None), matching
brain.py's RESPONSE_SCHEMA — so brain.py doesn't need to know or care which
provider actually answered.

Only Gemini has had real end-to-end use so far. OpenAI and Anthropic support
is new — the request/response shapes are built from each provider's current
documented API, but if something doesn't work exactly right, that's the
most likely place to look first.
"""
import json

import config

_clients = {}


def detect_provider(api_key: str) -> str:
    key = (api_key or "").strip()
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


def _is_rate_limit_error(e) -> bool:
    msg = str(e).lower()
    return any(s in msg for s in ("429", "resource_exhausted", "quota", "rate limit", "rate-limit", "overloaded"))


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

    last_error = None
    for model_name in models:
        try:
            response = _gemini_client(api_key).models.generate_content(
                model=model_name, contents=contents, config=gen_config,
            )
            return json.loads(response.text), None
        except Exception as e:
            last_error = e
            if _is_rate_limit_error(e):
                continue
            break
    return None, last_error


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
            return json.loads(response.choices[0].message.content), None
        except Exception as e:
            last_error = e
            if _is_rate_limit_error(e):
                continue
            break
    return None, last_error


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
                    return block.input, None
            return None, RuntimeError("Claude didn't call the action tool")
        except Exception as e:
            last_error = e
            if _is_rate_limit_error(e):
                continue
            break
    return None, last_error


CALLERS = {"gemini": call_gemini, "openai": call_openai, "anthropic": call_anthropic, "openrouter": call_openai}


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
        models = (models_by_provider or config.PROVIDER_MODELS).get(
            provider, config.PROVIDER_MODELS["gemini"]
        )
        data, error = CALLERS[provider](api_key, system_instruction, contents, schema, models, image=image)
        if data is not None:
            if idx != start:
                # This key worked and the previous one didn't — start here
                # next time instead of walking the dead key again.
                memory.set_active_key_index(idx)
                config.API_KEY = api_key
            return data, None
        last_error = error
        # Rate-limited or dead key -> try the next key. Anything else
        # (malformed request, bug in our own code) would fail identically
        # on every key, so don't burn through all of them for nothing.
        if not (_is_rate_limit_error(error) or _is_key_dead_error(error)):
            break

    return None, last_error



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

        if provider == "gemini":
            from google.genai import types
            client = _gemini_client(api_key)
            mdl = model or config.PROVIDER_MODELS.get("gemini", ["gemini-2.5-flash"])[0]
            resp = client.models.generate_content(
                model=mdl, contents=[{"role": "user", "parts": [{"text": user_content}]}],
                config=types.GenerateContentConfig(system_instruction=system_instruction, temperature=0.9),
            )
            return ((resp.text or "").strip(), None)

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
    except Exception as e:
        return ("", str(e))
