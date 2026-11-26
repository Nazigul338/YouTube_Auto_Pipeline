"""9:16 Shorts үчүн кинематографиялык hook (алгачкы 3–5 сек) + тарыхка көпүрө — Tech History (EN) каналы.

Тема: «The Car Parts That Created QR Codes». Бардык кадрлар ушул файлда нөлдөн тартылат (numpy + Pillow + FFmpeg):
сток/архив жок → лицензия тобокелдиги жок, ойдон чыгарылган «архивдик» кадр жок. Завод — стилдештирилген
РЕКОНСТРУКЦИЯ, экранда «ILLUSTRATIVE RECONSTRUCTION» деп белгиленет (жалган визуал болбосун).

Монтаж (убакыттар диктордун үнүнө жараша жылат, hook ≤ 5.0 сек болушу МИЛДЕТТҮҮ):
  0.00  QR коддун макро планы: муздак жарык тагы жылат, тайыз фокус, телефон сканеринин бурчтары кысылат,
        лазер сызыгы өтөт → «lock» (жашыл) + beep. Текст 1: «QR CODES WEREN'T / MADE FOR PHONES...»
  T_CUT QR модулунун ичине zoom-through + жарк + impact → 1990-жылдардын башындагы жапон унаа тетиктери заводу
        (конвейер, штрих-коддуу кутулар, натрий лампалар, туман, чаң), жай dolly-in.
        Текст 2: «THEY WERE BORN FROM / A FACTORY CRISIS.» + «JAPAN · EARLY 1990s».
  HOOK_END → көпүрө: lower-third «1992 · DENSO, JAPAN / ENGINEER MASAHIRO HARA» — окуянын башталышы.
  (--story берилсе, негизги видео 9:16'га келтирилип, кроссфейд менен улантылат.)

Үн: диктор (Gemini TTS Algenib, документалдык/сырдуу стиль; --tts) же даяр WAV'дар (--voice-dir);
музыка (тынчсыздандыруучу документалдык дрон + пульс + остинато) жана эффекттер (сканер, beep, whoosh,
impact, завод) ушул жерде синтезделет — CC0, ушул долбоордун өзүнүкү.

Фактылар (булактар: Wikipedia «QR code», «Masahiro Hara»; EPO European Inventor Award 2014; JPO):
  QR код 1994-ж. Denso Wave (ошол кезде Denso'нун бөлүмү, Toyota тобу) чыгарган, команданы Масахиро Хара
  жетектеген; 1992-ж. ага унаа тетиктерин көзөмөлдөө үчүн жаңы 2D код түзүү тапшырылган; мурда заводдо
  1D штрих-коддор колдонулган.
  ⚠ «crisis» сөзү булактарда жок (алар «штрих-коддор чегине жетти» дейт) — бул колдонуучу тандаган драмалык
  формулировка; SPEC["line2"] аркылуу «A FACTORY PROBLEM.» деп алмаштырса болот.

Иштетүү:
  python -m pipeline.shorts_hook --out out/qr_hook.mp4                 # үнсүз превью (тайминг демейки)
  python -m pipeline.shorts_hook --out out/qr_hook.mp4 --tts           # Gemini TTS (GOOGLE_API_KEY)
  python -m pipeline.shorts_hook --out out/qr_hook.mp4 --voice-dir v/  # v/line1.wav, line2.wav, bridge.wav
  ... --story story.mp4                                                # hook'тон кийин негизги окуя
Убакыт: GitHub runner'де ~1–2 мүн (Colab керек эмес).
"""

from __future__ import annotations

import argparse
import json
import math
import shutil
import subprocess
import tempfile
import wave
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

W, H, FPS, SR = 1080, 1920, 30, 48000
HOOK_MAX = 5.0          # hook (текст 1 + текст 2 + алардын үнү) ушундан узун болбойт
TEXT_MAX_START = 1.0    # биринчи текст ≤ 1 сек ичинде көрүнөт

SPEC = {
    "topic": "The Car Parts That Created QR Codes",
    "qr_data": "QR CODE - DENSO WAVE - 1994",
    "line1": ["QR CODES WEREN'T", "MADE FOR PHONES..."],
    "line1_accent": ["PHONES..."],
    "line2": ["THEY WERE BORN FROM", "A FACTORY CRISIS."],
    "line2_accent": ["FACTORY", "CRISIS."],
    "place": "JAPAN  ·  EARLY 1990s",
    "disclaimer": "ILLUSTRATIVE RECONSTRUCTION",
    "lower_kicker": "1992  ·  DENSO, JAPAN",
    "lower_title": ["ENGINEER", "MASAHIRO HARA"],
    "narration": {
        "line1": "QR codes weren't made for phones...",
        "line2": "They were born from a factory crisis.",
        "bridge": "Japan, 1992. At the car-parts maker Denso, engineer Masahiro Hara is asked to build a better code.",
    },
    "tts_style": ("Deep, confident, mysterious premium documentary narrator, low register, measured and unhurried, "
                  "a hint of suspense, clear diction, cinematic like a high-end history documentary. "
                  "Not a commercial or radio voice."),
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


# ============================================================ шрифттер

def _font_path(kind: str) -> str | None:
    cands = {
        "black": ["InterDisplay-Black.otf", "Inter-Black.otf", "Montserrat-Black.ttf", "Montserrat-ExtraBold.ttf",
                  "DejaVuSans-Bold.ttf"],
        "mono": ["JetBrainsMono-Bold.ttf", "DejaVuSansMono-Bold.ttf", "DejaVuSansMono.ttf"],
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
    l1_start: float = 0.12       # текст 1 + үн 1
    l1_dur: float = 1.9
    cut: float = 2.35            # QR → завод (жарк)
    l2_start: float = 2.5
    l2_dur: float = 2.0
    hook_end: float = 4.6
    bridge_start: float = 4.9
    bridge_dur: float = 5.6
    end: float = 10.8
    voice: dict = field(default_factory=dict)   # name -> (start, path)

    @classmethod
    def build(cls, durs: dict[str, float] | None = None) -> "Timeline":
        d = {"line1": 1.9, "line2": 2.0, "bridge": 5.6, **(durs or {})}
        t = cls()
        t.l1_dur, t.l2_dur, t.bridge_dur = d["line1"], d["line2"], d["bridge"]
        t.cut = max(1.9, t.l1_start + t.l1_dur + 0.12)
        t.l2_start = t.cut + 0.14
        t.hook_end = t.l2_start + t.l2_dur + 0.1
        t.bridge_start = t.hook_end + 0.3
        t.end = t.bridge_start + t.bridge_dur + 0.8
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
    """Чоң, калың, контрасттуу эки саптуу текст; сөздөр кезек-кезеги менен «урулуп» чыгат."""

    def __init__(self, lines: list[str], accent: list[str], color, y: int, maxw: int = 960, size: int = 132,
                 s: float = 1.0):
        self.s = s
        size = int(size * s)
        maxw = int(maxw * s)
        while size > 40:
            f = font("black", size)
            if max(f.getlength(ln) for ln in lines) <= maxw:
                break
            size -= 4
        self.f = font("black", size)
        self.words: list[tuple[Image.Image, int, int]] = []   # sprite, x, y (борбору)
        gap = self.f.getlength(" ")
        lh = int(size * 1.08)
        pad = int(28 * s)
        for i, ln in enumerate(lines):
            ws = ln.split(" ")
            tot = sum(self.f.getlength(w) for w in ws) + gap * (len(ws) - 1)
            x = (W * s - tot) / 2
            for w in ws:
                wl = self.f.getlength(w)
                col = color if w in accent else (255, 255, 255)
                self.words.append((self._sprite(w, col, pad), int(x + wl / 2), int(y * s + i * lh + size / 2)))
                x += wl + gap

    def _sprite(self, word: str, col, pad: int) -> Image.Image:
        bb = self.f.getbbox(word, stroke_width=int(7 * self.s))
        w, h = bb[2] - bb[0] + 2 * pad, bb[3] - bb[1] + 2 * pad
        sh = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        ImageDraw.Draw(sh).text((pad - bb[0], pad - bb[1] + int(6 * self.s)), word, font=self.f,
                                fill=(0, 0, 0, 200))
        sh = sh.filter(ImageFilter.GaussianBlur(14 * self.s))
        ImageDraw.Draw(sh).text((pad - bb[0], pad - bb[1]), word, font=self.f, fill=col + (255,),
                                stroke_width=int(7 * self.s), stroke_fill=(0, 0, 0, 255))
        return sh

    def draw(self, img: Image.Image, t: float, start: float, end: float, stagger: float = 0.07) -> None:
        for i, (sp, cx, cy) in enumerate(self.words):
            a0 = start + i * stagger
            k = (t - a0) / 0.22
            if k <= 0 or t > end + 0.2:
                continue
            alpha = ease_out(k) * (1 - ease((t - end) / 0.2))
            if alpha <= 0.01:
                continue
            sc = 1.22 - 0.22 * ease_out(k)
            spr = sp if abs(sc - 1) < 1e-3 else sp.resize((int(sp.width * sc), int(sp.height * sc)),
                                                          Image.BILINEAR)
            if alpha < 0.999:
                a = spr.getchannel("A").point(lambda v, al=alpha: int(v * al))
                spr = spr.copy()
                spr.putalpha(a)
            img.alpha_composite(spr, (cx - spr.width // 2, cy - spr.height // 2))


def mono_text(img: Image.Image, txt: str, xy, size: int, col, alpha: float, chars: int | None = None,
              s: float = 1.0) -> None:
    if alpha <= 0.01:
        return
    f = font("mono", int(size * s))
    txt = txt if chars is None else txt[:chars]
    lay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(lay)
    d.text((xy[0] * s, xy[1] * s), txt, font=f, fill=col + (int(255 * alpha),),
           stroke_width=max(1, int(3 * s)), stroke_fill=(0, 0, 0, int(220 * alpha)))
    img.alpha_composite(lay)


# ============================================================ пост-обработка (кино көрүнүш)

class Look:
    def __init__(self, w: int, h: int, seed: int = 7):
        rng = np.random.default_rng(seed)
        self.grain = [rng.normal(0, 1, (h, w)).astype(np.float32) for _ in range(6)]
        yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
        r = np.sqrt(((xx - w / 2) / (w * 0.62)) ** 2 + ((yy - h / 2) / (h * 0.55)) ** 2)
        self.vig = np.clip(1.0 - 0.55 * np.clip(r - 0.35, 0, None) ** 1.4, 0.25, 1.0)[..., None]
        self.dof = np.clip((r - 0.30) / 0.45, 0, 1)[..., None]   # 0 = курч борбор, 1 = бүдөмүк чет

    def apply(self, rgb: np.ndarray, i: int, grade: str, grain: float = 7.0, bloom: float = 0.35) -> np.ndarray:
        x = rgb.astype(np.float32)
        if bloom:
            hi = np.clip(x - 170, 0, None)
            b = np.asarray(Image.fromarray(np.clip(hi * 2.5, 0, 255).astype(np.uint8)).filter(
                ImageFilter.GaussianBlur(max(4, x.shape[1] // 45))), np.float32)
            x = x + bloom * b
        if grade == "cold":       # QR: муздак көгүш, кара каралар
            x = x * np.array([0.86, 1.0, 1.10], np.float32) + np.array([0, 4, 10], np.float32)
        elif grade == "warm":     # завод: натрий-янтарь жарык, көгүш көлөкө
            lum = x.mean(axis=2, keepdims=True) / 255
            x = x * (np.array([1.12, 0.98, 0.78], np.float32) * lum + np.array([0.80, 0.95, 1.10], np.float32)
                     * (1 - lum))
        x = x * self.vig
        x = x + self.grain[i % len(self.grain)][..., None] * grain
        return np.clip(x, 0, 255).astype(np.uint8)


# ============================================================ 1-план: QR макро

class QRShot:
    def __init__(self, s: float, data: str):
        import qrcode

        q = qrcode.QRCode(version=3, error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=1, border=2)
        q.add_data(data)
        q.make(fit=False)
        m = np.array(q.get_matrix(), dtype=bool)
        self.n = m.shape[0]
        self.s = s
        mod = int(round(64 * s))                     # модуль: кадрда ~15 модуль + бурчтагы «көз» = макро план
        size = self.n * mod
        rng = np.random.default_rng(3)
        paper = 214 + rng.normal(0, 5, (size, size))  # басылган этикетка: кагаз текстурасы
        ink = np.kron(m, np.ones((mod, mod), bool))
        img = np.where(ink, 18 + rng.normal(0, 3, (size, size)), paper)
        im = Image.fromarray(np.clip(img, 0, 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(0.8 * s))
        self.tex = np.asarray(im, np.float32)
        self.mod = mod
        self.size = size
        self.w, self.h = int(W * s), int(H * s)
        yy, xx = np.mgrid[0:self.h, 0:self.w].astype(np.float32)
        self.xx, self.yy = xx, yy
        # zoom-through максаты: үстүнкү сол «көз» (finder pattern) борбору
        self.target = np.array([2 + 3.5, 2 + 3.5]) * mod

    def frame(self, t: float, tl: Timeline) -> tuple[Image.Image, dict]:
        cut = tl.cut
        z = 1.0 + 0.10 * (t / cut)                                   # жай push-in
        zt = ease((t - (cut - 0.42)) / 0.42)
        z *= 1 + 9 * zt ** 2.2                                       # модулдун ичине кирүү
        ang = math.radians(-6 + 3 * t / cut)
        c0 = np.array([self.size / 2, self.size / 2]) * 0.45 + self.target * 0.55   # «көз» кадрда
        c = c0 * (1 - zt) + self.target * zt
        c = c + np.array([math.sin(t * 0.9) * 6, math.cos(t * 0.7) * 5]) * self.s   # жумшак калкуу
        # экран → текстура координаттары (айлануу + масштаб)
        dx = (self.xx - self.w / 2) / z
        dy = (self.yy - self.h * 0.56) / z
        u = c[0] + dx * math.cos(ang) - dy * math.sin(ang)
        v = c[1] + dx * math.sin(ang) + dy * math.cos(ang)
        ui = np.clip(u.astype(np.int32), 0, self.size - 1)
        vi = np.clip(v.astype(np.int32), 0, self.size - 1)
        inside = (u >= 0) & (u < self.size) & (v >= 0) & (v < self.size)
        base = np.where(inside, self.tex[vi, ui], 8.0)
        # драмалык жарык: кыйгач жарык тагы солдон оңго жылат
        lx = self.w * (0.15 + 0.6 * t / max(cut, 0.1))
        ly = self.h * 0.42
        r2 = ((self.xx - lx) / (self.w * 0.55)) ** 2 + ((self.yy - ly) / (self.h * 0.32)) ** 2
        light = 0.22 + 1.05 * np.exp(-r2)
        rgb = np.repeat((base * light)[..., None], 3, axis=2)
        info = {"z": z, "zt": zt}
        return Image.fromarray(np.clip(rgb, 0, 255).astype(np.uint8)), info

    def overlay(self, img: Image.Image, t: float, tl: Timeline, zt: float) -> None:
        """Телефон сканеринин интерфейси (бурчтар, лазер, lock)."""
        if zt > 0.35:
            return
        s = self.s
        d = ImageDraw.Draw(img)
        lock = min(1.5, tl.cut - 0.55)
        k = ease_out((t - 0.15) / (lock - 0.25))
        cx, cy = self.w / 2, self.h * 0.56
        half = (520 - 160 * k) * s
        locked = t >= lock
        col = (GREEN if locked else (235, 245, 255)) + (int(255 * (1 - zt / 0.35)),)
        L, lw = 110 * s, max(2, int(9 * s))
        for sx in (-1, 1):
            for sy in (-1, 1):
                x0, y0 = cx + sx * half, cy + sy * half
                d.line([(x0, y0), (x0 - sx * L, y0)], fill=col, width=lw)
                d.line([(x0, y0), (x0, y0 - sy * L)], fill=col, width=lw)
        if 0.35 <= t < lock:
            p = ease((t - 0.35) / (lock - 0.35))
            y = cy - half + 2 * half * p
            glow = Image.new("RGBA", img.size, (0, 0, 0, 0))
            gd = ImageDraw.Draw(glow)
            gd.rectangle([cx - half, y - 26 * s, cx + half, y + 26 * s], fill=(255, 40, 60, 90))
            glow = glow.filter(ImageFilter.GaussianBlur(18 * s))
            img.alpha_composite(glow)
            d.line([(cx - half, y), (cx + half, y)], fill=(255, 90, 100, 255), width=max(2, int(5 * s)))
        if locked:
            fl = max(0.0, 1 - (t - lock) / 0.25)
            if fl > 0:
                img.alpha_composite(Image.new("RGBA", img.size, (120, 255, 180, int(70 * fl))))
            mono_text(img, "●  CODE DETECTED", (cx / s - 200, cy / s + half / s + 40), 38, GREEN,
                      min(1.0, (t - lock) / 0.12) * (1 - zt / 0.35), s=s)


# ============================================================ 2-план: 1990-жылдардын заводу (реконструкция)

class FactoryShot:
    """Перспективадагы конвейер, штрих-коддуу тетик кутулары, натрий лампалар, туман, чаң (жарым чечим)."""

    def __init__(self, s: float, seed: int = 11):
        self.s = s
        self.w, self.h = int(W * s / 2), int(H * s / 2)
        self.f = 0.95 * self.w
        self.rng = np.random.default_rng(seed)
        self.bars = [self._barcode(i) for i in range(64)]
        self.dust = self.rng.uniform([-3.5, 0.5, 2], [3.5, 5.0, 40], (260, 3))
        self.fog = np.array([28, 30, 38], float)

    def _barcode(self, i: int) -> list[tuple[float, float]]:
        r = np.random.default_rng(100 + i)
        out, x = [], 0.0
        while x < 1:
            w = r.choice([0.012, 0.02, 0.03, 0.045])
            if r.random() < 0.55:
                out.append((x, min(1.0, x + w)))
            x += w + r.choice([0.01, 0.018, 0.026])
        return out

    def cam(self, u: float):
        camz = 0.55 * u
        camx = -0.85 + 0.10 * u + 0.05 * math.sin(u * 0.8)
        camy = 2.25 + 0.03 * math.sin(u * 0.6)
        hor = self.h * 0.40
        return camx, camy, camz, hor

    def P(self, x, y, z, c):
        camx, camy, camz, hor = c
        dz = max(z - camz, 0.05)
        return (self.w / 2 + self.f * (x - camx) / dz, hor - self.f * (y - camy) / dz)

    def shade(self, col, z, c, k=1.0):
        dz = max(z - c[2], 0.05)
        a = 1 - math.exp(-dz / 22)
        return tuple(int((ch * k) * (1 - a) + fg * a) for ch, fg in zip(col, self.fog))

    def frame(self, u: float) -> Image.Image:
        c = self.cam(u)
        img = Image.new("RGB", (self.w, self.h), (14, 14, 18))
        d = ImageDraw.Draw(img)
        light = Image.new("RGB", (self.w, self.h), (0, 0, 0))
        ld = ImageDraw.Draw(light)
        hor = c[3]
        # тамы жана шып: тик градиент
        for y in range(self.h):
            if y < hor:
                v = 12 + 18 * (y / hor)
                d.line([(0, y), (self.w, y)], fill=(int(v), int(v), int(v * 1.25)))
            else:
                v = 30 - 16 * ((y - hor) / (self.h - hor))
                d.line([(0, y), (self.w, y)], fill=(int(v * 1.05), int(v), int(v * 0.9)))
        # арткы дубалдагы бийик терезелер (муздак жарык — контраст)
        zb = 70.0
        for i in range(-6, 7):
            x0, y0 = self.P(i * 1.6 - 0.6, 7.5, zb, c)
            x1, y1 = self.P(i * 1.6 + 0.6, 5.6, zb, c)
            d.rectangle([x0, y0, x1, y1], fill=(60, 78, 100))
            ld.rectangle([x0, y0, x1, y1], fill=(40, 60, 90))
        z0 = math.floor(c[2] / 7) * 7
        zs = [z for z in np.arange(z0 + 63, z0 - 1, -7.0) if z - c[2] > 0.6]
        for z in zs:    # колонналар, шып устундары, лампалар (алыстан жакынга)
            for sx in (-4.2, 4.2):
                a, b = self.P(sx - 0.25, 7.0, z, c), self.P(sx + 0.25, 0.0, z, c)
                d.rectangle([a[0], a[1], b[0], b[1]], fill=self.shade((52, 58, 66), z, c))
            a, b = self.P(-4.2, 6.6, z, c), self.P(4.2, 6.4, z, c)
            d.rectangle([a[0], a[1], b[0], b[1]], fill=self.shade((40, 44, 50), z, c))
            lx, ly = self.P(0.0, 5.4, z, c)
            lw = self.f * 0.55 / max(z - c[2], 0.05)
            d.rectangle([lx - lw, ly - lw * 0.25, lx + lw, ly], fill=self.shade((255, 214, 150), z, c, 1.0))
            fl = [self.P(-2.0, 0.0, z - 1.0, c), self.P(2.0, 0.0, z - 1.0, c), self.P(1.4, 0.0, z + 1.2, c),
                  self.P(-1.4, 0.0, z + 1.2, c)]
            fall = math.exp(-max(z - c[2], 0) / 30)
            ld.polygon([(lx - lw, ly), (lx + lw, ly), fl[1], fl[0]],
                       fill=(int(70 * fall), int(52 * fall), int(26 * fall)))
            ld.polygon(fl, fill=(int(90 * fall), int(66 * fall), int(30 * fall)))
        # конвейер
        belt = [self.P(-0.95, 0.9, c[2] + 0.6, c), self.P(0.95, 0.9, c[2] + 0.6, c), self.P(0.95, 0.9, 75, c),
                self.P(-0.95, 0.9, 75, c)]
        d.polygon(belt, fill=(24, 24, 26))
        for sx in (-1.0, 1.0):
            d.line([self.P(sx, 0.95, c[2] + 0.6, c), self.P(sx, 0.95, 75, c)], fill=(110, 112, 118), width=2)
        side = [self.P(-1.0, 0.9, c[2] + 0.6, c), self.P(-1.0, 0.9, 75, c), self.P(-1.0, 0.45, 75, c),
                self.P(-1.0, 0.45, c[2] + 0.6, c)]
        d.polygon(side, fill=(34, 36, 40))
        roll = (u * 0.5) % 0.6
        for z in np.arange(math.ceil(c[2]), c[2] + 40, 0.6) - roll:     # ролик сызыктары — кыймыл сезими
            if z - c[2] > 0.6:
                d.line([self.P(-0.95, 0.9, z, c), self.P(0.95, 0.9, z, c)], fill=self.shade((40, 40, 44), z, c),
                       width=1)
        # тетик кутулары (алыстан жакынга), ар биринде 1D штрих-код этикеткасы
        speed, gap = 0.45, 2.4
        boxes = []
        for i in range(60):
            zc = 3.0 + i * gap - speed * u
            if 0.9 < zc - c[2] < 70:
                boxes.append((zc, i))
        for zc, i in sorted(boxes, reverse=True):
            x0, x1, y0, y1, zf, zb2 = -0.62, 0.62, 0.9, 1.62, zc - 0.45, zc + 0.45
            top = [self.P(x0, y1, zf, c), self.P(x1, y1, zf, c), self.P(x1, y1, zb2, c), self.P(x0, y1, zb2, c)]
            left = [self.P(x0, y0, zf, c), self.P(x0, y1, zf, c), self.P(x0, y1, zb2, c), self.P(x0, y0, zb2, c)]
            front = [self.P(x0, y1, zf, c), self.P(x1, y1, zf, c), self.P(x1, y0, zf, c), self.P(x0, y0, zf, c)]
            card = (150, 106, 62)
            d.polygon(top, fill=self.shade(card, zf, c, 1.25))
            d.polygon(left, fill=self.shade(card, zf, c, 0.55))
            d.polygon(front, fill=self.shade(card, zf, c, 0.85))
            fx0, fy0 = front[0]
            fx1, fy1 = front[2]
            fw, fh = fx1 - fx0, fy1 - fy0
            if fw > 14:
                lx0, ly0, lx1, ly1 = fx0 + fw * 0.16, fy0 + fh * 0.22, fx0 + fw * 0.84, fy0 + fh * 0.78
                d.rectangle([lx0, ly0, lx1, ly1], fill=self.shade((226, 222, 208), zf, c))
                if fw > 40:
                    bw = lx1 - lx0
                    for a, b in self.bars[i % 64]:
                        d.rectangle([lx0 + bw * (0.07 + 0.86 * a), ly0 + (ly1 - ly0) * 0.14,
                                     lx0 + bw * (0.07 + 0.86 * b), ly0 + (ly1 - ly0) * 0.68],
                                    fill=self.shade((22, 22, 22), zf, c))
                    for k in range(2):
                        yk = ly0 + (ly1 - ly0) * (0.76 + 0.1 * k)
                        d.line([(lx0 + bw * 0.08, yk), (lx0 + bw * (0.55 - 0.2 * k), yk)],
                               fill=self.shade((70, 70, 70), zf, c), width=max(1, int(fw / 120)))
        # чаң бөлүкчөлөрү (лампа жарыгында)
        dust = self.dust.copy()
        dust[:, 1] += 0.08 * math.sin(u * 0.7) + (u * 0.05) % 0.5
        for x, y, z in dust:
            z = z + math.floor(c[2] / 40) * 40
            if z - c[2] < 0.8:
                z += 40
            px, py = self.P(x, y, z, c)
            r = max(0.6, 2.2 / max(z - c[2], 0.3))
            ld.ellipse([px - r, py - r, px + r, py + r], fill=(110, 90, 60))
        light = light.filter(ImageFilter.GaussianBlur(self.w / 40))
        out = np.asarray(img, np.float32) + np.asarray(light, np.float32) * 1.2
        # туман: горизонтко жакын жарык тилке
        yy = np.arange(self.h, dtype=np.float32)[:, None, None]
        haze = np.exp(-((yy - hor) / (self.h * 0.12)) ** 2) * np.array([34, 30, 26], np.float32)
        out = out + haze
        im = Image.fromarray(np.clip(out, 0, 255).astype(np.uint8))
        return im.resize((int(W * self.s), int(H * self.s)), Image.LANCZOS)


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
    """Gemini TTS (Algenib) — ар сап өзүнчө (тайминг так болсун). GOOGLE_API_KEY керек."""
    from .config import load_config
    from .gemini import from_config

    cfg = load_config("tech_history")
    g = from_config(cfg, log=log)
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = {}
    for name, text in spec["narration"].items():
        pcm, rate = g.tts(text, voice=cfg.tts_voice, style=spec["tts_style"], variant=0, lang="English")
        p = out_dir / f"{name}.wav"
        with wave.open(str(p), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(rate)
            w.writeframes(pcm)
        paths[name] = p
        log(f"🎙 {name}: {len(pcm) / 2 / rate:.2f} сек")
    return paths


# ============================================================ рендер

def render(out: Path, *, voice_dir: Path | None = None, story: Path | None = None, scale: float = 1.0,
           spec: dict = SPEC, log=print) -> dict:
    out.parent.mkdir(parents=True, exist_ok=True)
    voices_raw: dict[str, np.ndarray] = {}
    if voice_dir:
        for name in ("line1", "line2", "bridge"):
            p = voice_dir / f"{name}.wav"
            if p.exists():
                voices_raw[name] = read_wav(p)
    # hook ≤5 сек: үн 1 ≤2.0 сек, үн 2 ≤2.35 сек (керек болсо ≤15% тездетилет)
    if "line1" in voices_raw:
        voices_raw["line1"] = fit_voice(voices_raw["line1"], 2.0)
    if "line2" in voices_raw:
        voices_raw["line2"] = fit_voice(voices_raw["line2"], 2.35)
    if "bridge" in voices_raw:
        voices_raw["bridge"] = fit_voice(voices_raw["bridge"], 7.0, 1.08)
    durs = {k: len(v) / SR for k, v in voices_raw.items()}
    tl = Timeline.build(durs)
    starts = {"line1": tl.l1_start, "line2": tl.l2_start, "bridge": tl.bridge_start}
    voices = {k: (starts[k], v) for k, v in voices_raw.items()}

    s = scale
    w, h = int(W * s) // 2 * 2, int(H * s) // 2 * 2
    look = Look(w, h)
    qr = QRShot(s, spec["qr_data"])
    fac = FactoryShot(s)
    t1 = TextBlock(spec["line1"], spec["line1_accent"], CYAN, y=250, s=s)
    t2 = TextBlock(spec["line2"], spec["line2_accent"], AMBER, y=250, s=s)
    lower = TextBlock(spec["lower_title"], ["MASAHIRO", "HARA"], AMBER, y=1130, size=96, maxw=820, s=s)

    tmp = Path(tempfile.mkdtemp())
    vid = tmp / "v.mp4"
    enc = subprocess.Popen(["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{w}x{h}",
                            "-r", str(FPS), "-i", "-", "-c:v", "libx264", "-preset", "medium", "-crf", "17",
                            "-pix_fmt", "yuv420p", "-color_primaries", "bt709", "-color_trc", "bt709",
                            "-colorspace", "bt709", str(vid)], stdin=subprocess.PIPE)
    nfr = int(round(tl.end * FPS))
    prev = None
    first_luma = None
    for i in range(nfr):
        t = i / FPS
        if t < tl.cut:
            im, info = qr.frame(t, tl)
            arr = np.asarray(im, np.float32)
            blur = np.asarray(im.filter(ImageFilter.GaussianBlur(10 * s)), np.float32)
            arr = arr * (1 - look.dof) + blur * look.dof                 # тайыз фокус
            if info["zt"] > 0 and prev is not None:                        # zoom-through: кыймыл бүдөмүгү
                arr = 0.55 * arr + 0.45 * prev
            prev = arr
            rgb = look.apply(arr, i, "cold", grain=6, bloom=0.25)
            frame = Image.fromarray(rgb).convert("RGBA")
            qr.overlay(frame, t, tl, info["zt"])
            t1.draw(frame, t, tl.l1_start, tl.cut - 0.12)
        else:
            u = t - tl.cut
            im = fac.frame(u)
            rgb = look.apply(np.asarray(im, np.float32), i, "warm", grain=8, bloom=0.45)
            frame = Image.fromarray(rgb).convert("RGBA")
            t2.draw(frame, t, tl.l2_start, tl.hook_end + 0.25)
            pa = ease((t - tl.l2_start - 0.35) / 0.3) * (1 - ease((t - tl.hook_end - 0.2) / 0.3))
            mono_text(frame, spec["place"], (72, 600), 40, (255, 226, 170), pa,
                      chars=int(max(0, t - tl.l2_start - 0.35) * 40), s=s)
            mono_text(frame, spec["disclaimer"], (72, 1500), 24, (220, 220, 220), 0.55 * min(1, u / 0.4), s=s)
            # көпүрө: lower-third (окуянын башталышы)
            if t >= tl.bridge_start:
                k = ease_out((t - tl.bridge_start) / 0.5)
                bar = Image.new("RGBA", frame.size, (0, 0, 0, 0))
                bd = ImageDraw.Draw(bar)
                for yy in range(int(960 * s), int(1400 * s), 4):            # окулушу үчүн караңгы тилке
                    a = int(150 * k * math.sin(math.pi * (yy / s - 960) / 440))
                    bd.rectangle([0, yy, w, yy + 4], fill=(0, 0, 0, max(0, a)))
                bd.rectangle([72 * s, 1040 * s, (72 + 520 * k) * s, 1048 * s], fill=AMBER + (255,))
                frame.alpha_composite(bar)
                mono_text(frame, spec["lower_kicker"], (72, 1066), 40, (255, 226, 170), k,
                          chars=int((t - tl.bridge_start) * 45), s=s)
                lower.draw(frame, t, tl.bridge_start + 0.35, tl.end + 5)
            # жарк (QR → завод өтүүсү)
            fl = max(0.0, 1 - u / 0.28)
            if fl > 0:
                frame.alpha_composite(Image.new("RGBA", frame.size, (255, 250, 235, int(235 * fl))))
        if t >= tl.cut - 0.12 and t < tl.cut:   # жарк башталышы
            k = (t - (tl.cut - 0.12)) / 0.12
            frame.alpha_composite(Image.new("RGBA", frame.size, (255, 250, 235, int(235 * k))))
        fi = int(min(1, (t + 1 / FPS) / 0.15) * 255)                       # fade-in 0.15 сек (s8 эрежеси)
        fr = frame.convert("RGB")
        if fi < 255:
            fr = Image.blend(Image.new("RGB", fr.size), fr, fi / 255)
        if i == int(0.2 * FPS):
            first_luma = float(np.asarray(fr.convert("L"), np.float32).mean())
        enc.stdin.write(fr.tobytes())
    enc.stdin.close()
    if enc.wait() != 0:
        raise RuntimeError("ffmpeg (видео) катасы")

    audio = mix(synth_audio(tl), voices)
    wav = tmp / "a.wav"
    _write_wav(wav, audio / max(1e-6, np.abs(audio).max()) * 0.8)
    hook_mp4 = tmp / "hook.mp4" if story else out
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(vid), "-i", str(wav), "-map", "0:v", "-map", "1:a",
                    "-c:v", "copy", "-af", "loudnorm=I=-14:TP=-1.5:LRA=11", "-ar", "48000", "-c:a", "aac",
                    "-b:a", "192k", "-shortest", "-movflags", "+faststart", str(hook_mp4)], check=True)
    if story:
        append_story(hook_mp4, story, out, tl.end)
    shutil.rmtree(tmp, ignore_errors=True)

    report = {
        "topic": spec["topic"], "format": f"{w}x{h} (9:16), {FPS} fps", "timeline": tl.to_dict(),
        "voice": {k: round(len(v) / SR, 2) for k, v in voices_raw.items()} or "жок (үнсүз превью)",
        "first_frame_luma": round(first_luma or 0, 1), "sources": spec["sources"],
        "checks": check(tl, first_luma or 0, bool(voices_raw)),
    }
    out.with_suffix(".json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
    return report


def check(tl: Timeline, first_luma: float, has_voice: bool) -> dict:
    """Hook эрежелери: текст ≤1 сек, hook ≤5 сек, биринчи кадр караңгы эмес, үн бар."""
    c = {
        "text_by_1s": tl.l1_start <= TEXT_MAX_START,
        "hook_le_5s": tl.hook_end <= HOOK_MAX + 1e-6,
        "first_frame_not_dark": first_luma >= 25,
        "no_logo_intro": True,          # логотип/интро анимация жок — биринчи кадр дароо QR макро
        "voice": has_voice,
    }
    c["ok"] = all(v for k, v in c.items() if k != "voice")
    return c


def append_story(hook: Path, story: Path, out: Path, hook_dur: float, xf: float = 0.4) -> None:
    """Негизги окуяны 9:16'га келтирип (blur фон + борбордо кадр), hook'ка кроссфейд менен улайт."""
    fc = (f"[1:v]split=2[b][f];[b]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},"
          f"gblur=sigma=30,eq=brightness=-0.08[bg];[f]scale={W}:-2[fg];[bg][fg]overlay=(W-w)/2:(H-h)/2,"
          f"fps={FPS},format=yuv420p,setsar=1[s];[0:v]format=yuv420p,setsar=1[h];"
          f"[h][s]xfade=transition=fade:duration={xf}:offset={hook_dur - xf:.3f}[v];"
          f"[0:a][1:a]acrossfade=d={xf}[a]")
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(hook), "-i", str(story), "-filter_complex", fc,
                    "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-crf", "18", "-preset", "medium",
                    "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(out)], check=True)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", type=Path, default=Path("out/qr_hook_9x16.mp4"))
    ap.add_argument("--tts", action="store_true", help="Gemini TTS менен диктор (GOOGLE_API_KEY)")
    ap.add_argument("--voice-dir", type=Path, help="line1.wav, line2.wav, bridge.wav")
    ap.add_argument("--story", type=Path, help="hook'тон кийин уланчу негизги видео")
    ap.add_argument("--scale", type=float, default=1.0)
    a = ap.parse_args(argv)
    vd = a.voice_dir
    if a.tts:
        vd = a.out.parent / "voice"
        tts_lines(vd)
    rep = render(a.out, voice_dir=vd, story=a.story, scale=a.scale)
    print(json.dumps(rep, ensure_ascii=False, indent=2))
    if not rep["checks"]["ok"]:
        print("❌ Hook эрежелери аткарылган жок — видео ДАЯР ЭМЕС")
        return 1
    print(f"✅ {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
