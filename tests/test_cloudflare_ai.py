"""Cloudflare Workers AI клиенти (жалган HTTP менен; чыныгы API'ге суроо жиберилбейт)."""
import base64
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from datetime import datetime, timezone

from pipeline import cf_budget as cb, cf_probe, cloudflare_ai as cfa

TOKEN, ACC = "tok_SECRET_123", "acc_SECRET_456"


def tiny_jpeg(w=1024, h=1024) -> bytes:
    sof = b"\xff\xc0\x00\x11\x08" + h.to_bytes(2, "big") + w.to_bytes(2, "big") + b"\x03" + b"\x00" * 9
    return b"\xff\xd8" + b"\xff\xe0\x00\x10" + b"JFIF\x00" + b"\x00" * 9 + sof + b"\x00" * 20000 + b"\xff\xd9"


class FakeHTTP:
    """urllib.request.urlopen'дун ордуна: жолго жараша жооп берет, суроолорду эсептейт."""

    def __init__(self, run_status=200, run_payload=None, analytics=True, per_image=57.6):
        self.calls = []
        self.run_status = run_status
        self.run_payload = run_payload
        self.analytics = analytics
        self.per_image = per_image
        self.flux_done = 0

    def __call__(self, req, timeout=None):
        url = req.full_url
        self.calls.append((req.get_method(), url, req.data))
        if "/tokens/verify" in url:
            return self._ok({"success": True, "result": {"status": "active"}})
        if "/ai/models/search" in url:
            return self._ok({"success": True, "result": [{"name": cfa.FLUX_MODEL, "task": {"name": "Text-to-Image"}}]})
        if url.endswith("/graphql"):
            if not self.analytics:
                return self._ok({"data": None, "errors": [{"message": "not authorized for that account"}]})
            g = [{"count": self.flux_done, "sum": {"totalNeurons": self.flux_done * self.per_image},
                  "dimensions": {"modelId": cfa.FLUX_MODEL}}] if self.flux_done else []
            return self._ok({"data": {"viewer": {"accounts": [{"aiInferenceAdaptiveGroups": g}]}}})
        if "/ai/run/" in url:
            p = self.run_payload or {"success": True,
                                     "result": {"image": base64.b64encode(tiny_jpeg()).decode()}}
            if self.run_status != 200:
                import io
                import urllib.error
                raise urllib.error.HTTPError(url, self.run_status, "err", {}, io.BytesIO(json.dumps(p).encode()))
            self.flux_done += 1
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

    def _probe(self, fake, d, **kw):
        env = {"CLOUDFLARE_API_TOKEN": TOKEN, "CLOUDFLARE_ACCOUNT_ID": ACC}
        logs = []
        store = cb.LedgerStore(None, local=Path(d) / "ledger.json")
        with mock.patch.dict(os.environ, env), mock.patch("urllib.request.urlopen", fake):
            res = cf_probe.run(Path(d), logs.append, store=store, wait=1, poll=0, sleep=lambda s: None, **kw)
        return res, logs, store

    def test_probe_five_images_measured(self):
        fake = FakeHTTP(per_image=58.0)
        with tempfile.TemporaryDirectory() as d:
            res, logs, store = self._probe(fake, d, mode="test", images=9)     # 9 сурады → 5'тен ашпайт
            self.assertTrue(res["ok"], logs)
            self.assertEqual(len(res["images"]), 5)
            self.assertEqual([x["measured"] for x in res["images"]], [58.0] * 5)
            self.assertEqual(res["report"]["used"], 290.0)
            self.assertEqual(res["report"]["avg_source"], "чыныгы (Cloudflare аналитикасы)")
            # (10000 − 290 − 1000) / 58 = 150.17 → 150
            self.assertEqual(res["report"]["estimated_remaining_images"], 150)
            saved = json.loads((Path(d) / "ledger.json").read_text())
            self.assertEqual(len(next(iter(saved["days"].values()))["requests"]), 5)
        runs = [c for c in fake.calls if "/ai/run/" in c[1]]
        self.assertEqual(len(runs), 5)
        self.assertEqual(set(json.loads(runs[0][2])), {"prompt", "steps"})   # схемада seed жок
        blob = json.dumps(res) + "\n".join(logs)
        self.assertNotIn(TOKEN, blob)
        self.assertNotIn(ACC, blob)

    def test_probe_without_analytics_uses_estimate(self):
        with tempfile.TemporaryDirectory() as d:
            res, logs, _ = self._probe(FakeHTTP(analytics=False), d, mode="test", images=2)
            self.assertTrue(res["ok"])
            self.assertFalse(res["analytics"]["ok"])
            self.assertTrue(any("API'ден алуу мүмкүн болбоду" in x for x in logs))
            self.assertEqual(res["report"]["avg_source"], "баалоо (жарыяланган баа)")
            self.assertAlmostEqual(res["report"]["used"], 2 * cb.estimate_neurons())

    def test_status_mode_makes_no_images(self):
        fake = FakeHTTP()
        with tempfile.TemporaryDirectory() as d:
            res, _, _ = self._probe(fake, d, mode="status", images=5)
            self.assertTrue(res["ok"])
        self.assertFalse([c for c in fake.calls if "/ai/run/" in c[1]])

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


class TestBudget(unittest.TestCase):
    def clock(self, h=12, day=24):
        return lambda: datetime(2026, 11, day, h, 0, tzinfo=timezone.utc)

    def test_estimate_and_formula(self):
        self.assertAlmostEqual(cb.estimate_neurons(1024, 1024, 4), 57.6)
        b = cb.Budget({}, now=self.clock())
        b.set_api(1000.0)
        cap = b.capacity()
        self.assertEqual(cap["available"], 8000.0)                       # 10000 − 1000 − 10%
        self.assertEqual(cap["max_images"], int(8000 // 57.6))           # төмөн тегеректөө

    def test_warn_and_hard_stop(self):
        b = cb.Budget({}, now=self.clock())
        b.set_api(8000.0)
        self.assertIsNone(b.check(50))                                   # 8050 < 8100
        b.set_api(8900.0)
        self.assertIn("⚠️", b.check(50))                                 # эрте эскертүү (≥8100)
        with self.assertRaises(cb.BudgetExceeded):
            b.check(150)                                                 # 9050 > 9000 (резерв)
        b.set_api(9990.0)
        with self.assertRaises(cb.BudgetExceeded):
            b.check(1)

    def test_used_is_max_of_local_and_api(self):
        b = cb.Budget({}, now=self.clock())
        b.record(True, 57.6)
        b.set_api(10.0)
        self.assertEqual(b.used(), 57.6)
        b.set_api(500.0)
        self.assertEqual(b.used(), 500.0)

    def test_utc_reset_keeps_history(self):
        data = {}
        b = cb.Budget(data, now=self.clock(23, 24))
        b.record(True, 57.6)
        b2 = cb.Budget(json.loads(json.dumps(b.to_json())), now=self.clock(0, 25))
        self.assertEqual(b2.used(), 0.0)                                 # жаңы күн — нөлдөн
        self.assertIn("2026-11-24", b2.data["days"])                    # тарых сакталды
        self.assertEqual(b2.report()["reset"], "2026-11-26 00:00 UTC")

    def test_failed_request_counts_no_neurons(self):
        b = cb.Budget({}, now=self.clock())
        b.record(False, 57.6, note="HTTP 500")
        self.assertEqual(b.used(), 0.0)
        self.assertEqual(len(b.day()["requests"]), 1)

    def test_video_plan_priorities(self):
        full = cb.plan_video_images(480, 1000)
        self.assertEqual(full["images"], full["full_coverage"])
        self.assertEqual(full["stock_sec"], 0.0)
        few = cb.plan_video_images(480, 8)
        self.assertEqual(few["images"], 8)
        self.assertEqual(few["by_section"]["hook"], 4)                   # hook биринчи (24 сек / 7)
        self.assertEqual(few["by_section"]["story"], 4)                  # анан окуя
        self.assertEqual(few["by_section"]["finale"], 0)
        self.assertEqual(few["by_section"]["practice"], 0)              # акыркы приоритет
        self.assertGreater(few["stock_sec"], 0)                          # калганы Pixabay

    def test_generate_respects_budget(self):
        b = cb.Budget({}, now=self.clock())
        b.set_api(8990.0)
        fake = FakeHTTP()
        cf = cfa.CloudflareAI(TOKEN, ACC)
        with mock.patch("urllib.request.urlopen", fake):
            with self.assertRaises(cb.BudgetExceeded):
                cf.generate_image("x", budget=b)
        self.assertFalse([c for c in fake.calls if "/ai/run/" in c[1]])   # суроо жиберилген жок

    def test_dashboard(self):
        b = cb.Budget({}, now=self.clock())
        b.record(True, 57.6)
        md = cb.dashboard_md(b.report(), cb.plan_video_images(480, 20), b.data["days"])
        for k in ("Бүгүнкү акысыз лимит", "Колдонулду", "Калды", "Бүгүн жаралган сүрөт",
                  "Дагы жаратууга болот", "Колдонулушу"):
            self.assertIn(k, md)


if __name__ == "__main__":
    unittest.main()
