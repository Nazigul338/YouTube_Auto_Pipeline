import json
import os
import shutil
import subprocess
import tempfile
import unittest

from poultry_ig_agent import lint, niche, pexels, safety, video
from poultry_ig_agent.tests.helpers import shots

HAVE = shutil.which("ffmpeg")


def vid(i, h=1920, w=1080, dur=15):
    return {"id": i, "duration": dur, "url": f"https://www.pexels.com/video/baby-chicken-{i}/", "user": {"name": f"Author{i}", "url": "u"},
            "video_files": [{"file_type": "video/mp4", "width": w, "height": h, "link": f"https://videos.pexels.com/{i}.mp4"},
                            {"file_type": "video/mp4", "width": w * 2, "height": h * 2, "link": "big"}]}


class Pexels(unittest.TestCase):
    def test_poultry_query_short_and_anchored(self):
        self.assertEqual(pexels.poultry_query("Close-up of fluffy chicks running in a warm brooder"), "baby chicken")
        self.assertEqual(pexels.poultry_query("Chicks drinking water from the dispenser"), "baby chicken drinking")
        self.assertEqual(pexels.poultry_query("A farmer smiling at the camera"), "baby chicken farmer")
        self.assertEqual(pexels.poultry_query("Farmer adjusting ventilation in the coop"), "chicken coop farmer")

    def test_relevance_rules(self):
        self.assertTrue(pexels.relevant("chick, chicken, farm"))
        self.assertTrue(pexels.relevant("hens, rooster"))
        self.assertFalse(pexels.relevant("chick, duckling, water"))      # өрдөк балапаны
        self.assertFalse(pexels.relevant("goose, chicks, lake"))
        self.assertFalse(pexels.relevant("chick, bird, nest"))           # 'chick' жалгыз жетишсиз
        self.assertTrue(pexels.relevant("https://www.pexels.com/video/baby-chicken-in-a-box-123/"))

    def test_irrelevant_rejected(self):
        from poultry_ig_agent import pixabay
        rose = {**hit(1), "tags": "rose, flower, red"}
        st = pixabay.PixabayStock("K", transport=lambda u: {"hits": [rose]}, downloader=lambda u, p: None)
        with self.assertRaises(pexels.StockError):
            st.fetch("chicks", 4, "/tmp/x.mp4")

    def test_series_exclude(self):
        from poultry_ig_agent import pixabay
        os.environ["POULTRY_STOCK_EXCLUDE"] = "1, 2"
        try:
            st = pixabay.PixabayStock("K", transport=lambda u: {"hits": [hit(1), hit(2), hit(3)]}, downloader=lambda u, p: open(p, "wb").close())
            _, lic = st.fetch("chicks", 4, os.path.join(tempfile.mkdtemp(), "a.mp4"))
            self.assertEqual(lic["id"], 3)
        finally:
            os.environ.pop("POULTRY_STOCK_EXCLUDE")

    def test_pick_file_vertical_not_4k(self):
        self.assertEqual(pexels.pick_file(vid(1))["link"], "https://videos.pexels.com/1.mp4")
        self.assertIsNone(pexels.pick_file({"video_files": [{"file_type": "video/mp4", "width": 640, "height": 360, "link": "x"}]}))

    def test_no_key(self):
        os.environ.pop("POULTRY_PEXELS_API_KEY", None)
        with self.assertRaises(pexels.StockError):
            pexels.PexelsStock()

    def test_no_duplicates_and_fallback_query(self):
        seen = []

        def tx(url):
            seen.append(url)
            return {"videos": [vid(7)]} if "query=baby+chicken&" in url else {"videos": []}
        st = pexels.PexelsStock("K", transport=tx, downloader=lambda u, p: open(p, "wb").close())
        d = tempfile.mkdtemp()
        _, lic = st.fetch("fluffy chicks", 4, os.path.join(d, "a.mp4"))
        self.assertEqual(lic["id"], 7); self.assertEqual(lic["source"], "Pexels")
        with self.assertRaises(pexels.StockError):        # 7 мурун колдонулду → кайталанбайт
            st.fetch("fluffy chicks", 4, os.path.join(d, "b.mp4"))
        self.assertTrue(any("baby+chicken" in u for u in seen))


class Durations(unittest.TestCase):
    def test_proportional_not_last_only(self):
        sh = [{"n": i, "duration": 5} for i in range(1, 7)]   # 30с план
        video.fit_durations(sh, 44.3)
        self.assertAlmostEqual(sum(s["duration"] for s in sh), 44.8, delta=0.05)
        self.assertLess(max(s["duration"] for s in sh) - min(s["duration"] for s in sh), 0.5)

    def test_short_voice_untouched(self):
        sh = [{"n": 1, "duration": 5}, {"n": 2, "duration": 5}]
        video.fit_durations(sh, 6)
        self.assertEqual([s["duration"] for s in sh], [5, 5])


class Disclosure(unittest.TestCase):
    def test_stock_note_added_and_not_linted(self):
        p = {"lang": "ky", "caption": "Таң", "topic_key": "daily", "shots": [{"source": "stock"}]}
        safety.ensure_disclaimers(p, niche.get("poultry"))
        self.assertIn("стоктук видео", p["caption"])
        self.assertFalse([i for i in lint.lint_post({**p, "format": "story", "hook": "h", "frames": [{"text": "x"}]}) if "Тыюу" in i])


@unittest.skipUnless(HAVE, "ffmpeg жок")
class BuildWithStock(unittest.TestCase):
    def _dl(self, url, path):
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc=s=720x1280:d=10:r=24", "-pix_fmt", "yuv420p", path], check=True)

    def test_build(self):
        from poultry_ig_agent.tests.test_video import FakeTTS, FakeVeo, probe
        st = pexels.PexelsStock("K", transport=lambda u: {"videos": [vid(n) for n in range(1, 9)]}, downloader=self._dl)
        assets = tempfile.mkdtemp(); os.makedirs(os.path.join(assets, "real"))
        out = tempfile.mkdtemp(); veo = FakeVeo()
        post = {"lang": "ky", "content_type": "education", "voiceover": "Таң атты", "shots": shots(4, "real")}
        r = video.build(post, out, veo, FakeTTS(), assets, stock=st)
        self.assertEqual(r["status"], "ready", r)
        self.assertEqual(r["stock_shots"], 4); self.assertEqual(veo.prompts, [])      # Veo чакырылган жок
        self.assertEqual(len(json.load(open(os.path.join(out, "licenses.json")))), 4)
        v = [s for s in probe(os.path.join(out, "final.mp4")) if s["codec_type"] == "video"][0]
        self.assertEqual((v["width"], v["height"]), (1080, 1920))

    def test_real_farm_never_stock(self):
        st = pexels.PexelsStock("K", transport=lambda u: {"videos": [vid(1)]}, downloader=self._dl)
        assets = tempfile.mkdtemp(); os.makedirs(os.path.join(assets, "real"))
        from poultry_ig_agent.tests.test_video import FakeTTS, FakeVeo
        r = video.build({"lang": "ky", "content_type": "real_farm", "voiceover": "x", "shots": shots(2)}, tempfile.mkdtemp(), FakeVeo(), FakeTTS(), assets, stock=st)
        self.assertEqual(r["status"], "needs_footage")


if __name__ == "__main__":
    unittest.main()


def hit(i, h=1080, dur=20):
    return {"id": i, "duration": dur, "pageURL": f"https://pixabay.com/videos/x-{i}/", "user": f"user{i}", "tags": "chicks, chicken, farm",
            "videos": {"large": {"url": f"https://cdn.pixabay.com/{i}_l.mp4", "width": 1920, "height": h},
                       "medium": {"url": f"https://cdn.pixabay.com/{i}_m.mp4", "width": 1280, "height": 720},
                       "tiny": {"url": "t", "width": 640, "height": 360}}}


class Pixabay(unittest.TestCase):
    def setUp(self):
        for k in ("POULTRY_PIXABAY_API_KEY", "POULTRY_PEXELS_API_KEY"):
            os.environ.pop(k, None)

    def test_pick_smallest_hd(self):
        from poultry_ig_agent import pixabay
        self.assertTrue(pixabay.pick_file(hit(1))["url"].endswith("_m.mp4"))

    def test_fetch_and_license_no_dup(self):
        from poultry_ig_agent import pixabay
        urls = []
        st = pixabay.PixabayStock("SECRET", transport=lambda u: urls.append(u) or {"hits": [hit(5)]},
                                  downloader=lambda u, p: open(p, "wb").close())
        d = tempfile.mkdtemp()
        _, lic = st.fetch("chicks drinking water", 5, os.path.join(d, "a.mp4"))
        self.assertEqual((lic["source"], lic["id"]), ("Pixabay", 5))
        self.assertIn("video_type=film", urls[0]); self.assertIn("safesearch=true", urls[0])
        with self.assertRaises(pexels.StockError):
            st.fetch("chicks drinking water", 5, os.path.join(d, "b.mp4"))

    def test_make_stock_prefers_pixabay(self):
        from poultry_ig_agent import pixabay
        with self.assertRaises(pexels.StockError):
            pixabay.make_stock()
        os.environ["POULTRY_PEXELS_API_KEY"] = "p"
        self.assertIsInstance(pixabay.make_stock(), pexels.PexelsStock)
        os.environ["POULTRY_PIXABAY_API_KEY"] = "x"
        self.assertIsInstance(pixabay.make_stock(), pixabay.PixabayStock)

    @unittest.skipUnless(HAVE, "ffmpeg жок")
    def test_landscape_cropped_to_vertical(self):
        from poultry_ig_agent import pixabay
        from poultry_ig_agent.tests.test_video import FakeTTS, FakeVeo, probe
        dl = lambda u, p: subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc=s=1280x720:d=10:r=24", "-pix_fmt", "yuv420p", p], check=True)
        st = pixabay.PixabayStock("K", transport=lambda u: {"hits": [hit(n) for n in range(1, 6)]}, downloader=dl)
        assets = tempfile.mkdtemp(); os.makedirs(os.path.join(assets, "real")); out = tempfile.mkdtemp()
        r = video.build({"lang": "ky", "content_type": "education", "voiceover": "x", "shots": shots(3, "real")}, out, FakeVeo(), FakeTTS(), assets, stock=st)
        self.assertEqual(r["status"], "ready", r)
        v = [s for s in probe(os.path.join(out, "final.mp4")) if s["codec_type"] == "video"][0]
        self.assertEqual((v["width"], v["height"]), (1080, 1920))


class FoodFilter(unittest.TestCase):
    def test_cooked_chicken_rejected(self):
        self.assertFalse(pexels.relevant("chicken, grill, food, meat"))
        self.assertFalse(pexels.relevant("chicken, wok, cooking, kitchen"))
        self.assertTrue(pexels.relevant("chicken, hen, farm, poultry"))
