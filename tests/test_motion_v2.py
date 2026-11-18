"""Камера кыймылы v2 (cinematic СЫНАК): ар түр иштейт, өлчөгүч аныктайт, тандоо мааниге/ар түрдүүлүккө баш ийет."""

import random
import subprocess
import tempfile
import unittest
from pathlib import Path

from pipeline import motion


class TestBuildAndMeasure(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.d = Path(cls.tmp.name)
        png = cls.d / "still.png"
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=1280x720", "-frames:v", "1",
                        str(png)], check=True)
        cls.src = cls.d / "still.mp4"
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-loop", "1", "-framerate", "30", "-t", "4", "-i", str(png),
                        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(cls.src)], check=True)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def render(self, name):
        out = self.d / f"{name}.mp4"
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(self.src), "-vf", motion.build(name, 3.0, 1.0, 5),
                        "-t", "3", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(out)], check=True)
        return out

    def test_every_type_moves_and_is_detected(self):
        for name in motion.TYPES:
            out = self.render(name)
            r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height",
                                "-of", "csv=p=0", str(out)], capture_output=True, text=True).stdout.strip()
            self.assertEqual(r, "1920,1080", name)
            det = motion.classify(motion.measure(out, 3.0))
            self.assertNotEqual(det, "static", name)
            self.assertTrue(motion.matches(f"v2:{name}@5", det), (name, det))

    def test_static_clip_is_flagged(self):
        det = motion.classify(motion.measure(self.src, 3.0))
        self.assertEqual(det, "static")
        self.assertFalse(motion.matches("v2:zoom_in@1", det))

    def test_parse(self):
        self.assertEqual(motion.parse("v2:ken_burns@42"), ("ken_burns", 42))


class TestPlan(unittest.TestCase):
    def shots(self, n=160, per_scene=4, kinds=None):
        return [{"i": k, "scene": k // per_scene + 1, "kind": (kinds or {}).get(k, "video")} for k in range(n)]

    def test_variety_and_limits(self):
        scenes = {s: {"emotion": e} for s, e in zip(range(1, 41), ["calm", "tense", "hopeful", "sad"] * 10)}
        plan = motion.plan_motions(self.shots(), scenes, random.Random(1))
        names = [motion.parse(p["motion"])[0] for p in plan]
        self.assertTrue(all(a != b for a, b in zip(names, names[1:])))        # кошуна кадрлар кайталанбайт
        self.assertGreaterEqual(len(set(names)), 7)
        self.assertLessEqual(max(names.count(t) for t in set(names)) / len(names), motion.MAX_SHARE + 0.01)

    def test_emotion_steers_choice(self):
        shots = self.shots(80, per_scene=4)
        tense = motion.plan_motions(shots, {s: {"emotion": "tense"} for s in range(1, 21)}, random.Random(2))
        calm = motion.plan_motions(shots, {s: {"emotion": "calm"} for s in range(1, 21)}, random.Random(2))
        cnt = lambda p, t: sum(motion.parse(x["motion"])[0] == t for x in p)
        self.assertGreater(cnt(tense, "handheld"), cnt(calm, "handheld"))
        self.assertGreater(cnt(calm, "pan_right") + cnt(calm, "pan_left"), cnt(tense, "pan_right") + cnt(tense, "pan_left"))

    def test_lateral_direction_consistent_in_scene(self):
        plan = motion.plan_motions(self.shots(200, per_scene=5), {s: {"emotion": "calm"} for s in range(1, 41)},
                                   random.Random(3))
        by_scene = {}
        for sh, p in zip(self.shots(200, per_scene=5), plan):
            n = motion.parse(p["motion"])[0]
            if n in motion.LATERAL:
                by_scene.setdefault(sh["scene"], set()).add(n)
        self.assertTrue(all(len(v) == 1 for v in by_scene.values()))

    def test_images_get_ken_burns_family(self):
        plan = motion.plan_motions(self.shots(10, kinds={k: "image" for k in range(10)}),
                                   {s: {"emotion": "calm"} for s in range(1, 4)}, random.Random(4))
        self.assertTrue(all(motion.parse(p["motion"])[0] in ("ken_burns", "zoom_in", "zoom_out", "dolly", "dolly_out")
                            for p in plan))


if __name__ == "__main__":
    unittest.main()
