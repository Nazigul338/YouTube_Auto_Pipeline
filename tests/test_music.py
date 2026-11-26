"""Музыка китепканасынын тесттери."""

import tempfile
import unittest
from pathlib import Path

from pipeline import music


def make_library(files):
    d = tempfile.TemporaryDirectory()
    for rel in files:
        p = Path(d.name) / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"x")
    return d


class TestClassify(unittest.TestCase):
    def test_sources_by_folder(self):
        self.assertEqual(music.classify("Pixabay/a.mp3")[0], "Pixabay Music")
        self.assertEqual(music.classify("pixabay/a.mp3")[1], "Pixabay Content License")
        self.assertFalse(music.classify("YouTube_Audio_Library/a.mp3")[2])
        self.assertTrue(music.classify("YouTube Audio Library Attribution/a.mp3")[2])
        self.assertTrue(music.classify("youtube-audio-library-attribution/a.mp3")[2])

    def test_unknown(self):
        self.assertEqual(music.classify("a.mp3")[0], "Unknown")           # папкасыз
        self.assertEqual(music.classify("Random/a.mp3")[0], "Unknown")    # белгисиз папка
        self.assertIsNone(music.classify("a.mp3")[2])


class TestScan(unittest.TestCase):
    def test_scan_filters_and_records(self):
        d = make_library(["Pixabay/calm-piano_123.mp3", "YouTube_Audio_Library/x.wav",
                          "Pixabay/readme.txt", "loose.mp3"])
        tracks = music.scan(Path(d.name))
        self.assertEqual(len(tracks), 3)
        t = next(t for t in tracks if t.rel == "Pixabay/calm-piano_123.mp3")
        self.assertEqual(t.title, "calm piano 123")
        rec = t.license_record()
        self.assertEqual(rec["basis"], "folder_chosen_by_owner")
        self.assertEqual(rec["license"], "Pixabay Content License")
        d.cleanup()

    def test_scan_missing_folder(self):
        self.assertEqual(music.scan(Path("/no/such/folder")), [])

    def test_report(self):
        total, by_source, unknown = music.library_report(
            ["Pixabay/a.mp3", "Pixabay/b.mp3", "loose.mp3", "Pixabay/c.txt"])
        self.assertEqual((total, unknown), (3, 1))
        self.assertEqual(by_source["Pixabay Music"], 2)
        self.assertIn("белгисиз", music.describe_report(total, by_source, unknown))
        self.assertIn("бош", music.describe_report(0, {}, 0))


class TestPick(unittest.TestCase):
    def setUp(self):
        self.d = make_library(["Pixabay/a.mp3", "Pixabay/b.mp3", "Pixabay/c.mp3", "loose.mp3"])
        self.tracks = music.scan(Path(self.d.name))

    def tearDown(self):
        self.d.cleanup()

    def test_never_picks_unknown_source(self):
        picked = {music.pick(self.tracks, []).rel}
        self.assertNotIn("loose.mp3", picked)

    def test_least_recently_used(self):
        self.assertEqual(music.pick(self.tracks, []).rel, "Pixabay/a.mp3")
        self.assertEqual(music.pick(self.tracks, ["Pixabay/a.mp3"]).rel, "Pixabay/b.mp3")
        # бардыгы колдонулган → эң эскиси
        used = ["Pixabay/b.mp3", "Pixabay/c.mp3", "Pixabay/a.mp3"]
        self.assertEqual(music.pick(self.tracks, used).rel, "Pixabay/b.mp3")

    def test_no_usable_tracks(self):
        only_unknown = [t for t in self.tracks if not t.is_known]
        self.assertIsNone(music.pick(only_unknown, []))
        self.assertIsNone(music.pick([], []))

    def test_attribution_text(self):
        d = make_library(["YouTube_Audio_Library_Attribution/Song_Name.mp3", "Pixabay/p.mp3"])
        tracks = {t.rel: t for t in music.scan(Path(d.name))}
        self.assertIn("Song Name", music.attribution_text(tracks["YouTube_Audio_Library_Attribution/Song_Name.mp3"]))
        self.assertIsNone(music.attribution_text(tracks["Pixabay/p.mp3"]))
        d.cleanup()


if __name__ == "__main__":
    unittest.main()


class TestNoRepeatedMusic(unittest.TestCase):
    """2026-11-25 (колдонуучу): фондук музыка мурунку даяр видеолордукун кайталабайт."""

    def lib(self):
        d = make_library(["YouTube Audio Library Attribution/Keys.mp3", "YouTube Audio Library Attribution/Duty.mp3",
                          "YouTube Audio Library Attribution/Missing.mp3", "YouTube Audio Library Attribution/Fresh.mp3"])
        return d, music.scan(Path(d.name))

    def test_avoids_ready_videos_and_own_previous(self):
        from pipeline.stages.s7_music import pick_track
        d, tracks = self.lib()
        rel = lambda n: f"YouTube Audio Library Attribution/{n}.mp3"
        tags = {rel("Keys"): {"mood": "emotional_piano", "vocals": False},        # маанайы дал келет, бирок колдонулган
                rel("Duty"): {"mood": "dark", "vocals": False},
                rel("Missing"): {"mood": "dark", "vocals": False},
                rel("Fresh"): {"mood": "calm", "vocals": False}}
        reg = {"videos": {"Video_001": {"status": "ready", "music": rel("Keys")},
                          "Video_004": {"status": "ready", "music": rel("Keys")},
                          "Video_003": {"status": "failed", "music": rel("Missing")}}}
        best, why, forced = pick_track(tracks, tags, "emotional_piano", reg, "Video_003")
        self.assertNotEqual(best.rel, rel("Keys"))          # маанай дал келсе да — кайталанбайт
        self.assertNotEqual(best.rel, rel("Missing"))        # өз мурунку трегин да алмаштырат
        self.assertFalse(forced)
        self.assertEqual(best.rel, rel("Duty"))              # калгандардын эң аз колдонулганы (тең → аты боюнча)

    def test_library_exhausted_flags_forced_repeat(self):
        from pipeline.stages.s7_music import pick_track, used_by_finished
        d = make_library(["YouTube Audio Library Attribution/Only.mp3"])
        tracks = music.scan(Path(d.name))
        rel = tracks[0].rel
        reg = {"videos": {"Video_001": {"status": "ready", "music": rel}}}
        self.assertEqual(used_by_finished(reg, "Video_009"), {rel})
        best, why, forced = pick_track(tracks, {rel: {"mood": "x", "vocals": False}}, "x", reg, "Video_009")
        self.assertTrue(forced)
        self.assertIn("китепкана түгөндү", why)
