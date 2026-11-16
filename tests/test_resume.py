"""Автоматтык улантуунун тесттери."""

import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from pipeline import ci, runner
from pipeline.errors import QuotaExhausted, StageError, TransientError
from pipeline.stages.base import Stage
from pipeline.stages.s0_check import CheckStage
from pipeline.storage import LocalStore

KEYS = {"GOOGLE_API_KEY": "t", "PIXABAY_API_KEY": "t"}
NOW = datetime(2026, 11, 20, 12, 0, tzinfo=timezone.utc)
OLD = (NOW - timedelta(hours=5)).isoformat()


def video(**kw):
    base = {"topic": "t", "niche": "motivation", "created": (NOW - timedelta(days=1)).isoformat(),
            "updated": OLD}
    base.update(kw)
    return base


class TestFindPending(unittest.TestCase):
    def pick(self, videos):
        return ci.find_pending({"videos": videos}, NOW)

    def test_quota_and_transient_are_resumed_oldest_first(self):
        self.assertEqual(self.pick({
            "Video_002": video(status="failed", failure_kind="transient"),
            "Video_001": video(status="failed", failure_kind="quota")}), "Video_001")

    def test_real_errors_are_not_resumed(self):
        self.assertIsNone(self.pick({"Video_001": video(status="failed", failure_kind="error")}))

    def test_ready_stopped_and_abandoned_are_skipped(self):
        self.assertIsNone(self.pick({
            "Video_001": video(status="ready"),
            "Video_002": video(status="in_progress", stopped_by_user=True),
            "Video_003": video(status="failed", failure_kind="quota", abandoned=True)}))

    def test_cut_off_run_is_resumed_but_fresh_run_is_not(self):
        self.assertEqual(self.pick({"Video_001": video(status="in_progress")}), "Video_001")
        fresh = video(status="in_progress", updated=(NOW - timedelta(minutes=3)).isoformat())
        self.assertIsNone(self.pick({"Video_001": fresh}))

    def test_limits(self):
        self.assertIsNone(self.pick({"Video_001": video(
            status="failed", failure_kind="quota", auto_resumes=ci.MAX_AUTO_RESUMES)}))
        old = video(status="failed", failure_kind="quota",
                    created=(NOW - timedelta(days=ci.MAX_AGE_DAYS + 1)).isoformat())
        self.assertIsNone(self.pick({"Video_001": old}))


def with_stage(stage_cls_factory):
    """Конвейерди [s0, s1(тест этабы)] кылып алмаштырат."""
    stages = [CheckStage(), stage_cls_factory()]
    names = [s.name for s in stages]
    return mock.patch.multiple(runner, STAGES=stages, STAGE_NAMES=names), \
        mock.patch.multiple(ci, STAGES=stages, STAGE_NAMES=names)


class TestResumeEndToEnd(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.store = LocalStore(self.root / "drive")
        self.work = self.root / "work"
        self.p = mock.patch("builtins.print")
        self.p.start()
        self.env = mock.patch.dict(os.environ, KEYS)
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.p.stop()
        self.tmp.cleanup()

    def make_stage(self, behaviours):
        calls = {"n": 0}

        class S(Stage):
            name, title = "s1_script", "Сценарий"
            retries = 0

            def run(self, ctx):
                b = behaviours[min(calls["n"], len(behaviours) - 1)]
                calls["n"] += 1
                if isinstance(b, Exception):
                    raise b
                p = ctx.path("script", "script.txt")
                p.write_text("ok", encoding="utf-8")
                return {"script_path": str(p)}

        return S

    def run_all(self, behaviours, topic="Тема"):
        S = self.make_stage(behaviours)
        a, b = with_stage(S)
        with a, b:
            first = ci.run_ci(topic, "motivation", self.work, store=self.store)
            reg1 = self.store.load_registry()["videos"]["Video_001"]
            second = ci.run_resume(self.work, store=self.store,
                                   now_dt=datetime.now(timezone.utc) + timedelta(hours=1))
            reg2 = self.store.load_registry()["videos"]["Video_001"]
        return first, reg1, second, reg2

    def test_quota_then_automatic_success(self):
        first, reg1, second, reg2 = self.run_all([QuotaExhausted("квота"), None])
        self.assertEqual(first, 1)
        self.assertEqual((reg1["status"], reg1["failure_kind"]), ("failed", "quota"))
        self.assertEqual(second, 0)
        self.assertEqual(reg2["status"], "ready")          # квота жаңыланды → өзү бүттү
        self.assertEqual(reg2["auto_resumes"], 1)
        st = json.loads((self.root / "drive" / "YouTube_Auto" / "Projects" / "Video_001" /
                         "state.json").read_text(encoding="utf-8"))
        self.assertEqual(st["stages"]["s1_script"]["status"], "done")

    def test_quota_again_is_quiet(self):
        first, _, second, reg2 = self.run_all([QuotaExhausted("квота")])
        self.assertEqual(second, 0)                        # ката эмес — кабарлоо жок
        self.assertEqual(reg2["failure_kind"], "quota")
        self.assertEqual(reg2["auto_resumes"], 1)

    def test_real_error_is_not_resumed_and_flagged(self):
        first, reg1, second, reg2 = self.run_all([StageError("чыныгы ката")])
        self.assertEqual(reg1["failure_kind"], "error")
        self.assertEqual(second, 0)                        # улантууга эч нерсе жок
        self.assertNotIn("auto_resumes", reg2)

    def test_transient_is_resumed(self):
        _, reg1, second, reg2 = self.run_all([TransientError("503"), None])
        self.assertEqual(reg1["failure_kind"], "transient")
        self.assertEqual(reg2["auto_resumes"], 1)

    def test_nothing_to_resume(self):
        self.assertEqual(ci.run_resume(self.work, store=self.store), 0)

    def test_no_drive_fails(self):
        self.assertEqual(ci.run_resume(self.work, store=None), 2)

    def test_stop_after_runs_are_never_auto_resumed(self):
        S = self.make_stage([None])
        a, b = with_stage(S)
        with a, b:
            ci.run_ci("Сыноо", "motivation", self.work, store=self.store, stop_after="s0_check")
            reg = self.store.load_registry()["videos"]["Video_001"]
            self.assertTrue(reg["stopped_by_user"])
            late = datetime.now(timezone.utc) + timedelta(days=1)
            self.assertIsNone(ci.find_pending({"videos": {"Video_001": reg}}, late))


if __name__ == "__main__":
    unittest.main()
