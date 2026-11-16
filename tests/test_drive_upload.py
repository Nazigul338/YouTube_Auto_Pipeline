"""Drive жүктөөсүнүн ишенимдүүлүгү: чоң файлда тармак таймауту болсо жүктөө кайра башталат."""

import tempfile
import unittest
from pathlib import Path

from pipeline.drive import DriveClient
from pipeline.errors import TransientError


class FakeReq:
    def __init__(self, behaviours):
        self.b = behaviours

    def next_chunk(self, num_retries=0):
        act = self.b.pop(0)
        if isinstance(act, Exception):
            raise act
        return None, act


def client():
    c = object.__new__(DriveClient)
    return c


class TestResumable(unittest.TestCase):
    def test_retries_after_timeout_and_succeeds(self):
        calls = []

        def make():
            calls.append(1)
            # 1-аракет: таймаут; 2-аракет: таймаут; 3-аракет: ийгилик
            plans = [[TimeoutError("The read operation timed out")], [ConnectionResetError()], [{"id": "F1"}]]
            return FakeReq(plans[len(calls) - 1])
        sleeps = []
        self.assertEqual(client()._resumable(make, "final.mp4", sleep=sleeps.append), "F1")
        self.assertEqual(len(calls), 3)
        self.assertEqual(sleeps, [10, 20])

    def test_gives_up_with_transient_error(self):
        def make():
            return FakeReq([TimeoutError("x")])
        with self.assertRaises(TransientError) as cm:
            client()._resumable(make, "final.mp4", tries=3, sleep=lambda s: None)
        self.assertIn("final.mp4", str(cm.exception))
        self.assertIn("TimeoutError", str(cm.exception))

    def test_non_network_error_is_not_swallowed(self):
        def make():
            return FakeReq([ValueError("bug")])
        with self.assertRaises(ValueError):
            client()._resumable(make, "f", sleep=lambda s: None)


if __name__ == "__main__":
    unittest.main()
