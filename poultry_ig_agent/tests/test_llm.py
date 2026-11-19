import io
import json
import os
import unittest
import urllib.error
from unittest import mock

from poultry_ig_agent import llm


def ok_response(obj):
    body = json.dumps({"candidates": [{"content": {"parts": [{"text": json.dumps(obj)}]}}]}).encode()
    r = io.BytesIO(body)
    r.__enter__ = lambda s=r: s
    r.__exit__ = lambda *a: False
    return r


class LLM(unittest.TestCase):
    def setUp(self):
        os.environ["POULTRY_GEMINI_API_KEY"] = "test"

    def test_timeout_falls_through_to_next_model(self):
        calls = []

        def fake(req, timeout=None):
            calls.append(req.full_url)
            if "m1" in req.full_url:
                raise TimeoutError("The read operation timed out")
            return ok_response({"a": 1})
        with mock.patch("urllib.request.urlopen", fake), mock.patch("time.sleep"):
            self.assertEqual(llm.generate_json("x", models=("m1", "m2"), retries=1), {"a": 1})
        self.assertEqual(sum("m1" in c for c in calls), 2)       # бир жолу кайра аракет
        self.assertTrue(any("m2" in c for c in calls))

    def test_all_fail_raises_llmerror_not_crash(self):
        def fake(req, timeout=None):
            raise urllib.error.URLError("down")
        with mock.patch("urllib.request.urlopen", fake), mock.patch("time.sleep"):
            with self.assertRaises(llm.LLMError):
                llm.generate_json("x", models=("m1",), retries=0)

    def test_key_not_in_url(self):
        seen = []

        def fake(req, timeout=None):
            seen.append(req.full_url)
            return ok_response({})
        with mock.patch("urllib.request.urlopen", fake):
            llm.generate_json("x", models=("m1",))
        self.assertNotIn("test", seen[0])


if __name__ == "__main__":
    unittest.main()
