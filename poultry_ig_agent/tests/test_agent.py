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
                        # мотивациянын secret'тери (POULTRY_ префикси жок) колдонулбашы керек
                        for bad in ("GOOGLE_API_KEY", "GDRIVE_", "PEXELS_API_KEY", "PIXABAY_API_KEY", "YTA_"):
                            self.assertIsNone(re.search(r"(?<!POULTRY_)\b" + bad, src), f"{f}: {bad}")

    def test_workflow_uses_own_secrets(self):
        wf = open(os.path.join(ROOT, "..", ".github", "workflows", "poultry_ig.yml"), encoding="utf-8").read()
        self.assertNotIn("GOOGLE_API_KEY", wf)
        self.assertNotIn("GDRIVE", wf)
        self.assertNotIn("pipeline.ci", wf)


if __name__ == "__main__":
    unittest.main()


class OwnText(unittest.TestCase):
    def setUp(self):
        self.out = tmp_out()
        os.environ["POULTRY_COURSE_FILE"] = course_file()

    def _fake(self, prompt):
        self.prompt = prompt
        return {"hook_onscreen": "ТАҢ", "shots": shots(4), "caption": "Сиз кантесиз? 👇", "hashtags": ["#ферма"],
                "cta": {"type": "comment", "text": "Жазыңыз"}, "voiceover": "LLM ӨЗГӨРТҮП КОЙГОН ТЕКСТ"}

    def test_text_kept_verbatim(self):
        txt = "Таң атты. Тооктор жем күтүп турат! Бүгүн суу идишин тазалайбыз."
        r = agent.run(own_text=txt, generate=self._fake)
        post = json.load(open(os.path.join(self.out, r["id"], "post.json"), encoding="utf-8"))
        self.assertEqual(post["voiceover"], txt)                 # LLM алмаштыра албайт
        self.assertEqual(post["hook"], "Таң атты.")
        self.assertTrue(post["own_text"])
        self.assertIn(txt, self.prompt)
        self.assertEqual(open(os.path.join(self.out, r["id"], "voiceover.txt"), encoding="utf-8").read().strip(), txt)

    def test_own_text_still_linted(self):
        r = agent.run(own_text="Бул дары менен 10 мг берсеңиз болот.", generate=self._fake)
        post = json.load(open(os.path.join(self.out, r["id"], "post.json"), encoding="utf-8"))
        self.assertEqual(post["status"], "needs_fix")            # доза — автордуку болсо да тосулат

    def test_empty_text_rejected(self):
        with self.assertRaises(ValueError):
            agent.make_post_from_text("  ", {}, self._fake)


@unittest.skipUnless(__import__("shutil").which("ffmpeg"), "ffmpeg жок")
class VoiceCmd(unittest.TestCase):
    def test_voice_mp3(self):
        import wave
        out = tmp_out()

        class T:
            def synth(self, text, path):
                with wave.open(path, "wb") as w:
                    w.setnchannels(1); w.setsampwidth(2); w.setframerate(24000); w.writeframes(b"\x01\x02" * 24000 * 2)
                return path
        pid = agent.save_post({"format": "reel", "lang": "ky", "topic": "t", "hook": "h", "voiceover": "Таң атты.", "shots": shots()})
        r = agent.cmd_voice(pid, T())
        self.assertTrue(os.path.exists(os.path.join(out, pid, "voice.mp3")))
        self.assertAlmostEqual(r["seconds"], 2, delta=0.2)


class Normalize(unittest.TestCase):
    def test_messy_llm_output(self):
        p = agent.normalize({"sources": ["https://www.fao.org", {"url": "https://www.woah.org"}], "hashtags": "ферма, #тоок",
                             "cta": "Комментарий жазыңыз", "shots": ["hens", {"visual": "coop", "duration": "5"}]})
        self.assertEqual(p["sources"], [{"url": "https://www.fao.org"}, {"url": "https://www.woah.org"}])
        self.assertEqual(p["hashtags"], ["#ферма", "#тоок"])
        self.assertEqual(p["cta"]["text"], "Комментарий жазыңыз")
        self.assertEqual([s["n"] for s in p["shots"]], [1, 2]); self.assertEqual(p["shots"][1]["duration"], 5.0)

    def test_string_sources_do_not_crash_own_text(self):
        out = tmp_out()
        os.environ["POULTRY_COURSE_FILE"] = course_file()
        fake = lambda _: {"shots": shots(4), "caption": "x", "hashtags": [], "cta": "Жазыңыз", "sources": ["https://www.fao.org"]}
        r = agent.run(own_text="Балапандар өлүп калбасын. Суу таза болсун.", generate=fake)
        post = json.load(open(os.path.join(out, r["id"], "post.json"), encoding="utf-8"))
        self.assertIn("ветеринар", post["caption"])
