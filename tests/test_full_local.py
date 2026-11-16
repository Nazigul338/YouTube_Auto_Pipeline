"""Бүт конвейердин интеграциялык тести: жалган API'лер, ЧЫНЫГЫ FFmpeg монтаж.

Узак иштейт (~1–3 мүн). GitHub workflow'до YTA_SKIP_SLOW=1 менен өткөрүлөт.
"""

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from pipeline import ci, media
from pipeline.storage import LocalStore
from tests.fakes import FakeGemini, FakeStock
from tests.test_stages_audio import fake_whisper_for


def small_cfg(root):
    from pipeline.config import load_config
    return load_config("motivation", drive_root=root, words_min=110, words_max=150,
                       min_duration_sec=30)


@unittest.skipIf(os.environ.get("YTA_SKIP_SLOW"), "узак тест")
class TestFullPipeline(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.store = LocalStore(self.root / "drive")
        music = self.root / "drive" / "YouTube_Auto" / "Music" / "YouTube_Audio_Library_Attribution"
        music.mkdir(parents=True)
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
                        "sine=f=330:d=20", "-ac", "2", str(music / "Calm Piano - Tester.mp3")],
                       check=True)
        self.p = mock.patch("builtins.print")
        self.p.start()
        self.env = mock.patch.dict(os.environ, {"GOOGLE_API_KEY": "t", "PIXABAY_API_KEY": "t"})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.p.stop()
        self.tmp.cleanup()

    def test_topic_to_final_mp4(self):
        proj = self.root / "w" / "Projects" / "Video_001"
        services = {"gemini": FakeGemini(words=130), "stock": FakeStock(),
                    "asr": fake_whisper_for(proj)}
        with mock.patch.object(ci, "load_config") as lc:
            lc.side_effect = lambda n, drive_root=None: small_cfg(drive_root)
            code = ci.run_ci("Почему мы откладываем", "motivation", self.root / "w",
                             store=self.store, services=services)
        state = json.loads((proj / "state.json").read_text(encoding="utf-8"))
        failed = {k: v.get("error") for k, v in state["stages"].items() if v["status"] != "done"}
        self.assertEqual(failed, {})
        self.assertEqual(code, 0)

        drive = self.root / "drive" / "YouTube_Auto"
        final = drive / "Final_Videos" / "Video_001.mp4"
        self.assertTrue(final.exists())
        info = media.probe(final)
        v = next(s for s in info["streams"] if s["codec_type"] == "video")
        self.assertEqual((v["width"], v["height"]), (1920, 1080))
        self.assertTrue(any(s["codec_type"] == "audio" for s in info["streams"]))
        for f in ["Scripts/Video_001.txt", "Audio/Video_001_voice.wav", "Subtitles/Video_001.srt",
                  "Clips/Video_001_clips.json", "Licenses/Video_001_LICENSE.txt", "Logs/Video_001.log",
                  "Projects/Video_001/report.txt", "Projects/Video_001/state.json",
                  "Music/_tags.json"]:
            self.assertTrue((drive / f).exists(), f)
        report = (drive / "Projects" / "Video_001" / "report.txt").read_text(encoding="utf-8")
        self.assertIn("ӨТТҮ", report)
        lic = (drive / "Licenses" / "Video_001_LICENSE.txt").read_text(encoding="utf-8")
        self.assertIn("Calm Piano", lic)
        self.assertIn("Music:", (drive / "Projects" / "Video_001" / "youtube_description.txt")
                      .read_text(encoding="utf-8"))
        reg = self.store.load_registry()["videos"]["Video_001"]
        self.assertEqual(reg["status"], "ready")
        self.assertTrue(reg["clip_ids"])
        self.assertTrue(reg["concept"])
        self.assertFalse(any((drive / "Projects" / "Video_001").rglob("*.mp4")))  # оор файлдар жок


if __name__ == "__main__":
    unittest.main()
