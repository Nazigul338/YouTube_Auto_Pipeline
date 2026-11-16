"""FFmpeg/ffprobe жардамчылары (бардык этаптар колдонот)."""

from __future__ import annotations

import json
import re
import subprocess
import wave
from pathlib import Path

from .errors import StageError


def run(cmd: list[str], what: str = "ffmpeg", timeout: int = 3600) -> str:
    """Буйрукту аткарат; ката болсо stderr'дин аягы менен түшүнүктүү StageError."""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise StageError(f"{what}: {timeout} сек ичинде бүткөн жок")
    if r.returncode != 0:
        tail = "\n".join((r.stderr or "").strip().splitlines()[-12:])
        raise StageError(f"{what} катасы (код {r.returncode}):\n{tail}")
    return (r.stdout or "") + (r.stderr or "")


def probe(path: Path) -> dict:
    out = run(["ffprobe", "-v", "error", "-show_format", "-show_streams", "-of", "json", str(path)],
              "ffprobe")
    return json.loads(out[: out.rfind("}") + 1])


def duration(path: Path) -> float:
    return float(probe(path)["format"]["duration"])


def write_wav(path: Path, pcm: bytes, rate: int) -> float:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm)
    return len(pcm) / 2 / rate


def silences(path: Path, noise_db: float = -40, min_len: float = 1.5) -> list[tuple[float, float]]:
    """[(башталышы, узактыгы)] — min_len'ден узун тынчтыктар."""
    out = run(["ffmpeg", "-hide_banner", "-i", str(path), "-af",
               f"silencedetect=noise={noise_db}dB:d={min_len}", "-f", "null", "-"], "silencedetect")
    starts = [float(x) for x in re.findall(r"silence_start: ([\d.]+)", out)]
    durs = [float(x) for x in re.findall(r"silence_duration: ([\d.]+)", out)]
    return list(zip(starts, durs))


def loudness(path: Path) -> dict:
    """EBU R128: integrated LUFS (I), true peak (TP)."""
    out = run(["ffmpeg", "-hide_banner", "-i", str(path), "-af", "ebur128=peak=true",
               "-f", "null", "-"], "ebur128")
    tail = out[out.rfind("Summary:"):]
    i = re.search(r"I:\s+(-?[\d.]+) LUFS", tail)
    tp = re.search(r"Peak:\s+(-?[\d.]+) dBFS", tail)
    return {"I": float(i.group(1)) if i else None, "TP": float(tp.group(1)) if tp else None}


def decode_float32(path: Path, rate: int = 16000):
    """Аудиону numpy float32 массивге (PyAV'сыз, ffmpeg аркылуу)."""
    import numpy as np

    r = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-f", "s16le", "-ac", "1",
                        "-ar", str(rate), "-"], capture_output=True)
    if r.returncode != 0:
        raise StageError(f"Аудиону окуу ишке ашкан жок: {r.stderr.decode()[-300:]}")
    return np.frombuffer(r.stdout, np.int16).astype(np.float32) / 32768.0
