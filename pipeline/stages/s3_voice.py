"""3-этап: Диктор (Gemini TTS, Algenib).

  - Текст сахналардын чегинде ≤1200 белгилүү бөлүктөргө бөлүнөт (сүйлөм ортосунан эмес).
  - Ар бөлүккө БИРДЕЙ стиль-нускама берилет → үн бөлүктөр арасында бирдей угулат.
  - Ар бөлүк текшерилет: ылдамдыгы (сөз/мүнөт) жана ичиндеги узун тынчтык.
    Шектүү болсо — ошол бөлүк кайра жаратылат.
  - Даяр бөлүктөр кэште калат → иш үзүлсө, кайра жаратылбайт (квота үнөмдөлөт).
  - Бөлүктөр табигый паузалар менен бириктирилет, loudnorm (−16 LUFS) менен
    деңгээли бирдей кылынат. Жасалма жайлатуу (atempo) КОЛДОНУЛБАЙТ.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .. import media
from ..textutil import word_count
from .base import Context, Stage, StageError, gemini_of

CHUNK_CHARS = 1200
WPM_MIN, WPM_MAX = 105, 190       # табигый орус сүйлөөсүнүн чеги
GAP_SCENE = 0.45                   # бөлүктөрдүн ортосундагы пауза (сек)
MAX_INNER_SILENCE = 2.2


def make_chunks(scenes: list[dict]) -> list[str]:
    chunks, cur = [], ""
    for s in scenes:
        t = s["text"].strip()
        if cur and len(cur) + 1 + len(t) > CHUNK_CHARS:
            chunks.append(cur)
            cur = t
        else:
            cur = f"{cur} {t}".strip()
    if cur:
        chunks.append(cur)
    return chunks


class VoiceStage(Stage):
    name = "s3_voice"
    title = "Үн (Gemini TTS)"
    retries = 2

    def run(self, ctx: Context) -> dict[str, Any]:
        cfg = ctx.cfg
        scenes = json.loads(ctx.path("scenes.json").read_text(encoding="utf-8"))["scenes"]
        chunks = make_chunks(scenes)
        style = cfg.niche_data.get("tts_style", "Deep, calm, confident male voice.")
        g = gemini_of(ctx)
        cdir = ctx.path("audio", "chunks")
        cdir.mkdir(parents=True, exist_ok=True)
        ctx.log(f"   {len(chunks)} бөлүк, үн: {cfg.tts_voice}")

        report = []
        for i, text in enumerate(chunks, 1):
            wav = cdir / f"chunk_{i:02d}.wav"
            meta = cdir / f"chunk_{i:02d}.json"
            if wav.exists() and meta.exists() and \
                    json.loads(meta.read_text())["text"] == text:
                report.append(json.loads(meta.read_text()))
                continue  # мурунку иштетүүдөн калган — кайра жаратпайбыз
            info = self.make_chunk(ctx, g, text, style, wav, i, len(chunks))
            meta.write_text(json.dumps(info, ensure_ascii=False), encoding="utf-8")
            report.append(info)

        # бириктирүү: бөлүктөрдүн ортосуна табигый пауза, 48 кГц
        lst = cdir / "concat.txt"
        gap = cdir / "gap.wav"
        media.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
                   f"anullsrc=r=24000:cl=mono", "-t", str(GAP_SCENE), str(gap)], "пауза")
        lines = []
        for i in range(1, len(chunks) + 1):
            lines.append(f"file 'chunk_{i:02d}.wav'")
            if i < len(chunks):
                lines.append("file 'gap.wav'")
        lst.write_text("\n".join(lines) + "\n", encoding="utf-8")
        raw = ctx.path("audio", "voice_raw.wav")
        media.run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(lst),
                   "-c", "copy", str(raw)], "үн бөлүктөрүн бириктирүү")
        voice = ctx.path("audio", "voice.wav")
        media.run(["ffmpeg", "-y", "-v", "error", "-i", str(raw), "-af",
                   "highpass=f=60,loudnorm=I=-16:TP=-1.5:LRA=11", "-ar", "48000", "-ac", "1",
                   str(voice)], "үн деңгээлин нормалдаштыруу")

        dur = media.duration(voice)
        words = sum(word_count(c) for c in chunks)
        wpm = words / (dur / 60)
        ctx.log(f"   ✓ Үн: {dur / 60:.1f} мүн ({dur:.0f} сек), {wpm:.0f} сөз/мүн")
        if dur < cfg.min_duration_sec:
            ctx.log(f"   ⚠ Үн {cfg.min_duration_sec} секунддан кыска ({dur:.0f} сек). "
                    f"QA 8 мүнөттөн аз деп белгилейт; сценарийди узартуу керек болушу мүмкүн.")
        (ctx.path("audio", "voice_report.json")).write_text(json.dumps(
            {"duration": dur, "wpm": round(wpm, 1), "chunks": report}, ensure_ascii=False, indent=1),
            encoding="utf-8")
        if ctx.store:
            ctx.store.publish("Audio", voice, f"{ctx.video_id}_voice.wav")
        return {"voice_path": str(voice), "duration": round(dur, 2), "wpm": round(wpm, 1)}

    def make_chunk(self, ctx, g, text: str, style: str, wav: Path, i: int, n: int) -> dict:
        problems = []
        for attempt in range(1, 4):
            pcm, rate = g.tts(text, voice=ctx.cfg.tts_voice, style=style)
            dur = media.write_wav(wav, pcm, rate)
            wc = word_count(text)
            wpm = wc / (dur / 60) if dur else 0
            long_sil = [s for s in media.silences(wav, -42, MAX_INNER_SILENCE)
                        if 0.3 < s[0] < dur - 0.5]
            ok = WPM_MIN <= wpm <= WPM_MAX and not long_sil
            ctx.log(f"   🎙 {i}/{n}: {dur:.1f} сек, {wpm:.0f} сөз/мүн"
                    + ("" if ok else f" — шектүү ({attempt}-аракет)"))
            if ok:
                return {"text": text, "duration": dur, "wpm": round(wpm, 1), "attempts": attempt}
            problems.append(f"{wpm:.0f} сөз/мүн, тынчтык {long_sil[:2]}")
        raise StageError(f"{i}-бөлүктүн үнү 3 аракеттен кийин да шектүү: {problems}")
