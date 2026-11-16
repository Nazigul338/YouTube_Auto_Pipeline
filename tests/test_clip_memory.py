"""Smart Video Memory & Anti-Repetition тесттери (тармаксыз, FFmpegсиз)."""

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from pipeline.clipmemory import ClipMemory, video_num
from pipeline.clipsearch import ClipFinder, Pool, detect_theme, expand_queries, relevance
from pipeline.errors import StageError
from pipeline.stages.s5_visuals import MAX_REUSE_FRACTION, plan_shots
from pipeline.stages.s9_qa import QAStage, Report
from pipeline.storage import LocalStore
from pipeline.stock import PIXABAY_LICENSE, Asset


def asset(i, dur=12.0, tags="", q="q"):
    return Asset("pixabay", "video", f"pixabay:{i}", f"https://x/{i}.mp4", 1920, 1080, dur,
                 f"https://pixabay.com/videos/id-{i}/", "a", *PIXABAY_LICENSE, tags=tags, query=q)


class PagedStock:
    """Ар суроо/бет үчүн өз ID диапазону; бет саны чектүү (Pixabay сыяктуу 400)."""

    def __init__(self, per_page=20, max_page=3, dur=12.0, same_for_all_queries=False):
        self.per_page, self.max_page, self.dur, self.same = per_page, max_page, dur, same_for_all_queries
        self.calls = []

    def videos(self, q, min_duration=3.0, page=1):
        self.calls.append((q, page))
        if page > self.max_page:
            raise StageError("Сток API: HTTP 400 — page out of range")
        base = (0 if self.same else abs(hash(q)) % 10**6 * 100) + (page - 1) * self.per_page
        return [asset(base + k, self.dur, tags=q, q=q) for k in range(self.per_page)]

    def images(self, q, page=1):
        return []


def scene(i=1, queries=("lonely road", "dark corridor"), text="Страх мешает нам двигаться вперёд"):
    return {"id": i, "text": text, "queries": list(queries), "visual": "a person stands before a door"}


class TestMemoryDB(unittest.TestCase):
    def shots(self, ids, **kw):
        return [{"asset": i, "page_url": f"https://pixabay.com/videos/id-{i}/", "kind": "video",
                 "source": "pixabay", "query": "road", "scene": 1, "theme": "fear", **kw} for i in ids]

    def test_reserve_records_all_required_fields(self):
        m = ClipMemory()
        m.reserve("Video_007", "Страх", self.shots(["pixabay:1", "pixabay:2"]), date="2026-11-16")
        r = m.clips["pixabay:1"]
        self.assertEqual(r["url"], "https://pixabay.com/videos/id-pixabay:1/")
        u = r["uses"][0]
        self.assertEqual((u["video"], u["date"], u["topic"]), ("Video_007", "2026-11-16", "Страх"))
        self.assertEqual(m.used_by_others("Video_008"), {"pixabay:1", "pixabay:2"})
        self.assertEqual(m.used_by_others("Video_007"), set())      # өзүн бөгөттөбөйт

    def test_rerun_releases_own_clips(self):
        m = ClipMemory()
        m.reserve("Video_001", "t", self.shots(["pixabay:1", "pixabay:2"]))
        m.reserve("Video_002", "t", self.shots(["pixabay:2"]))
        m.release("Video_001")
        self.assertNotIn("pixabay:1", m.clips)
        self.assertEqual(len(m.clips["pixabay:2"]["uses"]), 1)

    def test_import_registry_is_idempotent(self):
        reg = {"videos": {"Video_001": {"topic": "x", "created": "2026-11-10T10:00:00+00:00",
                                        "clip_ids": ["pixabay:5", "pixabay-img:6"]}}}
        m = ClipMemory()
        self.assertEqual(m.import_registry(reg), 2)
        self.assertEqual(m.import_registry(reg), 0)
        self.assertEqual(m.clips["pixabay:5"]["uses"][0]["date"], "2026-11-10")
        self.assertEqual(m.clips["pixabay-img:6"]["kind"], "image")

    def test_persists_across_restart_json_and_csv(self):
        with tempfile.TemporaryDirectory() as d:
            store = LocalStore(Path(d))
            store.ensure_layout()
            m = ClipMemory.load(store)
            m.reserve("Video_003", "Лень", self.shots(["pixabay:9"]))
            m.save(store, Path(d) / "w" / "clip_memory.csv")
            m2 = ClipMemory.load(LocalStore(Path(d)))          # «кайра иштетүү»
            self.assertEqual(m2.used_by_others("Video_004"), {"pixabay:9"})
            csv_text = (Path(d) / "YouTube_Auto" / "Clips" / "clip_memory.csv").read_text("utf-8")
            self.assertIn("pixabay_id,source,kind,page_url,video,date,topic", csv_text)
            self.assertIn("9,pixabay,video,", csv_text)
            self.assertIn("Video_003", csv_text)

    def test_top_queries_and_numbers(self):
        m = ClipMemory()
        m.reserve("Video_001", "t", self.shots(["pixabay:1", "pixabay:2"]))
        self.assertEqual(m.top_queries(1), ["road"])
        self.assertEqual(video_num("Video_012"), 12)


class TestAntiRepetition(unittest.TestCase):
    def finder(self, stock, mem=None, vid="Video_002"):
        return ClipFinder(stock, mem or ClipMemory(), vid, min_duration=3.0, log=lambda m: None)

    def test_fresh_pool_never_contains_used_clips(self):
        mem = ClipMemory()
        used = [asset(k) for k in range(20)]                  # бет 1 толугу менен колдонулган
        mem.reserve("Video_001", "t", [{"asset": a.id, "page_url": a.page_url, "kind": "video"}
                                       for a in used])
        stock = PagedStock(same_for_all_queries=True)
        f = self.finder(stock, mem)
        pool = f.pool_for(scene(), n_shots=4, need=3.6)
        ids = {c.asset.id for c in pool.fresh}
        self.assertTrue(ids)
        self.assertFalse(ids & {a.id for a in used})
        self.assertTrue(any(p > 1 for _, p in stock.calls))    # кийинки беттер изделди

    def test_expands_with_new_keywords_when_pool_thin(self):
        class Thin(PagedStock):
            def videos(self, q, min_duration=3.0, page=1):
                self.calls.append((q, page))
                if q in ("lonely road", "dark corridor", "a person stands before a") or page > 1:
                    return [asset(1), asset(2)] if page == 1 else []
                return super().videos(q, min_duration, page)
        stock = Thin()
        f = self.finder(stock)
        pool = f.pool_for(scene(), n_shots=5, need=3.6)
        self.assertGreaterEqual(len([c for c in pool.fresh if c.long]), 5)
        asked = {q for q, _ in stock.calls}
        self.assertTrue(asked - {"lonely road", "dark corridor", "a person stands before a"})  # жаңы сөздөр
        self.assertEqual(f.expanded_scenes, 1)

    def test_taken_clips_not_picked_twice(self):
        f = self.finder(PagedStock())
        sc = scene()
        pool = f.pool_for(sc, 6, 3.6)
        picked = [f.pick(sc, pool, 3.6, allow_stale=False)[0].id for _ in range(6)]
        self.assertEqual(len(set(picked)), 6)

    def test_reuse_only_as_last_resort_and_oldest_first(self):
        mem = ClipMemory()
        old, new = asset(1), asset(2)
        mem.reserve("Video_001", "t", [{"asset": old.id, "page_url": ""}])
        mem.reserve("Video_005", "t", [{"asset": new.id, "page_url": ""}])

        class Tiny(PagedStock):
            def videos(self, q, min_duration=3.0, page=1):
                return [old, new] if page == 1 else []
        f = self.finder(Tiny(), mem, "Video_010")
        sc = scene()
        pool = f.pool_for(sc, 1, 3.6)
        self.assertEqual(pool.fresh, [])
        with self.assertRaises(StageError):                    # reuse тыюу салынса — ката, унчукпайт
            f.pick(sc, pool, 3.6, allow_stale=False)
        a, tier, _ = f.pick(sc, pool, 3.6, allow_stale=True)
        self.assertEqual((a.id, tier), (old.id, "reused"))     # эң эскиси биринчи

    def test_short_clip_still_usable_as_extendable(self):
        f = self.finder(PagedStock(dur=3.2))
        sc = scene()
        pool = f.pool_for(sc, 2, 3.6)
        a, tier, _ = f.pick(sc, pool, 3.6, allow_stale=False)
        self.assertEqual(tier, "short")                        # узартылат (s8: stream_loop)

    def test_search_budget_respected(self):
        stock = PagedStock()
        f = ClipFinder(stock, ClipMemory(), "Video_002", 3.0, budget=5)
        f.pool_for(scene(), 8, 3.6)
        self.assertLessEqual(len(stock.calls), 5)

    def test_relevance_prefers_matching_tags(self):
        sc = scene()
        good = asset(1, tags="road, lonely, nature", q="lonely road")
        bad = asset(2, tags="cat, kitten", q="lonely road")
        self.assertGreater(relevance(good, sc), relevance(bad, sc))

    def test_two_consecutive_videos_share_no_clips(self):
        mem = ClipMemory()
        stock = PagedStock(same_for_all_queries=True, per_page=30, max_page=3)
        chosen = {}
        for vid in ("Video_001", "Video_002"):
            f = ClipFinder(stock, mem, vid, 3.0, log=lambda m: None)
            ids = []
            for sid in range(1, 4):
                sc = scene(sid)
                pool = f.pool_for(sc, 3, 3.6)
                ids += [f.pick(sc, pool, 3.6, allow_stale=False)[0].id for _ in range(3)]
            mem.reserve(vid, "t", [{"asset": i, "page_url": ""} for i in ids])
            chosen[vid] = set(ids)
            self.assertEqual(len(ids), len(set(ids)))
        self.assertFalse(chosen["Video_001"] & chosen["Video_002"])


class TestSmartSearch(unittest.TestCase):
    def test_theme_detection_distinguishes_topics(self):
        self.assertEqual(detect_theme("Страх неудачи парализует, мы боимся риска и паники"), "fear")
        self.assertEqual(detect_theme("Лень и прокрастинация: мы откладываем дела на диване"), "laziness")
        self.assertEqual(detect_theme("Привычки и дисциплина: режим и рутина каждый день"), "discipline")
        self.assertEqual(detect_theme("ok"), "general")

    def test_expand_queries_differ_per_theme_and_skip_tried(self):
        fear = expand_queries({"text": "Страх", "queries": ["a b"], "visual": ""}, set())
        lazy = expand_queries({"text": "Лень и диван", "queries": ["a b"], "visual": ""}, set())
        self.assertNotEqual(fear[:3], lazy[:3])
        again = expand_queries({"text": "Страх", "queries": ["a b"], "visual": ""}, {q.lower() for q in fear[:2]})
        self.assertFalse({q.lower() for q in again} & {q.lower() for q in fear[:2]})


class TestShotPlan(unittest.TestCase):
    def plan(self, speech_sec):
        lens = [8, 16, 11, 13, 9, 15, 12, 14, 10, 12]      # ар түрдүү сахна узактыктары
        scenes, t, k = [], 0.0, 0
        while t < speech_sec:
            L = min(lens[k % len(lens)], speech_sec - t)
            scenes.append({"id": k + 1, "start": round(t, 3), "end": round(t + L, 3)})
            t += L
            k += 1
        words = [{"w": "x", "s": i / 2.2, "e": i / 2.2 + 0.3} for i in range(int(speech_sec * 2.2))]
        return plan_shots(scenes, words, speech_sec + 1.5), speech_sec + 1.5

    def test_8min_video_has_120_to_160_shots_3_to_4_sec(self):
        shots, total = self.plan(480)
        durs = [s["dur"] for s in shots]
        self.assertTrue(120 <= len(shots) <= 160, len(shots))
        self.assertTrue(3.0 <= sum(durs) / len(durs) <= 4.0, sum(durs) / len(durs))
        self.assertLessEqual(max(durs), 5.0)
        self.assertGreaterEqual(min(durs), 2.0)
        self.assertAlmostEqual(sum(durs), total, delta=0.05)
        self.assertEqual(shots[0]["start"], 0.0)
        for a, b in zip(shots, shots[1:]):                 # боштуксуз, кайталанбайт
            self.assertAlmostEqual(a["end"], b["start"], delta=0.01)

    def test_9_5_min_video_keeps_pace(self):
        shots, total = self.plan(571)
        avg = sum(s["dur"] for s in shots) / len(shots)
        self.assertTrue(3.0 <= avg <= 4.0, avg)


class TestQARepetition(unittest.TestCase):
    def ctx(self, mem_videos):
        with tempfile.TemporaryDirectory() as d:
            pass
        d = tempfile.mkdtemp()
        store = LocalStore(Path(d))
        store.ensure_layout()
        mem = ClipMemory()
        for vid, ids in mem_videos.items():
            mem.reserve(vid, "t", [{"asset": i, "page_url": ""} for i in ids])
        mem.save(store)
        return SimpleNamespace(store=store, registry={"videos": {}}, video_id="Video_002")

    def shots(self, ids):
        return [{"asset": i, "kind": "video", "match": 0.5} for i in ids]

    def run_qa(self, ctx, ids):
        rep = Report()
        QAStage().check_repetition(ctx, rep, self.shots(ids))
        return {i["key"]: i["ok"] for i in rep.items}

    def test_clean_video_passes(self):
        ids = [f"pixabay:{k}" for k in range(100, 140)]
        ctx = self.ctx({"Video_001": [f"pixabay:{k}" for k in range(40)], "Video_002": ids})
        r = self.run_qa(ctx, ids)
        self.assertTrue(r["unique"] and r["no_reuse"] and r["memory"])

    def test_duplicate_inside_video_fails(self):
        ids = [f"pixabay:{k}" for k in range(100, 120)] + ["pixabay:100"]
        ctx = self.ctx({"Video_002": ids})
        self.assertFalse(self.run_qa(ctx, ids)["unique"])

    def test_heavy_reuse_of_old_clips_fails(self):
        old = [f"pixabay:{k}" for k in range(40)]
        ids = old[:10] + [f"pixabay:{k}" for k in range(100, 130)]       # 10/40 = 25% > 5%
        ctx = self.ctx({"Video_001": old, "Video_002": ids})
        self.assertFalse(self.run_qa(ctx, ids)["no_reuse"])

    def test_small_reuse_within_limit_passes(self):
        old = [f"pixabay:{k}" for k in range(40)]
        ids = old[:2] + [f"pixabay:{k}" for k in range(100, 138)]        # 2/40 = 5%
        ctx = self.ctx({"Video_001": old, "Video_002": ids})
        self.assertTrue(self.run_qa(ctx, ids)["no_reuse"])

    def test_clips_missing_in_memory_fail(self):
        ids = [f"pixabay:{k}" for k in range(100, 120)]
        ctx = self.ctx({})
        self.assertFalse(self.run_qa(ctx, ids)["memory"])


if __name__ == "__main__":
    unittest.main()
