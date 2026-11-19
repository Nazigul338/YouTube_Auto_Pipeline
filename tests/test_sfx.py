"""Sound Effects Library: лицензия капкасы, сценага жараша тандоо, паузага коюу, деңгээл, режим."""

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from pipeline import sfx
from pipeline.errors import StageError
from pipeline.storage import LocalStore, heavy


def ff(*args):
    subprocess.run(["ffmpeg", "-y", "-v", "error", *args], check=True)


def tone(path: Path, dur: float, freq: int = 440, vol: float = 0.5):
    path.parent.mkdir(parents=True, exist_ok=True)
    ff("-f", "lavfi", "-i", f"sine=f={freq}:d={dur}", "-af", f"volume={vol}", "-ar", "48000", str(path))


def meta(cat: str, file: str, **kw) -> dict:
    m = {"title": file, "file": file, "category": cat, "source": "Pixabay",
         "source_url": "https://pixabay.com/sound-effects/x/", "author": "a",
         "license": "Pixabay Content License", "commercial_use": True,
         "verified_by": "owner", "verified_at": "2026-11-19", "tags": [], "mood": []}
    m.update(kw)
    return m


def add(root: Path, cat: str, name: str, dur: float = 1.5, m: dict | None = None, **kw) -> Path:
    p = root / cat / name
    tone(p, dur)
    if m is not False:
        (root / cat / (p.stem + sfx.META_SUFFIX)).write_text(
            json.dumps(m or meta(cat, name, **kw)), encoding="utf-8")
    return p


class Base(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp())
        self.lib = self.d / "drive" / sfx.FOLDER

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)


class TestLicenseGate(Base):
    def test_check_meta(self):
        ok = meta("impact", "a.wav")
        self.assertIsNone(sfx.check_meta(ok, "impact", "a.wav", "x"))
        self.assertIn("metadata.json жок", sfx.check_meta(None, "impact", "a.wav", "x"))
        self.assertIn("толук эмес", sfx.check_meta({**ok, "source_url": ""}, "impact", "a.wav", "x"))
        self.assertIn("commercial_use", sfx.check_meta({**ok, "commercial_use": False}, "impact", "a.wav", "x"))
        self.assertIn("commercial_use", sfx.check_meta({**ok, "commercial_use": "yes"}, "impact", "a.wav", "x"))
        self.assertIn("тизмеде жок", sfx.check_meta({**ok, "license": "ZvukiPro license"}, "impact", "a.wav", "x"))
        self.assertIn("категория", sfx.check_meta(ok, "nature", "a.wav", "x"))
        self.assertIn("sha256", sfx.check_meta({**ok, "sha256": "abc"}, "impact", "a.wav", "x"))
        self.assertIsNone(sfx.check_meta({**ok, "license": " cc0 "}, "impact", "a.wav", "x"))
        self.assertEqual(sfx.license_name("Mixkit Free License"), "Mixkit Free License")

    def test_library_rejects_unverified(self):
        add(self.lib, "impact", "good.wav")
        add(self.lib, "impact", "nometa.wav", m=False)
        add(self.lib, "transitions", "noncom.wav", commercial_use=False)
        add(self.lib, "nature", "zvuki.wav", license="ZvukiPro")
        p = add(self.lib, "cinematic", "changed.wav")
        mp = p.with_name(p.stem + sfx.META_SUFFIX)
        mp.write_text(json.dumps(meta("cinematic", "changed.wav", sha256="0" * 64)), encoding="utf-8")
        (self.lib / "impact" / "notes.txt").write_text("x")
        ok, rej = sfx.load_library(self.lib)
        self.assertEqual([s.rel for s in ok], ["impact/good.wav"])
        self.assertEqual(sorted(r["file"] for r in rej),
                         ["cinematic/changed.wav", "impact/nometa.wav", "nature/zvuki.wav", "transitions/noncom.wav"])
        self.assertEqual(len(ok[0].sha256), 64)
        self.assertTrue(ok[0].license_record()["commercial_use"])

    def test_repo_assets_have_no_audio_and_example_is_valid(self):
        self.assertEqual(sorted(p.name for p in sfx.REPO_ASSETS.iterdir() if p.is_dir()), sorted(sfx.CATEGORIES))
        ex = json.loads((sfx.REPO_ASSETS / "metadata.example.json").read_text(encoding="utf-8"))
        self.assertIsNone(sfx.check_meta(ex, "transitions", "whoosh_soft_01.wav", None))
        self.assertFalse([p for p in sfx.REPO_ASSETS.rglob("*") if p.suffix.lower() in sfx.AUDIO_EXT])


def scene_setup():
    """5 сахна (~20 сек ар бири), сахна чектеринде 0.6 сек пауза, 3-сахнанын ичинде пауза жок."""
    emos = ["calm", "dramatic", "hopeful", "determined", "reflective"]
    scenes = [{"id": i, "emotion": e} for i, e in enumerate(emos)]
    words, st = [], []
    t = 0.0
    for i in range(5):
        st.append({"id": i, "start": round(t, 3)})
        for _ in range(40):
            words.append({"w": "x", "s": round(t, 3), "e": round(t + 0.45, 3)})
            t += 0.5
        t += 0.6        # пауза сахна чегинде
    total = round(t, 3)
    shots = [{"scene": 0, "query": "forest morning", "theme": "nature"},
             {"scene": 4, "query": "man thinking", "theme": "office"}]
    return scenes, {"scenes": st, "words": words}, shots, total


class TestPlan(Base):
    def lib_all(self):
        for c in sfx.CATEGORIES:
            add(self.lib, c, f"{c}_1.wav", dur=2.0, tags=["forest"] if c == "nature" else [])
            add(self.lib, c, f"{c}_2.wav", dur=2.0)
        ok, _ = sfx.load_library(self.lib)
        for s in ok:
            s.meta["_dur"] = 2.0
        return ok

    def test_pauses(self):
        g = sfx.pauses([{"s": 0.5, "e": 1.0}, {"s": 1.2, "e": 2.0}, {"s": 3.0, "e": 3.5}], 4.0)
        self.assertEqual(g, [(0.0, 0.5), (2.0, 3.0), (3.5, 4.0)])
        self.assertEqual(sfx.near_pause(2.4, g), (2.0, 3.0))
        self.assertIsNone(sfx.near_pause(10, g))

    def test_plan_matches_scenes_and_pauses(self):
        scenes, timing, shots, total = scene_setup()
        ev = sfx.plan(scenes, timing, shots, self.lib_all(), total, "Video_001")
        hits = [e for e in ev if e["kind"] == "hit"]
        beds = [e for e in ev if e["kind"] == "bed"]
        self.assertTrue(hits)
        for e in hits:
            a, b = e["pause"]
            self.assertTrue(a <= e["t"] <= b)                   # диктордун паузасында
        by_t = {round(e["t"]): e["category"] for e in hits}
        cats = [e["category"] for e in hits]
        self.assertIn("impact", cats)                          # dramatic/determined
        self.assertTrue({"emotional", "cinematic"} & set(cats))  # hopeful
        self.assertLessEqual(cats.count("impact"), sfx.MAX_IMPACT)
        ts = sorted(e["t"] for e in hits)
        self.assertTrue(all(b - a >= sfx.HIT_SPACING - 1.5 for a, b in zip(ts, ts[1:])), by_t)
        self.assertEqual(beds[0]["category"], "nature")        # 0-сахна: forest
        self.assertTrue(any(e["category"] == "atmosphere" for e in beds))  # reflective
        self.assertLessEqual(sum(e["dur"] for e in beds), total * sfx.BED_SHARE + 1e-6)
        # детерминдүү (кайра иштетүүдө ошол эле план)
        self.assertEqual(ev, sfx.plan(scenes, timing, shots, self.lib_all(), total, "Video_001"))

    def test_no_pause_no_hit_and_empty_library(self):
        scenes, timing, shots, total = scene_setup()
        timing["words"] = [{"w": "x", "s": i * 0.3, "e": i * 0.3 + 0.29} for i in range(int(total / 0.3))]
        ev = sfx.plan(scenes, timing, shots, self.lib_all(), total, "v")
        self.assertFalse([e for e in ev if e["kind"] == "hit"])
        self.assertEqual(sfx.plan(scenes, timing, shots, [], total, "v"), [])


class TestBuildAndMix(Base):
    def ctx(self):
        folder = self.d / "proj"
        for sub in ("audio", "music", "subtitles", "clips"):
            (folder / sub).mkdir(parents=True, exist_ok=True)
        logs = []
        c = SimpleNamespace(folder=folder, path=lambda *p: folder.joinpath(*p), log=logs.append,
                            cfg=SimpleNamespace(drive_root=str(self.d / "drive")), video_id="Video_009",
                            store=None, logs=logs)
        return c

    def prepare(self, c):
        scenes, timing, shots, total = scene_setup()
        c.path("subtitles", "timings.json").write_text(json.dumps(timing))
        c.path("clips", "shots.json").write_text(json.dumps({"total": total, "shots": shots}))
        # диктор: сахна ичинде үн, чектеринде тынчтык
        parts = []
        for i, sc in enumerate(timing["scenes"]):
            a = sc["start"]
            b = timing["scenes"][i + 1]["start"] - 0.6 if i + 1 < 5 else total - 0.6
            parts.append(f"between(t,{a},{b})")
        ff("-f", "lavfi", "-i", f"sine=f=220:d={total}", "-af",
           f"volume='if({'+'.join(parts)},0.6,0)':eval=frame", "-ar", "24000", "-ac", "1",
           str(c.path("audio", "voice.wav")))
        music = self.d / "music.wav"
        tone(music, 10, 330, 0.3)
        return scenes, total, music

    def test_build_mix_levels_and_rebuild(self):
        from pipeline.stages import s7_music

        for cat in sfx.CATEGORIES:
            add(self.lib, cat, f"{cat}.wav", dur=2.0 if cat in sfx.HIT_CATS else 8.0,
                tags=["forest"] if cat == "nature" else [])
        add(self.lib, "impact", "bad.wav", license="Unknown")
        c = self.ctx()
        scenes, total, music = self.prepare(c)
        info = sfx.build_sfx(c, scenes, total)
        self.assertTrue(info["events"])
        self.assertEqual([r["file"] for r in info["rejected"]], ["impact/bad.wav"])
        self.assertNotIn("impact/bad.wav", {e["rel"] for e in info["events"]})
        self.assertTrue(any("четке кагылды: impact/bad.wav" in l for l in c.logs))
        bed, hits = sfx.tracks_for_mix(c, total)
        self.assertTrue(hits.exists())
        lv = s7_music.mix(c, music, total, bed, hits)
        self.assertIsNotNone(lv.get("sfx_hits_lufs"))
        worst = max(v for v in (lv.get("sfx_bed_lufs"), lv["sfx_hits_lufs"]) if v is not None)
        self.assertGreaterEqual(lv["voice_lufs"] - worst, 10)   # эффекттер дикторду баспайт
        out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0",
                              str(c.path("audio", "mix.wav"))], capture_output=True, text=True).stdout
        self.assertAlmostEqual(float(out), total, delta=0.1)
        # жаңы runner: wav'дар жок → sfx.json боюнча кайра түзүлөт
        hits.unlink()
        _, h2 = sfx.tracks_for_mix(c, total)
        self.assertTrue(h2.exists())
        # китепканадагы файл алмашса — так ката
        h2.unlink()
        tone(self.lib / "transitions" / "transitions.wav", 1.0, 900)
        if any(e["rel"] == "transitions/transitions.wav" for e in info["events"]):
            with self.assertRaises(StageError):
                sfx.tracks_for_mix(c, total)

    def test_empty_library_keeps_video(self):
        c = self.ctx()
        scenes, total, _ = self.prepare(c)
        info = sfx.build_sfx(c, scenes, total)
        self.assertEqual(info["events"], [])
        self.assertEqual(sfx.tracks_for_mix(c, total), (None, None))
        self.assertTrue(any("эффектсиз" in l for l in c.logs))


class TestMusicStage(Base):
    ctx = TestBuildAndMix.ctx
    prepare = TestBuildAndMix.prepare

    def run_stage(self, flag: str):
        from pipeline.stages.s7_music import MusicStage

        c = self.ctx()
        scenes, total, _ = self.prepare(c)
        (c.folder / "scenes.json").write_text(json.dumps({"scenes": [
            {**s, "music_mood": "calm", "words": 40} for s in scenes]}))
        mroot = self.d / "drive" / "Music"
        tone(mroot / "Pixabay" / "Calm Piano.mp3", 10, 330, 0.3)
        (mroot / "_tags.json").write_text(json.dumps(
            {"Pixabay/Calm Piano.mp3": {"mood": "calm", "energy": "low", "vocals": False}}))
        c.cfg.music_root = mroot
        c.cfg.niche_data = {"music_moods": ["calm"]}
        c.registry = {"videos": {}}
        c.services = {"gemini": object()}   # тегдер даяр — Gemini чакырылбайт
        c.store = LocalStore(self.d / "local")
        for cat in ("transitions", "impact", "emotional", "nature", "atmosphere"):
            add(self.lib, cat, f"{cat}.wav", dur=2.0 if cat in sfx.HIT_CATS else 8.0)
        with mock.patch.dict(os.environ, {"YTA_SFX": flag}):
            MusicStage().run(c)
        return c, json.loads(c.path("music", "music.json").read_text(encoding="utf-8"))

    def test_stage_with_sfx(self):
        c, info = self.run_stage("1")
        self.assertGreaterEqual(info["levels"]["voice_minus_sfx_lu"], 10)
        self.assertTrue(json.loads(c.path("music", "sfx.json").read_text())["events"])

    def test_stage_without_flag_is_unchanged(self):
        c, info = self.run_stage("")
        self.assertNotIn("voice_minus_sfx_lu", info["levels"])
        self.assertFalse(c.path("music", "sfx.json").exists())
        self.assertFalse(c.path("audio", "sfx_hits.wav").exists())


class TestModeAndStorage(Base):
    def test_enabled_only_in_test(self):
        store = LocalStore(self.d)
        with mock.patch.dict(os.environ, {"YTA_SFX": ""}):
            self.assertFalse(sfx.enabled(store))
        with mock.patch.dict(os.environ, {"YTA_SFX": "1"}):
            self.assertTrue(sfx.enabled(store))
            prod = SimpleNamespace(root_name="YouTube_Auto")
            self.assertFalse(sfx.enabled(prod))
            self.assertIn("Өчүк", sfx.blocked_reason(prod))
            self.assertTrue(sfx.enabled(SimpleNamespace(root_name="YouTube_Auto_TEST")))

    def test_heavy_and_pull(self):
        self.assertTrue(heavy("audio/sfx_bed.wav"))
        self.assertTrue(heavy("audio/sfx_hits.wav"))
        store = LocalStore(self.d)
        add(store.root / sfx.FOLDER, "impact", "a.wav")
        dest = self.d / "runner" / sfx.FOLDER
        self.assertEqual(store.pull_sfx(dest), 2)
        self.assertTrue((dest / "impact" / "a.wav").exists())


if __name__ == "__main__":
    unittest.main()


class TestSynth(unittest.TestCase):
    def test_generated_library_passes_gate_and_loops(self):
        import numpy as np
        import wave

        from pipeline import sfx_synth

        d = Path(tempfile.mkdtemp())
        try:
            items = sfx_synth.generate(d, "2026-11-19")
            ok, rej = sfx.load_library(d)
            self.assertEqual(rej, [])
            self.assertEqual(len(ok), len(sfx_synth.CATALOG))
            self.assertEqual({s.category for s in ok}, set(sfx.CATEGORIES))
            self.assertTrue(all(m["license"] == "CC0 1.0" and m["commercial_use"] for m in items))
            for s in ok:
                m = sfx.measure(s.path)
                self.assertLessEqual(m["peak"], -2.9, s.rel)
                if s.category in sfx.BED_CATS:
                    self.assertGreaterEqual(m["dur"], 10)
                    with wave.open(str(s.path)) as w:
                        a = np.frombuffer(w.readframes(w.getnframes()), "<i2").reshape(-1, 2) / 32768
                    jump = np.max(np.abs(a[0] - a[-1]))
                    step = np.percentile(np.abs(np.diff(a, axis=0)), 99.9)
                    self.assertLessEqual(jump, step * 3 + 1e-3, s.rel)   # loop чеги чыкылдабайт
                else:
                    self.assertLessEqual(m["dur"], 4.0)
            # туруктуу: кайра түзсө — ошол эле файл (sha256 metadata'га дал келет)
            again = sfx_synth.generate(d / "x", "2026-11-19")
            self.assertEqual([m["sha256"] for m in items], [m["sha256"] for m in again])
        finally:
            shutil.rmtree(d, ignore_errors=True)
