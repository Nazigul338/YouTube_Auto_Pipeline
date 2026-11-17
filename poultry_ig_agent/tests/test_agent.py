import os
import re
import tempfile
import unittest

from poultry_ig_agent import agent, config, lint

ROOT = os.path.join(os.path.dirname(__file__), "..")


def fake(prompt):
    if '"items"' in prompt:
        return {"items": [{"day": 1, "pillar": "motivation", "format": "carousel", "topic": "Эрте туруу", "angle": "x"},
                          {"day": 2, "pillar": "soft_sales", "format": "reel", "topic": "Курс", "angle": "y"}]}
    ru = "орус" in prompt
    if "slides" in prompt:
        return {"hook": "Утро фермера" if ru else "Тоок эрте турат", "caption": "?", "hashtags": ["#ферма"],
                "slides": [{"title": f"T{i}", "body": "Текст."} for i in range(6)]}
    return {"hook": "h", "voiceover": "Рассвет на ферме." if ru else "Таң атты.", "caption": "c", "hashtags": [], "shots": ["a"]}


class Behaviour(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        config.OUT_DIR = self.tmp

    def test_ky_and_ru_posts(self):
        agent.cmd_plan(2, fake)
        ids = agent.cmd_make(2, fake)
        self.assertEqual(len(ids), 4)                      # 2 идея × (ky+ru)
        self.assertEqual(len(set(ids)), 4)                 # ID кагылышпайт
        self.assertEqual({i.rsplit("-", 1)[1] for i in ids}, {"ky", "ru"})
        agent.set_status(ids[0], "approved")

    def test_lint_blocks_price_ai_dose_ru_ky(self):
        for txt in ["AI менен", "80% өсөт", "Курс 5000 сом", "Автоматизация фермы", "нейросеть", "вакцина", "10 мг"]:
            bad = {"format": "reel", "hook": "h", "voiceover": txt, "caption": "c", "hashtags": []}
            self.assertTrue(lint.lint_post(bad), txt)

    def test_needs_fix_cannot_approve(self):
        bad = lambda _: {"hook": "h", "voiceover": "автоматташтыруу", "caption": "c", "hashtags": []}
        pid = agent.save_post(agent.make_post({"format": "reel", "pillar": "motivation", "topic": "t"}, bad))
        with self.assertRaises(SystemExit):
            agent.set_status(pid, "approved")


class Isolation(unittest.TestCase):
    """Poultry менен Motivation YouTube пайплайны бири-бирине көз карандысыз."""

    def _py(self):
        for d, _, fs in os.walk(ROOT):
            if "out" in d.split(os.sep):
                continue
            for f in fs:
                if f.endswith(".py") and f != "test_agent.py":
                    yield os.path.join(d, f)

    def test_no_pipeline_imports(self):
        for p in self._py():
            src = open(p, encoding="utf-8").read()
            self.assertIsNone(re.search(r"^\s*(from|import)\s+(pipeline|tests)\b", src, re.M), p)

    def test_own_secret_and_output(self):
        src = open(os.path.join(ROOT, "llm.py"), encoding="utf-8").read()
        self.assertIn("POULTRY_GEMINI_API_KEY", src)
        for name in ("GOOGLE_API_KEY", "GDRIVE", "PEXELS", "PIXABAY", "YTA_"):
            self.assertNotIn(name, src)
        self.assertIn("poultry_ig_agent", os.path.abspath(config.__file__))
        self.assertNotIn("YouTube_Auto", open(os.path.join(ROOT, "config.py"), encoding="utf-8").read())

    def test_motivation_tree_untouched_by_workflow(self):
        wf = open(os.path.join(ROOT, "..", ".github", "workflows", "poultry_ig.yml"), encoding="utf-8").read()
        self.assertNotIn("GOOGLE_API_KEY", wf)
        self.assertNotIn("pipeline.ci", wf)


if __name__ == "__main__":
    unittest.main()
