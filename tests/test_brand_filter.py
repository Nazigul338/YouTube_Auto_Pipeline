"""Бренд/логотип чыпкасы: товардык белгиси бар сток клиптер алынбайт (монетизация тобокелдиги)."""

import unittest

from pipeline.stock import Stock, brand_risk


def hit(i, tags):
    v = {"width": 1920, "height": 1080, "url": f"https://x/{i}.mp4"}
    return {"id": i, "tags": tags, "duration": 10, "pageURL": "", "user": "u",
            "videos": {"small": v}}


class TestBrandFilter(unittest.TestCase):
    def test_brand_words(self):
        self.assertTrue(brand_risk("youtube, money, success"))
        self.assertTrue(brand_risk("https://www.pexels.com/video/man-holding-youtube-logo-123/"))
        self.assertTrue(brand_risk("Instagram, phone"))
        self.assertTrue(brand_risk("coca-cola bottle"))
        self.assertFalse(brand_risk("road, car, field, sunset"))
        self.assertFalse(brand_risk(""))
        self.assertFalse(brand_risk("branding-free nature"))   # «branding» ≠ «brand»

    def test_pixabay_skips_brand_clips(self):
        s = Stock("k")
        s._get = lambda url, params, headers=None: {"hits": [
            hit(1, "youtube, money, man"), hit(2, "road, field, car"), hit(3, "logo, business")]}
        ids = [a.id for a in s._pixabay_videos("success", 3.0)]
        self.assertEqual(ids, ["pixabay:2"])

    def test_pexels_skips_brand_url(self):
        s = Stock("k", "p")
        f = [{"width": 1920, "height": 1080, "link": "https://x/a.mp4"}]
        s._get = lambda url, params, headers=None: {"videos": [
            {"id": 1, "duration": 9, "url": "https://www.pexels.com/video/tiktok-app-on-phone-1/",
             "video_files": f, "user": {"name": "a"}},
            {"id": 2, "duration": 9, "url": "https://www.pexels.com/video/mountain-lake-2/",
             "video_files": f, "user": {"name": "b"}}]}
        ids = [a.id for a in s._pexels_videos("calm", 3.0)]
        self.assertEqual(ids, ["pexels:2"])


if __name__ == "__main__":
    unittest.main()


class TestRefreshUrl(unittest.TestCase):
    """run #44661498471: сакталган Pixabay шилтемеси эртеси иштеген жок → API'ден ID боюнча жаңы шилтеме."""

    def test_refresh_and_stage_fallback(self):
        import json
        import tempfile
        from pathlib import Path
        from types import SimpleNamespace

        from pipeline.errors import StageError, TransientError
        from pipeline.stages.s5_visuals import ensure_media

        s = Stock("k")
        s._get = lambda url, params, headers=None: {"hits": [hit(5277, "road")]} if params.get("id") == "5277" else {"hits": []}
        self.assertEqual(s.refresh_url("pixabay:5277"), "https://x/5277.mp4")
        self.assertIsNone(s.refresh_url("pixabay:1"))

        d = Path(tempfile.mkdtemp())
        (d / "clips").mkdir()
        shots = [{"i": 0, "file": "a.mp4", "source": "pixabay", "kind": "video", "asset": "pixabay:5277",
                  "url": "https://old/expired.mp4"}]
        (d / "clips" / "shots.json").write_text(json.dumps({"total": 3, "shots": shots}))
        calls = []

        def download(a, dest):
            calls.append(a.url)
            if "old" in a.url:
                raise TransientError("Жүктөө ишке ашкан жок: pixabay:5277 (HTTP 403)")
            dest.write_bytes(b"x" * 20000)
            return dest

        s.download = download
        logs = []
        ctx = SimpleNamespace(path=lambda *p: d.joinpath(*p), services={"stock": s}, log=logs.append, store=None)
        ensure_media(ctx)
        self.assertEqual(calls, ["https://old/expired.mp4", "https://x/5277.mp4"])
        saved = json.loads((d / "clips" / "shots.json").read_text())["shots"][0]["url"]
        self.assertEqual(saved, "https://x/5277.mp4")
        # клип өчүрүлгөн → так ката (rerun_from s5)
        (d / "clips" / "a.mp4").unlink()
        shots[0]["asset"] = "pixabay:1"
        (d / "clips" / "shots.json").write_text(json.dumps({"total": 3, "shots": shots}))
        with self.assertRaises(StageError) as cm:
            ensure_media(ctx)
        self.assertIn("s5_visuals", str(cm.exception))
