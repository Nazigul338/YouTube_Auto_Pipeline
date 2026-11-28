"""Remotion интеграциясы (pipeline/remotion_render.py).

Тез тесттер: CLI жок болгондо түшүнүктүү себеп, шайкештик отчету, FFmpeg бириктирүү (чыныгы ffmpeg, Remotion жок).
Узак тест: чыныгы Remotion рендер (tools/remotion/node_modules бар болсо; YTA_SKIP_SLOW менен өткөрүлөт).
"""

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from pipeline import remotion_render as rr


class TestAvailability(unittest.TestCase):
    def test_missing_cli_reason(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.dict(os.environ, {"YTA_REMOTION_DIR": d}):
            ok, why = rr.available()
        self.assertFalse(ok)
        self.assertIn("npm ci", why)

    def test_flag_off_by_default(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("YTA_REMOTION", None)
            self.assertFalse(rr.enabled())


class TestSyncReport(unittest.TestCase):
    def report(self, flashes, beeps, marks=(1.0, 7.0)):
        with mock.patch.object(rr, "flash_times", return_value=flashes), \
                mock.patch.object(rr, "beep_times", return_value=beeps):
            return rr.sync_report(Path("x.mp4"), list(marks))

    def test_in_sync(self):
        self.assertTrue(self.report([1.0, 7.0], [1.0, 7.01, 15.0])["ok"])

    def test_audio_late(self):
        # сынакта бир өтүүчү loudnorm аягындагы бипти 82 мс жылдырган — мындай жылыш ката катары кармалат
        self.assertFalse(self.report([1.0, 7.0], [1.0, 7.082])["ok"])

    def test_missing_flash(self):
        self.assertFalse(self.report([1.0], [1.0, 7.0])["ok"])


@unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg жок")
class TestFfmpegFinish(unittest.TestCase):
    """Remotion'сыз: FFmpeg бириктирүү/кодировка жана шайкештик өлчөөсү өзү туура иштейби."""

    def test_finish_and_sync_on_synthetic_clip(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            marks = [1.0, 2.5]
            wav = rr.make_test_audio(d / "a.wav", 4.0, marks)
            flash = "+".join(f"between(t,{m},{m + 0.06})" for m in marks)
            raw = d / "raw.mp4"
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=black:s=1920x1080:r=30:d=4",
                            "-vf", f"drawbox=x=0:y=0:w=64:h=64:color=white:t=fill:enable='{flash}'",
                            "-c:v", "libx264", "-pix_fmt", "yuvj420p", str(raw)], check=True)
            out = rr.finish(raw, d / "final.mp4", audio=wav)
            v = rr.validate(out, 4.0)
            self.assertTrue(v["ok"], v["problems"])
            self.assertEqual(v["adur"], v["vdur"])
            s = rr.sync_report(out, marks)
            self.assertTrue(s["ok"], s)


@unittest.skipIf(os.environ.get("YTA_SKIP_SLOW"), "узак тест")
@unittest.skipUnless(rr.available()[0], "Remotion орнотулган эмес (tools/remotion: npm ci)")
class TestRemotionSelftest(unittest.TestCase):
    def test_15s_render(self):
        with tempfile.TemporaryDirectory() as d:
            rep = rr.selftest(Path(d))
        self.assertTrue(rep["ok"], rep)
