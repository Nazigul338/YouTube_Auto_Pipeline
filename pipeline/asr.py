"""Сүйлөөнү текстке (Whisper) — 3-этапта (TTS текшерүү) жана 4-этапта (субтитр) колдонулат.

PyAV колдонулбайт: faster-whisper 1.2.1 + av 19 шайкеш эмес экени сыноодо далилденген.
Аудио ffmpeg аркылуу декоддолуп, Whisper'ге массив катары берилет.
"""

from __future__ import annotations

from pathlib import Path

from . import media
from .errors import StageError
from .textutil import WORD_RE

_MODELS: dict[str, object] = {}


def _model(name: str):
    if name not in _MODELS:
        from faster_whisper import WhisperModel

        _MODELS[name] = WhisperModel(name, device="cpu", compute_type="int8")
    return _MODELS[name]


def norm_word(w: str) -> str:
    return "".join(WORD_RE.findall(w.lower().replace("ё", "е")))


def transcribe(path: Path, hint: str = "", model: str = "small") -> list[tuple[str, float, float]]:
    """[(нормалдаштырылган сөз, башы, аягы)]"""
    audio = media.decode_float32(path)
    segments, _ = _model(model).transcribe(
        audio, language="ru", word_timestamps=True, beam_size=5, vad_filter=False,
        condition_on_previous_text=False,   # сөздөрдү «жоготуп» коюудан сактайт
        initial_prompt=" ".join(hint.split()[:60]) or None)
    out = []
    for seg in segments:
        for w in seg.words or []:
            n = norm_word(w.word)
            if n:
                out.append((n, float(w.start), float(w.end)))
    if not out:
        raise StageError("Whisper бир дагы сөз тапкан жок — аудио бош болушу мүмкүн")
    return out


def get(ctx):
    """Тесттерде ctx.services["asr"] менен алмаштырылат: fn(path, hint) -> words."""
    if "asr" in ctx.services:
        return ctx.services["asr"]
    return lambda path, hint="": transcribe(path, hint, ctx.cfg.whisper_model)
