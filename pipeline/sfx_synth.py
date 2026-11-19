"""Оригиналдуу үн эффекттерин ТҮЗӨТ (синтез: numpy + FFmpeg) — жүктөө жок, лицензия тобокелдиги жок.

Эмне үчүн: Pixabay API'де үн эффекттери жок, ал эми сайттардан автоматтык жүктөө/scraping
эрежелерге каршы. Бул модуль эффекттерди нөлдөн жаратат; автору — ушул долбоор, лицензиясы CC0 1.0
(каналдын ээси коммерциялык колдоно алат, атрибуция керек эмес).

Иштетүү:  python -m pipeline.sfx_synth <чыгуу_папкасы>
Жыйынтык: <папка>/<категория>/<ат>.wav + <ат>.metadata.json (sfx.py лицензия капкасынан өтөт).

«Сокку» эффекттери алдыңкы бөлүгүндө күчтүү (sfx.py аларды диктордун паузасына коёт жана
паузадан кийин 0.6 сек ичинде басаңдатат), фондор 24 сек жана тегиз кайталанат (loop).
"""

from __future__ import annotations

import hashlib
import json
import sys
import wave
from datetime import date
from pathlib import Path

import numpy as np

SR = 48000
SCRIPT_URL = "https://github.com/Nazigul338/YouTube_Auto_Pipeline/blob/main/pipeline/sfx_synth.py"
LICENSE = ("CC0 1.0", "https://creativecommons.org/publicdomain/zero/1.0/")


# ---------------------------------------------------------------- негизги блоктор

def t_axis(dur: float) -> np.ndarray:
    return np.arange(int(dur * SR)) / SR


def colored_noise(n: int, alpha: float, rng: np.random.Generator) -> np.ndarray:
    """alpha=0 ак, 1 pink, 2 brown (спектр 1/f^alpha)."""
    spec = np.fft.rfft(rng.standard_normal(n))
    f = np.fft.rfftfreq(n, 1 / SR)
    f[0] = f[1]
    spec *= f ** (-alpha / 2)
    x = np.fft.irfft(spec, n)
    return x / (np.max(np.abs(x)) + 1e-9)


def tv_band(x: np.ndarray, lo, hi, block: int = 2048) -> np.ndarray:
    """Убакыт боюнча өзгөргөн band-pass (STFT маскасы, 50% overlap-add). lo/hi — Гц (сан же массив)."""
    n = len(x)
    lo = np.broadcast_to(np.asarray(lo, float), (n,))
    hi = np.broadcast_to(np.asarray(hi, float), (n,))
    hop = block // 2
    win = np.hanning(block)
    pad = np.concatenate([np.zeros(block), x, np.zeros(block)])
    out = np.zeros_like(pad)
    norm = np.zeros_like(pad)
    f = np.fft.rfftfreq(block, 1 / SR)
    for s in range(0, len(pad) - block, hop):
        c = min(max(s - block + hop, 0), n - 1)
        a, b = lo[c], hi[c]
        mask = 1 / (1 + (a / np.maximum(f, 1)) ** 4) / (1 + (f / max(b, 1)) ** 4)
        seg = np.fft.irfft(np.fft.rfft(pad[s:s + block] * win) * mask, block)
        out[s:s + block] += seg * win
        norm[s:s + block] += win ** 2
    return (out / np.maximum(norm, 1e-6))[block:block + n]


def reverb(x: np.ndarray, dur: float, mix: float, rng: np.random.Generator) -> np.ndarray:
    """Жумшак жасалма реверберация: экспоненциалдуу өчүүчү ызы-чуу IR (FFT конволюция)."""
    t = t_axis(dur)
    ir = rng.standard_normal(len(t)) * np.exp(-t / (dur / 5))
    ir = tv_band(ir, 150, 6000)
    ir /= np.sqrt(np.sum(ir ** 2)) + 1e-9
    m = len(x) + len(ir) - 1
    wet = np.fft.irfft(np.fft.rfft(x, m) * np.fft.rfft(ir, m), m)[:len(x)]
    return (1 - mix) * x + mix * wet


def env_ad(t: np.ndarray, attack: float, tau: float) -> np.ndarray:
    return np.where(t < attack, t / max(attack, 1e-4), np.exp(-(t - attack) / tau))


def pan(mono: np.ndarray, pos) -> np.ndarray:
    """pos −1 (сол) … +1 (оң), бирдей кубаттуулук."""
    p = (np.asarray(pos, float) + 1) * np.pi / 4
    return np.stack([mono * np.cos(p), mono * np.sin(p)], axis=1)


def loopable(st: np.ndarray, xfade: float = 1.5) -> np.ndarray:
    """Аягы башына жумшак кошулат — -stream_loop'то чыкылдабайт."""
    k = int(xfade * SR)
    body, tail = st[:-k].copy(), st[-k:]
    w = np.linspace(0, 1, k)[:, None]
    body[:k] = body[:k] * w + tail * (1 - w)
    return body


def finish(st: np.ndarray, peak_db: float = -3.0, rms_db: float | None = None) -> np.ndarray:
    st = np.tanh(st * 1.2) / np.tanh(1.2) if np.max(np.abs(st)) > 0 else st
    if rms_db is not None:
        st *= 10 ** (rms_db / 20) / (np.sqrt(np.mean(st ** 2)) + 1e-9)
    pk = np.max(np.abs(st)) + 1e-9
    lim = 10 ** (peak_db / 20)
    if pk > lim or rms_db is None:
        st *= lim / pk
    fade = int(0.004 * SR)
    if rms_db is None:   # «сокку» эффекттеринин аягы тынч
        st[-fade:] *= np.linspace(1, 0, fade)[:, None]
    return st


def stereo(mono: np.ndarray, width: float, rng: np.random.Generator) -> np.ndarray:
    """Моно → кенен стерео (кичине кечигүү + декорреляция)."""
    d = int(0.011 * SR)
    r = np.concatenate([np.zeros(d), mono[:-d]])
    return np.stack([mono, (1 - width) * mono + width * r], axis=1)


# ---------------------------------------------------------------- эффекттер

def whoosh(dur: float, peak: float, direction: int, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    t = t_axis(dur)
    x = colored_noise(len(t), 1.0, rng)
    up = np.clip(t / peak, 0, 1)
    down = np.clip((t - peak) / (dur - peak), 0, 1)
    center = np.where(t < peak, 350 + 3600 * up ** 1.6, 3950 - 3300 * down ** 0.7)
    y = tv_band(x, center * 0.45, center * 1.9)
    e = np.where(t < peak, up ** 2.2, np.exp(-down * 4.5))
    return finish(pan(y * e, direction * np.tanh((t - peak) * 4)))


def boom(dur: float, f0: float, f1: float, tau: float, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    t = t_axis(dur)
    f = f1 + (f0 - f1) * np.exp(-t / 0.12)
    body = np.sin(2 * np.pi * np.cumsum(f) / SR) * env_ad(t, 0.004, tau)
    click = tv_band(colored_noise(len(t), 0.5, rng), 80, 2200) * env_ad(t, 0.001, 0.035)
    air = tv_band(colored_noise(len(t), 1.0, rng), 60, 900) * env_ad(t, 0.01, tau * 0.8) * 0.35
    y = reverb(body + 0.6 * click + air, 1.6, 0.25, rng)
    return finish(stereo(y, 0.35, rng))


def braam(dur: float, root: float, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    t = t_axis(dur)
    y = np.zeros_like(t)
    for mult, det in ((1, 0), (1.5, 0.3), (2, -0.4), (1, 0.7)):
        ph = 2 * np.pi * root * mult * (1 + det / 100) * t
        y += sum(np.sin(k * ph) / k for k in range(1, 9))      # жумшак «пила»
    y = tv_band(y, 30, 300 + 1400 * np.exp(-t / 0.5))
    y *= env_ad(t, 0.03, 1.1)
    y = reverb(y, 2.4, 0.35, rng)
    return finish(stereo(y, 0.6, rng))


def sub_drop(dur: float, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    t = t_axis(dur)
    f = 40 + 90 * np.exp(-t / 0.35)
    y = np.sin(2 * np.pi * np.cumsum(f) / SR) * env_ad(t, 0.01, 0.9)
    y += tv_band(colored_noise(len(t), 1.0, rng), 200, 3000) * env_ad(t, 0.005, 0.25) * 0.25
    return finish(stereo(reverb(y, 2.0, 0.3, rng), 0.4, rng))


def chord(dur: float, notes: list[float], bell: bool, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    t = t_axis(dur)
    y = np.zeros_like(t)
    partials = ((1, 1.0), (2.76, 0.35), (5.4, 0.15), (8.93, 0.06)) if bell else \
        ((1, 1.0), (2, 0.45), (3, 0.22), (4, 0.12), (5, 0.06))
    for i, f in enumerate(notes):
        start = 0.035 * i                                       # жумшак арпеджио
        tt = np.clip(t - start, 0, None)
        for k, (m, a) in enumerate(partials):
            y += a * np.sin(2 * np.pi * f * m * tt) * env_ad(tt, 0.006, (1.8 if bell else 1.3) / (1 + k * 0.6)) * (t >= start)
    y = reverb(y, 2.8, 0.4, rng)
    return finish(stereo(y, 0.5, rng), peak_db=-4.0)


def pad_swell(dur: float, notes: list[float], seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    t = t_axis(dur)
    y = sum(np.sin(2 * np.pi * f * t + rng.uniform(0, 6)) * (1 + 0.3 * np.sin(2 * np.pi * 0.7 * t + i))
            for i, f in enumerate(notes))
    e = np.where(t < 0.25, t / 0.25, np.exp(-(t - 0.25) / 1.4))
    return finish(stereo(reverb(y * e, 3.0, 0.45, rng), 0.7, rng), peak_db=-4.0)


# фондор (24 сек, loop)
BED = 24.0


def _bed(dur: float = BED + 1.5) -> np.ndarray:
    return t_axis(dur)


def room_drone(seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    t = _bed()
    y = sum(a * np.sin(2 * np.pi * f * t) * (0.7 + 0.3 * np.sin(2 * np.pi * t / BED * k))
            for k, (f, a) in enumerate(((55, 1), (82.4, 0.6), (110, 0.35), (164.8, 0.15)), 1))
    y = y / 2.2 + 0.5 * tv_band(colored_noise(len(t), 2.0, rng), 40, 320)
    return finish(loopable(stereo(y, 0.8, rng)), peak_db=-6, rms_db=-24)


def air_tone(seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    t = _bed()
    y = tv_band(colored_noise(len(t), 1.0, rng), 150, 1200) * (0.8 + 0.2 * np.sin(2 * np.pi * t / (BED / 3)))
    st = np.stack([y, tv_band(colored_noise(len(t), 1.0, rng), 150, 1200)], axis=1)
    return finish(loopable(st), peak_db=-6, rms_db=-24)


def wind(seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    t = _bed()
    gust = 0.55 + 0.45 * np.sin(2 * np.pi * t / (BED / 2)) * np.sin(2 * np.pi * t / (BED / 5) + 1)
    center = 380 + 420 * (0.5 + 0.5 * np.sin(2 * np.pi * t / (BED / 3)))
    chans = [tv_band(colored_noise(len(t), 1.2, rng), center * 0.5, center * 2.2) * gust for _ in range(2)]
    return finish(loopable(np.stack(chans, axis=1)), peak_db=-6, rms_db=-24)


def rain(seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    t = _bed()
    chans = []
    for _ in range(2):
        hiss = tv_band(colored_noise(len(t), 0.4, rng), 1500, 9000) * 0.5
        drops = np.zeros_like(t)
        idx = rng.integers(0, len(t) - 400, size=int(BED * 60))
        kern = np.exp(-np.arange(400) / 40) * rng.standard_normal(400)
        for i in idx:
            drops[i:i + 400] += kern * rng.uniform(0.2, 1.0)
        chans.append(hiss + tv_band(drops, 1200, 7000) * 0.6)
    return finish(loopable(np.stack(chans, axis=1)), peak_db=-6, rms_db=-24)


def ocean(seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    t = _bed()
    wave_e = 0.25 + 0.75 * (0.5 + 0.5 * np.sin(2 * np.pi * t / (BED / 3) - np.pi / 2)) ** 2.5
    chans = []
    for sh in (0, 0.6):
        e = np.roll(wave_e, int(sh * SR))
        chans.append(tv_band(colored_noise(len(t), 1.3, rng), 120, 600 + 2600 * e) * e)
    return finish(loopable(np.stack(chans, axis=1)), peak_db=-6, rms_db=-24)


# ---------------------------------------------------------------- каталог

A3, C4, Cs4, D4, E4, Fs4, G4, A4, B4, Cs5, E5 = 220, 261.6, 277.2, 293.7, 329.6, 370.0, 392.0, 440, 493.9, 554.4, 659.3

CATALOG = [
    # (категория, файл, аталыш, функция, теги, маанай)
    ("transitions", "whoosh_soft_01", "Soft whoosh (left→right)", lambda: whoosh(1.3, 0.38, 1, 11),
     ["whoosh", "soft", "air"], ["calm", "reflective", "hopeful", "inspired"]),
    ("transitions", "whoosh_soft_02", "Soft whoosh (right→left)", lambda: whoosh(1.1, 0.32, -1, 12),
     ["whoosh", "soft", "air"], ["determined", "tense", "dramatic"]),
    ("transitions", "swish_short_03", "Short swish", lambda: whoosh(0.7, 0.22, 1, 13),
     ["swish", "fast"], ["determined", "inspired"]),
    ("impact", "boom_low_01", "Low cinematic boom", lambda: boom(2.6, 75, 38, 0.65, 21),
     ["boom", "deep", "hit"], ["dramatic", "tense"]),
    ("impact", "hit_soft_02", "Soft punch hit", lambda: boom(1.8, 110, 55, 0.32, 22),
     ["hit", "punch"], ["determined", "dramatic"]),
    ("cinematic", "braam_hit_01", "Soft cinematic braam", lambda: braam(3.0, 55, 31),
     ["braam", "trailer", "deep"], ["inspired", "determined", "dramatic"]),
    ("cinematic", "sub_drop_02", "Sub drop with air", lambda: sub_drop(2.4, 32),
     ["drop", "sub"], ["hopeful", "tense"]),
    ("emotional", "chime_chord_01", "Warm chime chord (A major)", lambda: chord(3.5, [A4, Cs5, E5], True, 41),
     ["chime", "bell", "warm"], ["hopeful", "inspired"]),
    ("emotional", "piano_chord_02", "Soft keys chord (D major)", lambda: chord(3.5, [D4, Fs4, A4], False, 42),
     ["keys", "piano", "soft"], ["hopeful", "reflective", "sad"]),
    ("emotional", "pad_swell_03", "Gentle pad swell (E minor)", lambda: pad_swell(3.5, [E4, G4, B4], 43),
     ["pad", "swell"], ["reflective", "sad", "calm"]),
    ("atmosphere", "room_drone_01", "Low warm room drone (loop)", lambda: room_drone(51),
     ["drone", "room", "low"], ["calm", "reflective", "sad"]),
    ("atmosphere", "air_tone_02", "Soft air tone (loop)", lambda: air_tone(52),
     ["air", "room", "quiet"], ["calm", "reflective"]),
    ("nature", "wind_01", "Gentle wind (loop)", lambda: wind(61),
     ["wind", "field", "mountain", "grass", "sky", "forest", "tree", "nature"], ["calm", "reflective", "sad"]),
    ("nature", "rain_02", "Light rain (loop)", lambda: rain(62),
     ["rain", "storm", "night", "window"], ["sad", "reflective", "calm"]),
    ("nature", "ocean_waves_03", "Soft ocean waves (loop)", lambda: ocean(63),
     ["sea", "ocean", "wave", "waves", "beach", "water", "lake"], ["calm", "hopeful", "reflective"]),
]


def write_wav(path: Path, st: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pcm = (np.clip(st, -1, 1) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())


def generate(out: Path, today: str | None = None) -> list[dict]:
    today = today or date.today().isoformat()
    items = []
    for cat, stem, title, fn, tags, moods in CATALOG:
        wav = out / cat / f"{stem}.wav"
        write_wav(wav, fn())
        digest = hashlib.sha256(wav.read_bytes()).hexdigest()
        meta = {"title": title, "file": wav.name, "category": cat,
                "source": "Original — synthesized by YouTube_Auto_Pipeline (pipeline/sfx_synth.py)",
                "source_url": SCRIPT_URL, "author": "YouTube_Auto_Pipeline (channel owner)",
                "license": LICENSE[0], "license_url": LICENSE[1], "commercial_use": True,
                "attribution_required": False, "verified_by": "Claude (generated in-house, no third-party audio)",
                "verified_at": today, "tags": tags, "mood": moods, "sha256": digest}
        (out / cat / f"{stem}.metadata.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1),
                                                         encoding="utf-8")
        items.append(meta)
    return items


if __name__ == "__main__":
    dest = Path(sys.argv[1] if len(sys.argv) > 1 else "sfx_out")
    for m in generate(dest):
        print(f"{m['category']}/{m['file']}  {m['sha256'][:12]}")
