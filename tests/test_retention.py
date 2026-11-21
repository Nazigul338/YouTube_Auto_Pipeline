"""Hook + көрүүчүнү кармоо + обложканын чынчылдыгы (жалган Gemini, чыныгы FFmpeg)."""

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from pipeline import retention as rt, thumbnail

GOOD = ("Почему чужое молчание пугает вас сильнее крика? Через восемь минут вы поймёте, откуда этот страх и как "
        "перестать читать мысли других.\n\nАнна ждёт ответа на сообщение уже третий час. Она перечитывает свой текст "
        "и ищет ошибку. Мозг заполняет тишину худшим вариантом, потому что неизвестность для него опаснее плохой "
        "новости. Что если тишина вообще не про вас?\n\nЧаще всего у человека просто занят вечер. Поэтому первый шаг — "
        "назвать свою догадку догадкой, а не фактом.\n\nМолчание другого человека — это пустая страница, и только вы "
        "решаете, что на ней написать.")
WEAK = ("Привет, друзья, сегодня поговорим о том, как важно иногда остановиться и подумать о своей жизни, ведь все мы "
        "иногда устаём и не знаем, что делать дальше.\n\n" + GOOD.split("\n\n", 1)[1])


class FakeG:
    def __init__(self, reviews, fixed=None):
        self.reviews, self.fixed, self.calls = list(reviews), fixed, []

    def json(self, prompt, purpose="", **kw):
        self.calls.append(purpose)
        return self.reviews.pop(0) if self.reviews else {}

    def text(self, prompt, purpose="", **kw):
        self.calls.append(purpose)
        return self.fixed if self.fixed is not None else prompt.split("ТЕКСТ:\n", 1)[1]


def rev(score=8, end=8, delivered=True, quote="назвать свою догадку догадкой, а не фактом", false=()):
    return {"hook_score": score, "hook_reason": "x", "hook_on_topic": True, "intro_drag": score < 5,
            "promise": "откуда страх", "promise_delivered": delivered, "delivered_quote": quote,
            "false_promises": list(false), "repetitions": [], "sag_points": [], "reengagement": ["Что если"],
            "ending_score": end, "ending_lesson": "y", "retention_strategy": "открытый вопрос в середине"}


class TestLocal(unittest.TestCase):
    def test_good_and_weak_openings(self):
        g, w = rt.local_checks(GOOD), rt.local_checks(WEAK)
        self.assertIsNone(g["greeting"])
        self.assertLessEqual(g["first_words"], rt.HOOK_FIRST_WORDS)
        self.assertEqual(w["greeting"], "привет")
        self.assertGreater(w["first_words"], rt.HOOK_FIRST_WORDS)
        self.assertEqual(rt.problems(g, {"source": "none"}), [])
        self.assertEqual(len(rt.problems(w, {"source": "none"})), 2)

    def test_quote_must_really_exist(self):
        self.assertTrue(rt.quote_in_text("назвать свою догадку догадкой", GOOD))
        self.assertFalse(rt.quote_in_text("учёные из Гарварда доказали обратное", GOOD))


class TestReview(unittest.TestCase):
    def test_fake_quote_downgrades_promise(self):
        r = rt.review(FakeG([rev(quote="секретная техника миллионеров")]), GOOD, "t", "question")
        self.assertFalse(r["promise_delivered"])
        self.assertIn("убада видеодо берилбейт", " ".join(rt.problems(rt.local_checks(GOOD), r)))

    def test_no_gemini_answer_is_local_only(self):
        self.assertEqual(rt.review(FakeG([{}]), GOOD, "t", "q")["source"], "none")

    def test_false_promise_and_weak_ending_are_problems(self):
        p = rt.problems(rt.local_checks(GOOD), rt.review(FakeG([rev(end=4, false=["три секрета"])]), GOOD, "t", "q"))
        self.assertTrue(any("жалган убада" in x for x in p) and any("жыйынтык" in x for x in p))


class TestImprove(unittest.TestCase):
    def test_weak_hook_is_rewritten_and_rechecked(self):
        g = FakeG([rev(score=3), rev(score=8)], fixed=GOOD)
        logs = []
        text, r = rt.improve(g, WEAK, "Страх молчания", "question", logs.append)
        self.assertEqual(text, GOOD)
        self.assertTrue(r["ok"], r["problems"])
        self.assertEqual(r["rounds"], 2)
        self.assertIn("retention_fix", g.calls)
        self.assertTrue(any("кайра жазылды" in l for l in logs))

    def test_worse_rewrite_is_not_accepted(self):
        g = FakeG([rev(score=6), rev(score=2, end=2, delivered=False)], fixed=WEAK)
        text, r = rt.improve(g, GOOD, "t", "q", lambda *_: None)
        self.assertEqual(text, GOOD)

    def test_good_script_untouched(self):
        g = FakeG([rev()])
        text, r = rt.improve(g, GOOD, "t", "q", lambda *_: None)
        self.assertEqual((text, r["ok"]), (GOOD, True))
        self.assertNotIn("retention_fix", g.calls)


class TestTimingAndChecklist(unittest.TestCase):
    def test_hook_timing_from_voice(self):
        words = [{"w": w, "s": i * 0.4, "e": i * 0.4 + 0.35} for i, w in enumerate(GOOD.split())]
        t = rt.hook_timing(words, GOOD)
        self.assertEqual(t["sentence_words"], 7)
        self.assertLess(t["phrase_end_sec"], rt.HOOK_PHRASE_SEC)

    def test_viewer_checklist_six_answers(self):
        ret = {"local": rt.local_checks(GOOD), "review": dict(rt.review(FakeG([rev()]), GOOD, "t", "q"))}
        thumb = {"quality": [{"text": "ЧУЖОЕ МОЛЧАНИЕ", "contrast": 0.2, "words": 2, "ok": True,
                              "support": "x", "support_found": True}]}
        vc = rt.viewer_checklist(ret, {"phrase_end_sec": 2.1, "sentence_end_sec": 2.8}, thumb, True)
        self.assertEqual(len(vc), 6)
        self.assertTrue(all(x["ok"] for x in vc), vc)
        vc2 = rt.viewer_checklist(ret, {"phrase_end_sec": 7.5}, {"quality": []}, False)
        self.assertEqual({x["key"]: x["ok"] for x in vc2}["hook_attention"], False)


class TestThumbnailRules(unittest.TestCase):
    def test_layout_and_accent_differ_from_previous(self):
        reg = {"videos": {"Video_001": {"thumbnail": {"layout": "left", "accent": "0xFFD21F"}},
                          "Video_003": {"thumbnail": {"layout": "right", "accent": "0x4FD8FF"}}}}
        lay = thumbnail.choose_layout(reg, "Video_004", "s")
        self.assertNotIn(lay, ("left", "right"))
        self.assertNotEqual(thumbnail.choose_accent(reg, "Video_004", "0x4FD8FF").upper(), "0X4FD8FF")
        self.assertEqual(thumbnail.choose_accent(reg, "Video_004", "0xFF5A36"), "0xFF5A36")

    def test_auto_thumbnails_rejects_clickbait(self):
        d = Path(tempfile.mkdtemp())
        try:
            for sub in ("clips", "script", "subtitles"):
                (d / sub).mkdir()
            subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc2=s=1280x720:d=4",
                            "-pix_fmt", "yuv420p", str(d / "clips" / "c0.mp4")], check=True)
            shots = [{"i": 0, "start": 0, "end": 4, "dur": 4, "file": "c0.mp4", "kind": "video", "source": "pixabay",
                      "ai_score": 5}]
            (d / "clips" / "shots.json").write_text(json.dumps({"shots": shots}), encoding="utf-8")
            (d / "script" / "script.txt").write_text(GOOD, encoding="utf-8")
            (d / "script" / "meta.json").write_text(json.dumps({"title": "Страх молчания", "hook": "x"}), encoding="utf-8")
            opts = [{"line1": "ТИШИНА", "line2": "НЕ ПРО ВАС?", "shot": 0, "emotion": "тревога",
                     "support": "Что если тишина вообще не про вас"},
                    {"line1": "СЕКРЕТ", "line2": "МИЛЛИОНЕРОВ", "shot": 0, "support": "тайный метод богатых людей"}]
            gem = SimpleNamespace(json=lambda *a, **k: opts,
                                  judge_image=lambda *a, **k: {"attention": 7, "topic_match": 8, "problems": []})
            ctx = SimpleNamespace(video_id="Video_004", registry={"videos": {}}, store=None, services={"gemini": gem},
                                  path=lambda *p: d.joinpath(*p), log=lambda *_: None)
            from unittest import mock

            with mock.patch("pipeline.stages.base.gemini_of", return_value=gem):
                th = thumbnail.auto_thumbnails(ctx, "Страх молчания")
            self.assertEqual(th["texts"], ["ТИШИНА НЕ ПРО ВАС?"])
            self.assertTrue(any("clickbait" in r for r in th["rejected"]), th["rejected"])
            q = th["quality"][0]
            self.assertTrue(q["support_found"] and q["ok"] and q["contrast"] >= thumbnail.MIN_CONTRAST, q)
            self.assertTrue(q["vision"]["ok"])
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_vision_review_rejects_foreign_text_and_keeps_good(self):
        d = Path(tempfile.mkdtemp())
        try:
            img = d / "t.jpg"
            subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc2=s=1280x720", "-frames:v", "1",
                            str(img)], check=True)
            bad = SimpleNamespace(judge_image=lambda *a, **k: {"attention": 8, "topic_match": 7,
                                                               "problems": ["foreign_text"], "note": "бейдж"})
            good = SimpleNamespace(judge_image=lambda *a, **k: {"attention": 8, "topic_match": 8, "problems": [],
                                                                "emotion": "тревога"})
            self.assertFalse(thumbnail.vision_review(bad, img, "t", "x", "")["ok"])
            self.assertTrue(thumbnail.vision_review(good, img, "t", "x", "")["ok"])
            self.assertIsNone(thumbnail.vision_review(SimpleNamespace(), img, "t", "x", ""))
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_top_layout_renders(self):
        d = Path(tempfile.mkdtemp())
        try:
            src = d / "s.mp4"
            subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc2=s=1920x1080:d=2",
                            "-pix_fmt", "yuv420p", str(src)], check=True)
            out = thumbnail.make(src, 1.0, "ПОЧЕМУ", "ТИШИНА?", d / "t.jpg", d, layout="top", boost=1.25)
            self.assertTrue(thumbnail.quality(out)["ok_image"])
        finally:
            shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
