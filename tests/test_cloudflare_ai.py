"""Cloudflare Workers AI клиенти (жалган HTTP менен; чыныгы API'ге суроо жиберилбейт)."""
import base64
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from pipeline import cf_probe, cloudflare_ai as cfa

TOKEN, ACC = "tok_SECRET_123", "acc_SECRET_456"


def tiny_jpeg(w=1024, h=1024) -> bytes:
    sof = b"\xff\xc0\x00\x11\x08" + h.to_bytes(2, "big") + w.to_bytes(2, "big") + b"\x03" + b"\x00" * 9
    return b"\xff\xd8" + b"\xff\xe0\x00\x10" + b"JFIF\x00" + b"\x00" * 9 + sof + b"\x00" * 20000 + b"\xff\xd9"


class FakeHTTP:
    """urllib.request.urlopen'дун ордуна: жолго жараша жооп берет, суроолорду эсептейт."""

    def __init__(self, run_status=200, run_payload=None):
        self.calls = []
        self.run_status = run_status
        self.run_payload = run_payload

    def __call__(self, req, timeout=None):
        url = req.full_url
        self.calls.append((req.get_method(), url, req.data))
        if "/tokens/verify" in url:
            return self._ok({"success": True, "result": {"status": "active"}})
        if "/ai/models/search" in url:
            return self._ok({"success": True, "result": [{"name": cfa.FLUX_MODEL, "task": {"name": "Text-to-Image"}}]})
        if "/ai/run/" in url:
            p = self.run_payload or {"success": True,
                                     "result": {"image": base64.b64encode(tiny_jpeg()).decode()}}
            if self.run_status != 200:
                import io
                import urllib.error
                raise urllib.error.HTTPError(url, self.run_status, "err", {}, io.BytesIO(json.dumps(p).encode()))
            return self._ok(p)
        raise AssertionError(url)

    @staticmethod
    def _ok(payload):
        r = mock.MagicMock()
        r.status = 200
        r.read.return_value = json.dumps(payload).encode()
        r.__enter__.return_value = r
        return r


class TestCloudflareAI(unittest.TestCase):
    def test_from_env_missing(self):
        with mock.patch.dict(os.environ, {"CLOUDFLARE_API_TOKEN": "", "CLOUDFLARE_ACCOUNT_ID": ""}):
            self.assertIsNone(cfa.CloudflareAI.from_env())

    def test_probe_happy_path_one_image(self):
        fake = FakeHTTP()
        env = {"CLOUDFLARE_API_TOKEN": TOKEN, "CLOUDFLARE_ACCOUNT_ID": ACC}
        logs = []
        with mock.patch.dict(os.environ, env), mock.patch("urllib.request.urlopen", fake), \
                tempfile.TemporaryDirectory() as d:
            res = cf_probe.run(Path(d), logs.append)
            self.assertTrue(res["ok"])
            self.assertEqual(res["image"]["size"], (1024, 1024))
            self.assertTrue((Path(d) / "flux_test.jpg").exists())
        runs = [c for c in fake.calls if "/ai/run/" in c[1]]
        self.assertEqual(len(runs), 1)                       # бир гана сүрөт
        self.assertEqual(json.loads(runs[0][2])["steps"], 4)
        blob = json.dumps(res) + "\n".join(logs)
        self.assertNotIn(TOKEN, blob)
        self.assertNotIn(ACC, blob)

    def test_max_images_guard(self):
        cf = cfa.CloudflareAI(TOKEN, ACC, max_images=1)
        with mock.patch("urllib.request.urlopen", FakeHTTP()):
            cf.generate_image("x")
            with self.assertRaises(cfa.CloudflareError):
                cf.generate_image("y")

    def test_quota_no_retry_and_secrets_hidden(self):
        payload = {"success": False, "errors": [{"code": 3036, "message": f"daily free allocation used for {ACC}"}]}
        fake = FakeHTTP(run_status=429, run_payload=payload)
        cf = cfa.CloudflareAI(TOKEN, ACC)
        with mock.patch("urllib.request.urlopen", fake):
            with self.assertRaises(cfa.QuotaError) as e:
                cf.generate_image("x")
        self.assertNotIn(ACC, str(e.exception))
        self.assertEqual(len([c for c in fake.calls if "/ai/run/" in c[1]]), 1)   # кайра аракет жок

    def test_network_error_hides_url(self):
        def boom(req, timeout=None):
            raise OSError(f"cannot reach {req.full_url}")
        cf = cfa.CloudflareAI(TOKEN, ACC)
        with mock.patch("urllib.request.urlopen", boom):
            with self.assertRaises(cfa.CloudflareError) as e:
                cf.model_info()
        self.assertNotIn(ACC, str(e.exception))

    def test_jpeg_size(self):
        self.assertEqual(cf_probe.jpeg_size(tiny_jpeg(800, 600)), (800, 600))
        self.assertIsNone(cf_probe.jpeg_size(b"PNG..."))


if __name__ == "__main__":
    unittest.main()
