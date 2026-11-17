"""Эски ↔ cinematic видеону салыштыруу (TEST): ffprobe, кадрлардын жарык/түс бирдейлиги, капталма-капталы кадрлар.

    VIDEO_ID=Video_003 YTA_DRIVE_FOLDER=YouTube_Auto_TEST python -m pipeline.compare_videos

Drive'дан `Final_Videos/<ID>.mp4` (эски) жана `<ID>_cinematic.mp4` (жаңы) жүктөлөт. Видеолор ӨЗГӨРТҮЛБӨЙТ.
Жыйынтык: логдо таблица, `_diagnose/<ID>_compare.jpg` (сол — эски, оң — жаңы), GitHub run бетинде отчет.
«Бирдейлик» = кадрлардын ортосундагы орточо жарыктын (YAVG) жана каныккандыктын (SATAVG) стандарттык четтөөсү:
аз болсо — кадрлар бири-бирине жакыныраак (ашыкча жарык/караңгы секириктер аз).
"""

from __future__ import annotations

import json
import os
import re
import statistics
import subprocess
import sys
import tempfile
from pathlib import Path

from . import media
from .drive import DriveClient, mask_email


def frame_stats(video: Path, times: list[float]) -> list[dict]:
    out = []
    for t in times:
        r = subprocess.run(["ffmpeg", "-hide_banner", "-v", "info", "-ss", f"{t:.2f}", "-i", str(video),
                            "-frames:v", "1", "-vf", "scale=480:-2,signalstats,metadata=print", "-f", "null", "-"],
                           capture_output=True, text=True)
        y = re.findall(r"YAVG=([\d.]+)", r.stderr)
        s = re.findall(r"SATAVG=([\d.]+)", r.stderr)
        if y:
            out.append({"t": t, "y": float(y[0]), "sat": float(s[0]) if s else 0.0})
    return out


def summary(video: Path) -> dict:
    sd = media.stream_durations(video)
    st = media.probe(video)["streams"]
    v = next(s for s in st if s["codec_type"] == "video")
    return {"video_sec": sd["video"], "audio_sec": sd["audio"], "frames": sd["nb_frames"],
            "size_mb": round(video.stat().st_size / 1e6, 1), "res": f"{v['width']}x{v['height']}",
            "color": f"{v.get('color_space')}/{v.get('color_range')}"}


def side_by_side(old: Path, new: Path, times: list[float], out: Path) -> None:
    tmp = out.parent / "sbs"
    tmp.mkdir(exist_ok=True)
    for i, t in enumerate(times, 1):
        media.run(["ffmpeg", "-y", "-v", "error", "-ss", f"{t:.2f}", "-i", str(old), "-ss", f"{t:.2f}",
                   "-i", str(new), "-filter_complex",
                   "[0:v]scale=640:360[a];[1:v]scale=640:360[b];[a][b]hstack", "-frames:v", "1",
                   str(tmp / f"p_{i:02d}.jpg")], "салыштыруу кадры")
    media.run(["ffmpeg", "-y", "-v", "error", "-framerate", "1", "-i", str(tmp / "p_%02d.jpg"),
               "-vf", "tile=2x3", "-frames:v", "1", str(out)], "салыштыруу барагы")


def main() -> int:
    root = os.environ.get("YTA_DRIVE_FOLDER", "YouTube_Auto_TEST")
    vid = os.environ["VIDEO_ID"].strip()
    drive = DriveClient.from_env()
    if drive is None:
        print("❌ GDRIVE_* жок")
        return 2
    print(f"☁️  Drive: {mask_email(drive.whoami())}; {root}/Final_Videos/{vid}[_cinematic].mp4")
    fid = drive.find_path(root, "Final_Videos")
    items = {k: drive.find_file(f"{vid}{k}.mp4", fid) for k in ("", "_cinematic")} if fid else {}
    if not all(items.values()):
        print(f"❌ Видеолор табылган жок: { {k or 'эски': bool(v) for k, v in items.items()} }")
        return 2
    with tempfile.TemporaryDirectory() as d:
        old, new = Path(d) / "old.mp4", Path(d) / "new.mp4"
        drive.download_file(items[""]["id"], old)
        drive.download_file(items["_cinematic"]["id"], new)
        so, sn = summary(old), summary(new)
        dur = min(so["video_sec"] or 0, sn["video_sec"] or 0)
        times = [dur * (i + 0.5) / 40 for i in range(40)]        # 40 чекит — кадрлардын бирдейлиги
        fo, fn = frame_stats(old, times), frame_stats(new, times)

        def spread(fs, key):
            vals = [f[key] for f in fs]
            return round(statistics.pstdev(vals), 2) if len(vals) > 1 else None

        rows = [("Видео узактыгы, сек", so["video_sec"], sn["video_sec"]),
                ("Аудио узактыгы, сек", so["audio_sec"], sn["audio_sec"]),
                ("Кадр саны", so["frames"], sn["frames"]),
                ("Файл, МБ", so["size_mb"], sn["size_mb"]),
                ("Өлчөм", so["res"], sn["res"]),
                ("Түс белгилери", so["color"], sn["color"]),
                ("Орточо жарык (YAVG)", round(statistics.mean(f["y"] for f in fo), 1),
                 round(statistics.mean(f["y"] for f in fn), 1)),
                ("Жарыктын секириги (std, аз=жакшы)", spread(fo, "y"), spread(fn, "y")),
                ("Каныккандыктын секириги (std, аз=жакшы)", spread(fo, "sat"), spread(fn, "sat"))]
        lines = ["| Көрсөткүч | Эски | Cinematic |", "|---|---|---|"] + \
                [f"| {a} | {b} | {c} |" for a, b, c in rows]
        print("\n".join(lines))
        ok_sync = all(abs((s["video_sec"] or 0) - (s["audio_sec"] or 0)) <= 1.0 for s in (so, sn))
        print(f"Видео↔аудио дал келүү: {'✅' if ok_sync else '❌'}")
        sheet = Path(d) / "compare.jpg"
        side_by_side(old, new, [dur * x for x in (0.08, 0.25, 0.42, 0.58, 0.75, 0.92)], sheet)
        folder = drive.ensure_path(root, "_diagnose")
        sid = drive.put_file(sheet, folder, f"{vid}_compare.jpg")
        url = f"https://drive.google.com/file/d/{sid}/view"
        print(f"== САЛЫШТЫРУУ БАРАГЫ (сол — эски, оң — cinematic): {url}")
        path = os.environ.get("GITHUB_STEP_SUMMARY")
        if path:
            with open(path, "a", encoding="utf-8") as f:
                f.write(f"\n## 🎞 {vid}: эски ↔ cinematic\n\n" + "\n".join(lines) +
                        f"\n\n[Салыштыруу барагы (сол — эски, оң — жаңы)]({url})\n")
        Path("compare_result.json").write_text(json.dumps({"old": so, "new": sn, "rows": rows},
                                                          ensure_ascii=False, default=str), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
