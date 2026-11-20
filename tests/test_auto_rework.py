"""Автоматтык кайра монтаж: QA шаблонго окшош деп тапса — жаңы концепция, монтаж s4'төн кайра (≤2 жолу)."""

import unittest

from pipeline import ci
from pipeline.state import FAILED


class FakeState:
    def __init__(self, qa_failed: bool):
        self.data = {"stages": {"s9_qa": {}}}
        self.qa_failed = qa_failed

    def status(self, name):
        return FAILED if self.qa_failed else "done"


class TestAutoRework(unittest.TestCase):
    def run_it(self, entry, outcomes):
        calls, logs = [], []

        def rerun():
            calls.append(1)
            ok = outcomes.pop(0)
            if not ok:          # кайра монтаж да окшош чыкты → QA кайра жокко чыгарат
                entry.pop("edit_brief", None)
                entry["rejected_briefs"].append({"name": "again", "reason": "окшош"})
            else:
                entry["edit_brief"] = {"name": "new"}
            return FakeState(not ok)

        st = ci.auto_rework(None, FakeState(True), entry, rerun, logs.append)
        return st, calls, logs

    def test_rework_once_then_success(self):
        entry = {"rejected_briefs": [{"name": "copy", "reason": "монтаж концепциясы окшош"}]}
        st, calls, logs = self.run_it(entry, [True])
        self.assertEqual(len(calls), 1)
        self.assertEqual(st.status("s9_qa"), "done")
        self.assertEqual(entry["reworks"], 1)
        self.assertIn("кайра монтаж №1", logs[0])
        self.assertEqual(entry["rework_log"][0]["reason"]["name"], "copy")

    def test_stops_after_max(self):
        entry = {"rejected_briefs": [{"name": "c", "reason": "x"}]}
        st, calls, _ = self.run_it(entry, [False, False, False])
        self.assertEqual(len(calls), ci.MAX_REWORKS)
        self.assertEqual(st.status("s9_qa"), FAILED)

    def test_no_rework_for_other_failures(self):
        entry = {"edit_brief": {"name": "ok"}}                      # концепция жокко чыгарылган эмес
        st, calls, _ = self.run_it(entry, [True])
        self.assertEqual(calls, [])
        st, calls, _ = ci.auto_rework(None, FakeState(False), {"rejected_briefs": [{}]}, lambda: 1 / 0,
                                      lambda m: None), [], None
        self.assertEqual(st.status("s9_qa"), "done")


if __name__ == "__main__":
    unittest.main()


class TestReworkFrom(unittest.TestCase):
    def test_duplicate_frames_restart_from_visuals(self):
        from types import SimpleNamespace
        from pathlib import Path
        import tempfile
        from pipeline import edit_concept as ec

        reg = {"videos": {"V": {"edit_brief": {"name": "a"}}}}
        ctx = SimpleNamespace(registry=reg, video_id="V", path=lambda *p: Path(tempfile.mkdtemp()).joinpath(*p))
        ec.reject(ctx, "монтаж окшош")
        self.assertEqual(reg["videos"]["V"]["rework_from"], "s4_subtitles")
        reg["videos"]["V"]["edit_brief"] = {"name": "b"}
        ec.reject(ctx, "кадрлар окшош", "s5_visuals")                       # клиптердин өзү окшош → жаңы клиптер
        self.assertEqual(reg["videos"]["V"]["rework_from"], "s5_visuals")
        reg["videos"]["V"]["edit_brief"] = {"name": "c"}
        ec.reject(ctx, "монтаж", "s4_subtitles")                             # эртерээк этап сакталат
        self.assertEqual(reg["videos"]["V"]["rework_from"], "s5_visuals")
