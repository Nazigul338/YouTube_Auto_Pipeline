"""Даяр видеону диагностикалоо (GitHub Actions'та): агымдардын узактыгы, кадр саны, PTS,
жана кадрлардын контакт-барагы (Drive'га жүктөлөт — көрүүгө болот).

    VIDEO_ID=Video_001 YTA_DRIVE_FOLDER=YouTube_Auto_TEST python -m pipeline.diagnose

Видеону ӨЗГӨРТПӨЙТ. Drive'га `_diagnose/` папкасына гана контакт-барак жазат.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from . import media
from .drive import DriveClient, mask_email


def streams_info(path: Path) -> list[dict]:
    info = media.probe(path)
    out = []
    for s in info["streams"]:
        out.append({k: s.get(k) for k in (
            "codec_type", "codec_name", "width", "height", "r_frame_rate", "avg_frame_rate",
            "time_base", "start_time", "duration", "nb_frames", "sample_rate", "channels")})
    return [{"format_duration": info["format"].get("duration"),
             "format_start": info["format"].get("start_time")}] + out


def frame_pts(path: Path) -> list[float]:
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                        "frame=pts_time", "-of", "csv=p=0", str(path)],
                       capture_output=True, text=True)
    return [float(x) for x in r.stdout.split() if x.replace(".", "", 1).replace("-", "", 1).isdigit()]


def pts_report(pts: list[float], audio_dur: float) -> dict:
    if not pts:
        return {"frames": 0}
    deltas = [b - a for a, b in zip(pts, pts[1:])]
    deltas_sorted = sorted(deltas)
    n = len(deltas_sorted)
    return {
        "frames": len(pts),
        "first_pts": round(pts[0], 3), "last_pts": round(pts[-1], 3),
        "expected_frames_at_30fps": round(audio_dur * 30),
        "delta_median": round(deltas_sorted[n // 2], 5) if n else None,
        "delta_max": round(max(deltas), 3) if n else None,
        "delta_min": round(min(deltas), 5) if n else None,
        "frames_with_pts_after_last_second": sum(1 for p in pts if p > pts[-1] - 1),
        "pts_monotonic": all(d >= 0 for d in deltas),
        "gaps_over_1s": [round(pts[i], 2) for i, d in enumerate(deltas) if d > 1.0][:10],
    }


def contact_sheet(video: Path, audio_dur: float, out: Path, n: int = 12) -> list[float]:
    """n кадр аудионун бүт узактыгына бирдей бөлүнүп алынат; жок болсо — кара."""
    times = [audio_dur * (i + 0.5) / n for i in range(n)]
    tmp = out.parent / "frames"
    tmp.mkdir(exist_ok=True)
    for i, t in enumerate(times, 1):
        f = tmp / f"f_{i:02d}.jpg"
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", f"{t:.2f}", "-i", str(video),
                        "-frames:v", "1", "-vf", "scale=480:270", str(f)], capture_output=True)
        if not f.exists() or f.stat().st_size < 500:
            subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
                            "color=c=red:s=480x270", "-frames:v", "1", str(f)], check=True)
    media.run(["ffmpeg", "-y", "-v", "error", "-framerate", "1", "-i", str(tmp / "f_%02d.jpg"),
               "-vf", "tile=4x3", "-frames:v", "1", str(out)], "контакт-барак")
    return [round(t, 1) for t in times]


def main() -> int:
    root = os.environ.get("YTA_DRIVE_FOLDER", "YouTube_Auto_TEST")
    vid = os.environ["VIDEO_ID"].strip()
    drive = DriveClient.from_env()
    if drive is None:
        print("❌ GDRIVE_* жок")
        return 2
    print(f"☁️  Drive: {mask_email(drive.whoami())}; {root}/Final_Videos/{vid}.mp4")
    fid = drive.find_path(root, "Final_Videos")
    item = drive.find_file(f"{vid}.mp4", fid) if fid else None
    if not item:
        print("❌ Видео табылган жок")
        return 2
    with tempfile.TemporaryDirectory() as d:
        video = Path(d) / "video.mp4"
        drive.download_file(item["id"], video)
        info = streams_info(video)
        print("== АГЫМДАР ==")
        print(json.dumps(info, ensure_ascii=False, indent=1))
        vdur = next((float(s["duration"]) for s in info[1:] if s["codec_type"] == "video"
                     and s.get("duration")), 0.0)
        adur = next((float(s["duration"]) for s in info[1:] if s["codec_type"] == "audio"
                     and s.get("duration")), 0.0)
        print(f"== ВИДЕО {vdur:.3f} сек | АУДИО {adur:.3f} сек | айырма {adur - vdur:.3f} сек ==")
        rep = pts_report(frame_pts(video), adur or vdur)
        print("== PTS ==")
        print(json.dumps(rep, ensure_ascii=False, indent=1))
        sheet = Path(d) / "sheet.jpg"
        times = contact_sheet(video, adur or vdur, sheet)
        folder = drive.ensure_path(root, "_diagnose")
        sid = drive.put_file(sheet, folder, f"{vid}_contact_sheet.jpg")
        print(f"== КОНТАКТ-БАРАК: Drive {root}/_diagnose/{vid}_contact_sheet.jpg (id {sid}); "
              f"секунддар: {times}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
