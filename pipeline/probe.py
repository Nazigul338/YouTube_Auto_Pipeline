"""Чыныгы мүмкүнчүлүктөрдү сынаган скрипт (GitHub Actions'та иштейт).

    python -m pipeline.probe

Эч нерсени өзгөртпөйт жана Drive'га тийбейт. Текшерет:
  - runner'дин ресурстары жана FFmpeg;
  - Gemini: моделдердин тизмеси, текст, Google Search, TTS (Algenib), embedding,
    аудиону түшүнүү (Files API), AI-сүрөт; Veo — тизмеде бар-жогу гана (акча кетпесин);
  - Pixabay: видео/сүрөт издөө жана лимит;
  - Whisper: моделди жүктөө жана TTS үлгүсүн кайра текстке айлантуу.
Ачкычтар эч качан басылбайт (катанын текстинен да тазаланат).
"""

from __future__ import annotations

import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import wave
from pathlib import Path

RESULTS: list[tuple[str, str, str]] = []  # (аталыш, ok/fail/info, эскертүү)
SECRETS = [os.environ.get(k, "") for k in ("GOOGLE_API_KEY", "PIXABAY_API_KEY", "PEXELS_API_KEY")]
TMP = Path(tempfile.mkdtemp(prefix="probe_"))


def clean(text: str) -> str:
    text = str(text)
    for s in SECRETS:
        if s and len(s) > 6:
            text = text.replace(s, "***")
    text = re.sub(r"AIza[0-9A-Za-z_\-]{20,}", "***", text)
    text = re.sub(r"key=[^&\s]+", "key=***", text)
    return text.replace("\n", " ")[:220]


def rec(name: str, status: str, note: str = "", full: bool = False) -> None:
    note = clean(note) if not full else str(note)
    RESULTS.append((name, status, note))
    icon = {"ok": "✅", "fail": "❌", "info": "ℹ️"}[status]
    print(f"{icon} {name}: {note}", flush=True)


def err(e: Exception) -> str:
    code = getattr(e, "code", None) or getattr(e, "status_code", None)
    return f"{type(e).__name__}{f' [{code}]' if code else ''}: {e}"


def sh(cmd: str) -> str:
    return subprocess.run(cmd, shell=True, capture_output=True, text=True).stdout.strip()


# ------------------------------------------------------------------ runner
def probe_runner() -> None:
    ram = int(sh("grep MemTotal /proc/meminfo | awk '{print $2}'") or 0) / 1e6
    rec("Runner", "info", f"CPU {os.cpu_count()}, RAM {ram:.1f} GB, "
        f"бош диск {shutil.disk_usage('/').free / 1e9:.1f} GB, Python {sys.version.split()[0]}")
    ver = sh("ffmpeg -version | head -1")
    filters = sh("ffmpeg -hide_banner -filters")
    need = ["zoompan", "xfade", "sidechaincompress", "loudnorm", "ass", "blackdetect",
            "freezedetect", "silencedetect", "ebur128"]
    missing = [f for f in need if f" {f} " not in filters]
    rec("FFmpeg", "fail" if missing or not ver else "ok",
        f"{ver[:40]}; жок фильтрлер: {missing or 'жок'}")


# ------------------------------------------------------------------ gemini
def probe_gemini() -> dict:
    out: dict = {}
    key = os.environ.get("GOOGLE_API_KEY", "").strip()
    if not key:
        rec("Gemini", "fail", "GOOGLE_API_KEY жок")
        return out
    from google import genai
    from google.genai import types
    import importlib.metadata as md
    rec("google-genai", "info", md.version("google-genai"))
    client = genai.Client(api_key=key, http_options=types.HttpOptions(timeout=90_000))
    beta = genai.Client(api_key=key, http_options=types.HttpOptions(api_version="v1beta",
                                                                     timeout=120_000))
    only_tts = os.environ.get("PROBE_ONLY") == "tts"

    # 1. Моделдер тизмеси
    try:
        models = []
        for m in client.models.list():
            acts = getattr(m, "supported_actions", None) or []
            models.append((m.name.replace("models/", ""), list(acts)))
        out["models"] = models
        names = [n for n, _ in models]
        groups = {
            "text": [n for n in names if n.startswith("gemini") and "tts" not in n
                     and "image" not in n and "embedding" not in n and "live" not in n],
            "tts": [n for n in names if "tts" in n],
            "image": [n for n in names if "imagen" in n or ("image" in n and "gemini" in n)],
            "veo": [n for n in names if "veo" in n],
            "embedding": [n for n in names if "embedding" in n],
        }
        out["groups"] = groups
        rec("Gemini моделдери", "ok", f"бардыгы {len(names)}")
        for g, lst in groups.items():
            rec(f"  {g}", "info", ", ".join(lst) or "—", full=True)
        for n, acts in models:
            print(f"   · {n}: {','.join(acts)}", flush=True)
    except Exception as e:
        rec("Gemini моделдери", "fail", err(e))
        return out

    # 2. Текст (сценарий үчүн талапкерлер)
    text_ok = []
    prefs = ["gemini-3.8-flash", "gemini-3.7-flash", "gemini-3.6-flash", "gemini-3.5-flash",
             "gemini-4-argon", "gemini-4-carbon", "gemini-4-hydrogen", "gemini-3.5-flash-lite"]
    cands = [p for p in prefs if p in groups["text"]] + \
            [n for n in groups["text"] if n not in prefs and "preview" not in n][:4]
    for model in ([] if only_tts else cands[:9]):
        try:
            t = time.time()
            r = client.models.generate_content(model=model, contents="Ответь одним словом: ок")
            text_ok.append(model)
            rec(f"Текст: {model}", "ok", f"{(r.text or '').strip()[:20]!r}, {time.time()-t:.1f} сек")
        except Exception as e:
            rec(f"Текст: {model}", "fail", err(e))
    out["text_ok"] = text_ok

    # 3. Google Search менен факт текшерүү
    if text_ok and not only_tts:
        try:
            r = client.models.generate_content(
                model=text_ok[0],
                contents="Кто ввёл термин 'выученная беспомощность'? Ответь коротко.",
                config=types.GenerateContentConfig(
                    tools=[types.Tool(google_search=types.GoogleSearch())]))
            gm = r.candidates[0].grounding_metadata if r.candidates else None
            n = len(getattr(gm, "grounding_chunks", None) or []) if gm else 0
            rec("Google Search (факт текшерүү)", "ok" if n else "info",
                f"{text_ok[0]}: булак саны {n}; жооп: {(r.text or '')[:60]}")
        except Exception as e:
            rec("Google Search (факт текшерүү)", "fail", err(e))

    # 4. TTS — Algenib (тизмеде көрүнбөсө да түз аты менен сынайбыз)
    sample = "Иногда самый трудный шаг — это первый. Но именно он меняет всё."
    tts_ok = None
    guesses = ["gemini-3.8-flash-tts", "gemini-3.8-flash-preview-tts", "gemini-3.5-flash-tts",
               "gemini-3.5-flash-preview-tts", "gemini-3.7-flash-tts", "gemini-3.6-flash-tts",
               "gemini-2.5-flash-preview-tts", "gemini-2.5-pro-preview-tts"]
    cands = list(dict.fromkeys(groups["tts"] + guesses +
                               [n for n in names if "audio" in n or "omni" in n or "speech" in n]))

    def save_pcm(data: bytes, mime: str, path: Path) -> float:
        rate = int(re.search(r"rate=(\d+)", mime).group(1)) if mime and "rate=" in mime else 24000
        with wave.open(str(path), "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(rate); w.writeframes(data)
        return len(data) / 2 / rate

    for model in cands:
        if tts_ok:
            break
        try:
            t = time.time()
            r = beta.models.generate_content(
                model=model, contents=f"Скажи спокойно и уверенно: {sample}",
                config=types.GenerateContentConfig(
                    response_modalities=["AUDIO"],
                    speech_config=types.SpeechConfig(voice_config=types.VoiceConfig(
                        prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name="Algenib")))))
            part = r.candidates[0].content.parts[0].inline_data
            wav_path = TMP / "tts.wav"
            dur = save_pcm(part.data, part.mime_type, wav_path)
            rec(f"TTS v1beta generate_content: {model}", "ok", f"{dur:.1f} сек ({part.mime_type}), {time.time()-t:.1f} сек")
            tts_ok = tts_ok or (model, wav_path)
        except Exception as e:
            rec(f"TTS v1beta generate_content: {model}", "fail", err(e))
        try:
            import base64
            t = time.time()
            r = beta.interactions.create(
                model=model, input=f"Скажи спокойно и уверенно: {sample}",
                response_format={"type": "audio"},
                generation_config={"speech_config": [{"voice": "Algenib"}]})
            data = base64.b64decode(r.output_audio.data)
            wav_path = TMP / "tts_i.wav"
            if data[:4] == b"RIFF":
                wav_path.write_bytes(data)
                with wave.open(str(wav_path)) as w:
                    dur = w.getnframes() / w.getframerate()
            else:
                dur = save_pcm(data, getattr(r.output_audio, "mime_type", "") or "", wav_path)
            rec(f"TTS v1beta interactions: {model}", "ok", f"{dur:.1f} сек, баш: {data[:4]!r}, {time.time()-t:.1f} сек")
            tts_ok = tts_ok or (model, wav_path)
        except Exception as e:
            rec(f"TTS v1beta interactions: {model}", "fail", err(e))
    out["tts_ok"] = tts_ok

    if only_tts:
        return out

    # 4б. Тынымсыз модель (503) — кайра аракет
    for attempt in range(3):
        try:
            r = client.models.generate_content(model="gemini-3.8-flash", contents="Ответь: ок")
            rec("gemini-3.8-flash (кайра аракет)", "ok", f"{attempt+1}-аракетте: {(r.text or '')[:10]!r}")
            break
        except Exception as e:
            if attempt == 2:
                rec("gemini-3.8-flash (кайра аракет)", "fail", err(e))
            time.sleep(10 * (attempt + 1))

    # 5. Embedding (окшоштук үчүн)
    for model in groups["embedding"][:2]:
        try:
            r = client.models.embed_content(model=model, contents="проверка")
            rec(f"Embedding: {model}", "ok", f"өлчөмү {len(r.embeddings[0].values)}")
            break
        except Exception as e:
            rec(f"Embedding: {model}", "fail", err(e))

    # 6. Аудиону түшүнүү (музыканын маанайын аныктоо үчүн)
    if text_ok:
        tone = TMP / "tone.mp3"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                        "sine=f=220:d=5", str(tone)], check=True)
        try:
            f = client.files.upload(file=str(tone))
            for _ in range(20):
                f = client.files.get(name=f.name)
                if str(getattr(f, "state", "")).endswith("ACTIVE"):
                    break
                time.sleep(1)
            r = client.models.generate_content(model=text_ok[0], contents=[
                f, "Опиши звук в 3 словах."])
            rec("Аудиону түшүнүү (Files API)", "ok", (r.text or "")[:60])
            try:
                client.files.delete(name=f.name)
            except Exception:
                pass
        except Exception as e:
            rec("Аудиону түшүнүү (Files API)", "fail", err(e))

    # 7. AI-сүрөт (акыркы видеодо колдонулушу мүмкүн)
    for model in groups["image"][:1]:
        try:
            if "imagen" in model:
                r = client.models.generate_images(
                    model=model, prompt="a lone person on a foggy mountain at sunrise, cinematic",
                    config=types.GenerateImagesConfig(number_of_images=1))
                ok = bool(r.generated_images)
            else:
                r = client.models.generate_content(
                    model=model, contents="A lone person on a foggy mountain at sunrise, cinematic photo",
                    config=types.GenerateContentConfig(response_modalities=["TEXT", "IMAGE"]))
                ok = any(getattr(p, "inline_data", None) for p in r.candidates[0].content.parts)
            rec(f"AI-сүрөт: {model}", "ok" if ok else "fail", "сүрөт келди" if ok else "сүрөт жок")
            if ok:
                break
        except Exception as e:
            rec(f"AI-сүрөт: {model}", "fail", err(e))
    rec("Veo (AI-видео)", "info",
        (", ".join(groups["veo"]) + " — тизмеде бар; акча кетпеши үчүн генерация сыналган жок")
        if groups["veo"] else "тизмеде жок")
    return out


# ------------------------------------------------------------------ pixabay
def probe_pixabay() -> None:
    key = os.environ.get("PIXABAY_API_KEY", "").strip()
    if not key:
        rec("Pixabay", "fail", "ачкыч жок")
        return
    import requests
    try:
        r = requests.get("https://pixabay.com/api/videos/",
                         params={"key": key, "q": "man thinking window", "per_page": 50}, timeout=30)
        d = r.json()
        hits = d.get("hits", [])
        fhd = sum(1 for h in hits if (h.get("videos", {}).get("large", {}).get("width") or 0) >= 1920)
        rec("Pixabay видео", "ok" if r.ok else "fail",
            f"HTTP {r.status_code}, табылды {d.get('totalHits')}, 50дөн 1080p+: {fhd}, "
            f"лимит {r.headers.get('X-RateLimit-Limit')}/{r.headers.get('X-RateLimit-Reset')}сек, "
            f"калды {r.headers.get('X-RateLimit-Remaining')}")
        if hits:
            v = hits[0]["videos"]
            rec("  өлчөмдөр (1-видео)", "info",
                ", ".join(f"{k}:{v[k].get('width')}x{v[k].get('height')}" for k in v))
        r = requests.get("https://pixabay.com/api/",
                         params={"key": key, "q": "mountain fog", "per_page": 3,
                                 "image_type": "photo", "orientation": "horizontal"}, timeout=30)
        rec("Pixabay сүрөт", "ok" if r.ok else "fail", f"HTTP {r.status_code}, {r.json().get('totalHits')}")
    except Exception as e:
        rec("Pixabay", "fail", err(e))
    if os.environ.get("PEXELS_API_KEY", "").strip():
        rec("Pexels", "info", "ачкыч бар (сыналбады)")
    else:
        rec("Pexels", "info", "ачкыч жок (милдеттүү эмес)")


# ------------------------------------------------------------------ whisper
def probe_whisper(tts) -> None:
    try:
        import numpy as np
        from faster_whisper import WhisperModel
        import importlib.metadata as md
        rec("faster-whisper / av", "info", f"{md.version('faster-whisper')} / {md.version('av')}")
        t = time.time()
        model = WhisperModel("small", device="cpu", compute_type="int8")
        rec("Whisper small жүктөлдү", "ok", f"{time.time()-t:.0f} сек")
        if tts:
            raw = subprocess.run(["ffmpeg", "-loglevel", "error", "-i", str(tts[1]), "-f", "s16le",
                                  "-ac", "1", "-ar", "16000", "-"], capture_output=True, check=True).stdout
            audio = np.frombuffer(raw, np.int16).astype(np.float32) / 32768
            t = time.time()
            segs, _ = model.transcribe(audio, language="ru", word_timestamps=True)
            words = [w.word for s in segs for w in (s.words or [])]
            rec("Whisper: TTS → текст", "ok" if words else "fail",
                f"{len(words)} сөз, {time.time()-t:.1f} сек: {''.join(words)[:70]}")
    except Exception as e:
        rec("Whisper", "fail", err(e))


def main() -> int:
    only_tts = os.environ.get("PROBE_ONLY") == "tts"
    if not only_tts:
        probe_runner()
    g = probe_gemini()
    if not only_tts:
        probe_pixabay()
    probe_whisper(g.get("tts_ok"))

    md = ["## 🔬 Мүмкүнчүлүктөрдү сынoo", "", "| Текшерүү | | Жыйынтык |", "|---|---|---|"]
    for name, status, note in RESULTS:
        md.append(f"| {name} | {dict(ok='✅', fail='❌', info='ℹ️')[status]} | {note.replace('|', '/')} |")
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        Path(summary).write_text("\n".join(md) + "\n", encoding="utf-8")
    Path("probe_results.json").write_text(json.dumps(
        {"results": RESULTS, "models": g.get("models", [])}, ensure_ascii=False, indent=1),
        encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
