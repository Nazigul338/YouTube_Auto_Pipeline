"""Drive тазалоо: катаал план, md5 көчүрмө текшерүү, СЕБЕТКЕ гана, код дал келбесе эч нерсе жасалбайт."""
import unittest
from unittest import mock

from pipeline import drive_cleanup as dc


def row(i, folder, name, md5=None, size=10_000_000):
    from pipeline.drive_inventory import classify
    return {"id": f"id{i}", "name": name, "folder": folder, "mb": size / 1_048_576, "bytes": size, "md5": md5,
            "cat": classify(f"{folder}/{name}", name, "video/mp4")[0]}


ROWS = [
    row(1, "YouTube_Auto/Long_Videos/test_2k", "CINEMATIC_10SEC_NEW.mp4", "aa"),
    row(2, "YouTube_Auto/Long_Videos/test_2k", "CINEMATIC_10SEC_YELLOW_ONLY.mp4", "aa"),
    row(3, "YouTube_Auto_TEST/Projects/Video_005/audio", "music_bed.wav"),
    row(4, "YouTube_Auto_TEST/Projects/Video_004/audio", "music_bed.wav"),
    row(5, "YouTube_Auto_TEST/Projects/Video_003/audio/chunks", "chunk_01.wav"),
    row(6, "YouTube_Auto_TEST/Audio", "Video_004_voice.wav"),
    row(7, "YouTube_Auto_TEST/Final_Videos", "Video_003_cinematic.mp4"),
    row(8, "YouTube_Auto/Long_Videos/clips_2k", "extra_01.mp4"),
    row(9, "YouTube_Auto_TEST/Projects/Video_001/audio", "voice_raw.wav"),
    row(10, "YouTube_Auto_TEST/_preview", "Video_003_cinematic_60s.mp4"),
    row(11, "YouTube_Auto_TEST/Projects/Video_006/audio", "voice.wav"),
    row(12, "YouTube_Auto_TEST/_voice_test", "A_Algenib_voice.mp3"),
]


class TestCleanup(unittest.TestCase):
    def test_plan_is_strict(self):
        p = dc.plan(ROWS)
        got = {r["id"] for r in p["files"]}
        self.assertEqual(got, {"id1", "id2", "id3", "id12"})
        for bad in ("id10", "id4", "id5", "id6", "id7", "id8", "id9", "id11"):
            self.assertNotIn(bad, got)

    def test_duplicates_verified_by_md5_and_size(self):
        p = dc.plan(ROWS)
        d = {r["id"]: r.get("duplicate") for r in p["files"]}
        self.assertEqual(d["id1"]["identical_md5"], "aa")
        self.assertFalse(d["id1"]["copy_kept"])          # экөө тең пландa — ачык белгиленет
        diff = [row(20, "YouTube_Auto/Long_Videos/test_2k", "a.mp4", "bb", 5),
                row(21, "YouTube_Auto/Long_Videos/test_2k", "b.mp4", "bb", 6)]   # md5 бирдей, көлөм башка
        self.assertTrue(all(not r.get("duplicate") for r in dc.plan(diff)["files"]))

    def test_trash_only_with_matching_code(self):
        svc = mock.MagicMock()
        svc.files.return_value.get.return_value.execute.return_value = {"trashed": True}
        p = dc.plan(ROWS)
        with self.assertRaises(SystemExit):
            dc.trash(svc, p, "wrong", log=lambda *_: None)
        svc.files.return_value.update.assert_not_called()
        res = dc.trash(svc, p, p["code"], log=lambda *_: None)
        self.assertEqual(len(res["trashed"]), 4)
        for call in svc.files.return_value.update.call_args_list:
            self.assertEqual(call.kwargs["body"], {"trashed": True})
        svc.files.return_value.delete.assert_not_called()
        svc.files.return_value.emptyTrash.assert_not_called()

    def test_named_sets(self):
        rows = [row(30, "YouTube_Auto/Long_Videos/clips_2k", "extra_01.mp4", "cc"),
                row(31, "YouTube_Auto/Long_Videos/clips_2k", "new_03.mp4", "cc"),
                row(32, "YouTube_Auto/Long_Videos/clips", "extra_02.mp4"),
                row(33, "YouTube_Auto_TEST/_preview", "Video_003_cinematic_60s.mp4"),
                row(34, "YouTube_Auto_TEST/Final_Videos", "Video_003_cinematic.mp4"),
                row(35, "YouTube_Auto/Long_Videos/final", "video_001_final_v2.mp4")]
        ex = dc.plan(rows, "extra")
        self.assertEqual([r["id"] for r in ex["files"]], ["id30"])
        self.assertTrue(ex["files"][0]["duplicate"]["copy_kept"])          # new_03 калат
        self.assertEqual([r["id"] for r in dc.plan(rows, "preview")["files"]], ["id33"])
        self.assertNotEqual(ex["code"], dc.plan(rows, "preview")["code"])

    def test_colab_clips_set(self):
        rows = [row(40, "YouTube_Auto/Long_Videos/clips_2k", "new_09.mp4"),
                row(41, "YouTube_Auto/Long_Videos/clips", "clip_03.mp4"),
                row(42, "YouTube_Auto/Long_Videos/final", "video_001_final_v2.mp4"),
                row(43, "YouTube_Auto/Long_Videos/audio", "video_001_part_01.wav"),
                row(44, "YouTube_Auto_TEST/Clips", "x.mp4"),
                row(45, "YouTube_Auto/Long_Videos/clips_2k", "video_001_clip.mp4")]
        self.assertEqual({r["id"] for r in dc.plan(rows, "colab_clips")["files"]}, {"id40", "id41"})

    def test_colab_rest(self):
        def r(i, folder, name, created="2026-11-05", mime="audio/wav"):
            x = row(i, folder, name)
            x.update(created=created, mime=mime)
            return x
        rows = [r(50, "YouTube_Auto", "music.mp3"),
                r(51, "YouTube_Auto/Long_Videos/audio", "test_Orus.wav"),
                r(52, "YouTube_Auto/Long_Videos/audio", "video_001_part_01.wav"),
                r(53, "YouTube_Auto/Long_Videos/final", "video_001_final_v2.mp4"),
                r(54, "YouTube_Auto/Music", "song.mp3"),
                r(55, "YouTube_Auto", "notes.txt", mime="text/plain"),
                r(56, "Colab Notebooks", "nb", mime="application/vnd.google.colaboratory"),
                r(57, "YouTube_Auto", "late.mp3", created="2026-11-20"),
                r(58, "YouTube_Auto_TEST", "x.wav")]
        self.assertEqual({x["id"] for x in dc.plan(rows, "colab_rest")["files"]}, {"id50", "id51"})

    def test_colab_videos(self):
        def r(i, folder, name, created="2026-11-05"):
            x = row(i, folder, name)
            x["created"] = created
            return x
        rows = [r(60, "YouTube_Auto/Long_Videos/final", "video_001_final_v2.mp4"),
                r(61, "YouTube_Auto/Long_Videos/final", "video_001_visual.mp4"),
                r(62, "YouTube_Auto_TEST/Final_Videos", "Video_001.mp4", "2026-11-16"),
                r(63, "YouTube_Auto/Long_Videos/audio", "video_001_full_voice_same6.wav"),
                r(64, "YouTube_Auto/Long_Videos/final", "new.mp4", "2026-11-20")]
        self.assertEqual({x["id"] for x in dc.plan(rows, "colab_videos")["files"]}, {"id60", "id61"})

    def test_keep_latest(self):
        rows = [row(70, "YouTube_Auto_TEST/Final_Videos", "Video_004_cinematic.mp4"),
                row(71, "YouTube_Auto_TEST/Final_Videos", "Video_001.mp4"),
                row(72, "YouTube_Auto_TEST/_preview", "Video_003_cinematic_60s.mp4"),
                row(73, "YouTube_Auto_TEST/Projects/Video_001/audio", "voice.wav"),
                row(74, "Poultry/videos", "reel.mp4")]
        self.assertEqual({x["id"] for x in dc.plan(rows, "keep_latest")["files"]}, {"id71", "id72"})

    def test_no_delete_in_code(self):
        src = open(dc.__file__, encoding="utf-8").read()
        self.assertNotIn(".delete(", src)
        self.assertNotIn("emptyTrash(", src)


if __name__ == "__main__":
    unittest.main()
