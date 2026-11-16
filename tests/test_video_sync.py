"""«Видео аудиодон кыска» катасынын тесттери (Video_001: видео 111 сек, аудио 571 сек).

Ката: клиптин чыныгы узактыгынан ашкан `-ss` бош/кыска кадр берген; QA болсо
`format.duration` (эң узун агым) менен өлчөп, катаны байкабаган.
"""

import subprocess
import tempfile
import unittest
from pathlib import Path
import random

from pipeline import media
from pipeline.errors import StageError
from pipeline.stages.s5_visuals import pick_offset
from pipeline.stages.s8_render import check_contiguous, expect_len, render_shot, video_len
from pipeline.stages.s9_qa import frames_ok, stream_sync


def ff(*args):
    subprocess.run(["ffmpeg", "-y", "-v", "error", *args], check=True)


def make_av(path: Path, video_sec: float, audio_sec: float):
    """Видео video_sec, аудио audio_sec (ар башка) болгон MP4."""
    ff("-f", "lavfi", "-i", f"testsrc2=size=320x180:rate=30:duration={video_sec}",
       "-f", "lavfi", "-i", f"sine=f=440:d={audio_sec}", "-c:v", "libx264", "-pix_fmt", "yuv420p",
       "-c:a", "aac", str(path))


class TestStreamDurations(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_format_duration_hides_short_video(self):
        """Катанын өзү: format.duration эң узун агымды берет."""
        f = self.d / "bad.mp4"
        make_av(f, video_sec=3, audio_sec=10)
        sd = media.stream_durations(f)
        self.assertAlmostEqual(sd["video"], 3.0, delta=0.2)
        self.assertAlmostEqual(sd["audio"], 10.0, delta=0.2)
        self.assertGreater(media.duration(f), 9.5)          # ← эски текшерүү ушуну «10 сек, баары жакшы» дейт
        self.assertGreater(sd["nb_frames"], 80)

    def test_broken_file_is_none_not_exception(self):
        f = self.d / "empty.mp4"
        f.write_bytes(b"\x00" * 100)
        self.assertIsNone(media.stream_durations(f)["video"])


class TestQAChecks(unittest.TestCase):
    def test_video_111_audio_571_fails(self):
        ok, note = stream_sync(111.433, 571.357, 571.4)
        self.assertFalse(ok)
        self.assertIn("ДАЛ КЕЛБЕЙТ", note)

    def test_within_one_second_passes(self):
        self.assertTrue(stream_sync(570.9, 571.357, 571.4)[0])
        self.assertTrue(stream_sync(571.0, 571.8)[0])

    def test_just_over_one_second_fails(self):
        self.assertFalse(stream_sync(570.0, 571.2)[0])

    def test_missing_stream_fails(self):
        self.assertFalse(stream_sync(0.0, 571.0)[0])
        self.assertFalse(stream_sync(571.0, 0.0)[0])

    def test_frame_count(self):
        self.assertTrue(frames_ok(17141, 571.357)[0])
        self.assertFalse(frames_ok(3343, 571.357)[0])      # Video_001: 3343 кадр гана
        self.assertTrue(frames_ok(None, 100)[0])           # белгисиз — өткөрүлөт


class TestRenderGuards(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_offset_never_exceeds_real_clip(self):
        for real in (4.0, 6.5, 15.0):
            for u in (0.0, 0.5, 0.999):
                off = pick_offset(real, 3.4, u)
                self.assertLessEqual(off + 3.4, real - 0.3 + 1e-6 if real > 3.7 else 3.4 + 1e-6)

    def test_short_real_clip_with_bad_offset_still_gives_full_shot(self):
        """API 15 сек деген клип чындыгында 4 сек: offset=12 — мурун бош кадр берген."""
        clip = self.d / "clip.mp4"
        ff("-f", "lavfi", "-i", "testsrc2=size=640x360:rate=30:duration=4", "-c:v", "libx264",
           "-pix_fmt", "yuv420p", str(clip))
        out = self.d / "shot.mp4"
        render_shot(clip, out, "video", 12.0, 3.4, "zoom_in", 1.0)   # offset клиптен сырткары
        self.assertAlmostEqual(video_len(out), 3.4, delta=0.15)

    def test_clip_shorter_than_shot_is_looped_not_truncated(self):
        clip = self.d / "tiny.mp4"
        ff("-f", "lavfi", "-i", "testsrc2=size=640x360:rate=30:duration=2", "-c:v", "libx264",
           "-pix_fmt", "yuv420p", str(clip))
        out = self.d / "shot.mp4"
        render_shot(clip, out, "video", 0.5, 3.4, "pan_right", 1.0)
        self.assertAlmostEqual(video_len(out), 3.4, delta=0.15)

    def test_unrenderable_shot_fails_loudly(self):
        bad = self.d / "bad.mp4"
        bad.write_bytes(b"not a video" * 10)
        with self.assertRaises(StageError):
            render_shot(bad, self.d / "x.mp4", "video", 0.0, 3.0, "zoom_in", 1.0)

    def test_expect_len_detects_truncation(self):
        f = self.d / "v.mp4"
        ff("-f", "lavfi", "-i", "testsrc2=size=320x180:rate=30:duration=3", "-c:v", "libx264",
           "-pix_fmt", "yuv420p", str(f))
        dbg = []
        expect_len(f, 3.0, 0.5, "тест", dbg)                       # туура
        with self.assertRaises(StageError) as cm:
            expect_len(f, 20.0, 0.5, "сахна 7", dbg)               # 20 күтүлгөн, 3 чыныгы
        self.assertIn("сахна 7", str(cm.exception))
        self.assertEqual(len(dbg), 2)

    def test_check_contiguous(self):
        good = [{"i": 0, "start": 0.0, "end": 3.0, "dur": 3.0},
                {"i": 1, "start": 3.0, "end": 6.0, "dur": 3.0}]
        check_contiguous(good, 6.0)
        with self.assertRaises(StageError):                          # аудиону толук жабабайт
            check_contiguous(good, 571.0)
        gap = [good[0], {"i": 1, "start": 4.5, "end": 7.5, "dur": 3.0}]
        with self.assertRaises(StageError):                          # боштук
            check_contiguous(gap, 7.5)


if __name__ == "__main__":
    unittest.main()
