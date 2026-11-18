import json
import os
import tempfile
import unittest

from poultry_ig_agent import lint, niche, safety, video


def cfg(**v):
    base = {"provider": "elevenlabs", "elevenlabs_voice_id": "VID", "elevenlabs_model": "eleven_v3",
            "owner_consent_confirmed": True, "disclose_ai_voice": True}
    base.update(v)
    return {"voice": base}


class Voice(unittest.TestCase):
    def test_default_is_gemini(self):
        self.assertIsInstance(video.tts_from_settings({"voice": {"provider": "gemini"}}), video.GeminiTTS)

    def test_elevenlabs_selected_with_consent(self):
        t = video.tts_from_settings(cfg())
        self.assertIsInstance(t, video.ElevenLabsTTS)
        self.assertEqual(t.voice_id, "VID")

    def test_refuses_without_consent(self):
        with self.assertRaises(video.VideoError):
            video.tts_from_settings(cfg(owner_consent_confirmed=False))

    def test_refuses_without_voice_id(self):
        with self.assertRaises(video.VideoError):
            video.tts_from_settings(cfg(elevenlabs_voice_id=None))

    def test_missing_key_errors_not_crashes_silently(self):
        os.environ.pop("POULTRY_ELEVENLABS_API_KEY", None)
        with self.assertRaises(video.VideoError):
            video.tts_from_settings(cfg()).synth("салам", os.path.join(tempfile.mkdtemp(), "v.wav"))

    def test_ai_voice_disclosed_and_not_flagged_by_lint(self):
        p = {"lang": "ky", "caption": "Таң", "ai_voice": True, "topic_key": "daily"}
        safety.ensure_disclaimers(p, niche.get("poultry"))
        self.assertIn("AI", p["caption"])
        self.assertFalse([i for i in lint.lint_post({**p, "format": "story", "hook": "h", "frames": [{"text": "x"}]}) if "Тыюу" in i])

    def test_repo_settings_safe_defaults(self):
        s = json.load(open(os.path.join(os.path.dirname(__file__), "..", "settings.json"), encoding="utf-8"))
        self.assertFalse(s["voice"]["owner_consent_confirmed"])
        self.assertTrue(s["voice"]["disclose_ai_voice"])


if __name__ == "__main__":
    unittest.main()


class FileVoice(unittest.TestCase):
    def test_drive_link_normalized(self):
        self.assertEqual(video.drive_direct("https://drive.google.com/file/d/AbC_12-x/view?usp=sharing"),
                         "https://drive.google.com/uc?export=download&id=AbC_12-x")
        self.assertEqual(video.drive_direct("https://example.com/a.mp3"), "https://example.com/a.mp3")

    def test_file_voice_requires_consent(self):
        with self.assertRaises(video.VideoError):
            video.tts_from_settings({"voice": {"owner_consent_confirmed": False}}, voice_file="x.mp3")

    @unittest.skipUnless(__import__("shutil").which("ffmpeg"), "ffmpeg жок")
    def test_local_file_converted(self):
        import subprocess
        d = tempfile.mkdtemp(); src = os.path.join(d, "akylai.mp3")
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "sine=d=2", src], check=True)
        out = video.tts_from_settings({"voice": {"owner_consent_confirmed": True}}, voice_file=src).synth("", os.path.join(d, "v.wav"))
        self.assertAlmostEqual(video.duration(out), 2, delta=0.2)

    def test_voiceover_txt_written(self):
        from poultry_ig_agent import agent
        from poultry_ig_agent.tests.helpers import shots, tmp_out
        out = tmp_out()
        pid = agent.save_post({"format": "reel", "lang": "ky", "topic": "t", "hook": "h", "voiceover": "Таң атты.", "shots": shots()})
        self.assertEqual(open(os.path.join(out, pid, "voiceover.txt"), encoding="utf-8").read().strip(), "Таң атты.")
