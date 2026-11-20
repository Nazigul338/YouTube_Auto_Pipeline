"""Видеонун ӨЗ кадрынан обложка (1280×720, JPG): түс күчөтүлөт, сол жакта караңгы градиент, чоң кызыктуу жазуу.

    VIDEO_FILE=Video_001_cinematic.mp4 THUMBS='14|ВЫ ЖИВЁТЕ|ДЛЯ НИХ?;300|ТИХАЯ|МЕСТЬ' \
    YTA_DRIVE_FOLDER=YouTube_Auto_TEST python -m pipeline.thumbnail

THUMBS: `сек|1-сап|2-сап` вариант, `;` менен бөлүнөт. Натыйжа: Drive → <root>/Thumbnails/<ID>_thumb_<N>.jpg
жана бардык варианттар бир барakta (<ID>_thumbs.jpg). Кадр — видеонун лицензиясы катталган материалы
(Pixabay/Pexels), жазуу — оригиналдуу; бөтөн логотип/адамдын сүрөтү кошулбайт. Кадр ТАЗА булак клиптен
алынат (субтитр/карточка жок); табылбаса гана даяр видеодон.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

from . import media

W, H = 1280, 720
YELLOW = "0xFFD21F"
FONT_CANDIDATES = ("Montserrat:style=Black", "Montserrat:style=ExtraBold", "Montserrat:style=Bold",
                   "DejaVu Sans:style=Bold")


def parse(spec: str) -> list[tuple[float, str, str]]:
    out = []
    for part in spec.split(";"):
        bits = [b.strip() for b in part.split("|")]
        if len(bits) >= 2 and bits[0]:
            out.append((float(bits[0]), bits[1], bits[2] if len(bits) > 2 else ""))
    return out


def fit_size(text: str, base: int, max_w: int = int(W * 0.66)) -> int:
    """Болжолдуу кенендик (жоон шрифт ≈ 0.68×өлчөм бир тамгага) — сапка батсын."""
    n = max(1, len(text))
    return int(max(56, min(base, max_w / (0.68 * n))))


def shot_at(shots: list[dict], t: float) -> dict | None:
    for sh in shots:
        if sh.get("start", 0) <= t < sh.get("end", 0):
            return sh
    return None


def clean_source(shots: list[dict], t: float, work: Path, stock=None) -> tuple[Path, float] | None:
    """Субтитрсиз/карточкасыз ТАЗА кадр үчүн: ошол учурдагы булак клип жана андагы убакыт.

    Себеби (2026-11-20): даяр видеодон алынган кадрда субтитр жана текст-карточка калып калган.
    """
    sh = shot_at(shots, t)
    if not sh or not sh.get("url") or sh.get("source") == "gemini":
        return None
    from .stock import Asset, Stock

    stock = stock or Stock(os.environ.get("PIXABAY_API_KEY", ""), os.environ.get("PEXELS_API_KEY"))
    dest = work / f"clip_{sh.get('i', 0)}{Path(sh.get('file', 'x.mp4')).suffix or '.mp4'}"
    a = Asset(sh["source"], sh.get("kind", "video"), sh["asset"], sh["url"], 1920, 1080, 0.0, "", "", "", "")
    try:
        stock.download(a, dest)
    except Exception:
        fresh = stock.refresh_url(sh["asset"]) if hasattr(stock, "refresh_url") else None
        if not fresh:
            return None
        a.url = fresh
        stock.download(a, dest)
    if sh.get("kind") == "image":
        return dest, 0.0
    return dest, max(0.0, float(sh.get("offset", 0.0)) + (t - sh["start"]))


def thumb_similarity(a: str, b: str) -> float:
    import re

    wa, wb = set(re.findall(r"\w{3,}", a.lower())), set(re.findall(r"\w{3,}", b.lower()))
    return len(wa & wb) / len(wa | wb) if wa and wb else 0.0


def check_unique(specs: list[tuple[float, str, str]], registry: dict, video_id: str,
                 limit: float = 0.5) -> list[tuple[tuple[float, str, str], str | None]]:
    """Оригиналдуулук: обложканын жазуусу мурунку видеолордукуна окшош болбосун → [(вариант, себеп|None)]."""
    prev = [(vid, t) for vid, v in registry.get("videos", {}).items() if vid != video_id
            for t in (v.get("thumbnail") or {}).get("texts", [])]
    out = []
    for sp in specs:
        text = f"{sp[1]} {sp[2]}"
        hit = next(((vid, t) for vid, t in prev if thumb_similarity(text, t) >= limit), None)
        out.append((sp, f"{hit[0]}: «{hit[1]}»" if hit else None))
    return out


LAYOUTS = ("left", "right", "center")


def make(src: Path, t: float, line1: str, line2: str, out: Path, work: Path, *, accent: str = YELLOW,
         layout: str = "left", font_pref: str | None = None) -> Path:
    """Обложка: кадр + градиент (жазуу жакта) + 2 сап (ак + акцент түс). layout: left/right/center (концепцияга жараша)."""
    frame = work / f"f_{int(t * 10)}_{abs(hash(str(src))) % 10000}.png"
    media.run(["ffmpeg", "-y", "-v", "error", "-ss", f"{t:.2f}", "-i", str(src), "-frames:v", "1", str(frame)],
              "обложка кадры")
    key = f"{int(t * 10)}_{abs(hash(line1 + line2)) % 10000}"
    t1, t2 = work / f"l1_{key}.txt", work / f"l2_{key}.txt"
    t1.write_text(line1, encoding="utf-8")
    t2.write_text(line2, encoding="utf-8")
    font = font_file(font_pref)
    ff = f"fontfile='{font}':" if font else ""
    s1, s2 = fit_size(line1, 112), fit_size(line2, 158)
    y2 = H - 70 - s2
    y1 = y2 - 18 - s1
    if layout == "right":
        x1, x2 = f"w-tw-58", f"w-tw-56"
        alpha = "215*pow(max(0\\,X/W-0.3)/0.7\\,1.3)"
    elif layout == "center":
        x1 = x2 = "(w-tw)/2"
        alpha = "225*pow(max(0\\,Y/H-0.35)/0.65\\,1.2)"
    else:
        x1, x2 = "58", "56"
        alpha = "215*pow(max(0\\,1-X/(W*0.7))\\,1.3)"
    draw = (f"drawtext={ff}textfile='{t1}':fontsize={s1}:fontcolor=white:borderw=5:bordercolor=black@0.85:"
            f"shadowx=4:shadowy=4:shadowcolor=black@0.6:x={x1}:y={y1},"
            f"drawtext={ff}textfile='{t2}':fontsize={s2}:fontcolor={accent}:borderw=6:bordercolor=black@0.9:"
            f"shadowx=5:shadowy=5:shadowcolor=black@0.6:x={x2}:y={y2}") if line2 else \
        (f"drawtext={ff}textfile='{t1}':fontsize={s1}:fontcolor=white:borderw=5:bordercolor=black@0.85:"
         f"x={x1}:y={H - 70 - s1}")
    graph = (f"[0:v]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},"
             "eq=contrast=1.16:saturation=1.22:brightness=-0.02,unsharp=5:5:0.7,vignette=PI/5[b];"
             f"color=black:s={W}x{H},format=rgba,geq=r=0:g=0:b=0:a='{alpha}'[g];"
             f"[b][g]overlay=format=auto,{draw},format=yuvj420p[o]")
    media.run(["ffmpeg", "-y", "-v", "error", "-i", str(frame), "-filter_complex", graph, "-map", "[o]",
               "-frames:v", "1", "-q:v", "2", str(out)], "обложка")
    return out


def image_hash(path: Path) -> str:
    """Обложканын dHash'ы (мурунку обложкалар менен сүрөт окшоштугу)."""
    import numpy as np

    from .visual_compare import dhash

    r = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-vf", "scale=64:36,format=gray", "-f", "rawvideo",
                        "-"], capture_output=True, timeout=60)
    g = np.frombuffer(r.stdout[:64 * 36], np.uint8).reshape(36, 64).astype(float)
    return f"{dhash(g):016x}"


THUMB_PROMPT = """You design YouTube thumbnails for a Russian psychology channel. The thumbnail must make a viewer
stop scrolling: intrigue, emotion, a question or tension — honest, no clickbait lies, no shouting caps words beyond
the text itself. It must fit THIS video's own visual world and differ from our previous thumbnails.

Title: {title}
Hook (first seconds): {hook}
Visual world of the video: {world}
Previous thumbnail texts (do NOT repeat their wording or idea): {previous}
Candidate frames (index. narration at that moment):
{shots}

Return JSON only: [{{"line1": "<1-3 Russian words, white>", "line2": "<1-3 Russian words, accent, the punch>",
"shot": <index of the best frame for this text: a person/emotion or a strong motif, no text in frame>}}] — 3 options,
each with a different angle."""


def font_file(pref: str | None = None) -> str:
    cands = ([f"{pref}:style=Black", f"{pref}:style=Bold", pref] if pref else []) + list(FONT_CANDIDATES)
    for q in cands:
        try:
            r = subprocess.run(["fc-match", "-f", "%{file}", q], capture_output=True, text=True, timeout=10)
            fam = subprocess.run(["fc-match", "-f", "%{family}", q], capture_output=True, text=True, timeout=10)
            if r.stdout and q.split(":")[0].lower() in fam.stdout.lower():
                return r.stdout
        except (OSError, subprocess.TimeoutExpired):
            continue
    return ""


def auto_thumbnails(ctx, title: str = "") -> dict:
    """s9 (QA өткөндөн кийин): Gemini жазуу сунуштайт → концепциянын стили → таза клиптен кадр → мурункулар менен
    текст жана сүрөт боюнча салыштыруу → Drive Thumbnails/. Ката болсо видеого таасир этпейт."""
    import json

    from .stages.base import gemini_of

    entry = ctx.registry.setdefault("videos", {}).setdefault(ctx.video_id, {})
    brief = entry.get("edit_brief") or {}
    meta = {}
    try:
        meta = json.loads(ctx.path("script", "meta.json").read_text(encoding="utf-8"))
    except Exception:
        pass
    shots = json.loads(ctx.path("clips", "shots.json").read_text(encoding="utf-8"))["shots"]
    words = []
    try:
        words = json.loads(ctx.path("subtitles", "timings.json").read_text(encoding="utf-8"))["words"]
    except Exception:
        pass
    cands = sorted([s for s in shots if s.get("source") != "gemini" and s.get("kind") == "video"],
                   key=lambda s: -(s.get("ai_score") or 0))[:24]
    cands.sort(key=lambda s: s["start"])
    text_at = lambda s: " ".join(w["w"] for w in words if w["e"] > s["start"] and w["s"] < s["end"])[:120]
    prev = [t for v, e in ctx.registry.get("videos", {}).items() if v != ctx.video_id
            for t in (e.get("thumbnail") or {}).get("texts", [])]
    prev_hashes = [h for v, e in ctx.registry.get("videos", {}).items() if v != ctx.video_id
                   for h in (e.get("thumbnail") or {}).get("hashes", [])]
    opts = []
    try:
        data = gemini_of(ctx).json(THUMB_PROMPT.format(
            title=title or meta.get("title", ""), hook=meta.get("hook", ""), world=brief.get("world", ""),
            previous="; ".join(prev[-12:]) or "(none)",
            shots="\n".join(f"{k}. {text_at(s)}" for k, s in enumerate(cands))), purpose="thumbnail", temperature=0.9)
        for o in data if isinstance(data, list) else []:
            k = int(o.get("shot", 0))
            if 0 <= k < len(cands) and str(o.get("line1", "")).strip():
                opts.append((cands[k], str(o["line1"]).strip()[:22].upper(), str(o.get("line2", "")).strip()[:22].upper()))
    except Exception as e:
        ctx.log(f"   ⚠️ Обложка тексти Gemini'ден келген жок ({type(e).__name__}) — hook'тон")
    if not opts and cands:
        hc = (meta.get("hook_card") or title or "").upper().split()
        mid = max(1, len(hc) // 2)
        opts = [(cands[k * len(cands) // 3], " ".join(hc[:mid]), " ".join(hc[mid:])) for k in range(min(3, len(cands)))]
    layout = LAYOUTS[int(hashlib_md5(ctx.video_id + brief.get("name", "")) % 3)]
    accent = brief.get("subtitles", {}).get("highlight", "#FFD21F").replace("#", "0x")
    font_pref = "Montserrat" if brief.get("subtitles", {}).get("font", "Montserrat").startswith("Montserrat") else "DejaVu Sans"
    out_dir = ctx.path("thumbnails")
    out_dir.mkdir(exist_ok=True)
    made, rejected = [], []
    for k, (sh, l1, l2) in enumerate(opts, 1):
        if check_unique([(0.0, l1, l2)], ctx.registry, ctx.video_id)[0][1]:
            rejected.append(f"«{l1} {l2}»: жазуусу мурункуга окшош")
            continue
        clip = ctx.path("clips", sh["file"])
        if not clip.exists():
            continue
        at = float(sh.get("offset", 0.0)) + sh["dur"] / 2
        out = make(clip, at, l1, l2, out_dir / f"{ctx.video_id}_thumb_{k}.jpg", out_dir, accent=accent, layout=layout,
                   font_pref=font_pref)
        h = image_hash(out)
        if any(bin(int(h, 16) ^ int(p, 16)).count("1") <= 8 for p in prev_hashes):
            rejected.append(f"«{l1} {l2}»: сүрөтү мурунку обложкага окшош")
            continue
        url = ctx.store.publish("Thumbnails", out, out.name) if ctx.store else None
        made.append({"file": out.name, "text": f"{l1} {l2}".strip(), "shot": sh["i"], "hash": h, "url": url})
    entry["thumbnail"] = {"texts": [m["text"] for m in made], "hashes": [m["hash"] for m in made],
                          "layout": layout, "accent": accent, "files": [m["file"] for m in made],
                          "urls": [m["url"] for m in made], "rejected": rejected}
    (ctx.path("thumbnails", "thumbnails.json")).write_text(json.dumps(entry["thumbnail"], ensure_ascii=False, indent=1),
                                                           encoding="utf-8")
    ctx.log(f"   🖼 Обложка: {len(made)} вариант ({layout}, акцент {accent})" +
            (f"; четке кагылды: {'; '.join(rejected)}" if rejected else "") +
            "".join(f"\n      {m['text']}: {m['url']}" for m in made))
    return entry["thumbnail"]


def hashlib_md5(s: str) -> int:
    import hashlib

    return int(hashlib.md5(s.encode()).hexdigest(), 16)


def sheet(files: list[Path], out: Path) -> Path:
    ins = []
    for f in files:
        ins += ["-i", str(f)]
    n = len(files)
    g = "".join(f"[{i}:v]scale=640:360[s{i}];" for i in range(n)) + "".join(f"[s{i}]" for i in range(n)) + \
        (f"vstack=inputs={n}[o]" if n > 1 else "null[o]")
    media.run(["ffmpeg", "-y", "-v", "error", *ins, "-filter_complex", g, "-map", "[o]", "-frames:v", "1",
               "-q:v", "3", str(out)], "обложкалар барагы")
    return out


def main() -> int:
    from .drive import DriveClient, mask_email

    root = os.environ.get("YTA_DRIVE_FOLDER", "YouTube_Auto_TEST")
    vid = os.environ.get("VIDEO_ID", "Video_001").strip()
    name = os.environ.get("VIDEO_FILE", f"{vid}.mp4").strip()
    specs = parse(os.environ.get("THUMBS", ""))
    if not specs:
        print("❌ THUMBS бош")
        return 2
    drive = DriveClient.from_env()
    if drive is None:
        print("❌ GDRIVE_* жок")
        return 2
    print(f"☁️  Drive: {mask_email(drive.whoami())}; {root}/Final_Videos/{name}; шрифт: {font_file() or 'демейки'}")
    fid = drive.find_path(root, "Final_Videos")
    item = drive.find_file(name, fid) if fid else None
    if not item:
        print("❌ Видео табылган жок")
        return 2
    from .storage import DriveStore

    store = DriveStore(drive, root)
    registry = store.load_registry()
    checked = check_unique(specs, registry, vid)
    for sp, why in checked:
        if why:
            print(f"⚠️ «{sp[1]} {sp[2]}» мурунку обложкага окшош ({why}) — четке кагылды (оригиналдуулук)")
    specs = [sp for sp, why in checked if not why]
    if not specs:
        print("❌ Бардык варианттар мурунку обложкаларга окшош — башка жазуу бериңиз")
        return 3
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        import json

        shots = []
        cdir = drive.find_path(root, "Projects", vid, "clips")
        sj = drive.find_file("shots.json", cdir) if cdir else None
        if sj:
            shots = json.loads(drive.download_file(sj["id"], d / "shots.json").read_text(encoding="utf-8"))["shots"]
        src = None
        folder = drive.ensure_path(root, "Thumbnails")
        files, lines = [], []
        for k, (t, l1, l2) in enumerate(specs, 1):
            clean = clean_source(shots, t, d) if shots else None
            if clean:
                out = make(clean[0], clean[1], l1, l2, d / f"{vid}_thumb_{k}.jpg", d)
            else:
                print(f"⚠️ {t:.0f} сек: таза булак клип табылган жок — даяр видеодон (субтитр калышы мүмкүн)")
                src = src or drive.download_file(item["id"], d / "src.mp4")
                out = make(src, t, l1, l2, d / f"{vid}_thumb_{k}.jpg", d)
            files.append(out)
            pid = drive.put_file(out, folder, out.name)
            lines.append(f"🖼 ОБЛОЖКА {k} ({t:.0f} сек, «{l1} {l2}»): https://drive.google.com/file/d/{pid}/view")
        sh = sheet(files, d / f"{vid}_thumbs.jpg")
        sid = drive.put_file(sh, folder, sh.name)
        lines.append(f"📋 БААРЫ БИР БАРАКТА: https://drive.google.com/file/d/{sid}/view")
        registry.setdefault("videos", {}).setdefault(vid, {})["thumbnail"] = {
            "texts": [f"{l1} {l2}".strip() for _, l1, l2 in specs], "times": [t for t, _, _ in specs]}
        store.save_registry(registry)
        msg = "\n".join(lines)
        print(msg)
        path = os.environ.get("GITHUB_STEP_SUMMARY")
        if path:
            with open(path, "a", encoding="utf-8") as f:
                f.write(msg + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
