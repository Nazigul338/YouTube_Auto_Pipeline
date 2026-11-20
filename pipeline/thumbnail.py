"""Видеонун ӨЗ кадрынан обложка (1280×720, JPG): түс күчөтүлөт, сол жакта караңгы градиент, чоң кызыктуу жазуу.

    VIDEO_FILE=Video_001_cinematic.mp4 THUMBS='14|ВЫ ЖИВЁТЕ|ДЛЯ НИХ?;300|ТИХАЯ|МЕСТЬ' \
    YTA_DRIVE_FOLDER=YouTube_Auto_TEST python -m pipeline.thumbnail

THUMBS: `сек|1-сап|2-сап` вариант, `;` менен бөлүнөт. Натыйжа: Drive → <root>/Thumbnails/<ID>_thumb_<N>.jpg
жана бардык варианттар бир барakta (<ID>_thumbs.jpg). Кадр — видеонун лицензиясы катталган материалы
(Pixabay/Pexels), жазуу — оригиналдуу; бөтөн логотип/адамдын сүрөтү кошулбайт.
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


def font_file() -> str:
    for q in FONT_CANDIDATES:
        try:
            r = subprocess.run(["fc-match", "-f", "%{file}", q], capture_output=True, text=True, timeout=10)
            fam = subprocess.run(["fc-match", "-f", "%{family}", q], capture_output=True, text=True, timeout=10)
            if r.stdout and q.split(":")[0].lower() in fam.stdout.lower():
                return r.stdout
        except (OSError, subprocess.TimeoutExpired):
            continue
    return ""


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


def make(src: Path, t: float, line1: str, line2: str, out: Path, work: Path) -> Path:
    frame = work / f"f_{int(t * 10)}.png"
    media.run(["ffmpeg", "-y", "-v", "error", "-ss", f"{t:.2f}", "-i", str(src), "-frames:v", "1", str(frame)],
              "обложка кадры")
    t1, t2 = work / f"l1_{int(t * 10)}.txt", work / f"l2_{int(t * 10)}.txt"
    t1.write_text(line1, encoding="utf-8")
    t2.write_text(line2, encoding="utf-8")
    font = font_file()
    ff = f"fontfile='{font}':" if font else ""
    s1, s2 = fit_size(line1, 112), fit_size(line2, 158)
    y2 = H - 70 - s2
    y1 = y2 - 18 - s1
    draw = (f"drawtext={ff}textfile='{t1}':fontsize={s1}:fontcolor=white:borderw=5:bordercolor=black@0.85:"
            f"shadowx=4:shadowy=4:shadowcolor=black@0.6:x=58:y={y1},"
            f"drawtext={ff}textfile='{t2}':fontsize={s2}:fontcolor={YELLOW}:borderw=6:bordercolor=black@0.9:"
            f"shadowx=5:shadowy=5:shadowcolor=black@0.6:x=56:y={y2}") if line2 else \
        (f"drawtext={ff}textfile='{t1}':fontsize={s1}:fontcolor=white:borderw=5:bordercolor=black@0.85:x=58:y={H - 70 - s1}")
    graph = (f"[0:v]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},"
             "eq=contrast=1.16:saturation=1.22:brightness=-0.02,unsharp=5:5:0.7,vignette=PI/5[b];"
             f"color=black:s={W}x{H},format=rgba,geq=r=0:g=0:b=0:a='215*pow(max(0\\,1-X/(W*0.7))\\,1.3)'[g];"
             f"[b][g]overlay=format=auto,{draw},format=yuvj420p[o]")
    media.run(["ffmpeg", "-y", "-v", "error", "-i", str(frame), "-filter_complex", graph, "-map", "[o]",
               "-frames:v", "1", "-q:v", "2", str(out)], "обложка")
    return out


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
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        src = drive.download_file(item["id"], d / "src.mp4")
        folder = drive.ensure_path(root, "Thumbnails")
        files, lines = [], []
        for k, (t, l1, l2) in enumerate(specs, 1):
            out = make(src, t, l1, l2, d / f"{vid}_thumb_{k}.jpg", d)
            files.append(out)
            pid = drive.put_file(out, folder, out.name)
            lines.append(f"🖼 ОБЛОЖКА {k} ({t:.0f} сек, «{l1} {l2}»): https://drive.google.com/file/d/{pid}/view")
        sh = sheet(files, d / f"{vid}_thumbs.jpg")
        sid = drive.put_file(sh, folder, sh.name)
        lines.append(f"📋 БААРЫ БИР БАРАКТА: https://drive.google.com/file/d/{sid}/view")
        msg = "\n".join(lines)
        print(msg)
        path = os.environ.get("GITHUB_STEP_SUMMARY")
        if path:
            with open(path, "a", encoding="utf-8") as f:
                f.write(msg + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
