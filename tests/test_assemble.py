"""Монтаждын бириктирүү (xfade) жана запас жолдору. Чыныгы FFmpeg, кичине клиптер.

Контекст: GitHub runner'де (FFmpeg 8.0.1) 8-сахналык топтордун бири 89.7 сек ордуна 17.1 сек болуп чыккан
(Video_001, топ 1) — бул эки жолу бирдей кайталанган; жергиликтүү FFmpeg 6.1'де кайталанбайт.
"""

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from pipeline.errors import StageError
from pipeline.stages import s8_render as s8


def make_scene(path: Path, sec: float, color: str):
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
                    f"color=c={color}:s=320x180:r=30:d={sec}", "-c:v", "libx264", "-preset",
                    "ultrafast", "-pix_fmt", "yuv420p", "-r", "30", str(path)], check=True)


class TestAssemble(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name)
        self.big = mock.patch.object(s8, "W", 320), mock.patch.object(s8, "H", 180)
        self.durs = [4.5, 3.5, 5.0]                       # ар сахнанын акыркы кадры өтүүгө узартылган (+0.5)
        self.files = []
        for k, (sec, c) in enumerate(zip(self.durs, ["red", "green", "blue"])):
            f = self.d / f"s{k}.mp4"
            make_scene(f, sec, c)
            self.files.append(f)
        self.trans = [{"type": "dissolve", "dur": 0.5}, {"type": "smoothright", "dur": 0.5}]
        self.want = sum(self.durs) - 1.0

    def tearDown(self):
        self.tmp.cleanup()

    def test_normal_uses_xfade(self):
        dbg = []
        dur, how = s8.assemble(self.files, self.durs, self.trans, self.d / "o.mp4", "тест", 0.5, dbg)
        self.assertEqual(how, "xfade")
        self.assertAlmostEqual(dur, self.want, delta=0.01)
        self.assertAlmostEqual(s8.video_len(self.d / "o.mp4"), self.want, delta=0.2)

    def test_cut_chain_has_same_length_as_xfade(self):
        out = self.d / "c.mp4"
        dur = s8.cut_chain(self.files, self.durs, self.trans, out)
        self.assertAlmostEqual(dur, self.want, delta=0.01)
        self.assertAlmostEqual(s8.video_len(out), self.want, delta=0.2)

    def test_cut_transition_type_keeps_lengths_consistent(self):
        trans = [{"type": "cut", "dur": 0.0}, {"type": "dissolve", "dur": 0.5}]
        a = s8.xfade_chain(self.files, self.durs, trans, self.d / "a.mp4")
        b = s8.cut_chain(self.files, self.durs, trans, self.d / "b.mp4")
        self.assertAlmostEqual(a, b, delta=0.01)

    def test_truncated_xfade_falls_back_and_stays_correct(self):
        """FFmpeg 8'дегидей: xfade файлды кыска жазат → запас ыкма туура узактык берет."""
        real = s8.xfade_chain

        def truncating(inputs, durs, transitions, out, normalize=False):
            want = real(inputs, durs, transitions, out, normalize)
            short = out.with_name("short.mp4")
            subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(out), "-t", "2", "-c", "copy",
                            str(short)], check=True)
            short.replace(out)
            return want

        dbg = []
        with mock.patch.object(s8, "xfade_chain", truncating):
            dur, how = s8.assemble(self.files, self.durs, self.trans, self.d / "o.mp4", "топ 1", 0.5, dbg)
        self.assertEqual(how, "cut")
        self.assertAlmostEqual(s8.video_len(self.d / "o.mp4"), self.want, delta=0.2)
        failed = [x for x in dbg if "method_failed" in x]
        self.assertEqual([x["method_failed"] for x in failed], ["xfade", "xfade+normalize"])
        self.assertEqual(len(failed[0]["inputs"]), 3)                  # PTS диагностикасы жазылды
        self.assertIn("fallback_used", str(dbg))

    def test_all_methods_broken_raises(self):
        def broken(*a, **k):
            Path(a[3]).write_bytes(b"x")
            return 10.0
        with mock.patch.object(s8, "xfade_chain", broken), mock.patch.object(s8, "cut_chain", broken):
            with self.assertRaises(StageError):
                s8.assemble(self.files, self.durs, self.trans, self.d / "o.mp4", "топ", 0.5, [])

    def test_pts_summary(self):
        s = s8.pts_summary(self.files[0])
        self.assertTrue(s["monotonic"])
        self.assertAlmostEqual(s["last_pts"], 4.5 - 1 / 30, delta=0.05)


if __name__ == "__main__":
    unittest.main()
