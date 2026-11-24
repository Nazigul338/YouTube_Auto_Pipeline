"""Фондук музыканы өзүбүз жаратабыз (лицензия маселеси жок — өз чыгармабыз).

Стиль: жумшак акустикалык гитара (Karplus-Strong синтези) + жылуу фон (pad) + жеңил ревербрация.
Ар видео өз обонун алат: тон, темп, аккорд ырааты, арпеджио үлгүсү seed'ден (пост ID) тандалат —
бир эле трек кайталанбайт (оригиналдуулук эрежеси).
"""
import hashlib
import json
import wave

import numpy as np
from scipy.signal import lfilter

SR = 44100
NOTE = {"C": 0, "C#": 1, "D": 2, "D#": 3, "E": 4, "F": 5, "F#": 6, "G": 7, "G#": 8, "A": 9, "A#": 10, "B": 11}
KEYS = ["C", "D", "E", "F", "G", "A"]
MAJOR = [0, 2, 4, 5, 7, 9, 11]
# ступендер (0 = I). Жылуу, тынч, «айыл» маанайындагы ырааттар
PROGRESSIONS = {
    "warm": [[0, 4, 5, 3], [0, 5, 3, 4], [0, 3, 0, 4], [5, 3, 0, 4], [0, 3, 5, 4]],
    "calm": [[0, 3, 0, 3], [0, 5, 3, 0], [3, 0, 4, 0]],
}
PATTERNS = [[0, 1, 2, 1, 3, 1, 2, 1], [0, 2, 1, 2, 3, 2, 1, 2], [0, 1, 2, 3, 2, 1, 2, 1], [0, 2, 3, 2, 1, 2, 3, 2]]


def _freq(midi):
    return 440.0 * 2 ** ((midi - 69) / 12)


def pluck(freq, seconds, rng, damping=0.996, brightness=0.5):
    """Karplus-Strong кылдын үнү (lfilter — тез)."""
    n = int(SR * seconds)
    period = max(2, int(round(SR / freq)))
    burst = rng.uniform(-1, 1, period)
    burst = lfilter([brightness, 1 - brightness], [1], burst)        # жумшак чертүү
    x = np.zeros(n); x[:period] = burst
    a = np.zeros(period + 2); a[0] = 1; a[period] = -0.5 * damping; a[period + 1] = -0.5 * damping
    y = lfilter([1], a, x)
    return y / (np.max(np.abs(y)) + 1e-9)


def chord_midis(key, degree, octave=3):
    root = 12 * (octave + 1) + NOTE[key]
    return [root + MAJOR[(degree + i) % 7] + 12 * ((degree + i) // 7) for i in (0, 2, 4)]


def reverb(x, mix=0.25):
    out = np.zeros_like(x)
    for d, g in ((1557, 0.77), (1617, 0.74), (1491, 0.75), (1422, 0.73)):      # Schroeder comb
        a = np.zeros(d + 1); a[0] = 1; a[d] = -g
        out += lfilter([1], a, x)
    for d, g in ((225, 0.7), (556, 0.7)):                                     # allpass
        b = np.zeros(d + 1); b[0] = -g; b[d] = 1
        a = np.zeros(d + 1); a[0] = 1; a[d] = -g
        out = lfilter(b, a, out)
    return (1 - mix) * x + mix * out / 4


def plan(seed_text, mood="warm"):
    h = int(hashlib.sha1(seed_text.encode("utf-8")).hexdigest(), 16)
    progs = PROGRESSIONS.get(mood, PROGRESSIONS["warm"])
    return {"key": KEYS[h % len(KEYS)], "bpm": 78 + (h >> 8) % 19, "progression": progs[(h >> 16) % len(progs)],
            "pattern": PATTERNS[(h >> 24) % len(PATTERNS)], "seed": h % (2 ** 32), "mood": mood}


def generate(path, seconds, seed_text, mood="warm"):
    """seconds узундуктагы стерео WAV жазат; кайтарат: колдонулган параметрлер (лицензия жазуусу үчүн)."""
    p = plan(seed_text, mood)
    rng = np.random.default_rng(p["seed"])
    n = int(SR * (seconds + 2))
    L, R = np.zeros(n), np.zeros(n)
    beat = 60.0 / p["bpm"]; step = beat / 2                     # 8-нота арпеджио
    bar = 4 * beat
    cache = {}
    t, i = 0.0, 0
    while t < seconds + 1:
        degree = p["progression"][int(t // bar) % len(p["progression"])]
        notes = chord_midis(p["key"], degree, 3)
        # арпеджио: бас + аккорд тондору (бир октава жогору)
        pool = [notes[0] - 12, notes[0], notes[1], notes[2]]
        midi = pool[p["pattern"][i % len(p["pattern"])]]
        if midi not in cache:
            cache[midi] = pluck(_freq(midi), 2.2, rng, brightness=0.45)
        s = cache[midi] * (0.55 if i % 8 == 0 else 0.38) * rng.uniform(0.85, 1.0)
        a = int(t * SR); b = min(n, a + len(s))
        pan = 0.5 + 0.25 * np.sin(i * 0.7)                         # жеңил стерео кыймыл
        L[a:b] += s[:b - a] * (1 - pan) * 2; R[a:b] += s[:b - a] * pan * 2
        t += step; i += 1
    # жылуу фон: аккорддун тондору, жай кирип-чыгуу, детюн
    tt = np.arange(n) / SR
    pad = np.zeros(n)
    for k in range(int(np.ceil((seconds + 2) / bar))):
        degree = p["progression"][k % len(p["progression"])]
        a = int(k * bar * SR); b = min(n, int((k + 1) * bar * SR) + int(0.5 * SR))
        seg = tt[a:b] - tt[a]
        env = np.minimum(1, seg / 0.8) * np.minimum(1, np.maximum(0, (bar + 0.5 - seg) / 0.8))
        for m in chord_midis(p["key"], degree, 4):
            f = _freq(m)
            pad[a:b] += env * (np.sin(2 * np.pi * f * seg) + 0.6 * np.sin(2 * np.pi * f * 1.003 * seg)) * 0.05
    pad = lfilter([0.08], [1, -0.92], pad)                          # жумшартуу (low-pass)
    L += pad; R += pad
    L, R = reverb(L), reverb(R)
    # башы/аягы акырын
    fade = int(1.5 * SR)
    for ch in (L, R):
        ch[:fade] *= np.linspace(0, 1, fade)
        end = int(seconds * SR); ch[end - fade:end] *= np.linspace(1, 0, fade); ch[end:] = 0
    st = np.stack([L[:int(seconds * SR)], R[:int(seconds * SR)]], axis=1)
    st = st / (np.max(np.abs(st)) + 1e-9) * 0.7
    with wave.open(path, "wb") as w:
        w.setnchannels(2); w.setsampwidth(2); w.setframerate(SR)
        w.writeframes((st * 32767).astype("<i2").tobytes())
    return {"source": "generated", "license": "own composition (poultry_ig_agent/music_gen.py)",
            "key": p["key"], "bpm": p["bpm"], "progression": p["progression"], "mood": mood}


if __name__ == "__main__":
    import sys
    print(json.dumps(generate(sys.argv[1], float(sys.argv[2]), sys.argv[3]), ensure_ascii=False))
