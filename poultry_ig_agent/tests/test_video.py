import json
import os
import shutil
import subprocess
import tempfile
import unittest
import wave

from poultry_ig_agent import niche, video
from poultry_ig_agent.tests.helpers import shots

HAVE = shutil.which("ffmpeg") and shutil.which("ffprobe")


class FakeVeo:
    def __init__(self): self.prompts = []
    def generate(self, prompt, seconds, out):
        self.prompts.append(prompt)
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"testsrc=s=720x1280:d={seconds}:r=24", "-pix_fmt", "yuv420p", out], check=True)
        return out


class FakeTTS:
    def synth(self, text, out, secs=12):
        with wave.open(out, "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(24000)
            w.writeframes(b"\x10\x02" * 24000 * secs)
        return out


def probe(path):
    o = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,width,height", "-of", "json", path], capture_output=True, text=True).stdout
    return json.loads(o)["streams"]


class Pure(unittest.TestCase):
    def test_srt(self):
        s = video.srt("бир эки үч төрт беш алты жети", 7)
        self.assertIn("00:00:00,000 -->", s); self.assertEqual(s.count("-->"), 2)

    def test_real_missing_never_silently_ai(self):
        d = tempfile.mkdtemp(); os.makedirs(os.path.join(d, "real"))
        post = {"content_type": "education", "shots": shots(3, "real")}
        _, missing = video.resolve_shots(post, d)
        self.assertEqual(missing, [1, 2, 3])
        s2, m2 = video.resolve_shots(post, d, allow_ai_fallback=True)
        self.assertEqual(m2, []); self.assertTrue(all(x["source"] == "ai" for x in s2))

    def test_real_farm_never_ai_even_with_fallback(self):
        d = tempfile.mkdtemp(); os.makedirs(os.path.join(d, "real"))
        _, missing = video.resolve_shots({"content_type": "real_farm", "shots": shots(2)}, d, allow_ai_fallback=True)
        self.assertEqual(missing, [1, 2])

    def test_user_footage_assigned(self):
        d = tempfile.mkdtemp(); os.makedirs(os.path.join(d, "real"))
        for n in ("a.mp4", "b.jpg"):
            open(os.path.join(d, "real", n), "w").close()
        out, missing = video.resolve_shots({"content_type": "real_farm", "shots": shots(2)}, d)
        self.assertEqual(missing, []); self.assertTrue(out[0]["file"].endswith("a.mp4"))


@unittest.skipUnless(HAVE, "ffmpeg жок")
class Build(unittest.TestCase):
    def test_full_reel_ai_and_real(self):
        assets = tempfile.mkdtemp(); os.makedirs(os.path.join(assets, "real")); os.makedirs(os.path.join(assets, "music"))
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "color=c=green:s=640x480:d=2", "-pix_fmt", "yuv420p", os.path.join(assets, "real", "farm.mp4")], check=True)
        sh = shots(4); sh[1]["source"] = "real"
        post = {"lang": "ky", "content_type": "education", "voiceover": "Таң атты ферма ойгонду жумуртка чогулду", "shots": sh}
        out = tempfile.mkdtemp(); veo = FakeVeo()
        res = video.build(post, out, veo, FakeTTS(), assets, niche=niche.get("poultry"))
        self.assertEqual(res["status"], "ready", res)
        self.assertEqual(res["ai_shots"], 3)
        self.assertEqual(len(veo.prompts), 3)                       # реал кадр үчүн Veo чакырылган жок
        self.assertIn("Kyrgyzstan", veo.prompts[0])                 # style bible шайкештик үчүн
        st = probe(os.path.join(out, "final.mp4"))
        v = [s for s in st if s["codec_type"] == "video"][0]
        self.assertEqual((v["width"], v["height"]), (1080, 1920))   # 9:16
        self.assertTrue(any(s["codec_type"] == "audio" for s in st))
        self.assertGreaterEqual(video.duration(os.path.join(out, "final.mp4")), 12)   # диктор (12с) кесилген жок

    def test_needs_footage_no_video_built(self):
        assets = tempfile.mkdtemp(); os.makedirs(os.path.join(assets, "real"))
        out = tempfile.mkdtemp()
        r = video.build({"lang": "ky", "content_type": "real_farm", "voiceover": "x", "shots": shots(3)}, out, FakeVeo(), FakeTTS(), assets)
        self.assertEqual(r["status"], "needs_footage")
        self.assertFalse(os.path.exists(os.path.join(out, "final.mp4")))

    def test_provider_failure_logged_not_crash(self):
        class Bad:
            def generate(self, *a): raise video.VideoError("veo ката")
        assets = tempfile.mkdtemp(); os.makedirs(os.path.join(assets, "real"))
        r = video.build({"lang": "ky", "content_type": "viral", "voiceover": "x", "shots": shots(3)}, tempfile.mkdtemp(), Bad(), FakeTTS(), assets)
        self.assertEqual(r["status"], "failed")


if __name__ == "__main__":
    unittest.main()


@unittest.skipUnless(HAVE, "ffmpeg жок")
class Onscreen(unittest.TestCase):
    def test_lines_rendered_separately(self):
        d = tempfile.mkdtemp(); src = os.path.join(d, "s.mp4")
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "color=c=gray:s=720x1280:d=1", "-pix_fmt", "yuv420p", src], check=True)
        video.normalize(src, 1, os.path.join(d, "o.mp4"), "1-ката: Температураны туура эмес жөндөө", "", d)
        files = sorted(f for f in os.listdir(d) if f.startswith("t_"))
        self.assertEqual(len(files), 2)                                  # 2 сап → 2 өзүнчө drawtext
        self.assertFalse(any("\n" in open(os.path.join(d, f), encoding="utf-8").read() for f in files))


class StaleStock(unittest.TestCase):
    def test_previous_stock_shot_never_becomes_ai(self):
        d = tempfile.mkdtemp(); os.makedirs(os.path.join(d, "real"))
        post = {"content_type": "education", "shots": [{"n": 1, "duration": 4, "source": "stock", "visual": "chicks", "file": "/old/x.mp4"}]}
        out, missing = video.resolve_shots(post, d)
        self.assertEqual(missing, [1]); self.assertEqual(out[0]["source"], "real"); self.assertNotIn("file", out[0])


@unittest.skipUnless(HAVE, "ffmpeg жок")
class EmojiStrip(unittest.TestCase):
    def test_unsupported_emoji_removed_supported_symbols_kept(self):
        d = tempfile.mkdtemp(); src = os.path.join(d, "s.mp4")
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "color=c=gray:s=720x1280:d=1", "-pix_fmt", "yuv420p", src], check=True)
        video.normalize(src, 1, os.path.join(d, "o.mp4"), "Жумуртка азайдыбы? 🥚 👇 → ✓", "", d)
        txt = " ".join(open(os.path.join(d, f), encoding="utf-8").read() for f in sorted(os.listdir(d)) if f.startswith("t_"))
        self.assertNotIn("🥚", txt); self.assertNotIn("👇", txt)
        self.assertIn("→", txt); self.assertIn("✓", txt)


@unittest.skipUnless(HAVE, "ffmpeg жок")
class UpperWrap(unittest.TestCase):
    def test_uppercase_wrapped_shorter(self):
        d = tempfile.mkdtemp(); src = os.path.join(d, "s.mp4")
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "color=c=gray:s=720x1280:d=1", "-pix_fmt", "yuv420p", src], check=True)
        video.normalize(src, 1, os.path.join(d, "o.mp4"), "СЕБЕП №5 · ЖАШ ЖАНА ДЕН СООЛУК", "", d)
        lines = [open(os.path.join(d, f), encoding="utf-8").read() for f in sorted(os.listdir(d)) if f.startswith("t_")]
        self.assertTrue(all(len(l) <= 18 for l in lines)); self.assertGreaterEqual(len(lines), 2)


@unittest.skipUnless(HAVE, "ffmpeg жок")
class PhotoStory(unittest.TestCase):
    def _img(self, d, name="p.png"):
        from PIL import Image
        p = os.path.join(d, name); Image.new("RGB", (941, 1672), (180, 120, 60)).save(p); return p

    def test_kenburns_clip_is_vertical_and_timed(self):
        d = tempfile.mkdtemp(); img = self._img(d)
        out = video.normalize(img, 2.0, os.path.join(d, "o.mp4"), "Себеп 1: Кальций аз", "", d, motion="in", fade=0.3)
        v = [s for s in probe(out) if s["codec_type"] == "video"][0]
        self.assertEqual((v["width"], v["height"]), (1080, 1920))
        self.assertAlmostEqual(video.duration(out), 2.0, delta=0.15)

    def test_photo_source_resolved_and_not_stock(self):
        d = tempfile.mkdtemp(); img = self._img(d)
        shots, missing = video.resolve_shots({"content_type": "education", "shots": [
            {"n": 1, "source": "photo", "file": img, "duration": 3}, {"n": 2, "source": "photo", "file": "/nope.png"}]},
            tempfile.mkdtemp())
        self.assertEqual(missing, [2]); self.assertEqual(shots[0]["file"], img)

    def test_fit_shrinks_long_plan(self):
        sh = [{"n": i, "duration": 4} for i in range(10)]          # 40с план, үн 20с
        video.fit_durations(sh, 20)
        self.assertAlmostEqual(sum(s["duration"] for s in sh), 20.5, delta=0.3)

    def test_voice_tempo_and_photo_build(self):
        d = tempfile.mkdtemp(); assets = tempfile.mkdtemp(); os.makedirs(os.path.join(assets, "real"))
        imgs = [self._img(d, f"i{k}.png") for k in range(3)]
        post = {"lang": "ky", "content_type": "education", "voiceover": "x", "voice_tempo": 1.1, "fade": 0.25,
                "shots": [{"n": k + 1, "source": "photo", "file": p, "duration": 4, "visual": "-", "motion": m, "onscreen": "Т"}
                          for k, (p, m) in enumerate(zip(imgs, ("in", "left", "out")))]}
        r = video.build(post, os.path.join(d, "out"), FakeVeo(), FakeTTS(), assets)
        self.assertEqual(r["status"], "ready", r)
        self.assertAlmostEqual(video.duration(r["path"]), 12 / 1.1 + 0.5, delta=0.6)   # 12с үн 1.1x тезирээк


@unittest.skipUnless(HAVE, "ffmpeg жок")
class Music(unittest.TestCase):
    def test_generated_music_unique_per_video_and_licensed(self):
        from poultry_ig_agent import music_gen
        a, b = music_gen.plan("Instagram_Reels_03"), music_gen.plan("Instagram_Reels_04")
        self.assertNotEqual((a["key"], a["bpm"], a["progression"]), (b["key"], b["bpm"], b["progression"]))
        d = tempfile.mkdtemp(); info = music_gen.generate(os.path.join(d, "m.wav"), 3, "x")
        self.assertEqual(info["source"], "generated"); self.assertIn("own composition", info["license"])
        self.assertAlmostEqual(video.duration(os.path.join(d, "m.wav")), 3, delta=0.1)

    def test_build_records_music(self):
        assets = tempfile.mkdtemp(); os.makedirs(os.path.join(assets, "real"))
        r = video.build({"id": "t1", "lang": "ky", "content_type": "education", "voiceover": "x", "shots": shots(3)},
                        tempfile.mkdtemp(), FakeVeo(), FakeTTS(), assets)
        self.assertEqual(r["status"], "ready", r)
        self.assertEqual(r["music"]["source"], "generated")

    def test_music_off(self):
        assets = tempfile.mkdtemp(); os.makedirs(os.path.join(assets, "real"))
        r = video.build({"lang": "ky", "content_type": "education", "voiceover": "x", "shots": shots(3), "music": "none"},
                        tempfile.mkdtemp(), FakeVeo(), FakeTTS(), assets)
        self.assertIsNone(r["music"])


@unittest.skipUnless(HAVE, "ffmpeg жок")
class CardLayout(unittest.TestCase):
    def test_card_small_image_with_text_and_fade(self):
        from PIL import Image
        d = tempfile.mkdtemp(); img = os.path.join(d, "p.png"); Image.new("RGB", (330, 225), (150, 90, 40)).save(img)
        out = video.normalize(img, 2.0, os.path.join(d, "o.mp4"), "3. Мите курттар: бит жана кене", "", d,
                              motion="card", fade=0.2, text_style="yellow")
        v = [s for s in probe(out) if s["codec_type"] == "video"][0]
        self.assertEqual((v["width"], v["height"]), (1080, 1920))
        self.assertAlmostEqual(video.duration(out), 2.0, delta=0.15)
        self.assertFalse([f for f in os.listdir(d) if f.endswith(".card.mp4")])
