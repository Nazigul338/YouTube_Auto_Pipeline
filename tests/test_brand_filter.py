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
