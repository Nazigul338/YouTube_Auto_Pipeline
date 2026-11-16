"""Диагностика (GitHub Actions'та): `concat -c copy` менен жасалган сахна файлын FFmpeg толук декодтойбу?

Video_001'де (FFmpeg 8.0.1) ffprobe сахнада 279 кадр көрсөткөн, бирок ffmpeg аны декодтоодо ~103 кадрда токтоп
калгандай (бир кичине сегмент 8.37 сек ордуна 4.93 сек болгон). Бул скрипт production `render_shot` менен
ар түрдүү клиптерден (fps/түс белгилери/SAR) кадрларды рендерлеп, сахнага `-c copy` менен бириктирип,
ар файлдын: пакеттер, ЧЫНЫГЫ декодтолгон кадрлар, түс/профиль талааларын басып чыгарат.

    python -m pipeline.probe_concat
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

from .stages import s8_render as s8


def sh(*a) -> str:
    r = subprocess.run(list(a), capture_output=True, text=True)
    return (r.stdout or "") + (r.stderr or "")


def info(path: Path) -> dict:
    out = subprocess.run(["ffprobe", "-v", "error", "-count_frames", "-select_streams", "v:0",
                          "-show_entries",
                          "stream=nb_read_packets,nb_read_frames,profile,level,pix_fmt,color_space,"
                          "color_range,color_primaries,color_transfer,sample_aspect_ratio,r_frame_rate,"
                          "time_base,has_b_frames,duration", "-of", "json", str(path)],
                         capture_output=True, text=True).stdout
    s = (json.loads(out or "{}").get("streams") or [{}])[0]
    return s


def decode_frames(path: Path, vf: str | None = None) -> int:
    args = ["ffmpeg", "-v", "error", "-i", str(path), "-an"]
    if vf:
        args += ["-vf", vf]
    args += ["-f", "null", "-"]
    out = sh(*args, "-stats")
    import re
    m = re.findall(r"frame=\s*(\d+)", out)
    return int(m[-1]) if m else -1


def make_clip(path: Path, spec: str, extra: list[str]):
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", spec, *extra, str(path)], check=True)


def main() -> int:
    print(sh("ffmpeg", "-version").splitlines()[0])
    d = Path(tempfile.mkdtemp())
    enc = ["-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p"]
    clips = {
        "plain30": ("testsrc2=size=1920x1080:rate=30:duration=20", enc),
        "fps25": ("testsrc2=size=1920x1080:rate=25:duration=20", enc),
        "fps60": ("testsrc2=size=1920x1080:rate=60:duration=20", enc),
        "bt601": ("testsrc2=size=1920x1080:rate=30:duration=20",
                  enc + ["-colorspace", "smpte170m", "-color_primaries", "smpte170m",
                         "-color_trc", "smpte170m"]),
        "pc_range": ("testsrc2=size=1920x1080:rate=30:duration=20",
                     ["-vf", "format=yuvj420p", "-c:v", "libx264", "-preset", "ultrafast",
                      "-color_range", "pc"]),
        "sar": ("testsrc2=size=1440x1080:rate=30:duration=20", enc + ["-vf", "setsar=4/3"]),
    }
    files = {}
    for name, (spec, extra) in clips.items():
        p = d / f"clip_{name}.mp4"
        make_clip(p, spec, extra)
        files[name] = p
    rows = []
    motions = ["zoom_in", "pan_left", "push_in", "pan_up", "zoom_out", "pan_right"]
    for scene_name, order in {
        "uniform": ["plain30"] * 3,
        "mixed_fps": ["plain30", "fps25", "fps60"],
        "mixed_color": ["plain30", "bt601", "pc_range"],
        "mixed_sar": ["plain30", "sar", "plain30"],
        "all": ["plain30", "fps25", "bt601", "pc_range", "sar", "fps60"],
    }.items():
        shots = []
        for i, c in enumerate(order):
            o = d / f"{scene_name}_shot{i}.mp4"
            s8.render_shot(files[c], o, "video", 1.0, 3.2, motions[i % 6], 1.0)
            shots.append(o)
        lst = d / f"{scene_name}.txt"
        lst.write_text("".join(f"file '{p.name}'\n" for p in shots))
        scene = d / f"{scene_name}_scene.mp4"
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(lst),
                        "-c", "copy", str(scene)], check=True)
        want = round(3.2 * 30) * len(order)
        si = [info(p) for p in shots]
        sc = info(scene)
        dec = decode_frames(scene)
        body = decode_frames(scene, "trim=start_frame=15,setpts=PTS-STARTPTS,tpad=stop_mode=clone:"
                                    "stop_duration=2,fps=30,format=yuv420p")
        row = {"scene": scene_name, "want_frames": want, "packets": sc.get("nb_read_packets"),
               "ffprobe_decoded": sc.get("nb_read_frames"), "ffmpeg_decoded": dec,
               "body_filter_frames(no -frames:v)": body,
               "shot_colors": sorted({(x.get("color_space"), x.get("color_range"),
                                       x.get("sample_aspect_ratio"), x.get("profile"), x.get("level"))
                                      for x in si}, key=str)}
        rows.append(row)
        print(json.dumps(row, ensure_ascii=False), flush=True)
    # тулку: body-чыпка (trim+tpad+fps) кадр жоготпошу керек: want − 15 + 60
    bad = [r for r in rows if r["ffmpeg_decoded"] != r["want_frames"]
           or r["body_filter_frames(no -frames:v)"] != r["want_frames"] - 15 + 60
           or len(r["shot_colors"]) != 1]
    print("RESULT:", "ӨТТҮ (бардык сахналар толук декодтолду)" if not bad else
          f"КАТА: {[r['scene'] for r in bad]} толук декодтолгон жок")
    return 0


if __name__ == "__main__":
    sys.exit(main())
