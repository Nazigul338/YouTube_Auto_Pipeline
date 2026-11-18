"""Kani TTS кыргызча сыноо: (A) бүт текст бир жолу, (B) сүйлөм-сүйлөм + төмөн температура + узун бөлүктү кесүү.
Колдонуу: python kani_probe.py --model nineninesix/kani-tts-400m-ky --text-file t.txt --outdir probe_out
"""
import argparse
import json
import os
import re
import time

import numpy as np


def sentences(text):
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]


def expected_max_s(sentence):
    # кыргызча ≈ 13–15 тамга/сек; 2 эсе запас + 1 сек
    return 2 * len(sentence) / 13 + 1.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--text-file", required=True)
    ap.add_argument("--outdir", required=True)
    a = ap.parse_args()
    os.makedirs(a.outdir, exist_ok=True)
    text = open(a.text_file, encoding="utf-8").read().strip()
    from kani_tts import KaniTTS
    t0 = time.time()
    model = KaniTTS(a.model)
    rep = {"model": a.model, "chars": len(text), "load_s": round(time.time() - t0, 1)}
    sr = 22050

    # A: бир жолу (мурдагыдай)
    t = time.time()
    audio, _ = model(text)
    model.save_audio(audio, os.path.join(a.outdir, "A_full.wav"))
    rep["A"] = {"gen_s": round(time.time() - t, 1), "audio_s": round(len(np.asarray(audio).reshape(-1)) / sr, 2)}

    # B: сүйлөм-сүйлөм
    parts, rep["B"] = [], {"sentences": []}
    t = time.time()
    for s in sentences(text):
        lim = expected_max_s(s)
        info = {"chars": len(s), "limit_s": round(lim, 1)}
        for attempt, temp in enumerate((0.6, 0.4)):
            au, _ = model(s, temperature=temp, top_p=0.9, repetition_penalty=1.2)
            au = np.asarray(au, dtype=np.float32).reshape(-1)
            dur = len(au) / sr
            info[f"try{attempt}_s"] = round(dur, 2)
            if dur <= lim:
                break
        if dur > lim:
            au = au[: int(lim * sr)]
            info["trimmed"] = True
        parts += [au, np.zeros(int(0.25 * sr), dtype=np.float32)]
        rep["B"]["sentences"].append(info)
    full = np.concatenate(parts)
    import soundfile as sf
    sf.write(os.path.join(a.outdir, "B_sentences.wav"), full, sr)
    rep["B"].update(gen_s=round(time.time() - t, 1), audio_s=round(len(full) / sr, 2))
    print(json.dumps(rep, ensure_ascii=False, indent=1))
    with open(os.path.join(a.outdir, "report.json"), "w", encoding="utf-8") as f:
        json.dump(rep, f, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
