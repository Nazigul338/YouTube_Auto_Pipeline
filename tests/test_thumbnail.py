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


class TestUnique(unittest.TestCase):
    def test_similar_text_rejected(self):
        reg = {"videos": {"Video_001": {"thumbnail": {"texts": ["ВЫ ЖИВЁТЕ ДЛЯ НИХ?"]}}}}
        res = thumbnail.check_unique([(1.0, "ВЫ ЖИВЁТЕ", "ДЛЯ НИХ?"), (2.0, "СТРАХ", "ЧУЖОГО МНЕНИЯ")], reg, "Video_002")
        self.assertIsNotNone(res[0][1])
        self.assertIsNone(res[1][1])
        self.assertIsNone(thumbnail.check_unique([(1.0, "ВЫ ЖИВЁТЕ", "ДЛЯ НИХ?")], reg, "Video_001")[0][1])


class TestCleanSource(unittest.TestCase):
    def test_uses_source_clip_time(self):
        from types import SimpleNamespace

        shots = [{"i": 0, "start": 0.0, "end": 3.0, "source": "pixabay", "kind": "video", "asset": "pixabay:1",
                  "url": "https://x/1.mp4", "file": "a.mp4", "offset": 2.0},
                 {"i": 1, "start": 3.0, "end": 6.0, "source": "gemini", "kind": "image", "asset": "g", "url": "",
                  "file": "b.jpg"}]
        d = Path(tempfile.mkdtemp())
        try:
            got = []
            st = SimpleNamespace(download=lambda a, dest: got.append(a.url) or dest)
            src, at = thumbnail.clean_source(shots, 1.5, d, st)
            self.assertEqual((src.name, at, got), ("clip_0.mp4", 3.5, ["https://x/1.mp4"]))
            self.assertIsNone(thumbnail.clean_source(shots, 4.0, d, st))     # AI-сүрөт — булак жок
            self.assertIsNone(thumbnail.clean_source(shots, 99, d, st))
        finally:
            shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
