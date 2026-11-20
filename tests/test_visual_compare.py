"""Даяр видеолорду визуалдык салыштыруу: көчүрмө/шаблон табылат, башка видео өтөт (чыныгы FFmpeg)."""

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from pipeline import visual_compare as vc


def ff(*a):
    subprocess.run(["ffmpeg", "-y", "-v", "error", *a], check=True)


class TestVisualCompare(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.d = Path(tempfile.mkdtemp())
        ff("-f", "lavfi", "-i", "testsrc2=s=640x360:d=30,format=yuv420p", str(cls.d / "a.mp4"))
        ff("-i", str(cls.d / "a.mp4"), "-vf", "eq=brightness=0.02", "-crf", "30", str(cls.d / "a_copy.mp4"))
        ff("-f", "lavfi", "-i", "mandelbrot=s=640x360:r=25", "-f", "lavfi", "-i", "color=c=0x203040:s=640x360:d=30",
           "-filter_complex", "[0:v]trim=0:15,setpts=PTS-STARTPTS[x];[1:v]trim=0:15,setpts=PTS-STARTPTS[y];"
           "[x][y]concat=n=2:v=1,format=yuv420p", "-t", "30", str(cls.d / "b.mp4"))
        cls.fp = {n: vc.fingerprint(cls.d / f"{n}.mp4") for n in ("a", "a_copy", "b")}

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.d, ignore_errors=True)

    def test_copy_detected(self):
        r = vc.compare(self.fp["a_copy"], self.fp["a"])
        self.assertGreaterEqual(r["dup_frames"], 0.9)
        self.assertTrue(r["too_similar"])

    def test_different_passes(self):
        r = vc.compare(self.fp["b"], self.fp["a"])
        self.assertLess(r["dup_frames"], 0.15)
        self.assertFalse(r["too_similar"], r)

    def test_composition_alone_is_not_template(self):
        a = dict(self.fp["a"])
        b = dict(self.fp["b"], composition=a["composition"], brightness=a["brightness"], palette=a["palette"])
        r = vc.compare(b, a)
        self.assertIn("composition", r["similar"])
        self.assertFalse(r["too_similar"], r)                 # монтаж өлчөмдөрү башка → шаблон эмес

    def test_against_finished_uses_registry(self):
        reg = {"videos": {"Video_001": {"final_cinematic": "x", "visual_fp": self.fp["a"]},
                          "Video_009": {"visual_fp": self.fp["a"]}}}          # даяр эмес — салыштырылбайт
        res = vc.against_finished(self.fp["a_copy"], reg, "Video_002")
        self.assertEqual(list(res), ["Video_001"])
        self.assertTrue(res["Video_001"]["too_similar"])


if __name__ == "__main__":
    unittest.main()
