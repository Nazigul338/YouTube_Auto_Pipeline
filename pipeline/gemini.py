"""Gemini API менен ишенимдүү иштөө.

Сыноолордо (probe) аныкталган чындыктар:
  - TTS (`speech_config`) v1beta'да гана иштейт → бардык суроолор v1beta аркылуу.
  - `gemini-3.8-flash` көп учурда 503 «high demand» берет → запас моделдер тизмеси.
  - 429 RESOURCE_EXHAUSTED: мүнөттүк лимит (күтүү жардам берет) же күнүмдүк
    квота / акысыз деңгээлде жок функция (күтүү жардам бербейт).
  - Суроо илинип калышы мүмкүн → ар бир суроого timeout.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any, Callable

from .errors import StageError, TransientError

TRANSIENT_CODES = {408, 429, 500, 502, 503, 504}


def _code(exc: Exception) -> int | None:
    c = getattr(exc, "code", None) or getattr(exc, "status_code", None)
    try:
        return int(c)
    except (TypeError, ValueError):
        return None


def _is_daily_quota(exc: Exception) -> bool:
    t = str(exc).lower()
    return "perday" in t or "per day" in t or "check your plan and billing" in t


def _is_timeout(exc: Exception) -> bool:
    name = type(exc).__name__.lower()
    return "timeout" in name or "timed out" in str(exc).lower()


def _short(exc: Exception) -> str:
    return f"{type(exc).__name__} [{_code(exc)}]: {str(exc)[:200]}"


class Gemini:
    def __init__(self, api_key: str, *, text_models: list[str], tts_models: list[str],
                 embed_model: str = "gemini-embedding-001", timeout_s: int = 180,
                 log: Callable[[str], None] = print, sleep: Callable[[float], None] = time.sleep,
                 client: Any = None):
        self.text_models = text_models
        self.tts_models = tts_models
        self.embed_model = embed_model
        self.log = log
        self.sleep = sleep
        if client is None:
            from google import genai
            from google.genai import types

            client = genai.Client(api_key=api_key, http_options=types.HttpOptions(
                api_version="v1beta", timeout=timeout_s * 1000))
        self.client = client
        self.usage: list[dict] = []   # кайсы модель эмне үчүн колдонулду (AI отчету үчүн)
        self.skip_until: dict[str, float] = {}   # иштебеген моделдер: убактылуу четке кагылат

    # ------------------------------------------------------------ жалпы
    def _call(self, models: list[str], fn: Callable[[str], Any], purpose: str,
              attempts: int = 2) -> Any:
        errors: list[str] = []
        all_transient = True
        candidates = [m for m in models if self.skip_until.get(m, 0) < time.time()] or models
        for model in candidates:
            for attempt in range(1, attempts + 1):
                try:
                    result = fn(model)
                    self.usage.append({"purpose": purpose, "model": model})
                    return result
                except StageError:
                    raise
                except Exception as e:
                    code = _code(e)
                    errors.append(f"{model}: {_short(e)}")
                    if code == 429 and _is_daily_quota(e):
                        self.log(f"   ⚠ {model}: квота/лимит бүттү → кийинки модель")
                        self.skip_until[model] = time.time() + 6 * 3600
                        break
                    if _is_timeout(e):
                        self.log(f"   ⚠ {model}: жооп бербей калды (timeout) → кийинки модель")
                        self.skip_until[model] = time.time() + 20 * 60
                        break
                    if code in TRANSIENT_CODES or code is None:
                        if attempt < attempts:
                            wait = 10 * attempt
                            self.log(f"   ⚠ {model}: {code or type(e).__name__} — {wait} сек кийин кайра")
                            self.sleep(wait)
                            continue
                        self.log(f"   ⚠ {model}: {attempts} аракет ийгиликсиз → кийинки модель "
                                 f"(10 мүн четке кагылат)")
                        self.skip_until[model] = time.time() + 10 * 60
                        break
                    all_transient = False  # 400/403/404 — бул модель жарабайт
                    self.log(f"   ⚠ {model}: {code} — кийинки модель")
                    break
        detail = "\n".join(errors[-6:])
        msg = f"Gemini ({purpose}) иштеген жок. Акыркы каталар:\n{detail}"
        raise (TransientError if all_transient else StageError)(msg)

    # ------------------------------------------------------------ текст
    def text(self, prompt: str, *, purpose: str = "text", temperature: float = 0.9,
             system: str | None = None, models: list[str] | None = None) -> str:
        from google.genai import types

        def fn(model: str) -> str:
            r = self.client.models.generate_content(
                model=model, contents=prompt,
                config=types.GenerateContentConfig(temperature=temperature,
                                                   system_instruction=system))
            text = (r.text or "").strip()
            if not text:
                raise RuntimeError("бош жооп")
            return text

        return self._call(models or self.text_models, fn, purpose)

    def json(self, prompt: str, *, purpose: str = "json", temperature: float = 0.7,
             system: str | None = None) -> Any:
        from google.genai import types

        def fn(model: str) -> Any:
            r = self.client.models.generate_content(
                model=model, contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=temperature, system_instruction=system,
                    response_mime_type="application/json"))
            return parse_json(r.text or "")

        return self._call(self.text_models, fn, purpose)

    # ------------------------------------------------------------ үн
    TTS_PROMPTS = (
        # 0: англисче режиссёрдук нускама + текст (нускаманы окубоо эскертилет)
        "Read the following Russian text aloud as a narrator. Voice direction (do NOT read "
        "it aloud): {style}\n\n{text}",
        # 1: (алынды — сыноодо «Say in a deep…» деп ОКУЛУП калды) → таза текст
        "{text}",
        # 2: таза текст — нускама эч качан окулбайт (стиль үн тандоосунан гана)
        "{text}",
    )

    def tts(self, text: str, *, voice: str, style: str, variant: int = 0) -> tuple[bytes, int]:
        """PCM s16le моно байттары жана жыштыгы. Gemini WAV да, таза PCM да кайтара алат."""
        import io
        import wave

        from google.genai import types

        style_short = "Say in a deep, calm, confident voice"
        prompt = self.TTS_PROMPTS[variant].format(style=style.strip(), style_short=style_short,
                                                  text=text.strip())

        def fn(model: str) -> tuple[bytes, int]:
            r = self.client.models.generate_content(
                model=model, contents=prompt,
                config=types.GenerateContentConfig(
                    response_modalities=["AUDIO"],
                    speech_config=types.SpeechConfig(voice_config=types.VoiceConfig(
                        prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=voice)))))
            part = r.candidates[0].content.parts[0].inline_data
            data, mime = part.data or b"", part.mime_type or ""
            if data[:4] == b"RIFF":
                with wave.open(io.BytesIO(data)) as w:
                    if w.getsampwidth() != 2 or w.getnchannels() != 1:
                        raise RuntimeError(f"күтүлбөгөн WAV: {w.getsampwidth()}B×{w.getnchannels()}ch")
                    rate, pcm = w.getframerate(), w.readframes(w.getnframes())
            else:
                m = re.search(r"rate=(\d+)", mime)
                rate, pcm = (int(m.group(1)) if m else 24000), data
            if len(pcm) < rate:  # < 0.5 сек
                raise RuntimeError("аудио бош же өтө кыска")
            return pcm, rate

        return self._call(self.tts_models, fn, "tts")

    # ------------------------------------------------------------ башка
    def embed(self, texts: list[str]) -> list[list[float]]:
        def fn(model: str) -> list[list[float]]:
            out = []
            for t in texts:
                r = self.client.models.embed_content(model=model, contents=t[:8000])
                out.append(list(r.embeddings[0].values))
            return out

        return self._call([self.embed_model], fn, "embedding")

    def rate_frames(self, items: list[tuple[bytes, str]]) -> list[int]:
        """Кадр сценарийдин ошол бөлүгүнө канчалык дал келет: 1–5 упай."""
        from google.genai import types

        def fn(model: str) -> list[int]:
            contents: list[Any] = [
                "You check a video edit. For each numbered frame, rate 1-5 how well the image "
                "illustrates the narration text next to it (5 = clearly matches the meaning, "
                "3 = acceptable mood match, 1 = unrelated). Return JSON array of integers only."]
            for k, (jpg, text) in enumerate(items, 1):
                contents += [f"Frame {k}. Narration (Russian): {text[:300]}",
                             types.Part.from_bytes(data=jpg, mime_type="image/jpeg")]
            r = self.client.models.generate_content(
                model=model, contents=contents,
                config=types.GenerateContentConfig(response_mime_type="application/json",
                                                   temperature=0.1))
            scores = parse_json(r.text or "[]")
            return [int(s) for s in scores][:len(items)]

        return self._call(self.text_models, fn, "frame_check")

    def ask_about_file(self, path: Path, prompt: str, *, purpose: str = "file") -> str:
        def fn(model: str) -> str:
            f = self.client.files.upload(file=str(path))
            try:
                for _ in range(60):
                    f = self.client.files.get(name=f.name)
                    if str(getattr(f, "state", "")).endswith("ACTIVE"):
                        break
                    self.sleep(1)
                r = self.client.models.generate_content(model=model, contents=[f, prompt])
                return (r.text or "").strip()
            finally:
                try:
                    self.client.files.delete(name=f.name)
                except Exception:
                    pass

        return self._call(self.text_models, fn, purpose)


def parse_json(text: str) -> Any:
    """Моделдин жообунан JSON'ду бөлүп алат (```json блогу болсо да)."""
    text = text.strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if m:
        text = m.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = min([i for i in (text.find("{"), text.find("[")) if i >= 0], default=-1)
        if start >= 0:
            end = max(text.rfind("}"), text.rfind("]"))
            return json.loads(text[start:end + 1])
        raise


def from_config(cfg, log: Callable[[str], None] = print) -> Gemini:
    from .config import get_secret

    key = get_secret("GOOGLE_API_KEY")
    if not key:
        raise StageError("GOOGLE_API_KEY жок (GitHub Secrets'ке кошуңуз)")
    return Gemini(key, text_models=list(cfg.text_models), tts_models=list(cfg.tts_models),
                  embed_model=cfg.embed_model, log=log)
