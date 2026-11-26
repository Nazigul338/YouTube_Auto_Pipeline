"""s8 рендерден кийинки оңдоолор: кара кадр жана план↔өлчөө (2026-11-25)."""
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from pipeline.stages import s8_render as r8


class TestPure(unittest.TestCase):
    def test_alt_offsets(self):
        offs = r8.alt_offsets(real=16.0, dur=3.52, cur=1.06)
        self.assertTrue(offs and len(offs) <= 4)
        room = 16.0 - 3.52 - 0.3
        for o in offs:
            self.assertGreaterEqual(o, 0.0)
            self.assertLessEqual(o, room + 0.01)
            self.assertGreaterEqual(abs(o - 1.06), 0.8)
        self.assertEqual(r8.alt_offsets(real=3.0, dur=3.0, cur=0.0), [])      # клип кыска — альтернатива жок

    def test_alt_motion(self):
        a = r8.alt_motion("v2:zoom_out@103953", 117, 0)
        b = r8.alt_motion("v2:zoom_out@103953", 117, 1)
        self.assertTrue(a.startswith("v2:") and b.startswith("v2:"))
        self.assertNotEqual(a.split("@")[0], b.split("@")[0])
        self.assertEqual(a, r8.alt_motion("v2:zoom_out@103953", 117, 0))      # кайталануучу
        self.assertIsNone(r8.alt_motion("v2:zoom_out@1", 1, 3))               # түрлөр түгөнгөндө None
        self.assertNotIn("ken_burns", r8.alt_motion("v2:ken_burns@5", 2, 0) + r8.alt_motion("v2:ken_burns@5", 2, 1))


@unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg жок")
class TestBlackSeconds(unittest.TestCase):
    def test_black_vs_normal(self):
        d = Path(tempfile.mkdtemp())
        black, test = d / "b.mp4", d / "t.mp4"
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "color=black:s=320x180:r=30", "-t", "2",
                        str(black)], check=True)
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc=s=320x180:r=30", "-t", "2",
                        str(test)], check=True)
        self.assertGreaterEqual(r8.black_seconds(black), 1.5)
        self.assertLess(r8.black_seconds(test), r8.BLACK_MAX)


if __name__ == "__main__":
    unittest.main()
