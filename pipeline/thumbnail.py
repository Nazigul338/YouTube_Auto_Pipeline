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
import re
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


LAYOUTS = ("left", "right", "center", "top")
ACCENTS = ("0xFFD21F", "0xFF5A36", "0x4FD8FF", "0xB7FF3C", "0xFF7AC8", "0xFFFFFF")
MAX_WORDS = 6                 # обложкадагы жазуу кыска (2 сап, ≤6 сөз)
MIN_CONTRAST = 0.12           # жарыктын std (0–1): андан аз — бүдөмүк, көзгө урунбайт
BRIGHT_RANGE = (0.08, 0.85)


def choose_layout(registry: dict, video_id: str, seed: str) -> str:
    """Мурунку видеолордо эң аз колдонулган жана акыркысынан БАШКА жайгашуу (композиция кайталанбасын)."""
    prev = [(v.get("thumbnail") or {}).get("layout") for k, v in sorted(registry.get("videos", {}).items())
            if k != video_id]
    prev = [x for x in prev if x]
    last = prev[-1] if prev else None
    return min((l for l in LAYOUTS if l != last), key=lambda l: (prev.count(l), hashlib_md5(seed + l) % 97))


def choose_accent(registry: dict, video_id: str, wanted: str) -> str:
    """Акцент түсү — концепциядан; мурунку видеонукундай болсо, палитрадан башкасы."""
    prev = [(v.get("thumbnail") or {}).get("accent") for k, v in sorted(registry.get("videos", {}).items())
            if k != video_id]
    prev = [x.upper() for x in prev if x]
    if wanted.upper() not in prev[-2:]:
        return wanted
    return next(a for a in ACCENTS if a.upper() not in prev[-2:])


def quality(path: Path) -> dict:
    """Көзгө урунабы: контраст (жарыктын std) жана орточо жарык."""
    import numpy as np

    r = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-vf", "scale=160:90,format=gray", "-f", "rawvideo",
                        "-"], capture_output=True, timeout=60)
    g = np.frombuffer(r.stdout[:160 * 90], np.uint8).astype(float) / 255
    c, m = round(float(g.std()), 3), round(float(g.mean()), 3)
    return {"contrast": c, "brightness": m, "ok_image": c >= MIN_CONTRAST and BRIGHT_RANGE[0] <= m <= BRIGHT_RANGE[1]}


def make(src: Path, t: float, line1: str, line2: str, out: Path, work: Path, *, accent: str = YELLOW,
         layout: str = "left", font_pref: str | None = None, boost: float = 1.0) -> Path:
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
    if layout == "top":
        y1 = 52
        y2 = y1 + s1 + 14
        x1 = x2 = "(w-tw)/2"
        alpha = "225*pow(max(0\\,1-Y/(H*0.62))\\,1.2)"
    elif layout == "right":
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
         f"x={x1}:y={52 if layout == 'top' else H - 70 - s1}")
    graph = (f"[0:v]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},"
             f"eq=contrast={1.16 * boost:.2f}:saturation={1.22 * boost:.2f}:brightness={0.06 * (boost - 1) - 0.02:.2f},"
             "unsharp=5:5:0.7,vignette=PI/5[b];"
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


THUMB_PROMPT = """You design YouTube thumbnails for a Russian psychology channel. Goal: a viewer stops scrolling because
of REAL curiosity, not a trick. Rules:
- strong emotion and a clear visual story in the frame (a person's face/gesture or a striking motif), high contrast;
- text: SHORT, big, easy to read — 2 lines, at most {max_words} Russian words total;
- the words raise a question / inner tension that THIS video really answers (no clickbait, no lies, no promises the
  script does not keep), they match the topic;
- different wording, idea and angle from our previous thumbnails; fits this video's own visual world.

{story}Title: {title}
Hook (first seconds): {hook}
What the video promises the viewer: {promise}
Visual world of the video: {world}
Previous thumbnail texts (do NOT repeat their wording or idea): {previous}
Candidate frames (index. narration at that moment):
{shots}

SCRIPT (the thumbnail must be honest to it):
{script}

Return JSON only: [{{"line1": "<1-3 Russian words, white>", "line2": "<1-3 Russian words, accent, the punch>",
"shot": <index of the best frame: a person/emotion or a strong motif, no text in frame>,
"emotion": "<the emotion this thumbnail triggers>",
"support": "<VERBATIM 5-15 word quote from the SCRIPT that this thumbnail's question is answered by>"}}] —
5 options, each with a different angle and a DIFFERENT frame (prefer frames with a person showing emotion)."""


VISION_PROMPT = """You are a demanding YouTube viewer scrolling past thumbnails. Judge THIS finished thumbnail
for a Russian psychology video. Title: «{title}». Thumbnail text: «{text}». Topic promise: {promise}

Return JSON only: {{"attention": <1-10: would you stop scrolling?>, "topic_match": <1-10: the image + text clearly fit
the topic and the text's emotion>, "emotion": "<what emotion the image itself shows>",
"problems": [<any of: "foreign_text" (readable names, badges, signs, captions or letters in the photo itself, NOT the
big thumbnail text), "logo", "alcohol", "face_covered" (the big text covers a face), "no_subject" (no person and no
clear meaningful motif), "off_topic", "low_quality", "misleading">],
"note": "<one short sentence>"}}"""
VISION_MIN = 6
VISION_HARD = {"foreign_text", "logo", "alcohol", "face_covered", "off_topic", "misleading", "low_quality"}


SCREEN_PROMPT = """You pick background frames for a YouTube thumbnail of a Russian psychology video.
Title: «{title}». The video promises: {promise}
For EACH image (Image 0..N) judge it as a thumbnail background (big text will be added on one side).
Return JSON array only: [{{"i": <image index>, "score": <1-10 thumbnail potential: a person with a visible, readable
emotion or a striking meaningful motif that fits THIS topic>, "person_emotion": <true/false>,
"see": "<what is in the frame, 6-12 words>", "problems": [<any of: "foreign_text" (readable names, badges, signs,
letters), "logo", "alcohol", "off_topic", "low_quality", "no_subject">]}}]"""
SCREEN_MAX = 16
SCREEN_MIN = 6


def source_of(ctx, sh: dict, work: Path) -> tuple[Path, float] | None:
    """Кадрдын булак клиби: жергиликтүү (s9) же кайра жүктөлгөн (thumbnail.yml auto)."""
    clip = ctx.path("clips", sh["file"])
    if clip.exists():
        return clip, float(sh.get("offset", 0.0)) + sh["dur"] / 2
    return clean_source([sh], sh["start"] + sh["dur"] / 2, work, stock=(getattr(ctx, "services", None) or {}).get("stock"))


def screen_frames(gem, ctx, cands: list[dict], title: str, promise: str, work: Path) -> list[dict]:
    """Кадрларды обложка катары АЛДЫН АЛА көрүп тандоо (себеби run #44891327839: Gemini кадрды көрбөй, сөзгө карап
    тандап, 5 вариант тең «темадан тышкары / адам жок / алкоголь» болуп четке кагылды).
    → жакшы кадрлар (баасы боюнча), ар биринде `_src` жана `_see`. Көрүү кызматы жок болсо — тизме өзгөрбөйт."""
    if not hasattr(gem, "judge_image"):
        return cands
    person = re.compile(r"\b(woman|man|girl|boy|person|people|face|portrait|couple|tired|sad|worried|thinking)\b", re.I)
    pool = sorted(cands, key=lambda s: (s.get("hero") not in ("silhouette", "back", "hands"),
                                        -bool(person.search(s.get("query") or "")),
                                        -(s.get("ai_score") or 0)))[:SCREEN_MAX]
    items, jpgs = [], []
    for sh in pool:
        src = source_of(ctx, sh, work)
        if not src:
            continue
        jpg = work / f"scr_{sh.get('i', 0)}.jpg"
        try:
            media.run(["ffmpeg", "-y", "-v", "error", "-ss", f"{src[1]:.2f}", "-i", str(src[0]), "-frames:v", "1",
                       "-vf", "scale=480:-2", "-q:v", "4", str(jpg)], "обложка кадрын тандоо")
        except Exception:
            continue
        items.append(dict(sh, _src=src))
        jpgs.append(jpg.read_bytes())
    if not items:
        return []
    r = None
    for _ in range(2):                     # 503/убактылуу ката — бир жолу кайра
        try:
            r = gem.judge_image(jpgs, SCREEN_PROMPT.format(title=title, promise=promise or "-"), purpose="thumbnail_frames")
            break
        except Exception as e:
            log = getattr(ctx, "log", print)
            log(f"   ⚠️ Кадрларды көрүү ишке ашкан жок: {type(e).__name__}: {str(e)[:100]}")
    if r is None:
        return items                       # көрүлбөгөн — ар бир даяр обложка кийин көрүүдөн өтүшү керек
    good = []
    for x in r if isinstance(r, list) else []:
        try:
            k = int(x.get("i"))
        except (TypeError, ValueError):
            continue
        if 0 <= k < len(items) and int(x.get("score") or 0) >= SCREEN_MIN and \
                not (set(map(str, x.get("problems") or [])) & VISION_HARD):
            good.append((int(x["score"]) + (2 if x.get("person_emotion") else 0), dict(items[k], _see=str(x.get("see", ""))[:120])))
    good.sort(key=lambda t: -t[0])
    return [g for _, g in good[:8]]


def vision_review(gem, path: Path, title: str, text: str, promise: str) -> dict | None:
    """Даяр обложканы Gemini көзү менен баалоо. Кызмат жок (тест) → None. Кызмат бар, бирок баа алынбаса →
    {"ok": False, "unavailable": True} — көрүлбөгөн обложка кабыл алынбайт (run #44892369934: 503'тон кийин
    көрүлбөгөн бүдөмүк обложка өтүп кеткен)."""
    if not hasattr(gem, "judge_image"):
        return None
    r = None
    for _ in range(2):
        try:
            r = gem.judge_image(path.read_bytes(), VISION_PROMPT.format(title=title, text=text, promise=promise or "-"),
                                purpose="thumbnail_review")
            break
        except Exception:
            continue
    if not isinstance(r, dict) or not isinstance(r.get("attention"), (int, float)):
        return {"ok": False, "unavailable": True, "attention": 0, "topic_match": 0, "problems": ["no_review"],
                "emotion": "", "note": "көрүү баасы алынган жок"}
    probs = [str(x) for x in (r.get("problems") or []) if str(x)]
    out = {"attention": int(r["attention"]), "topic_match": int(r.get("topic_match") or 0), "problems": probs,
           "emotion": str(r.get("emotion", ""))[:80], "note": str(r.get("note", ""))[:200]}
    out["ok"] = out["attention"] >= VISION_MIN and out["topic_match"] >= VISION_MIN and not (set(probs) & VISION_HARD)
    return out


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
    try:
        script = ctx.path("script", "script.txt").read_text(encoding="utf-8")
    except Exception:
        script = ""
    story_txt = ""
    try:                                   # кино-окуя: обложка — каармандын эмоциясы + негизги конфликт
        sd = json.loads(ctx.path("script", "story.json").read_text(encoding="utf-8"))
        story_txt = ("THIS IS A SHORT CINEMATIC FILM in a faceless style (the hero's face is never shown). The thumbnail shows the "
                     "HERO's emotion through body language, hands, silhouette or a key object, and the main conflict of "
                     "the story (" + sd["outline"].get("logline", "") + "). Hero: " + sd["hero"].get("descriptor", "") +
                     ". Director's thumbnail idea: " + (brief.get("director") or {}).get("thumbnail", "-") + "\n")
    except Exception:
        pass
    # бетсиз кино-стиль: обложкада да каарман (силуэт/артынан/колдор) — бөтөн адамдын бети эмес
    face_first = lambda s: (0 if s.get("hero") in ("silhouette", "back", "hands") and
                            s.get("continuity") in (None, "ok") else 1)
    cands = sorted([s for s in shots if s.get("source") != "gemini" and s.get("kind") == "video"],
                   key=lambda s: (face_first(s), -(s.get("ai_score") or 0)))[:24]
    cands.sort(key=lambda s: s["start"])
    text_at = lambda s: " ".join(w["w"] for w in words if w["e"] > s["start"] and w["s"] < s["end"])[:120]
    prev = [t for v, e in ctx.registry.get("videos", {}).items() if v != ctx.video_id
            for t in (e.get("thumbnail") or {}).get("texts", [])]
    prev_hashes = [h for v, e in ctx.registry.get("videos", {}).items() if v != ctx.video_id
                   for h in (e.get("thumbnail") or {}).get("hashes", [])]
    gem = None
    out_dir = ctx.path("thumbnails")
    out_dir.mkdir(exist_ok=True)
    try:
        gem = gemini_of(ctx)
        screened = screen_frames(gem, ctx, cands, title or meta.get("title", ""), meta.get("hook_promise", ""), out_dir)
        ctx.log(f"   🖼 Обложка үчүн кадрлар көрүлдү: {len(screened)}/{min(len(cands), SCREEN_MAX)} жарамдуу")
        if screened:
            cands = screened
    except Exception as e:
        ctx.log(f"   ⚠️ Обложка кадрлары көрүлгөн жок ({type(e).__name__})")

    def propose(feedback: list[str]) -> list:
        opts = []
        try:
            data = gem.json(THUMB_PROMPT.format(
                title=title or meta.get("title", ""), hook=meta.get("hook", ""), world=brief.get("world", ""),
                promise=meta.get("hook_promise", "") or "-", max_words=MAX_WORDS, story=story_txt,
                previous="; ".join(prev[-12:] + [f"REJECTED: {r}" for r in feedback[-6:]]) or "(none)",
                script=script[:9000],
                shots="\n".join(f"{k}. {text_at(s)}" + (f" [in frame: {s['_see']}]" if s.get("_see") else "")
                                 for k, s in enumerate(cands))), purpose="thumbnail", temperature=0.9)
            for o in data if isinstance(data, list) else []:
                k = int(o.get("shot", 0))
                if 0 <= k < len(cands) and str(o.get("line1", "")).strip():
                    opts.append((cands[k], str(o["line1"]).strip()[:22].upper(),
                                 str(o.get("line2", "")).strip()[:22].upper(),
                                 {"support": str(o.get("support", ""))[:200], "emotion": str(o.get("emotion", ""))[:60]}))
        except Exception as e:
            ctx.log(f"   ⚠️ Обложка тексти Gemini'ден келген жок ({type(e).__name__}) — hook'тон")
        if not opts and cands and not feedback:      # hook карточкасы — сценарийдин өзүнөн (чынчыл)
            hc = (meta.get("hook_card") or title or "").upper().split()[:MAX_WORDS]
            mid = max(1, len(hc) // 2)
            opts = [(cands[k * len(cands) // 3], " ".join(hc[:mid]), " ".join(hc[mid:]), {"source": "hook_card"})
                    for k in range(min(3, len(cands)))]
        return opts

    layout = choose_layout(ctx.registry, ctx.video_id, ctx.video_id + brief.get("name", ""))
    accent = choose_accent(ctx.registry, ctx.video_id,
                           brief.get("subtitles", {}).get("highlight", "#FFD21F").replace("#", "0x"))
    font_pref = "Montserrat" if brief.get("subtitles", {}).get("font", "Montserrat").startswith("Montserrat") else "DejaVu Sans"
    from .retention import quote_in_text

    made, rejected, qual = [], [], []
    n = 0
    for round_ in range(2):                  # 2-айлампа: четке кагылуу себептери Gemini'ге кайтарылат
        if made or (round_ and gem is None):
            break
        for sh, l1, l2, info in propose(rejected if round_ else []):
            n += 1
            k = n
            text = f"{l1} {l2}".strip()
            n_words = len(text.split())
            if check_unique([(0.0, l1, l2)], ctx.registry, ctx.video_id)[0][1]:
                rejected.append(f"«{text}»: жазуусу мурункуга окшош")
                continue
            if n_words > MAX_WORDS:
                rejected.append(f"«{text}»: жазуу узун ({n_words} сөз > {MAX_WORDS})")
                continue
            support_found = None
            if "support" in info:              # clickbait'ка каршы: обложканын суроосуна видеодо жооп барбы
                support_found = quote_in_text(info["support"], script)
                if not support_found:
                    rejected.append(f"«{text}»: видеодо жообу табылган жок (clickbait коркунучу)")
                    continue
            if len(made) >= 3:
                break
            got = sh.get("_src") or source_of(ctx, sh, out_dir)
            if not got:
                continue
            clip, at = got
            out = out_dir / f"{ctx.video_id}_thumb_{k}.jpg"
            make(clip, at, l1, l2, out, out_dir, accent=accent, layout=layout, font_pref=font_pref)
            q = quality(out)
            if not q["ok_image"]:              # бүдөмүк/өтө караңгы — контрастты күчөтүп бир жолу кайра
                make(clip, at, l1, l2, out, out_dir, accent=accent, layout=layout, font_pref=font_pref, boost=1.25)
                q = quality(out)
            qrow = {"text": text, "words": n_words, "contrast": q["contrast"], "brightness": q["brightness"],
                    "ok": q["ok_image"] and n_words <= MAX_WORDS, "emotion": info.get("emotion", ""),
                    "support": info.get("support", "")}
            if support_found is not None:
                qrow["support_found"] = support_found
            if not q["ok_image"]:
                rejected.append(f"«{text}»: контраст/жарык жетишсиз ({q['contrast']}, {q['brightness']})")
                continue
            vis = vision_review(gem, out, title or meta.get("title", ""), text, meta.get("hook_promise", ""))
            qrow["vision"] = vis
            if vis is not None and not vis["ok"]:
                rejected.append(f"«{text}»: көрүүчүнүн көзү менен өтпөдү (көңүл {vis['attention']}/10, тема "
                                f"{vis['topic_match']}/10, {vis['problems'] or '-'}: {vis['note'][:80]})")
                qrow["ok"] = False
                continue
            h = image_hash(out)
            if any(bin(int(h, 16) ^ int(p, 16)).count("1") <= 8 for p in prev_hashes):
                rejected.append(f"«{text}»: сүрөтү мурунку обложкага окшош")
                continue
            url = ctx.store.publish("Thumbnails", out, out.name) if ctx.store else None
            made.append({"file": out.name, "text": text, "shot": sh["i"], "hash": h, "url": url})
            qual.append(qrow)
    entry["thumbnail"] = {"texts": [m["text"] for m in made], "hashes": [m["hash"] for m in made], "quality": qual,
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
    if os.environ.get("THUMBS", "").strip().lower() == "auto":
        return main_auto(root, vid)
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


def main_auto(root: str, vid: str) -> int:
    """Даяр видеого обложканы жаңы эрежелер менен КАЙРА жасоо (видео өзгөрбөйт): Projects/<ID> Drive'дан алынат,
    сценарийдин hook/убадасы баалоонот (кайра жазылбайт), анан auto_thumbnails (чынчылдык + көрүү баасы)."""
    import json
    from types import SimpleNamespace

    from . import retention as rt
    from .config import load_config
    from .drive import DriveClient
    from .gemini import from_config
    from .stock import Stock
    from .storage import DriveStore

    drive = DriveClient.from_env()
    if drive is None:
        print("❌ GDRIVE_* жок")
        return 2
    store = DriveStore(drive, root)
    registry = store.load_registry()
    with tempfile.TemporaryDirectory() as d:
        work = Path(d) / vid
        if not store.pull_project(vid, work):
            print(f"❌ Projects/{vid} табылган жок")
            return 2
        cfg = load_config("motivation", drive_root=root)
        gem = from_config(cfg, log=print)
        script = (work / "script" / "script.txt").read_text(encoding="utf-8")
        meta_p = work / "script" / "meta.json"
        meta = json.loads(meta_p.read_text(encoding="utf-8"))
        if not (work / "script" / "retention.json").exists():
            rev = rt.review(gem, script, meta.get("title", ""), meta.get("hook_type", ""))
            loc = rt.local_checks(script)
            ret = {"local": loc, "review": rev, "problems": rt.problems(loc, rev), "rounds": 1, "post_hoc": True}
            ret["ok"] = not ret["problems"]
            (work / "script" / "retention.json").write_text(rt.dump(ret), encoding="utf-8")
            meta["hook_promise"] = rev.get("promise", "")
            meta_p.write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
            print(f"🎯 Hook/retention (даяр сценарий, кайра жазылбайт): hook {rev.get('hook_score')}/10 — "
                  f"{rev.get('hook_reason', '')[:160]}; финал {rev.get('ending_score')}/10; убада «{rev.get('promise', '')[:120]}» "
                  f"→ видеодо: {rev.get('promise_delivered')} «{rev.get('delivered_quote', '')[:100]}»; "
                  f"жалган убада {rev.get('false_promises') or '-'}; кемчилик {ret['problems'] or '-'}")
        stock = Stock(os.environ.get("PIXABAY_API_KEY", ""), os.environ.get("PEXELS_API_KEY"))
        ctx = SimpleNamespace(video_id=vid, registry=registry, store=store, cfg=cfg,
                              services={"gemini": gem, "stock": stock}, path=lambda *p: work.joinpath(*p), log=print)
        old = (registry.get("videos", {}).get(vid) or {}).get("thumbnail")
        th = auto_thumbnails(ctx, meta.get("title", ""))
        th["previous_attempt"] = {k: (old or {}).get(k) for k in ("texts", "layout", "accent")}
        for q in th.get("quality", []):
            print(f"   ✓ «{q['text']}»: контраст {q['contrast']}, {q['words']} сөз, видеодо жообу: {q.get('support_found')} "
                  f"«{q.get('support', '')[:80]}», көрүү: {q.get('vision')}")
        vc = rt.viewer_checklist(json.loads((work / "script" / "retention.json").read_text(encoding="utf-8")),
                                 {}, th, None)
        for x in vc:
            print(f"   {x['question']} {'✅' if x['ok'] else ('❌' if x['ok'] is False else '—')} {x['note'][:300]}")
        store.save_registry(registry)
        files = [work / "thumbnails" / f for f in th.get("files", [])]
        if files:
            sh = sheet(files, work / "thumbnails" / f"{vid}_thumbs.jpg")
            print(f"📋 БААРЫ БИР БАРАКТА: {store.publish('Thumbnails', sh, sh.name)}")
    return 0 if th.get("files") else 3


if __name__ == "__main__":
    sys.exit(main())
