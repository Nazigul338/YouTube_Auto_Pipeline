import json
import os
import tempfile
import unittest

from poultry_ig_agent import analytics, config, instagram, publisher
from poultry_ig_agent.tests.helpers import tmp_out


class FakeTx:
    def __init__(self, fail_container=None):
        self.calls, self.n, self.fail = [], 0, fail_container

    def __call__(self, method, url, params=None, data=None, headers=None):
        self.calls.append((method, url, params, data, headers))
        if url.endswith("/media") and method == "POST":
            self.n += 1
            return {"id": f"c{self.n}"}
        if "status_code" in (params or {}).get("fields", ""):
            return {"status_code": self.fail or "FINISHED"}
        if url.endswith("/media_publish"):
            return {"id": "M1"}
        if url.endswith("/comments"):
            return {"data": [{"id": "k1", "text": "Курс канча?"}, {"id": "k2", "text": "супер"}]}
        if url.endswith("/media") and method == "GET":
            return {"data": []}
        if url.endswith("/insights"):
            return {"data": [{"values": [{"value": 7}]}]}
        return {"data": [], "id": "ok"}


def client(tx=None):
    return instagram.InstagramClient("TOK", "17841", "v23.0", tx or FakeTx(), sleep=lambda s: None)


class IG(unittest.TestCase):
    def test_requires_credentials(self):
        os.environ.pop("POULTRY_IG_ACCESS_TOKEN", None)
        with self.assertRaises(instagram.IGError):
            instagram.InstagramClient()

    def test_reel_by_url(self):
        tx = FakeTx(); c = client(tx)
        self.assertEqual(c.publish_reel("cap", video_url="https://x/v.mp4"), "M1")
        self.assertEqual(tx.calls[0][2]["media_type"], "REELS")
        self.assertIn("media_publish", tx.calls[-1][1])

    def test_reel_resumable_upload(self):
        tx = FakeTx(); c = client(tx)
        f = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False); f.write(b"1234"); f.close()
        c.publish_reel("cap", video_path=f.name)
        up = [x for x in tx.calls if "rupload" in x[1]][0]
        self.assertEqual(up[4]["file_size"], "4"); self.assertTrue(up[4]["Authorization"].startswith("OAuth"))

    def test_reel_needs_exactly_one_source(self):
        with self.assertRaises(instagram.IGError):
            client().publish_reel("c")

    def test_container_error_raises(self):
        with self.assertRaises(instagram.IGError):
            client(FakeTx("ERROR")).publish_photo("https://x/i.jpg", "c")

    def test_carousel_limits(self):
        with self.assertRaises(instagram.IGError):
            client().publish_carousel(["a"], "c")
        self.assertEqual(client().publish_carousel(["https://a", "https://b"], "c"), "M1")

    def test_comments_and_insights(self):
        c = client()
        self.assertEqual(len(c.list_comments("m")), 2)
        self.assertEqual(c.media_insights("m")["views"], 7)

    def test_token_never_logged(self):
        def boom(*a, **k):
            raise instagram.IGError("bad token TOK here")
        tmp_out()
        with self.assertLogs("poultry", "ERROR") as cm:
            with self.assertRaises(instagram.IGError):
                client(boom)._call("GET", "x")
        self.assertNotIn("TOK", "".join(cm.output))


class Gate(unittest.TestCase):
    def setUp(self):
        self.out = tmp_out()
        self.d = os.path.join(self.out, "p"); os.makedirs(self.d)
        self.post = {"id": "p", "format": "carousel", "caption": "c", "hashtags": ["#a"], "lint_issues": [], "status": "pending_review"}

    def test_unapproved_blocked(self):
        with self.assertRaises(PermissionError):
            publisher.publish(self.post, self.d, None, False)

    def test_approved_is_dry_run_by_default(self):
        self.post["status"] = "approved"
        r = publisher.publish(self.post, self.d, client(), live=True)   # settings.publish_live=false → dry-run
        self.assertTrue(r["dry_run"])

    def test_live_counts_manual_publishes(self):
        self.post["status"] = "approved"
        os.environ["POULTRY_SETTINGS_FILE"] = _settings(publish_live=True)
        r = publisher.publish(self.post, self.d, client(), True, {"images": ["https://a", "https://b"]})
        self.assertFalse(r["dry_run"])
        self.assertEqual(publisher.load_state()["approved_publishes"], 1)
        os.environ.pop("POULTRY_SETTINGS_FILE")

    def test_autopilot_conditions(self):
        os.environ["POULTRY_SETTINGS_FILE"] = _settings(autopilot={"enabled": True, "required_approved_publishes": 2})
        self.assertFalse(publisher.autopilot_allowed(self.post)[0])          # азырынча 0 жарыялоо
        st = {"approved_publishes": 2, "published": []}
        self.assertTrue(publisher.autopilot_allowed(self.post, state=st)[0])
        self.assertFalse(publisher.autopilot_allowed({**self.post, "needs_vet_review": True}, state=st)[0])
        self.assertFalse(publisher.autopilot_allowed({**self.post, "lint_issues": ["x"]}, state=st)[0])
        os.environ.pop("POULTRY_SETTINGS_FILE")

    def test_autopilot_off_by_default(self):
        self.assertFalse(publisher.autopilot_allowed(self.post, state={"approved_publishes": 99, "published": []})[0])

    def test_reel_without_video_refused(self):
        self.post.update(format="reel", status="approved")
        with self.assertRaises(PermissionError):
            publisher.publish(self.post, self.d, None, False)


def _settings(**over):
    fd, p = tempfile.mkstemp(suffix=".json")
    with os.fdopen(fd, "w") as f:
        json.dump(over, f)
    return p


class Analytics(unittest.TestCase):
    def test_report(self):
        rows = [{"id": str(i), "caption": f"v{i}", "type": "REELS", "views": 100 * i, "saved": i, "shares": i % 3, "follows": i % 2} for i in range(1, 8)]
        rows[3]["leads"] = 2
        txt = analytics.build_report(rows, {"1": {"purpose": "sales", "lang": "ky"}}, "2026-11-17")
        for s in ("Эң көп көрүлгөн", "Эң көп сакталган", "Кардар кызыгуусу", "Кийинки жумага", "v7"):
            self.assertIn(s, txt)

    def test_few_rows_no_conclusions(self):
        self.assertIn("аз", analytics.build_report([{"id": "1", "caption": "a", "views": 1}])) 

    def test_leads_from_comments(self):
        rows = analytics.count_leads(client(), [{"id": "m"}])
        self.assertEqual(rows[0]["leads"], 1)


if __name__ == "__main__":
    unittest.main()
