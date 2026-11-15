"""CI режиминин тесттери (чыныгы Drive'сыз, жалган Drive менен)."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from pipeline import ci, runner
from pipeline.stages.base import Stage, StageError

KEYS = {"GOOGLE_API_KEY": "t", "PIXABAY_API_KEY": "t"}


class FakeDrive:
    def __init__(self, music=("a.mp3", "b.wav")):
        self.music = music
        self.uploaded: list[Path] = []
        self.paths: list[tuple] = []

    def whoami(self):
        return "user@example.com"

    def ensure_path(self, *names):
        self.paths.append(names)
        return "/".join(names)

    def find_path(self, *names):
        self.paths.append(("find",) + names)
        return "/".join(names) if self.music is not None else None

    def download_folder(self, folder_id, dest, only_ext=None):
        dest.mkdir(parents=True, exist_ok=True)
        out = []
        for n in self.music:
            (dest / n).write_bytes(b"x")
            out.append(dest / n)
        return out

    def upload_tree(self, local_dir, parent_id, log=print):
        self.uploaded.append(local_dir)
        return "folder-id"


@mock.patch.dict(os.environ, KEYS)
class TestCI(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.work = Path(self.tmp.name)
        self.patch = mock.patch("builtins.print")
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self.tmp.cleanup()

    def test_with_drive_pulls_music_and_uploads(self):
        drive = FakeDrive()
        code = ci.run_ci("Тест", "motivation", self.work, drive=drive)
        self.assertEqual(code, 0)
        self.assertTrue((self.work / "Music" / "a.mp3").exists())
        self.assertEqual(len(drive.uploaded), 1)
        self.assertTrue((drive.uploaded[0] / "state.json").exists())
        self.assertIn(("YouTube_Auto", "Videos"), drive.paths)
        self.assertIn(("find", "YouTube_Auto", "Music"), drive.paths)  # окуу гана
        self.assertNotIn(("YouTube_Auto", "Music"), drive.paths)       # түзүлгөн жок

    def test_without_drive_still_runs(self):
        self.assertEqual(ci.run_ci("Тест", "motivation", self.work, drive=None), 0)

    def test_failed_stage_returns_1_and_still_uploads(self):
        class Boom(Stage):
            name, title = "s1_script", "Сценарий"

            def run(self, ctx):
                raise StageError("сыноо")

        stages = list(runner.STAGES)
        stages[1] = Boom()
        drive = FakeDrive()
        with mock.patch.object(runner, "STAGES", stages), \
             mock.patch.object(ci, "STAGES", stages):
            code = ci.run_ci("Ката", "motivation", self.work, drive=drive)
        self.assertEqual(code, 1)
        self.assertEqual(len(drive.uploaded), 1)  # логдор Drive'га барышы керек

    def test_each_run_makes_new_folder(self):
        d1, d2 = FakeDrive(), FakeDrive()
        ci.run_ci("Бир тема", "motivation", self.work, drive=d1)
        ci.run_ci("Бир тема", "motivation", self.work, drive=d2)
        self.assertNotEqual(d1.uploaded[0], d2.uploaded[0])

    def test_empty_topic_returns_2(self):
        self.assertEqual(ci.main(["--topic", "  ", "--workdir", str(self.work)]), 2)

    def test_summary_written(self):
        summary = self.work / "summary.md"
        with mock.patch.dict(os.environ, {"GITHUB_STEP_SUMMARY": str(summary)}):
            ci.run_ci("Тест", "motivation", self.work, drive=FakeDrive())
        text = summary.read_text(encoding="utf-8")
        self.assertIn("Тест", text)
        self.assertIn("Drive", text)

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

    def test_missing_music_folder_is_not_created(self):
        d = FakeDrive(music=None)
        with mock.patch("builtins.print"):
            from pipeline.config import load_config
            cfg = load_config("motivation", drive_root=tempfile.mkdtemp())
            self.assertEqual(ci.pull_music(d, cfg), 0)
        self.assertNotIn(("YouTube_Auto", "Music"), d.paths)
