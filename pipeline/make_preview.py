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
        print(msg)
        path = os.environ.get("GITHUB_STEP_SUMMARY")
        if path:
            with open(path, "a", encoding="utf-8") as f:
                f.write(f"## ▶️ [Үзүндүнү көрүү]({url})\n\n{msg}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
