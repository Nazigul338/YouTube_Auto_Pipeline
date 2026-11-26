"""9:16 Shorts hook (pipeline/shorts_hook.py): тайминг эрежелери + чыныгы FFmpeg рендери (кичине масштаб)."""

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import numpy as np

from pipeline import shorts_hook as sh

HAS = shutil.which("ffmpeg") is not None
try:
    import qrcode  # noqa: F401
except ImportError:
    HAS = False


class TimelineTest(unittest.TestCase):
    def test_default_hook_rules(self):
        tl = sh.Timeline.build()
        self.assertLessEqual(tl.l1_start, sh.TEXT_MAX_START)
        self.assertLessEqual(tl.hook_end, sh.HOOK_MAX)
        self.assertLess(tl.cut, tl.l2_start)
        self.assertLess(tl.hook_end, tl.bridge_start)

    def test_longest_allowed_voice_still_fits(self):
        tl = sh.Timeline.build({"line1": 2.0, "line2": 2.35})
        self.assertLessEqual(tl.hook_end, sh.HOOK_MAX)

    def test_too_long_voice_fails_check(self):
        tl = sh.Timeline.build({"line1": 3.0, "line2": 3.0})
        self.assertFalse(sh.check(tl, 60, True)["ok"])

    def test_dark_first_frame_fails(self):
        self.assertFalse(sh.check(sh.Timeline.build(), 5, True)["ok"])

    def test_trim_silence(self):
        x = np.concatenate([np.zeros(sh.SR), 0.5 * np.ones(sh.SR), np.zeros(sh.SR)])
        self.assertLess(len(sh.trim_silence(x)) / sh.SR, 1.2)

    @unittest.skipUnless(HAS, "ffmpeg/qrcode жок")
    def test_fit_voice_speeds_up(self):
        x = np.sin(np.linspace(0, 3000, int(2.3 * sh.SR))) * 0.3
        y = sh.fit_voice(x, 2.0)
        self.assertLess(len(y) / sh.SR, 2.1)


@unittest.skipUnless(HAS and not os.environ.get("YTA_SKIP_SLOW"), "узак тест (YTA_SKIP_SLOW)")
class RenderTest(unittest.TestCase):
    def test_render_small(self):
        d = Path(tempfile.mkdtemp())
        try:
            out = d / "h.mp4"
            rep = sh.render(out, scale=0.25, log=lambda *_: None)
            self.assertTrue(rep["checks"]["ok"], rep)
            pr = json.loads(subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-of", "json", str(out)],
                                           capture_output=True, text=True).stdout)
            v = next(s for s in pr["streams"] if s["codec_type"] == "video")
            self.assertAlmostEqual(v["width"] / v["height"], 9 / 16, places=2)
            self.assertTrue(any(s["codec_type"] == "audio" for s in pr["streams"]))
        finally:
            shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
