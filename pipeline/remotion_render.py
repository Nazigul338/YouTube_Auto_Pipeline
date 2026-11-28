"""Remotion — кинематографиялык анимациялар (аталыш, карта, motion graphics, субтитр) үчүн рендер (СЫНАК).

Архитектура өзгөрбөйт: FFmpeg негизги монтаж/үн/бириктирүү/кодировка болуп калат (s8_render). Remotion
өзүнчө клип (MP4) рендерлейт — аны FFmpeg кадимки клип катары колдонот/кодировкалайт. Ар видео өз props'ун
(түс, текст, маршрут, өтүүлөр, субтитр) берет — бир шаблон кайталанбайт.

Талаптар: Node ≥ 22, `tools/remotion` ичинде `npm ci` (версиялар бекитилген, remotion 4.0.547).
Браузер: Remotion өзү жүктөйт (remotion.media). Ал бөгөттөлгөн чөйрөдө гана YTA_REMOTION_BROWSER менен
бар Chrome Headless Shell берилет (мис. Claude cloud контейнери).
Лицензия: жеке адам / ≤3 кишилик компания үчүн акысыз (https://www.remotion.dev/docs/license). Ачкыч болсо —
YTA_REMOTION_LICENSE (GitHub Secret) аркылуу гана; кодго/логго жазылбайт.

Күйгүзүү: YTA_REMOTION=1 (демейки өчүк). Ошондо да TEST папкаларында гана иштейт (YouTube_Auto_TEST,
YouTube_Auto_EN_TEST); production папкасы үчүн REMOTION_PRODUCTION_APPROVED = True керек — аны колдонуучунун
уруксаты менен гана өзгөртүү. Азыр колдонулушу: 8-этаптагы текст-карточкалар (HyperFrames/ASS ордунда;
Remotion иштебей калса — HyperFrames, андан кийин ASS).

Сыноо: python -m pipeline.remotion_render --selftest out_dir
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from . import media
from .errors import StageError

REPO = Path(__file__).resolve().parents[1]
FPS = 30
W, H = 1920, 1080


# Production папкасында иштөөгө колдонуучунун уруксаты (2026-11-28: али берилген жок — False бойдон).
REMOTION_PRODUCTION_APPROVED = False
CARD_STYLES = ("focus", "mask", "cascade", "frame")


def enabled() -> bool:
    """Желек гана (YTA_REMOTION=1). Папканы текшерүү — active()."""
    return os.environ.get("YTA_REMOTION", "").strip().lower() in ("1", "true", "yes")


def allowed(store=None) -> bool:
    from . import cinematic

    return cinematic.is_test_root(store) or REMOTION_PRODUCTION_APPROVED


def active(store=None) -> bool:
    """Remotion ушул видеодо колдонулабы: желек күйүк ЖАНА папка уруксат берилген."""
    return enabled() and allowed(store)


def blocked_reason(store=None) -> str | None:
    if enabled() and not allowed(store):
        from . import cinematic

        return (f"YTA_REMOTION=1, бирок папка «{cinematic.root_name(store) or '?'}» — Remotion азырынча TEST "
                f"папкаларында гана (production'го колдонуучунун уруксаты керек). Өчүк калды.")
    return None


def pick_card_style(video_id: str, registry: dict | None) -> str:
    """Ар видеого карточка стили: video_id'ден, бирок акыркы видеонун стили КАЙТАЛАНБАЙТ."""
    import hashlib

    vids = ((registry or {}).get("videos") or {})
    prev = [v.get("remotion_card_style") for k, v in sorted(vids.items()) if k != video_id and isinstance(v, dict)]
    last = next((x for x in reversed(prev) if x), None)
    start = int(hashlib.sha1(video_id.encode()).hexdigest(), 16) % len(CARD_STYLES)
    order = CARD_STYLES[start:] + CARD_STYLES[:start]
    return next(st for st in order if st != last)


def tools_dir() -> Path:
    return Path(os.environ.get("YTA_REMOTION_DIR") or REPO / "tools" / "remotion")


def available() -> tuple[bool, str]:
    """(иштейби, себеби)."""
    if shutil.which("node") is None:
        return False, "node табылган жок"
    if shutil.which("ffmpeg") is None:
        return False, "ffmpeg табылган жок"
    if not (tools_dir() / "node_modules" / ".bin" / "remotion").exists():
        return False, f"Remotion CLI жок ({tools_dir()}) — `npm ci` иштетилген эмес"
    return True, "ok"


def render(composition: str, props: dict, out: Path, *, audio: Path | None = None, log=print,
           timeout: int = 1800, extra: list[str] | None = None) -> Path:
    """Remotion композициясын props менен MP4'кө рендерлейт. audio берилсе — public/ ичине көчүрүлөт."""
    ok, why = available()
    if not ok:
        raise StageError(f"Remotion: {why}")
    d = tools_dir()
    props = dict(props)
    public = d / "public"
    public.mkdir(exist_ok=True)
    copied = None
    if audio is not None:
        copied = public / f"_yta_{os.getpid()}_{audio.name}"
        shutil.copy2(audio, copied)
        props["audio"] = copied.name
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
        json.dump(props, f, ensure_ascii=False)
        pfile = f.name
    cmd = [str(d / "node_modules" / ".bin" / "remotion"), "render", "src/index.ts", composition, str(out.resolve()),
           f"--props={pfile}", "--log=info", *(extra or [])]
    browser = os.environ.get("YTA_REMOTION_BROWSER", "").strip()
    if browser:
        cmd.append(f"--browser-executable={browser}")
    lic = os.environ.get("YTA_REMOTION_LICENSE", "").strip()
    env = {**os.environ, "REMOTION_DISABLE_TELEMETRY": "1"}
    if lic:
        cmd.append(f"--license-key={lic}")          # ката текстинде *** менен жашырылат
    log(f"   🎞 Remotion: {composition} → {out.name}")
    try:
        r = subprocess.run(cmd, cwd=d, capture_output=True, text=True, timeout=timeout, env=env)
    except subprocess.TimeoutExpired:
        raise StageError(f"Remotion: {timeout} сек ичинде бүткөн жок")
    finally:
        os.unlink(pfile)
        if copied is not None:
            copied.unlink(missing_ok=True)
    if r.returncode != 0 or not out.exists():
        tail = "\n".join(((r.stderr or "") + (r.stdout or "")).strip().splitlines()[-15:])
        if lic:
            tail = tail.replace(lic, "***")
        raise StageError(f"Remotion рендер катасы (код {r.returncode}):\n{tail}")
    return out


ALPHA_ARGS = ["--codec=prores", "--prores-profile=4444", "--pixel-format=yuva444p10le", "--image-format=png"]


def render_card(text: str, dur: float, workdir: Path, accent: str, style: str, seed: str,
                log=print) -> tuple[Path | None, str]:
    """Бир тунук карточка (ProRes 4444 MOV, alpha). (жол же None, түшүндүрмө) — ката болсо видео токтобойт."""
    from . import hfcards

    out = Path(workdir).resolve() / "card.mov"
    try:
        render("Card", {"text": text, "dur": round(dur, 3), "accent": accent, "style": style, "seed": seed}, out,
               log=lambda *_: None, timeout=300, extra=ALPHA_ARGS)
    except StageError as e:
        return None, str(e).splitlines()[0][:200]
    ok, why = hfcards.validate(out, dur)
    return (out if ok else None), why


def render_cards(cards: list[dict], workdir: Path, accent: str, style: str, seed: str,
                 log=print) -> dict[int, Path]:
    """{карточканын индекси: mov}. Ишке ашпагандары кайтарылбайт (алар HyperFrames/ASS бойдон калат)."""
    ok, why = available()
    if not ok:
        log(f"   ⚠️ Remotion жеткиликсиз ({why}) — карточкалар HyperFrames/ASS менен")
        return {}
    done: dict[int, Path] = {}
    for k, c in enumerate(cards):
        path, why = render_card(c["text"], c["dur"], Path(workdir) / f"card_{k:02d}", accent, style, f"{seed}-{k}")
        log(f"   {'✓' if path else '⚠️'} Remotion карточка {k + 1}/{len(cards)} «{c['text']}» ({style}): {why}"
            + ("" if path else " → HyperFrames/ASS колдонулат"))
        if path:
            done[k] = path
    return done


def finish(raw: Path, out: Path, *, audio: Path | None = None) -> Path:
    """FFmpeg акыркы этабы: YouTube 16:9 H.264 High / yuv420p / bt709 (tv), AAC 48 kHz, faststart.

    audio берилсе — үн ушул файлдан алынат (pipeline'дын s7 миксин FFmpeg бириктирет), болбосо Remotion'дун үнү.
    Үн бул жерде кайра нормалдаштырылбайт: аны s7 жасайт. Сынакта бир өтүүчү loudnorm аягына жакын бипти
    82 мс жылдырып, үндү 0.1 сек узартты — ошондуктан бул жерде колдонулбайт. Үн видеонун узундугуна кесилет."""
    vdur = float(next(s for s in media.probe(raw)["streams"] if s["codec_type"] == "video")["duration"])
    src = ["-i", str(raw)] + (["-i", str(audio)] if audio is not None else [])
    amap = "1:a:0" if audio is not None else "0:a:0"
    media.run(["ffmpeg", "-y", "-v", "error", *src, "-map", "0:v:0", "-map", amap,
               "-vf", "scale=1920:1080:flags=lanczos:out_range=tv,setsar=1,format=yuv420p",
               "-c:v", "libx264", "-profile:v", "high", "-preset", "medium", "-crf", "18", "-r", str(FPS),
               "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709", "-color_range", "tv",
               "-af", "apad", "-t", f"{vdur:.3f}", "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
               "-movflags", "+faststart", str(out)], "ffmpeg finish")
    return out


def validate(path: Path, expect: float, tol: float = 0.1, strict: bool = True) -> dict:
    """MP4 туурабы: 1920×1080 16:9, 30 fps, H.264 + AAC, узактык, видео/үн узактыгы, толук декоддолот."""
    info = media.probe(path)
    v = next((s for s in info["streams"] if s["codec_type"] == "video"), None)
    a = next((s for s in info["streams"] if s["codec_type"] == "audio"), None)
    problems = []
    if v is None:
        problems.append("видео агым жок")
    if a is None:
        problems.append("үн агымы жок")
    res = {"problems": problems}
    if v is not None:
        num, den = (v.get("r_frame_rate") or "0/1").split("/")
        fps = float(num) / float(den or 1)
        vd = float(v.get("duration") or info["format"]["duration"])
        res.update(width=v["width"], height=v["height"], vcodec=v["codec_name"], pix_fmt=v.get("pix_fmt"),
                   fps=round(fps, 3), vdur=round(vd, 3))
        if (v["width"], v["height"]) != (W, H):
            problems.append(f"өлчөм {v['width']}×{v['height']} (керек 1920×1080)")
        if v["codec_name"] != "h264" or (strict and v.get("pix_fmt") != "yuv420p"):
            problems.append(f"кодек {v['codec_name']}/{v.get('pix_fmt')} (керек h264/yuv420p)")
        if abs(fps - FPS) > 0.01:
            problems.append(f"fps {fps}")
        if abs(vd - expect) > tol:
            problems.append(f"видео {vd:.2f} сек (керек {expect:.2f})")
    if a is not None:
        ad = float(a.get("duration") or 0)
        res.update(acodec=a["codec_name"], adur=round(ad, 3), sample_rate=a.get("sample_rate"))
        if a["codec_name"] != "aac":
            problems.append(f"үн кодеги {a['codec_name']}")
        if v is not None and abs(ad - res["vdur"]) > 0.05:
            problems.append(f"видео {res['vdur']} vs үн {ad:.3f} сек")
    dec = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-f", "null", "-"], capture_output=True, text=True)
    if dec.returncode != 0 or dec.stderr.strip():
        problems.append("декоддоо катасы: " + dec.stderr.strip()[-200:])
    res["ok"] = not problems
    return res


def flash_times(path: Path, thr: float = 200.0) -> list[float]:
    """Сол жогорку бурчтагы ак белгинин (SyncFlash) башталыш убактылары."""
    r = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-an", "-vf",
                        "crop=48:48:8:8,signalstats,metadata=print:key=lavfi.signalstats.YAVG:file=-",
                        "-f", "null", "-"], capture_output=True, text=True)
    out, prev, t = [], False, None
    for line in r.stdout.splitlines():
        m = re.search(r"pts_time:([\d.]+)", line)
        if m:
            t = float(m.group(1))
        m = re.search(r"YAVG=([\d.]+)", line)
        if m and t is not None:
            on = float(m.group(1)) > thr
            if on and not prev:
                out.append(round(t, 3))
            prev = on
    return out


def beep_times(path: Path) -> list[float]:
    """1 kHz «бип» башталыштары (fon тынч, бип ачык): highpass → silencedetect."""
    r = subprocess.run(["ffmpeg", "-v", "info", "-i", str(path), "-vn", "-af",
                        "highpass=f=700,lowpass=f=1500,silencedetect=noise=-32dB:d=0.04", "-f", "null", "-"],
                       capture_output=True, text=True)
    return [round(float(x), 3) for x in re.findall(r"silence_end: ([\d.]+)", r.stderr)]


def sync_report(path: Path, marks: list[float], tol: float = 0.05) -> dict:
    """Ар белги үчүн видеодогу жарк менен үндөгү бип ортосундагы айырма (≤tol сек = шайкеш)."""
    fl, bp = flash_times(path), beep_times(path)
    rows = []
    for m in marks:
        f = min(fl, key=lambda x: abs(x - m), default=None)
        b = min(bp, key=lambda x: abs(x - m), default=None)
        off = None if f is None or b is None else round(b - f, 3)
        rows.append({"mark": m, "flash": f, "beep": b, "offset": off})
    ok = bool(rows) and all(r["offset"] is not None and abs(r["offset"]) <= tol
                            and abs(r["flash"] - r["mark"]) <= 1.5 / FPS for r in rows)
    return {"ok": ok, "rows": rows, "flashes": fl, "beeps": bp}


def make_test_audio(path: Path, dur: float, marks: list[float]) -> Path:
    """Сынак үнү (FFmpeg): тынч «бөлмө» фону + ар белгиде 1 kHz 80 мс бип."""
    beeps = "+".join(f"between(t,{m},{m + 0.08})" for m in marks) or "0"
    media.run(["ffmpeg", "-y", "-v", "error",
               "-f", "lavfi", "-i", f"anoisesrc=d={dur}:c=brown:a=0.02:r=48000",
               "-f", "lavfi", "-i", f"aevalsrc='0.5*sin(2*PI*1000*t)*({beeps})':d={dur}:s=48000",
               "-filter_complex", "[0][1]amix=inputs=2:normalize=0,lowpass=f=8000,aformat=channel_layouts=stereo",
               "-c:a", "pcm_s16le", str(path)], "ffmpeg test audio")
    return path


def selftest(out_dir: Path, log=print) -> dict:
    """15 сек сынак: Remotion (аталыш, карта, өтүүлөр, субтитр, grain) + FFmpeg (үн, акыркы кодировка) + текшерүү."""
    out_dir.mkdir(parents=True, exist_ok=True)
    marks = [1.0, 7.0, 13.5]
    dur = 15.0
    audio = make_test_audio(out_dir / "test_audio.wav", dur, marks)
    raw = render("DocTest", {"syncMarks": marks, "seed": "selftest"}, out_dir / "remotion_raw.mp4", audio=audio, log=log)
    final = finish(raw, out_dir / "remotion_test_15s.mp4", audio=audio)
    # raw — Remotion'дун ортодогу файлы (yuvj420p болушу мүмкүн); катаал талап акыркы файлга
    rep = {"raw": validate(raw, dur, strict=False), "raw_sync": sync_report(raw, marks), "final": validate(final, dur), "sync": sync_report(final, marks)}
    rep["ok"] = all(rep[k]["ok"] for k in ("raw", "raw_sync", "final", "sync"))
    (out_dir / "remotion_test_report.json").write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
    return rep


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", metavar="OUT_DIR")
    a = ap.parse_args(argv)
    if not a.selftest:
        ap.print_help()
        return 2
    rep = selftest(Path(a.selftest))
    print(json.dumps(rep, ensure_ascii=False, indent=1))
    print("✅ Remotion сынагы өттү" if rep["ok"] else "❌ Remotion сынагы өткөн жок")
    return 0 if rep["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
