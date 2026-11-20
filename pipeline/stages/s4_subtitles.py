"""4-этап: Субтитрлер (Whisper убакыты + сценарийдин так тексти).

  - Whisper (faster-whisper, CPU) ар бир сөздүн убактысын берет.
  - Субтитрдин ТЕКСТИ сценарийден алынат → орфография так (Whisper жаңылса да).
  - Whisper сөздөрү сценарий менен салыштырылат (difflib). Дал келүү < 80% болсо —
    үн сценарийден айырмаланат (TTS бир бөлүгүн окубай калган) → ката.
  - Сахналардын убактысы (башталышы/аягы) кийинки этаптар үчүн сакталат.
  - Чыгат: subtitles.srt (YouTube үчүн), subtitles.ass (видеого, анимациялуу, ачкыч
    сөздөр түстүү), timings.json.
"""

from __future__ import annotations

import difflib
import json
import re
from typing import Any

from .. import media
from ..textutil import WORD_RE
from .base import Context, Stage, StageError

MIN_COVERAGE = 0.80
LINE_CHARS = 34     # 72 px шрифтте бир сап ~1480 px'ке батат (1920 кеңдикте)
FONT_SIZE = 72      # телефондо окууга ыңгайлуу (мурун 60)
MARGIN_V = 96       # экрандын түбүнөн (мурун 72) — интерфейс/жээктен алыс
MAX_CUE_SEC = 3.6


def tokens_with_text(text: str) -> list[tuple[str, str]]:
    """[(нормалдаштырылган сөз, түп сөз+тыныш белгиси)]"""
    out = []
    for m in re.finditer(r"\S+", text):
        raw = m.group(0)
        w = WORD_RE.findall(raw.lower().replace("ё", "е"))
        if w:
            out.append(("".join(w), raw))
        elif out:  # өзүнчө тыныш белги (мис. «—») — мурунку сөзгө жабышат
            out[-1] = (out[-1][0], out[-1][1] + " " + raw)
    return out


def align(script_tokens: list[str], whisper_words: list[tuple[str, float, float]]):
    """Сценарийдин ар бир сөзүнө (start, end) берет. Кайтарат: (убакыттар, coverage)."""
    wnorm = [w for w, _, _ in whisper_words]
    sm = difflib.SequenceMatcher(None, script_tokens, wnorm, autojunk=False)
    times: list[tuple[float, float] | None] = [None] * len(script_tokens)
    matched = 0
    for a, b, size in sm.get_matching_blocks():
        for k in range(size):
            _, s, e = whisper_words[b + k]
            times[a + k] = (s, e)
            matched += 1
    # Дал келбеген сөздөр: кошуналардын ортосуна тамга санына жараша жайгаштыруу
    n = len(times)
    i = 0
    total_end = whisper_words[-1][2] if whisper_words else 0.0
    while i < n:
        if times[i] is not None:
            i += 1
            continue
        j = i
        while j < n and times[j] is None:
            j += 1
        left = times[i - 1][1] if i > 0 else 0.0
        right = times[j][0] if j < n else max(total_end, left + 0.3 * (j - i))
        lens = [max(1, len(script_tokens[k])) for k in range(i, j)]
        span = max(0.05 * (j - i), right - left)
        t = left
        for k, L in zip(range(i, j), lens):
            d = span * L / sum(lens)
            times[k] = (t, t + d)
            t += d
        i = j
    return times, (matched / n if n else 0.0)


def build_cues(raw_words: list[str], times: list[tuple[float, float]]):
    cues, cur, start = [], [], None
    for k, (w, (s, e)) in enumerate(zip(raw_words, times)):
        if start is None:
            start = s
        cur.append(k)
        text = " ".join(raw_words[i] for i in cur)
        end_punct = re.search(r"[.!?…]$", w)
        soft = re.search(r"[,;:—]$", w)
        nxt_len = len(text) + 1 + (len(raw_words[k + 1]) if k + 1 < len(raw_words) else 0)
        if (end_punct or nxt_len > LINE_CHARS or (soft and len(text) > LINE_CHARS * 0.6)
                or e - start > MAX_CUE_SEC or k == len(raw_words) - 1):
            cues.append({"start": start, "end": e, "idx": cur})
            cur, start = [], None
    # жылмакай: минималдуу узактык, кийинкисине тийбей
    for i, c in enumerate(cues):
        nxt = cues[i + 1]["start"] if i + 1 < len(cues) else c["end"] + 1.0
        c["end"] = min(max(c["end"] + 0.12, c["start"] + 0.8), nxt - 0.02)
    return cues


def pick_font(preferred: str | None = None) -> str:
    """Системада БАР шрифтти тандайт (жок шрифт — libass белгисиз алмаштырат).

    Тартиби: ниша жөндөөсү → Montserrat → DejaVu Sans. Бардыгы Bold менен колдонулат.
    """
    import subprocess

    try:
        have = subprocess.run(["fc-list", ":", "family"], capture_output=True, text=True,
                              timeout=20).stdout.lower()
    except Exception:
        have = ""
    for name in [preferred, "Montserrat", "DejaVu Sans"]:
        if name and name.lower() in have:
            return name
    return "DejaVu Sans"


def ts_srt(t: float) -> str:
    ms = int(round(t * 1000))
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"


def ts_ass(t: float) -> str:
    cs = int(round(t * 100))
    return f"{cs // 360000}:{cs // 6000 % 60:02d}:{cs // 100 % 60:02d}.{cs % 100:02d}"


ASS_HEADER = """[Script Info]
ScriptType: v4.00+
PlayResX: 1920
PlayResY: 1080
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Sub,{font},{size},&H00FFFFFF,&H00FFFFFF,&H00101010,&H96000000,-1,0,0,0,100,100,0.6,0,1,4.4,2.0,2,200,200,{margin},204

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
HIGHLIGHT = r"{\c&H3FC8FF&}"   # алтын-сары (BGR)


class SubtitlesStage(Stage):
    name = "s4_subtitles"
    title = "Субтитрлер (Whisper)"
    retries = 0

    def run(self, ctx: Context) -> dict[str, Any]:
        voice = ctx.path("audio", "voice.wav")
        script = ctx.path("script", "script.txt").read_text(encoding="utf-8")
        scenes = json.loads(ctx.path("scenes.json").read_text(encoding="utf-8"))["scenes"]

        whisper_words = self.transcribe(ctx, voice, script)
        toks = tokens_with_text(script)
        norm_tokens = [t for t, _ in toks]
        raw_words = [r for _, r in toks]
        times, coverage = align(norm_tokens, whisper_words)
        ctx.log(f"   Whisper: {len(whisper_words)} сөз; сценарий менен дал келүү {coverage:.0%}")
        if coverage < MIN_COVERAGE:
            raise StageError(f"Үн сценарийге {coverage:.0%} гана дал келет (керек ≥ "
                             f"{MIN_COVERAGE:.0%}) — TTS текстти толук окубаган болушу мүмкүн. "
                             f"3-этапты кайра иштетиңиз (rerun_from: s3_voice).")

        # сахналардын убактысы
        k = 0
        scene_times = []
        for s in scenes:
            n = len(tokens_with_text(s["text"]))
            if n == 0:
                continue
            seg = times[k:k + n]
            scene_times.append({"id": s["id"], "start": round(seg[0][0], 3),
                                "end": round(seg[-1][1], 3), "first_word": k, "words": n})
            k += n
        if k != len(times):
            raise StageError("Сахналардын сөздөрү сценарийге дал келген жок (ички ката)")
        total = media.duration(voice)

        cues = build_cues(raw_words, times)
        kw_index = self.keyword_index(scenes, scene_times, raw_words)
        font = pick_font(ctx.cfg.niche_data.get("subtitle_font"))
        ctx.log(f"   Субтитр шрифти: {font}, {FONT_SIZE} px, түбүнөн {MARGIN_V} px")
        header, hl = ASS_HEADER.format(font=font, size=FONT_SIZE, margin=MARGIN_V), HIGHLIGHT
        from .. import edit_concept
        if edit_concept.enabled(ctx):   # ар видеонун ӨЗ концепциясынын субтитр стили (оригиналдуулук)
            import re as _re

            b = edit_concept.get(ctx, scenes)
            fam = {"Montserrat Bold": "Montserrat", "DejaVu Sans Bold": "DejaVu Sans",
                   "DejaVu Serif Bold": "DejaVu Serif"}.get(b["subtitles"]["font"], b["subtitles"]["font"])
            sfont = pick_font(fam)
            style, hl = edit_concept.subtitle_style(b, sfont, MARGIN_V)
            header = _re.sub(r"Style: Sub,[^\n]*", lambda m: style, header)
            ctx.log(f"   Субтитр стили (концепция «{b['name']}»): {sfont}, {b['subtitles']['size']} px, "
                    f"{'кутуча' if b['subtitles']['box'] else 'контур'}, түс {b['subtitles']['primary']}/"
                    f"{b['subtitles']['highlight']}")
        ass = [header]
        srt = []
        for n_, c in enumerate(cues, 1):
            words = []
            for i in c["idx"]:
                w = raw_words[i].replace("{", "(").replace("}", ")")
                words.append(hl + w + r"{\c&HFFFFFF&}" if i in kw_index else w)
            text = " ".join(words)
            plain = " ".join(raw_words[i] for i in c["idx"])
            ass.append(f"Dialogue: 0,{ts_ass(c['start'])},{ts_ass(c['end'])},Sub,,0,0,0,,"
                       r"{\fad(90,90)}" + text)
            srt.append(f"{n_}\n{ts_srt(c['start'])} --> {ts_srt(c['end'])}\n{plain}\n")

        sub_dir = ctx.path("subtitles")
        (sub_dir / "subtitles.ass").write_text("\n".join(ass) + "\n", encoding="utf-8")
        (sub_dir / "subtitles.srt").write_text("\n".join(srt), encoding="utf-8")
        timing = {"coverage": round(coverage, 4), "duration": total,
                  "scenes": scene_times,
                  "words": [{"w": raw_words[i], "s": round(t[0], 3), "e": round(t[1], 3)}
                            for i, t in enumerate(times)]}
        tfile = ctx.path("subtitles", "timings.json")
        tfile.write_text(json.dumps(timing, ensure_ascii=False), encoding="utf-8")
        if ctx.store:
            ctx.store.publish("Subtitles", sub_dir / "subtitles.srt", f"{ctx.video_id}.srt")
            ctx.store.publish("Subtitles", sub_dir / "subtitles.ass", f"{ctx.video_id}.ass")
        ctx.log(f"   ✓ {len(cues)} субтитр, {len(scene_times)} сахнанын убактысы")
        return {"ass_file": str(sub_dir / "subtitles.ass"), "srt_file": str(sub_dir / "subtitles.srt"),
                "timings_file": str(tfile), "coverage": round(coverage, 4)}

    @staticmethod
    def keyword_index(scenes, scene_times, raw_words) -> set[int]:
        idx: set[int] = set()
        for s, t in zip(scenes, scene_times):
            for kw in s.get("keywords", []):
                kw_toks = [x for x, _ in tokens_with_text(kw)]
                if not kw_toks:
                    continue
                span = [x for x, _ in tokens_with_text(" ".join(
                    raw_words[t["first_word"]:t["first_word"] + t["words"]]))]
                for j in range(len(span) - len(kw_toks) + 1):
                    if span[j:j + len(kw_toks)] == kw_toks:
                        idx.update(range(t["first_word"] + j, t["first_word"] + j + len(kw_toks)))
                        break
        return idx

    def transcribe(self, ctx: Context, voice, script: str) -> list[tuple[str, float, float]]:
        from .. import asr

        return asr.get(ctx)(voice, script)
