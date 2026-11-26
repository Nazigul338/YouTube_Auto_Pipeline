"""16:9 hook (pipeline/history_hook.py): тайминг, лицензия чыпкасы, чыныгы FFmpeg рендери (сыноо сүрөттөрү менен)."""

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

from pipeline import history_hook as hh

HAS_FF = shutil.which("ffmpeg") is not None


class TimelineTest(unittest.TestCase):
    def test_default_hook_rules(self):
        tl = hh.Timeline.build()
        self.assertLessEqual(tl.l1_start, hh.TEXT_MAX_START)
        self.assertLessEqual(tl.hook_end, hh.HOOK_MAX)
        self.assertLess(tl.cut, tl.l2_start)
        self.assertEqual(tl.hara_at, 0.0)

    def test_longest_allowed_voice_still_fits(self):
        self.assertLessEqual(hh.Timeline.build({"line1": 2.0, "line2": 2.35}).hook_end, hh.HOOK_MAX)

    def test_hara_inside_bridge(self):
        tl = hh.Timeline.build(hara=True)
        self.assertTrue(tl.bridge_start < tl.hara_at < tl.end)

    def test_too_long_voice_fails_check(self):
        self.assertFalse(hh.check(hh.Timeline.build({"line1": 3.0, "line2": 3.0}), 60, True)["ok"])

    def test_dark_first_frame_fails(self):
        self.assertFalse(hh.check(hh.Timeline.build(), 5, True)["ok"])


class LicenseTest(unittest.TestCase):
    def test_free_licenses(self):
        for lic in ("CC BY-SA 4.0", "CC BY 2.0", "CC0", "Public domain", "PD-self"):
            self.assertTrue(hh.FREE_LICENSES.match(lic), lic)

    def test_non_free_rejected(self):
        for lic in ("Fair use", "CC BY-NC 2.0", "CC BY-ND 4.0", "", "All rights reserved"):
            self.assertFalse(hh.FREE_LICENSES.match(lic), lic)

    def test_hook_text_is_problem_not_crisis(self):
        self.assertNotIn("CRISIS", " ".join(hh.SPEC["line2"]))


class FakeGem:
    def __init__(self, rows):
        self.rows = rows

    def judge_image(self, jpgs, prompt, purpose=""):
        return self.rows


class JudgeTest(unittest.TestCase):
    def test_logo_and_face_rejected_text_penalised(self):
        d = Path(tempfile.mkdtemp())
        try:
            files = []
            for k in range(3):
                Image.new("RGB", (64, 36), (k * 40, 0, 0)).save(d / f"{k}.jpg")
                files.append(d / f"{k}.jpg")
            rows = [{"i": 0, "fit": 9, "logo": True}, {"i": 1, "fit": 8, "face": True},
                    {"i": 2, "fit": 7, "text": True, "focus": [0.99, 0.0]}, {"i": 9, "fit": 10}, "junk"]
            out = hh.judge(FakeGem(rows), files, "x", log=lambda *_: None)
            self.assertEqual(out, [(6, 2, (0.85, 0.15))])
        finally:
            shutil.rmtree(d, ignore_errors=True)


def _photos(d: Path) -> None:
    rng = np.random.default_rng(0)
    for name in ("scan", "factory", "barcode"):
        Image.fromarray(rng.integers(40, 200, (900, 1600, 3), dtype=np.uint8)).save(d / f"{name}.jpg")
    (d / "photos.json").write_text(json.dumps({n: {"license": "test", "source": "test"}
                                               for n in ("scan", "factory", "barcode")}))


class LocalPhotosTest(unittest.TestCase):
    def test_missing_photo_raises(self):
        d = Path(tempfile.mkdtemp())
        try:
            with self.assertRaises(FileNotFoundError):
                hh.local_photos(d)
            _photos(d)
            ph = hh.local_photos(d)
            self.assertEqual(set(ph), {"scan", "factory", "barcode"})
        finally:
            shutil.rmtree(d, ignore_errors=True)


@unittest.skipUnless(HAS_FF and not os.environ.get("YTA_SKIP_SLOW"), "узак тест (YTA_SKIP_SLOW)")
class RenderTest(unittest.TestCase):
    def test_render(self):
        d = Path(tempfile.mkdtemp())
        try:
            _photos(d)
            out = d / "h.mp4"
            rep = hh.render(out, hh.local_photos(d), log=lambda *_: None)
            self.assertTrue(rep["checks"]["ok"], rep)
            pr = json.loads(subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-of", "json", str(out)],
                                           capture_output=True, text=True).stdout)
            v = next(s for s in pr["streams"] if s["codec_type"] == "video")
            self.assertEqual((v["width"], v["height"]), (1920, 1080))
            self.assertTrue(any(s["codec_type"] == "audio" for s in pr["streams"]))
        finally:
            shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
