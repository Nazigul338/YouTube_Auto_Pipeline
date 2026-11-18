"""Камера кыймылы v2 (cinematic СЫНАК режими): жумшак (ease-in-out), мааниге жараша тандалган, текшерилүүчү.

Кыймылдар (бардыгы `zoompan` менен 2× чоңойтулган кадрда — субпикселдик жылмакайлык, секирик жок):
  zoom_in, zoom_out      — акырын жакындоо/алыстоо
  pan_left, pan_right    — солго/оңго жылуу (бир аз чоңойтулган кадрда)
  pan_up, pan_down       — өйдө/төмөн
  ken_burns              — жакындоо + диагоналдык жылуу (бурчтан бурчка)
  dolly (dolly in)       — жакындоо + капталга жылуу (тереңдик сезими; ЧЫНЫГЫ параллакс эмес)
  dolly_out              — алыстоо + капталга жылуу (dolly in'дин тескериси)
  handheld               — табигый «колдогу камера»: төмөн жыштыктагы жумшак тербелүү
ЧЫНЫГЫ parallax (алдыңкы/арткы план өзүнчө жылышы) тереңдик картасын (ML) талап кылат — бекер CPU runner'де
кошулган жок; `dolly` анын жакын жөнөкөй алмашуусу.

Тандоо (`plan_motions`): сахнанын эмоциясы + кадрдын сахнадагы орду (биринчиси — «таанытуучу» план) +
сахна ичинде жылуунун багыты бирдей (кесүүдөн кийин кыймыл үзгүлтүксүз сезилет) + кошуна кадрлар кайталанбайт +
бир түр ≤30%.
"""

from __future__ import annotations

import math
import random

W, H, FPS = 1920, 1080, 30
UPSCALE = 2                      # zoompan 2× чоң кадрда — бүтүн пикселдик кадам 0.5 px болот (жылмакай)

TYPES = ["zoom_in", "zoom_out", "pan_left", "pan_right", "pan_up", "pan_down", "ken_burns", "dolly", "dolly_out",
         "handheld"]
LATERAL = {"pan_left": -1, "pan_right": 1}

# эмоция → ылайыктуу кыймылдар (биринчиси эң мүнөздүү)
BY_EMOTION = {
    "calm": ["pan_right", "pan_left", "ken_burns", "zoom_in"],
    "reflective": ["zoom_in", "ken_burns", "pan_left", "pan_down"],
    "sad": ["zoom_in", "pan_down", "ken_burns", "zoom_out"],
    "hopeful": ["zoom_out", "pan_up", "dolly_out", "pan_right"],
    "inspired": ["pan_up", "dolly_out", "ken_burns", "dolly"],
    "determined": ["pan_right", "dolly", "zoom_in", "pan_up"],
    "tense": ["handheld", "zoom_in", "dolly", "pan_left"],
    "dramatic": ["handheld", "zoom_in", "zoom_out", "dolly"],
}
ESTABLISHING = ["zoom_out", "ken_burns", "dolly_out", "pan_right", "pan_left"]     # сахнанын биринчи кадры
SPEED = {"calm": 0.75, "reflective": 0.7, "sad": 0.6, "hopeful": 0.9, "tense": 1.15,
         "determined": 1.05, "inspired": 1.0, "dramatic": 1.2}
MAX_SHARE = 0.30


def ease(p: str) -> str:
    """smoothstep: жай башталып, жай токтойт. p — 0..1 туюнтма."""
    return f"(({p})*({p})*(3-2*({p})))"


def parse(spec: str) -> tuple[str, int]:
    """'v2:ken_burns@123' → ('ken_burns', 123)."""
    body = spec[3:] if spec.startswith("v2:") else spec
    name, _, seed = body.partition("@")
    return name, int(seed or 0)


def build(motion: str, dur: float, intensity: float = 1.0, seed: int = 0) -> str:
    """Кыймылдын FFmpeg чыпкасы. Кирүү: ар кандай өлчөм → чыгуу 1920×1080, 30 fps."""
    n = max(2, int(round(dur * FPS)))
    p = f"(on/{n - 1})"
    e = ease(p)
    amp = min(0.16, 0.085 * intensity)          # максималдуу масштаб өзгөрүүсү (8.5% — жумшак)
    big_w, big_h = W * UPSCALE, H * UPSCALE
    cover = (f"scale={big_w}:{big_h}:force_original_aspect_ratio=increase,crop={big_w}:{big_h},"
             f"setsar=1,fps={FPS}")
    cx, cy = "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"
    free_x, free_y = "(iw-iw/zoom)", "(ih-ih/zoom)"          # жылууга болгон аралык
    rnd = random.Random(seed)
    if motion == "zoom_in":
        z, x, y = f"1+{amp:.4f}*{e}", cx, cy
    elif motion == "zoom_out":
        z, x, y = f"1+{amp:.4f}*(1-{e})", cx, cy
    elif motion in ("pan_left", "pan_right", "pan_up", "pan_down"):
        zc = 1 + max(0.06, amp)                                # бир аз чоңойтуп, ошол чекте жылабыз
        z = f"{zc:.4f}"
        if motion == "pan_right":
            x, y = f"{free_x}*{e}", cy
        elif motion == "pan_left":
            x, y = f"{free_x}*(1-{e})", cy
        elif motion == "pan_up":
            x, y = cx, f"{free_y}*(1-{e})"
        else:
            x, y = cx, f"{free_y}*{e}"
    elif motion == "ken_burns":
        sx, sy = rnd.choice([(0.15, 0.2), (0.85, 0.2), (0.15, 0.8), (0.85, 0.8)])
        ex, ey = 1 - sx, 1 - sy
        z = f"1+{amp * 0.4:.4f}+{amp * 0.6:.4f}*{e}"
        x = f"{free_x}*({sx}+({ex}-{sx})*{e})"
        y = f"{free_y}*({sy}+({ey}-{sy})*{e})"
    elif motion in ("dolly", "dolly_out"):
        d = rnd.choice([-1, 1])
        z = f"1+{amp:.4f}*{e}" if motion == "dolly" else f"1+{amp:.4f}*(1-{e})"
        x = f"{free_x}*(0.5+{0.35 * d}*{e})"
        y = cy
    elif motion == "handheld":
        z = f"{1 + max(0.05, amp * 0.7):.4f}"
        f1, f2 = 0.37 + rnd.random() * 0.2, 0.23 + rnd.random() * 0.15
        ph1, ph2 = rnd.random() * 6.28, rnd.random() * 6.28
        x = f"{free_x}*(0.5+0.32*sin(2*PI*{f1:.3f}*on/{FPS}+{ph1:.2f})+0.12*sin(2*PI*{f2 * 2.3:.3f}*on/{FPS}))"
        y = f"{free_y}*(0.5+0.30*sin(2*PI*{f2:.3f}*on/{FPS}+{ph2:.2f}))"
    else:
        raise ValueError(f"белгисиз кыймыл: {motion}")
    return f"{cover},zoompan=z='{z}':x='{x}':y='{y}':d=1:s={W}x{H}:fps={FPS}"


def plan_motions(shots: list[dict], scenes: dict, rng: random.Random) -> list[dict]:
    """[{i, motion, intensity, seed}] — мааниге, позицияга жана ар түрдүүлүккө жараша."""
    out, prev, counts = [], None, {t: 0 for t in TYPES}
    limit = max(2, math.ceil(MAX_SHARE * len(shots)))
    scene_dir: dict = {}
    for k, sh in enumerate(shots):
        sc = scenes.get(sh["scene"], {})
        emo = sc.get("emotion", "reflective")
        first = k == 0 or shots[k - 1]["scene"] != sh["scene"]
        pool = list(ESTABLISHING if first and emo not in ("tense", "dramatic") else BY_EMOTION.get(emo, TYPES))
        pool += [t for t in TYPES if t not in pool]                 # запас — бардык түрлөр
        cand = [t for t in pool if t != prev and counts[t] < limit]
        if sh.get("kind") == "image":                                # сүрөт — Ken Burns кыймылы табигый
            cand = [t for t in cand if t in ("ken_burns", "zoom_in", "zoom_out", "dolly", "dolly_out")] or cand
        # сахна ичинде капталдагы жылуунун багыты бирдей (кесүү үзгүлтүксүз сезилет)
        d = scene_dir.get(sh["scene"])
        if d is not None:
            cand = [t for t in cand if LATERAL.get(t, d) == d] or cand
        head = cand[:3] if cand[:3] else TYPES
        motion = rng.choice(head) if rng.random() < 0.8 else rng.choice(cand or TYPES)
        if motion in LATERAL and sh["scene"] not in scene_dir:
            scene_dir[sh["scene"]] = LATERAL[motion]
        counts[motion] += 1
        prev = motion
        inten = SPEED.get(emo, 1.0) * (1.2 if sh.get("kind") == "image" else 1.0)
        seed = rng.randrange(10 ** 6)
        out.append({"i": sh["i"], "motion": f"v2:{motion}@{seed}", "intensity": round(inten, 2)})
    return out


# ---------------------------------------------------------------- текшерүү (QA): кыймыл чындап барбы
MW, MH = 256, 144


def _frame(path, t: float):
    import subprocess

    import numpy as np

    r = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{t:.3f}", "-i", str(path), "-frames:v", "1", "-vf",
                        f"scale={MW}:{MH},format=gray", "-f", "rawvideo", "-"], capture_output=True, timeout=60)
    if len(r.stdout) < MW * MH:
        return None
    return np.frombuffer(r.stdout[:MW * MH], np.uint8).astype(np.float32)


def _scale_center(a, s: float):
    """Кадрды борборунан s эсе чоңойтот (s>1 — жакындоо), nearest."""
    import numpy as np

    ys = (np.arange(MH) - MH / 2) / s + MH / 2
    xs = (np.arange(MW) - MW / 2) / s + MW / 2
    yi = np.clip(ys.round().astype(int), 0, MH - 1)
    xi = np.clip(xs.round().astype(int), 0, MW - 1)
    return a[np.ix_(yi, xi)]


def _shift(a, b):
    """Фазалык корреляция: b ≈ a жылдырылган (dx, dy) пиксель (256×144 масштабында)."""
    import numpy as np

    fa, fb = np.fft.fft2(a - a.mean()), np.fft.fft2(b - b.mean())
    r = fb * np.conj(fa)
    r /= np.abs(r) + 1e-9
    c = np.abs(np.fft.ifft2(r))
    y, x = np.unravel_index(int(np.argmax(c)), c.shape)
    if y > MH // 2:
        y -= MH
    if x > MW // 2:
        x -= MW
    return float(x), float(y)


def measure(path, dur: float) -> dict:
    """Кадрдын башы (12%) жана аягы (88%) салыштырылат: жылыш (dx, dy — 1920 px масштабында), масштаб,
    жалпы өзгөрүү. Статикалык кадр: жылыш ≈0, масштаб ≈1, айырма ≈0."""
    import numpy as np

    a, b = _frame(path, dur * 0.12), _frame(path, dur * 0.88)
    if a is None or b is None:
        return {"ok": False, "why": "кадр окулган жок"}
    a2, b2 = a.reshape(MH, MW), b.reshape(MH, MW)
    best_s, best_e = 1.0, float(np.mean(np.abs(a2 - b2)))
    for s in np.arange(0.86, 1.161, 0.01):
        e = float(np.mean(np.abs(_scale_center(a2, s)[12:-12, 20:-20] - b2[12:-12, 20:-20])))
        if e < best_e - 0.05:
            best_s, best_e = float(s), e
    dx, dy = _shift(a2, b2)
    k = W / MW
    return {"ok": True, "dx": round(dx * k, 1), "dy": round(dy * k, 1), "scale": round(best_s, 3),
            "diff": round(float(np.mean(np.abs(a2 - b2))), 2)}


def classify(m: dict) -> str:
    """Өлчөөдөн кыймылдын түрү (болжол): zoom_in / zoom_out / pan_* / mixed / static."""
    if not m.get("ok"):
        return "unknown"
    moves = []
    if m["scale"] >= 1.02:
        moves.append("zoom_in")
    elif m["scale"] <= 0.98:
        moves.append("zoom_out")
    if abs(m["dx"]) >= 25:
        moves.append("pan_right" if m["dx"] < 0 else "pan_left")     # камера оңго → сүрөт солго жылат
    if abs(m["dy"]) >= 18:
        moves.append("pan_down" if m["dy"] < 0 else "pan_up")
    if not moves:
        return "static" if m["diff"] < 1.0 else "subtle"
    return moves[0] if len(moves) == 1 else "+".join(moves)


EXPECT = {"zoom_in": {"zoom_in"}, "zoom_out": {"zoom_out"}, "pan_left": {"pan_left"},
          "pan_right": {"pan_right"}, "pan_up": {"pan_up"}, "pan_down": {"pan_down"}}


def matches(planned: str, detected: str) -> bool | None:
    """Пландалган кыймыл аныкталганга дал келеби. ken_burns/dolly/handheld — аралаш, «кыймыл бар» жетиштүү."""
    p = parse(planned)[0]
    if detected in ("unknown",):
        return None
    if p in EXPECT:
        return any(part in EXPECT[p] for part in detected.split("+"))
    return detected not in ("static",)
