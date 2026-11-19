"""settings.json жана course.json'ду жүктөө (баары өзгөртүлө турган, ачкыч жок)."""
import json
import os

HERE = os.path.dirname(__file__)
DEFAULTS = {
    "default_lang": "ky", "graph_version": "v23.0", "publish_live": False,
    "autopilot": {"enabled": False, "required_approved_publishes": 5},
    "voice": {"provider": "gemini", "elevenlabs_voice_id": None, "elevenlabs_model": "eleven_v3",
              "owner_consent_confirmed": False, "disclose_ai_voice": True},
    "video": {"min_seconds": 15, "max_seconds": 60,
              "ai_label": {"ky": "AI иллюстрация", "ru": "AI-иллюстрация"}},
}


def _load(name, default):
    path = os.environ.get("POULTRY_" + name.split(".")[0].upper() + "_FILE", os.path.join(HERE, name))
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return default
    if isinstance(default, dict):
        merged = {**default, **data}
        for k, v in default.items():
            if isinstance(v, dict) and isinstance(data.get(k), dict):
                merged[k] = {**v, **data[k]}
        return merged
    return data


def load_settings():
    return _load("settings.json", DEFAULTS)


def load_course():
    return _load("course.json", {})
