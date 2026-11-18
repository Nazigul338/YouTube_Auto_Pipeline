"""Даяр видеонун шилтемеси автоматтык чыгат (колдонуучу Drive'дан издебейт)."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from pipeline import ci
from pipeline.state import VideoState
from pipeline.storage import DriveStore, LocalStore


class FakeDrive:
    def ensure_path(self, *a):
        return "FOLDER"

    def put_file(self, local, parent, name):
        return "FILE123"


class TestVideoLink(unittest.TestCase):
    def test_drive_publish_returns_view_link(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "v.mp4"
            f.write_bytes(b"x")
            url = DriveStore(FakeDrive()).publish("Final_Videos", f, "Video_009.mp4")
        self.assertEqual(url, "https://drive.google.com/file/d/FILE123/view")

    def test_local_publish_returns_path(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "v.mp4"
            f.write_bytes(b"x")
            self.assertTrue(LocalStore(Path(d)).publish("Final_Videos", f, "a.mp4").startswith("file://"))

    def test_summary_shows_link_first_when_ready(self):
        with tempfile.TemporaryDirectory() as d:
            st = VideoState.create(Path(d) / "p", "Тема", "motivation", ci.STAGE_NAMES)
            for n in ci.STAGE_NAMES:
                st.mark_done(n, {})
            summ = Path(d) / "summary.md"
            with mock.patch.dict(os.environ, {"GITHUB_STEP_SUMMARY": str(summ)}):
                ci._write_summary(st, "Video_009", "https://drive.google.com/file/d/X/view")
            text = summ.read_text(encoding="utf-8")
        self.assertIn("[ВИДЕОНУ КӨРҮҮ (Google Drive)](https://drive.google.com/file/d/X/view)", text)
        self.assertLess(text.index("ВИДЕОНУ КӨРҮҮ"), text.index("Сценарий"))

    def test_no_link_when_not_ready(self):
        with tempfile.TemporaryDirectory() as d:
            st = VideoState.create(Path(d) / "p", "Тема", "motivation", ci.STAGE_NAMES)
            summ = Path(d) / "summary.md"
            with mock.patch.dict(os.environ, {"GITHUB_STEP_SUMMARY": str(summ)}):
                ci._write_summary(st, "Video_009", "https://drive.google.com/file/d/X/view")
            self.assertNotIn("ВИДЕОНУ КӨРҮҮ", summ.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()


class TestPreviewSheet(unittest.TestCase):
    def test_sheet_times_even(self):
        from pipeline.make_preview import sheet_times
        t = sheet_times(540.0, 20)
        self.assertEqual(len(t), 20)
        self.assertAlmostEqual(t[0], 13.5)
        self.assertAlmostEqual(t[-1], 526.5)
        self.assertEqual(sheet_times(0.0), [])
