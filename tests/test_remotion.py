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


class TestGuard(unittest.TestCase):
    """YTA_REMOTION демейки өчүк; күйгүзүлсө да TEST папкасында гана (production — колдонуучунун уруксаты)."""

    def env(self, **kw):
        base = {"YTA_REMOTION": "", "YTA_DRIVE_FOLDER": ""}
        base.update(kw)
        return mock.patch.dict(os.environ, base)

    def test_off_without_flag(self):
        with self.env(YTA_DRIVE_FOLDER="YouTube_Auto_TEST"):
            self.assertFalse(rr.active())

    def test_on_in_test_folders(self):
        for root in ("YouTube_Auto_TEST", "YouTube_Auto_EN_TEST"):
            with self.env(YTA_REMOTION="1", YTA_DRIVE_FOLDER=root):
                self.assertTrue(rr.active(), root)
                self.assertIsNone(rr.blocked_reason())

    def test_blocked_in_production(self):
        self.assertFalse(rr.REMOTION_PRODUCTION_APPROVED)
        for root in ("YouTube_Auto", "YouTube_Auto_EN"):
            with self.env(YTA_REMOTION="1", YTA_DRIVE_FOLDER=root):
                self.assertFalse(rr.active(), root)
                self.assertIn("уруксаты", rr.blocked_reason())


class TestCardStyle(unittest.TestCase):
    def test_deterministic_and_known(self):
        st = rr.pick_card_style("Video_007", {})
        self.assertIn(st, rr.CARD_STYLES)
        self.assertEqual(st, rr.pick_card_style("Video_007", {}))

    def test_not_same_as_previous_video(self):
        st = rr.pick_card_style("Video_007", {})
        reg = {"videos": {"Video_006": {"remotion_card_style": st}}}
        self.assertNotEqual(rr.pick_card_style("Video_007", reg), st)


class TestS8Cards(unittest.TestCase):
    """8-этап: Remotion → (ишке ашпаганы) HyperFrames → ASS. Remotion өчүк болсо мурунку жол өзгөрбөйт."""

    def setUp(self):
        import json

        self.tmp = tempfile.TemporaryDirectory()
        d = Path(self.tmp.name)
        (d / "animation").mkdir()
        (d / "animation" / "overlays.ass").write_text("[Script Info]\n[Events]\nFormat: x\n", encoding="utf-8")
        cards = [{"text": "Один", "start": 1.0, "end": 3.5}, {"text": "Два", "start": 5.0, "end": 7.5}]
        (d / "animation" / "cards.json").write_text(json.dumps(cards), encoding="utf-8")
        self.d = d
        self.ctx = mock.Mock()
        self.ctx.path = lambda *a: d.joinpath(*a)
        self.ctx.video_id = "Video_007"
        self.ctx.registry = {"videos": {}}
        self.ctx.store = None
        self.logs = []
        self.ctx.log = self.logs.append
        self.shots = [{"i": 0, "start": 0.0, "end": 4.0, "dur": 4.0}, {"i": 1, "start": 4.0, "end": 8.0, "dur": 4.0}]
        self.motions = [{}, {}]
        self.plan = {"concept_params": {}}

    def tearDown(self):
        self.tmp.cleanup()

    def run_cards(self, env, rem=None, hf=None):
        from pipeline.stages.s8_render import RenderStage

        with mock.patch.dict(os.environ, env), \
                mock.patch.object(rr, "render_cards", return_value=rem or {}) as m_rem, \
                mock.patch("pipeline.hfcards.render_all", return_value=hf or {}) as m_hf:
            out = RenderStage()._cinematic_cards(self.ctx, self.shots, self.motions, self.plan, self.d)
        return out, m_rem, m_hf

    def test_remotion_off_uses_hyperframes_as_before(self):
        (cfs, _, n, _), m_rem, m_hf = self.run_cards(
            {"YTA_REMOTION": "", "YTA_HYPERFRAMES": "1", "YTA_DRIVE_FOLDER": "YouTube_Auto_TEST"},
            hf={0: Path("a.mov"), 1: Path("b.mov")})
        m_rem.assert_not_called()
        self.assertEqual(len(m_hf.call_args[0][0]), 2)
        self.assertEqual(n, 2)

    def test_remotion_on_with_fallback_to_hyperframes(self):
        (cfs, _, n, left), m_rem, m_hf = self.run_cards(
            {"YTA_REMOTION": "1", "YTA_HYPERFRAMES": "1", "YTA_DRIVE_FOLDER": "YouTube_Auto_TEST"},
            rem={0: Path("r.mov")}, hf={0: Path("h.mov")})
        m_rem.assert_called_once()
        self.assertEqual([c["text"] for c in m_hf.call_args[0][0]], ["Два"])   # Remotion'до ишке ашпаганы гана
        self.assertEqual(cfs, {0: (Path("r.mov"), 1.0), 1: (Path("h.mov"), 1.0)})
        self.assertEqual(left, 0)
        self.assertIn(self.ctx.registry["videos"]["Video_007"]["remotion_card_style"], rr.CARD_STYLES)

    def test_remotion_flag_in_production_is_ignored(self):
        (cfs, _, n, _), m_rem, m_hf = self.run_cards(
            {"YTA_REMOTION": "1", "YTA_HYPERFRAMES": "1", "YTA_DRIVE_FOLDER": "YouTube_Auto"},
            hf={0: Path("a.mov"), 1: Path("b.mov")})
        m_rem.assert_not_called()
        self.assertTrue(any("уруксаты" in x for x in self.logs))


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

    def test_cyrillic_alpha_card(self):
        with tempfile.TemporaryDirectory() as d:
            path, why = rr.render_card("Почему похвала пугает?", 2.0, Path(d), "#e0563b", "frame", "t")
            self.assertIsNotNone(path, why)
