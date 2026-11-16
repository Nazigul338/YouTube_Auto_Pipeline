"""CI режиминин тесттери (чыныгы Drive'сыз, жалган Drive менен)."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import json

from pipeline import ci, runner
from pipeline.stages.base import Stage, StageError, TransientError
from pipeline.storage import LocalStore

KEYS = {"GOOGLE_API_KEY": "t", "PIXABAY_API_KEY": "t"}


class TestCI(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.store = LocalStore(self.root / "drive")
        self.work = self.root / "work"
        music = self.root / "drive" / "YouTube_Auto" / "Music" / "Pixabay"
        music.mkdir(parents=True)
        (music / "a.mp3").write_bytes(b"x")
        self.p = mock.patch("builtins.print")
        self.p.start()
        self.env = mock.patch.dict(os.environ, KEYS)
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.p.stop()
        self.tmp.cleanup()

    def drive(self, *parts):
        return self.root / "drive" / "YouTube_Auto" / Path(*parts)

    def test_layout_ids_and_checkpoint(self):
        code = ci.run_ci("Тест", "motivation", self.work, store=self.store)
        self.assertEqual(code, 0)
        for f in ["Projects", "Scripts", "Audio", "Subtitles", "Clips", "Final_Videos", "Logs", "Licenses"]:
            self.assertTrue(self.drive(f).is_dir(), f)
        self.assertTrue(self.drive("Projects", "Video_001", "state.json").exists())  # checkpoint
        self.assertTrue(self.drive("Logs", "Video_001.log").exists())
        reg = self.store.load_registry()
        self.assertEqual(reg["videos"]["Video_001"]["topic"], "Тест")
        self.assertTrue((self.work / "Music" / "Pixabay" / "a.mp3").exists())
        ci.run_ci("Экинчи", "motivation", self.work, store=self.store)
        self.assertIn("Video_002", self.store.load_registry()["videos"])

    def test_no_store_fails_fast(self):
        self.assertEqual(ci.run_ci("Тест", "motivation", self.work, store=None), 2)

    def test_empty_topic(self):
        self.assertEqual(ci.run_ci("  ", "motivation", self.work, store=self.store), 2)

    def test_resume_by_video_id(self):
        calls = {"n": 0}

        class Flaky(Stage):
            name, title = "s1_script", "Сценарий"

            def run(self, ctx):
                calls["n"] += 1
                if calls["n"] == 1:
                    raise StageError("сыноо")
                p = ctx.path("script", "script.txt")
                p.write_text("ok", encoding="utf-8")
                return {"script_path": str(p)}

        stages = list(runner.STAGES)
        stages[1] = Flaky()
        with mock.patch.object(runner, "STAGES", stages), mock.patch.object(ci, "STAGES", stages):
            self.assertEqual(ci.run_ci("Ката", "motivation", self.work, store=self.store), 1)
            st = json.loads(self.drive("Projects", "Video_001", "state.json").read_text("utf-8"))
            self.assertEqual(st["stages"]["s1_script"]["status"], "failed")  # Drive'да сакталды
            # жаңы runner (бош workdir) — Drive'дан улантуу
            code = ci.run_ci("", "motivation", self.root / "work2", store=self.store,
                             video_id="Video_001")
        self.assertEqual(code, 0)
        st = json.loads(self.drive("Projects", "Video_001", "state.json").read_text("utf-8"))
        self.assertEqual(st["stages"]["s1_script"]["status"], "done")
        self.assertEqual(st["stages"]["s1_script"]["attempts"], 2)
        self.assertTrue(self.drive("Projects", "Video_001", "script", "script.txt").exists())

    def test_unknown_video_id(self):
        self.assertEqual(ci.run_ci("", "motivation", self.work, store=self.store,
                                   video_id="Video_999"), 2)

    def test_transient_error_retried(self):
        calls = {"n": 0}

        class Busy(Stage):
            name, title = "s1_script", "Сценарий"
            retries = 2

            def run(self, ctx):
                calls["n"] += 1
                if calls["n"] < 3:
                    raise TransientError("503")
                return {}

        stages = list(runner.STAGES)
        stages[1] = Busy()
        with mock.patch.object(runner, "STAGES", stages), mock.patch.object(ci, "STAGES", stages), \
             mock.patch.object(runner.time, "sleep", lambda s: None):
            from pipeline.stages.base import Context
            code = ci.run_ci("Тест", "motivation", self.work, store=self.store)
        self.assertEqual(calls["n"], 3)

    def test_summary_written(self):
        summary = self.root / "summary.md"
        with mock.patch.dict(os.environ, {"GITHUB_STEP_SUMMARY": str(summary)}):
            ci.run_ci("Тест", "motivation", self.work, store=self.store)
        text = summary.read_text(encoding="utf-8")
        self.assertIn("Video_001", text)

    def test_heavy_files_not_synced(self):
        from pipeline.storage import heavy
        self.assertTrue(heavy("render/final.mp4"))
        self.assertTrue(heavy("clips/c1.mp4"))
        self.assertFalse(heavy("clips/clips.json"))
        self.assertFalse(heavy("audio/voice.wav"))
        self.assertFalse(heavy("state.json"))

    def test_check_mode_fails_without_secrets(self):
        env = {k: "" for k in ("GOOGLE_API_KEY", "PIXABAY_API_KEY",
                               "GDRIVE_CLIENT_ID", "GDRIVE_CLIENT_SECRET",
                               "GDRIVE_REFRESH_TOKEN")}
        with mock.patch.dict(os.environ, env):
            self.assertEqual(ci.run_check(), 1)


class TestDriveHelpers(unittest.TestCase):
    def test_from_env_none_without_secrets(self):
        from pipeline.drive import DriveClient
        with mock.patch.dict(os.environ, {"GDRIVE_CLIENT_ID": ""}):
            self.assertIsNone(DriveClient.from_env())

    def test_escape(self):
        from pipeline.drive import _escape
        self.assertEqual(_escape("it's"), "it\\'s")


if __name__ == "__main__":
    unittest.main()


class TestSecretStrip(unittest.TestCase):
    def test_get_secret_strips_whitespace(self):
        from pipeline.config import get_secret
        with mock.patch.dict(os.environ, {"X_TEST_KEY": "  abc123\n"}):
            self.assertEqual(get_secret("X_TEST_KEY"), "abc123")
        with mock.patch.dict(os.environ, {"X_TEST_KEY": "   "}):
            self.assertIsNone(get_secret("X_TEST_KEY"))


class TestDriveErrors(unittest.TestCase):
    def test_refresh_errors_are_explained(self):
        from pipeline.drive import explain_http_error
        class RefreshError(Exception):
            pass
        self.assertIn("эскирген", explain_http_error(RefreshError("invalid_grant: Token has been expired")))
        self.assertIn("Client ID", explain_http_error(RefreshError("invalid_client: Unauthorized")))
        self.assertIn("Test users", explain_http_error(RefreshError("access_denied")))
        self.assertNotIn("белгисиз ката", explain_http_error(RefreshError("x")))


class TestDriveSecretStrip(unittest.TestCase):
    def test_gdrive_secrets_are_stripped(self):
        from pipeline import drive
        env = {"GDRIVE_CLIENT_ID": " id \n", "GDRIVE_CLIENT_SECRET": "sec\n",
               "GDRIVE_REFRESH_TOKEN": "tok  "}
        with mock.patch.dict(os.environ, env):
            self.assertTrue(drive.drive_secrets_present())
            self.assertEqual([drive._secret(n) for n in drive.SECRET_NAMES],
                             ["id", "sec", "tok"])
        with mock.patch.dict(os.environ, {**env, "GDRIVE_REFRESH_TOKEN": "  \n"}):
            self.assertFalse(drive.drive_secrets_present())


class TestClientCheck(unittest.TestCase):
    class R:
        def __init__(self, data, code=400):
            self._d, self.status_code = data, code
        def json(self):
            return self._d

    def test_client_ok_when_invalid_grant(self):
        from pipeline.drive import check_client_credentials
        ok, _ = check_client_credentials("i", "s", post=lambda *a, **k: self.R({"error": "invalid_grant"}))
        self.assertTrue(ok)

    def test_client_bad_when_invalid_client(self):
        from pipeline.drive import check_client_credentials
        ok, note = check_client_credentials("i", "s", post=lambda *a, **k: self.R({"error": "invalid_client"}))
        self.assertFalse(ok)
        self.assertIn("туура эмес", note)


class TestMask(unittest.TestCase):
    def test_mask_email(self):
        from pipeline.drive import mask_email
        self.assertEqual(mask_email("someone@gmail.com"), "s***@gmail.com")
        self.assertEqual(mask_email("bad"), "***")
