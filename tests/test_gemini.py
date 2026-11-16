"""Gemini ороочусунун тесттери (тармаксыз)."""

import unittest

from pipeline.errors import StageError, TransientError
from pipeline.gemini import Gemini, parse_json, quota_info


class E(Exception):
    def __init__(self, msg, code):
        super().__init__(msg)
        self.code = code


RPM = E("429 RESOURCE_EXHAUSTED. please check your plan and billing details. "
        "'quotaId': 'GenerateRequestsPerMinutePerProjectPerModel-FreeTier' 'retryDelay': '37s'", 429)
RPD = E("429 RESOURCE_EXHAUSTED. 'quotaId': 'GenerateRequestsPerDayPerProjectPerModel-FreeTier'", 429)


def make():
    waits = []
    g = Gemini("k", text_models=["a", "b"], tts_models=[], client=object(),
               log=lambda m: None, sleep=waits.append)
    return g, waits


class TestQuota(unittest.TestCase):
    def test_quota_info(self):
        self.assertFalse(quota_info(RPM)["per_day"])
        self.assertEqual(quota_info(RPM)["delay"], 37.0)
        self.assertTrue(quota_info(RPD)["per_day"])

    def test_per_minute_waits_and_retries_same_model(self):
        g, waits = make()
        calls = []

        def fn(m):
            calls.append(m)
            if len(calls) <= 2:
                raise RPM
            return "ok"
        self.assertEqual(g._call(["a", "b"], fn, "t"), "ok")
        self.assertEqual(calls, ["a", "a", "a"])
        self.assertEqual(waits, [39.0, 39.0])

    def test_daily_quota_falls_back_and_skips(self):
        g, _ = make()
        fn = lambda m: (_ for _ in ()).throw(RPD) if m == "a" else "b-ok"  # noqa: E731
        self.assertEqual(g._call(["a", "b"], fn, "t"), "b-ok")
        self.assertIn("a", g.skip_until)

    def test_bad_request_is_not_transient(self):
        g, _ = make()
        with self.assertRaises(StageError) as cm:
            g._call(["a"], lambda m: (_ for _ in ()).throw(E("400 bad", 400)), "t")
        self.assertNotIsInstance(cm.exception, TransientError)

    def test_503_transient(self):
        g, _ = make()
        with self.assertRaises(TransientError):
            g._call(["a"], lambda m: (_ for _ in ()).throw(E("503", 503)), "t")

    def test_parse_json(self):
        self.assertEqual(parse_json('```json\n[1, 2]\n```'), [1, 2])
        self.assertEqual(parse_json('Ответ: {"a": 1} спасибо'), {"a": 1})


if __name__ == "__main__":
    unittest.main()
