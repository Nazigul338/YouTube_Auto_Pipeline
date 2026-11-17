import json
import os
import re
import unittest

from poultry_ig_agent import agent, config, lint
from poultry_ig_agent.tests.helpers import course_file, fake, shots, tmp_out

ROOT = os.path.join(os.path.dirname(__file__), "..")


class Flow(unittest.TestCase):
    def setUp(self):
        self.out = tmp_out()
        os.environ["POULTRY_COURSE_FILE"] = course_file()

    def test_plan_make_ky_ru(self):
        agent.cmd_plan(2, fake)
        ids = agent.cmd_make(2, fake)
        self.assertEqual(len(ids), 4)
        self.assertEqual({i.rsplit("-", 1)[1] for i in ids}, {"ky", "ru"})
        self.assertTrue(os.path.exists(os.path.join(self.out, ids[0], "slide_01.png")))

    def test_run_story_and_reel(self):
        r = agent.run("daily", "practical", "story", "ky", generate=fake)
        self.assertTrue(os.path.exists(os.path.join(self.out, r["id"], "story_01.png")))
        r2 = agent.run(None, "viral", "reel", "ru", generate=fake)
        post = json.load(open(os.path.join(self.out, r2["id"], "post.json"), encoding="utf-8"))
        self.assertEqual(post["status"], "pending_review")
        self.assertEqual(post["lint_issues"], [])
        self.assertIn("AI", post["caption"])           # AI кадр ачыктоосу автоматтык кошулду

    def test_topic_rotation(self):
        agent.run("broiler", "education", "carousel", "ky", generate=fake)
        self.assertNotEqual(agent.pick_topic(), "broiler")

    def test_reel_needs_shots_and_cta(self):
        bad = {"format": "reel", "hook": "h", "voiceover": "v", "caption": "c", "hashtags": []}
        self.assertTrue(lint.lint_post(bad))

    def test_lint_blocks(self):
        for txt in ["AI менен", "Курс 5000 сом", "Автоматизация фермы", "нейросеть", "10 мг", "80% өсөт", "гарантия"]:
            self.assertTrue(lint.lint_post({"format": "reel", "hook": "h", "voiceover": txt, "caption": "c", "hashtags": []}), txt)

    def test_course_price_allowed_only_if_matches(self):
        c = {"price": 3000, "currency": "сом"}
        ok = {"format": "carousel", "hook": "h", "caption": "Баасы 3000 сом", "hashtags": [], "slides": [{"title": "a", "body": "b"}] * 3}
        bad = {**ok, "caption": "Баасы 999 сом"}
        self.assertFalse([i for i in lint.lint_post(ok, c) if "сан" in i])
        self.assertTrue([i for i in lint.lint_post(bad, c) if "сан" in i])

    def test_approval_gates(self):
        pid = agent.save_post(agent.make_post({"format": "reel", "topic_key": "vitamins", "content_type": "education", "lang": "ky", "topic": "Витамин"},
                                              lambda _: {"hook": "h", "voiceover": "v", "caption": "c", "hashtags": [], "shots": shots(),
                                                         "cta": {"text": "x"}, "sources": [{"url": "https://www.woah.org"}]}))
        with self.assertRaises(SystemExit):
            agent.set_status(pid, "approved")                       # ден соолук: --vet-reviewed керек
        agent.set_status(pid, "approved", vet_reviewed=True)


class Isolation(unittest.TestCase):
    def test_no_pipeline_imports_and_own_secrets(self):
        for d, _, fs in os.walk(ROOT):
            if os.sep + "out" in d:
                continue
            for f in fs:
                if f.endswith(".py"):
                    src = open(os.path.join(d, f), encoding="utf-8").read()
                    self.assertIsNone(re.search(r"^\s*(from|import)\s+(pipeline|tests)\b", src, re.M), f)
                    if f not in ("test_agent.py", "config.py"):
                        for bad in ("GOOGLE_API_KEY", "GDRIVE", "PEXELS", "PIXABAY", "YTA_"):
                            self.assertNotIn(bad, src, f)

    def test_workflow_uses_own_secrets(self):
        wf = open(os.path.join(ROOT, "..", ".github", "workflows", "poultry_ig.yml"), encoding="utf-8").read()
        self.assertNotIn("GOOGLE_API_KEY", wf)
        self.assertNotIn("GDRIVE", wf)
        self.assertNotIn("pipeline.ci", wf)


if __name__ == "__main__":
    unittest.main()
