"""Kani TTS кыргызча сыноо: модель жүктөлөбү, канча убакыт кетет, үн кандай.
Колдонуу: python kani_probe.py --model nineninesix/kani-tts-400m-ky --text-file t.txt --out out.wav [--ref ref.wav]
"""
import argparse
import json
import time


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--text-file", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--ref", default=None, help="үн клондоо үчүн эталон (kani-tts-2 гана)")
    a = ap.parse_args()
    text = open(a.text_file, encoding="utf-8").read().strip()
    rep = {"model": a.model, "chars": len(text)}
    t0 = time.time()
    from kani_tts import KaniTTS
    model = KaniTTS(a.model)
    rep["load_s"] = round(time.time() - t0, 1)
    kw = {}
    if a.ref:
        from kani_tts import SpeakerEmbedder
        kw["speaker_emb"] = SpeakerEmbedder(device="cpu").embed_audio_file(a.ref)
    t1 = time.time()
    audio, _ = model(text, **kw)
    rep["gen_s"] = round(time.time() - t1, 1)
    model.save_audio(audio, a.out)
    import soundfile as sf
    info = sf.info(a.out)
    rep["audio_s"] = round(info.duration, 2)
    rep["realtime_factor"] = round(rep["gen_s"] / max(info.duration, 0.01), 2)
    print(json.dumps(rep, ensure_ascii=False))
    with open(a.out + ".json", "w", encoding="utf-8") as f:
        json.dump(rep, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
