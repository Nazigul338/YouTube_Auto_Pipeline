"""Cinematic СЫНАК режими: коргоо, чыпкалар (чыныгы FFmpeg), blur фон, HyperFrames шаблону, s8 overlay."""

import json
import os
import random
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from pipeline import cinematic, hfcards, media
from pipeline.stages import s8_render as s8
from pipeline.storage import DriveStore, LocalStore


class FakeDrive:
    def ensure_path(self, *a):
        return "F"


def ff(*a):
    subprocess.run(["ffmpeg", "-y", "-v", "error", *a], check=True)


class TestGuard(unittest.TestCase):
    """Эң маанилүү: production папкасында желек коюлса да режим ӨЧҮК."""

    def test_off_without_flag(self):
        with mock.patch.dict(os.environ, {"YTA_CINEMATIC": ""}):
            self.assertFalse(cinematic.enabled(DriveStore(FakeDrive(), "YouTube_Auto_TEST")))

    def test_on_only_in_test_root(self):
        with mock.patch.dict(os.environ, {"YTA_CINEMATIC": "1"}):
            self.assertTrue(cinematic.enabled(DriveStore(FakeDrive(), "YouTube_Auto_TEST")))
            prod = DriveStore(FakeDrive(), "YouTube_Auto")
            self.assertFalse(cinematic.enabled(prod))
            self.assertIn("уруксат", cinematic.blocked_reason(prod))

    def test_env_root_without_store(self):
        with mock.patch.dict(os.environ, {"YTA_CINEMATIC": "1", "YTA_DRIVE_FOLDER": "YouTube_Auto"}):
            self.assertFalse(cinematic.enabled(None))


class TestFilters(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_look_chain_runs_and_keeps_frames(self):
        src = self.d / "s.mp4"
        ff("-f", "lavfi", "-i", "testsrc2=size=640x360:rate=30:duration=2", "-c:v", "libx264", "-preset",
           "ultrafast", "-pix_fmt", "yuv420p", str(src))
        out = self.d / "o.mp4"
        vf = cinematic.look_chain("eq=contrast=1.06,colorbalance=rs=0.04") + ",vignette=PI/5,format=yuv420p"
        ff("-i", str(src), "-filter_complex", f"[0:v]{vf}[v]", "-map", "[v]", "-c:v", "libx264",
           "-preset", "ultrafast", str(out))
        self.assertEqual(media.stream_durations(out)["nb_frames"], 60)

    def test_match_filter_is_gentle(self):
        self.assertEqual(cinematic.match_filter(None), "")
        self.assertEqual(cinematic.match_filter({"y": 0.43, "sat": 0.20}), "")
        dark = cinematic.match_filter({"y": 0.10, "sat": 0.05})
        self.assertIn("brightness=0.070", dark)          # чектелген: ±0.07
        self.assertIn("saturation=1.180", dark)

    def test_measure_reads_brightness(self):
        dark, bright = self.d / "d.mp4", self.d / "b.mp4"
        for p, c in ((dark, "0x202020"), (bright, "0xD0D0D0")):
            ff("-f", "lavfi", "-i", f"color=c={c}:s=320x180:r=30:d=2", "-c:v", "libx264", "-preset", "ultrafast",
               "-pix_fmt", "yuv420p", str(p))
        self.assertLess(cinematic.measure(dark, 0, 1)["y"], cinematic.measure(bright, 0, 1)["y"])

    def test_blur_bg_only_for_wrong_aspect(self):
        self.assertFalse(cinematic.needs_blur_bg(1920, 1080))
        self.assertFalse(cinematic.needs_blur_bg(1920, 1200))     # 16:10 — кесүү жетиштүү
        self.assertTrue(cinematic.needs_blur_bg(1080, 1920))      # вертикалдык
        self.assertTrue(cinematic.needs_blur_bg(1440, 1080))      # 4:3

    def test_vertical_clip_becomes_full_16_9_without_bars(self):
        clip = self.d / "v.mp4"
        ff("-f", "lavfi", "-i", "testsrc2=size=360x640:rate=30:duration=3", "-c:v", "libx264", "-preset",
           "ultrafast", "-pix_fmt", "yuv420p", str(clip))
        pre, info = cinematic.shot_prefilter(clip, "video", 0.0, 2.0)
        self.assertEqual(info["blur_bg"], "360x640")
        out = self.d / "shot.mp4"
        s8.render_shot(clip, out, "video", 0.0, 2.0, "zoom_in", 1.0, prefilter=pre)
        info2 = media.probe(out)["streams"][0]
        self.assertEqual((info2["width"], info2["height"]), (1920, 1080))
        # кара тилке жок: четки тилкелердин орточо жарыгы 0'дөн чоң (бүдөмүк фон)
        r = subprocess.run(["ffmpeg", "-v", "info", "-i", str(out), "-vf",
                            "crop=200:1080:0:0,signalstats,metadata=print", "-frames:v", "1", "-f", "null", "-"],
                           capture_output=True, text=True)
        import re
        yavg = float(re.findall(r"YAVG=([\d.]+)", r.stderr)[0])
        self.assertGreater(yavg, 20)

    def test_transitions_vary_and_no_double_fadeblack(self):
        rng, prev, seq = random.Random(1), None, []
        for _ in range(600):
            prev = cinematic.pick_transition(rng, prev)
            seq.append(prev)
        self.assertGreater(len(set(seq)), 3)
        self.assertFalse(any(a == b == "fadeblack" for a, b in zip(seq, seq[1:])))
        self.assertGreater(seq.count("dissolve") + seq.count("fade"), len(seq) * 0.55)
        self.assertLess(seq.count("fadeblack"), len(seq) * 0.11)          # караңгы өтүү сейрек

    def test_card_overlay_in_render_shot(self):
        clip, card = self.d / "c.mp4", self.d / "card.mov"
        ff("-f", "lavfi", "-i", "color=c=0x303030:s=640x360:r=30:d=4", "-c:v", "libx264", "-preset",
           "ultrafast", "-pix_fmt", "yuv420p", str(clip))
        ff("-f", "lavfi", "-i", "color=c=white@1.0:s=1920x1080:r=30:d=1,format=yuva444p,"
           "drawbox=x=0:y=0:w=1920:h=1080:color=white@1.0:t=fill", "-c:v", "prores_ks", "-profile:v", "4444",
           "-pix_fmt", "yuva444p10le", str(card))
        out = self.d / "s.mp4"
        s8.render_shot(clip, out, "video", 0.0, 3.0, "zoom_in", 1.0, card=(card, 1.0))
        self.assertAlmostEqual(s8.video_len(out), 3.0, delta=0.1)

        def y_at(t):
            r = subprocess.run(["ffmpeg", "-v", "info", "-ss", str(t), "-i", str(out), "-vf",
                                "signalstats,metadata=print", "-frames:v", "1", "-f", "null", "-"],
                               capture_output=True, text=True)
            import re
            return float(re.findall(r"YAVG=([\d.]+)", r.stderr)[0])
        self.assertLess(y_at(0.3), 100)       # карточка али жок
        self.assertGreater(y_at(1.5), 200)    # карточка (ак) 1.0–2.0 сек
        self.assertLess(y_at(2.6), 100)       # карточка бүттү, видео уланат


class TestHFTemplate(unittest.TestCase):
    def test_html_escapes_and_fills(self):
        html = hfcards.build_html("МАЛЕНЬКИЕ <ШАГИ> & ВСЁ", 2.6, "#ffc860")
        self.assertIn('<span class="w">МАЛЕНЬКИЕ</span>', html)
        self.assertIn("&lt;ШАГИ&gt;", html)
        self.assertNotIn("__", html.split("<body>")[1].split("<script>")[0])
        self.assertIn('data-duration="2.600"', html)
        self.assertIn("#ffc860", html)

    def test_accent_from_ass_color(self):
        self.assertEqual(hfcards.accent_css("&H0060C8FF&"), "#FFC860")

    def test_unavailable_falls_back(self):
        with mock.patch.dict(os.environ, {"YTA_HF_DIR": "/nonexistent"}):
            ok, why = hfcards.available()
            self.assertFalse(ok)
            logs = []
            self.assertEqual(hfcards.render_all([{"text": "A", "dur": 2}], Path("/tmp/x_hf"), "#fff", logs.append), {})
            self.assertIn("ASS", logs[0])

    def test_relative_workdir_is_resolved(self):
        """Runner'деги ката: салыштырмалуу жол → CLI файлды башка жерге жазган. Эми ар дайым абсолюттук."""
        seen = {}

        def fake_run(cmd, cwd=None, **kw):
            seen["out"], seen["cwd"] = cmd[cmd.index("-o") + 1], cwd
            raise subprocess.TimeoutExpired(cmd, 1)
        with tempfile.TemporaryDirectory() as d, mock.patch.object(hfcards, "make_project",
                                                                    side_effect=lambda t, du, dest, a: dest), \
                mock.patch("subprocess.run", fake_run):
            old = os.getcwd()
            os.chdir(d)
            try:
                hfcards.render_card("А", 2.0, Path("rel/card_00"))
            finally:
                os.chdir(old)
        self.assertTrue(Path(seen["out"]).is_absolute())
        self.assertTrue(Path(seen["cwd"]).is_absolute())

    @unittest.skipUnless(os.environ.get("YTA_HF_LIVE"), "HyperFrames орнотулган чөйрөдө гана")
    def test_live_render_russian_card(self):
        with tempfile.TemporaryDirectory() as d:
            path, why = hfcards.render_card("МАЛЕНЬКИЕ ШАГИ МЕНЯЮТ ВСЁ", 2.6, Path(d) / "c")
            self.assertIsNotNone(path, why)


if __name__ == "__main__":
    unittest.main()
