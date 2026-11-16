"""1–2-этаптардын тесттери (жалган Gemini менен)."""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from pipeline import ci
from pipeline.stages.base import StageError
from pipeline.stages.s1_script import choose_style, clean_script, split_title
from pipeline.storage import LocalStore
from pipeline.textutil import duplicate_sentences, group_sentences, jaccard, norm, word_count
from tests.fakes import FakeGemini, make_script

KEYS = {"GOOGLE_API_KEY": "t", "PIXABAY_API_KEY": "t"}


class TestTextUtil(unittest.TestCase):
    def test_word_count_and_dups(self):
        self.assertEqual(word_count("Привет, мир! Как дела-то?"), 4)
        t = "Это первое длинное предложение здесь. Другое. Это первое длинное предложение здесь."
        self.assertEqual(len(duplicate_sentences(t)), 1)

    def test_grouping_keeps_text(self):
        s = make_script(1150)
        g = group_sentences(s)
        self.assertEqual(norm(" ".join(g)), norm(s))
        self.assertTrue(all(word_count(x) <= 50 for x in g))

    def test_jaccard(self):
        a = make_script(300, "-a")
        self.assertGreater(jaccard(a, a), 0.99)
        self.assertLess(jaccard(a, make_script(300, "-zz")), 0.5)

    def test_clean_script(self):
        raw = "НАЗВАНИЕ: X\n## Часть 1\n**Важно** [пауза] текст 🙂\n- пункт"
        title, body = split_title(raw)
        self.assertEqual(title, "X")
        self.assertNotIn("[", body)
        self.assertNotIn("#", body)
        self.assertNotIn("🙂", body)
        self.assertIn("Важно текст", clean_script("**Важно** текст"))

    def test_style_rotation(self):
        styles = {"a": "", "b": "", "c": ""}
        reg = {"videos": {"Video_001": {"style": "a"}, "Video_002": {"style": "b"}}}
        self.assertEqual(choose_style(styles, reg, "Video_003"), "c")


class TestScriptAndScenes(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.store = LocalStore(self.root / "drive")
        self.p = mock.patch("builtins.print")
        self.p.start()
        self.env = mock.patch.dict(os.environ, KEYS)
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.p.stop()
        self.tmp.cleanup()

    def run_video(self, g, topic="Тема", stop="s2_scenes", work="w1"):
        return ci.run_ci(topic, "motivation", self.root / work, store=self.store,
                         stop_after=stop, services={"gemini": g})

    def test_script_and_scenes(self):
        g = FakeGemini()
        self.assertEqual(self.run_video(g), 0)
        proj = self.root / "w1" / "Projects" / "Video_001"
        text = (proj / "script" / "script.txt").read_text(encoding="utf-8")
        self.assertTrue(1100 <= word_count(text) <= 1200)
        meta = json.loads((proj / "script" / "meta.json").read_text(encoding="utf-8"))
        self.assertIn(meta["style"], ["story", "question", "myth", "analysis", "letter",
                                      "contrast", "experiment"])
        self.assertTrue((self.root / "drive" / "YouTube_Auto" / "Scripts" / "Video_001.txt").exists())
        self.assertIn("fact_check", g.calls)
        scenes = json.loads((proj / "scenes.json").read_text(encoding="utf-8"))["scenes"]
        self.assertEqual(norm(" ".join(s["text"] for s in scenes)), norm(text))
        for s in scenes:  # жалган (тексте жок) ачкыч сөз чыпкаланды
            self.assertNotIn("несуществующее слово", s["keywords"])
        reg = self.store.load_registry()["videos"]["Video_001"]
        self.assertEqual(reg["style"], meta["style"])

    def test_second_video_other_style_and_similarity_checked(self):
        self.run_video(FakeGemini(), work="w1")
        self.run_video(FakeGemini(), topic="Другая тема", work="w2")
        reg = self.store.load_registry()["videos"]
        self.assertNotEqual(reg["Video_001"]["style"], reg["Video_002"]["style"])
        meta = json.loads((self.root / "w2" / "Projects" / "Video_002" / "script" / "meta.json")
                          .read_text(encoding="utf-8"))
        self.assertLess(meta["similarity"]["max_jaccard"], 0.10)

    def test_copy_of_previous_script_rejected(self):
        self.run_video(FakeGemini(same_text=True), work="w1")
        code = self.run_video(FakeGemini(same_text=True), topic="Копия", work="w2")
        self.assertEqual(code, 1)
        st = json.loads((self.root / "drive" / "YouTube_Auto" / "Projects" / "Video_002" /
                         "state.json").read_text(encoding="utf-8"))
        self.assertIn("окшош", st["stages"]["s1_script"]["error"])

    def test_length_out_of_range_fails(self):
        g = FakeGemini(words=600)   # кеңейтүү «иштебей» калат (жалган модель текстти өзгөртпөйт)
        self.assertEqual(self.run_video(g, stop="s1_script"), 1)


if __name__ == "__main__":
    unittest.main()
