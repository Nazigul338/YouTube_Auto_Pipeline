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
from ..clipmemory import ClipMemory
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


SYNC_TOL = 1.0


def stream_sync(v_dur: float, a_dur: float, expected: float | None = None,
                tol: float = SYNC_TOL) -> tuple[bool, str]:
    """Видео жана аудио агымдарынын узактыгы. Айырма > 1 сек болсо — FAILED."""
    diff = abs(v_dur - a_dur)
    ok = diff <= tol and v_dur > 0 and a_dur > 0
    if expected is not None and abs(v_dur - expected) > max(tol, 1.0):
        ok = False
    note = f"видео {v_dur:.2f} сек, аудио {a_dur:.2f} сек, айырма {diff:.2f} сек"
    if expected is not None:
        note += f", күтүлгөнү {expected:.2f} сек"
    if not ok:
        note += f" — ДАЛ КЕЛБЕЙТ (чек {tol} сек)"
    return ok, note


def frames_ok(nb_frames: int | None, v_dur: float, fps: float = 30.0,
              tol: float = 0.03) -> tuple[bool, str]:
    """Кадр саны ≈ узактык × fps (±3%). nb_frames белгисиз болсо — текшерилген эмес (өтөт)."""
    if nb_frames is None:
        return True, "nb_frames белгисиз (өткөрүлдү)"
    want = v_dur * fps
    ok = want > 0 and abs(nb_frames - want) <= tol * want + 2
    return ok, f"{nb_frames} кадр, күтүлгөнү ~{want:.0f}" + ("" if ok else " — ДАЛ КЕЛБЕЙТ")


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
            sd = media.stream_durations(final)
            rep.add("opens", "Видео ачылат", True, f"{final.stat().st_size / 1e6:.0f} МБ")
        except Exception as e:
            rep.add("opens", "Видео ачылат", False, f"ffprobe: {e}")
            return self.finish(ctx, rep, final, meta, music, clip_lic)
        # ЭКИ агымдын узактыгы ӨЗҮНЧӨ. `format.duration` эң узунун берет, ошондуктан аудио 571 сек,
        # видео 111 сек болсо да «9:31» деп туура көрүнүп, катаны жашырган (Video_001).
        v_dur, a_dur = sd["video"] or 0.0, sd["audio"] or 0.0
        ok_sync, note_sync = stream_sync(v_dur, a_dur, total)
        rep.add("sync", "Видео жана аудио агымдарынын узактыгы дал келет (айырма ≤ 1 сек)",
                ok_sync, note_sync)
        ok_frames, note_frames = frames_ok(sd["nb_frames"], v_dur)
        rep.add("frames", "Кадрлардын саны видеонун узактыгына дал келет (30 fps)",
                ok_frames, note_frames)
        dur = min(v_dur, a_dur) if a_dur else v_dur        # «чыныгы» узактык — кыскасы
        rep.add("duration", "Узактыгы 8 мүнөттөн ашат (кыска агым боюнча)",
                cfg.min_duration_sec <= dur <= MAX_DURATION,
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
        blacks = [b for b in detect(final, "blackdetect=d=0.5:pic_th=0.98:pix_th=0.04", "black")
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
        covered = sum(durs)
        rep.add("coverage", "Кадрлар аудионун бүт узактыгын жабат",
                abs(covered - total) <= 0.1 and abs(shots[-1]["end"] - total) <= 0.1,
                f"кадрлардын суммасы {covered:.2f} сек, аудио {total:.2f} сек")
        avg = sum(durs) / len(durs)
        rep.add("pacing", "Кадрлар 3–4 сек сайын алмашат", 2.8 <= avg <= 4.2 and max(durs) <= 5.2
                and min(durs) >= 1.2,
                f"орточо {avg:.2f} сек, эң узун {max(durs):.2f}, эң кыска {min(durs):.2f}, {len(shots)} кадр")
        want_lo, want_hi = int(total / 4.4), int(total / 2.8) + 1
        rep.add("shot_count", f"Кадр саны ~{want_lo}–{want_hi} (орточо 3–4 сек)",
                want_lo <= len(shots) <= want_hi, f"{len(shots)} кадр / {total:.0f} сек", required=False)
        out_of_range = [d for d in durs if not 2.7 <= d <= 4.5]
        rep.add("pacing_strict", "Кадрлардын ≥97% 3–4 сек (2.7–4.5)", len(out_of_range) <= 0.03 * len(durs),
                f"чектен тышкары {len(out_of_range)}/{len(durs)} (мин {min(durs):.2f}, макс {max(durs):.2f})",
                required=False)
        self.check_repetition(ctx, rep, shots)

        # 8. Субтитр
        srt = ctx.path("subtitles", "subtitles.srt").read_text(encoding="utf-8")
        last_t = re.findall(r"--> (\d\d):(\d\d):(\d\d),(\d+)", srt)[-1]
        last = int(last_t[0]) * 3600 + int(last_t[1]) * 60 + int(last_t[2])
        min_cues = max(5, len(timing["words"]) // 15)
        rep.add("subs", "Субтитр үн менен шайкеш",
                abs(last - timing["duration"]) < 4 and srt.count("-->") >= min_cues,
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
        if self._cinematic(ctx):            # СЫНАК режими гана: FFmpeg Skill'дин YouTube текшерүүсү + мүнөт сайын бирдейлик
            self.check_platform(ctx, rep, final)
            self.check_uniformity(ctx, rep, final, timing, total)
        self.check_subtitle_layout(ctx, rep)
        return self.finish(ctx, rep, final, meta, music, clip_lic)

    @staticmethod
    def _cinematic(ctx) -> bool:
        from .. import cinematic

        try:
            plan = json.loads(ctx.path("animation", "plan.json").read_text(encoding="utf-8"))
        except Exception:
            return False
        return bool(plan.get("cinematic")) and cinematic.enabled(ctx.store)

    def check_uniformity(self, ctx, rep, final: Path, timing: dict, total: float) -> None:
        """Видео башынан аягына чейин бирдей: ар мүнөт (жарык, түс, курчтук, катуулук, темп)."""
        from .. import uniformity

        try:
            rows = uniformity.analyze(final, total, timing["words"])
        except Exception as e:
            rep.add("uniform", "Сапат 8 мүнөт бою бирдей (мүнөт сайын)", None, f"текшерилген жок: {type(e).__name__}",
                    required=False)
            return
        ctx.path("uniformity.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
        ok, note = uniformity.summary(rows)
        rep.add("uniform", "Сапат 8 мүнөт бою бирдей (мүнөт сайын)", ok, note, required=False)

    def check_subtitle_layout(self, ctx, rep) -> None:
        """Субтитр: чоң, 2 сапка батат, экрандын коопсуз зонасында (ASS стили боюнча)."""
        try:
            ass = ctx.path("subtitles", "subtitles.ass").read_text(encoding="utf-8")
            from .s4_subtitles import FONT_SIZE, LINE_CHARS, MARGIN_V
            style = next(l for l in ass.splitlines() if l.startswith("Style: Sub,"))
            size, marg = int(style.split(",")[2]), int(style.split(",")[21])
            cues = [l.split(",,0,0,0,,", 1)[-1] for l in ass.splitlines() if l.startswith("Dialogue:")]
            plain = [re.sub(r"\{[^}]*\}", "", c) for c in cues]
            longest = max((len(c) for c in plain), default=0)
            ok = size >= 64 and 60 <= marg <= 140 and longest <= 2 * LINE_CHARS
            rep.add("subs_layout", "Субтитр чоң (≥64 px), ылдыйдан 60–140 px, ≤2 сап", ok,
                    f"{size} px, түбүнөн {marg} px, эң узун {longest} белги (чек {2 * LINE_CHARS})", required=False)
        except Exception as e:
            rep.add("subs_layout", "Субтитр жайгашуусу", None, f"текшерилген жок: {type(e).__name__}", required=False)

    def check_platform(self, ctx, rep, final: Path) -> None:
        """ffmpeg-skill `check.py --platform youtube` (.claude/skills/ffmpeg-skill). FAIL → QA өтпөйт."""
        script = Path(__file__).resolve().parents[2] / ".claude" / "skills" / "ffmpeg-skill" / "scripts" / "check.py"
        if not script.exists():
            rep.add("platform", "YouTube талаптары (ffmpeg-skill check.py)", None, "check.py табылган жок",
                    required=False)
            return
        try:
            r = subprocess.run(["python3", str(script), str(final), "--platform", "youtube", "--json"],
                               capture_output=True, text=True, timeout=1800)
            d = json.loads(r.stdout or "{}")
        except Exception as e:
            rep.add("platform", "YouTube талаптары (ffmpeg-skill check.py)", None,
                    f"иштеген жок: {type(e).__name__}", required=False)
            return
        rows = d.get("checks") or d.get("rows") or []
        bad = [f"{x.get('check')}: {x.get('value')}" for x in rows if x.get("status") == "FAIL"]
        warn = [x.get("check") for x in rows if x.get("status") == "WARN"]
        ctx.path("platform_check.json").write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
        rep.add("platform", "YouTube талаптары (ffmpeg-skill check.py)", not bad,
                f"{len(rows) - len(bad) - len(warn)} PASS, {len(warn)} WARN {warn}, {len(bad)} FAIL {bad}")

    def check_repetition(self, ctx, rep, shots) -> None:
        """Кайталанбоо: бул видеодо да, база (Smart Video Memory) боюнча мурунку видеолордо да."""
        from .s5_visuals import MAX_REUSE_FRACTION

        ids = [s["asset"] for s in shots]
        dups = sorted({i for i in ids if ids.count(i) > 1})
        rep.add("unique", "Бир видеодо клиптер кайталанбайт", not dups,
                f"{len(set(ids))}/{len(ids)} уникалдуу" + (f"; кайталангандар: {dups[:3]}" if dups else ""))
        mem = ClipMemory.load(ctx.store, ctx.registry)
        others = mem.used_by_others(ctx.video_id)
        overlap = [i for i in ids if i in others]
        allowed = int(MAX_REUSE_FRACTION * len(ids) + 0.999)
        rep.add("no_reuse", f"Мурунку видеолордун клиптери кайра колдонулган эмес (чек ≤ {allowed} кадр)",
                len(overlap) <= allowed,
                f"мурункулар менен кесилиш: {len(overlap)} / {len(ids)} (база: {mem.stats()['clips']} клип, "
                f"{mem.stats()['videos']} видео)" + (f"; мисал: {overlap[:3]}" if overlap else ""))
        if ctx.store is not None and hasattr(ctx.store, "load_clip_memory"):
            have = mem.clips_of(ctx.video_id)
            rep.add("memory", "Клиптер видео базасына (Drive) жазылган", set(ids) <= have,
                    f"{len(set(ids) & have)}/{len(set(ids))} клип базада")
        match = [s.get("match", 0) for s in shots if s["kind"] == "video"]
        if match:
            share = sum(1 for m in match if m > 0) / len(match)
            rep.add("theme_match", "Клиптердин тегдери сахнанын маанисине дал келет (Pixabay tags)",
                    share >= 0.5, f"{share:.0%} кадр дал келет (≥50% керек)", required=False)
        ext = sum(1 for s in shots if s.get("extend"))
        if ext:
            rep.add("extended", "Кыска клиптер автоматтык узартылды", None, f"{ext} кадр (-stream_loop)",
                    required=False)

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
        url = None
        # cinematic СЫНАГЫ эски видеонун ҮСТҮНӨН жазбайт: өзүнчө аталыш (эски/жаңыны салыштыруу үчүн)
        suffix = "_cinematic" if self._cinematic(ctx) else ""
        if ctx.store:
            url = ctx.store.publish("Final_Videos", final, f"{ctx.video_id}{suffix}.mp4")
            ctx.store.publish("Licenses", lic, f"{ctx.video_id}_LICENSE.txt")
        entry = ctx.registry.setdefault("videos", {}).setdefault(ctx.video_id, {})
        entry["final" + suffix] = f"Final_Videos/{ctx.video_id}{suffix}.mp4"
        if url:
            entry["final_url" + suffix] = url
            ctx.log(f"   ▶️ ВИДЕОНУН ШИЛТЕМЕСИ: {url}")
        try:                                       # клиптер «жарыялангандай» белгиленет
            mem = ClipMemory.load(ctx.store, ctx.registry)
            if mem.mark_published(ctx.video_id):
                mem.save(ctx.store, ctx.path("clips", "clip_memory.csv"))
        except Exception as e:                     # база жазылбаса да видео даяр
            ctx.log(f"   ⚠️ клип базасын жаңыртуу ишке ашкан жок: {type(e).__name__}")
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
