"""МОТИВАЦИЯ + ПСИХОЛОГИЯ форматы (2026-11-24): 7 бөлүк, бир окуя, Hook 3 сек, бурулуштар."""
import unittest
from types import SimpleNamespace

from pipeline import retention, sections
from tests.fakes import fake_format_map, make_script


def mapped(text, resp=None):
    r = resp if resp is not None else fake_format_map(text)
    return sections.map_sections(SimpleNamespace(json=lambda *a, **k: r), text), r


class TestFormatCheck(unittest.TestCase):
    def setUp(self):
        self.text = make_script(1150, "-x")

    def test_good_script_passes(self):
        info, _ = mapped(self.text)
        rep = sections.check(info, self.text)
        self.assertEqual(rep["problems"], [])
        self.assertTrue(rep["story"]["marked_example"])
        self.assertLessEqual(rep["max_gap_sec"], sections.TURN_GAP_SEC)

    def test_two_stories_and_position(self):
        info, r = mapped(self.text)
        r2 = dict(r, stories=r["stories"] + r["stories"][:1])
        info2, _ = mapped(self.text, r2)
        info2["stories"].append(dict(info2["stories"][0]))
        self.assertTrue(any("бир гана" in p for p in sections.check(info2, self.text)["problems"]))
        early = dict(info, stories=[{"w0": 30, "w1": 200, "summary": "x"}])
        self.assertTrue(any("ортосунда эмес" in p for p in sections.check(early, self.text)["problems"]))

    def test_story_too_long_and_no_story(self):
        info, _ = mapped(self.text)
        n = info["n"]
        big = dict(info, stories=[{"w0": int(0.3 * n), "w1": int(0.7 * n), "summary": "x"}])
        self.assertTrue(any("көлөмү" in p for p in sections.check(big, self.text)["problems"]))
        none = dict(info, stories=[], sections=[s for s in info["sections"] if s["section"] != "story"])
        self.assertTrue(any("окуя жок" in p for p in sections.check(none, self.text)["problems"]))

    def test_real_claim_and_no_marker(self):
        info, _ = mapped(self.text)
        bad = self.text.replace("Например,", "Однажды,") + " Это реальная история моего друга."
        info2 = dict(info, n=len(bad.split()))
        probs = sections.check(info2, bad)["problems"]
        self.assertTrue(any("чыныгы катары" in p for p in probs))
        self.assertTrue(any("мисал катары белгиленген эмес" in p for p in probs))

    def test_long_gap_without_turns(self):
        info, _ = mapped(self.text)
        sparse = dict(info, turns=info["turns"][:3])
        self.assertTrue(any("бурулушсуз" in p for p in sections.check(sparse, self.text)["problems"]))

    def test_repeated_story_is_rejected(self):
        info, _ = mapped(self.text)
        summ = sections.check(info, self.text)["story"]["summary"]
        prev = [{"id": "Video_006", "story_summary": summ}]
        probs = sections.check(info, self.text, prev)["problems"]
        self.assertTrue(any("Video_006" in p for p in probs))
        reg = {"videos": {"Video_006": {"story_example": summ}, "Video_007": {}}}
        self.assertEqual(sections.previous_stories(reg, "Video_007"), prev)

    def test_enforce_rewrites_until_ok(self):
        good = self.text
        bad = good.replace("Например,", "Однажды,")

        class G:
            calls = []

            def json(self, prompt, **k):
                return fake_format_map(prompt.split("СЦЕНАРИЙ:\n", 1)[-1])

            def text(self, prompt, **k):
                self.calls.append(k.get("purpose"))
                return good
        logs = []
        new, info, rep = sections.enforce(G(), bad, "тема", [], logs.append)
        self.assertEqual(new, good)
        self.assertEqual(rep["problems"], [])
        self.assertIn("format_fix", G.calls)

    def test_enforce_accepts_shorter_fix(self):
        """run #45354695418: оңдолгон текст ~25% кыска болгондуктан ташталып, формат бузук калган."""
        good = make_script(870, "-x")
        bad = self.text.replace("Например,", "Однажды,")

        class G:
            prompts = []

            def json(self, prompt, **k):
                return fake_format_map(prompt.split("СЦЕНАРИЙ:\n", 1)[-1])

            def text(self, prompt, **k):
                self.prompts.append(prompt)
                return good
        new, _, rep = sections.enforce(G(), bad, "тема", [], [].append)
        self.assertEqual(new, good)
        self.assertEqual(rep["problems"], [])
        self.assertIn("НЕ МЕНЬШЕ", G.prompts[0])
        # өтө кыска (<55%) вариант мурункудай ташталат
        G.text = lambda self, p, **k: make_script(500, "-x")
        new2, _, _ = sections.enforce(G(), bad, "тема", [], [].append)
        self.assertEqual(new2, bad)

    def test_scene_labels(self):
        info, _ = mapped(self.text)
        w = self.text.split()
        texts = [" ".join(w[k:k + 50]) for k in range(0, len(w), 50)]
        lab = sections.scene_labels(info, texts)
        self.assertEqual(lab[0], "hook")
        self.assertIn("story", lab)
        self.assertEqual(lab[-1], "finale")


class TestHookThreeSeconds(unittest.TestCase):
    def test_thresholds(self):
        self.assertEqual(retention.HOOK_FIRST_WORDS, 8)
        self.assertEqual(retention.HOOK_PHRASE_SEC, 3.0)
        self.assertGreaterEqual(retention.HOOK_MIN_SCORE, 8)
        loc = retention.local_checks("Ты стараешься изо всех сил каждый божий день и всё равно недоволен собой. Почему?")
        self.assertTrue(any("биринчи сүйлөм узун" in p for p in retention.problems(loc, {"hook_score": 9})))

    def test_find_handles_hyphenated_words(self):
        from pipeline.story import _find
        words = "Это что-то странное: номер 23-1 и номер 23-2 рядом.".split()
        self.assertEqual(_find(words, "номер 23-2 рядом", 0), 6)


class TestFirstShot(unittest.TestCase):
    def test_s9_first_shot_check(self):
        import json
        import tempfile
        from pathlib import Path

        from pipeline.stages.s9_qa import QAStage
        d = Path(tempfile.mkdtemp())
        (d / "clips").mkdir()
        shots = [{"start": i * 3.0, "ai_score": 3} for i in range(20)]
        (d / "clips" / "shots.json").write_text(json.dumps({"shots": shots}), encoding="utf-8")
        ctx = SimpleNamespace(path=lambda *p: d.joinpath(*p))
        items = []
        rep = SimpleNamespace(add=lambda key, title, ok, note, required=True: items.append((key, ok)))
        QAStage().check_shot_meaning(ctx, rep)
        self.assertIn(("first_shot", False), items)


if __name__ == "__main__":
    unittest.main()


class TestRuleTurns(unittest.TestCase):
    def test_steps_and_questions_are_turns(self):
        """run #45370647815: «Второй/Третий/Четвертый шаг» бурулуш катары эсептелген эмес (119 сек)."""
        para = " ".join(["слово"] * 60) + "."
        t = " ".join([f"{x} шаг — сделай это. {para}" for x in ("Первый", "Второй", "Третий", "Четвертый")])
        t += " Почему так происходит? " + para
        w = t.split()
        heads = [w[i] for i in sections.rule_turns(t)]
        self.assertEqual(heads, ["Первый", "Второй", "Третий", "Четвертый", "Почему"])
        fmt = {"info": {"ok": True, "n": len(w), "turns": [0]},
               "problems": ["окуя ортосунда эмес", "149 сек жаңы ой/суроо/бурулушсуз (керек ≤40 сек)"]}
        out = sections.refresh_gaps(fmt, t, wps=2.25)
        self.assertEqual(out["problems"], ["окуя ортосунда эмес"])
        self.assertLessEqual(out["max_gap_sec"], sections.TURN_GAP_SEC)
        # бурулушсуз узун текст мурункудай кармалат
        long = " ".join(["слово"] * 300) + "."
        bad = sections.refresh_gaps({"info": {"ok": True, "n": 300, "turns": [0]}, "problems": []}, long)
        self.assertTrue(any("бурулуш" in p for p in bad["problems"]))
