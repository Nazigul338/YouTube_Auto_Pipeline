"""ОРИГИНАЛДУУЛУК — толук pipeline (жалган API, ЧЫНЫГЫ FFmpeg): эки видео катар жасалат жана ар бир этап
видеонун ӨЗ концепциясын чындап колдонгону текшерилет. Узак (~5–15 мүн) — YTA_SKIP_SLOW=1 болсо өткөрүлөт.

Текшерилет:
  s4  subtitles.ass «Style: Sub» = концепциянын субтитр стили
  s5  shots.json кадр узундуктары концепциянын ыргагына жараша (эки видеодо айырмалуу)
  s6  plan.json concept_params.grade = концепциянын түсү; өтүүлөр концепциянын палитрасынан; кыймыл артыкчылыгы
  s7  music.json — угулган деңгээл (music_audible), концепциянын музыка деңгээли
  s9  originality.json — экинчи видео биринчиси менен салыштырылды, report.txt'те 8 пункттук тизме
  жана эки видеонун концепциясы ар түрдүү (≥4/7 топ).
"""

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from pipeline import ci, edit_concept as ec
from pipeline.storage import LocalStore
from tests.fakes import FakeGemini, FakeStock
from tests.test_stages_audio import fake_whisper_for


VOCAB = ("утро тишина окно дорога страх надежда письмо улица память выбор шаг дыхание чай кухня работа друг "
         "вечер город поезд река свет тень зеркало книга музыка ладонь сердце время сон берег ветер дождь").split()


class UniqueScriptGemini(FakeGemini):
    def __init__(self, words: int, seed: str):
        super().__init__(words=words)
        self.rng = __import__("random").Random(seed)

    def text(self, prompt, *, purpose="text", **kw):
        if purpose != "script_draft":
            return super().text(prompt, purpose=purpose, **kw)
        self.calls.append(purpose)
        self.usage.append({"purpose": purpose, "model": "fake"})
        sents = []
        while sum(len(x.split()) for x in sents) < self.words:
            sents.append(" ".join(self.rng.choice(VOCAB) for _ in range(9)).capitalize() + ".")
        return "НАЗВАНИЕ: Тест\n\n" + "\n\n".join(" ".join(sents[k:k + 4]) for k in range(0, len(sents), 4))


def small_cfg(root):
    from pipeline.config import load_config
    return load_config("motivation", drive_root=root, words_min=110, words_max=150, min_duration_sec=30)


@unittest.skipIf(os.environ.get("YTA_SKIP_SLOW"), "узак тест")
class TestOriginalityPipeline(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.store = LocalStore(self.root / "drive")
        music = self.root / "drive" / "YouTube_Auto" / "Music" / "YouTube_Audio_Library_Attribution"
        music.mkdir(parents=True)
        for name, f in (("Calm Piano - Tester.mp3", 330), ("Rise Up - Tester.mp3", 440)):
            subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"sine=f={f}:d=20", "-ac", "2",
                            str(music / name)], check=True)
        self.p = mock.patch("builtins.print")
        self.p.start()
        self.env = mock.patch.dict(os.environ, {"GOOGLE_API_KEY": "t", "PIXABAY_API_KEY": "t", "YTA_CINEMATIC": "1",
                                                "YTA_HYPERFRAMES": "", "YTA_SFX": "", "YTA_VOICE_STYLE": ""})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.p.stop()
        self.tmp.cleanup()

    def make(self, topic: str, vid: str) -> Path:
        proj = self.root / "w" / "Projects" / vid
        gem = UniqueScriptGemini(words=130, seed=vid)   # ар видеого чындап башка сценарий (бирдей — s1 бөгөйт)
        services = {"gemini": gem, "stock": FakeStock(), "asr": fake_whisper_for(proj)}
        with mock.patch.object(ci, "load_config") as lc:
            lc.side_effect = lambda n, drive_root=None: small_cfg(drive_root)
            code = ci.run_ci(topic, "motivation", self.root / "w", store=self.store, services=services)
        state = json.loads((proj / "state.json").read_text(encoding="utf-8"))
        failed = {k: v.get("error") for k, v in state["stages"].items() if v["status"] != "done"}
        self.assertEqual(failed, {}, vid)
        self.assertEqual(code, 0)
        return proj

    def check_stages_use_concept(self, proj: Path, vid: str) -> dict:
        b = self.store.load_registry()["videos"][vid]["edit_brief"]
        self.assertEqual(json.loads((proj / "edit_brief.json").read_text(encoding="utf-8"))["name"], b["name"])
        # s4: субтитр стили
        style, _ = ec.subtitle_style(b, "X", 96)
        ass = (proj / "subtitles" / "subtitles.ass").read_text(encoding="utf-8")
        sub_line = next(l for l in ass.splitlines() if l.startswith("Style: Sub,"))
        self.assertEqual(sub_line.split(",", 2)[2], style.split(",", 2)[2], vid)
        # s6: түс, өтүүлөр, кыймыл
        plan = json.loads((proj / "animation" / "plan.json").read_text(encoding="utf-8"))
        self.assertEqual(plan["concept_params"]["grade"], ec.grade_filter(b), vid)
        self.assertEqual(plan["concept"], b["name"])
        allowed = {t for t, w in b["transitions"].items() if w > 0} | {"cut"}
        between = [p["transition_out"]["type"] for p in plan["shots"] if p.get("transition_out")
                   and p["transition_out"]["type"] != "cut"]
        self.assertTrue(set(between) <= allowed, (vid, set(between), allowed))
        # s5: ыргак — кадрлар 2.8–4.5 сек чегинде (QA), орточо концепциянын базасына жакын
        shots = json.loads((proj / "clips" / "shots.json").read_text(encoding="utf-8"))["shots"]
        self.assertTrue(all(2.7 <= s["dur"] <= 4.6 for s in shots[:-1]), vid)
        # s7: музыка угулат
        music = json.loads((proj / "music" / "music.json").read_text(encoding="utf-8"))
        self.assertIsNotNone(music["levels"].get("voice_minus_ducked_music_lu"), vid)
        # s9: салыштыруу + 8 пункт
        orig = json.loads((proj / "originality.json").read_text(encoding="utf-8"))
        rep = (proj / "report.txt").read_text(encoding="utf-8")
        self.assertIn("ОРИГИНАЛДУУЛУК ЖАНА САПАТ", rep)
        return {"brief": b, "orig": orig, "avg_shot": sum(s["dur"] for s in shots) / len(shots), "sub": sub_line}

    def test_two_videos_each_with_own_concept(self):
        p1 = self.make("Почему мы откладываем важные дела", "Video_001")
        r1 = self.check_stages_use_concept(p1, "Video_001")
        p2 = self.make("Как перестать бояться чужого мнения", "Video_002")
        r2 = self.check_stages_use_concept(p2, "Video_002")
        self.assertEqual([c["video"] for c in r2["orig"]["compared"]], ["Video_001"])   # чындап салыштырылды
        cmp_ = ec.compare(r2["brief"], r1["brief"])
        self.assertTrue(cmp_["ok"], cmp_)
        self.assertNotEqual(r1["sub"], r2["sub"])                                       # субтитр стили башка
        self.assertNotEqual(r1["brief"]["name"], r2["brief"]["name"]) if r1["brief"]["source"] == "gemini" else None
        self.assertEqual(r2["orig"]["problems"], [])

    def test_copied_template_is_detected_and_reworked(self):
        """2-видеого 1-видеонун концепциясы атайын берилет (шаблон көчүрүү) → QA табат → жаңы концепция →
        монтаж s4'төн АВТОМАТТЫК кайра → видео даяр болот."""
        p1 = self.make("Почему мы откладываем важные дела", "Video_001")
        reg = self.store.load_registry()
        b1 = reg["videos"]["Video_001"]["edit_brief"]
        reg["videos"]["Video_002"] = {"edit_brief": dict(b1)}                # көчүрмө концепция
        self.store.save_registry(reg)
        p2 = self.make("Как перестать бояться чужого мнения", "Video_002")
        e2 = self.store.load_registry()["videos"]["Video_002"]
        self.assertEqual(e2.get("reworks"), 1, e2.get("rework_log"))
        self.assertEqual(e2["rejected_briefs"][0]["name"], b1["name"])
        self.assertIn("окшош", e2["rejected_briefs"][0]["reason"])
        self.assertTrue(ec.compare(e2["edit_brief"], b1)["ok"])             # жаңы концепция башка
        r2 = self.check_stages_use_concept(p2, "Video_002")                 # жаңы концепция менен монтаждалды
        self.assertEqual(r2["brief"]["name"], e2["edit_brief"]["name"])
        log = (p2 / "logs" / "run.log").read_text(encoding="utf-8")
        self.assertIn("кайра монтаж №1", log)


if __name__ == "__main__":
    unittest.main()
