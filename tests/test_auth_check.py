"""OAuth текшерүүнүн талдоо логикасынын тесттери (тармаксыз)."""

import unittest

from pipeline.auth_check import analyze_token_response

SCOPE = "https://www.googleapis.com/auth/drive"


class TestAnalyze(unittest.TestCase):
    def test_production_token_has_no_expiry_field(self):
        r = analyze_token_response({"access_token": "x", "expires_in": 3599, "scope": SCOPE,
                                    "token_type": "Bearer"})
        self.assertTrue(r["ok"])
        self.assertIsNone(r["refresh_token_expires_in_sec"])
        self.assertIn("PRODUCTION", r["mode"])
        self.assertEqual(r["scopes"], [SCOPE])

    def test_testing_token_has_seven_day_expiry(self):
        r = analyze_token_response({"access_token": "x", "expires_in": 3599, "scope": SCOPE,
                                    "refresh_token_expires_in": 604799})
        self.assertIn("TESTING", r["mode"])
        self.assertEqual(r["refresh_token_expires_in_days"], 7.0)

    def test_invalid_grant(self):
        r = analyze_token_response({"error": "invalid_grant",
                                    "error_description": "Token has been expired or revoked."})
        self.assertFalse(r["ok"])
        self.assertEqual(r["error"], "invalid_grant")
        self.assertNotIn("access_token", r)

    def test_no_secrets_in_result(self):
        r = analyze_token_response({"access_token": "SECRET-ACCESS", "scope": SCOPE})
        self.assertNotIn("SECRET-ACCESS", str(r))


if __name__ == "__main__":
    unittest.main()
