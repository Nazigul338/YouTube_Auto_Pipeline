"""3-этап: Диктор (Gemini TTS, Algenib).

  - Текст сахналардын чегинде ≤1200 белгилүү бөлүктөргө бөлүнөт (сүйлөм ортосунан эмес).
  - Ар бөлүккө БИРДЕЙ стиль-нускама берилет → үн бөлүктөр арасында бирдей угулат.
  - Ар бөлүк текшерилет: ылдамдыгы (сөз/мүнөт), ичиндеги узун тынчтык жана
    Whisper менен «угулат»: башы сценарийдин башына дал келеби (нускама окулган
    эмеспи — сыноодо Gemini «Скажи спокойно…» деп окуп койгон), текст толук окулдубу.
    Шектүү болсо — ошол бөлүк башка промпт ыкмасы менен кайра жаратылат.
  - Даяр бөлүктөр кэште калат → иш үзүлсө, кайра жаратылбайт (квота үнөмдөлөт).
  - БИР ВИДЕО — БИР TTS МОДЕЛИ (эреже 4: үн башынан аягына чейин бирдей). Биринчи
    ийгиликтүү бөлүктүн модели бекитилет; анын күнүмдүк квотасы бүтсө — эртең улантылат.
  - Акысыз TTS квотасы аз (сыноодо ~10–15 суроо/күн/модель) → бөлүктөр чоң (1400 белги).
  - Бөлүктөр табигый паузалар менен бириктирилет, loudnorm (−16 LUFS) менен
    деңгээли бирдей кылынат. Жасалма жайлатуу (atempo) КОЛДОНУЛБАЙТ.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import difflib

from .. import asr, media
from ..textutil import word_count
from .base import Context, Stage, StageError, gemini_of

CHUNK_CHARS = 1400                 # акысыз TTS квотасы аз → суроолор аз болсун
WPM_MIN, WPM_MAX = 105, 190       # табигый орус сүйлөөсүнүн чеги
GAP_SCENE = 0.45                   # бөлүктөрдүн ортосундагы пауза (сек)
MAX_INNER_SILENCE = 2.2


def chunk_keywords(scenes: list[dict]) -> list[list[str]]:
    """make_chunks менен бирдей топтоо — ар бөлүктүн сахналарынын ачкыч сөздөрү (басым үчүн)."""
    out, cur, kws = [], "", []
    for s in scenes:
        t = s["text"].strip()
        if cur and len(cur) + 1 + len(t) > CHUNK_CHARS:
            out.append(kws)
            cur, kws = t, list(s.get("keywords") or [])
        else:
            cur = f"{cur} {t}".strip()
            kws += list(s.get("keywords") or [])
    if cur:
        out.append(kws)
    return out


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
        from .. import voice_style
        motivational = voice_style.enabled(ctx.store)     # СЫНАК гана (TEST папкасы + желек)
        kw_per_chunk = chunk_keywords(scenes) if motivational else []
        from .. import story as stl
        is_story = stl.is_story(cfg)
        if motivational:
            ctx.log("   🎙 " + ("КИНО-ОКУЯ айтуучусу" if is_story else "МОТИВАЦИЯЛЫК стиль") +
                    ": режиссура + паузалар + басым")
        g = gemini_of(ctx)
        cdir = ctx.path("audio", "chunks")
        cdir.mkdir(parents=True, exist_ok=True)
        ctx.log(f"   {len(chunks)} бөлүк, үн: {cfg.tts_voice}")

        pin_file = cdir / "model.txt"
        self.pinned = pin_file.read_text().strip() if pin_file.exists() else None
        if self.pinned:
            ctx.log(f"   Бул видеонун TTS модели бекитилген: {self.pinned}")
        report = []
        for i, text in enumerate(chunks, 1):
            wav = cdir / f"chunk_{i:02d}.wav"
            meta = cdir / f"chunk_{i:02d}.json"
            if wav.exists() and meta.exists():
                old = json.loads(meta.read_text())
                same_style = (old.get("style") == "motivational") == motivational   # стиль алмашса — кайра
                if old["text"] == text and old.get("model") == self.pinned and same_style:
                    report.append(old)
                    continue  # мурунку иштетүүдөн калган — кайра жаратпайбыз
            if motivational:
                info = self.make_chunk(ctx, g, text, voice_style.direction(kw_per_chunk[i - 1], story=is_story), wav, i,
                                       len(chunks), tts_text=voice_style.shape_text(text))
                info["style"] = "motivational"
            else:
                info = self.make_chunk(ctx, g, text, style, wav, i, len(chunks))
            if not self.pinned:
                self.pinned = info["model"]
                pin_file.write_text(self.pinned)
                ctx.log(f"   TTS модели бекитилди: {self.pinned}")
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

    def make_chunk(self, ctx, g, text: str, style: str, wav: Path, i: int, n: int,
                   tts_text: str | None = None) -> dict:
        problems = []
        listen = asr.get(ctx)
        expect = [asr.norm_word(w) for w in text.split() if asr.norm_word(w)]
        for attempt, variant in enumerate((0, 2, 0, 2), 1):
            pcm, rate = g.tts(tts_text or text, voice=ctx.cfg.tts_voice, style=style, variant=variant,
                              models=[self.pinned] if self.pinned else None)
            used = next((u["model"] for u in reversed(getattr(g, "usage", []))
                         if u.get("purpose") == "tts"), self.pinned or "?")
            dur = media.write_wav(wav, pcm, rate)
            wpm = len(expect) / (dur / 60) if dur else 0
            long_sil = [s for s in media.silences(wav, -42, MAX_INNER_SILENCE)
                        if 0.3 < s[0] < dur - 0.5]
            heard = [w for w, _, _ in listen(wav, text)]
            extra_head, coverage, gap = check_heard(expect, heard)
            wav.with_name(f"{wav.stem}_heard_{attempt}.txt").write_text(" ".join(heard), encoding="utf-8")
            ok = (WPM_MIN <= wpm <= WPM_MAX and not long_sil and extra_head <= 1
                  and coverage >= 0.82 and gap <= 7)
            why = [] if ok else [x for x, bad in (
                (f"{wpm:.0f} сөз/мүн", not WPM_MIN <= wpm <= WPM_MAX),
                (f"тынчтык {long_sil[:1]}", bool(long_sil)),
                (f"башында {extra_head} ашыкча сөз (нускама окулган)", extra_head > 1),
                (f"текст {coverage:.0%} гана угулду", coverage < 0.82),
                (f"{gap} сөз катары менен окулбай калды", gap > 7)) if bad]
            ctx.log(f"   🎙 {i}/{n}: {dur:.1f} сек, {wpm:.0f} сөз/мүн, дал келүү {coverage:.0%}"
                    + ("" if ok else f" — {', '.join(why)} ({attempt}-аракет)"))
            if ok:
                return {"text": text, "duration": dur, "wpm": round(wpm, 1), "model": used,
                        "coverage": round(coverage, 3), "attempts": attempt, "prompt_variant": variant}
            problems.append("; ".join(why))
        raise StageError(f"{i}-бөлүктүн үнү 4 аракеттен кийин да туура эмес: {problems}")


def check_heard(expect: list[str], heard: list[str]) -> tuple[int, float, int]:
    """(башындагы ашыкча сөздөр, сценарийдин канчасы угулду, эң узун угулбаган катар).

    Whisper'дин жөнөкөй каталары ЧАЧЫРАНДЫ болот; TTS бир бөлүктү окубай калса —
    КАТАР үзгүлтүк пайда болот. Ошондуктан узун катар — негизги белги.
    """
    if not heard:
        return 0, 0.0, len(expect)
    sm = difflib.SequenceMatcher(None, expect, heard, autojunk=False)
    blocks = [b for b in sm.get_matching_blocks() if b.size]
    matched = sum(b.size for b in blocks)
    first = next((b for b in blocks if b.size >= 2), blocks[0] if blocks else None)
    extra_head = (first.b - first.a) if first else len(heard)
    gap, pos = 0, 0
    for b in blocks + [difflib.Match(len(expect), len(heard), 0)]:
        gap = max(gap, b.a - pos)
        pos = b.a + b.size
    return max(0, extra_head), matched / max(1, len(expect)), gap
