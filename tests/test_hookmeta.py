import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from pipeline import hookmeta


def ctx_with(meta, script="Знаешь это ощущение, что жизнь где-то там, за поворотом? Вот второе предложение."):
    d = Path(tempfile.mkdtemp())
    (d / "script").mkdir()
    (d / "script" / "script.txt").write_text(script, encoding="utf-8")
    if meta is not None:
        (d / "script" / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    return SimpleNamespace(path=lambda *p: d.joinpath(*p)), d


class TestEnsure(unittest.TestCase):
    def test_backfills_old_project(self):
        ctx, d = ctx_with({"title": "T", "words": 10})
        with mock.patch.dict(os.environ, {"VIDEO_HOOK_CARD": "настоящая жизнь — за поворотом?"}):
            m = hookmeta.ensure(ctx)
        self.assertEqual(m["hook_type"], "question")
        self.assertTrue(m["hook"].endswith("за поворотом?"))
        self.assertEqual(m["hook_card"], "НАСТОЯЩАЯ ЖИЗНЬ — ЗА ПОВОРОТОМ?")
        self.assertEqual(json.loads((d / "script" / "meta.json").read_text(encoding="utf-8"))["title"], "T")

    def test_keeps_existing_values(self):
        full = {"hook": "A?", "hook_type": "scenario", "hook_card": "КАРТОЧКА"}
        ctx, _ = ctx_with(full)
        with mock.patch.dict(os.environ, {"VIDEO_HOOK_CARD": "ДРУГОЕ"}):
            self.assertEqual(hookmeta.ensure(ctx), full)

    def test_default_card_and_no_script(self):
        ctx, _ = ctx_with({}, script="Это утверждение без вопроса. Дальше.")
        with mock.patch.dict(os.environ, {"VIDEO_HOOK_CARD": ""}):
            m = hookmeta.ensure(ctx)
        self.assertEqual(m["hook_type"], "statement")
        self.assertEqual(m["hook_card"], "ЭТО УТВЕРЖДЕНИЕ БЕЗ ВОПРОСА.")


if __name__ == "__main__":
    unittest.main()
