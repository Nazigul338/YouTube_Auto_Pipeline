import unittest

from pipeline import chapter_check as cc


class TestFindPhrase(unittest.TestCase):
    words = [("мы", 25.0, 25.2), ("привыкли", 25.3, 25.7), ("думать", 25.8, 26.2), ("что", 26.3, 26.4),
             ("мы", 100.0, 100.1), ("привыкли", 100.2, 100.5), ("думать", 100.6, 100.9)]

    def test_nearest_occurrence(self):
        self.assertEqual(cc.find_phrase(self.words, "мы привыкли думать", 26), 25.0)
        self.assertEqual(cc.find_phrase(self.words, "мы привыкли думать", 99), 100.0)

    def test_missing_and_tolerance(self):
        self.assertIsNone(cc.find_phrase(self.words, "нет такой фразы", 26))
        rows = cc.check("x", self.words, [(26, "мы привыкли думать"), (60, "мы привыкли думать")])
        self.assertTrue(rows[0]["ok"])
        self.assertFalse(rows[1]["ok"])          # 40 сек терезеден тышкары

    def test_chapter_tables_sorted_and_start_at_zero(self):
        for name, ch in cc.CHAPTERS.items():
            secs = [s for s, _ in ch]
            self.assertEqual(secs[0], 0, name)
            self.assertEqual(secs, sorted(secs), name)
            self.assertTrue(all(b - a >= 10 for a, b in zip(secs, secs[1:])), name)   # YouTube: глава ≥ 10 сек


if __name__ == "__main__":
    unittest.main()
