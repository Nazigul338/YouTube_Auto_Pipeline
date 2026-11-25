"""Диагностика (2026-11-25): клиптин колдонулган бөлүгүндөгү жарыктык (0–255) убакыт боюнча + blackdetect.
Video_003: кара экран 410.47–411.03 сек эки run'до бирдей — булагы клипте бекен, өтүүдөбү?
Env CLIPS = "url|offset|dur;url|offset|dur". Окуу гана, Drive'га тийбейт."""
import os
import re
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path


def luma_series(path: Path, off: float, dur: float) -> list[float]:
    r = subprocess.run(["ffmpeg", "-v", "info", "-ss", f"{off:.2f}", "-t", f"{dur:.2f}", "-i", str(path), "-vf",
                        "scale=96:-2,fps=10,signalstats,metadata=print:key=lavfi.signalstats.YAVG", "-an", "-f", "null", "-"],
                       capture_output=True, text=True, timeout=120)
    return [round(float(x), 1) for x in re.findall(r"YAVG=([\d.]+)", r.stderr)]


def black(path: Path, off: float, dur: float, d: float, pic: float, pix: float) -> list[str]:
    r = subprocess.run(["ffmpeg", "-v", "info", "-ss", f"{off:.2f}", "-t", f"{dur:.2f}", "-i", str(path), "-vf",
                        f"scale=160:-2,fps=8,blackdetect=d={d}:pic_th={pic}:pix_th={pix}", "-an", "-f", "null", "-"],
                       capture_output=True, text=True, timeout=120)
    return re.findall(r"black_start:[\d.]+ black_end:[\d.]+ black_duration:[\d.]+", r.stderr)


def main() -> int:
    for spec in filter(None, os.environ.get("CLIPS", "").split(";")):
        url, off, dur = spec.split("|")
        off, dur = float(off), float(dur)
        d = Path(tempfile.mkdtemp())
        p = d / "c.mp4"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        p.write_bytes(urllib.request.urlopen(req, timeout=120).read())
        print(f"\n== {url.rsplit('/', 1)[-1]} offset {off} dur {dur} (файл {p.stat().st_size // 1024} КБ)")
        print("   жарыктык /0.1 сек:", luma_series(p, off, dur))
        print("   blackdetect QA (0.5/0.98/0.04):", black(p, off, dur, 0.5, 0.98, 0.04))
        print("   blackdetect s5 (0.25/0.95/0.07):", black(p, off, dur, 0.25, 0.95, 0.07))
    return 0


if __name__ == "__main__":
    sys.exit(main())
