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
        audible = (music.get("levels") or {}).get("voice_minus_ducked_music_lu")
        if audible is not None:   # СЫНАК: музыка чындап угулабы (колдонуучу 2026-11-20: «музыка жок го»)
            from .s7_music import AUDIBLE_RANGE

            lo, hi = AUDIBLE_RANGE
            rep.add("music_audible", "Фондук музыка угулат (бирок дикторду баспайт)", lo <= audible <= hi,
                    f"басаңдатылгандан кийин диктордон {audible} LU акырын (керек {lo:.0f}–{hi:.0f})")
        self.check_sfx(ctx, rep, music)

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
            self.check_motion(ctx, rep)
            self.check_originality(ctx, rep, music, meta)
            self.check_visual(ctx, rep, final)
            self.check_hook(ctx, rep)
            self.check_shot_meaning(ctx, rep)
            self.check_policy(ctx, rep, clip_lic, music, meta)
            self.check_ai_images(ctx, rep, shots)
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

    def check_motion(self, ctx, rep) -> None:
        """Ар кадрда камера кыймылы барбы (рендерленген кадрдан өлчөнгөн, s8 → motion_report.json)."""
        f = ctx.path("animation", "motion_report.json")
        if not f.exists():
            rep.add("motion", "Ар кадрда камера кыймылы бар", False, "motion_report.json жок")
            return
        r = json.loads(f.read_text(encoding="utf-8"))
        n, static = r["shots"], r["static"]
        share = max(r["by_type"].values()) / n if n else 1
        rate = r["matched"] / r["judged"] if r["judged"] else 0
        ok = not static and rate >= 0.85 and len(r["by_type"]) >= 6 and share <= 0.35
        rep.add("motion", "Ар кадрда камера кыймылы бар (zoom/pan/ken burns…), ар түрдүү, план менен дал келет", ok,
                f"{n} кадр, статикалык {len(static)}, план↔өлчөө {r['matched']}/{r['judged']} ({rate:.0%}), "
                f"түр {len(r['by_type'])} (эң көп {share:.0%})")

    @staticmethod
    def script_profile(ctx) -> dict:
        """Сценарийдин структурасы жана hook (биринчи 1–2 сүйлөм)."""
        try:
            text = ctx.path("script", "script.txt").read_text(encoding="utf-8")
        except Exception:
            return {}
        paras = [p for p in re.split(r"\n\s*\n", text) if p.strip()]
        sents = re.split(r"(?<=[.!?…])\s+", text.strip())
        hook = " ".join(sents[:2])[:240]
        return {"hook": hook, "hook_type": "question" if "?" in " ".join(sents[:2]) else "statement",
                "paragraphs": len(paras), "questions": text.count("?"),
                "examples": len(re.findall(r"(?i)представьте|возьм[её]м|например|по имени", text))}

    @staticmethod
    def _jacc(a: str, b: str) -> float:
        wa, wb = set(re.findall(r"\w{4,}", a.lower())), set(re.findall(r"\w{4,}", b.lower()))
        return len(wa & wb) / len(wa | wb) if wa and wb else 0.0

    def check_originality(self, ctx, rep, music: dict, meta: dict) -> None:
        """ОРИГИНАЛДУУЛУК — №1 приоритет (YouTube «Inauthentic content», 2025-07-15; колдонуучу 2026-11-20).

        Жаңы видео ар бир мурунку ДАЯР видео менен салыштырылат:
          монтаж концепциясы — 7 топ (түс, ыргак, кыймыл, өтүүлөр, субтитр, музыка атмосферасы, визуалдык мотивдер);
          музыка трек; сценарийдин баяндоо стили/структурасы; hook (башталышы); сценарий окшоштугу (s1).
        Окшош болсо — видео ДАЯР ЭМЕС (милдеттүү) жана концепция жокко чыгарылат: кайра иштетүүдө ЖАҢЫ концепция түзүлөт.
        """
        from .. import edit_concept as ecm

        entry = ctx.registry.setdefault("videos", {}).setdefault(ctx.video_id, {})
        brief = entry.get("edit_brief")
        prof = self.script_profile(ctx)
        mine = {"music": (music.get("license") or {}).get("file"), "music_mood": music.get("mood"),
                "narrative": meta.get("style"), **prof}
        entry["fingerprint"] = {**mine, "brief": (brief or {}).get("name")}
        rows, problems = [], []
        for vid, v in ecm.finished_others(ctx.registry, ctx.video_id).items():
            c = ecm.compare(brief, ecm.brief_of(v)) if brief else None
            fp = v.get("fingerprint") or {}
            same_extra = [k for k in ("music", "narrative") if mine.get(k) and fp.get(k) == mine.get(k)]
            hook_sim = self._jacc(mine.get("hook", ""), fp.get("hook", "")) if fp.get("hook") else 0.0
            struct_same = bool(fp.get("paragraphs")) and fp.get("hook_type") == mine.get("hook_type") and \
                abs(fp.get("paragraphs", 0) - mine.get("paragraphs", 0)) <= 1 and fp.get("narrative") == mine.get("narrative")
            row = {"video": vid, "concept": c, "same_extra": same_extra, "hook_similarity": round(hook_sim, 2),
                   "structure_same": struct_same}
            rows.append(row)
            if c and not c["ok"]:
                problems.append(f"{vid}: монтаж концепциясы окшош (бирдей: {', '.join(c['same']) or '-'}; орточо {c['mean']})")
            if hook_sim >= 0.35:
                problems.append(f"{vid}: hook окшош ({hook_sim:.2f})")
            if struct_same and len(same_extra) == 2:
                problems.append(f"{vid}: баяндоо структурасы + музыка + стиль бирдей")
        sim = (meta.get("similarity") or {})
        if sim.get("too_similar"):
            problems.append(f"сценарий мурункуга окшош ({sim.get('max_jaccard')})")
        if self._cinematic(ctx) and not brief:
            problems.append("видеонун өз монтаж концепциясы жок")
        ok = not problems
        if not ok and brief and any("концепциясы окшош" in p for p in problems):
            ecm.reject(ctx, "; ".join(problems))      # кайра иштетүүдө жаңы концепция түзүлөт
        note = (f"концепция «{(brief or {}).get('name', '-')}» ({(brief or {}).get('source', '-')}); hook: "
                f"{mine.get('hook_type')}; " + ("; ".join(problems) if problems else "; ".join(
                    f"{r['video']}: {len(r['concept']['differ']) if r['concept'] else '?'}/7 топ айырма, "
                    f"hook {r['hook_similarity']}" for r in rows[:5]) or "салыштырууга мурунку даяр видео жок"))
        if not ok:
            note += " → КАЙРА ИШТЕТИҢИЗ (rerun_from: s4_subtitles): жаңы концепция автоматтык түзүлөт"
        rep.add("original_video", "Видео мурунку даяр видеолордон айырмаланат (өз концепциясы, шаблон эмес)", ok, note)
        ctx.path("originality.json").write_text(json.dumps(
            {"brief": brief, "fingerprint": mine, "compared": rows, "problems": problems,
             "script_similarity": sim}, ensure_ascii=False, indent=1), encoding="utf-8")

    def check_visual(self, ctx, rep, final) -> None:
        """ДАЯР видеону мурунку даяр видеолор менен визуалдык салыштыруу (кадрлар, палитра, композиция, ыргак,
        монтаж түзүлүшү, өтүүлөр). Өтө окшош болсо — МИЛДЕТТҮҮ fail жана концепция жокко чыгарылат (кайра монтаж)."""
        from .. import edit_concept as ecm, visual_compare as vc

        try:
            plan = json.loads(ctx.path("animation", "plan.json").read_text(encoding="utf-8"))
        except Exception:
            plan = None
        try:
            fp = vc.fingerprint(final, plan)
        except Exception as e:
            rep.add("visual_original", "Даяр видео мурункулардан визуалдык айырмаланат", None,
                    f"өлчөнгөн жок: {type(e).__name__}", required=False)
            return
        entry = ctx.registry.setdefault("videos", {}).setdefault(ctx.video_id, {})
        entry["visual_fp"] = fp
        res = vc.against_finished(fp, ctx.registry, ctx.video_id)
        bad = {v: r for v, r in res.items() if r["too_similar"]}
        note = "; ".join(f"{v}: окшош кадр {r['dup_frames']:.0%}, окшош өлчөм {r['similar'] or '-'}"
                         for v, r in res.items()) or "салыштырууга визуалдык изи бар мурунку видео жок"
        if bad:
            ecm.reject(ctx, "визуалдык окшош: " + ", ".join(bad))
            note += " → жаңы концепция менен КАЙРА МОНТАЖ"
        rep.add("visual_original", "Даяр видео мурункулардан визуалдык айырмаланат (кадр, түс, композиция, ыргак)",
                not bad, note)
        ctx.path("visual_compare.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")

    def production_report(self, ctx, rep, passed: bool) -> None:
        """Чыныгы иштөөнүн ДАЛИЛДҮҮ отчету (колдонуучунун 6 суроосу): Logs/<ID>_production_report.md + лог."""
        import os

        entry = ctx.registry.get("videos", {}).get(ctx.video_id, {})
        st = ctx.state.data.get("stages", {})
        by = {i["key"]: i for i in rep.items}
        b = entry.get("edit_brief") or {}
        L = [f"# Өндүрүш отчету — {ctx.video_id}: {ctx.state.topic}", "",
             f"**Жыйынтык:** {'✅ QA өттү — видео даяр' if passed else '❌ QA өткөн жок — видео даяр эмес'}", "",
             "## 1. Ар бир этап чындап иштедиби?"]
        for name, v in st.items():
            o = v.get("outputs") or {}
            L.append(f"- {name}: **{v.get('status')}** (аракет {v.get('attempts', '-')}, бүттү {v.get('finished_at', '-')})" +
                     (f" — {v.get('error')[:120]}" if v.get("error") else "") +
                     (f" — {', '.join(f'{k}={o[k]}' for k in list(o)[:3])}" if o else ""))
        L += ["", "## 2. Жаңы монтаж концепциясы колдонулдубу?",
              f"- Концепция: **«{b.get('name', '-')}»** (булагы: {b.get('source', '-')}, аракет: {b.get('attempts', '-')})",
              f"- Визуалдык дүйнө: {b.get('world', '-')}", f"- Мотивдер: {', '.join(b.get('motifs', [])) or '-'}",
              f"- Түс: {b.get('grade')}", f"- Ыргак: кадр {b.get('base_shot')} сек, актылар {b.get('act_pace')}",
              f"- Кыймыл (артыкчылык): {[k for k, w in sorted((b.get('motion') or {}).items(), key=lambda x: -x[1])][:4]}",
              f"- Өтүүлөр: {[k for k, w in sorted((b.get('transitions') or {}).items(), key=lambda x: -x[1]) if w > 0][:4]}"
              f", {b.get('transition_sec')} сек",
              f"- Субтитр: {b.get('subtitles')}", f"- Музыка: {b.get('music_mood')} ({b.get('music_level')} LU)",
              "", "## 3. Мурунку видеолордон айырмасы эмнеде?"]
        for c in self._json(ctx, "originality.json").get("compared", []):
            cc = c.get("concept") or {}
            L.append(f"- {c['video']}: концепция айырмаланган топтор {cc.get('differ')}, окшош {cc.get('same')}, "
                     f"орточо {cc.get('mean')}; hook окшоштугу {c.get('hook_similarity')}")
        for vid, r in self._json(ctx, "visual_compare.json").items():
            L.append(f"- {vid} (даяр видеону визуалдык салыштыруу): окшош кадр {r['dup_frames']:.0%}, аралыктар "
                     f"{r['distances']}, окшош өлчөмдөр {r['similar'] or '-'}")
        L += ["", "## 4. QA окшоштукту таптыбы?"]
        for k in ("original_video", "visual_original", "original", "hook", "shot_meaning"):
            if k in by:
                L.append(f"- {by[k]['title']}: {'✅' if by[k]['ok'] else ('❌' if by[k]['ok'] is False else '—')} "
                         f"{by[k]['note'][:300]}")
        L += ["", "## 5. Кемчилик табылса, кайра монтаж жасадыбы?"]
        if entry.get("rework_log"):
            for r in entry["rework_log"]:
                L.append(f"- Кайра монтаж №{r['n']}: четке кагылган концепция «{(r.get('reason') or {}).get('name')}» — "
                         f"{(r.get('reason') or {}).get('reason', '')[:200]}")
        else:
            L.append("- Кайра монтаж керек болгон жок (окшоштук табылган жок)")
        for rb in entry.get("rejected_briefs", []):
            L.append(f"- Четке кагылган концепция: «{rb.get('name')}» — {rb.get('reason', '')[:160]}")
        th = entry.get("thumbnail") or {}
        L += ["", "## 6. Обложка жана Hook даярдалдыбы?",
              f"- Hook: {by.get('hook', {}).get('note', '-')}",
              f"- Обложка: {len(th.get('files', []))} вариант, жайгашуу {th.get('layout', '-')}, акцент {th.get('accent', '-')}"]
        for t, u in zip(th.get("texts", []), th.get("urls", [])):
            L.append(f"  - «{t}»: {u}")
        if th.get("rejected"):
            L.append(f"  - четке кагылды: {th['rejected']}")
        if th.get("error"):
            L.append(f"  - ❌ ката: {th['error']}")
        text = "\n".join(L) + "\n"
        out = ctx.path("production_report.md")
        out.write_text(text, encoding="utf-8")
        if ctx.store:
            try:
                url = ctx.store.publish("Logs", out, f"{ctx.video_id}_production_report.md")
                ctx.log(f"   📋 Өндүрүш отчету: {url}")
            except Exception:
                pass
        ctx.log(text)
        path = os.environ.get("GITHUB_STEP_SUMMARY")
        if path:
            with open(path, "a", encoding="utf-8") as f:
                f.write(text)

    @staticmethod
    def _json(ctx, name: str) -> dict:
        try:
            return json.loads(ctx.path(name).read_text(encoding="utf-8"))
        except Exception:
            return {}

    def check_hook(self, ctx, rep) -> None:
        """Hook: алгачкы 2 сүйлөм кыска жана шаблонсуз, экранда hook карточкасы ≤4 сек, түрү мурунку видеодон башка."""
        from .. import edit_concept as ecm
        from .s1_script import HOOK_BANNED

        try:
            meta = json.loads(ctx.path("script", "meta.json").read_text(encoding="utf-8"))
        except Exception:
            meta = {}
        hook, htype = meta.get("hook", ""), meta.get("hook_type")
        try:
            cards = json.loads(ctx.path("animation", "cards.json").read_text(encoding="utf-8"))
        except Exception:
            cards = []
        card = next((c for c in cards if c.get("hook")), None)
        prev = [v.get("hook_type") for v in ecm.finished_others(ctx.registry, ctx.video_id).values() if v.get("hook_type")]
        last = prev[-1] if prev else None
        problems = []
        if not hook:
            problems.append("hook жок")
        elif len(hook.split()) > 45:
            problems.append(f"hook узун ({len(hook.split())} сөз)")
        if any(hook.lower().startswith(b) for b in HOOK_BANNED):
            problems.append("шаблон башталыш")
        if not card or card["start"] > 4.0:
            problems.append("алгачкы 4 секундда hook карточкасы жок")
        if htype and last and htype == last:
            problems.append(f"hook түрү мурунку видеодогудай ({htype})")
        rep.add("hook", "Hook: алгачкы секунддар көңүл бурат (өз түрү, кыска, экранда)", not problems,
                (f"түрү {htype}; «{hook[:90]}»; карточка «{(card or {}).get('text', '-')}»" +
                 (f" — {'; '.join(problems)}" if problems else "")))

    def check_shot_meaning(self, ctx, rep) -> None:
        """Кадрлар темага/сөзгө дал келеби: s5 AI баалоосу БАРДЫК кадр боюнча (s9'дагы 10 кадрдык сынак эмес)."""
        try:
            shots = json.loads(ctx.path("clips", "shots.json").read_text(encoding="utf-8"))["shots"]
        except Exception:
            return
        sc = [s["ai_score"] for s in shots if isinstance(s.get("ai_score"), int)]
        if len(sc) < max(5, len(shots) // 2):
            rep.add("shot_meaning", "Кадрлар баяндалган ойго дал келет (бардык кадр, AI)", None,
                    f"бааланган кадр аз ({len(sc)}/{len(shots)}) — Gemini жеткиликсиз болгон", required=False)
            return
        avg = sum(sc) / len(sc)
        bad = sum(1 for x in sc if x <= 1)
        rep.add("shot_meaning", "Кадрлар баяндалган ойго дал келет (бардык кадр, AI)",
                avg >= 3.0 and bad <= max(2, len(sc) // 20),
                f"орточо {avg:.2f}/5 ({len(sc)} кадр), 1 упай алган {bad} (керек: орточо ≥3.0, 1-упай ≤5%)")

    ORIGINALITY_CHECKLIST = [
        ("Бул видео мурункулардан мазмуну боюнча айырмаланабы?", ["original"]),
        ("Өз алдынча монтаж концепциясы барбы?", ["original_video"]),
        ("Кадрлар темага туура келеби?", ["shot_meaning", "relevance", "theme_match"]),
        ("Бир эле монтаж шаблону кайталанган жокпу?", ["original_video", "visual_original", "motion"]),
        ("Оригиналдуу баяндоо жана пайдалуу маалымат барбы?", ["original", "words"]),
        ("Видеонун башынан аягына чейин кызыгуу сакталабы (hook, ыргак, бирдей сапат)?", ["hook", "pacing", "uniform", "freeze", "silence"]),
        ("Музыка жана материалдардын лицензиясы текшерилгенби?", ["licenses", "sfx_license", "music_audible"]),
        ("Видео техникалык жактан толук жана сапаттуубу?", ["opens", "sync", "format", "loudness", "black", "duration"]),
    ]

    def originality_checklist(self, rep) -> list[dict]:
        """Колдонуучунун 8 пункттук милдеттүү тизмеси (report.json → «originality_checklist»)."""
        by = {i["key"]: i for i in rep.items}
        out = []
        for q, keys in self.ORIGINALITY_CHECKLIST:
            got = [by[k] for k in keys if k in by]
            ok = None if not got else all(g["ok"] is not False for g in got if g["required"]) and \
                any(g["ok"] for g in got)
            out.append({"question": q, "ok": ok, "checks": [g["key"] for g in got]})
        return out

    @staticmethod
    def ai_images_info(ctx) -> dict:
        try:
            return json.loads(ctx.path("clips", "ai_images.json").read_text(encoding="utf-8"))
        except Exception:
            return {}

    @staticmethod
    def sfx_info(ctx) -> dict:
        p = ctx.path("music", "sfx.json")
        try:
            return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
        except ValueError:
            return {}

    def check_sfx(self, ctx, rep, music: dict) -> None:
        """Үн эффекттери (СЫНАК): лицензиясы текшерилген гана, паузада, диктордон ≥10 LU акырын."""
        from .. import sfx

        info = self.sfx_info(ctx)
        ev = info.get("events") or []
        if not ev:
            return
        lic = {l["file"]: l for l in info.get("licenses", [])}
        bad = [e["rel"] for e in ev
               if e["rel"] not in lic or not lic[e["rel"]].get("commercial_use")
               or not sfx.license_name(lic[e["rel"]].get("license"))]
        rep.add("sfx_license", "Үн эффекттеринин лицензиясы текшерилген (коммерциялык уруксат)", not bad,
                f"{len(lic)} аудио, {len(ev)} колдонуу" + (f"; текшерилбеген: {bad[:3]}" if bad else ""))
        hits = [e for e in ev if e["kind"] == "hit"]
        off = [e for e in hits if not (e["pause"][0] - 0.01 <= e["t"] <= e["pause"][1])]
        rel = (music.get("levels") or {}).get("voice_minus_sfx_lu")
        rep.add("sfx_level", "Үн эффекттери дикторду баспайт (паузада, ≥10 LU акырын)",
                not off and rel is not None and rel >= 10,
                f"{len(hits)} эффект паузада ({len(off)} паузадан тышкары), {len(ev) - len(hits)} фон; "
                f"диктор эффекттерден {rel} LU катуу")

    def check_ai_images(self, ctx, rep, shots) -> None:
        """AI-сүрөттөр (кошумча): бюджет чегинде, сток негизги бойдон, катар коюлган эмес, лицензиясы бар."""
        info = self.ai_images_info(ctx)
        if not info:
            return
        ai = [s for s in shots if s.get("source") == "gemini"]
        idx = [s["i"] for s in ai]
        adjacent = sum(1 for a, b in zip(idx, idx[1:]) if b - a == 1)
        share = len(ai) / max(1, len(shots))
        ok = info.get("cost_usd", 0) <= info.get("budget_usd", 0) + 1e-6 and adjacent == 0 and share <= 0.2
        rep.add("ai_images", "AI-сүрөттөр (Gemini): бюджет, үлүш ≤20%, катар эмес", ok,
                f"коюлду {len(ai)}/{len(shots)} ({share:.0%}), жаратылды {info.get('generated', 0)}, кэштен "
                f"{info.get('cached', 0)}, чыгым ${info.get('cost_usd', 0):.3f} / чек ${info.get('budget_usd', 0):.2f}"
                + (f"; {info['stopped']}" if info.get("stopped") else ""), required=False)

    def check_policy(self, ctx, rep, clip_lic: list, music: dict, meta: dict) -> None:
        """YouTube Partner Program боюнча белгилүү тобокелдиктер (кошумча, policy_report.json)."""
        risks, good = [], []
        lic_ok = all(l.get("license") for l in clip_lic)
        (good if lic_ok else risks).append(f"видео/сүрөт лицензиялары {len(clip_lic)}/{len(clip_lic)} катталган "
                                          "(Pixabay Content License — монетизацияга уруксат, бирок клипти өзгөртүүсүз "
                                          "кайра сатууга/таратууга болбойт)")
        src = (music.get("license") or {}).get("source")
        (good if src and src != "Unknown" else risks).append(f"музыка: {src}")
        good.append("сценарий — оригиналдуу (Gemini, мурункулар менен окшоштук текшерилет), фактылар текшерилет")
        good.append("клиптер ар видеодо жаңы (Smart Video Memory), кадрлар сценарийге AI менен дал келтирилет")
        risks.append("Reused content тобокелдиги: сток-видеолор колдонулат — баалуулук оригиналдуу баяндоо, монтаж жана "
                     "түшүндүрмөдөн келет; бир эле форматты массалык кайталабоо керек")
        n_ai = sum(1 for l in clip_lic if l.get("source") == "gemini")
        if n_ai:
            risks.append(f"AI-сүрөттөр: {n_ai} кадр Gemini менен жаратылган (SynthID белгиси бар). Реалдуу "
                         "көрүнүшү мүмкүн → YouTube Studio'до «Altered or synthetic content» = «Yes» коюу сунушталат; "
                         "сүрөттөмөдө AI колдонулганы жазылды")
        risks.append("Синтетикалык үн (Gemini TTS): чыныгы адамдын үнүн туурабайт; YouTube «altered or synthetic "
                     "content» белгиси адатта талап кылынбайт — акыркы чечим каналдын ээсинде")
        out = {"ok": good, "risks": risks}
        ctx.path("policy_report.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
        rep.add("policy", "YouTube саясаты: лицензия, оригиналдуулук, AI белгилөө (тобокелдиктер)", lic_ok and bool(src),
                f"{len(good)} талап аткарылды, {len(risks)} эскертүү (policy_report.json)", required=False)

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
        checklist = self.originality_checklist(rep)
        cl_text = "ОРИГИНАЛДУУЛУК ЖАНА САПАТ — МИЛДЕТТҮҮ ТЕКШЕРҮҮ:\n" + "\n".join(
            f"  [{'x' if c['ok'] else (' ' if c['ok'] is False else '?')}] {c['question']}" for c in checklist) + "\n\n"
        header = (f"QA ОТЧЕТУ — {ctx.video_id}: {ctx.state.topic}\n"
                  f"Аталыш (сунуш): {meta.get('title')}\nКүнү: {date.today().isoformat()}\n"
                  f"ЖЫЙЫНТЫК: {'✅ ӨТТҮ — видео даяр' if passed else '❌ ӨТКӨН ЖОК — видео даяр эмес'}\n\n")
        ctx.path("report.txt").write_text(header + cl_text + rep.text() + "\n", encoding="utf-8")
        ctx.path("report.json").write_text(json.dumps({"passed": passed, "originality_checklist": checklist,
                                                       "checks": rep.items},
                                                      ensure_ascii=False, indent=1), encoding="utf-8")
        ctx.path("ai_usage.json").write_text(json.dumps(ai, ensure_ascii=False, indent=1), encoding="utf-8")
        lic = self.license_txt(ctx, meta, music, clip_lic)
        self.description(ctx, meta, music)
        ctx.log(cl_text + rep.text())
        if not passed and self._cinematic(ctx):
            self.production_report(ctx, rep, False)
        if not passed:
            raise StageError("QA өткөн жок: " + "; ".join(f"{i['title']} ({i['note']})"
                                                         for i in rep.failed))
        url = None
        # cinematic СЫНАГЫ эски видеонун ҮСТҮНӨН жазбайт: өзүнчө аталыш (эски/жаңыны салыштыруу үчүн)
        from .. import cinematic as _cin

        suffix = "_cinematic" if self._cinematic(ctx) and _cin.is_test_root(ctx.store) else ""   # production: <ID>.mp4
        if ctx.store:
            url = ctx.store.publish("Final_Videos", final, f"{ctx.video_id}{suffix}.mp4")
            ctx.store.publish("Licenses", lic, f"{ctx.video_id}_LICENSE.txt")
        entry = ctx.registry.setdefault("videos", {}).setdefault(ctx.video_id, {})
        entry["final" + suffix] = f"Final_Videos/{ctx.video_id}{suffix}.mp4"
        if url:
            entry["final_url" + suffix] = url
            ctx.log(f"   ▶️ ВИДЕОНУН ШИЛТЕМЕСИ: {url}")
        if self._cinematic(ctx):                   # ар видеого өз обложкасы (мурункулар менен салыштырылат)
            try:
                from ..thumbnail import auto_thumbnails
                auto_thumbnails(ctx, meta.get("title", ""))
            except Exception as e:                 # обложка жасалбаса да видео даяр (отчетто көрсөтүлөт)
                ctx.log(f"   ⚠️ Обложка жасалган жок: {type(e).__name__}: {str(e)[:120]}")
                entry["thumbnail"] = {"error": f"{type(e).__name__}: {str(e)[:200]}"}
            self.production_report(ctx, rep, True)
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
        info = self.ai_images_info(ctx)
        if info.get("used"):
            return {
                "tools": ["Gemini (сценарий, факт текшерүү, сахналар)", "Gemini TTS (синтетикалык үн, Algenib)",
                          "Whisper (субтитр убактысы)", "Gemini (музыканын маанайы, кадр баалоо)",
                          "Gemini API (AI-сүрөттөр)"],
                "models_this_run": used,
                "visuals": (f"сток-видео (Pixabay/Pexels) + {info['used']} AI-сүрөт (Gemini, SynthID); "
                            f"чыгым ${info.get('cost_usd', 0):.3f}"),
                "recommendation": ("YouTube Studio → «Altered or synthetic content»: сунуш — «Yes». Себеби: видеодо "
                                   f"{info['used']} AI менен жаратылган реалдуу көрүнүшү мүмкүн сүрөт бар. Белгилөө "
                                   "монетизацияга таасир этпейт; белгилебөө эрежени бузуу болушу мүмкүн. "
                                   "Акыркы чечимди сиз кабыл аласыз."),
            }
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
        fx = self.sfx_info(ctx).get("licenses") or []
        if fx and self.sfx_info(ctx).get("events"):
            lines += ["", "== ҮН ЭФФЕКТТЕРИ =="]
            for l in fx:
                lines.append(f"{l['file']} | «{l['title']}» | булагы: {l['source']} {l['source_url']} | "
                             f"автор: {l.get('author') or '—'} | {l['license']} {l.get('license_url', '')} | "
                             f"коммерциялык: ооба | текшерген: {l['verified_by']} {l['verified_at']} | "
                             f"sha256 {l['sha256'][:12]}")
        lines += ["", "== ВИДЕОКЛИПТЕР / СҮРӨТТӨР ==",
                  "Pixabay Content License: https://pixabay.com/service/license-summary/", ""]
        for l in clip_lic:
            lines.append(f"[{l['shot']:03d}] {l['type']} {l['id']} | автор: {l['author']} | "
                         f"{l['page_url']} | {l['license']}")
        lines += ["", "== AI КУРАЛДАРЫ ==", "Gemini (сценарий, факт текшерүү, сахналар), "
                  "Gemini TTS (диктор үнү), Whisper (субтитр убактысы)."]
        ai = [l for l in clip_lic if l.get("source") == "gemini"]
        if ai:
            lines += ["", "== AI-СҮРӨТТӨР ==", f"{len(ai)} кадр — Google Gemini API менен жаратылган "
                      "(Generative AI Additional Terms, SynthID белгиси): https://ai.google.dev/gemini-api/terms"]
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
        sx = self.sfx_info(ctx)
        for l in (sx.get("licenses") or []) if sx.get("events") else []:
            if l.get("attribution_required"):
                lines.append(f"Звук: «{l['title']}» — {l.get('author') or l['source']} ({l['license']})")
        if self.ai_images_info(ctx).get("used"):
            lines.append("Часть изображений создана с помощью ИИ (Google Gemini).")
        ctx.path("youtube_description.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
