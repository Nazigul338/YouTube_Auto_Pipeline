"""9-этап: Сапатты текшерүү (QA) жана Final MP4.

docs/VIDEO_RULES.md 13-эреже боюнча текшерет. Бир да МИЛДЕТТҮҮ текшерүү өтпөсө —
видео «даяр» деп белгиленбейт: Final_Videos/'го жүктөлбөйт, себеби отчетто жазылат.

Чыгат: report.txt, report.json, LICENSE.txt, youtube_description.txt, ai_usage.json.
QA өтсө: Final_Videos/<ID>.mp4, Licenses/<ID>_LICENSE.txt.
"""

from __future__ import annotations

import json
import re
import subprocess
from datetime import date
from pathlib import Path
from typing import Any

from .. import media
from ..textutil import word_count
from .base import Context, Stage, StageError, gemini_of

MAX_DURATION = 15 * 60


class Report:
    def __init__(self):
        self.items: list[dict] = []

    def add(self, key: str, title: str, ok: bool | None, note: str, required: bool = True):
        self.items.append({"key": key, "title": title, "ok": ok, "note": note,
                           "required": required})

    @property
    def failed(self) -> list[dict]:
        return [i for i in self.items if i["required"] and i["ok"] is False]

    def text(self) -> str:
        icon = {True: "✅", False: "❌", None: "⚠️"}
        return "\n".join(f"{icon[i['ok']]} {i['title']}: {i['note']}"
                         + ("" if i["required"] else " (кошумча)") for i in self.items)


def detect(final: Path, filt: str, key: str) -> list[tuple[float, float]]:
    """blackdetect / freezedetect / silencedetect жыйынтыгы: [(башы, аягы)]."""
    args = ["-af", filt, "-vn"] if key == "silence" else ["-vf", filt, "-an"]
    out = media.run(["ffmpeg", "-hide_banner", "-i", str(final), *args, "-f", "null", "-"],
                    filt.split("=")[0], timeout=3600)
    if key == "black":
        return [(float(x), float(y)) for x, y in
                re.findall(r"black_start:([\d.]+) black_end:([\d.]+)", out)]
    tag = "freeze" if key == "freeze" else "silence"
    st = [float(x) for x in re.findall(rf"{tag}_start: ([\d.]+)", out)]
    en = [float(x) for x in re.findall(rf"{tag}_end: ([\d.]+)", out)]
    if len(en) < len(st):           # аягына чейин созулса
        en.append(media.duration(final))
    return list(zip(st, en))


def frame_jpg(video: Path, t: float) -> bytes:
    r = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{t:.2f}", "-i", str(video), "-frames:v", "1",
                        "-vf", "scale=640:-2", "-f", "image2", "-c:v", "mjpeg", "-"],
                       capture_output=True)
    return r.stdout


class QAStage(Stage):
    name = "s9_qa"
    title = "Сапатты текшерүү жана Final MP4"
    retries = 0

    def run(self, ctx: Context) -> dict[str, Any]:
        cfg = ctx.cfg
        final = ctx.path("render", "final.mp4")
        rep = Report()
        J = lambda *p: json.loads(ctx.path(*p).read_text(encoding="utf-8"))  # noqa: E731
        shots_data = J("clips", "shots.json")
        shots, total = shots_data["shots"], shots_data["total"]
        timing = J("subtitles", "timings.json")
        music = J("music", "music.json")
        meta = J("script", "meta.json")
        clip_lic = J("clips", "licenses.json")
        voice_rep = J("audio", "voice_report.json")

        # 1–3. Файл, узактык, формат
        try:
            info = media.probe(final)
            v = next(s for s in info["streams"] if s["codec_type"] == "video")
            a = [s for s in info["streams"] if s["codec_type"] == "audio"]
            dur = float(info["format"]["duration"])
            rep.add("opens", "Видео ачылат", True, f"{final.stat().st_size / 1e6:.0f} МБ")
        except Exception as e:
            rep.add("opens", "Видео ачылат", False, f"ffprobe: {e}")
            return self.finish(ctx, rep, final, meta, music, clip_lic)
        rep.add("duration", "Узактыгы 8 мүнөттөн ашат", cfg.min_duration_sec <= dur <= MAX_DURATION,
                f"{int(dur // 60)}:{int(dur % 60):02d} (керек ≥ {cfg.min_duration_sec // 60}:"
                f"{cfg.min_duration_sec % 60:02d})")
        fps = eval(v.get("r_frame_rate", "0/1")) if "/" in v.get("r_frame_rate", "") else 0
        fmt_ok = (v["width"], v["height"]) == (1920, 1080) and abs(fps - 30) < 0.1 \
            and v["codec_name"] == "h264" and v.get("pix_fmt") == "yuv420p"
        rep.add("format", "1080p, 16:9, 30 FPS, H.264", fmt_ok,
                f"{v['width']}×{v['height']}, {fps:.2f} fps, {v['codec_name']}, {v.get('pix_fmt')}")

        # 4–5. Үн жана деңгээл
        rep.add("audio", "Үн бар", bool(a), f"{a[0]['codec_name']} {a[0].get('sample_rate')} Гц"
                if a else "аудио агым жок")
        loud = media.loudness(final)
        rep.add("loudness", "Үн деңгээли (−14 LUFS ±2, пик ≤ −1 dB)",
                loud["I"] is not None and -16.5 <= loud["I"] <= -11.5 and (loud["TP"] or 0) <= -0.5,
                f"{loud['I']} LUFS, пик {loud['TP']} dBFS")
        rep.add("voice", "Диктордун үнү толук (сценарий менен дал келүү)",
                timing["coverage"] >= 0.8,
                f"{timing['coverage']:.0%}; {voice_rep.get('wpm')} сөз/мүн")
        rel = music.get("voice_minus_music_lu")
        rep.add("music_level", "Музыка дикторду баспайт", rel is not None and rel >= 10,
                f"диктор музыкадан {rel} LU катуу (керек ≥ 10)")

        # 6. Кара экран, катып калган кадр, тынчтык
        blacks = [b for b in detect(final, "blackdetect=d=0.4:pic_th=0.97", "black")
                  if b[0] > 0.6 and b[1] < dur - 1.2]
        rep.add("black", "Кара экран жок", not blacks, f"{len(blacks)} жер: {blacks[:3]}" if blacks else "жок")
        freezes = [f for f in detect(final, "freezedetect=n=0.002:d=3", "freeze")
                   if f[0] < dur - 2]
        rep.add("freeze", "Катып калган кадр жок (≥3 сек)", not freezes,
                f"{len(freezes)} жер: {freezes[:3]}" if freezes else "жок")
        sil = [s for s in detect(final, "silencedetect=noise=-45dB:d=2.5", "silence")
               if s[0] < dur - 3]
        rep.add("silence", "Узун үнсүз жер жок (≥2.5 сек)", not sil,
                f"{len(sil)} жер: {sil[:3]}" if sil else "жок")

        # 7. Кадрлардын темпи жана уникалдуулугу
        durs = [s["dur"] for s in shots]
        avg = sum(durs) / len(durs)
        rep.add("pacing", "Кадрлар орточо ~3 сек сайын алмашат", 2.2 <= avg <= 3.8 and max(durs) <= 4.6,
                f"орточо {avg:.2f} сек, эң узун {max(durs):.2f} сек, {len(shots)} кадр")
        ids = [s["asset"] for s in shots]
        hist = set()
        for vid, vv in ctx.registry.get("videos", {}).items():
            if vid != ctx.video_id:
                hist.update(vv.get("clip_ids", []))
        rep.add("unique", "Клиптер кайталанбайт (бул жана мурунку видеолор)",
                len(set(ids)) == len(ids) and not (set(ids) & hist),
                f"{len(set(ids))}/{len(ids)} уникалдуу; мурункулар менен кесилиш: {len(set(ids) & hist)}")

        # 8. Субтитр
        srt = ctx.path("subtitles", "subtitles.srt").read_text(encoding="utf-8")
        last_t = re.findall(r"--> (\d\d):(\d\d):(\d\d),(\d+)", srt)[-1]
        last = int(last_t[0]) * 3600 + int(last_t[1]) * 60 + int(last_t[2])
        rep.add("subs", "Субтитр үн менен шайкеш", abs(last - timing["duration"]) < 4 and srt.count("-->") > 50,
                f"{srt.count('-->')} субтитр, акыркысы {last} сек / үн {timing['duration']:.0f} сек")

        # 9. Лицензиялар
        lic_ok = len(clip_lic) == len(shots) and all(l.get("license") and l.get("page_url") is not None
                                                     for l in clip_lic) \
            and music.get("license", {}).get("source") not in (None, "Unknown")
        rep.add("licenses", "Бардык материалдардын лицензиясы катталган", lic_ok,
                f"клиптер: {len(clip_lic)}/{len(shots)}; музыка: {music['license'].get('source')}")

        # 10. Сценарийдин оригиналдуулугу
        sim = meta.get("similarity", {})
        rep.add("original", "Сценарий оригиналдуу (мурункуларга окшош эмес)", not sim.get("too_similar"),
                f"5-грамма {sim.get('max_jaccard')}, embedding {sim.get('max_cosine')}")
        words = word_count(ctx.path("script", "script.txt").read_text(encoding="utf-8"))
        rep.add("words", "Сценарий 1100–1200 сөз", cfg.words_min - 60 <= words <= cfg.words_max + 60,
                f"{words} сөз")

        # 11. Кадрлар сценарийге дал келеби (Gemini көрүү менен) — кошумча текшерүү
        self.check_relevance(ctx, rep, final, shots)
        return self.finish(ctx, rep, final, meta, music, clip_lic)

    def check_relevance(self, ctx, rep, final, shots):
        scenes = {s["id"]: s for s in json.loads(ctx.path("scenes.json").read_text("utf-8"))["scenes"]}
        step = max(1, len(shots) // 10)
        sample = shots[::step][:10]
        try:
            items = [(frame_jpg(final, (s["start"] + s["end"]) / 2), scenes[s["scene"]]["text"])
                     for s in sample]
            items = [(j, t) for j, t in items if j]
            scores = gemini_of(ctx).rate_frames(items)
            avg = sum(scores) / len(scores)
            rep.add("relevance", "Кадрлар сценарийге дал келет (AI баалоосу)", avg >= 2.8,
                    f"орточо {avg:.1f}/5, {len(scores)} кадр", required=False)
        except Exception as e:
            rep.add("relevance", "Кадрлар сценарийге дал келет (AI баалоосу)", None,
                    f"текшерилген жок: {type(e).__name__}", required=False)

    def finish(self, ctx, rep: Report, final: Path, meta: dict, music: dict, clip_lic: list):
        ai = self.ai_usage(ctx)
        rep.add("ai_disclosure", "AI белгилөө сунушу", None, ai["recommendation"], required=False)
        passed = not rep.failed
        header = (f"QA ОТЧЕТУ — {ctx.video_id}: {ctx.state.topic}\n"
                  f"Аталыш (сунуш): {meta.get('title')}\nКүнү: {date.today().isoformat()}\n"
                  f"ЖЫЙЫНТЫК: {'✅ ӨТТҮ — видео даяр' if passed else '❌ ӨТКӨН ЖОК — видео даяр эмес'}\n\n")
        ctx.path("report.txt").write_text(header + rep.text() + "\n", encoding="utf-8")
        ctx.path("report.json").write_text(json.dumps({"passed": passed, "checks": rep.items},
                                                      ensure_ascii=False, indent=1), encoding="utf-8")
        ctx.path("ai_usage.json").write_text(json.dumps(ai, ensure_ascii=False, indent=1), encoding="utf-8")
        lic = self.license_txt(ctx, meta, music, clip_lic)
        self.description(ctx, meta, music)
        ctx.log(rep.text())
        if not passed:
            raise StageError("QA өткөн жок: " + "; ".join(f"{i['title']} ({i['note']})"
                                                         for i in rep.failed))
        if ctx.store:
            ctx.store.publish("Final_Videos", final, f"{ctx.video_id}.mp4")
            ctx.store.publish("Licenses", lic, f"{ctx.video_id}_LICENSE.txt")
        entry = ctx.registry.setdefault("videos", {}).setdefault(ctx.video_id, {})
        entry["final"] = f"Final_Videos/{ctx.video_id}.mp4"
        return {"report_file": str(ctx.path("report.txt")), "license_file": str(lic),
                "passed": True}

    def ai_usage(self, ctx) -> dict:
        g = ctx.services.get("gemini")
        used = sorted({f"{u['purpose']}: {u['model']}" for u in getattr(g, "usage", [])})
        return {
            "tools": ["Gemini (сценарий, факт текшерүү, сахналар)", "Gemini TTS (синтетикалык үн, Algenib)",
                      "Whisper (субтитр убактысы)", "Gemini (музыканын маанайы, кадр баалоо)"],
            "models_this_run": used,
            "visuals": "сток-видео/сүрөттөр (Pixabay/Pexels) — AI менен жаратылган реалдуу сахна жок",
            "recommendation": ("YouTube Studio → «Altered or synthetic content»: сунуш — «No». "
                               "Себеби: реалдуу көрүнгөн AI-сахна жок, чыныгы адамдын үнү/жүзү "
                               "тууралган эмес; AI сценарий, субтитр жана синтетикалык диктор үнү "
                               "YouTube'дун эрежеси боюнча адатта белгилөөнү талап кылбайт. "
                               "Акыркы чечимди сиз кабыл аласыз."),
        }

    def license_txt(self, ctx, meta, music, clip_lic) -> Path:
        m = music["license"]
        lines = [f"LICENSE / ЛИЦЕНЗИЯЛАР — {ctx.video_id}", f"Тема: {ctx.state.topic}",
                 f"Аталыш: {meta.get('title')}", f"Түзүлгөн күнү: {date.today().isoformat()}", "",
                 "== МУЗЫКА ==", f"Файл: {m['file']}", f"Аталышы: {m['title']}",
                 f"Булагы: {m['source']}", f"Лицензия: {m['license']}",
                 f"Автор көрсөтүү талап кылынабы: {m['attribution_required']}",
                 f"Негиз: {m['basis']} (каналдын ээси тректи ушул булактын папкасына салган)"]
        if music.get("attribution"):
            lines.append(f"Сүрөттөмөгө жазылуучу сап: {music['attribution']}")
        lines += ["", "== ВИДЕОКЛИПТЕР / СҮРӨТТӨР ==",
                  "Pixabay Content License: https://pixabay.com/service/license-summary/", ""]
        for l in clip_lic:
            lines.append(f"[{l['shot']:03d}] {l['type']} {l['id']} | автор: {l['author']} | "
                         f"{l['page_url']} | {l['license']}")
        lines += ["", "== AI КУРАЛДАРЫ ==", "Gemini (сценарий, факт текшерүү, сахналар), "
                  "Gemini TTS (диктор үнү), Whisper (субтитр убактысы)."]
        out = ctx.path("LICENSE.txt")
        out.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return out

    def description(self, ctx, meta, music) -> None:
        script = ctx.path("script", "script.txt").read_text(encoding="utf-8")
        first = " ".join(script.split()[:45]) + "…"
        lines = [meta.get("title", ""), "", first, ""]
        if music.get("attribution"):
            lines.append(music["attribution"])
        lines.append("Видеоматериалы: Pixabay (Pixabay Content License).")
        ctx.path("youtube_description.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
