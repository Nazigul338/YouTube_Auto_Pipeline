"""Колдонуучунун видеосундагы сөздү Gemini менен текстке айлантат (кыргыз/орус).
Колдонуу: python -m poultry_ig_agent.tools.transcribe <папка>  → ар бир *.mp3 жанына <аты>.txt (убакыт белгилери менен)."""
import base64
import glob
import json
import os
import sys
import time
import urllib.error
import urllib.request

from .. import config
from ..llm import api_key

PROMPT = ("Бул аудиодо фермер тоок чарбасы же чөп/жем тууралуу сүйлөп жатат. Сөзмө-сөз транскрипция жаз, "
          "тилин өзгөртпө (кыргызча болсо кыргызча, орусча болсо орусча), котормо жасаба, ойлоп кошпо. "
          "Ар 3–8 секунддук фразаны өзүнчө сапка [мм:сс] убакыт белгиси менен баштап жаз. "
          "Угулбаган жерди [угулбайт] деп белгиле. Сөз жок болсо (шамал, ызы-чуу) — [сөз жок] деп жаз.")


def transcribe(path):
    data = base64.b64encode(open(path, "rb").read()).decode()
    body = json.dumps({"contents": [{"parts": [{"inline_data": {"mime_type": "audio/mp3", "data": data}},
                                               {"text": PROMPT}]}],
                       "generationConfig": {"temperature": 0.1}}).encode()
    last = None
    for model in config.TEXT_MODELS:
        for attempt in range(3):
            req = urllib.request.Request(f"{config.API_BASE}/models/{model}:generateContent", data=body,
                                         headers={"Content-Type": "application/json", "x-goog-api-key": api_key()})
            try:
                with urllib.request.urlopen(req, timeout=300) as r:
                    d = json.load(r)
                return model, "".join(p.get("text", "") for p in d["candidates"][0]["content"]["parts"])
            except urllib.error.HTTPError as e:
                last = f"{model}: HTTP {e.code}"
                if e.code in (429, 500, 503):
                    time.sleep(5 * (attempt + 1)); continue
                break
            except (OSError, KeyError, IndexError) as e:
                last = f"{model}: {type(e).__name__}"; time.sleep(3)
    raise RuntimeError(f"транскрипция болгон жок: {last}")


if __name__ == "__main__":
    for p in sorted(glob.glob(os.path.join(sys.argv[1], "*.mp3"))):
        model, text = transcribe(p)
        out = p[:-4] + ".txt"
        open(out, "w", encoding="utf-8").write(text.strip() + "\n")
        print(f"== {os.path.basename(p)} ({model})\n{text.strip()}\n")
