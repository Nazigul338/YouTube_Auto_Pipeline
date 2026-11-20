"""Оригиналдуулук №1: ар видеонун өз монтаж концепциясы, мурункулар менен салыштыруу, QA бөгөтү."""

import json
import random
import shutil
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from pipeline import cinematic, edit_concept as ec, motion
from pipeline.stages.s9_qa import QAStage, Report

V1 = {"concept": "warm_cinematic", "final_cinematic": "x"}                       # Video_001 (эски, концепциясыз)


class TestChoose(unittest.TestCase):
    def test_differs_from_every_finished_video_and_persists(self):
        reg = {"videos": {"Video_001": V1}}
        a = ec.choose(reg, "Video_002", "fear", ["cool_moody", "muted_film"])
        self.assertGreaterEqual(ec.distance(a, ec.fingerprint(V1)), ec.MIN_DIFF)
        reg["videos"]["Video_002"] = {"edit_concept": a, "final": "y"}
        b = ec.choose(reg, "Video_003", "fear", ["cool_moody", "muted_film"])   # ошол эле тема — башка монтаж
        for v in ("Video_001", "Video_002"):
            self.assertGreaterEqual(ec.distance(b, ec.fingerprint(reg["videos"][v])), ec.MIN_DIFF)
        self.assertNotEqual({k: a[k] for k in ec.DIMS}, {k: b[k] for k in ec.DIMS})
        reg["videos"]["Video_003"] = {"edit_concept": b}
        self.assertEqual(ec.choose(reg, "Video_003", "success"), b)              # кайра иштетүүдө өзгөрбөйт

    def test_theme_shapes_concept(self):
        calm = ec.choose({"videos": {}}, "Video_010", "fear")
        drive = ec.choose({"videos": {}}, "Video_011", "confidence")
        self.assertIn(calm["pacing"], ec.THEME_PREFS["calm"]["pacing"])
        self.assertIn(drive["pacing"], ec.THEME_PREFS["drive"]["pacing"])
        self.assertIn(drive["transitions"], ec.THEME_PREFS["drive"]["transitions"])

    def test_many_videos_never_repeat_a_template(self):
        reg = {"videos": {"Video_001": V1}}
        for n in range(2, 12):
            c = ec.choose(reg, f"Video_{n:03d}", random.Random(n).choice(list(ec.THEME_GROUP)))
            for vid, v in reg["videos"].items():
                self.assertGreaterEqual(ec.distance(c, ec.fingerprint(v)), ec.MIN_DIFF, (n, vid))
            reg["videos"][f"Video_{n:03d}"] = {"edit_concept": c, "final": "f"}

    def test_pacing_in_range(self):
        t = {1: 4.0, 2: 3.0, 3: 3.6}
        for name in ec.PACING:
            out = ec.pacing_targets(t, {}, {"pacing": name})
            self.assertTrue(all(2.9 <= v <= 4.3 for v in out.values()), (name, out))
        sb = ec.pacing_targets({1: 3.6, 2: 3.6, 3: 3.6}, {}, {"pacing": "slow_burn"})
        self.assertGreater(sb[1], sb[3])                                        # жайдан тезге


class TestApply(unittest.TestCase):
    def test_motion_palette_and_transitions(self):
        shots = [{"i": k, "scene": k // 3, "kind": "video"} for k in range(30)]
        scenes = {s: {"emotion": "reflective"} for s in range(10)}
        pref = ec.MOTION["lateral"]
        got = [m["motion"].split(":")[1].split("@")[0] for m in motion.plan_motions(shots, scenes, random.Random(1), pref)]
        base = [m["motion"].split(":")[1].split("@")[0] for m in motion.plan_motions(shots, scenes, random.Random(1))]
        self.assertGreater(sum(x in pref for x in got), sum(x in pref for x in base))
        rng = random.Random(2)
        cuts = [cinematic.transition_for(rng, None, "calm", "calm", 0, 20, ec.TRANSITIONS["hard_cuts"]) for _ in range(30)]
        self.assertIn("cut", cuts)
        self.assertTrue(set(cuts) <= set(ec.TRANSITIONS["hard_cuts"]))


class TestQA(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp())
        (self.d / "animation").mkdir()
        (self.d / "animation" / "plan.json").write_text(json.dumps({"concept": "cool_moody"}))

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def run_check(self, mine: dict, prev: dict):
        reg = {"videos": {"Video_001": prev, "Video_002": {"edit_concept": mine}}}
        ctx = SimpleNamespace(path=lambda *p: self.d.joinpath(*p), registry=reg, video_id="Video_002", store=None)
        rep = Report()
        QAStage().check_originality(ctx, rep, {"license": {"file": "m.mp3"}, "mood": "calm"},
                                    {"style": "story", "similarity": {"max_jaccard": 0.0}})
        return {i["key"]: i for i in rep.items}["original_video"]

    def test_template_copy_blocked(self):
        c = {"grade": "cool_moody", "pacing": "pulse", "motion": "lateral", "transitions": "hard_cuts",
             "subtitles": "boxed"}
        prev = {"edit_concept": dict(c), "final": "x", "fingerprint": {"music": "m.mp3", "music_mood": "calm",
                                                                       "style": "story"}}
        r = self.run_check(c, prev)
        self.assertFalse(r["ok"])
        self.assertTrue(r["required"])

    def test_distinct_concept_passes_and_checklist(self):
        c = ec.choose({"videos": {"Video_001": V1}}, "Video_002", "fear")
        r = self.run_check(c, V1)
        self.assertTrue(r["ok"], r["note"])
        rep = Report()
        rep.add("original", "x", True, "")
        rep.add("original_video", "x", False, "")
        cl = QAStage().originality_checklist(rep)
        self.assertEqual(len(cl), 8)
        self.assertFalse(cl[1]["ok"])        # «өз монтаж концепциясы» — жок
        self.assertTrue(cl[0]["ok"])


if __name__ == "__main__":
    unittest.main()
