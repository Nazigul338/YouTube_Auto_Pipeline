"""3–4-этаптардын тесттери (жалган TTS/Whisper, чыныгы FFmpeg)."""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from pipeline import ci, media
from pipeline.stages.s3_voice import make_chunks
from pipeline.stages.s4_subtitles import align, build_cues, tokens_with_text
from pipeline.storage import LocalStore
from tests.fakes import FakeGemini

KEYS = {"GOOGLE_API_KEY": "t", "PIXABAY_API_KEY": "t"}


def fake_whisper_for(project: Path, drop_every: int = 0, read_instruction: bool = False):
    """«Угулган» сөздөр = берилген тексттин сөздөрү, аудионун узактыгына бирдей жайгашат.

    drop_every — субтитр этабында ар N-сөздү «укпай» калат (дал келүү төмөндөйт).
    read_instruction — TTS нускаманы окуп койгондой кылат (башына ашыкча сөздөр).
    """
    def run(voice, hint=""):
        toks = [t for t, _ in tokens_with_text(hint)]
        if read_instruction and "chunk_" in str(voice) and run.bad > 0:
            run.bad -= 1
            toks = ["скажи", "спокойно", "и", "уверенно"] + toks
        if drop_every and "chunk_" in str(voice):
            drop = 0
        else:
            drop = drop_every
        dur = media.duration(voice)
        step = dur / len(toks)
        out = []
        for i, t in enumerate(toks):
            if drop and i % drop:
                continue
            out.append((t, i * step, (i + 0.9) * step))
        return out
    run.bad = 1
    return run


class TestAlign(unittest.TestCase):
    def test_align_fills_gaps(self):
        script = ["а", "б", "в", "г"]
        whisper = [("а", 0.0, 0.5), ("в", 1.0, 1.5), ("г", 1.5, 2.0)]
        times, cov = align(script, whisper)
        self.assertAlmostEqual(cov, 0.75)
        self.assertTrue(0.5 <= times[1][0] < times[1][1] <= 1.0)

    def test_cues_respect_limits(self):
        words = ("Это первое предложение. А это второе, чуть длиннее, чем первое, "
                 "и оно продолжается дальше.").split()
        times = [(i * 0.4, i * 0.4 + 0.35) for i in range(len(words))]
        cues = build_cues(words, times)
        for c in cues:
            self.assertLessEqual(len(" ".join(words[i] for i in c["idx"])), 46)
            self.assertGreater(c["end"], c["start"])

    def test_chunks_dont_split_scenes(self):
        scenes = [{"text": "слово " * 60} for _ in range(10)]
        chunks = make_chunks(scenes)
        self.assertTrue(all(len(c) <= 1200 for c in chunks))
        self.assertEqual(sum(c.count("слово") for c in chunks), 600)


class TestVoiceAndSubs(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.store = LocalStore(self.root / "drive")
        self.p = mock.patch("builtins.print")
        self.p.start()
        self.env = mock.patch.dict(os.environ, KEYS)
        self.env.start()
        self.proj = self.root / "w" / "Projects" / "Video_001"

    def tearDown(self):
        self.env.stop()
        self.p.stop()
        self.tmp.cleanup()

    def test_voice_and_subtitles(self):
        g = FakeGemini(words=300)
        with mock.patch.object(ci, "load_config", wraps=ci.load_config) as lc:
            lc.side_effect = lambda n, drive_root=None: _cfg(drive_root)
            code = ci.run_ci("Тема", "motivation", self.root / "w", store=self.store,
                             stop_after="s4_subtitles",
                             services={"gemini": g, "asr": fake_whisper_for(self.proj)})
        self.assertEqual(code, 0)
        voice = self.proj / "audio" / "voice.wav"
        self.assertTrue(voice.exists())
        info = media.probe(voice)["streams"][0]
        self.assertEqual(info["sample_rate"], "48000")
        ass = (self.proj / "subtitles" / "subtitles.ass").read_text(encoding="utf-8")
        self.assertIn("Dialogue:", ass)
        self.assertIn(r"\c&H3FC8FF&", ass)                  # ачкыч сөз түстүү
        t = json.loads((self.proj / "subtitles" / "timings.json").read_text(encoding="utf-8"))
        self.assertEqual(t["coverage"], 1.0)
        starts = [s["start"] for s in t["scenes"]]
        self.assertEqual(starts, sorted(starts))
        drive = self.root / "drive" / "YouTube_Auto"
        self.assertTrue((drive / "Audio" / "Video_001_voice.wav").exists())
        self.assertTrue((drive / "Subtitles" / "Video_001.srt").exists())
        # чанктар кэштелди: кайра иштетүүдө TTS чакырылбайт
        n_tts = g.calls.count("tts")
        code = ci.run_ci("", "motivation", self.root / "w", store=self.store, video_id="Video_001",
                         rerun_from="s3_voice", stop_after="s3_voice",
                         services={"gemini": g, "asr": fake_whisper_for(self.proj)})
        self.assertEqual(g.calls.count("tts"), n_tts)

    def test_low_coverage_fails(self):
        g = FakeGemini(words=300)
        with mock.patch.object(ci, "load_config") as lc:
            lc.side_effect = lambda n, drive_root=None: _cfg(drive_root)
            code = ci.run_ci("Тема", "motivation", self.root / "w", store=self.store,
                             stop_after="s4_subtitles",
                             services={"gemini": g, "asr": fake_whisper_for(self.proj, 2)})
        self.assertEqual(code, 1)
        st = json.loads((self.proj / "state.json").read_text(encoding="utf-8"))
        self.assertIn("дал келет", st["stages"]["s4_subtitles"]["error"])


def _cfg(root):
    from pipeline.config import load_config
    return load_config("motivation", drive_root=root, words_min=250, words_max=350)


if __name__ == "__main__":
    unittest.main()


class TestInstructionRead(unittest.TestCase):
    def test_check_heard(self):
        from pipeline.stages.s3_voice import check_heard
        exp = "иногда самый трудный шаг это первый".split()
        self.assertEqual(check_heard(exp, exp), (0, 1.0, 0))
        extra, cov, gap = check_heard(exp, ["скажи", "спокойно", "и", "уверенно"] + exp)
        self.assertEqual(extra, 4)
        self.assertEqual(cov, 1.0)
        self.assertEqual(check_heard(exp, exp[:3])[2], 3)       # аягы окулбады — катар
        long = [f"с{i}" for i in range(40)]
        scattered = [w if i % 6 else "xx" for i, w in enumerate(long)]  # чачыранды ката
        self.assertLessEqual(check_heard(long, scattered)[2], 1)
        skipped = long[:10] + long[25:]                                 # 15 сөз окулбай калды
        self.assertEqual(check_heard(long, skipped)[2], 15)


class TestInstructionRetry(unittest.TestCase):
    def test_chunk_regenerated_when_instruction_is_read(self):
        tmp = tempfile.TemporaryDirectory()
        root = Path(tmp.name)
        store = LocalStore(root / "drive")
        proj = root / "w" / "Projects" / "Video_001"
        g = FakeGemini(words=300)
        with mock.patch("builtins.print"), mock.patch.dict(os.environ, KEYS), \
                mock.patch.object(ci, "load_config") as lc:
            lc.side_effect = lambda n, drive_root=None: _cfg(drive_root)
            code = ci.run_ci("Тема", "motivation", root / "w", store=store, stop_after="s3_voice",
                             services={"gemini": g,
                                       "asr": fake_whisper_for(proj, read_instruction=True)})
        self.assertEqual(code, 0)
        rep = json.loads((proj / "audio" / "voice_report.json").read_text(encoding="utf-8"))
        self.assertEqual(rep["chunks"][0]["attempts"], 2)   # 1-аракет четке кагылды
        tmp.cleanup()
