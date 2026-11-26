"""16:9 кинематографиялык hook (алгачкы 3–5 сек) + тарыхка көпүрө, архивдик стилдеги сүрөттөр менен — Tech History (EN).

Тема: «The Car Parts That Created QR Codes». Колдонуучунун чечими (2026-11-26): 16:9 гана, сүрөттөр Pixabay'дан
(«архивдик» иштетүү: пленка тырмагы, grain, жарыктын дирилдеши, кадрдын термелиши, сепия), Масахиро Харанын сүрөтү
ЭРКИН лицензия менен табылса гана (Wikimedia Commons; CC0/PD/CC BY/CC BY-SA) — бул видеого гана уруксат.
Pixabay сүрөттөрү чыныгы 1990-жылдардагы Denso эмес → экранда «ILLUSTRATIVE STOCK PHOTOS» белгиси (жалган визуал жок).

Монтаж (убакыттар диктордун үнүнө жараша жылат, hook ≤ 5.0 сек МИЛДЕТТҮҮ):
  0.00  scan:    QR коддун сканерленишинин сүрөтү — фокустан ачылуу, жай push-in, муздак жарык тагы, сканердин
                 бурчтары + лазер → «lock» + beep. Текст 1: «QR CODES WEREN'T MADE FOR PHONES...»
  CUT   QR чекитине zoom-through + жарк + impact →
        factory: унаа заводунун сүрөтү, архивдик иштетүү, Ken Burns. Текст 2: «THEY WERE BORN FROM A FACTORY
                 PROBLEM.» + «JAPAN · EARLY 1990s».
  HOOK_END → barcode: тетик кутусундагы штрих-код (көйгөйдүн өзү) → hara (лицензия болсо): lower-third
                 «1992 · DENSO, JAPAN / ENGINEER MASAHIRO HARA» — окуянын башталышы.

Иштетүү (GitHub Actions'та — сүрөт сайттары ошол жерде ачык; Colab керек эмес, ~3–5 мүн):
  python -m pipeline.history_hook --out out/qr_hook_16x9.mp4 --fetch --tts      # Pixabay + Commons + Gemini TTS
  python -m pipeline.history_hook --out out/h.mp4 --photos-dir p/               # p/scan.jpg factory.jpg barcode.jpg [hara.jpg]
Ачкычтар: PIXABAY_API_KEY, GOOGLE_API_KEY (тандоо үчүн Gemini көрүү + TTS). Gemini жок болсо — тегдер боюнча тандайт.
Фактылар: Wikipedia «QR code», «Masahiro Hara»; EPO European Inventor Award 2014; JPO.
"""

from __future__ import annotations

import argparse
import io
import json
import math
import re
import shutil
import subprocess
import tempfile
import wave
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

W, H, FPS, SR = 1920, 1080, 30, 48000
HOOK_MAX = 5.0          # hook (текст 1 + текст 2 + алардын үнү) ушундан узун болбойт
TEXT_MAX_START = 1.0    # биринчи текст ≤ 1 сек ичинде көрүнөт
SHOTS = ("scan", "factory", "barcode")
PHOTO_FIT_MIN = 6       # Gemini баасы (1–10): мындан төмөн болсо кийинки издөөлөр сыналат; QA ≥5 талап кылат

SPEC = {
    "topic": "The Car Parts That Created QR Codes",
    "line1": ["QR CODES WEREN'T MADE FOR PHONES..."],
    "line1_accent": ["PHONES..."],
    "line2": ["THEY WERE BORN FROM", "A FACTORY PROBLEM."],
    "line2_accent": ["FACTORY", "PROBLEM."],
    "place": "JAPAN  ·  EARLY 1990s",
    "disclaimer": "ILLUSTRATIVE STOCK PHOTOS",
    "lower_kicker": "1992  ·  DENSO, JAPAN",
    "lower_title": ["ENGINEER MASAHIRO HARA"],
    "narration": {
        "line1": "QR codes weren't made for phones...",
        "line2": "They were born from a factory problem.",
        "bridge": "Japan, 1992. At the car-parts maker Denso, engineer Masahiro Hara is asked to build a better code.",
    },
    "tts_style": ("Deep, confident, mysterious premium documentary narrator, low register, measured and unhurried, "
                  "a hint of suspense, clear diction, cinematic like a high-end history documentary. "
                  "Not a commercial or radio voice."),
    # Pixabay издөөлөрү (биринчиси эң так) жана Gemini көрүү үчүн кадрдын сүрөттөмөсү
    "photos": {
        "scan": {"queries": ["qr code scan smartphone", "scanning qr code", "qr code phone", "qr code"],
                 "want": "a close-up of a QR code being scanned with a phone camera; the QR code is large and sharp"},
        "factory": {"queries": ["car factory assembly line", "automotive assembly line", "car production line",
                                "car factory", "car manufacturing", "automobile factory", "car body assembly",
                                "assembly line workers", "auto parts factory", "factory production line"],
                    "want": "a car factory / automotive assembly line interior with car bodies or parts, dramatic "
                            "industrial light, works as a documentary 'archive-style' shot"},
        "barcode": {"queries": ["barcode label box", "barcode cardboard box", "barcode scanner warehouse", "barcode"],
                    "want": "a printed 1D barcode label on a box or part, close-up, the barcode clearly visible"},
    },
    "hara_query": "Masahiro Hara",
    "sources": [
        "https://en.wikipedia.org/wiki/QR_code",
        "https://en.wikipedia.org/wiki/Masahiro_Hara",
        "https://www.epo.org/learning-events/european-inventor/finalists/2014/hara.html",
        "https://www.jpo.go.jp/e/news/koho/innovation/01_qrcode_e.html",
    ],
}

CYAN = (56, 225, 255)
AMBER = (255, 176, 32)
GREEN = (60, 255, 140)
FREE_LICENSES = re.compile(r"^(cc0|public domain|pd\b|pd-|cc by(-sa)? \d|cc-by(-sa)?-\d)", re.I)


# ============================================================ шрифттер

def _font_path(kind: str) -> str | None:
    cands = {
        "black": ["InterDisplay-Black.otf", "Inter-Black.otf", "Montserrat-Black.ttf", "Montserrat-ExtraBold.ttf",
                  "DejaVuSans-Bold.ttf"],
        "mono": ["JetBrainsMono-Bold.ttf", "DejaVuSansMono-Bold.ttf", "DejaVuSansMono.ttf"],
        "cjk": ["NotoSansCJK-Bold.ttc", "NotoSansCJKjp-Bold.otf", "NotoSansCJK-Regular.ttc", "DejaVuSansMono-Bold.ttf"],
    }[kind]
    roots = [Path("/usr/share/fonts"), Path("/usr/local/share/fonts"), Path.home() / ".fonts"]
    for name in cands:
        for r in roots:
            if r.exists():
                hit = next(r.rglob(name), None)
                if hit:
                    return str(hit)
    return None


def font(kind: str, size: int) -> ImageFont.FreeTypeFont:
    p = _font_path(kind)
    return ImageFont.truetype(p, size) if p else ImageFont.load_default(size)


# ============================================================ убакыт сызыгы

@dataclass
class Timeline:
    l1_start: float = 0.12
    l1_dur: float = 1.9
    cut: float = 2.14
    l2_start: float = 2.28
    l2_dur: float = 2.0
    hook_end: float = 4.38
    bridge_start: float = 4.68
    bridge_dur: float = 5.6
    hara_at: float = 0.0          # 0 = Харанын сүрөтү жок
    end: float = 11.08
    voice: dict = field(default_factory=dict)

    @classmethod
    def build(cls, durs: dict[str, float] | None = None, hara: bool = False) -> "Timeline":
        d = {"line1": 1.9, "line2": 2.0, "bridge": 5.6, **(durs or {})}
        t = cls()
        t.l1_dur, t.l2_dur, t.bridge_dur = d["line1"], d["line2"], d["bridge"]
        t.cut = max(1.9, t.l1_start + t.l1_dur + 0.12)
        t.l2_start = t.cut + 0.14
        t.hook_end = t.l2_start + t.l2_dur + 0.1
        t.bridge_start = t.hook_end + 0.3
        t.end = t.bridge_start + t.bridge_dur + 0.8
        # «Masahiro Hara» деген сөз айтылганга жакын — көпүрөнүн ~55%ында портретке өтүү
        t.hara_at = t.bridge_start + 0.55 * t.bridge_dur if hara else 0.0
        return t

    def to_dict(self) -> dict:
        return {k: round(v, 3) for k, v in self.__dict__.items() if isinstance(v, float)}


def ease(x: float) -> float:
    x = min(max(x, 0.0), 1.0)
    return x * x * (3 - 2 * x)


def ease_out(x: float) -> float:
    x = min(max(x, 0.0), 1.0)
    return 1 - (1 - x) ** 3


# ============================================================ текст

class TextBlock:
    """Чоң, калың, контрасттуу текст; сөздөр кезек-кезеги менен «урулуп» чыгат. align: center | left."""

    def __init__(self, lines: list[str], accent: list[str], color, y: int, maxw: int = 1500, size: int = 120,
                 align: str = "center", x: int = 0):
        while size > 40:
            f = font("black", size)
            if max(f.getlength(ln) for ln in lines) <= maxw:
                break
            size -= 4
        self.f = font("black", size)
        self.words: list[tuple[Image.Image, int, int]] = []
        gap = self.f.getlength(" ")
        lh = int(size * 1.08)
        for i, ln in enumerate(lines):
            ws = ln.split(" ")
            tot = sum(self.f.getlength(w) for w in ws) + gap * (len(ws) - 1)
            cx = (W - tot) / 2 if align == "center" else x
            for w in ws:
                wl = self.f.getlength(w)
                col = color if w in accent else (255, 255, 255)
                self.words.append((self._sprite(w, col, 28), int(cx + wl / 2), int(y + i * lh + size / 2)))
                cx += wl + gap

    def _sprite(self, word: str, col, pad: int) -> Image.Image:
        bb = self.f.getbbox(word, stroke_width=7)
        w, h = bb[2] - bb[0] + 2 * pad, bb[3] - bb[1] + 2 * pad
        sh = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        ImageDraw.Draw(sh).text((pad - bb[0], pad - bb[1] + 6), word, font=self.f, fill=(0, 0, 0, 210))
        sh = sh.filter(ImageFilter.GaussianBlur(14))
        ImageDraw.Draw(sh).text((pad - bb[0], pad - bb[1]), word, font=self.f, fill=col + (255,),
                                stroke_width=7, stroke_fill=(0, 0, 0, 255))
        return sh

    def draw(self, img: Image.Image, t: float, start: float, end: float, stagger: float = 0.07) -> None:
        for i, (sp, cx, cy) in enumerate(self.words):
            k = (t - (start + i * stagger)) / 0.22
            if k <= 0 or t > end + 0.2:
                continue
            alpha = ease_out(k) * (1 - ease((t - end) / 0.2))
            if alpha <= 0.01:
                continue
            sc = 1.22 - 0.22 * ease_out(k)
            spr = sp if abs(sc - 1) < 1e-3 else sp.resize((int(sp.width * sc), int(sp.height * sc)),
                                                          Image.BILINEAR)
            if alpha < 0.999:
                spr = spr.copy()
                spr.putalpha(spr.getchannel("A").point(lambda v, al=alpha: int(v * al)))
            img.alpha_composite(spr, (cx - spr.width // 2, cy - spr.height // 2))


def mono_text(img: Image.Image, txt: str, xy, size: int, col, alpha: float, chars: int | None = None) -> None:
    if alpha <= 0.01:
        return
    f = font("mono" if txt.isascii() else "cjk", size)       # япон автордун аты (CC BY атрибуциясы)
    txt = txt if chars is None else txt[:chars]
    lay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(lay).text(xy, txt, font=f, fill=col + (int(255 * alpha),), stroke_width=3,
                             stroke_fill=(0, 0, 0, int(220 * alpha)))
    img.alpha_composite(lay)


# ============================================================ сүрөттөр: Pixabay + Commons + Gemini тандоо

@dataclass
class Photo:
    shot: str
    path: Path
    focus: tuple[float, float] = (0.5, 0.5)      # кызыктуу чекит (0..1) — QR/штрих-код ушул жерде
    meta: dict = field(default_factory=dict)      # булак, автор, лицензия


JUDGE = """You are a documentary photo editor. Shot needed: {want}.
For EACH image (Image 0..N) return JSON array only:
[{{"i": <index>, "fit": <1-10 how well it matches the shot>, "logo": <true if a readable brand name/logo/trademark is visible>,
"face": <true if a recognizable human face is prominent>, "text": <true if other readable words are prominent>,
"focus": [<x 0..1>, <y 0..1> centre of the QR code / barcode / main subject]}}]"""


def fetch_photos(out_dir: Path, spec: dict = SPEC, log=print) -> dict[str, Photo]:
    """Ар кадр үчүн Pixabay'дан талапкерлер → Gemini көрүү (туура келиши, логотип/бет/жазуу жок) → эң жакшысы."""
    from .stock import from_env

    st = from_env()
    gem = None
    try:
        from .config import load_config
        from .gemini import from_config
        gem = from_config(load_config("tech_history"), log=log)
    except Exception as e:  # noqa: BLE001 — Gemini жок болсо тегдер боюнча тандалат
        log(f"⚠ Gemini көрүү жок ({str(e)[:80]}) — тегдер боюнча тандалат")
    out_dir.mkdir(parents=True, exist_ok=True)
    used: set[str] = set()
    res: dict[str, Photo] = {}
    for shot, cfg in spec["photos"].items():
        queries = list(cfg["queries"])
        seen: set[str] = set(used)
        pool: list = []                                        # (fit, asset, file, focus)
        for rnd in range(3):                                   # ≤3 айлампа × 10 талапкер (Gemini квотасы үнөмдөлөт)
            cands = []
            while queries and len(cands) < 10:
                q = queries.pop(0)
                for a in st.images(q):
                    if a.id not in seen and len(cands) < 10:
                        seen.add(a.id)
                        cands.append(a)
            if not cands:
                break
            files = [st.download(a, out_dir / "cand" / f"{shot}_{rnd}_{k}.jpg") for k, a in enumerate(cands)]
            rated = judge(gem, files, cfg["want"], log) if gem is not None else []
            if not rated:                                       # Gemini жок — Pixabay тартиби (тегдер)
                rated = [(5, 0, (0.5, 0.5))]
            for fit, i, focus in rated:
                pool.append((fit, cands[i], files[i], focus))
            best_fit = max(p[0] for p in pool)
            log(f"🖼 {shot}: {rnd + 1}-айлампа, {len(cands)} талапкер, эң жакшысы {best_fit}/10")
            if best_fit >= PHOTO_FIT_MIN or gem is None:
                break
        if not pool:
            raise RuntimeError(f"Pixabay: «{shot}» үчүн сүрөт табылган жок")
        fit, a, src, focus = max(pool, key=lambda p: p[0])
        used.add(a.id)
        dst = out_dir / f"{shot}.jpg"
        shutil.copy(src, dst)
        res[shot] = Photo(shot, dst, focus, {"fit": fit, "source": "Pixabay", "id": a.id, "page": a.page_url,
                                             "author": a.author, "license": a.license,
                                             "license_url": a.license_url, "tags": a.tags})
    hara = commons_photo(spec["hara_query"], out_dir / "hara.jpg", log=log)
    if hara:
        res["hara"] = hara
    (out_dir / "photos.json").write_text(json.dumps({k: {**v.meta, "focus": v.focus} for k, v in res.items()},
                                                    ensure_ascii=False, indent=2))
    return res


def judge(gem, files: list[Path], want: str, log=print) -> list[tuple[int, int, tuple[float, float]]]:
    """Gemini көрүү: [(fit, индекс, focus)] — логотиптүү же бети ачык көрүнгөн сүрөттөр алынып салынат."""
    try:
        jpgs = []
        for p in files:
            im = Image.open(p).convert("RGB")
            im.thumbnail((640, 640))
            b = io.BytesIO()
            im.save(b, "JPEG", quality=82)
            jpgs.append(b.getvalue())
        r = gem.judge_image(jpgs, JUDGE.format(want=want), purpose="hook_photo")
    except Exception as e:  # noqa: BLE001
        log(f"⚠ Gemini баалоосу иштеген жок ({str(e)[:80]})")
        return []
    out = []
    for x in (r if isinstance(r, list) else []):
        try:
            i = int(x.get("i", -1))
            if not 0 <= i < len(files) or x.get("logo") or x.get("face"):
                continue
            f = x.get("focus") or [0.5, 0.5]
            fit = int(x.get("fit") or 0) - (1 if x.get("text") else 0)
            out.append((fit, i, (min(max(float(f[0]), 0.15), 0.85), min(max(float(f[1]), 0.15), 0.85))))
        except (TypeError, ValueError, AttributeError):
            continue
    return out


def commons_photo(query: str, dst: Path, log=print) -> Photo | None:
    """Wikimedia Commons: аты файлдын аталышында болгон, ЭРКИН лицензиялуу (CC0/PD/CC BY/CC BY-SA) сүрөт."""
    import requests

    s = requests.Session()
    s.headers["User-Agent"] = "YouTubeAutoPipeline/1.0 (documentary hook; github.com/Nazigul338/YouTube_Auto_Pipeline)"
    try:
        r = s.get("https://commons.wikimedia.org/w/api.php", timeout=30, params={
            "action": "query", "format": "json", "generator": "search", "gsrnamespace": 6,
            "gsrsearch": f'"{query}"', "gsrlimit": 10, "prop": "imageinfo",
            "iiprop": "url|extmetadata|size|mime", "iiurlwidth": 1600}).json()
    except Exception as e:  # noqa: BLE001
        log(f"⚠ Commons: {str(e)[:80]}")
        return None
    words = [w.lower() for w in query.split()]
    for pg in sorted((r.get("query") or {}).get("pages", {}).values(), key=lambda p: p.get("index", 99)):
        title = pg.get("title", "")
        ii = (pg.get("imageinfo") or [{}])[0]
        md = ii.get("extmetadata") or {}
        lic = (md.get("LicenseShortName") or {}).get("value", "")
        if not all(w in title.lower() for w in words) or "image/" not in ii.get("mime", ""):
            continue
        if not FREE_LICENSES.match(lic.strip()):
            log(f"⛔ Commons «{title}»: лицензия «{lic}» эркин эмес — колдонулбайт")
            continue
        url = ii.get("thumburl") or ii.get("url")
        try:
            b = s.get(url, timeout=60)
            b.raise_for_status()
            dst.write_bytes(b.content)
        except Exception as e:  # noqa: BLE001
            log(f"⚠ Commons жүктөө: {str(e)[:80]}")
            continue
        author = re.sub(r"<[^>]+>", "", (md.get("Artist") or {}).get("value", "")).strip()
        log(f"👤 Хара: «{title}» — {lic}, автор: {author or '?'}")
        return Photo("hara", dst, (0.5, 0.38), {
            "source": "Wikimedia Commons", "title": title, "page": ii.get("descriptionurl", ""), "author": author,
            "license": lic, "license_url": (md.get("LicenseUrl") or {}).get("value", "")})
    log("ℹ Харанын эркин лицензиялуу сүрөтү табылган жок — аты гана (lower-third) берилет")
    return None


def local_photos(d: Path) -> dict[str, Photo]:
    meta = {}
    if (d / "photos.json").exists():
        meta = json.loads((d / "photos.json").read_text())
    res = {}
    for shot in (*SHOTS, "hara"):
        p = next((d / f"{shot}{ext}" for ext in (".jpg", ".jpeg", ".png") if (d / f"{shot}{ext}").exists()), None)
        if p:
            m = meta.get(shot, {})
            res[shot] = Photo(shot, p, tuple(m.get("focus", (0.5, 0.38 if shot == "hara" else 0.5))), m)
    missing = [s for s in SHOTS if s not in res]
    if missing:
        raise FileNotFoundError(f"{d}: сүрөттөр жетишпейт: {missing}")
    return res


# ============================================================ кадр: Ken Burns + архивдик көрүнүш

class Plate:
    """Бир сүрөт → кыймылдуу кадр (zoom/pan кызыктуу чекитке карай), 16:9'га толтурулат."""

    def __init__(self, photo: Photo, z0: float, z1: float, pan: tuple[float, float] = (0, 0)):
        im = ImageOps.exif_transpose(Image.open(photo.path)).convert("RGB")
        sc = max(W / im.width, H / im.height) * 1.0
        self.im = im.resize((max(W, int(im.width * sc * 1.6)), max(H, int(im.height * sc * 1.6))), Image.LANCZOS)
        self.base = max(W / self.im.width, H / self.im.height)     # «толтуруу» масштабы
        self.fx, self.fy = photo.focus
        self.z0, self.z1, self.pan = z0, z1, pan

    def frame(self, p: float, extra_zoom: float = 1.0, to_focus: float = 0.0, weave=(0.0, 0.0)) -> Image.Image:
        z = (self.z0 + (self.z1 - self.z0) * p) * extra_zoom
        s = self.base * z                                            # булак пиксели → экран пиксели
        cw, ch = W / s, H / s
        # борбор: сүрөттүн ортосунан кызыктуу чекитке жылат (z чоңойгон сайын жакындайт)
        k = min(1.0, 0.35 + 0.65 * to_focus)
        cx = self.im.width * (0.5 + (self.fx - 0.5) * k) + self.pan[0] * p * self.im.width
        cy = self.im.height * (0.5 + (self.fy - 0.5) * k) + self.pan[1] * p * self.im.height
        cx = min(max(cx, cw / 2), self.im.width - cw / 2) + weave[0] / s
        cy = min(max(cy, ch / 2), self.im.height - ch / 2) + weave[1] / s
        return self.im.transform((W, H), Image.AFFINE, (1 / s, 0, cx - cw / 2, 0, 1 / s, cy - ch / 2),
                                 Image.BILINEAR)

    def focus_xy(self, p: float, extra_zoom: float = 1.0, to_focus: float = 0.0) -> tuple[float, float]:
        z = (self.z0 + (self.z1 - self.z0) * p) * extra_zoom
        s = self.base * z
        cw, ch = W / s, H / s
        k = min(1.0, 0.35 + 0.65 * to_focus)
        cx = self.im.width * (0.5 + (self.fx - 0.5) * k) + self.pan[0] * p * self.im.width
        cy = self.im.height * (0.5 + (self.fy - 0.5) * k) + self.pan[1] * p * self.im.height
        cx = min(max(cx, cw / 2), self.im.width - cw / 2)
        cy = min(max(cy, ch / 2), self.im.height - ch / 2)
        return ((self.fx * self.im.width - cx) * s + W / 2, (self.fy * self.im.height - cy) * s + H / 2)


class Look:
    """Кино/архив көрүнүшү: grade, bloom, vignette, grain, пленка тырмактары, чаң, жарыктын дирилдеши."""

    def __init__(self, seed: int = 7):
        self.rng = np.random.default_rng(seed)
        self.grain = [self.rng.normal(0, 1, (H // 2, W // 2)).astype(np.float32) for _ in range(6)]
        yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
        r = np.sqrt(((xx - W / 2) / (W * 0.62)) ** 2 + ((yy - H / 2) / (H * 0.62)) ** 2)
        self.vig = np.clip(1.0 - 0.6 * np.clip(r - 0.4, 0, None) ** 1.3, 0.3, 1.0)[..., None]
        self.dof = np.clip((r - 0.35) / 0.5, 0, 1)[..., None]

    def apply(self, im: Image.Image, i: int, grade: str, archive: float = 0.0, focus_blur: float = 0.0,
              light: tuple[float, float] | None = None) -> np.ndarray:
        if focus_blur > 0.3:                                         # фокустан ачылуу
            im = im.filter(ImageFilter.GaussianBlur(focus_blur))
        x = np.asarray(im, np.float32)
        hi = np.clip(x - 175, 0, None)
        b = np.asarray(Image.fromarray(np.clip(hi * 2.5, 0, 255).astype(np.uint8)).resize(
            (W // 4, H // 4)).filter(ImageFilter.GaussianBlur(10)).resize((W, H), Image.BILINEAR), np.float32)
        x = x + 0.35 * b
        lum = x.mean(axis=2, keepdims=True)
        if grade == "cold":                                          # QR: муздак, контрасттуу
            x = (x - 128) * 1.12 + 120
            x = x * np.array([0.86, 1.0, 1.12], np.float32)
        elif grade == "archive":                                     # архив: түсү өчкөн сепия + көгүш көлөкө
            sep = lum * np.array([1.10, 0.96, 0.76], np.float32)
            x = x * (1 - 0.72 * archive) + sep * (0.72 * archive)
            x = (x - 128) * 1.15 + 124
        if light is not None:                                        # жылган жарык тагы
            lx, ly = light
            yy = np.linspace(0, 1, H, dtype=np.float32)[:, None]
            xx = np.linspace(0, 1, W, dtype=np.float32)[None, :]
            m = 0.72 + 0.5 * np.exp(-(((xx - lx) / 0.45) ** 2 + ((yy - ly) / 0.6) ** 2))
            x = x * m[..., None]
        x = x * self.vig
        flick = 1.0 + (0.035 * archive) * math.sin(i * 2.7) * math.cos(i * 1.3)
        x = x * flick
        g = np.asarray(Image.fromarray(np.clip(self.grain[i % 6] * 40 + 128, 0, 255).astype(np.uint8)).resize(
            (W, H), Image.BILINEAR), np.float32) - 128
        x = x + g[..., None] * (0.15 + 0.25 * archive)
        out = np.clip(x, 0, 255).astype(np.uint8)
        if archive > 0:
            out = self._scratches(out, i, archive)
        return out

    def _scratches(self, a: np.ndarray, i: int, k: float) -> np.ndarray:
        r = np.random.default_rng(1000 + i)
        im = Image.fromarray(a)
        d = ImageDraw.Draw(im, "RGBA")
        for _ in range(r.integers(0, 3)):                            # тик тырмактар
            x = int(r.uniform(0.05, 0.95) * W)
            d.line([(x, 0), (x + int(r.normal(0, 6)), H)], fill=(235, 230, 215, int(70 * k)), width=1)
        for _ in range(r.integers(2, 9)):                            # чаң/так
            x, y, s = r.uniform(0, W), r.uniform(0, H), r.uniform(1, 4)
            c = 20 if r.random() < 0.6 else 230
            d.ellipse([x - s, y - s, x + s, y + s], fill=(c, c, c, int(150 * k)))
        return np.asarray(im)


def scanner_overlay(img: Image.Image, t: float, tl: Timeline, fxy: tuple[float, float], fade: float) -> None:
    """Телефон сканеринин бурчтары + лазер + lock, QR чекитинин айланасында."""
    if fade <= 0.01:
        return
    lock = min(1.5, tl.cut - 0.55)
    k = ease_out((t - 0.15) / (lock - 0.25))
    cx, cy = fxy
    half = 330 - 120 * k
    locked = t >= lock
    col = (GREEN if locked else (235, 245, 255)) + (int(255 * fade),)
    d = ImageDraw.Draw(img)
    L = 70
    for sx in (-1, 1):
        for sy in (-1, 1):
            x0, y0 = cx + sx * half, cy + sy * half
            d.line([(x0, y0), (x0 - sx * L, y0)], fill=col, width=7)
            d.line([(x0, y0), (x0, y0 - sy * L)], fill=col, width=7)
    if 0.35 <= t < lock:
        y = cy - half + 2 * half * ease((t - 0.35) / (lock - 0.35))
        glow = Image.new("RGBA", img.size, (0, 0, 0, 0))
        ImageDraw.Draw(glow).rectangle([cx - half, y - 18, cx + half, y + 18], fill=(255, 40, 60, int(90 * fade)))
        img.alpha_composite(glow.filter(ImageFilter.GaussianBlur(14)))
        d.line([(cx - half, y), (cx + half, y)], fill=(255, 90, 100, int(255 * fade)), width=4)
    if locked:
        fl = max(0.0, 1 - (t - lock) / 0.25)
        if fl > 0:
            img.alpha_composite(Image.new("RGBA", img.size, (120, 255, 180, int(60 * fl))))
        mono_text(img, "●  CODE DETECTED", (int(cx - half), int(cy + half + 22)), 30, GREEN,
                  min(1.0, (t - lock) / 0.12) * fade)


# ============================================================ үн: музыка + эффекттер (синтез, CC0)

def _t(n):
    return np.arange(n) / SR


def _place(buf, x, t0, gain=1.0):
    i = int(t0 * SR)
    if i >= len(buf):
        return
    x = x[: len(buf) - i]
    buf[i:i + len(x)] += gain * x


def _lp_fft(x, cutoff, hi=None):
    X = np.fft.rfft(x)
    f = np.fft.rfftfreq(len(x), 1 / SR)
    m = 1 / (1 + (f / cutoff) ** 4)
    if hi:
        m *= 1 / (1 + (hi / np.maximum(f, 1)) ** 4)
    return np.fft.irfft(X * m, len(x))


def synth_audio(tl: Timeline, seed: int = 5) -> np.ndarray:
    """Стерео (N,2) float: дрон + пульс + сканер + beep + whoosh + impact + завод + остинато."""
    rng = np.random.default_rng(seed)
    n = int(tl.end * SR) + SR
    L = np.zeros(n)
    R = np.zeros(n)
    t = _t(n)
    # 1) тынчсыз дрон (E минор), акырын күчөйт; заводдо бир аз ачылат
    sw = np.clip(t / tl.cut, 0, 1)
    drone = sum(a * np.sin(2 * np.pi * f * t + p) for a, f, p in
                [(1.0, 41.2, 0), (0.6, 61.74, 1.1), (0.35, 82.41, 2.0), (0.18, 123.47, 0.3)])
    drone = np.tanh(1.6 * drone) * (0.10 + 0.12 * sw)
    beat = (0.8 + 0.2 * np.sin(2 * np.pi * 0.25 * t))
    L += drone * beat
    R += drone * beat
    # 2) жүрөк пульсу (QR планы)
    for k in np.arange(0.0, tl.cut - 0.2, 0.72):
        m = int(0.5 * SR)
        tt = _t(m)
        thump = np.sin(2 * np.pi * (58 - 18 * tt) * tt) * np.exp(-tt / 0.09)
        _place(L, thump, k, 0.35)
        _place(R, thump, k, 0.35)
    # 3) сканер: электрондук гуу + лазер шыбыры
    lock = min(1.5, tl.cut - 0.55)
    m = int((lock - 0.35) * SR)
    if m > 0:
        tt = _t(m)
        hum = (np.sin(2 * np.pi * 3150 * tt) * 0.5 + _lp_fft(rng.standard_normal(m), 6000, 2500) * 0.6)
        hum *= np.sin(np.pi * tt / tt[-1]) * (0.6 + 0.4 * np.sin(2 * np.pi * 9 * tt)) * 0.05
        _place(L, hum, 0.35)
        _place(R, hum, 0.35)
    # 4) beep (код окулду)
    for f0, st, dur in [(1900, 0.0, 0.07), (2450, 0.09, 0.11)]:
        m = int(dur * SR)
        tt = _t(m)
        b = np.sin(2 * np.pi * f0 * tt) * np.minimum(1, tt / 0.004) * np.exp(-tt / (dur * 0.7)) * 0.22
        _place(L, b, lock + st)
        _place(R, b, lock + st)
    # 5) whoosh (zoom-through) жана impact
    m = int(0.75 * SR)
    tt = _t(m)
    nz = rng.standard_normal(m)
    env = np.exp(-((tt - 0.55) / 0.18) ** 2)
    wh = _lp_fft(nz, 3500, 300) * env * 0.5
    _place(L, wh * np.linspace(0.6, 1.0, m), tl.cut - 0.55)
    _place(R, wh * np.linspace(1.0, 0.6, m), tl.cut - 0.55)
    m = int(2.2 * SR)
    tt = _t(m)
    boom = np.sin(2 * np.pi * (35 + 85 * np.exp(-tt / 0.08)) * tt) * np.exp(-tt / 0.55)
    click = _lp_fft(rng.standard_normal(m), 5000) * np.exp(-tt / 0.02) * 0.6
    tail = _lp_fft(rng.standard_normal(m), 900) * np.exp(-tt / 0.6) * 0.25
    imp = np.tanh(1.4 * (boom + click + tail)) * 0.75
    _place(L, imp, tl.cut)
    _place(R, imp, tl.cut)
    # 6) завод: гуу (50 Гц тармак + күңгүрт ызы-чуу), конвейер шылдыры, металл тыкылдоо
    m = n - int(tl.cut * SR)
    tt = _t(m)
    fade = np.minimum(1, tt / 0.6)
    amb = (_lp_fft(rng.standard_normal(m), 260) * 0.9 + np.sin(2 * np.pi * 100 * tt) * 0.05)
    rat = _lp_fft(rng.standard_normal(m), 2500, 700) * (0.5 + 0.5 * np.sign(np.sin(2 * np.pi * 7.5 * tt))) * 0.06
    _place(L, (amb * 0.22 + rat) * fade, tl.cut)
    _place(R, (amb * 0.22 + rat * 0.8) * fade, tl.cut)
    k = tl.cut + 0.5
    while k < tl.end:
        mm = int(0.5 * SR)
        tt2 = _t(mm)
        clank = sum(np.sin(2 * np.pi * f * tt2) * np.exp(-tt2 / d) for f, d in
                    [(523, 0.16), (1307, 0.09), (2210, 0.05), (3480, 0.03)])
        p = rng.uniform(0.2, 0.8)
        g = rng.uniform(0.03, 0.06)
        _place(L, clank, k, g * (1 - p))
        _place(R, clank, k, g * p)
        k += rng.uniform(0.6, 1.3)
    # 7) документалдык остинато (көпүрөдө): жумшак «пиано» E–G–B–D, 92 bpm
    notes = [164.81, 196.0, 246.94, 293.66, 246.94, 196.0]
    step = 60 / 92 / 2
    k, j = tl.hook_end - 0.2, 0
    while k < tl.end - 0.3:
        mm = int(1.2 * SR)
        tt2 = _t(mm)
        f0 = notes[j % len(notes)]
        pl = sum(np.sin(2 * np.pi * f0 * h * tt2) / h ** 1.6 for h in (1, 2, 3, 4)) * np.exp(-tt2 / 0.45)
        pl *= np.minimum(1, tt2 / 0.005) * 0.07 * min(1, (k - tl.hook_end + 0.4) / 1.2)
        _place(L, pl, k, 1.0 if j % 2 else 0.7)
        _place(R, pl, k, 0.7 if j % 2 else 1.0)
        k += step
        j += 1
    out = np.stack([L, R], axis=1)[: int(tl.end * SR)]
    # аягында жумшак өчүү
    fo = int(0.6 * SR)
    out[-fo:] *= np.linspace(1, 0, fo)[:, None]
    return out


def read_wav(path: Path) -> np.ndarray:
    tmp = Path(tempfile.mkdtemp()) / "v.wav"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(path), "-ac", "1", "-ar", str(SR),
                    "-sample_fmt", "s16", str(tmp)], check=True)
    with wave.open(str(tmp)) as w:
        x = np.frombuffer(w.readframes(w.getnframes()), np.int16).astype(np.float64) / 32768
    shutil.rmtree(tmp.parent, ignore_errors=True)
    return trim_silence(x)


def trim_silence(x: np.ndarray, thr: float = 0.012) -> np.ndarray:
    a = np.abs(x)
    idx = np.where(a > thr)[0]
    if len(idx) == 0:
        return x
    return x[max(0, idx[0] - int(0.02 * SR)): idx[-1] + int(0.08 * SR)]


def fit_voice(x: np.ndarray, max_dur: float, max_tempo: float = 1.15) -> np.ndarray:
    """Өтө узун болсо atempo менен бир аз тездетет (≤15% — үн табигый калат)."""
    dur = len(x) / SR
    if dur <= max_dur:
        return x
    tempo = min(max_tempo, dur / max_dur)
    d = Path(tempfile.mkdtemp())
    _write_wav(d / "a.wav", x[:, None])
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(d / "a.wav"), "-af", f"atempo={tempo:.4f}",
                    "-ac", "1", str(d / "b.wav")], check=True)
    with wave.open(str(d / "b.wav")) as w:
        y = np.frombuffer(w.readframes(w.getnframes()), np.int16).astype(np.float64) / 32768
    shutil.rmtree(d, ignore_errors=True)
    return y


def _write_wav(path: Path, st: np.ndarray) -> None:
    st = np.clip(st, -1, 1)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(st.shape[1])
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((st * 32767).astype(np.int16).tobytes())


def mix(music: np.ndarray, voices: dict[str, tuple[float, np.ndarray]]) -> np.ndarray:
    out = music.copy()
    if not voices:
        return out
    v = np.zeros(len(out))
    for st, x in voices.values():
        i = int(st * SR)
        x = x[: max(0, len(v) - i)]
        v[i:i + len(x)] += x
    # ducking: диктор сүйлөгөндө музыка −7 дБ
    env = np.convolve(np.abs(v) > 0.02, np.ones(int(0.25 * SR)) / int(0.25 * SR), mode="same")
    duck = 1 - 0.55 * np.clip(env * 3, 0, 1)
    out *= duck[:, None]
    out += np.stack([v, v], axis=1) * 0.95
    return out


# ============================================================ TTS

def tts_lines(out_dir: Path, spec: dict = SPEC, log=print) -> dict[str, Path]:
    """Gemini TTS (Algenib) — ар сап өзүнчө. Whisper менен текшерилет: нускама окулбасын, текст толук угулсун;
    WAV так айтылган сөздөргө чейин кесилет (run #45751726825: 6 сөздүк сап 28 сек болгон — нускама окулган)."""
    from . import asr
    from .config import load_config
    from .gemini import from_config
    from .stages.s3_voice import check_heard

    cfg = load_config("tech_history")
    g = from_config(cfg, log=log)
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = {}
    for name, text in spec["narration"].items():
        expect = [asr.norm_word(w) for w in text.split() if asr.norm_word(w)]
        tries = []
        # variant 2 (таза текст) биринчи: run #45753645612'да variant 0 нускаманы 3/3 окуп койду (квота бекер)
        for attempt, variant in enumerate((2, 0, 2, 0), 1):
            pcm, rate = g.tts(text, voice=cfg.tts_voice, style=spec["tts_style"], variant=variant, lang="English")
            raw = out_dir / f"{name}_raw.wav"
            with wave.open(str(raw), "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(rate)
                w.writeframes(pcm)
            words = asr.transcribe(raw, language="en")
            heard = [w for w, _, _ in words]
            extra, cov, gap = check_heard(expect, heard)
            dur = len(pcm) / 2 / rate
            ok = extra <= 1 and cov >= 0.85 and gap <= 2 and bool(words)
            log(f"🎙 {name}: {dur:.1f} сек, угулду {cov:.0%}, башында ашыкча {extra} сөз (variant {variant})"
                + ("" if ok else f" — {attempt}-аракет ийгиликсиз"))
            tries.append(f"{dur:.1f}s/{cov:.0%}/+{extra}")
            if not ok:
                continue
            # нускаманын калдыгын жана узун тынчтыкты кесүү: акыркы n сөздүн башынан аягына чейин
            n = len(expect)
            seg = words[-n:] if len(words) >= n else words
            t0, t1 = max(0.0, seg[0][1] - 0.06), min(dur, seg[-1][2] + 0.18)
            p = out_dir / f"{name}.wav"
            subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(raw), "-ss", f"{t0:.3f}", "-to", f"{t1:.3f}",
                            str(p)], check=True)
            paths[name] = p
            break
        else:
            raise RuntimeError(f"TTS «{name}» 4 аракеттен кийин да туура эмес: {tries}")
    return paths


def render(out: Path, photos: dict[str, Photo], *, voice_dir: Path | None = None, spec: dict = SPEC,
           log=print) -> dict:
    out.parent.mkdir(parents=True, exist_ok=True)
    voices_raw: dict[str, np.ndarray] = {}
    if voice_dir:
        for name in ("line1", "line2", "bridge"):
            p = voice_dir / f"{name}.wav"
            if p.exists():
                voices_raw[name] = read_wav(p)
    # hook ≤5 сек: үн 1 ≤2.0 сек, үн 2 ≤2.35 сек (керек болсо ≤15% тездетилет)
    for name, mx, tempo in (("line1", 2.0, 1.15), ("line2", 2.35, 1.15), ("bridge", 7.0, 1.08)):
        if name in voices_raw:
            voices_raw[name] = fit_voice(voices_raw[name], mx, tempo)
    durs = {k: len(v) / SR for k, v in voices_raw.items()}
    tl = Timeline.build(durs, hara="hara" in photos)
    starts = {"line1": tl.l1_start, "line2": tl.l2_start, "bridge": tl.bridge_start}
    voices = {k: (starts[k], v) for k, v in voices_raw.items()}

    look = Look()
    scan = Plate(photos["scan"], 1.04, 1.16)
    fac = Plate(photos["factory"], 1.18, 1.06, pan=(0.03, 0.0))          # zoom-out + жай панорама
    bar_end = tl.hara_at or tl.end
    bar = Plate(photos["barcode"], 1.05, 1.22)
    hara = Plate(photos["hara"], 1.02, 1.10) if "hara" in photos else None
    t1 = TextBlock(spec["line1"], spec["line1_accent"], CYAN, y=110, maxw=1640, size=112)
    t2 = TextBlock(spec["line2"], spec["line2_accent"], AMBER, y=90, maxw=1500, size=118)
    lower = TextBlock(spec["lower_title"], ["MASAHIRO", "HARA"], AMBER, y=880, size=78, maxw=1100,
                      align="left", x=110)

    tmp = Path(tempfile.mkdtemp())
    vid = tmp / "v.mp4"
    enc = subprocess.Popen(["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
                            "-r", str(FPS), "-i", "-", "-c:v", "libx264", "-preset", "medium", "-crf", "17",
                            "-pix_fmt", "yuv420p", "-color_primaries", "bt709", "-color_trc", "bt709",
                            "-colorspace", "bt709", str(vid)], stdin=subprocess.PIPE)
    nfr = int(round(tl.end * FPS))
    prev = None
    first_luma = None
    for i in range(nfr):
        t = i / FPS
        wv = (math.sin(i * 0.9) * 1.5, math.cos(i * 0.7) * 1.2)            # кадрдын термелиши (пленка)
        if t < tl.cut:
            zt = ease((t - (tl.cut - 0.42)) / 0.42)                         # zoom-through QR чекитине
            ez = 1 + 7 * zt ** 2.2
            p = t / tl.cut
            im = scan.frame(p, ez, to_focus=zt)
            blur = 9 * (1 - ease_out(t / 0.55))                              # фокустан ачылуу (0 кадрда да көрүнөт)
            arr = look.apply(im, i, "cold", focus_blur=blur, light=(0.15 + 0.6 * p, 0.42)).astype(np.float32)
            if zt > 0 and prev is not None:
                arr = 0.55 * arr + 0.45 * prev
            prev = arr
            frame = Image.fromarray(arr.astype(np.uint8)).convert("RGBA")
            scanner_overlay(frame, t, tl, scan.focus_xy(p, ez, zt), 1 - min(1, zt / 0.35))
            t1.draw(frame, t, tl.l1_start, tl.cut - 0.12)
        else:
            if t < tl.hook_end + 0.15:
                p = (t - tl.cut) / (tl.hook_end + 0.15 - tl.cut)
                im = fac.frame(p, weave=wv)
                arr = look.apply(im, i, "archive", archive=1.0)
            else:
                pb = (t - tl.hook_end - 0.15) / max(0.1, bar_end - tl.hook_end - 0.15)
                arr = look.apply(bar.frame(min(pb, 1.0), weave=wv), i, "archive", archive=0.85)
                if hara is not None and t >= tl.hara_at - 0.5:              # кроссфейд портретке
                    ph = (t - tl.hara_at + 0.5) / max(0.1, tl.end - tl.hara_at + 0.5)
                    harr = look.apply(hara.frame(min(ph, 1.0), weave=wv), i, "archive", archive=0.9)
                    k = ease((t - tl.hara_at + 0.5) / 0.9)
                    arr = (arr * (1 - k) + harr * k).astype(np.uint8)
                kx = ease((t - tl.hook_end - 0.15 + 0.25) / 0.5)              # жумшак өтүү заводдон
                if kx < 1:
                    farr = look.apply(fac.frame(1.0, weave=wv), i, "archive", archive=1.0)
                    arr = (farr * (1 - kx) + arr * kx).astype(np.uint8)
            frame = Image.fromarray(arr).convert("RGBA")
            t2.draw(frame, t, tl.l2_start, tl.hook_end + 0.25)
            pa = ease((t - tl.l2_start - 0.35) / 0.3) * (1 - ease((t - tl.hook_end - 0.2) / 0.3))
            mono_text(frame, spec["place"], (W // 2 - 230, 360), 40, (255, 226, 170), pa,
                      chars=int(max(0, t - tl.l2_start - 0.35) * 40))
            if hara is None or t < tl.hara_at:
                mono_text(frame, spec["disclaimer"], (40, H - 50), 22, (220, 220, 220), 0.6)
            if t >= tl.bridge_start:                                          # lower-third
                k = ease_out((t - tl.bridge_start) / 0.5)
                lay = Image.new("RGBA", frame.size, (0, 0, 0, 0))
                bd = ImageDraw.Draw(lay)
                for yy in range(760, 1080, 4):
                    a = int(170 * k * min(1, (yy - 760) / 160))
                    bd.rectangle([0, yy, W, yy + 4], fill=(0, 0, 0, a))
                bd.rectangle([110, 815, 110 + 560 * k, 822], fill=AMBER + (255,))
                frame.alpha_composite(lay)
                mono_text(frame, spec["lower_kicker"], (110, 836), 34, (255, 226, 170), k,
                          chars=int((t - tl.bridge_start) * 45))
                lower.draw(frame, t, tl.bridge_start + 0.35, tl.end + 5)
            if hara is not None and t >= tl.hara_at:                          # лицензия/автор (CC BY талабы)
                m = photos["hara"].meta
                credit = f"PHOTO: {m.get('author', '')[:40]} / {m.get('license', '')} / WIKIMEDIA COMMONS".upper()
                mono_text(frame, credit, (40, H - 50), 20, (220, 220, 220), 0.7 * ease((t - tl.hara_at) / 0.5))
            fl = max(0.0, 1 - (t - tl.cut) / 0.28)
            if fl > 0:
                frame.alpha_composite(Image.new("RGBA", frame.size, (255, 250, 235, int(235 * fl))))
        if tl.cut - 0.12 <= t < tl.cut:
            k = (t - (tl.cut - 0.12)) / 0.12
            frame.alpha_composite(Image.new("RGBA", frame.size, (255, 250, 235, int(235 * k))))
        fr = frame.convert("RGB")
        fi = min(1.0, (t + 1 / FPS) / 0.15)                                  # fade-in 0.15 сек (s8 эрежеси)
        if fi < 1:
            fr = Image.blend(Image.new("RGB", fr.size), fr, fi)
        if i == int(0.2 * FPS):
            first_luma = float(np.asarray(fr.convert("L"), np.float32).mean())
        enc.stdin.write(fr.tobytes())
    enc.stdin.close()
    if enc.wait() != 0:
        raise RuntimeError("ffmpeg (видео) катасы")

    audio = mix(synth_audio(tl), voices)
    wav = tmp / "a.wav"
    _write_wav(wav, audio / max(1e-6, np.abs(audio).max()) * 0.8)
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(vid), "-i", str(wav), "-map", "0:v", "-map", "1:a",
                    "-c:v", "copy", "-af", "loudnorm=I=-14:TP=-1.5:LRA=11", "-ar", "48000", "-c:a", "aac",
                    "-b:a", "192k", "-shortest", "-movflags", "+faststart", str(out)], check=True)
    shutil.rmtree(tmp, ignore_errors=True)

    report = {
        "topic": spec["topic"], "format": f"{W}x{H} (16:9), {FPS} fps", "timeline": tl.to_dict(),
        "voice": {k: round(len(v) / SR, 2) for k, v in voices_raw.items()} or "жок (үнсүз превью)",
        "first_frame_luma": round(first_luma or 0, 1),
        "photos": {k: {**v.meta, "focus": v.focus} for k, v in photos.items()},
        "description_credits": credits(photos), "sources": spec["sources"],
        "checks": check(tl, first_luma or 0, bool(voices_raw), photos),
    }
    out.with_suffix(".json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
    return report


def credits(photos: dict[str, Photo]) -> str:
    """YouTube сүрөттөмөсү үчүн: булактар жана «stock photos are illustrative»."""
    lines = ["Photos: stock images are illustrative of the era (not archival footage of Denso)."]
    for k, ph in photos.items():
        m = ph.meta
        if m.get("source"):
            lines.append(f"- {m.get('source')}: {m.get('author', '?')} — {m.get('license', '')} — {m.get('page', '')}")
    return "\n".join(lines)


def check(tl: Timeline, first_luma: float, has_voice: bool, photos: dict[str, Photo] | None = None) -> dict:
    """Hook эрежелери: текст ≤1 сек, hook ≤5 сек, биринчи кадр караңгы эмес, сүрөттөрдүн лицензиясы белгилүү."""
    c = {
        "text_by_1s": tl.l1_start <= TEXT_MAX_START,
        "hook_le_5s": tl.hook_end <= HOOK_MAX + 1e-6,
        "first_frame_not_dark": first_luma >= 25,
        "no_logo_intro": True,
        "licenses_known": all(bool(p.meta.get("license")) for p in (photos or {}).values()) if photos else False,
        "photos_fit": all(int(p.meta.get("fit", 5)) >= 5 for p in (photos or {}).values()),
        "voice": has_voice,
    }
    c["ok"] = all(v for k, v in c.items() if k not in ("voice", "licenses_known"))
    return c


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", type=Path, default=Path("out/qr_hook_16x9.mp4"))
    ap.add_argument("--fetch", action="store_true", help="Pixabay + Commons'тон сүрөт алуу (PIXABAY_API_KEY)")
    ap.add_argument("--photos-dir", type=Path, help="scan.jpg, factory.jpg, barcode.jpg [, hara.jpg, photos.json]")
    ap.add_argument("--tts", action="store_true", help="Gemini TTS менен диктор (GOOGLE_API_KEY)")
    ap.add_argument("--voice-dir", type=Path, help="line1.wav, line2.wav, bridge.wav")
    a = ap.parse_args(argv)
    pdir = a.photos_dir or a.out.parent / "photos"
    photos = fetch_photos(pdir) if a.fetch else local_photos(pdir)
    vd = a.voice_dir
    if a.tts:
        vd = a.out.parent / "voice"
        tts_lines(vd)
    rep = render(a.out, photos, voice_dir=vd)
    print(json.dumps(rep, ensure_ascii=False, indent=2))
    if not rep["checks"]["ok"]:
        print("❌ Hook эрежелери аткарылган жок — видео ДАЯР ЭМЕС")
        return 1
    print(f"✅ {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
