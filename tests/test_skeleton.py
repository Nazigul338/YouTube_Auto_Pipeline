"""Каркастын тесттери: python -m unittest discover tests"""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from pipeline import runner
from pipeline.config import load_config
from pipeline.project import slugify, versioned_path
from pipeline.stages import STAGE_NAMES
from pipeline.stages.base import Stage, StageError
from pipeline.state import DONE, FAILED, PENDING, VideoState

KEYS = {"GOOGLE_API_KEY": "test", "PIXABAY_API_KEY": "test"}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cfg = load_config("motivation", drive_root=self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def run_quiet(self, topic, **kw):
        with mock.patch("builtins.print"):
            return runner.run(topic, cfg=self.cfg, **kw)


class TestHelpers(unittest.TestCase):
    def test_slugify(self):
        self.assertEqual(slugify("Почему ты откладываешь?"), "pochemu-ty-otkladyvaesh")
        self.assertEqual(slugify("!!!"), "video")

    def test_versioned_path(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "script.txt"
            self.assertEqual(versioned_path(p), p)
            p.write_text("a")
            self.assertEqual(versioned_path(p).name, "script_v2.txt")
            (Path(d) / "script_v2.txt").write_text("b")
            self.assertEqual(versioned_path(p).name, "script_v3.txt")

    def test_niche_config(self):
        cfg = load_config("motivation")
        self.assertEqual(cfg.tts_voice, "Algenib")
        self.assertEqual((cfg.width, cfg.height), (1920, 1080))
        with self.assertRaises(FileNotFoundError):
            load_config("no_such_niche")


@mock.patch.dict(os.environ, KEYS)
class TestRunner(Base):
    def test_new_project_and_check_stage(self):
        state = self.run_quiet("Тест тема")
        folder = state.folder
        self.assertTrue((folder / "state.json").exists())
        for sub in ["script", "audio", "subtitles", "clips", "animation", "music", "render", "logs"]:
            self.assertTrue((folder / sub).is_dir())
        self.assertEqual(state.status("s0_check"), DONE)
        self.assertEqual(state.status("s1_script"), PENDING)  # азырынча даяр эмес
        self.assertTrue((folder / "logs" / "run.log").exists())
        data = json.loads((folder / "state.json").read_text(encoding="utf-8"))
        self.assertEqual(list(data["stages"]), STAGE_NAMES)

    def test_resume_same_topic(self):
        s1 = self.run_quiet("Бир тема")
        s2 = self.run_quiet("Бир тема")
        self.assertEqual(s1.folder, s2.folder)
        s3 = self.run_quiet("Бир тема", new=True)
        self.assertNotEqual(s1.folder, s3.folder)

    def test_empty_topic(self):
        with self.assertRaises(ValueError):
            self.run_quiet("   ")

    def test_failure_is_recorded_and_retry_works(self):
        class Boom(Stage):
            name, title = "s1_script", "Сценарий"
            calls = 0

            def run(self, ctx):
                Boom.calls += 1
                if Boom.calls == 1:
                    raise StageError("сыноо катасы")
                p = ctx.path("script", "script.txt")
                p.write_text("ok", encoding="utf-8")
                return {"script_path": str(p)}

        stages = list(runner.STAGES)
        stages[1] = Boom()
        with mock.patch.object(runner, "STAGES", stages):
            st = self.run_quiet("Ката тема")
            self.assertEqual(st.status("s1_script"), FAILED)
            self.assertIn("сыноо катасы", st.stage("s1_script")["error"])
            st = self.run_quiet("Ката тема")  # кайра ▶
            self.assertEqual(st.status("s1_script"), DONE)
            self.assertEqual(st.stage("s1_script")["attempts"], 2)

    def test_verify_catches_missing_file(self):
        class NoFile(Stage):
            name, title = "s1_script", "Сценарий"

            def run(self, ctx):
                return {"script_path": str(ctx.path("script", "missing.txt"))}

        stages = list(runner.STAGES)
        stages[1] = NoFile()
        with mock.patch.object(runner, "STAGES", stages):
            st = self.run_quiet("Текшерүү тема")
        self.assertEqual(st.status("s1_script"), FAILED)

    def test_missing_secret_fails_check(self):
        with mock.patch.dict(os.environ, {"PIXABAY_API_KEY": ""}):
            st = self.run_quiet("Ачкычсыз")
        self.assertEqual(st.status("s0_check"), FAILED)
        self.assertIn("PIXABAY_API_KEY", st.stage("s0_check")["error"])

    def test_bad_stage_name(self):
        with self.assertRaises(ValueError):
            self.run_quiet("Тема", stop_after="s99")


if __name__ == "__main__":
    unittest.main()
