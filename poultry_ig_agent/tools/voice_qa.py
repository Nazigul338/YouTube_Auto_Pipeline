"""Диктор үнүнүн кыргызча тактыгын автоматтык баалоо: TTS → Gemini транскрипциясы → түп нуска менен салыштыруу.
python -m poultry_ig_agent.tools.voice_qa --text-file T --outdir D --voices Orus,Charon --styles plain,warm
Тактык = 100 × (1 − тамга деңгээлиндеги айырма). Нускаманы окуп жиберсе ('TEXT', 'farmer', 'instructions') — белгиленет.
ЭСКЕРТҮҮ: транскрипция да модель — 100% чындык эмес; акыркы чечим колдонуучунун кулагында."""
import argparse
import base64
import difflib
import json
import os
import re
import subprocess
import time
import urllib.request

from poultry_ig_agent import config, llm, video


def norm(s):
    return re.sub(r"[^а-яөүңё]+", " ", s.lower()).split()


def accuracy(ref, hyp):
    r, h = " ".join(norm(ref)), " ".join(norm(hyp))
    return round(100 * difflib.SequenceMatcher(None, r, h).ratio(), 1)


def transcribe(wav):
    key = llm.api_key()
    audio = base64.b64encode(open(wav, "rb").read()).decode()
    body = json.dumps({"contents": [{"parts": [
        {"text": "Transcribe this Kyrgyz speech verbatim in Kyrgyz Cyrillic, exactly as pronounced (do not correct "
                 "mistakes, do not translate). Output only the transcript."},
        {"inlineData": {"mimeType": "audio/wav", "data": audio}}]}], "generationConfig": {"temperature": 0}}).encode()
    last = None
    for m in config.TEXT_MODELS:
        try:
            req = urllib.request.Request(f"{config.API_BASE}/models/{m}:generateContent", body,
                                         {"Content-Type": "application/json", "x-goog-api-key": key})
            d = json.load(urllib.request.urlopen(req, timeout=150))
            return d["candidates"][0]["content"]["parts"][0]["text"].strip(), m
        except Exception as e:
            last = f"{m}: {type(e).__name__}"
    raise RuntimeError("транскрипция болбоду: " + str(last))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--text-file", required=True)
    ap.add_argument("--outdir", required=True)
    ap.add_argument("--voices", default="Orus,Charon,Fenrir,Iapetus,Algieba,Schedar")
    ap.add_argument("--styles", default="plain,warm")
    a = ap.parse_args()
    os.makedirs(a.outdir, exist_ok=True)
    text = open(a.text_file, encoding="utf-8").read().strip()
    rows = []
    for v in a.voices.split(","):
        for st in a.styles.split(","):
            name = f"{v}_{st}"
            wav = os.path.join(a.outdir, name + ".wav")
            row = {"voice": v, "style": st}
            try:
                t = video.GeminiTTS(v, style=st)
                t.synth(text, wav)
                row["tts_model"] = t.last_model
                row["seconds"] = round(video.duration(wav), 1)
                hyp, tm = transcribe(wav)
                row.update(transcript=hyp, asr_model=tm, accuracy=accuracy(text, hyp),
                           leak=bool(re.search(r"(?i)\b(text|farmer|instruction|tone|kyrgyz)\b", hyp)))
                subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", wav, "-ac", "1", "-b:a", "96k",
                                os.path.join(a.outdir, name + ".mp3")], check=True)
            except Exception as e:
                row["error"] = str(e)[:200]
            if os.path.exists(wav):
                os.remove(wav)
            rows.append(row)
            print(json.dumps(row, ensure_ascii=False))
            time.sleep(4)
    rows.sort(key=lambda r: (-(r.get("accuracy") or 0)))
    with open(os.path.join(a.outdir, "report.json"), "w", encoding="utf-8") as f:
        json.dump({"text": text, "results": rows}, f, ensure_ascii=False, indent=1)
    print("\n== ТАКТЫК БОЮНЧА:")
    for r in rows:
        print(f"{r['voice']:9s} {r['style']:6s} {r.get('accuracy', '—'):>6} %  {r.get('seconds', '')}с  "
              f"{'⚠ нускама окулду' if r.get('leak') else ''} {r.get('error', '')}")
    raise SystemExit(0 if any("accuracy" in r for r in rows) else 1)


if __name__ == "__main__":
    main()
