"""Gemini REST клиенти (Colab/SDK кереги жок, стандарттык китепкана гана)."""
import json
import os
import time
import urllib.error
import urllib.request

from . import config


class LLMError(RuntimeError):
    pass


def _extract_json(text):
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text
        text = text.rsplit("```", 1)[0]
    return json.loads(text)


def generate_json(prompt, models=None, retries=2):
    """Prompt жөнөтөт, JSON кайтарат. Квота/503 болсо кийинки моделге өтөт."""
    key = os.environ.get("POULTRY_GEMINI_API_KEY")
    if not key:
        raise LLMError("POULTRY_GEMINI_API_KEY коюлган эмес (GitHub Secrets'ке кош).")
    body = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"responseMimeType": "application/json", "temperature": 0.9},
    }).encode()
    last = None
    for model in models or config.TEXT_MODELS:
        for attempt in range(retries + 1):
            req = urllib.request.Request(
                f"{config.API_BASE}/models/{model}:generateContent", data=body,
                headers={"Content-Type": "application/json", "x-goog-api-key": key})
            try:
                with urllib.request.urlopen(req, timeout=120) as r:
                    data = json.load(r)
                text = data["candidates"][0]["content"]["parts"][0]["text"]
                return _extract_json(text)
            except urllib.error.HTTPError as e:
                last = f"{model}: HTTP {e.code}"
                if e.code in (429, 500, 503) and attempt < retries:
                    time.sleep(2 ** attempt * 3)
                    continue
                break  # кийинки моделге
            except (KeyError, IndexError, json.JSONDecodeError) as e:
                last = f"{model}: жооп окулган жок ({type(e).__name__})"
                break
    raise LLMError(f"Бардык моделдер ишке ашкан жок. Акыркы ката: {last}")


def api_key():
    key = os.environ.get("POULTRY_GEMINI_API_KEY")
    if not key:
        raise LLMError("POULTRY_GEMINI_API_KEY коюлган эмес (GitHub Secrets'ке кош).")
    return key
