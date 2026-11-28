"""Cloudflare сүрөт модулу (cf_images / cf_image_probe) — жалган HTTP; чыныгы API'ге суроо жиберилбейт."""
import base64
import io
import json
import os
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

from pipeline import cf_budget as cb, cf_image_probe as probe, cf_images as ci, cloudflare_ai as cfa
from tests.test_cloudflare_ai import ACC, TOKEN, tiny_jpeg

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR" + (1344).to_bytes(4, "big") + (768).to_bytes(4, "big") + b"\x00" * 100

LUCID = "@cf/leonardo/lucid-origin"
FLUX2 = "@cf/black-forest-labs/flux-2-dev"
SCHEMAS = {
    LUCID: {"input": {"properties": {"prompt": {"type": "string"}, "width": {"type": "integer", "maximum": 2500},
                                      "height": {"type": "integer", "maximum": 2500},
                                      "num_steps": {"type": "integer", "maximum": 40}, "seed": {"type": "integer"}}}},
    FLUX2: {"input": {"properties": {"multipart": {"properties": {"body": {"properties": {
        "prompt": {"type": "string"}, "width": {"type": "integer", "maximum": 1024},
        "height": {"type": "integer", "maximum": 1024}, "steps": {"type": "integer", "maximum": 50}}}}}}}},
    cfa.FLUX_MODEL: {"input": {"properties": {"prompt": {"type": "string"},
                                               "steps": {"type": "integer", "maximum": 8}}}},
}


class Fake:
    def __init__(self, models=(LUCID, cfa.FLUX_MODEL), raw_png=False, run_status=200):
        self.models, self.raw_png, self.run_status = models, raw_png, run_status
        self.calls = []

    def __call__(self, req, timeout=None):
        url = req.full_url
        self.calls.append((req.get_method(), url, req.data, dict(req.header_items())))
        if "/tokens/verify" in url:
            return self._json({"success": True, "result": {"status": "active"}})
        if "/ai/models/search" in url:
            return self._json({"success": True, "result": [
                {"name": m, "description": "d", "properties": [{"property_id": "price", "value": [{"unit": "per tile"}]}]}
                for m in self.models]})
        if "/ai/models/schema" in url:
            name = url.split("model=")[1].replace("%40", "@").replace("%2F", "/")
            return self._json({"success": True, "result": SCHEMAS.get(name, {})})
        if url.endswith("/graphql"):
            return self._json({"data": None, "errors": [{"message": "not authorized"}]})
        if "/ai/run/" in url:
            if self.run_status != 200:
                raise urllib.error.HTTPError(url, self.run_status, "x", {"Content-Type": "application/json"},
                                             io.BytesIO(json.dumps({"success": False, "errors": [
                                                 {"code": 10000, "message": "Authentication error"}]}).encode()))
            if self.raw_png:
                return self._raw(PNG, "image/png")
            return self._json({"success": True, "result": {"image": base64.b64encode(tiny_jpeg(1344, 768)).decode()}})
        raise AssertionError(url)

    def _json(self, p):
        return self._raw(json.dumps(p).encode(), "application/json")

    @staticmethod
    def _raw(data, ctype):
        r = mock.MagicMock()
        r.status = 200
        r.read.return_value = data
        r.headers = {"Content-Type": ctype}
        r.__enter__.return_value = r
        return r


class TestInputs(unittest.TestCase):
    def test_only_schema_fields_and_limits(self):
        sp = ci.input_spec(SCHEMAS[LUCID])
        self.assertFalse(sp["multipart"])
        self.assertEqual(ci.build_inputs(sp, "p", 1344, 768, 60), {"prompt": "p", "width": 1344, "height": 768,
                                                                    "num_steps": 40})

    def test_multipart_schema(self):
        sp = ci.input_spec(SCHEMAS[FLUX2])
        self.assertTrue(sp["multipart"])
        self.assertEqual(ci.build_inputs(sp, "p", 1344, 768, None), {"prompt": "p", "width": 1024, "height": 768})

    def test_flux_schnell_has_no_size(self):
        sp = ci.input_spec(SCHEMAS[cfa.FLUX_MODEL])
        self.assertEqual(ci.build_inputs(sp, "p", 1344, 768, 4), {"prompt": "p", "steps": 4})

    def test_pick_prefers_quality(self):
        self.assertEqual(ci.pick_model([cfa.FLUX_MODEL, LUCID]), LUCID)
        self.assertIsNone(ci.pick_model([cfa.FLUX_MODEL], "@cf/x/none"))


class TestProbe(unittest.TestCase):
    def run_probe(self, fake, mode, model="", drive=None):
        logs = []
        with tempfile.TemporaryDirectory() as d, \
                mock.patch.dict(os.environ, {"CLOUDFLARE_API_TOKEN": TOKEN, "CLOUDFLARE_ACCOUNT_ID": ACC}), \
                mock.patch("urllib.request.urlopen", fake):
            res = probe.run(Path(d), mode, model, logs.append, drive=drive,
                            store=cb.LedgerStore(None, local=Path(d) / "l.json"), wait=0, poll=0, sleep=lambda s: None)
            files = sorted(x.name for x in Path(d).iterdir())
        blob = json.dumps(res, ensure_ascii=False) + "\n".join(logs)
        self.assertNotIn(TOKEN, blob)
        self.assertNotIn(ACC, blob)
        return res, logs, files

    def test_models_mode_generates_nothing(self):
        fake = Fake()
        res, logs, files = self.run_probe(fake, "models")
        self.assertTrue(res["ok"])
        self.assertTrue(res["account_id_ok"])
        self.assertFalse(res["perm_analytics_read"])
        self.assertFalse([c for c in fake.calls if "/ai/run/" in c[1]])
        self.assertIn("models.md", files)

    def test_image_mode_one_request_and_drive(self):
        fake = Fake()
        drive = mock.Mock()
        drive.ensure_path.return_value = "FOLDER"
        drive.upload_file.return_value = "FILE"
        res, logs, files = self.run_probe(fake, "image", drive=drive)
        self.assertTrue(res["ok"], logs)
        runs = [c for c in fake.calls if "/ai/run/" in c[1]]
        self.assertEqual(len(runs), 1)
        self.assertIn(LUCID, runs[0][1])
        self.assertEqual(json.loads(runs[0][2])["width"], 1344)
        drive.ensure_path.assert_called_once_with(*probe.TEST_FOLDER)
        self.assertEqual(res["image"]["size"], (1344, 768))
        self.assertEqual(drive.upload_file.call_count, 2)                       # сүрөт + json

    def test_raw_png_response(self):
        res, logs, files = self.run_probe(Fake(raw_png=True), "image")
        self.assertTrue(res["ok"], logs)
        self.assertTrue(any(f.endswith(".png") for f in files))

    def test_auth_error_no_retry(self):
        fake = Fake(run_status=403)
        res, logs, _ = self.run_probe(fake, "image")
        self.assertFalse(res["ok"])
        self.assertEqual(len([c for c in fake.calls if "/ai/run/" in c[1]]), 1)

    def test_multipart_request(self):
        fake = Fake(models=(FLUX2,))
        res, logs, _ = self.run_probe(fake, "image")
        self.assertTrue(res["ok"], logs)
        run = next(c for c in fake.calls if "/ai/run/" in c[1])
        self.assertIn("multipart/form-data", run[3].get("Content-type", ""))
        self.assertIn(b'name="prompt"', run[2])


if __name__ == "__main__":
    unittest.main()
