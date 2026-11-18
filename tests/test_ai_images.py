"""AI-сүрөттөр (Gemini, СЫНАК): бюджет, кэш, кайталанбоо, ката → сток, s5'ке туташуу. Жалган API менен."""

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from pipeline import ai_images as ai
from pipeline.errors import QuotaExhausted
from pipeline.gemini import Gemini
from pipeline.stages.s5_visuals import PACE, VisualsStage, plan_shots, scene_targets, strict_cuts
from pipeline.stock import PIXABAY_LICENSE, Asset
from pipeline.storage import LocalStore


def png_bytes(d: Path, color="red") -> bytes:
    p = d / f"src_{color}.png"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"color=c={color}:s=1344x768",
                    "-frames:v", "1", str(p)], check=True)
    return p.read_bytes()


class FakeModels:
    def __init__(self, data: bytes, fail: Exception | None = None):
        self.data, self.fail, self.calls = data, fail, 0

    def generate_content(self, model, contents, config=None):
        self.calls += 1
        if self.fail:
            raise self.fail
        part = SimpleNamespace(inline_data=SimpleNamespace(data=self.data, mime_type="image/png"))
        return SimpleNamespace(candidates=[SimpleNamespace(content=SimpleNamespace(parts=[part]))])


class FakeGem:
    """Gemini'дин ЧЫНЫГЫ _call логикасы + жалган client."""

    def __init__(self, data: bytes, fail=None, scores=None):
        self.models = FakeModels(data, fail)
        self.g = Gemini("x", text_models=["t"], tts_models=["s"], log=lambda m: None, sleep=lambda s: None,
                        client=SimpleNamespace(models=self.models))
        self.client = self.g.client
        self.usage = []
        self.slept = []
        self.sleep = self.slept.append
        self.scores = scores
        self.prompts = 0

    def _call(self, *a, **k):
        return self.g._call(*a, **k)

    def json(self, prompt, **k):
        self.prompts += 1
        import re
        return [{"i": int(i), "prompt": f"a lone figure walking toward light, number {i}"}
                for i in re.findall(r"Item (\d+):", prompt)]

    def rate_frames(self, items):
        return [self.scores.pop(0) if self.scores else 4 for _ in items]


class TestBudgetAndSlots(unittest.TestCase):
    def test_budget_limits_count_and_money(self):
        b = ai.Budget(max_images=3, max_usd=0.08)
        self.assertTrue(b.can("gemini-2.5-flash-image"))
        b.add("gemini-2.5-flash-image")
        b.add("gemini-2.5-flash-image")
        self.assertAlmostEqual(b.spent, 0.078)
        self.assertFalse(b.can("gemini-2.5-flash-image"))     # 3-сүрөт $0.117 > $0.08
        self.assertEqual(ai.price("unknown-model"), ai.UNKNOWN_PRICE)

    def test_budget_from_env(self):
        with mock.patch.dict(os.environ, {"YTA_AI_IMAGE_MAX": "5", "YTA_AI_IMAGE_BUDGET": "0.2"}):
            b = ai.Budget.from_env()
        self.assertEqual((b.max_images, b.max_usd), (5, 0.2))

    def test_slots_priority_no_adjacent_max_two_per_scene(self):
        shots = [{"i": k, "scene": k // 4} for k in range(12)]
        scores = {k: 4 for k in range(12)}
        scores.update({1: 1, 2: 1, 5: 2, 6: 2, 8: 3, 4: 3})
        slots = ai.select_slots(shots, scores, limit=10)
        self.assertTrue(all(b - a > 1 for a, b in zip(slots, slots[1:])))   # катар эмес
        self.assertIn(1, slots)
        self.assertIn(5, slots)
        self.assertNotIn(4, slots)        # 5'ке кошуна
        self.assertIn(8, slots)           # сахнанын биринчиси, баа 3
        self.assertNotIn(3, slots)        # баа 4 — сток жакшы
        self.assertEqual(ai.select_slots(shots, scores, limit=0), [])
        self.assertEqual(len(ai.select_slots(shots, scores, limit=1)), 1)

    def test_style_differs_from_previous_video_and_is_stable(self):
        reg = {"videos": {"Video_001": {"ai_style": ai.STYLES[0]}}}
        s = ai.pick_style("Video_002", reg)
        self.assertIn(s, ai.STYLES)
        self.assertEqual(s, ai.pick_style("Video_002", reg))
        for vid in ("Video_002", "Video_003", "Video_007"):
            self.assertNotEqual(ai.pick_style(vid, reg), ai.STYLES[0])
        reg["videos"]["Video_002"] = {"ai_style": ai.STYLES[3]}
        self.assertEqual(ai.pick_style("Video_002", reg), ai.STYLES[3])    # кайра иштетүүдө өзгөрбөйт

    def test_not_enabled_in_production(self):
        with mock.patch.dict(os.environ, {"YTA_AI_IMAGES": "1", "YTA_CINEMATIC": "1"}):
            prod = SimpleNamespace(root_name="YouTube_Auto")
            self.assertFalse(ai.enabled(prod))
            self.assertTrue(ai.enabled(SimpleNamespace(root_name="YouTube_Auto_TEST")))
        with mock.patch.dict(os.environ, {"YTA_AI_IMAGES": "", "YTA_CINEMATIC": "1"}):
            self.assertFalse(ai.enabled(SimpleNamespace(root_name="YouTube_Auto_TEST")))


class TestProduce(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name)
        self.store = LocalStore(self.d / "drive")
        self.work = self.d / "work"
        self.work.mkdir()
        self.data = png_bytes(self.d)

    def tearDown(self):
        self.tmp.cleanup()

    def test_generates_16x9_frame_and_caches_without_second_charge(self):
        gem = FakeGem(self.data)
        cache, budget = ai.Cache(self.store), ai.Budget()
        a, path = ai.produce(gem, cache, budget, "Video_009", "a mountain at dawn", self.work)
        out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=width,height", "-of", "csv=p=0",
                              str(path)], capture_output=True, text=True).stdout.strip()
        self.assertEqual(out, "1920,1080")
        self.assertEqual((a.source, a.kind, a.license), ("gemini", "image", ai.LICENSE))
        self.assertEqual(budget.generated, 1)
        cache.save(self.work)
        # кайра иштетүү: жаңы Cache (Drive'дан индекс) — сүрөт кайра жаратылбайт, акча кетпейт
        path.unlink()
        cache2, budget2 = ai.Cache(self.store), ai.Budget()
        a2, p2 = ai.produce(gem, cache2, budget2, "Video_009", "a mountain at dawn", self.work)
        self.assertEqual(gem.models.calls, 1)
        self.assertEqual((budget2.generated, budget2.cached, budget2.spent), (0, 1, 0.0))
        self.assertTrue(p2.exists())
        self.assertEqual(a2.id, a.id)

    def test_other_videos_image_is_not_reused(self):
        gem = FakeGem(self.data)
        cache = ai.Cache(self.store)
        a1, _ = ai.produce(gem, cache, ai.Budget(), "Video_001", "same prompt", self.work)
        a2, _ = ai.produce(gem, cache, ai.Budget(), "Video_002", "same prompt", self.work)
        self.assertNotEqual(a1.id, a2.id)
        self.assertEqual(gem.models.calls, 2)

    def test_quota_429_stops_and_keeps_stock(self):
        err = RuntimeError("429 RESOURCE_EXHAUSTED quota limit: 0 GenerateRequestsPerDayPerProjectPerModel")
        err.code = 429
        gem = FakeGem(self.data, fail=err)
        budget = ai.Budget()
        self.assertIsNone(ai.produce(gem, ai.Cache(self.store), budget, "V", "p", self.work, log=lambda m: None))
        self.assertTrue(budget.stopped)
        self.assertEqual(budget.spent, 0.0)
        self.assertFalse(budget.can("gemini-2.5-flash-image"))

    def test_minute_limit_waits_once_then_stops(self):
        err = RuntimeError("429 RESOURCE_EXHAUSTED please check your plan and billing details")
        err.code = 429
        gem = FakeGem(self.data, fail=err)
        budget = ai.Budget()
        self.assertIsNone(ai.produce(gem, ai.Cache(self.store), budget, "V", "p", self.work, log=lambda m: None))
        self.assertEqual(gem.models.calls, 2)            # 1 күтүү (≤60 сек) + 1 кайра, андан ары эмес
        self.assertTrue(all(s <= 62 for s in gem.slept))
        self.assertTrue(budget.stopped)

    def test_server_error_retries_then_succeeds(self):
        gem = FakeGem(self.data)
        calls = {"n": 0}
        real = gem.models.generate_content

        def flaky(*a, **k):
            calls["n"] += 1
            if calls["n"] == 1:
                e = RuntimeError("503 UNAVAILABLE")
                e.code = 503
                raise e
            return real(*a, **k)
        gem.models.generate_content = flaky
        budget = ai.Budget()
        self.assertIsNotNone(ai.produce(gem, ai.Cache(self.store), budget, "V", "p", self.work, log=lambda m: None))
        self.assertEqual(budget.generated, 1)
        self.assertEqual(gem.usage[-1]["purpose"], "ai_image")

    def test_budget_exhausted_returns_none_without_call(self):
        gem = FakeGem(self.data)
        budget = ai.Budget(max_usd=0.01)
        self.assertIsNone(ai.produce(gem, ai.Cache(self.store), budget, "V", "p", self.work))
        self.assertEqual(gem.models.calls, 0)
        self.assertIn("бюджет", budget.stopped)


def stock_asset(i):
    return Asset("pixabay", "video", f"pixabay:{i}", "u", 1920, 1080, 10.0, "", "a", *PIXABAY_LICENSE)


class TestStageIntegration(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name)
        (self.d / "proj" / "clips").mkdir(parents=True)
        self.clip = self.d / "c.mp4"
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=30:duration=6",
                        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(self.clip)], check=True)
        self.shots = [{"i": k, "scene": 1 + k // 3, "dur": 3.0} for k in range(6)]
        self.scenes = {1: {"text": "Страх мешает нам двигаться"}, 2: {"text": "Сделай первый шаг сегодня"}}
        self.results = [(k, stock_asset(k), self.clip, 6.0, "fresh", 0.5) for k in range(6)]
        self.store = LocalStore(self.d / "drive")
        self.data = png_bytes(self.d, "blue")

    def tearDown(self):
        self.tmp.cleanup()

    def ctx(self, gem):
        return SimpleNamespace(log=lambda m: None, services={"gemini": gem}, store=self.store, registry={},
                               video_id="Video_010", path=lambda *p: self.d.joinpath("proj", *p))

    def test_ai_image_replaces_only_bad_stock_and_is_rated(self):
        gem = FakeGem(self.data, scores=[5, 2])       # 1-кадр AI жакшы (5>1), 4-кадр AI начар (2 ≤ 2) → сток калат
        stats = {"scores": {0: 4, 1: 1, 2: 4, 3: 4, 4: 2, 5: 4}, "avg": 3.2}
        ctx = self.ctx(gem)
        with mock.patch.dict(os.environ, {"YTA_AI_IMAGE_MAX": "4"}):
            out, info = VisualsStage().add_ai_images(ctx, self.results, self.shots, self.scenes, stats)
        kinds = {r[0]: r[1].source for r in out}
        self.assertEqual(kinds[1], "gemini")
        self.assertEqual(kinds[4], "pixabay")
        self.assertEqual(len(out), 6)
        self.assertEqual(info["used"], 1)
        self.assertEqual(len(info["rejected"]), 1)
        self.assertAlmostEqual(info["cost_usd"], 0.078)
        saved = json.loads((self.d / "proj" / "clips" / "ai_images.json").read_text(encoding="utf-8"))
        self.assertEqual(saved["generated"], 2)
        self.assertIn("ai_style", ctx.registry["videos"]["Video_010"])
        self.assertTrue((self.store.root / ai.FOLDER / ai.INDEX).exists())

    def test_failure_keeps_all_stock(self):
        err = RuntimeError("429 RESOURCE_EXHAUSTED billing required PerDay")
        err.code = 429
        gem = FakeGem(self.data, fail=err)
        stats = {"scores": {0: 1, 1: 4, 2: 4, 3: 1, 4: 4, 5: 4}, "avg": 3.0}
        out, info = VisualsStage().add_ai_images(self.ctx(gem), self.results, self.shots, self.scenes, stats)
        self.assertTrue(all(r[1].source == "pixabay" for r in out))
        self.assertEqual(info["cost_usd"], 0.0)
        self.assertTrue(info["stopped"])


class TestScriptPacing(unittest.TestCase):
    def test_calm_scenes_get_longer_shots_than_tense(self):
        gaps = [x * 0.25 for x in range(200)]
        calm = strict_cuts(0.0, 24.0, gaps, PACE["calm"])
        tense = strict_cuts(0.0, 24.0, gaps, PACE["tense"])
        self.assertLess(len(calm), len(tense))
        for c in (calm, tense):
            self.assertTrue(all(2.8 - 1e-6 <= b - a <= 4.4 + 1e-6 for a, b in zip(c, c[1:])))

    def test_targets_from_emotion(self):
        t = scene_targets({1: {"emotion": "calm"}, 2: {"emotion": "tense"}, 3: {}})
        self.assertGreater(t[1], t[2])
        self.assertEqual(t[3], 3.6)
        words = [{"s": k * 0.4, "e": k * 0.4 + 0.3} for k in range(100)]
        sh = plan_shots([{"id": 1, "start": 0.0}, {"id": 2, "start": 20.0}], words, 40.0, strict=True, targets=t)
        n1 = sum(1 for s in sh if s["scene"] == 1)
        n2 = sum(1 for s in sh if s["scene"] == 2)
        self.assertLess(n1, n2)


class TestDollyOut(unittest.TestCase):
    def test_dolly_out_builds_and_is_planned(self):
        from pipeline import motion
        self.assertIn("dolly_out", motion.TYPES)
        f = motion.build("dolly_out", 3.0, 1.0, 7)
        self.assertIn("(1-", f.split("zoompan=z='")[1].split("'")[0])


if __name__ == "__main__":
    unittest.main()
