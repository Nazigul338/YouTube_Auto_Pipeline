import unittest

from poultry_ig_agent import calc, niche, safety, sales
from poultry_ig_agent.tests.helpers import course_file
import json

N = niche.get("poultry")


class Safety(unittest.TestCase):
    def test_health_requires_vet_and_trusted_sources(self):
        post = {"lang": "ky", "topic_key": "vaccination", "caption": "Эмдөө жөнүндө", "sources": [{"url": "https://random-blog.com/x"}]}
        safety.ensure_disclaimers(post, N)
        self.assertIn("ветеринар", post["caption"])
        self.assertTrue(post["needs_vet_review"])
        self.assertTrue(any("Ишенимсиз" in i for i in safety.check(post, N)))

    def test_trusted_source_ok_and_missing_source_flagged(self):
        ok = {"lang": "ru", "topic_key": "prevention", "caption": "x", "sources": [{"url": "https://www.woah.org"}]}
        safety.ensure_disclaimers(ok, N)
        self.assertEqual(safety.check(ok, N), [])
        none = {"lang": "ru", "topic_key": "prevention", "caption": "x", "sources": []}
        safety.ensure_disclaimers(none, N)
        self.assertTrue(safety.check(none, N))

    def test_non_health_untouched(self):
        p = {"lang": "ky", "topic_key": "daily", "caption": "Таңкы жумуртка", "hook": "Таң"}
        safety.ensure_disclaimers(p, N)
        self.assertNotIn("needs_vet_review", p)

    def test_domain_suffix_trick_rejected(self):
        self.assertFalse(safety.trusted("https://woah.org.evil.com", N))
        self.assertTrue(safety.trusted("https://agri.state.edu", N))


class Sales(unittest.TestCase):
    def setUp(self):
        self.c = json.load(open(course_file(), encoding="utf-8"))

    def test_price_from_config(self):
        self.assertIn("3000", sales.answer("Курс канча турат?", self.c)["reply"])

    def test_missing_price_hands_off_never_invents(self):
        r = sales.answer("Баасы канча?", {"name": "X", "price": None})
        self.assertTrue(r["needs_human"])
        self.assertNotRegex(r["reply"], r"\d{3,}")

    def test_faq_and_whatsapp(self):
        self.assertIn("сертификат", sales.answer("Сертификат берилеби?", self.c)["reply"])
        self.assertIn("chat.whatsapp.com", sales.invite(self.c))

    def test_unknown_goes_to_human_and_llm_always_needs_human(self):
        r = sales.draft_dm_reply("Салам, бир нерсе сурайын", self.c, "ru", lambda p: {"reply": "ok"})
        self.assertTrue(r["needs_human"])

    def test_sales_post_blocked_without_course(self):
        self.assertTrue(sales.check({"purpose": "sales", "cta": {"text": "x"}}, {"name": None}))

    def test_no_guarantees(self):
        self.assertTrue(sales.check({"purpose": "sales", "cta": {"text": "x"}, "caption": "100% кепилдик"}, self.c))


class Calc(unittest.TestCase):
    P = dict(chicks=100, chick_price=100, feed_price_per_kg=40, feed_per_bird_kg=4, mortality_pct=5, avg_live_weight_kg=2.2,
             sell_price_per_kg=250, other_costs=5000)

    def test_math(self):
        r = calc.compute(self.P)
        self.assertEqual(r["revenue"], round(95 * 2.2 * 250))
        self.assertEqual(r["cost"], 10000 + 16000 + 5000)
        self.assertEqual(r["profit"], r["revenue"] - r["cost"])

    def test_missing_input_refused(self):
        with self.assertRaises(ValueError):
            calc.compute({"chicks": 10})

    def test_post_has_disclaimer(self):
        self.assertTrue(any("кепилдик" in s["body"] or "гарант" in s["body"] for s in calc.to_post(self.P)["slides"]))


if __name__ == "__main__":
    unittest.main()


class AuthorExperience(unittest.TestCase):
    def test_experience_source_accepted_with_disclosure(self):
        p = {"lang": "ky", "topic_key": "chicks", "caption": "Балапандар өлүп калбасын",
             "sources": [{"type": "author_experience", "note": "балапан багуу практикасы"}]}
        safety.ensure_disclaimers(p, N)
        self.assertIn("өз практикасынан", p["caption"])
        self.assertIn("ветеринар", p["caption"])
        self.assertTrue(p["needs_vet_review"])          # адам бекитүүсү дагы эле керек
        self.assertEqual(safety.check(p, N), [])

    def test_experience_without_note_flagged(self):
        p = {"lang": "ky", "topic_key": "chicks", "caption": "Балапандар өлүп калбасын. ветеринар", "sources": [{"type": "author_experience"}]}
        self.assertTrue(safety.check(p, N))
