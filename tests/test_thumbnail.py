"""Обложка: варианттарды окуу, жазуу сапка батат, 1280×720 JPG чыгат."""

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from pipeline import media, thumbnail


class TestThumbnail(unittest.TestCase):
    def test_parse_and_fit(self):
        self.assertEqual(thumbnail.parse("14|ВЫ ЖИВЁТЕ|ДЛЯ НИХ?; 329|ТИХАЯ|МЕСТЬ"),
                         [(14.0, "ВЫ ЖИВЁТЕ", "ДЛЯ НИХ?"), (329.0, "ТИХАЯ", "МЕСТЬ")])
        self.assertLess(thumbnail.fit_size("ДОКАЗЫВАЕТЕ?", 158), 158)
        self.assertEqual(thumbnail.fit_size("МЕСТЬ", 158), 158)

    def test_make_jpg(self):
        d = Path(tempfile.mkdtemp())
        try:
            src = d / "s.mp4"
            subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc2=s=1920x1080:d=2",
                            "-pix_fmt", "yuv420p", str(src)], check=True)
            out = thumbnail.make(src, 1.0, "КОМУ ВЫ", "ДОКАЗЫВАЕТЕ?", d / "t.jpg", d)
            v = next(s for s in media.probe(out)["streams"] if s["codec_type"] == "video")
            self.assertEqual((v["width"], v["height"]), (1280, 720))
            self.assertLess(out.stat().st_size, 2_000_000)          # YouTube чеги 2 МБ
            sh = thumbnail.sheet([out, out], d / "sh.jpg")
            self.assertTrue(sh.exists())
        finally:
            shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
