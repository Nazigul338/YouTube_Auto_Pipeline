"""Сапатты жакшыртуу (TEST): катуу темп, AI маани текшерүү, концепция туруктуулугу, мүнөт сайын бирдейлик."""

import os
import random
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from pipeline import uniformity
from pipeline.stages import s6_animation
from pipeline.stages.s5_visuals import STRICT_MAX, STRICT_MIN, VisualsStage, plan_shots, strict_cuts
from pipeline.stock import PIXABAY_LICENSE, Asset


class TestStrictPacing(unittest.TestCase):
    def test_samples(self):
        for d, want in ((4.6, 1), (5.0, 2), (9.0, 3), (12.6, 4), (19.0, 5)):
            c = strict_cuts(0.0, d, [])
            self.assertEqual(len(c) - 1, want, d)
            self.assertAlmostEqual(c[-1], d)

    def test_cuts_snap_to_word_gaps_but_stay_in_range(self):
        gaps = [i * 0.37 for i in range(1, 80)]
        for d in (7.7, 10.4, 13.9, 17.2):
            c = strict_cuts(0.0, d, gaps)
            durs = [b - a for a, b in zip(c, c[1:])]
            self.assertTrue(all(STRICT_MIN - 1e-6 <= x <= STRICT_MAX + 1e-6 for x in durs), (d, durs))

    def test_full_video_in_range(self):
        rng = random.Random(7)
        scenes, t, k = [], 0.0, 0
        while t < 571:
            scenes.append({"id": k + 1, "start": round(t, 3)})
            t += rng.uniform(6.5, 19)
            k += 1
        words = [{"w": "x", "s": i / 2.2, "e": i / 2.2 + 0.3} for i in range(int(571 * 2.2))]
        shots = plan_shots(scenes, words, 573.3, strict=True)
        durs = [s["dur"] for s in shots]
        self.assertGreaterEqual(min(durs), 2.5)
        self.assertLessEqual(max(durs), 4.6)
        self.assertAlmostEqual(sum(durs), 573.3, delta=0.05)
        self.assertTrue(all(abs(a["end"] - b["start"]) < 0.01 for a, b in zip(shots, shots[1:])))


class TestConcept(unittest.TestCase):
    def test_keeps_concept_on_rerun_and_is_deterministic(self):
        reg = {"videos": {"Video_003": {"concept": "muted_film"}, "Video_001": {"concept": "warm_cinematic"}}}
        self.assertEqual(s6_animation.choose_concept(reg, "Video_003"), "muted_film")
        a = s6_animation.choose_concept({"videos": {}}, "Video_009")
        out = subprocess.run(["python3", "-c", "from pipeline.stages.s6_animation import choose_concept as c;"
                              "print(c({'videos':{}}, 'Video_009'))"], capture_output=True, text=True,
                             env=dict(os.environ, PYTHONHASHSEED="12345")).stdout.strip()
        self.assertEqual(a, out)                     # процесс/hash seed алмашса да бирдей


class FakeGem:
    def __init__(self, scores, fail=False):
        self.scores, self.fail, self.calls = scores, fail, 0

    def rate_frames(self, items):
        self.calls += 1
        if self.fail:
            raise RuntimeError("quota")
        return [self.scores.pop(0) for _ in items]


def asset(i):
    return Asset("pixabay", "video", f"pixabay:{i}", "u", 1920, 1080, 10.0, "", "a", *PIXABAY_LICENSE)


class TestAIRelevance(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name)
        self.clip = self.d / "c.mp4"
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=30:duration=8",
                        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(self.clip)], check=True)
        self.shots = [{"i": k, "scene": 1, "dur": 3.0} for k in range(3)]
        self.scenes = {1: {"text": "Страх мешает нам двигаться вперёд"}}
        self.results = [(k, asset(k), self.clip, 8.0, "fresh", 0.5) for k in range(3)]
        self.ctx = SimpleNamespace(log=lambda m: None, services={})

    def tearDown(self):
        self.tmp.cleanup()

    def run_stage(self, gem, replacements):
        self.ctx.services["gemini"] = gem
        chosen = {k: (asset(k), "fresh", 0.5) for k in range(3)}
        finder = mock.Mock()
        finder.replacement.side_effect = lambda pool, dur: replacements.pop(0) if replacements else None
        new = {}

        def fetch(i):
            a = chosen[i][0]
            return (i, a, self.clip, 8.0, "fresh", 0.0)
        return VisualsStage().ai_relevance(self.ctx, self.results, self.shots, self.scenes, chosen,
                                           {k: None for k in range(3)}, finder, fetch, lambda i: 0.5)

    def test_low_score_replaced_only_if_better(self):
        # 1-чакыруу: [5, 1, 2]; алмаштыруулар: 2 жаңы клип; 2-чакыруу: жаңылар [4, 1]
        gem = FakeGem([5, 1, 2, 4, 1])
        out, st = self.run_stage(gem, [asset(100), asset(101)])
        self.assertEqual(st["low"], 2)
        self.assertEqual(st["replaced"], 1)                    # 1→4 жакшырды; 2→1 начарлады, эскиси калат
        self.assertEqual(st["scores"][1], 4)
        self.assertEqual(st["scores"][2], 2)
        self.assertEqual(len(out), 3)

    def run_rounds(self, first_scores, retry_score, rounds=3):
        class Gem:
            calls = 0

            def rate_frames(self, items):
                Gem.calls += 1
                return list(first_scores) if Gem.calls == 1 else [retry_score] * len(items)
        stage = VisualsStage()
        stage.rounds = rounds
        self.ctx.services["gemini"] = Gem()
        chosen = {k: (asset(k), "fresh", 0.5) for k in range(3)}
        finder = mock.Mock()
        finder.beat_candidate.return_value = None
        finder.replacement.side_effect = lambda pool, dur: asset(200 + Gem.calls)
        fetch = lambda i: (i, chosen[i][0], self.clip, 8.0, "fresh", 0.0)
        with mock.patch.object(VisualsStage, "visual_beats", return_value={}):
            stage.ai_relevance(self.ctx, self.results, self.shots, self.scenes, chosen,
                               {k: None for k in range(3)}, finder, fetch, lambda i: 0.5)
        return Gem.calls

    def test_extra_rounds_while_average_below_target(self):
        # run #45987020953: 3 айлампадан кийин орточо 2.97 → MAX_ROUNDS'ка чейин улантылат
        self.assertEqual(self.run_rounds([5, 1, 1], 2), 1 + VisualsStage.MAX_ROUNDS)

    def test_no_extra_rounds_when_average_reached(self):
        self.assertEqual(self.run_rounds([5, 5, 2], 2), 1 + 3)

    def test_first_shot_pushed_to_five(self):
        # биринчи кадр 4/5 (QA'дан өтөт, бирок кайра баалоодо 3 болушу мүмкүн) → 5'ке жакшыртылып көрүлөт
        self.assertGreater(self.run_rounds([4, 5, 5], 5, rounds=1), 1)

    def test_carry_best_restores_better_previous_clip(self):
        # Video_006: rerun нөлдөн тандап, жакшы клиптер жоголгон → мурункусу жакшыраак болсо кайтарылат
        import json as _json
        ctx = SimpleNamespace(log=lambda m: None, path=lambda *p: self.d.joinpath(*p))
        (self.d / "clips").mkdir()
        old = [{"i": k, "scene": 1, "dur": 3.0, "kind": "video", "source": "pixabay", "asset": f"pixabay:{900 + k}",
                "file": f"old{k}.mp4", "url": "u", "ai_score": sc, "real_duration": 8.0}
               for k, sc in enumerate([4, 2, 5])]
        (self.d / "clips" / "shots.json").write_text(_json.dumps({"total": 9, "shots": old}))
        (self.d / "clips" / "licenses.json").write_text(_json.dumps(
            [{"shot": k, "author": "a", "license": "Pixabay", "license_url": "l"} for k in range(3)]))
        prev = VisualsStage.previous_best(ctx, self.shots)
        self.assertEqual(sorted(prev), [0, 1, 2])
        stock = mock.Mock()
        stock.download.side_effect = lambda a, path: path.write_bytes(self.clip.read_bytes())
        st = {"scores": {0: 3, 1: 3, 2: 5}, "avg": 11 / 3}
        out, kept = VisualsStage().carry_best(ctx, list(self.results), self.shots, st, prev, stock)
        self.assertEqual(kept, 1)                               # 0-кадр: 4 > 3; 1-кадр: 2 < 3; 2-кадр: тең
        self.assertEqual(out[0][1].id, "pixabay:900")
        self.assertEqual(out[1][1].id, "pixabay:1")
        self.assertEqual(st["scores"][0], 4)
        self.assertAlmostEqual(st["avg"], 4.0)

    def test_previous_best_ignores_changed_plan(self):
        import json as _json
        ctx = SimpleNamespace(path=lambda *p: self.d.joinpath(*p))
        (self.d / "clips").mkdir()
        old = [{"scene": 2, "dur": 3.0, "kind": "video", "asset": "pixabay:1", "file": "f", "ai_score": 5}]
        (self.d / "clips" / "shots.json").write_text(_json.dumps({"shots": old}))
        (self.d / "clips" / "licenses.json").write_text(_json.dumps([{"shot": 0}]))
        self.assertEqual(VisualsStage.previous_best(ctx, self.shots), {})

    def test_quota_failure_does_not_break(self):
        with mock.patch("time.sleep"):
            out, st = self.run_stage(FakeGem([], fail=True), [asset(100)])
        self.assertEqual(st["rated"], 0)
        self.assertEqual(st["replaced"], 0)
        self.assertEqual(len(out), 3)                          # кадрлар өзгөрүүсүз

    def test_rating_retries_after_outage_and_finishes(self):
        """503 толкуну: 1-аракетте баары жыгылат, 2-аракетте Gemini оңолот → кадрлар бааланат."""
        class Flaky:
            calls = 0

            def rate_frames(self, items):
                Flaky.calls += 1
                if Flaky.calls <= 1:                       # 1-аракет жыгылат, 2-аракетте Gemini оңолот
                    raise RuntimeError("503")
                return [4] * len(items)
        with mock.patch("time.sleep") as sl:
            out, st = self.run_stage(Flaky(), [])
        self.assertEqual(st["rated"], 3)
        sl.assert_called_once_with(VisualsStage.RATE_WAIT)

    def test_rating_gives_up_after_all_passes(self):
        with mock.patch("time.sleep") as sl:
            out, st = self.run_stage(FakeGem([], fail=True), [])
        self.assertEqual(st["rated"], 0)
        self.assertEqual(sl.call_count, VisualsStage.RATE_PASSES - 1)
        self.assertEqual(len(out), 3)

    def test_no_replacement_available(self):
        out, st = self.run_stage(FakeGem([1, 1, 1]), [])
        self.assertEqual((st["low"], st["replaced"]), (3, 0))


class TestUniformity(unittest.TestCase):
    def frames(self, ys):
        return [(i * 20.0, {"y": y, "sat": 0.3, "sharp": 50.0}) for i, y in enumerate(ys)]

    def test_flags_odd_minute(self):
        fr = self.frames([100] * 9 + [150] * 3 + [100] * 9)        # 2-мүнөт (индекс 3..5: 60-120 сек) — ошол жерде 150?
        fr = [(t, dict(d, y=160 if 60 <= t < 120 else 100)) for t, d in fr]
        words = [{"s": i * 0.5} for i in range(int(420 / 0.5))]   # 120 сөз/мүн
        loud = [(float(t), -16.0) for t in range(0, 420)]
        rows = uniformity.build_table(fr, loud, words, 420.0)
        self.assertEqual(len(rows), 7)
        self.assertTrue(rows[1]["flags"] and "жарык" in rows[1]["flags"][0])
        self.assertEqual([r["minute"] for r in rows if r["flags"]], [2])
        ok, note = uniformity.summary(rows)
        self.assertFalse(ok)
        self.assertIn("2-мүнөт", note)

    def test_all_good(self):
        fr = self.frames([100] * 21)
        words = [{"s": i * 0.5} for i in range(int(420 / 0.5))]
        rows = uniformity.build_table(fr, [(float(t), -16.0) for t in range(420)], words, 420.0)
        self.assertTrue(uniformity.summary(rows)[0])

    def test_slow_voice_and_loudness_flagged(self):
        fr = self.frames([100] * 21)
        words = [{"s": i * 1.5} for i in range(int(420 / 1.5))]    # 40 сөз/мүн
        loud = [(float(t), -16.0 if t < 200 else -9.0) for t in range(420)]
        rows = uniformity.build_table(fr, loud, words, 420.0)
        text = " ".join(" ".join(r["flags"]) for r in rows)
        self.assertIn("темп", text)
        self.assertIn("катуулук", text)

    def test_real_video_analysis(self):
        with tempfile.TemporaryDirectory() as d:
            v = Path(d) / "v.mp4"
            subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=30:duration=85",
                            "-f", "lavfi", "-i", "sine=f=300:d=85,volume=0.2", "-c:v", "libx264", "-preset", "ultrafast",
                            "-pix_fmt", "yuv420p", "-c:a", "aac", str(v)], check=True)
            rows = uniformity.analyze(v, 85.0, [{"s": i * 0.5} for i in range(170)])
            self.assertEqual(len(rows), 2)
            self.assertIsNotNone(rows[0]["brightness"])
            self.assertIsNotNone(rows[0]["loudness"])
            self.assertIsNotNone(rows[0]["sharpness"])


if __name__ == "__main__":
    unittest.main()


class TestVisualBeats(TestAIRelevance):
    """2026-11-20: начар кадр үчүн ОШОЛ сөздүн маанисин көрсөткөн өзүнчө идея + издөө; шаблон/монетизация эрежелери."""

    def test_beat_query_used_and_rated_on_shot_words(self):
        import json as _json

        (self.d / "subtitles").mkdir()
        (self.d / "subtitles" / "timings.json").write_text(_json.dumps({"words": [
            {"w": "Страх", "s": 0.2, "e": 0.6}, {"w": "мешает", "s": 3.2, "e": 3.6}, {"w": "двигаться", "s": 6.5, "e": 6.9}]}))
        for k, sh in enumerate(self.shots):
            sh.update(start=3.0 * k, end=3.0 * (k + 1))
        self.ctx.path = lambda *p: self.d.joinpath(*p)
        seen_texts, prompts = [], []

        class Gem(FakeGem):
            def rate_frames(self, items):
                seen_texts.extend(t for _, t in items)
                return super().rate_frames(items)

            def json(self, prompt, **kw):
                prompts.append(prompt)
                return [{"i": 1, "idea": "a person freezing at a doorway", "queries": ["man hesitating doorway", "x"]},
                        {"i": 2, "idea": "dup", "queries": ["man hesitating doorway"]}]   # кайталанган идея — алынбайт

        gem = Gem([5, 1, 2, 4])
        self.ctx.services["gemini"] = gem
        chosen = {k: (asset(k), "fresh", 0.5) for k in range(3)}
        finder = mock.Mock()
        finder.beat_candidate.side_effect = lambda q, dur: asset(200) if q == "man hesitating doorway" else None
        finder.replacement.return_value = None

        def fetch(i):
            return (i, chosen[i][0], self.clip, 8.0, "fresh", 0.0)

        out, st = VisualsStage().ai_relevance(self.ctx, self.results, self.shots, self.scenes, chosen,
                                              {k: None for k in range(3)}, finder, fetch, lambda i: 0.5)
        self.assertTrue(seen_texts[1].startswith("«мешает»"))              # кадрдын өз сөзү боюнча бааланат
        self.assertIn("NO cartoons", prompts[0])                           # эрежелер prompt'то
        self.assertIn("chess pieces", prompts[0])                          # шаблон кадрлардын тизмеси
        self.assertEqual(st["beats"], {"1": "a person freezing at a doorway"})
        self.assertEqual(st["beats_won"], 1)
        self.assertEqual(out[1][1].id, "pixabay:200")
