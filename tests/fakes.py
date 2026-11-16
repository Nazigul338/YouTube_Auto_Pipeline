"""Тесттер үчүн жалган кызматтар (тармакка чыкпайт)."""

from __future__ import annotations

import hashlib
import json
import math
import re
import struct

TOPICS = ["привычка", "страх", "решение", "утро", "цель", "сомнение", "шаг", "время",
          "выбор", "усталость", "надежда", "ошибка"]


def make_script(n_words: int = 1150, seed: str = "") -> str:
    sents, total, i = [], 0, 0
    while total < n_words:
        t = TOPICS[(i + len(seed)) % len(TOPICS)]
        s = (f"Иногда {t} становится тихим собеседником номер {i + 1}{seed}, "
             f"и мы замечаем это только вечером, когда день уже прошёл.")
        sents.append(s)
        from pipeline.textutil import word_count
        total += word_count(s)
        i += 1
    paras = [" ".join(sents[k:k + 4]) for k in range(0, len(sents), 4)]
    return "\n\n".join(paras)


class FakeGemini:
    def __init__(self, words: int = 1150, same_text: bool = False):
        self.words = words
        self.same_text = same_text
        self.calls: list[str] = []
        self.usage: list[dict] = []
        self.n = 0

    def text(self, prompt: str, *, purpose: str = "text", **kw) -> str:
        self.calls.append(purpose)
        self.usage.append({"purpose": purpose, "model": "fake"})
        if purpose == "script_draft":
            self.n += 1
            seed = "" if self.same_text else f"-{self.n}"
            return "НАЗВАНИЕ: Тестовое видео\n\n" + make_script(self.words, seed)
        body = prompt.split("ТЕКСТ:\n", 1)[-1]
        if purpose == "fact_check":
            return f"===ТЕКСТ===\n{body}\n===ИЗМЕНЕНИЯ===\nнет"
        return body

    def json(self, prompt: str, *, purpose: str = "json", **kw):
        self.calls.append(purpose)
        if purpose == "scenes":
            n = int(re.search(r"exactly (\d+) objects", prompt).group(1))
            scenes = re.findall(r"^\d+\. (.*)$", prompt.split("SCENES:", 1)[1], re.M)
            out = []
            for i in range(n):
                ws = re.findall(r"\w+", scenes[i]) if i < len(scenes) else []
                first = ws[min(1, len(ws) - 1)] if ws else "день"
                out.append({"id": i + 1, "emotion": "reflective", "visual": "a person at a window",
                            "queries": ["man thinking window", "city night", "sunrise"],
                            "keywords": [first, "несуществующее слово"],
                            "on_screen_text": "Первый шаг" if i % 4 == 0 else "",
                            "music_mood": "emotional_piano"})
            return out
        if purpose == "music_tags":
            return {}
        return {}

    def embed(self, texts):
        out = []
        for t in texts:
            h = hashlib.sha256(t.encode()).digest()
            out.append([b / 255 for b in h])
        return out

    def tts(self, text: str, *, voice: str, style: str, variant: int = 0, models=None):
        """Сөз санына жараша узактыктагы синус (24 кГц PCM)."""
        self.calls.append("tts")
        self.usage.append({"purpose": "tts", "model": (models or ["fake-tts"])[0]})
        rate = 24000
        secs = max(1.0, len(re.findall(r"\w+", text)) / 2.4)
        n = int(secs * rate)
        data = b"".join(struct.pack("<h", int(3000 * math.sin(2 * math.pi * 220 * k / rate)))
                        for k in range(n))
        return data, rate

    def ask_about_file(self, path, prompt, *, purpose="file"):
        return json.dumps({"mood": "emotional_piano", "energy": "low", "vocals": False})


    def rate_frames(self, items):
        self.calls.append("frame_check")
        return [4] * len(items)


class FakeStock:
    """Сток API'нин ордуна: FFmpeg жасаган тест-клиптер (тармаксыз)."""

    def __init__(self, per_query: int = 25):
        self.per_query = per_query
        self.downloads = 0

    def _asset(self, kind, q, k):
        from pipeline.stock import Asset, PIXABAY_LICENSE
        h = abs(hash((q, k))) % 10**8
        return Asset("pixabay", kind, f"pixabay{'-img' if kind == 'image' else ''}:{h}",
                     f"fake://{kind}/{h}", 1920, 1080, 8.0 if kind == "video" else 0.0,
                     f"https://pixabay.com/x/{h}", "tester", *PIXABAY_LICENSE, query=q)

    def videos(self, q, min_duration=3.0):
        return [self._asset("video", q, k) for k in range(self.per_query)]

    def images(self, q):
        return [self._asset("image", q, k) for k in range(5)]

    def download(self, asset, dest):
        import subprocess
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.exists():
            return dest
        self.downloads += 1
        if asset.kind == "video":
            subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
                            f"testsrc2=size=640x360:rate=30:duration=8", "-c:v", "libx264",
                            "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(dest)], check=True)
        else:
            subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
                            "testsrc2=size=1280x720", "-frames:v", "1", str(dest)], check=True)
        return dest
