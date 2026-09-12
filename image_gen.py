"""
image_gen.py — on-demand image generation via Gemini's image model
(gemini-2.5-flash-image, "Nano Banana"). Every image is saved to
%APPDATA%\\Jarvis\\generated_images\\ so you can find it again later, and
also handed back as base64 so the UI can show it immediately.
"""
import base64
import os
import time

from google.genai import types

import config

_client = None


def _get_client():
    global _client
    if _client is None:
        from google import genai
        key = config.IMAGE_GEMINI_API_KEY or config.API_KEY
        _client = genai.Client(api_key=key)
    return _client


def _save_dir() -> str:
    d = os.path.join(os.environ.get("APPDATA", "."), "Jarvis", "generated_images")
    os.makedirs(d, exist_ok=True)
    return d


def generate(prompt: str):
    """Returns (base64_image_or_None, mime_type_or_None, saved_path_or_None, error_or_None)."""
    prompt = (prompt or "").strip()
    if not prompt:
        return None, None, None, "no prompt given"
    try:
        response = _get_client().models.generate_content(
            model=config.IMAGE_MODEL,
            contents=[prompt],
            config=types.GenerateContentConfig(response_modalities=["TEXT", "IMAGE"]),
        )
        for part in response.parts:
            inline = getattr(part, "inline_data", None)
            if inline is not None and getattr(inline, "data", None):
                raw = inline.data
                mime = getattr(inline, "mime_type", None) or "image/png"
                ext = "jpg" if "jpeg" in mime else "png"
                path = os.path.join(_save_dir(), f"jarvis_{int(time.time())}.{ext}")
                with open(path, "wb") as f:
                    f.write(raw)
                return base64.b64encode(raw).decode("ascii"), mime, path, None
        return None, None, None, "no image came back in the response"
    except Exception as e:
        return None, None, None, str(e)
