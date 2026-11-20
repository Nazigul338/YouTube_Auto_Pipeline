"""Мотивациялык үн стили (СЫНАК): коргоо, паузалар сөздөрдү өзгөртпөйт, s3 интеграциясы, кэш."""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from pipeline import ci, voice_lab, voice_style
from pipeline.stages.s3_voice import chunk_keywords, make_chunks
from pipeline.storage import DriveStore, LocalStore
from tests.fakes import FakeGemini
from tests.test_stages_audio import KEYS, _cfg, fake_whisper_for


class FakeDrive:
    def ensure_path(self, *a):
        return "F"


class Recorder(FakeGemini):
    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.tts_calls = []

    def tts(self, text, *, voice, style, variant=0, models=None):
        self.tts_calls.append({"text": text, "style": style, "voice": voice})
        return super().tts(text, voice=voice, style=style, variant=variant, models=models)


class TestGuardAndText(unittest.TestCase):
    def test_only_test_root(self):
        with mock.patch.dict(os.environ, {"YTA_VOICE_STYLE": "motivational"}):
            self.assertTrue(voice_style.enabled(DriveStore(FakeDrive(), "YouTube_Auto_TEST")))
            self.assertTrue(voice_style.enabled(DriveStore(FakeDrive(), "YouTube_Auto")))   # бекитилди 2026-11-20
            from pipeline import cinematic
            with mock.patch.object(cinematic, "PRODUCTION_APPROVED", False):
                self.assertFalse(voice_style.enabled(DriveStore(FakeDrive(), "YouTube_Auto")))
            self.assertFalse(voice_style.enabled(DriveStore(FakeDrive(), "Other")))
        with mock.patch.dict(os.environ, {"YTA_VOICE_STYLE": ""}):
            self.assertFalse(voice_style.enabled(DriveStore(FakeDrive(), "YouTube_Auto_TEST")))

    def test_shape_keeps_words(self):
        for t in (voice_lab.TEXT, "Почему мы ждём? Но ответ прост... Запомни это! И вот — шаг.",
                  "Сегодня важный день. А теперь подумай."):
            shaped = voice_style.shape_text(t)
            self.assertEqual(voice_style.words(shaped), voice_style.words(t))
        self.assertIn("?\n\n", voice_style.shape_text("Ты ждёшь? Начни."))
        self.assertIn(".\n\nНо", voice_style.shape_text("Это трудно. Но возможно."))

    def test_direction_has_emphasis(self):
        d = voice_style.direction(["время", "шаг"])
        self.assertIn("motivational narrator", d)
        self.assertIn("«время», «шаг»", d)
        self.assertNotIn("emphasis", voice_style.direction([]))

    def test_chunk_keywords_aligned_with_chunks(self):
        sc = [{"text": "а" * 800, "keywords": ["x"]}, {"text": "б" * 800, "keywords": ["y"]},
              {"text": "в" * 100, "keywords": ["z"]}]
        self.assertEqual(len(chunk_keywords(sc)), len(make_chunks(sc)))


class TestS3Integration(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.store = LocalStore(self.root / "drive")
        self.proj = self.root / "w" / "Projects" / "Video_001"
        self.p = mock.patch("builtins.print")
        self.p.start()

    def tearDown(self):
        self.p.stop()
        self.tmp.cleanup()

    def run_ci(self, g, **kw):
        with mock.patch.object(ci, "load_config", wraps=ci.load_config) as lc:
            lc.side_effect = lambda n, drive_root=None: _cfg(drive_root)
            return ci.run_ci(kw.pop("topic", "Тема"), "motivation", self.root / "w", store=self.store,
                             stop_after="s3_voice", services={"gemini": g, "asr": fake_whisper_for(self.proj)}, **kw)

    def test_motivational_style_used_and_cache_respects_style(self):
        g = Recorder(words=300)
        with mock.patch.dict(os.environ, {**KEYS, "YTA_VOICE_STYLE": "motivational"}):
            self.assertEqual(self.run_ci(g), 0)
        self.assertTrue(g.tts_calls)
        self.assertTrue(all("motivational narrator" in c["style"] for c in g.tts_calls))
        self.assertTrue(all(c["voice"] == "Algenib" for c in g.tts_calls))     # үн сакталат
        rep = json.loads((self.proj / "audio" / "voice_report.json").read_text(encoding="utf-8"))
        self.assertTrue(all(c.get("style") == "motivational" for c in rep["chunks"]))
        n = len(g.tts_calls)
        # ошол эле стиль → кэш (TTS чакырылбайт)
        with mock.patch.dict(os.environ, {**KEYS, "YTA_VOICE_STYLE": "motivational"}):
            self.run_ci(g, topic="", video_id="Video_001", rerun_from="s3_voice")
        self.assertEqual(len(g.tts_calls), n)
        # стиль өчүрүлдү → мурунку (production) стилде кайра жаратылат
        with mock.patch.dict(os.environ, {**KEYS, "YTA_VOICE_STYLE": ""}):
            self.run_ci(g, topic="", video_id="Video_001", rerun_from="s3_voice")
        self.assertGreater(len(g.tts_calls), n)
        self.assertFalse(any("motivational narrator" in c["style"] for c in g.tts_calls[n:]))

    def test_production_style_unchanged_without_flag(self):
        g = Recorder(words=300)
        with mock.patch.dict(os.environ, {**KEYS, "YTA_VOICE_STYLE": ""}):
            self.assertEqual(self.run_ci(g), 0)
        self.assertTrue(all("Deep, strong, mature Russian male voice" in c["style"] for c in g.tts_calls))
        self.assertTrue(all("\n\n" not in c["text"] for c in g.tts_calls))


class TestPitch(unittest.TestCase):
    def test_lower_voice_has_lower_f0(self):
        import subprocess
        with tempfile.TemporaryDirectory() as d:
            lo, hi = Path(d) / "lo.wav", Path(d) / "hi.wav"
            for p, f in ((lo, 110), (hi, 220)):
                subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"sine=f={f}:d=3",
                                "-af", "volume=0.5", str(p)], check=True)
            a, b = voice_lab.pitch_stats(lo), voice_lab.pitch_stats(hi)
            self.assertAlmostEqual(a["f0_median"], 110, delta=6)
            self.assertAlmostEqual(b["f0_median"], 220, delta=10)
            self.assertLess(a["f0_var_semitones"], 0.5)          # таза тон = «монотон»


if __name__ == "__main__":
    unittest.main()
