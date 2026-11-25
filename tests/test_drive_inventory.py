"""Drive инвентаризациясы: категориялар жана ОКУУ ГАНА кепилдиги."""
import unittest
from unittest import mock

from pipeline import drive_inventory as di


class TestClassify(unittest.TestCase):
    def c(self, path, mime="video/mp4"):
        return di.classify(path, path.rsplit("/", 1)[-1], mime)[0]

    def test_categories(self):
        self.assertEqual(self.c("YouTube_Auto/Final_Videos/Video_001.mp4"), "protected")
        self.assertEqual(self.c("YouTube_Auto/Final_Videos/Video_001_cinematic.mp4"), "protected")
        self.assertEqual(self.c("YouTube_Auto/Projects/Video_001/audio/voice.wav", "audio/wav"), "protected")
        self.assertEqual(self.c("YouTube_Auto/Final_Videos/Video_003.mp4"), "protected")
        self.assertEqual(self.c("YouTube_Auto_TEST/Final_Videos/Video_004_cinematic.mp4"), "protected")
        self.assertEqual(self.c("YouTube_Auto_TEST/Final_Videos/Video_003.mp4"), "protected")
        self.assertEqual(self.c("YouTube_Auto/Long_Videos/final/video_001_final_v2.mp4"), "protected")
        self.assertEqual(self.c("YouTube_Auto/Long_Videos/audio/video_001_part_01.wav", "audio/wav"), "protected")
        self.assertEqual(self.c("YouTube_Auto_TEST/Projects/Video_005/audio/voice.wav", "audio/wav"), "candidate")
        self.assertEqual(self.c("YouTube_Auto_TEST/Projects/Video_004/audio/music_bed.wav", "audio/wav"), "candidate")
        self.assertEqual(self.c("YouTube_Auto_TEST/Projects/Video_004/audio/voice.wav", "audio/wav"), "protected")
        self.assertEqual(self.c("YouTube_Auto_TEST/Audio/Video_004_voice.wav", "audio/wav"), "candidate")
        self.assertEqual(self.c("YouTube_Auto/Sound_Effects/nature/rain_02.wav", "audio/wav"), "protected")
        self.assertEqual(self.c("YouTube_Auto/Long_Videos/test_2k/CINEMATIC_10SEC_NEW.mp4"), "candidate")
        self.assertEqual(self.c("YouTube_Auto/Long_Videos/clips_2k/extra_01.mp4"), "keep_review")
        self.assertEqual(self.c("YouTube_Auto_TEST/Projects/Video_006/audio/voice.wav", "audio/wav"), "active")
        self.assertEqual(self.c("YouTube_Auto_TEST/Projects/Video_004/script/script.txt", "text/plain"), "protected")
        self.assertEqual(self.c("YouTube_Auto/Music/song.mp3", "audio/mpeg"), "protected")
        self.assertEqual(self.c("YouTube_Auto/Licenses/x.wav", "audio/wav"), "protected")
        self.assertEqual(self.c("Colab Notebooks/extra_01.mp4"), "user")
        self.assertEqual(self.c("YouTube_Auto/music.mp3", "audio/mpeg"), "keep_review")

    def test_read_only(self):
        svc = mock.MagicMock()
        svc.files.return_value.list.return_value.execute.return_value = {"files": []}
        svc.about.return_value.get.return_value.execute.return_value = {"storageQuota": {"limit": "1", "usage": "1"}}
        inv = di.Inventory(svc)
        inv.quota()
        data = inv.collect()
        di.report(inv.quota(), data)
        for bad in ("delete", "update", "create", "emptyTrash", "copy"):
            getattr(svc.files.return_value, bad).assert_not_called()


if __name__ == "__main__":
    unittest.main()
