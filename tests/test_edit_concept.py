"""Оригиналдуулук №1: ар видеонун өз ЧЫГАРМАЧЫЛЫК концепциясы, кайра жазуу, салыштыруу, QA бөгөтү.

Толук pipeline'дын ар этабы концепцияны колдонгону: tests/test_originality_pipeline.py (узак).
"""

import json
import os
import random
import shutil
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from pipeline import cinematic, edit_concept as ec, motion
from pipeline.stages.s9_qa import QAStage, Report
from pipeline.storage import LocalStore

V1 = {"concept": "warm_cinematic", "final_cinematic": "x"}          # Video_001 — эски, концепциясыз (өзгөрбөйт)
SCENES = [{"id": i, "emotion": e, "theme": "psychology", "text": f"сахна {i}"}
          for i, e in enumerate(["calm", "tense", "dramatic", "hopeful", "inspired", "reflective"], 1)]


def raw_brief(**kw):
    b = {"name": "Glass Mirrors", "world": "Reflections and windows; the story is told through glass.",
         "motifs": ["mirror", "window", "glass"], "scene_motifs": {"1": "woman mirror morning", "99": "x"},
         "grade": {"contrast": 1.12, "saturation": 0.8, "gamma": 0.98, "warmth": -0.6, "tint": 0.1, "vignette": 4},
         "base_shot": 4.1, "act_pace": [1.1, 1.0, 0.88, 1.05],
         "motion": {"dolly": 1, "zoom_in": 0.5}, "motion_intensity": 0.8,
         "transitions": {"fadeblack": 1, "dissolve": 0.5}, "transition_sec": 0.8,
         "subtitles": {"font": "DejaVu Serif Bold", "primary": "#F0E8DC", "highlight": "#7AD2E8", "outline": 3,
                       "box": False, "size": 70},
         "cards": {"every": 6, "color": "#A0D0F0"}, "music_mood": "dark_cinematic", "music_level": 1.5}
    b.update(kw)
    return b


class FakeG:
    def __init__(self, answers):
        self.answers, self.prompts = list(answers), []

    def json(self, prompt, **kw):
        self.prompts.append(prompt)
        a = self.answers.pop(0) if self.answers else {}
        if isinstance(a, Exception):
            raise a
        return a


def ctx_for(registry, gem, vid="Video_002", d=None):
    d = d or Path(tempfile.mkdtemp())
    return SimpleNamespace(registry=registry, video_id=vid, services={"gemini": gem}, path=lambda *p: d.joinpath(*p),
                           log=lambda m: None, cfg=SimpleNamespace(niche_data={"music_moods": [
                               "emotional_piano", "cinematic", "dark_cinematic", "inspirational"]}),
                           store=LocalStore(d))


class TestNormalize(unittest.TestCase):
    def test_clamps_and_cleans(self):
        b = ec.normalize({"grade": {"contrast": 9, "saturation": -3}, "base_shot": 10, "act_pace": [0.1, 5],
                          "subtitles": {"font": "Comic Sans", "primary": "red", "size": 200},
                          "scene_motifs": {"1": "ok", "7": "drop"}, "music_mood": "polka"},
                         ["cinematic"], [1, 2])
        self.assertEqual((b["grade"]["contrast"], b["grade"]["saturation"]), (1.16, 0.7))
        self.assertEqual(b["base_shot"], 4.3)
        self.assertEqual(b["act_pace"][:2], [0.85, 1.15])
        self.assertEqual((b["subtitles"]["font"], b["subtitles"]["primary"], b["subtitles"]["size"]),
                         (ec.FONTS[0], "#FFFFFF", 76))
        self.assertEqual(b["scene_motifs"], {"1": "ok"})
        self.assertEqual(b["music_mood"], "cinematic")
        self.assertAlmostEqual(sum(b["motion"].values()), 1.0, places=2)


class TestCreate(unittest.TestCase):
    def test_gemini_concept_used(self):
        g = FakeG([raw_brief()])
        b = ec.create(ctx_for({"videos": {"Video_001": V1}}, g), SCENES, "Тест")
        self.assertEqual((b["source"], b["name"], b["attempts"]), ("gemini", "Glass Mirrors", 1))
        self.assertIn("Video_001", g.prompts[0])            # мурунку видео prompt'то
        self.assertIn("NO cartoons", g.prompts[0])          # кадр эрежелери

    def test_too_similar_is_redesigned(self):
        prev = ec.normalize(raw_brief())
        reg = {"videos": {"Video_001": V1, "Video_002": {"edit_brief": prev, "final": "y"}}}
        other = raw_brief(name="Warm Hands", motifs=["hands", "tea cup", "kitchen"],
                          grade={"contrast": 1.02, "saturation": 1.18, "gamma": 1.04, "warmth": 0.9, "tint": -0.5,
                                 "vignette": 5.8}, base_shot=3.0, act_pace=[0.88, 0.9, 1.1, 1.15],
                          motion={"pan_left": 1, "pan_right": 1, "handheld": 1}, motion_intensity=1.25,
                          transitions={"cut": 1, "smoothleft": 1}, transition_sec=0.4,
                          subtitles={"font": "Montserrat Black", "primary": "#FFFFFF", "highlight": "#FF6040",
                                     "outline": 6, "box": True, "size": 74},
                          music_mood="inspirational", music_level=-1.5)
        g = FakeG([raw_brief(), other])                       # 1-аракет — көчүрмө, 2-си — жаңы
        b = ec.create(ctx_for(reg, g, "Video_003"), SCENES)
        self.assertEqual((b["name"], b["attempts"]), ("Warm Hands", 2))
        self.assertIn("TOO SIMILAR", g.prompts[1])
        for vid in ("Video_001", "Video_002"):
            self.assertTrue(b["checks"][vid]["ok"], b["checks"][vid])

    def test_fallback_when_gemini_fails_or_keeps_copying(self):
        prev = ec.normalize(raw_brief())
        reg = {"videos": {"Video_001": V1, "Video_002": {"edit_brief": prev, "final": "y"}}}
        for gem in (FakeG([RuntimeError("503")]), FakeG([raw_brief()] * 3)):
            b = ec.create(ctx_for(reg, gem, "Video_003"), SCENES)
            self.assertEqual(b["source"], "fallback")
            self.assertTrue(all(r["ok"] for r in b["checks"].values()), b["checks"])

    def test_twelve_videos_never_share_a_template(self):
        reg = {"videos": {"Video_001": V1}}
        for n in range(2, 14):
            vid = f"Video_{n:03d}"
            b = ec.create(ctx_for(reg, FakeG([RuntimeError("off")]), vid), SCENES)
            for other, v in ec.finished_others(reg, vid).items():
                self.assertTrue(ec.compare(b, ec.brief_of(v))["ok"], (vid, other))
            reg["videos"][vid] = {"edit_brief": b, "final": "f"}

    def test_get_persists_and_reject_forces_new(self):
        d = Path(tempfile.mkdtemp())
        try:
            reg = {"videos": {}}
            c = ctx_for(reg, FakeG([raw_brief()]), "Video_005", d)
            (d / "scenes.json").write_text(json.dumps({"scenes": SCENES}))
            b = ec.get(c)
            self.assertEqual(ec.get(c), b)                                      # кайра иштетүүдө өзгөрбөйт
            self.assertTrue((d / "edit_brief.json").exists())
            ec.reject(c, "окшош")
            self.assertNotIn("edit_brief", reg["videos"]["Video_005"])
            self.assertFalse((d / "edit_brief.json").exists())
            self.assertEqual(reg["videos"]["Video_005"]["rejected_briefs"][0]["name"], "Glass Mirrors")
        finally:
            shutil.rmtree(d, ignore_errors=True)


class TestApply(unittest.TestCase):
    def setUp(self):
        self.b = ec.normalize(raw_brief())

    def test_pacing_follows_concept(self):
        t = {i: 3.6 for i in range(1, 9)}
        out = ec.pacing_targets(t, {}, self.b)
        self.assertTrue(all(2.9 <= v <= 4.3 for v in out.values()))
        self.assertGreater(out[1], out[6])                    # 1-акт 1.1, 3-акт 0.88
        fast = ec.pacing_targets(t, {}, ec.normalize(raw_brief(base_shot=3.0)))
        self.assertLess(sum(fast.values()), sum(out.values()))

    def test_grade_subtitles_cards(self):
        p = ec.concept_params(self.b)
        self.assertIn("contrast=1.120", p["grade"])
        self.assertIn("saturation=0.800", p["grade"])
        self.assertEqual(p["vignette"], "PI/4.00")
        self.assertEqual(p["card_every"], 6)
        style, hl = ec.subtitle_style(self.b, "DejaVu Serif", 96)
        self.assertIn(",70,&H00DCE8F0,", style)               # түс BGR, өлчөм 70
        self.assertEqual(hl, "{\\c&HE8D27A&}")

    def test_motion_and_transitions(self):
        self.assertEqual(ec.motion_prefer(self.b)[0], "dolly")
        pal = ec.transition_palette(self.b)
        self.assertEqual(set(pal), {"fadeblack", "dissolve"})
        shots = [{"i": k, "scene": k // 3, "kind": "video"} for k in range(30)]
        scenes = {s: {"emotion": "reflective"} for s in range(10)}
        got = [m["motion"].split(":")[1].split("@")[0]
               for m in motion.plan_motions(shots, scenes, random.Random(1), ec.motion_prefer(self.b))]
        self.assertGreater(got.count("dolly"), 3)
        rng = random.Random(3)
        tr = {cinematic.transition_for(rng, None, "calm", "calm", 0, 40, pal) for _ in range(40)}
        self.assertTrue(tr <= {"fadeblack", "dissolve"})


class TestQA(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp())
        (self.d / "script").mkdir()
        (self.d / "script" / "script.txt").write_text("Почему мы живём для других? Это вопрос.\n\nДругой абзац.")

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def run_qa(self, mine, prev, mine_hook=None):
        reg = {"videos": {"Video_001": V1, "Video_002": prev, "Video_003": {"edit_brief": mine}}}
        ctx = SimpleNamespace(path=lambda *p: self.d.joinpath(*p), registry=reg, video_id="Video_003", store=None)
        rep = Report()
        QAStage().check_originality(ctx, rep, {"license": {"file": "m.mp3"}, "mood": "calm"},
                                    {"style": "story", "similarity": {"max_jaccard": 0.0}})
        return {i["key"]: i for i in rep.items}["original_video"], reg

    def test_copied_template_blocked_and_concept_rejected(self):
        b = ec.normalize(raw_brief())
        r, reg = self.run_qa(dict(b), {"edit_brief": dict(b), "final": "x"})
        self.assertFalse(r["ok"])
        self.assertTrue(r["required"])
        self.assertIn("КАЙРА", r["note"])
        self.assertNotIn("edit_brief", reg["videos"]["Video_003"])          # кайра иштетүүдө жаңы концепция

    def test_same_hook_blocked(self):
        a = ec.normalize(raw_brief())
        prev = {"edit_brief": ec.fallback({"videos": {"x": {"edit_brief": a, "final": 1}}}, "Video_002", "fear", [], []),
                "final": "x", "fingerprint": {"hook": "Почему мы живём для других? Это вопрос."}}
        r, _ = self.run_qa(a, prev)
        self.assertFalse(r["ok"])
        self.assertIn("hook", r["note"])

    def test_distinct_passes(self):
        a = ec.normalize(raw_brief())
        prev = {"edit_brief": ec.fallback({"videos": {"x": {"edit_brief": a, "final": 1}}}, "Video_002", "fear", [], []),
                "final": "x", "fingerprint": {"hook": "Совсем другое начало истории про утро."}}
        r, _ = self.run_qa(a, prev)
        self.assertTrue(r["ok"], r["note"])
        self.assertTrue((self.d / "originality.json").exists())

    def test_checklist_has_eight_items(self):
        rep = Report()
        rep.add("original", "x", True, "")
        rep.add("original_video", "x", False, "")
        cl = QAStage().originality_checklist(rep)
        self.assertEqual(len(cl), 8)
        self.assertFalse(cl[1]["ok"])


if __name__ == "__main__":
    unittest.main()
