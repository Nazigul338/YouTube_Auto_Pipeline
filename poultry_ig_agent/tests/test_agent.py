import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import config  # noqa: E402
import agent  # noqa: E402
import lint  # noqa: E402


def fake(prompt):
    if '"items"' in prompt:
        return {"items": [{"day": 1, "pillar": "motivation", "format": "carousel", "topic": "Эрте туруу", "angle": "x"},
                          {"day": 2, "pillar": "daily_life", "format": "reel", "topic": "Эртең", "angle": "y"}]}
    if "slides" in prompt:
        return {"hook": "Тоок эрте турат", "caption": "Сиз качан турасыз?", "hashtags": ["#ферма"],
                "slides": [{"title": f"T{i}", "body": "Бир сүйлөм."} for i in range(6)]}
    return {"hook": "Таң атты", "voiceover": "Таң атты, ферма ойгонду.", "caption": "Сизде кандай?", "hashtags": ["#ферма"], "shots": ["a"]}


class T(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        config.OUT_DIR = self.tmp

    def test_flow(self):
        agent.cmd_plan(2, fake)
        ids = agent.cmd_make(2, fake)
        self.assertEqual(len(ids), 2)
        self.assertTrue(os.path.exists(os.path.join(self.tmp, ids[0], "slide_01.png")))
        agent.set_status(ids[0], "approved")
        self.assertIn("approved", [s for _, s in agent.cmd_list()])

    def test_lint_blocks(self):
        bad = {"format": "reel", "hook": "h", "voiceover": "AI менен 80% өсөт", "caption": "c", "hashtags": []}
        self.assertTrue(lint.lint_post(bad))

    def test_needs_fix_cannot_approve(self):
        def bad(_):
            return {"hook": "h", "voiceover": "автоматташтыруу", "caption": "c", "hashtags": []}
        pid = agent.save_post(agent.make_post({"format": "reel", "pillar": "motivation", "topic": "t"}, bad))
        with self.assertRaises(SystemExit):
            agent.set_status(pid, "approved")


if __name__ == "__main__":
    unittest.main()
