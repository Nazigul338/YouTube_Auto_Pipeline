"""Сахналарды өтүүлөр менен бириктирүү (s8.stitch) — чыныгы FFmpeg, кичине клиптер.

Контекст: GitHub runner'де (FFmpeg 8.0.1) 8 кирүүлүү xfade графы 94.9 сек ордуна 17.6 сек берген
(Video_001, топ 0/1), ал эми `trim+concat` запас жолу 3600 сек илинип калган. Кирүү файлдар таза болгон
(PTS туура). Чечим: чоң граф жок — ар сегмент 1–2 кирүүлүү кичине ffmpeg, кадр-так, акыры concat -c copy.
"""

import subprocess
import tempfile
import unittest
from pathlib import Path

from pipeline import media
from pipeline.stages import s8_render as s8


def make_scene(path: Path, frames: int, color: str):
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
                    f"color=c={color}:s=320x180:r=30", "-frames:v", str(frames), "-c:v", "libx264",
                    "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-r", "30", str(path)], check=True)


def nframes(path: Path) -> int:
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-count_packets",
                        "-show_entries", "stream=nb_read_packets", "-of", "csv=p=0", str(path)],
                       capture_output=True, text=True)
    return int(r.stdout.strip().rstrip(","))


class TestPlan(unittest.TestCase):
    def test_total_and_continuity(self):
        durs = [12.12, 9.38, 6.84, 16.98]
        tr = [{"type": "dissolve", "dur": 0.5}, {"type": "smoothright", "dur": 0.5},
              {"type": "cut", "dur": 0.0}]
        plan = s8.plan_segments(durs, tr)
        want = sum(durs) - 0.5 - 0.5 - 0.04
        self.assertAlmostEqual(plan["total_frames"] / 30, want, delta=0.05)
        self.assertEqual(sum(s["frames"] for s in plan["segments"]), plan["total_frames"])
        # cut (1 кадр) өзүнчө сегмент эмес — body'ге кошулат (run #44898457854: 1 кадрлык mp4 монтажды токтоткон)
        self.assertEqual([s["kind"] for s in plan["segments"]],
                         ["body", "trans", "body", "trans", "body", "body"])
        self.assertTrue(all(s["frames"] >= 2 for s in plan["segments"] if s["kind"] == "trans"))

    def test_no_drift_over_many_scenes(self):
        durs = [8.37 + (k % 5) * 1.713 for k in range(50)]
        tr = [{"type": "dissolve", "dur": 0.5}] * 49
        plan = s8.plan_segments(durs, tr)
        self.assertAlmostEqual(plan["total_frames"] / 30, sum(durs) - 49 * 0.5, delta=0.04)

    def test_single_scene(self):
        plan = s8.plan_segments([5.0], [])
        self.assertEqual([(s["kind"], s["frames"]) for s in plan["segments"]], [("body", 150)])


class TestStitch(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def scenes(self, frames):
        files = []
        for k, (n, c) in enumerate(zip(frames, ["red", "green", "blue", "yellow", "white", "purple"])):
            f = self.d / f"s{k}.mp4"
            make_scene(f, n, c)
            files.append(f)
        return files

    def test_exact_frames_with_dissolve_and_smoothright(self):
        files = self.scenes([135, 105, 150])                     # 4.5, 3.5, 5.0 сек
        durs = [4.5, 3.5, 5.0]
        tr = [{"type": "dissolve", "dur": 0.5}, {"type": "smoothright", "dur": 0.5}]
        out, dbg = self.d / "o.mp4", []
        dur, frames = s8.stitch(files, durs, tr, self.d, out, dbg)
        self.assertEqual(frames, 135 + 105 + 150 - 30)
        self.assertEqual(nframes(out), frames)
        self.assertAlmostEqual(s8.video_len(out), dur, delta=0.15)
        self.assertEqual(dbg[0]["cut_fallbacks"], [])

    def test_source_files_slightly_short_do_not_shorten_result(self):
        """Реалдуу файлдар 1–2 кадр кыска (362 vs 363.6) — жылыш топтолбойт, сызык так."""
        files = self.scenes([133, 103, 148, 100])                # план: 4.5, 3.5, 5.0, 3.4 сек
        durs = [4.5, 3.5, 5.0, 3.4]
        tr = [{"type": "dissolve", "dur": 0.5}] * 3
        out = self.d / "o.mp4"
        dur, frames = s8.stitch(files, durs, tr, self.d, out, [])
        self.assertAlmostEqual(frames / 30, sum(durs) - 1.5, delta=0.04)
        self.assertEqual(nframes(out), frames)

    def test_cut_transition_and_many_scenes(self):
        files = self.scenes([90] * 6)
        durs = [3.0] * 6
        tr = [{"type": "cut", "dur": 0.0}, {"type": "dissolve", "dur": 0.5}] * 2 + [{"type": "cut", "dur": 0}]
        out = self.d / "o.mp4"
        dur, frames = s8.stitch(files, durs, tr, self.d, out, [])
        self.assertEqual(nframes(out), frames)
        self.assertAlmostEqual(frames / 30, 18.0 - 3 * 0.04 - 2 * 0.5, delta=0.05)

    def test_broken_transition_falls_back_to_cut_same_length(self):
        files = self.scenes([120, 120])
        tr = [{"type": "no_such_transition", "dur": 0.5}]
        out, dbg = self.d / "o.mp4", []
        dur, frames = s8.stitch(files, [4.0, 4.0], tr, self.d, out, dbg)
        self.assertEqual(nframes(out), frames)
        self.assertEqual(len(dbg[0]["cut_fallbacks"]), 1)

    def test_render_shot_normalizes_color_tags_across_clips(self):
        """Ар башка түс белгилүү клиптер → бирдей белгилүү кадрлар (FFmpeg 8 кадр жоготпосун)."""
        specs = {"none": [], "bt601": ["-colorspace", "smpte170m", "-color_primaries", "smpte170m",
                                       "-color_trc", "smpte170m"],
                 "pc": ["-vf", "format=yuvj420p", "-color_range", "pc"]}
        tags = set()
        for name, extra in specs.items():
            clip = self.d / f"c_{name}.mp4"
            subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
                            "testsrc2=size=640x360:rate=30:duration=6", "-c:v", "libx264", "-preset",
                            "ultrafast", *([] if "-vf" in extra else ["-pix_fmt", "yuv420p"]), *extra,
                            str(clip)], check=True)
            out = self.d / f"shot_{name}.mp4"
            s8.render_shot(clip, out, "video", 0.5, 2.0, "zoom_in", 1.0)
            r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                                "stream=color_space,color_range,color_primaries,color_transfer,pix_fmt",
                                "-of", "csv=p=0", str(out)], capture_output=True, text=True)
            tags.add(r.stdout.strip())
        self.assertEqual(len(tags), 1, tags)
        self.assertIn("bt709", tags.pop())

    def test_pts_summary(self):
        f = self.scenes([135])[0]
        s = s8.pts_summary(f)
        self.assertTrue(s["monotonic"])
        self.assertAlmostEqual(s["last_pts"], 4.5 - 1 / 30, delta=0.05)


if __name__ == "__main__":
    unittest.main()
