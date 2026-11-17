"""Мүнөт сайын сапаттын бирдейлиги (QA, сынак режими): видео 8 мүнөт бою башынан аягына чейин бирдей бекенби.

Ар мүнөттө өлчөнөт: жарык, каныккандык, курчтук (Laplacian), үндүн катуулугу (LUFS, short-term), диктордун темпи
(сөз/мүн). Мүнөт «чыгып калды» деп эсептелет эгер бүт видеонун медианасынан кескин айырмаланса:
  жарык ±22 (0–255), каныккандык ×0.65…×1.5, курчтук <45%, катуулук ±3 LU, темп 90…170 сөз/мүн.
Натыйжа: [{minute, brightness, saturation, sharpness, loudness, wpm, flags}], `uniformity.json`.
"""

from __future__ import annotations

import re
import statistics
import subprocess
from pathlib import Path

W, H = 320, 180
BRIGHT_TOL, SAT_LO, SAT_HI, SHARP_MIN, LOUD_TOL = 22.0, 0.65, 1.5, 0.45, 3.0
WPM_MIN, WPM_MAX = 90, 170


def frame_metrics(rgb: bytes) -> dict:
    import numpy as np

    a = np.frombuffer(rgb, np.uint8).reshape(H, W, 3).astype(np.float32)
    gray = a.mean(axis=2)
    mx, mn = a.max(axis=2), a.min(axis=2)
    sat = float(np.mean((mx - mn) / np.maximum(mx, 1.0)))
    lap = (gray[1:-1, 1:-1] * 4 - gray[:-2, 1:-1] - gray[2:, 1:-1] - gray[1:-1, :-2] - gray[1:-1, 2:])
    return {"y": float(gray.mean()), "sat": sat, "sharp": float(lap.var())}


def sample(video: Path, total: float, every: float = 20.0) -> list[tuple[float, dict]]:
    """Ар `every` сек сайын бир кадр (бир ffmpeg өтүү). [(убакыт, метрика)]"""
    r = subprocess.run(["ffmpeg", "-v", "error", "-i", str(video), "-an", "-vf",
                        f"fps=1/{every},scale={W}:{H},format=rgb24", "-f", "rawvideo", "-"],
                       capture_output=True, timeout=3600)
    size = W * H * 3
    out = []
    for k in range(len(r.stdout) // size):
        out.append((k * every, frame_metrics(r.stdout[k * size:(k + 1) * size])))
    return out


def loudness_by_second(video: Path) -> list[tuple[float, float]]:
    """EBU R128 short-term (S) — [(убакыт, LUFS)]; тынчтык (< −70) алынбайт."""
    r = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-v", "info", "-i", str(video), "-vn", "-af",
                        "ebur128=framelog=info", "-f", "null", "-"], capture_output=True, text=True,
                       timeout=3600)
    out = []
    for line in r.stderr.splitlines():
        m = re.search(r"\bt:\s*([\d.]+).*?\bS:\s*(-?[\d.]+)", line)
        if m and float(m.group(2)) > -70:
            out.append((float(m.group(1)), float(m.group(2))))
    return out


def words_per_minute(words: list[dict], minute: int, total: float) -> float | None:
    lo, hi = minute * 60.0, min((minute + 1) * 60.0, total)
    if hi - lo < 20:
        return None
    n = sum(1 for w in words if lo <= w["s"] < hi)
    return n / ((hi - lo) / 60.0)


def build_table(frames: list[tuple[float, dict]], loud: list[tuple[float, float]], words: list[dict],
                total: float) -> list[dict]:
    minutes = int(total // 60) + (1 if total % 60 >= 20 else 0)
    rows = []
    for m in range(minutes):
        fs = [d for t, d in frames if m * 60 <= t < (m + 1) * 60]
        ls = [v for t, v in loud if m * 60 <= t < (m + 1) * 60]
        rows.append({"minute": m + 1,
                     "brightness": round(statistics.mean(f["y"] for f in fs), 1) if fs else None,
                     "saturation": round(statistics.mean(f["sat"] for f in fs), 3) if fs else None,
                     "sharpness": round(statistics.mean(f["sharp"] for f in fs), 1) if fs else None,
                     "loudness": round(statistics.mean(ls), 1) if ls else None,
                     "wpm": (round(words_per_minute(words, m, total), 0) if words_per_minute(words, m, total) else None),
                     "flags": []})

    def med(key):
        vals = [r[key] for r in rows if r[key] is not None]
        return statistics.median(vals) if vals else None

    mb, ms, msh, ml = med("brightness"), med("saturation"), med("sharpness"), med("loudness")
    for r in rows:
        if r["brightness"] is not None and mb is not None and abs(r["brightness"] - mb) > BRIGHT_TOL:
            r["flags"].append(f"жарык {r['brightness']} (медиана {mb:.0f})")
        if r["saturation"] is not None and ms and not SAT_LO <= r["saturation"] / ms <= SAT_HI:
            r["flags"].append(f"каныккандык {r['saturation']} (медиана {ms:.2f})")
        if r["sharpness"] is not None and msh and r["sharpness"] < SHARP_MIN * msh:
            r["flags"].append(f"курчтук {r['sharpness']} (медиана {msh:.0f})")
        if r["loudness"] is not None and ml is not None and abs(r["loudness"] - ml) > LOUD_TOL:
            r["flags"].append(f"катуулук {r['loudness']} LUFS (медиана {ml:.1f})")
        if r["wpm"] is not None and not WPM_MIN <= r["wpm"] <= WPM_MAX:
            r["flags"].append(f"темп {r['wpm']:.0f} сөз/мүн")
    return rows


def analyze(video: Path, total: float, words: list[dict]) -> list[dict]:
    return build_table(sample(video, total), loudness_by_second(video), words, total)


def summary(rows: list[dict]) -> tuple[bool, str]:
    bad = [r for r in rows if r["flags"]]
    if not bad:
        return True, f"{len(rows)} мүнөттүн баары бирдей (жарык, түс, курчтук, катуулук, темп)"
    return False, "; ".join(f"{r['minute']}-мүнөт: {', '.join(r['flags'])}" for r in bad[:4])
