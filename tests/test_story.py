"""Кино-окуя форматы: каарман, сюжет, актылар, кино-разбивка, continuity, музыкалык арка, QA (жалган Gemini)."""

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from pipeline import continuity, story
from pipeline.config import load_config
from tests.fakes import FakeGemini


class TestGenerators(unittest.TestCase):
    def test_profile_and_outline(self):
        g = FakeGemini()
        hero = story.character_profile(g, "Почему ты не можешь расслабиться", [], "тревожный, всё контролирует")
        self.assertEqual(hero["gender"], "woman")
        self.assertIn("woman", hero["descriptor"])
        o = story.outline(g, "t", hero, [], lambda *_: None)
        self.assertEqual([a["act"] for a in o["acts"]], story.ACT_KEYS)
        self.assertIn(o["logline"], story.outline_text(o))

    def test_previous_hero_name_is_avoided(self):
        g = FakeGemini()
        first = story.character_profile(g, "t", [])
        second = story.character_profile(g, "t", [{"id": "Video_005", "name": first["name"]}])
        self.assertNotEqual(first["name"], second["name"])

    def test_similar_plot_is_rewritten(self):
        g = FakeGemini()
        hero = story.character_profile(g, "t", [])
        o1 = story.outline(g, "t", hero, [], lambda *_: None)
        prev = [dict(story.registry_entry(hero, o1, "T"), id="Video_005")]
        logs = []
        calls = []
        real = g.json

        def same_then_new(prompt, purpose="", **kw):        # 1-жолу ошол эле сюжет, 2-жолу башкасы
            calls.append(purpose)
            if purpose == "story_outline" and calls.count("story_outline") == 1:
                return {"logline": o1["logline"], "acts": [dict(a) for a in o1["acts"]],
                        "turning_point": o1["turning_point"]}
            if purpose == "story_outline":
                return {"logline": "Совсем другая история про отца и сына на рыбалке у озера.",
                        "acts": [{"act": k, "summary": f"Озеро, лодка, молчание {k}"} for k in story.ACT_KEYS],
                        "turning_point": "сын сам заводит мотор"}
            return real(prompt, purpose=purpose, **kw)
        g.json = same_then_new
        o2 = story.outline(g, "t", hero, prev, logs.append)
        self.assertTrue(any("окшош" in l for l in logs), logs)
        self.assertLess(o2["plot_similarity"], story.PLOT_SIMILAR)

    def test_map_acts_exact_and_fallback(self):
        text = " ".join(f"w{i}" for i in range(700))
        starts = [0, 50, 150, 330, 470, 580, 660]
        g = SimpleNamespace(json=lambda *a, **k: [{"act": k, "starts": " ".join(f"w{j}" for j in range(s, s + 6))}
                                                   for k, s in zip(story.ACT_KEYS, starts)])
        acts = story.map_acts(g, text)
        self.assertEqual([a["w0"] for a in acts], starts)
        self.assertEqual(acts[0]["method"], "gemini")
        fb = story.map_acts(SimpleNamespace(json=lambda *a, **k: []), text)
        self.assertEqual((len(fb), fb[0]["method"]), (7, "proportional"))

    def test_structure_and_text_checks(self):
        words = [{"w": "x", "s": i * 0.7, "e": i * 0.7 + 0.6} for i in range(700)]
        fb = story.map_acts(SimpleNamespace(json=lambda *a, **k: []), " ".join("x" for _ in range(700)))
        times = story.act_times(fb, words)
        self.assertEqual(story.check_structure(times, 490), [])
        bad = [dict(t) for t in times]
        bad[0]["end"] = 60
        self.assertTrue(any("hook" in p for p in story.check_structure(bad, 490)))
        self.assertTrue(story.check_text("Это реальная история. У неё тревожное расстройство."))
        self.assertEqual(story.check_text("Анна закрывает ноутбук и смотрит в окно."), [])


class TestActFillAndPeak(unittest.TestCase):
    def test_missing_final_message_is_filled(self):
        sents = [f"Предложение номер {i} идет дальше." for i in range(240)]
        text = " ".join(sents)
        w = text.split()
        marks = {"hook": 0, "introduction": 50, "conflict": 150, "development": 450,
                 "turning_point": 650, "transformation": 760}
        resp = [{"act": k, "starts": " ".join(w[i:i + 4])} for k, i in marks.items()]
        g = SimpleNamespace(json=lambda *a, **k: resp)
        acts = story.map_acts(g, text)
        self.assertEqual([a["act"] for a in acts], story.ACT_KEYS)
        self.assertEqual(acts[0]["method"], "gemini+fill")
        fm = acts[-1]
        self.assertGreater(fm["w0"], 760)
        self.assertTrue(w[fm["w0"] - 1].endswith("."))      # сүйлөмдүн башынан
        self.assertEqual(acts[1]["w0"], 50)                  # Gemini белгилегендер өзгөргөн жок

    def test_filled_act_not_too_short_with_quotes(self):
        sents = [f"Он{i} сказал{i}: «Пойдем{i} дальше{i} {i}.»" for i in range(200)]
        text = " ".join(sents)
        w = text.split()
        marks = {"hook": 0, "introduction": 40, "conflict": 150, "development": 400,
                 "turning_point": 560, "transformation": 700}
        resp = [{"act": k, "starts": " ".join(w[i:i + 4])} for k, i in marks.items()]
        acts = story.map_acts(SimpleNamespace(json=lambda *a, **k: resp), text)
        fm = acts[-1]
        self.assertEqual(fm["act"], "final_message")
        self.assertGreaterEqual(fm["w1"] - fm["w0"], int(0.05 * len(w)))
        self.assertGreaterEqual(fm["w0"] - acts[-2]["w0"], int(0.05 * len(w)))
        self.assertTrue(w[fm["w0"] - 1].endswith(".»"))

    def test_true_peak_limited(self):
        from pipeline import media
        d = Path(tempfile.mkdtemp())
        try:
            p = d / "hot.wav"
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
                            "aevalsrc='0.32*sin(2*PI*220*t)+if(lt(mod(t\\,3)\\,0.02)\\,1.2*sin(2*PI*5000*t)\\,0)':d=8",
                            "-ar", "48000", "-ac", "2", "-c:a", "pcm_f32le", str(p)], check=True)
            self.assertGreater(media.loudness(p)["TP"], -1.0)
            r = media.limit_true_peak(p, p)
            self.assertLessEqual(r["TP"], media.TP_CEILING)
            self.assertGreaterEqual(r["limited"], 1)
        finally:
            shutil.rmtree(d, ignore_errors=True)


class TestHookAndDark(unittest.TestCase):
    def test_tighten_hook_shortens_only_hook(self):
        long_hook = "Тиканье часов в пустой квартире звучит как отсчет до самого настоящего взрыва. " + "слово " * 70
        rest = " ".join(f"r{i}" for i in range(900))
        text = long_hook + rest
        n_hook = len(long_hook.split())

        def acts_for(t):
            w = t.split()
            k = w.index("r0")
            step = (len(w) - k) // 6
            starts = [0] + [k + step * j for j in range(6)]
            return [{"act": a, "w0": s, "w1": (starts[j + 1] if j < 6 else len(w)), "method": "gemini"}
                    for j, (a, s) in enumerate(zip(story.ACT_KEYS, starts))]
        g = SimpleNamespace(text=lambda *a, **k: "Часы тикают как бомба. Алексей не спит третью ночь подряд.")
        with mock.patch.object(story, "map_acts", lambda g_, t: acts_for(t)):
            self.assertTrue(story.hook_problems(text, acts_for(text)))
            logs = []
            new, acts = story.tighten_hook(g, text, acts_for(text), logs.append)
        self.assertTrue(new.startswith("Часы тикают как бомба."))
        self.assertTrue(new.endswith(rest))
        self.assertEqual(story.hook_problems(new, acts), [])
        self.assertLess(len(new.split()), len(text.split()))
        self.assertTrue(any("Hook кыскартылды" in l for l in logs), logs)
        self.assertGreater(n_hook, 50)

    def test_dark_seconds(self):
        from pipeline.stages.s5_visuals import dark_seconds

        d = Path(tempfile.mkdtemp())
        try:
            clip = d / "c.mp4"
            subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "color=c=black:s=320x180:d=2",
                            "-f", "lavfi", "-i", "testsrc=s=320x180:d=2", "-filter_complex", "[0][1]concat=n=2[v]",
                            "-map", "[v]", str(clip)], check=True)
            self.assertGreaterEqual(dark_seconds(clip, 0, 2), 1.5)
            self.assertLess(dark_seconds(clip, 2.2, 1.5), 0.4)
        finally:
            shutil.rmtree(d, ignore_errors=True)


class TestAdjustLength(unittest.TestCase):
    def test_worse_rewrite_is_rejected(self):
        from pipeline.stages.s1_script import adjust_length

        replies = iter([" ".join(["слово"] * 1224), " ".join(["слово"] * 759), " ".join(["слово"] * 1180)])
        g = SimpleNamespace(text=lambda *a, **k: next(replies))
        out = adjust_length(g, " ".join(["слово"] * 1075), 1100, 1200, lambda *_: None)
        self.assertEqual(len(out.split()), 1180)       # 759 кабыл алынбайт


class TestContinuity(unittest.TestCase):
    def test_faceless_check_replaces_visible_face_and_wrong_gender(self):
        d = Path(tempfile.mkdtemp())
        try:
            (d / "script").mkdir()
            (d / "clips").mkdir()
            (d / "script" / "story.json").write_text(json.dumps({"hero": {"descriptor": "man 30s", "gender": "man",
                                                                          "look": {}}}))
            scenes = {1: {"hero": "back", "detail_query": "hands phone"}, 2: {"hero": "none"}}
            shots = [{"scene": 1, "dur": 3}, {"scene": 1, "dur": 3}, {"scene": 1, "dur": 3}, {"scene": 2, "dur": 3}]
            A = SimpleNamespace
            results = [(i, A(kind="video"), d / f"{i}.mp4", 10.0, "fresh", 0.0) for i in range(4)]
            gem = A(judge_image=lambda imgs, prompt, purpose="": [
                {"i": 0, "face": False, "gender": "man"}, {"i": 1, "face": True, "gender": "man"},
                {"i": 2, "face": False, "gender": "woman"}])
            chosen = {i: ("old", "fresh", 0.0) for i in range(4)}
            finder = A(beat_candidate=lambda q, dur: f"new:{q}")
            fetched = []

            def fetch(i):
                fetched.append((i, chosen[i][0]))
                return (i, A(kind="video"), d / f"n{i}.mp4", 10.0, "fresh", 0.0)
            stage = A(_frame=lambda path, kind, off, dur: b"jpg")
            ctx = A(path=lambda *p: d.joinpath(*p), services={"gemini": gem})
            out, st = continuity.enforce(stage, ctx, results, shots, scenes, chosen, {}, finder, fetch,
                                         lambda i: 0.5, lambda real, dur, u: 0.0)
            self.assertEqual(st["checked"], 3)               # «none» сахнасы текшерилбейт
            self.assertEqual((st["faces"], st["wrong_gender"]), (1, 1))
            self.assertEqual(fetched, [(1, "new:hands phone"), (2, "new:hands phone")])
            self.assertEqual((st["consistent"], st["replaced"], st["rate"]), (1, 2, 1.0))
            self.assertTrue((d / "clips" / "continuity.json").exists())
        finally:
            shutil.rmtree(d, ignore_errors=True)


class TestMusicArcAndConfig(unittest.TestCase):
    def test_arc_filter_runs_in_ffmpeg(self):
        from pipeline.stages.s7_music import arc_filter

        f = arc_filter([(0, 5, 1.0), (5, 10, -1.5)])[1:]
        subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=d=10", "-af", f, "-f", "null", "-"],
                       check=True)
        self.assertEqual(arc_filter(None), "")

    def test_niche_and_voice(self):
        cfg = load_config("psych_story")
        self.assertTrue(story.is_story(cfg))
        self.assertFalse(story.is_story(load_config("motivation")))
        from pipeline import voice_style

        self.assertIn("short cinematic", voice_style.direction([], story=True))
        self.assertNotIn("short cinematic", voice_style.direction([]))


@unittest.skipIf(os.environ.get("YTA_SKIP_SLOW"), "узак тест")
class TestStoryPipeline(unittest.TestCase):
    """Толук pipeline кино-окуя форматында (жалган API, ЧЫНЫГЫ FFmpeg)."""

    def test_story_video(self):
        from pipeline import ci
        from pipeline.storage import LocalStore
        from tests.fakes import FakeStock
        from tests.test_originality_pipeline import UniqueScriptGemini
        from tests.test_stages_audio import fake_whisper_for

        tmp = Path(tempfile.mkdtemp())
        try:
            store = LocalStore(tmp / "drive")
            music = tmp / "drive" / "YouTube_Auto" / "Music" / "YouTube_Audio_Library_Attribution"
            music.mkdir(parents=True)
            subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "sine=f=330:d=20", "-ac", "2",
                            str(music / "Calm Piano - Tester.mp3")], check=True)
            proj = tmp / "w" / "Projects" / "Video_001"

            class G(UniqueScriptGemini):
                def judge_image(self, imgs, prompt, purpose=""):
                    n = len(imgs) if isinstance(imgs, list) else 1
                    if purpose == "continuity_faceless":
                        return [{"i": k, "face": k % 4 == 1, "gender": "woman"} for k in range(n)]
                    return {}
            services = {"gemini": G(words=130, seed="s"), "stock": FakeStock(), "asr": fake_whisper_for(proj)}
            env = {"GOOGLE_API_KEY": "t", "PIXABAY_API_KEY": "t", "YTA_CINEMATIC": "1", "YTA_HYPERFRAMES": "",
                   "YTA_SFX": "", "YTA_VOICE_STYLE": "", "VIDEO_HERO": "тревожная, всё контролирует"}
            with mock.patch.dict(os.environ, env), mock.patch("builtins.print"), \
                    mock.patch.object(ci, "load_config") as lc:
                lc.side_effect = lambda n, drive_root=None: load_config(
                    n, drive_root=drive_root, words_min=110, words_max=150, min_duration_sec=30)
                code = ci.run_ci("Почему ты не можешь расслабиться", "psych_story", tmp / "w", store=store,
                                 services=services)
            state = json.loads((proj / "state.json").read_text(encoding="utf-8"))
            failed = {k: v.get("error") for k, v in state["stages"].items() if v["status"] != "done"}
            self.assertEqual(failed, {})
            self.assertEqual(code, 0)
            e = store.load_registry()["videos"]["Video_001"]
            self.assertEqual(e["format"], "story")
            self.assertEqual(e["story"]["gender"], "woman")
            sc = json.loads((proj / "scenes.json").read_text(encoding="utf-8"))["scenes"]
            self.assertTrue(all(s.get("act") in story.ACT_KEYS and s.get("shot") for s in sc))
            cont = json.loads((proj / "clips" / "continuity.json").read_text(encoding="utf-8"))
            self.assertGreater(cont["checked"], 0)
            self.assertGreaterEqual(cont["rate"], 0.8)
            music_j = json.loads((proj / "music" / "music.json").read_text(encoding="utf-8"))
            self.assertEqual(len(music_j["arc"]), 7)
            rep = json.loads((proj / "report.json").read_text(encoding="utf-8")) if (proj / "report.json").exists() else {}
            desc = (proj / "youtube_description.txt").read_text(encoding="utf-8")
            self.assertIn("вымышлены", desc)
            self.assertIn("## 8. Кино-окуя", (proj / "production_report.md").read_text(encoding="utf-8"))
            self.assertIsNotNone(rep)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
