"""Англисче «Tech History» каналы: тил параметри, Wikipedia булагы, факты текшерүү, doc сценарий (жалган API)."""

import json
import os
import re
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from pipeline import ci, lang, retention, sources
from pipeline.config import load_config
from pipeline.storage import LocalStore
from pipeline.textutil import norm, word_count
from tests.fakes import FakeGemini

KEYS = {"GOOGLE_API_KEY": "t", "PIXABAY_API_KEY": "t"}

WIKI = {
    "Lotus 1-2-3": ("Lotus 1-2-3 is a discontinued spreadsheet program from Lotus Software. "
                    "Lotus 1-2-3 was released on January 26, 1983 for the IBM PC. "
                    "It quickly overtook VisiCalc in sales and became the leading spreadsheet of the decade. ") * 12,
    "Mitch Kapor": ("Mitch Kapor founded Lotus Development Corporation in 1982 together with Jonathan Sachs. "
                    "Kapor later co-founded the Electronic Frontier Foundation. ") * 14,
}

FACT_SENT = "Lotus 1-2-3 was released on January 26, 1983 for the IBM PC."
WRONG_SENT = "Lotus 1-2-3 was released in 1979 for the Apple II."


class FakeWiki:
    def __init__(self):
        self.calls = []

    def search(self, q, limit=3):
        self.calls.append(q)
        return [t for t in WIKI if t.lower().split()[0] in q.lower()][:limit] or ["Lotus 1-2-3"]

    def extract(self, title):
        return title, WIKI.get(title, "")


def en_script(n_words: int, seed: str = "", wrong: bool = False) -> str:
    """Англисче жалган сценарий: бир чыныгы факты (же туура эмес факты) + уникалдуу сүйлөмдөр."""
    sents = ["One spreadsheet changed every office desk.", WRONG_SENT if wrong else FACT_SENT]
    i = 0
    while word_count(" ".join(sents)) < n_words:
        sents.append(f"The office of chapter {i + 1}{seed} hummed with beige machines and quiet keyboards at night.")
        i += 1
    return "\n\n".join(" ".join(sents[k:k + 4]) for k in range(0, len(sents), 4))


class FakeGeminiEN(FakeGemini):
    """Англисче doc жолунун жалган Gemini'си. `fix_works=False` — оңдоо фактыны өзгөртпөйт."""

    def __init__(self, words=1220, wrong=False, fix_works=True):
        super().__init__(words)
        self.wrong, self.fix_works = wrong, fix_works

    def text(self, prompt, *, purpose="text", **kw):
        self.calls.append(purpose)
        self.usage.append({"purpose": purpose, "model": "fake"})
        if purpose == "script_draft":
            self.n += 1
            return ("TITLE: The Spreadsheet That Ate The Office\nCARD: One program, every desk\n\n" +
                    en_script(self.words, f"-{self.n}", self.wrong) + "\n\nSOURCES: (ignored)")
        script = prompt.split("SCRIPT:\n", 1)[-1] if purpose == "fact_fix" else prompt.split("TEXT:\n", 1)[-1]
        if purpose == "fact_fix" and self.fix_works:
            return script.replace(WRONG_SENT, FACT_SENT)
        return script

    def json(self, prompt, *, purpose="json", **kw):
        if purpose == "sources_pick":
            self.calls.append(purpose)
            return {"articles": ["Lotus 1-2-3", "Mitch Kapor"]}
        if purpose == "fact_verify":
            self.calls.append(purpose)
            script = prompt.split("SCRIPT:\n", 1)[-1]
            claims = []
            if FACT_SENT in script:
                claims.append({"sentence": FACT_SENT, "claim": "Lotus 1-2-3 released 1983", "supported": True,
                               "source": 1, "quote": "Lotus 1-2-3 was released on January 26, 1983 for the IBM PC"})
            if WRONG_SENT in script:   # Gemini «туура» десе да — цитата булакта жок
                claims.append({"sentence": WRONG_SENT, "claim": "released 1979 Apple II", "supported": True,
                               "source": 1, "quote": "Lotus 1-2-3 was released in 1979 for the Apple II"})
            return {"claims": claims}
        return super().json(prompt, purpose=purpose, **kw)


class TestLangHelpers(unittest.TestCase):
    def test_niche_and_lang(self):
        cfg = load_config("tech_history")
        self.assertTrue(lang.is_en(cfg) and lang.is_doc(cfg))
        self.assertEqual(lang.name(cfg), "English")
        ru = load_config("motivation")
        self.assertFalse(lang.is_en(ru) or lang.is_doc(ru))
        p = "You are the director of a Russian-language psychology YouTube channel. Russian narration."
        self.assertEqual(lang.localize(p, ru), p)                       # орусча канал өзгөрбөйт
        self.assertNotIn("Russian", lang.localize(p, cfg))

    def test_thumbnail_prompts_localized(self):
        from pipeline import thumbnail
        en, ru = load_config("tech_history"), load_config("motivation")
        self.assertEqual(thumbnail.localize(thumbnail.THUMB_PROMPT, ru), thumbnail.THUMB_PROMPT)
        self.assertNotIn("Russian", thumbnail.localize(thumbnail.THUMB_PROMPT, en))
        self.assertNotIn("Russian", thumbnail.localize(thumbnail.VISION_PROMPT, en))

    def test_asr_uses_channel_language(self):
        from pipeline import asr
        seen = {}
        with mock.patch.object(asr, "transcribe", lambda p, h, m, l: seen.setdefault("lang", l) and []):
            asr.get(SimpleNamespace(services={}, cfg=load_config("tech_history")))("x.wav")
        self.assertEqual(seen["lang"], "en")

    def test_retention_english_greeting(self):
        self.assertEqual(retention.local_checks("Hello everyone, today we talk.", "en")["greeting"], "hello")
        self.assertIsNone(retention.local_checks("Hello everyone.", "ru")["greeting"])
        self.assertIn("Rewrite the first", retention.fix_instructions(["hook алсыз"], "en"))


class TestSources(unittest.TestCase):
    ARTS = [{"title": t, "url": sources.url_of(t), "text": x} for t, x in WIKI.items()]

    def test_quote_must_exist_in_source(self):
        ok, _ = sources.check_claim({"supported": True, "claim": "released 1983", "sentence": FACT_SENT,
                                     "quote": "Lotus 1-2-3 was released on January 26, 1983 for the IBM PC"},
                                    self.ARTS)
        self.assertTrue(ok)
        ok, why = sources.check_claim({"supported": True, "claim": "released 1979", "sentence": WRONG_SENT,
                                       "quote": "Lotus 1-2-3 was released in 1979 for the Apple II"}, self.ARTS)
        self.assertFalse(ok)
        self.assertIn("цитата", why)

    def test_number_must_match_quote(self):
        ok, why = sources.check_claim({"supported": True, "claim": "founded in 1984", "sentence": "x",
                                       "quote": "Mitch Kapor founded Lotus Development Corporation in 1982"},
                                      self.ARTS)
        self.assertFalse(ok)
        self.assertIn("1984", why)

    def test_unsupported_by_model(self):
        self.assertFalse(sources.check_claim({"supported": False, "claim": "x"}, self.ARTS)[0])

    def test_pick_articles_skips_empty_and_strips_references(self):
        w = FakeWiki()
        WIKI_EXTRA = "Body text. " * 120 + "\n== References ==\nRef 1"
        with mock.patch.dict(WIKI, {"Lotus 1-2-3": WIKI_EXTRA}):
            arts = sources.pick_articles(FakeGeminiEN(), w, "Lotus 1-2-3 history", lambda *_: None)
        self.assertTrue(arts)
        self.assertNotIn("References", arts[0]["text"])
        self.assertTrue(arts[0]["url"].startswith("https://en.wikipedia.org/wiki/"))


class TestDocScript(unittest.TestCase):
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

    def run_video(self, g, stop="s2_scenes", work="w1", topic="The rise of Lotus 1-2-3"):
        return ci.run_ci(topic, "tech_history", self.root / work, store=self.store, stop_after=stop,
                         services={"gemini": g, "wiki": FakeWiki()})

    def proj(self, work="w1", vid="Video_001"):
        return self.root / work / "Projects" / vid

    def test_english_script_with_verified_facts_and_scenes(self):
        g = FakeGeminiEN()
        self.assertEqual(self.run_video(g), 0)
        p = self.proj()
        text = (p / "script" / "script.txt").read_text(encoding="utf-8")
        self.assertTrue(1150 - 60 <= word_count(text) <= 1300 + 60)
        self.assertIn(FACT_SENT, text)
        meta = json.loads((p / "script" / "meta.json").read_text(encoding="utf-8"))
        self.assertEqual(meta["language"], "en")
        self.assertEqual(meta["title"], "The Spreadsheet That Ate The Office")
        self.assertEqual(meta["hook_card"], "One program, every desk")
        self.assertEqual([s["title"] for s in meta["sources"]], ["Lotus 1-2-3", "Mitch Kapor"])
        facts = json.loads((p / "script" / "facts.json").read_text(encoding="utf-8"))
        self.assertEqual(facts["report"]["n_ok"], 1)
        self.assertFalse(facts["report"]["unsupported"])
        self.assertNotIn("SOURCES", text)
        self.assertNotIn("fact_check", g.calls)                 # орусча факты-редактор чакырылган жок
        self.assertIn("fact_verify", g.calls)
        scenes = json.loads((p / "scenes.json").read_text(encoding="utf-8"))["scenes"]
        self.assertEqual(norm(" ".join(s["text"] for s in scenes)), norm(text))
        reg = self.store.load_registry()["videos"]["Video_001"]
        self.assertEqual(reg["format"], "doc")

    def test_wrong_fact_is_fixed_from_sources(self):
        g = FakeGeminiEN(wrong=True)
        self.assertEqual(self.run_video(g, stop="s1_script"), 0)
        text = (self.proj() / "script" / "script.txt").read_text(encoding="utf-8")
        self.assertNotIn("1979", text)
        self.assertIn(FACT_SENT, text)
        self.assertIn("fact_fix", g.calls)

    def test_unfixable_fact_stops_video(self):
        g = FakeGeminiEN(wrong=True, fix_works=False)
        self.assertEqual(self.run_video(g, stop="s1_script"), 1)
        st = json.loads((self.root / "drive" / "YouTube_Auto" / "Projects" / "Video_001" / "state.json")
                        .read_text(encoding="utf-8"))
        self.assertIn("тастыкталган жок", st["stages"]["s1_script"]["error"])

    def test_no_sources_no_video(self):
        g = FakeGeminiEN()
        with mock.patch.dict(WIKI, {k: "" for k in WIKI}, clear=True):
            self.assertEqual(self.run_video(g, stop="s1_script"), 1)
        self.assertNotIn("script_draft", g.calls)

    def test_scene_prompt_is_english_documentary(self):
        g = FakeGeminiEN()
        prompts = []
        orig = g.json

        def spy(prompt, *, purpose="json", **kw):
            if purpose == "scenes":
                prompts.append(prompt)
            return orig(prompt, purpose=purpose, **kw)
        g.json = spy
        self.assertEqual(self.run_video(g), 0)
        self.assertIn("technology history documentary", prompts[0])
        self.assertIn("NEVER search for brand names", prompts[0])
        self.assertNotIn("Russian", prompts[0])


class TestQAFacts(unittest.TestCase):
    def test_check_facts(self):
        from pipeline.stages.s9_qa import QAStage, Report
        with tempfile.TemporaryDirectory() as d:
            ctx = SimpleNamespace(cfg=load_config("tech_history"), path=lambda *p: Path(d).joinpath(*p))
            (Path(d) / "script").mkdir()
            f = Path(d) / "script" / "facts.json"
            f.write_text(json.dumps({"report": {"source": "gemini", "n": 3, "n_ok": 3, "unsupported": []},
                                     "sources": [{"title": "Lotus 1-2-3"}]}))
            rep = Report()
            QAStage().check_facts(ctx, rep)
            self.assertTrue(rep.items[0]["ok"])
            f.write_text(json.dumps({"report": {"source": "gemini", "n": 3, "n_ok": 2,
                                                "unsupported": [{"claim": "x"}]}}))
            rep = Report()
            QAStage().check_facts(ctx, rep)
            self.assertFalse(rep.items[0]["ok"])
            rep = Report()
            QAStage().check_facts(SimpleNamespace(cfg=load_config("motivation"), path=ctx.path), rep)
            self.assertEqual(rep.items, [])                      # орусча каналда бул текшерүү жок


if __name__ == "__main__":
    unittest.main()


@unittest.skipIf(os.environ.get("YTA_SKIP_SLOW"), "узак тест")
class TestFullEnglishPipeline(unittest.TestCase):
    """Тема → даяр MP4 (англисче doc): жалган API, ЧЫНЫГЫ FFmpeg."""

    def test_topic_to_final_mp4_en(self):
        import subprocess
        from pipeline import media
        from tests.fakes import FakeStock
        from tests.test_stages_audio import fake_whisper_for

        with tempfile.TemporaryDirectory() as d, mock.patch("builtins.print"), \
                mock.patch.dict(os.environ, KEYS):
            root = Path(d)
            store = LocalStore(root / "drive")
            music = root / "drive" / "YouTube_Auto" / "Music" / "YouTube_Audio_Library_Attribution"
            music.mkdir(parents=True)
            subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "sine=f=330:d=20", "-ac", "2",
                            str(music / "Calm Piano - Tester.mp3")], check=True)
            proj = root / "w" / "Projects" / "Video_001"
            services = {"gemini": FakeGeminiEN(words=130), "stock": FakeStock(), "wiki": FakeWiki(),
                        "asr": fake_whisper_for(proj)}
            with mock.patch.object(ci, "load_config") as lc:
                lc.side_effect = lambda n, drive_root=None: load_config(
                    "tech_history", drive_root=drive_root, words_min=110, words_max=150, min_duration_sec=30)
                code = ci.run_ci("The rise of Lotus 1-2-3", "tech_history", root / "w", store=store,
                                 services=services)
            state = json.loads((proj / "state.json").read_text(encoding="utf-8"))
            failed = {k: v.get("error") for k, v in state["stages"].items() if v["status"] != "done"}
            self.assertEqual(failed, {})
            self.assertEqual(code, 0)
            drive = root / "drive" / "YouTube_Auto"
            self.assertTrue((drive / "Final_Videos" / "Video_001.mp4").exists())
            info = media.probe(drive / "Final_Videos" / "Video_001.mp4")
            self.assertTrue(any(s["codec_type"] == "audio" for s in info["streams"]))
            desc = (drive / "Projects" / "Video_001" / "youtube_description.txt").read_text(encoding="utf-8")
            self.assertIn("Sources:", desc)
            self.assertIn("https://en.wikipedia.org/wiki/Lotus_1-2-3", desc)
            self.assertNotIn("Видеоматериалы", desc)
            report = (drive / "Projects" / "Video_001" / "report.txt").read_text(encoding="utf-8")
            self.assertIn("Фактылар булак", report)
