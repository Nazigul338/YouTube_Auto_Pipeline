"""Даяр видеодон телефонго ылайыктуу кыска үзүндү (СЫНАК/көрүү үчүн). Видеонун өзү ӨЗГӨРБӨЙТ.

    VIDEO_FILE=Video_003_cinematic.mp4 VIDEO_ID=Video_003 PREVIEW_SEC=60 YTA_DRIVE_FOLDER=YouTube_Auto_TEST \
        python -m pipeline.make_preview

Үзүндү биринчи HyperFrames/текст карточкасынан ~8 сек мурун башталат (карточка, өтүүлөр жана түс көрүнсүн).
Натыйжа: Drive → <root>/_preview/<файл>_<N>s.mp4 (1080p, H.264 CRF 23, AAC, faststart) жана шилтеме.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

from . import media
from .drive import DriveClient, mask_email


def pick_start(cards: list[dict], total: float, length: float) -> float:
    if cards:
        start = max(0.0, float(cards[0]["start"]) - 8.0)
    else:
        start = max(0.0, total * 0.2)
    return round(min(start, max(0.0, total - length)), 2)


def sheet_times(total: float, n: int = 20) -> list[float]:
    """Бүт видео боюнча бирдей аралыктагы n кадрдын убактысы (көз менен текшерүү барагы үчүн)."""
    return [round(total * (i + 0.5) / n, 2) for i in range(n)] if total > 0 else []


def contact_sheet(src: Path, total: float, out: Path, n: int = 20, cols: int = 4) -> Path:
    """Бүт видеодон n кадр (4 мамыча, 480×270) — бир JPG. Видео өзгөрбөйт."""
    tmp = out.parent / "sheet_frames"
    tmp.mkdir(exist_ok=True)
    for k, t in enumerate(sheet_times(total, n)):
        media.run(["ffmpeg", "-y", "-v", "error", "-ss", f"{t:.2f}", "-i", str(src), "-frames:v", "1",
                   "-vf", "scale=480:270", str(tmp / f"f{k:03d}.png")], "кадр", timeout=120)
    rows = -(-n // cols)
    media.run(["ffmpeg", "-y", "-v", "error", "-framerate", "1", "-i", str(tmp / "f%03d.png"),
               "-vf", f"tile={cols}x{rows}", "-frames:v", "1", "-q:v", "3", str(out)], "барак", timeout=120)
    return out


def main() -> int:
    root = os.environ.get("YTA_DRIVE_FOLDER", "YouTube_Auto_TEST")
    vid = os.environ.get("VIDEO_ID", "Video_003").strip()
    name = os.environ.get("VIDEO_FILE", f"{vid}_cinematic.mp4").strip()
    length = float(os.environ.get("PREVIEW_SEC", "60"))
    drive = DriveClient.from_env()
    if drive is None:
        print("❌ GDRIVE_* жок")
        return 2
    print(f"☁️  Drive: {mask_email(drive.whoami())}; {root}/Final_Videos/{name}")
    fid = drive.find_path(root, "Final_Videos")
    item = drive.find_file(name, fid) if fid else None
    if not item:
        print("❌ Видео табылган жок")
        return 2
    cards = []
    anim = drive.find_path(root, "Projects", vid, "animation")
    cj = drive.find_file("cards.json", anim) if anim else None
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        if cj:
            cards = json.loads(drive.download_file(cj["id"], d / "cards.json").read_text(encoding="utf-8"))
        src = drive.download_file(item["id"], d / "src.mp4")
        total = media.stream_durations(src)["video"] or 0.0
        start = pick_start(cards, total, length)
        out = d / f"{Path(name).stem}_{int(length)}s.mp4"
        media.run(["ffmpeg", "-y", "-v", "error", "-ss", f"{start:.2f}", "-i", str(src), "-t", f"{length:.2f}",
                   "-vf", "fade=t=in:st=0:d=0.4,fade=t=out:st=" + f"{length - 0.8:.2f}" + ":d=0.8,format=yuv420p",
                   "-af", f"afade=t=in:d=0.4,afade=t=out:st={length - 1.0:.2f}:d=1.0",
                   "-c:v", "libx264", "-preset", "medium", "-crf", "23", "-profile:v", "high",
                   "-c:a", "aac", "-b:a", "160k", "-ar", "48000", "-movflags", "+faststart", str(out)],
                  "үзүндү", timeout=1800)
        sd = media.stream_durations(out)
        size = out.stat().st_size / 1e6
        folder = drive.ensure_path(root, "_preview")
        pid = drive.put_file(out, folder, out.name)
        url = f"https://drive.google.com/file/d/{pid}/view"
        msg = (f"✓ Үзүндү: {start:.0f}–{start + length:.0f} сек (карточкалар: {len(cards)}), видео {sd['video']:.2f} сек, "
               f"аудио {sd['audio']:.2f} сек, {size:.1f} МБ\n▶️ ҮЗҮНДҮНҮН ШИЛТЕМЕСИ: {url}")
        try:
            sh = contact_sheet(src, total, d / f"{Path(name).stem}_sheet.jpg")
            sid = drive.put_file(sh, folder, sh.name)
            surl = f"https://drive.google.com/file/d/{sid}/view"
            times = ", ".join(f"{t:.0f}" for t in sheet_times(total))
            msg += f"\n🖼 БҮТ ВИДЕОНУН КАДРЛАРЫ (20, сек: {times}): {surl}"
        except Exception as e:  # барак кошумча — үзүндүгө таасир этпейт
            msg += f"\n⚠️ Кадрлар барагы жасалган жок: {type(e).__name__}"
        print(msg)
        path = os.environ.get("GITHUB_STEP_SUMMARY")
        if path:
            with open(path, "a", encoding="utf-8") as f:
                f.write(f"## ▶️ [Үзүндүнү көрүү]({url})\n\n{msg}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
