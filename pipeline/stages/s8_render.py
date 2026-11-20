"""8-этап: Монтаж (FFmpeg) — 1920×1080, 30 FPS, H.264 + AAC.

  1. Ар кадр өзүнчө рендерленет: масштаб (16:9 толтуруу), кыймыл (zoom/pan/push),
     сүрөттөр Ken Burns менен. Параллель (4 CPU).
  2. Бир сахнанын кадрлары — кесүү менен (кайра кодировкасыз бириктирүү).
  3. Сахналар — жумшак өтүү (xfade) менен; ар өтүү өзүнчө кичине ffmpeg (1–2 кирүү), кадр-так сегменттер → concat.
     Өтүүнүн узактыгы алдын ала кошулат → видео менен үндүн убактысы так дал келет.
  4. Акыркы өтүү: түс градациясы + виньетка + субтитр + текст-карточкалар + үн.
"""

from __future__ import annotations

import json
import os
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from .. import media
from .base import Context, Stage, StageError
from .s5_visuals import ensure_media
from .s7_music import ensure_mix

W, H, FPS = 1920, 1080, 30
# Бардык кадрлар БИРДЕЙ түс белгилери менен чыгат. Pixabay клиптеринде bt601/bt709/белгисиз, tv/pc ар башка;
# бир сахнада аралашса FFmpeg 8.0.1 filtergraph'ты ортосунан кайра ачып кадрларды жоготот (Video_001:
# сахна 8.37 сек ордуна 4.93 сек; GitHub runner'де probe_concat аныктаган, FFmpeg 6.1'де байкалбайт).
COLOR_VF = ("scale=out_color_matrix=bt709:out_range=tv,format=yuv420p,"
            "setparams=colorspace=bt709:color_primaries=bt709:color_trc=bt709:range=tv")
COLOR_ARGS = ["-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709",
              "-color_range", "tv"]
ENC = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p",
       "-r", str(FPS), *COLOR_ARGS, "-an"]


def motion_filter(motion: str, dur: float, intensity: float) -> str:
    """Кадрдын кыймылы. Кирүү: ар кандай өлчөм → чыгуу: 1920×1080, 30 fps."""
    if motion.startswith("v2:"):            # cinematic СЫНАК: жумшак, мааниге жараша кыймыл (pipeline/motion.py)
        from .. import motion as motion_v2

        name, seed = motion_v2.parse(motion)
        return motion_v2.build(name, dur, intensity, seed)
    n = max(1, int(round(dur * FPS)))
    amp = 0.07 * intensity
    cover = (f"scale={int(W * 1.25)}:{int(H * 1.25)}:force_original_aspect_ratio=increase,"
             f"crop={int(W * 1.25)}:{int(H * 1.25)},setsar=1,fps={FPS}")
    if motion in ("zoom_in", "push_in", "zoom_out"):
        a = amp if motion != "push_in" else amp * 0.55
        z = (f"1+{a:.4f}*on/{n}" if motion != "zoom_out" else f"1+{a:.4f}*(1-on/{n})")
        return (f"{cover},zoompan=z='{z}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
                f":d=1:s={W}x{H}:fps={FPS}")
    sw, sh = int(W * (1 + amp)), int(H * (1 + amp))
    base = (f"scale={sw}:{sh}:force_original_aspect_ratio=increase,crop={sw}:{sh},setsar=1,"
            f"fps={FPS}")
    if motion == "pan_right":
        return f"{base},crop={W}:{H}:x='(iw-{W})*t/{dur:.3f}':y='(ih-{H})/2'"
    if motion == "pan_left":
        return f"{base},crop={W}:{H}:x='(iw-{W})*(1-t/{dur:.3f})':y='(ih-{H})/2'"
    if motion == "pan_up":
        return f"{base},crop={W}:{H}:x='(iw-{W})/2':y='(ih-{H})*(1-t/{dur:.3f})'"
    return f"{base},crop={W}:{H}"


SHOT_TOL = 0.12      # кадрдын чыныгы узактыгы күтүлгөндөн ушунчадан көп кыска болбосун
SCENE_TOL = 0.35
BATCH_TOL = 0.8
SEG_TOL = 0.25        # concat-copy: кадр-так план ± бир нече кадр
FINAL_TOL = 1.0


def video_len(path: Path) -> float | None:
    return media.stream_durations(path)["video"]


def render_shot(clip: Path, out: Path, kind: str, offset: float, dur: float,
                motion: str, intensity: float, prefilter: str = "",
                card: tuple[Path, float] | None = None) -> Path:
    """Бир кадрды рендерлейт жана ЧЫНЫГЫ узактыгын текшерет.

    Мурунку ката: клиптин чыныгы узактыгынан ашкан `-ss` бош/кыска файл берген, ал унчукпай
    өтүп, монтаждын калган бөлүгүн бузган. Эми кадр кыска болсо: клиптин башынан (кайталап)
    кайра рендерленет; ошондо да кыска болсо — так ката менен токтойт.
    """
    # Кэш ПАРАМЕТРЛЕР дал келгенде гана колдонулат: кайра монтажда (жаңы концепция) эски кыймыл/узундук калбасын
    # (pipeline тести: кайра монтажда 2-сахна 12.17 сек болуп, эски кадр узундугу кайра колдонулган).
    import hashlib as _hl

    key = _hl.md5(repr((str(clip), kind, round(offset, 3), round(dur, 3), motion, round(intensity, 3), prefilter,
                        str(card[0]) if card else None, round(card[1], 3) if card else None)).encode()).hexdigest()
    keyf = out.with_suffix(".key")
    if out.exists() and out.stat().st_size > 1000 and keyf.exists() and keyf.read_text() == key:
        got = video_len(out)
        if got is not None and abs(got - dur) <= SHOT_TOL:
            return out
    out.unlink(missing_ok=True)
    keyf.unlink(missing_ok=True)
    # prefilter/card — cinematic СЫНАК режиминде гана берилет (кадыресе бош → мурунку жол)
    vf = (prefilter + "," if prefilter else "") + motion_filter(motion, dur, intensity) + "," + COLOR_VF
    if card is not None:
        graph = ["-filter_complex",
                 f"[0:v]{vf}[b];[1:v]setpts=PTS-STARTPTS+{card[1]:.3f}/TB[c];"
                 f"[b][c]overlay=eof_action=pass:format=auto,{COLOR_VF}[v]", "-map", "[v]"]
        extra_in = ["-i", str(card[0])]
    else:
        graph, extra_in = ["-vf", vf], []
    tmp = out.with_suffix(".tmp.mp4")
    if kind == "image":
        attempts = [["-loop", "1", "-framerate", str(FPS), "-t", f"{dur:.3f}", "-i", str(clip)]]
    else:
        attempts = [
            ["-ss", f"{offset:.3f}", "-t", f"{dur + 0.2:.3f}", "-i", str(clip)],
            # запас: клиптин башынан, кыска болсо цикл менен кайталоо
            ["-stream_loop", "-1", "-t", f"{dur + 0.2:.3f}", "-i", str(clip)],
        ]
    got = None
    for src in attempts:
        tmp.unlink(missing_ok=True)
        try:
            media.run(["ffmpeg", "-y", "-v", "error", "-threads", "2", *src, *extra_in, *graph,
                       "-t", f"{dur:.3f}", *ENC, str(tmp)], f"кадр {out.stem}", timeout=900)
            got = video_len(tmp)
        except StageError:
            got = None
        if got is not None and got >= dur - SHOT_TOL:
            tmp.rename(out)
            keyf.write_text(key)
            return out
    tmp.unlink(missing_ok=True)
    raise StageError(f"{out.stem}: кадр кыска чыкты ({got} сек, күтүлгөнү {dur:.2f} сек); "
                     f"клип: {clip.name}, offset {offset}")


def check_contiguous(shots: list[dict], total: float, tol: float = 0.02) -> None:
    """Кадрлар [0, total] аралыгын боштуксуз жана кайталанбай толук жабышы керек."""
    prev = 0.0
    for sh in shots:
        if abs(sh["start"] - prev) > tol:
            raise StageError(f"{sh['i']}-кадрда боштук/кайталануу: башталышы {sh['start']}, "
                             f"мурунку кадрдын аягы {prev}")
        if sh["dur"] <= 0:
            raise StageError(f"{sh['i']}-кадрдын узактыгы ≤ 0")
        prev = sh["end"]
    if abs(prev - total) > 0.05:
        raise StageError(f"Кадрлар аудионун бүт узактыгын жаппайт: акыркы кадр {prev:.2f} сек, "
                         f"аудио {total:.2f} сек")


def expect_len(path: Path, want: float, tol: float, label: str, debug: list[dict]) -> float:
    """Файлдын видео агымынын ЧЫНЫГЫ узактыгы күтүлгөнгө дал келбесе — так ката."""
    got = video_len(path)
    debug.append({"label": label, "file": path.name, "want": round(want, 3),
                  "got": None if got is None else round(got, 3)})
    if got is None or abs(got - want) > tol:
        raise StageError(f"{label}: видео агымы {got} сек, күтүлгөнү {want:.2f} сек "
                         f"(чектен ашты: ±{tol}). Монтаж ушул жерде бузулду.")
    return got


def _eff_d(t: dict) -> tuple[str, float]:
    """Өтүүнүн түрү жана ЭФФЕКТИВДҮҮ узактыгы (cut → 0.04 сек fade)."""
    d = max(0.0, float(t.get("dur", 0.5)))
    typ = t.get("type", "fade")
    return ("fade", 0.04) if typ == "cut" or d == 0 else (typ, d)


def fr(sec: float) -> int:
    """Секунд → кадр (30 fps), тегеректелет."""
    return int(round(sec * FPS))


def plan_segments(durs: list[float], transitions: list[dict]) -> dict:
    """Убакыт сызыгынын КАДР-ТАК планы (чыныгы файл узактыктарына көз каранды эмес → жылыш топтолбойт).

    durs[k] — k-сахнанын файлы (акыркы кадры өтүүгө узартылган), transitions[k] — k→k+1 өтүүсү.
    Тизме: body_0, trans_0, body_1, … body_n-1.  Жалпы = f(Σdurs − Σoverlaps).
    """
    n = len(durs)
    dout = [(_eff_d(transitions[k])[1] if k < n - 1 else 0.0) for k in range(n)]
    segs, t = [], 0.0
    for k in range(n):
        din = dout[k - 1] if k else 0.0
        a, b = fr(t + din), fr(t + durs[k] - dout[k])
        segs.append({"kind": "body", "scene": k, "src_start": fr(din), "frames": b - a})
        if k < n - 1:
            c = fr(t + durs[k])
            typ, d = _eff_d(transitions[k])
            segs.append({"kind": "trans", "scene": k, "src_start": fr(durs[k] - dout[k]),
                         "frames": c - b, "type": typ})
        t += durs[k] - dout[k]
    return {"segments": segs, "total_frames": fr(t)}


def _src(k: int, start: int, tail_pad: float = 2.0) -> str:
    """Кирүү агымы: start кадрдан баштап, кыска болсо акыркы кадр клондолот (чоң filtergraph ЖОК)."""
    return (f"trim=start_frame={start},setpts=PTS-STARTPTS,tpad=stop_mode=clone:"
            f"stop_duration={tail_pad:g},fps={FPS},format=yuv420p")


def _render_segment(seg: dict, files: list[Path], out: Path) -> None:
    n = seg["frames"]
    k = seg["scene"]
    if seg["kind"] == "body":
        media.run(["ffmpeg", "-y", "-v", "error", "-i", str(files[k]), "-vf", _src(k, seg["src_start"]),
                   "-frames:v", str(n), *ENC, str(out)], f"сегмент {out.stem}", timeout=900)
        return
    if n < 2:      # өтө кыска өтүү (cut) — кадр кесүү менен
        media.run(["ffmpeg", "-y", "-v", "error", "-i", str(files[k]), "-vf", _src(k, seg["src_start"]),
                   "-frames:v", str(n), *ENC, str(out)], f"сегмент {out.stem}", timeout=900)
        return
    fc = (f"[0:v]{_src(k, seg['src_start'])},trim=end_frame={n},setpts=PTS-STARTPTS[a];"
          f"[1:v]{_src(k + 1, 0)},trim=end_frame={n},setpts=PTS-STARTPTS[b];"
          f"[a][b]xfade=transition={seg['type']}:duration={n / FPS:.4f}:offset=0[v]")
    media.run(["ffmpeg", "-y", "-v", "error", "-i", str(files[k]), "-i", str(files[k + 1]),
               "-filter_complex", fc, "-map", "[v]", "-frames:v", str(n), *ENC, str(out)],
              f"өтүү {out.stem}", timeout=900)


def stitch(files: list[Path], durs: list[float], transitions: list[dict], rdir: Path,
           out: Path, debug: list, workers: int = 2) -> tuple[float, int]:
    """Сахналарды өтүүлөр менен бириктирет — ЖҮЗДӨГӨН КИЧИНЕ ffmpeg чакыруусу менен.

    Мурунку ыкма (8 кирүүлүү чоң xfade графы) GitHub FFmpeg 8.0.1'де видеону кыркып салган/илинип калган;
    бул ыкмада ар кадам 1–2 кирүүлүү, ар сегмент так кадр санына чейин, акыры concat `-c copy`.
    Кайтарат: (узактык сек, кадр саны).
    """
    plan = plan_segments(durs, transitions)
    segs = plan["segments"]
    sdir = rdir / "segments"
    sdir.mkdir(parents=True, exist_ok=True)
    jobs = []
    for i, s in enumerate(segs):
        s["file"] = sdir / f"seg_{i:03d}_{s['kind']}.mp4"
        jobs.append(s)

    def check(s):
        got = video_len(s["file"])
        if got is None or abs(got - s["frames"] / FPS) > 0.15:
            raise StageError(f"{s['file'].name}: {got} сек, күтүлгөнү {s['frames'] / FPS:.2f} сек")

    def work(s):
        try:
            _render_segment(s, files, s["file"])
            check(s)
        except StageError:
            if s["kind"] != "trans":
                raise
            # өтүү иштебесе — кесүү менен (узактык так калат)
            s["fallback"] = "cut"
            media.run(["ffmpeg", "-y", "-v", "error", "-i", str(files[s["scene"]]), "-vf",
                       _src(s["scene"], s["src_start"]), "-frames:v", str(s["frames"]), *ENC,
                       str(s["file"])], f"өтүү (кесүү) {s['file'].stem}", timeout=900)
            check(s)
        return s

    with ThreadPoolExecutor(max(1, workers)) as ex:
        list(ex.map(work, [s for s in jobs if s["frames"] > 0]))
    lst = sdir / "list.txt"
    lst.write_text("".join(f"file '{s['file'].name}'\n" for s in segs if s["frames"] > 0),
                   encoding="utf-8")
    media.run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy",
               str(out)], "сегменттерди бириктирүү", timeout=1800)
    debug.append({"label": "stitch", "segments": len(segs), "planned_frames": plan["total_frames"],
                  "cut_fallbacks": [s["file"].name for s in segs if s.get("fallback")]})
    return plan["total_frames"] / FPS, plan["total_frames"]


def pts_summary(path: Path) -> dict:
    """Диагностика: кадрлардын убакыт белгилери (кыскарган монтаждын себебин табуу үчүн)."""
    import subprocess

    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                        "frame=pts_time", "-of", "csv=p=0", str(path)], capture_output=True, text=True)
    pts = []
    for x in r.stdout.split():
        try:
            pts.append(float(x.rstrip(",")))
        except ValueError:
            pass
    st = media.probe(path)["streams"][0]
    if not pts:
        return {"file": path.name, "frames": 0}
    deltas = [b - a for a, b in zip(pts, pts[1:])] or [0.0]
    return {"file": path.name, "frames": len(pts), "first_pts": round(pts[0], 3),
            "last_pts": round(pts[-1], 3), "delta_min": round(min(deltas), 4),
            "delta_max": round(max(deltas), 3), "monotonic": min(deltas) >= 0,
            "time_base": st.get("time_base"), "fps": st.get("r_frame_rate"),
            "start_time": st.get("start_time")}


class RenderStage(Stage):
    name = "s8_render"
    title = "Монтаж (FFmpeg)"
    retries = 0

    def run(self, ctx: Context) -> dict[str, Any]:
        shots = ensure_media(ctx)
        mix = ensure_mix(ctx)
        plan = json.loads(ctx.path("animation", "plan.json").read_text(encoding="utf-8"))
        total = json.loads(ctx.path("clips", "shots.json").read_text(encoding="utf-8"))["total"]
        motions = {p["i"]: p for p in plan["shots"]}
        rdir = ctx.path("render")
        sdir = rdir / "shots"
        sdir.mkdir(parents=True, exist_ok=True)
        check_contiguous(shots, total)
        debug: list[dict] = []
        try:
            return self._render(ctx, shots, mix, plan, total, motions, rdir, sdir, debug)
        finally:   # ката чыкса да өлчөөлөр логго калсын (Drive → Projects/<ID>/logs/)
            ctx.path("logs", "render_debug.json").write_text(
                json.dumps(debug, ensure_ascii=False, indent=1), encoding="utf-8")

    def _render(self, ctx, shots, mix, plan, total, motions, rdir, sdir, debug) -> dict[str, Any]:
        # 1) сахналарга топтоо; ар сахнанын акыркы кадры өтүү узактыгына узартылат
        scenes: list[list[dict]] = []
        for sh in shots:
            if not scenes or scenes[-1][0]["scene"] != sh["scene"]:
                scenes.append([])
            scenes[-1].append(sh)
        jobs = []
        for grp in scenes:
            last = grp[-1]
            ext = (motions[last["i"]].get("transition_out") or {}).get("dur", 0.0)
            for sh in grp:
                d = sh["dur"] + (ext if sh is last else 0.0)
                m = motions[sh["i"]]
                jobs.append((ctx.path("clips", sh["file"]), sdir / f"shot_{sh['i']:03d}.mp4",
                             sh["kind"], sh.get("offset", 0.0), d, m["motion"], m["intensity"]))
        workers = max(1, min(3, (os.cpu_count() or 2) - 1))
        from .. import cinematic
        cine = bool(plan.get("cinematic")) and cinematic.enabled(ctx.store)   # СЫНАК гана
        cards_ass = ctx.path("animation", "overlays.ass")
        if cine:
            t0 = time.time()
            card_for_shot, cards_ass, hf_n, ass_n = self._cinematic_cards(ctx, shots, motions, plan, rdir)
            ctx.log(f"   🎞 CINEMATIC (сынак): HyperFrames карточкалары {hf_n}, ASS карточкалары {ass_n} "
                    f"({time.time() - t0:.0f} сек)")
            debug.append({"label": "cinematic_cards", "hyperframes": hf_n, "ass": ass_n})
        ctx.log(f"   1/4 Кадрлар рендерленүүдө: {len(jobs)} …")
        t1 = time.time()
        if cine:
            infos: dict[int, dict] = {}

            def job(j):
                clip, out, kind, off, d, motion, inten = j
                pre, info = cinematic.shot_prefilter(clip, kind, off, d)
                idx = int(out.stem.split("_")[1])
                infos[idx] = info
                render_shot(clip, out, kind, off, d, motion, inten, prefilter=pre, card=card_for_shot.get(idx))
                if motion.startswith("v2:"):        # кыймыл чындап барбы — рендерленген кадрдан өлчөө
                    from .. import motion as motion_v2

                    m = motion_v2.measure(out, d)
                    det = motion_v2.classify(m)
                    info["motion"] = {"planned": motion_v2.parse(motion)[0], "detected": det,
                                      "match": motion_v2.matches(motion, det),
                                      **{k: m.get(k) for k in ("dx", "dy", "scale", "diff")}}

            with ThreadPoolExecutor(workers) as ex:
                list(ex.map(job, jobs))
            self._motion_report(ctx, infos, sdir, rdir)
            blur_n = sum(1 for v in infos.values() if v.get("blur_bg"))
            match_n = sum(1 for v in infos.values() if v.get("match"))
            debug.append({"label": "cinematic_shots", "blur_bg": blur_n, "matched": match_n,
                          "shots": {str(k): v for k, v in sorted(infos.items())}})
            ctx.log(f"   🎞 кадрлар: жарык/түс бирдейленди {match_n}, blur фон {blur_n} "
                    f"({time.time() - t1:.0f} сек)")
        else:
            with ThreadPoolExecutor(workers) as ex:
                list(ex.map(lambda j: render_shot(*j), jobs))

        # 2) сахна = кадрлар кесүү менен (copy)
        ctx.log(f"   2/4 Сахналар: {len(scenes)} …")
        scene_files, scene_durs, scene_trans = [], [], []
        for k, grp in enumerate(scenes):
            lst = sdir / f"scene_{k:03d}.txt"
            lst.write_text("".join(f"file 'shot_{sh['i']:03d}.mp4'\n" for sh in grp), encoding="utf-8")
            sf = sdir / f"scene_{k:03d}.mp4"
            media.run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(lst),
                       "-c", "copy", str(sf)], f"сахна {k}")
            trans = motions[grp[-1]["i"]].get("transition_out") or {"type": "cut", "dur": 0.0}
            scene_files.append(sf)
            scene_durs.append(sum(sh["dur"] for sh in grp) + trans.get("dur", 0.0))
            scene_trans.append(trans)
            expect_len(sf, scene_durs[-1], SCENE_TOL, f"сахна {k}", debug)

        # 3) өтүүлөр: ар сегмент өзүнчө кичине ffmpeg (чоң xfade графы жок), кадр-так
        ctx.log("   3/4 Өтүүлөр (сегменттер) …")
        video = rdir / "video_noaudio.mp4"
        vdur, vframes = stitch(scene_files, scene_durs, scene_trans, rdir, video, debug, workers=workers)
        expect_len(video, vdur, SEG_TOL, "бириктирилген видео (аудиосуз)", debug)
        last_ext = scene_trans[-1].get("dur", 0.0)
        expect_len(video, total + last_ext, FINAL_TOL,
                   "видео ↔ аудионун узактыгы (аудиосуз монтаж)", debug)

        # 4) акыркы өтүү: градация, виньетка, субтитр, карточкалар, үн
        ctx.log("   4/4 Акыркы кодировка (субтитр, түс, үн) …")
        c = plan["concept_params"]
        subs = ctx.path("subtitles", "subtitles.ass")
        cards = cards_ass
        look = cinematic.look_chain(c["grade"]) if cine else c["grade"]
        tail = (f"subtitles='{_esc(subs)}',subtitles='{_esc(cards)}',"
                f"fade=t=in:st=0:d=0.5,fade=t=out:st={max(0.0, total - 0.8):.3f}:d=0.8,format=yuv420p")
        band_in: list[str] = []
        if cine:   # СЫНАК: субтитр астында жумшак күңүрт градиент (ак фондо да окулат)
            band = cinematic.subtitle_band(rdir / "sub_band.png")
            band_in = ["-loop", "1", "-framerate", str(FPS), "-i", str(band)]
            graph = (f"[0:v]{look},vignette={c['vignette']}[g];"
                     f"[g][2:v]overlay=0:H-h:shortest=1:format=auto,{tail}[v]")
            debug.append({"label": "subtitle_band", "h": cinematic.BAND_H, "alpha": cinematic.BAND_ALPHA})
        else:
            graph = f"[0:v]{look},vignette={c['vignette']},{tail}[v]"
        final = rdir / "final.mp4"
        media.run(["ffmpeg", "-y", "-v", "error", "-i", str(video), "-i", str(mix), *band_in,
                   "-filter_complex", graph, "-map", "[v]", "-map", "1:a",
                   "-t", f"{total:.3f}", "-c:v", "libx264", "-preset", "fast", "-crf", "22" if cine else "20",
                   "-pix_fmt", "yuv420p", "-r", str(FPS), "-c:a", "aac", "-b:a", "192k",
                   "-ar", "48000", "-movflags", "+faststart", str(final)],
                  "акыркы монтаж", timeout=7200)
        # ЭКИ агымдын узактыгы ӨЗҮНЧӨ текшерилет (format.duration эң узунун берет — аны ишенбейбиз)
        sd = media.stream_durations(final)
        v_len, a_len = sd["video"], sd["audio"]
        size = final.stat().st_size / 1e6
        debug.append({"label": "final.mp4", "video": v_len, "audio": a_len, "want": round(total, 3),
                      "nb_frames": sd["nb_frames"]})
        if v_len is None or a_len is None:
            raise StageError(f"final.mp4'те агым жок: видео {v_len}, аудио {a_len}")
        ctx.log(f"   ✓ final.mp4: видео {v_len:.2f} сек, аудио {a_len:.2f} сек, "
                f"күтүлгөнү {total:.2f} сек, {sd['nb_frames']} кадр, {size:.0f} МБ")
        if abs(v_len - a_len) > 1.0 or abs(v_len - total) > FINAL_TOL:
            raise StageError(f"Видео менен аудионун узактыгы дал келбейт: видео {v_len:.1f} сек, "
                             f"аудио {a_len:.1f} сек, күтүлгөнү {total:.1f} сек")
        dur = min(v_len, a_len)
        res = {"final_path": str(final), "duration": round(dur, 2), "size_mb": round(size, 1),
               "video_sec": round(v_len, 2), "audio_sec": round(a_len, 2)}
        if cine:
            res["cinematic"] = True
        return res

    def _motion_report(self, ctx, infos: dict, sdir: Path, rdir: Path) -> None:
        """animation/motion_report.json + мисалдар сүрөтү (ар кыймыл түрү: башы | аягы) → Drive _diagnose/."""
        rows = {str(k): v["motion"] for k, v in sorted(infos.items()) if v.get("motion")}
        if not rows:
            return
        static = [k for k, r in rows.items() if r["detected"] == "static"]
        judged = [r for r in rows.values() if r["match"] is not None]
        ok = sum(1 for r in judged if r["match"])
        rep = {"shots": len(rows), "static": static, "matched": ok, "judged": len(judged),
               "by_type": {}, "rows": rows}
        for r in rows.values():
            rep["by_type"][r["planned"]] = rep["by_type"].get(r["planned"], 0) + 1
        ctx.log(f"   🎥 кыймыл: {len(rows)} кадр, статикалык {len(static)}, план↔өлчөө дал келди {ok}/{len(judged)}; "
                f"түрлөр {rep['by_type']}")
        # мисалдар: ар түрдөн бирден (≤8)
        picks, seen = [], set()
        for k, r in rows.items():
            if r["planned"] not in seen and r["match"]:
                seen.add(r["planned"])
                picks.append((int(k), r))
        tiles = []
        font = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
        for k, r in picks[:8]:
            f = sdir / f"shot_{k:03d}.mp4"
            d = video_len(f) or 3.0
            out = rdir / f"mex_{k:03d}.jpg"
            label = f"{r['planned']}  #{k}  scale {r['scale']}  dx {r['dx']}  dy {r['dy']}"
            dt = (f",drawtext=fontfile={font}:text='{label}':x=12:y=12:fontsize=22:fontcolor=white:"
                  f"box=1:boxcolor=black@0.6") if Path(font).exists() else ""
            try:
                media.run(["ffmpeg", "-y", "-v", "error", "-ss", f"{d * 0.12:.2f}", "-i", str(f), "-ss", f"{d * 0.88:.2f}",
                           "-i", str(f), "-filter_complex",
                           f"[0:v]scale=480:270[a];[1:v]scale=480:270[b];[a][b]hstack{dt}", "-frames:v", "1",
                           str(out)], "кыймыл мисалы")
                tiles.append(out)
            except StageError:
                pass
        if tiles:
            sheet = rdir / "motion_examples.jpg"
            inputs = []
            for p in tiles:
                inputs += ["-i", str(p)]
            media.run(["ffmpeg", "-y", "-v", "error", *inputs, "-filter_complex",
                       "".join(f"[{i}:v]" for i in range(len(tiles))) + f"vstack=inputs={len(tiles)}" if len(tiles) > 1
                       else "[0:v]null", "-frames:v", "1", str(sheet)], "кыймыл мисалдары")
            if ctx.store:
                rep["examples_url"] = ctx.store.publish("_diagnose", sheet, f"{ctx.video_id}_motion_examples.jpg")
                ctx.log(f"   🎥 кыймыл мисалдары (башы | аягы): {rep.get('examples_url')}")
        ctx.path("animation", "motion_report.json").write_text(json.dumps(rep, ensure_ascii=False, indent=1),
                                                               encoding="utf-8")

    def _cinematic_cards(self, ctx, shots, motions, plan, rdir):
        """Карточкаларды кадрларга жайгаштырып, HyperFrames менен рендерлейт (сынак).

        Кайтарат: ({кадр_индекси: (mov, кечигүү)}, финалдык ASS файлы (ишке ашпагандары гана), hf_n, ass_n).
        """
        import json as _json

        from .. import hfcards
        from .s6_animation import card_line

        src = ctx.path("animation", "overlays.ass")
        cj = ctx.path("animation", "cards.json")
        items = _json.loads(cj.read_text(encoding="utf-8")) if cj.exists() else []
        placed = []
        for c in items:
            sh = next((s for s in shots if s["start"] <= c["start"] < s["end"]), None)
            if sh is None:
                continue
            ext = (motions[sh["i"]].get("transition_out") or {}).get("dur", 0.0)
            delay = round(c["start"] - sh["start"], 3)
            dur = round(min(c["end"] - c["start"], sh["dur"] + ext - delay - 0.1), 3)
            placed.append({**c, "shot": sh["i"], "delay": delay, "dur": dur})
        done: dict[int, Path] = {}
        usable = [p for p in placed if p["dur"] >= 1.2]
        if hfcards.requested() and usable:
            accent = hfcards.accent_css(plan["concept_params"].get("card_color", "&H004EC1F2&"))
            res = hfcards.render_all(usable, rdir / "hf_cards", accent, log=ctx.log)
            done = {id(usable[k]): v for k, v in res.items()}
        elif not hfcards.requested():
            ctx.log("   ℹ️ YTA_HYPERFRAMES өчүк — карточкалар ASS бойдон")
        card_for_shot = {p["shot"]: (done[id(p)], p["delay"]) for p in usable if id(p) in done}
        left = [c for c in items if not any(id(p) in done and p["text"] == c["text"] and
                                            p["start"] == c["start"] for p in usable)]
        text = src.read_text(encoding="utf-8")
        header = text[: text.index("[Events]")] + "[Events]\n" + \
            "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
        out = ctx.path("animation", "overlays_final.ass")
        out.write_text(header + "\n".join(card_line(c) for c in left) + "\n", encoding="utf-8")
        return card_for_shot, out, len(card_for_shot), len(left)


def _esc(p: Path) -> str:
    return str(p).replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")
