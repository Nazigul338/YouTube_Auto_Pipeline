"""Угулуучу фондук музыка (СЫНАК): колдонуучу 2026-11-20 «фоновой музыка жок го» деди.

Мурунку жол: −31 LUFS + ratio 6 басаңдатуу → сүйлөө учурунда музыка диктордон ~27 LU акырын (угулбайт).
Жаңы (cinematic гана): −21 LUFS + жумшак басаңдатуу → ~12 LU акырын (угулат, дикторду баспайт).
"""

import shutil
import tempfile
import unittest
import wave
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from pipeline import media
from pipeline.stages import s7_music

SR = 48000


def write(path: Path, x: np.ndarray, ch: int = 1):
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as f:
        f.setnchannels(ch)
        f.setsampwidth(2)
        f.setframerate(SR)
        f.writeframes((np.clip(x, -1, 1) * 32767).astype("<i2").tobytes())


class TestAudibleMusic(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp())
        rng = np.random.default_rng(1)
        T = 40
        t = np.arange(T * SR) / SR
        env = np.zeros_like(t)
        pos = 0.3
        while pos < T - 1:                       # сүйлөөгө окшош: фразалар + паузалар
            L = rng.uniform(3, 6)
            a, b = int(pos * SR), int(min(T, pos + L) * SR)
            env[a:b] = np.clip(np.sin(2 * np.pi * 4.5 * t[a:b]) * 0.5 + 0.6, 0, 1)
            pos += L + rng.uniform(0.4, 0.9)
        spec = np.fft.rfft(rng.standard_normal(len(t)))
        f = np.fft.rfftfreq(len(t), 1 / SR)
        spec *= ((f > 150) & (f < 4000)) / np.sqrt(np.maximum(f, 1) / 200)
        v = np.fft.irfft(spec, len(t))
        write(self.d / "raw.wav", v / np.max(np.abs(v)) * env * 0.8)
        (self.d / "audio").mkdir()
        media.run(["ffmpeg", "-y", "-v", "error", "-i", str(self.d / "raw.wav"), "-af", "loudnorm=I=-17:TP=-2",
                   "-ar", "24000", str(self.d / "audio" / "voice.wav")])
        m = sum(np.sin(2 * np.pi * fr * t) * 0.2 for fr in (220, 277, 330, 440))
        write(self.d / "m.wav", np.stack([m, m], 1).ravel() / 2, 2)
        self.ctx = SimpleNamespace(path=lambda *p: self.d.joinpath(*p), log=lambda *_: None)

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def test_audible_profile_in_range_default_unchanged(self):
        r = s7_music.mix(self.ctx, self.d / "m.wav", 40.0, audible=True)
        rel = r["voice_lufs"] - r["music_ducked_lufs"]
        lo, hi = s7_music.AUDIBLE_RANGE
        self.assertTrue(lo <= rel <= hi, rel)
        self.assertAlmostEqual(r["mix"]["I"], -14, delta=1.0)
        d = s7_music.mix(self.ctx, self.d / "m.wav", 40.0)          # негизги жол: өзгөргөн жок
        self.assertNotIn("music_ducked_lufs", d)
        self.assertAlmostEqual(d["bed_lufs"], s7_music.MUSIC_BED_LUFS, delta=1.0)


if __name__ == "__main__":
    unittest.main()
