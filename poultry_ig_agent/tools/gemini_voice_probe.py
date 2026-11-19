"""Gemini TTS кыргызча сыноо: бир нече үн → mp3 + отчет. Колдонуу (репо тамырынан):
python -m poultry_ig_agent.tools.gemini_voice_probe --text-file poultry_ig_agent/voice_probe/text_ky.txt --outdir out --voices Charon,Kore
"""
import argparse
import json
import os
import subprocess
import time

from poultry_ig_agent import video


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--text-file", required=True)
    ap.add_argument("--outdir", required=True)
    ap.add_argument("--voices", default="Charon,Orus,Fenrir,Kore,Aoede")
    a = ap.parse_args()
    os.makedirs(a.outdir, exist_ok=True)
    text = open(a.text_file, encoding="utf-8").read().strip()
    rep, ok = {"chars": len(text), "voices": {}}, 0
    for v in a.voices.split(","):
        wav = os.path.join(a.outdir, f"gemini_{v}.wav")
        t = time.time()
        try:
            video.GeminiTTS(v).synth(text, wav)
            mp3 = wav[:-4] + ".mp3"
            subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", wav, "-ac", "1", "-b:a", "96k", mp3], check=True)
            os.remove(wav)
            rep["voices"][v] = {"ok": True, "gen_s": round(time.time() - t, 1), "audio_s": round(video.duration(mp3), 2)}
            ok += 1
        except Exception as e:
            rep["voices"][v] = {"ok": False, "error": str(e)[:300]}
        time.sleep(3)  # бекер квотаны аяйбыз
    print(json.dumps(rep, ensure_ascii=False, indent=1))
    with open(os.path.join(a.outdir, "report.json"), "w", encoding="utf-8") as f:
        json.dump(rep, f, ensure_ascii=False, indent=1)
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
