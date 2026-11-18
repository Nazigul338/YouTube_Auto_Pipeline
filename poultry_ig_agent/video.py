"""AI жана реалдуу видео өндүрүшү: кадрлар → (Veo | сиздин файлдар) → диктор → субтитр → 9:16 монтаж.

Чындык эрежеси:
- Сиздин реалдуу видео/сүрөттөрүңүз assets/real/ папкасынан алынат; жетишпесе агент ЖАЛГАН «реал» жасабайт.
- AI кадрларына экранда жазуу + caption'го ачыктоо автоматтык кошулат.
- content_type=real_farm болсо AI кадр ЭЧ КАЧАН колдонулбайт.
ЧЫНЫГЫ Veo/TTS API менен али текшерилген эмес (тесттер жасалма провайдер менен). Модель аттары config'те.
"""
import base64
import glob
import json
import os
import subprocess
import tempfile
import textwrap
import time
import urllib.request
import wave

from . import config, llm, log, safety, settings

FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
VID_EXT = (".mp4", ".mov", ".m4v", ".webm")
IMG_EXT = (".jpg", ".jpeg", ".png")


class VideoError(RuntimeError):
    pass


def _run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode:
        raise VideoError("ffmpeg ката: " + r.stderr[-400:])
    return r.stdout


def duration(path):
    return float(_run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path]).strip())


# ---------------- провайдерлер ----------------
class VeoProvider:
    """Gemini API (Veo) — long-running операция. Модель: POULTRY_VEO_MODEL."""

    def __init__(self, model=None, poll=10, timeout=600):
        self.model = model or os.environ.get("POULTRY_VEO_MODEL", config.VEO_MODEL)
        self.poll, self.timeout = poll, timeout

    def generate(self, prompt, seconds, out_path):
        key = llm.api_key()
        h = {"Content-Type": "application/json", "x-goog-api-key": key}
        body = json.dumps({"instances": [{"prompt": prompt}], "parameters": {"aspectRatio": "9:16"}}).encode()
        req = urllib.request.Request(f"{config.API_BASE}/models/{self.model}:predictLongRunning", body, h)
        op = json.load(urllib.request.urlopen(req, timeout=60))["name"]
        t0 = time.time()
        while True:
            st = json.load(urllib.request.urlopen(urllib.request.Request(f"{config.API_BASE}/{op}", headers=h), timeout=60))
            if st.get("done"):
                break
            if time.time() - t0 > self.timeout:
                raise VideoError("Veo: күтүү убактысы бүттү")
            time.sleep(self.poll)
        try:
            uri = st["response"]["generateVideoResponse"]["generatedSamples"][0]["video"]["uri"]
        except (KeyError, IndexError):
            raise VideoError("Veo: видео кайтарылган жок (коопсуздук чыпкасы же ката): " + json.dumps(st)[:200])
        with urllib.request.urlopen(urllib.request.Request(uri, headers=h), timeout=300) as r, open(out_path, "wb") as f:
            f.write(r.read())
        return out_path


class GeminiTTS:
    """Gemini TTS → wav. Кыргызча айтылыш сапаты ASR (Whisper) менен текшерилиши керек, же башка провайдер алмаштырылат."""

    def __init__(self, voice=None):
        self.voice = voice or os.environ.get("POULTRY_TTS_VOICE", "Kore")

    def synth(self, text, out_path):
        key = llm.api_key()
        body = json.dumps({"contents": [{"parts": [{"text": text}]}], "generationConfig": {
            "responseModalities": ["AUDIO"],
            "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": self.voice}}}}}).encode()
        last = None
        for m in config.TTS_MODELS:
            try:
                req = urllib.request.Request(f"{config.API_BASE}/models/{m}:generateContent", body,
                                             {"Content-Type": "application/json", "x-goog-api-key": key})
                data = json.load(urllib.request.urlopen(req, timeout=120))
                pcm = base64.b64decode(data["candidates"][0]["content"]["parts"][0]["inlineData"]["data"])
                with wave.open(out_path, "wb") as w:
                    w.setnchannels(1); w.setsampwidth(2); w.setframerate(24000); w.writeframes(pcm)
                return out_path
            except Exception as e:  # кийинки моделге
                last = f"{m}: {type(e).__name__}"
        raise VideoError("TTS ишке ашкан жок: " + str(last))


class ElevenLabsTTS:
    """Клондолгон/тандалган ElevenLabs үнү. Ачкыч: POULTRY_ELEVENLABS_API_KEY (GitHub Secret).
    Үн ээсинин уруксаты settings.json → voice.owner_consent_confirmed=true болмоюнча ИШТЕБЕЙТ.
    Кыргызча сапаты модельге жараша (default eleven_v3) — чыныгы API менен текшерилген эмес."""

    API = "https://api.elevenlabs.io/v1/text-to-speech"

    def __init__(self, voice_id, model="eleven_v3", consent=False):
        if not consent:
            raise VideoError("Үн ээсинин уруксаты тастыкталган эмес (settings.json → voice.owner_consent_confirmed)")
        if not voice_id:
            raise VideoError("voice.elevenlabs_voice_id коюлган эмес")
        self.voice_id, self.model = voice_id, model

    def synth(self, text, out_path):
        key = os.environ.get("POULTRY_ELEVENLABS_API_KEY")
        if not key:
            raise VideoError("POULTRY_ELEVENLABS_API_KEY коюлган эмес")
        body = json.dumps({"text": text, "model_id": self.model}).encode()
        req = urllib.request.Request(f"{self.API}/{self.voice_id}?output_format=mp3_44100_128", body,
                                     {"Content-Type": "application/json", "xi-api-key": key, "Accept": "audio/mpeg"})
        mp3 = out_path + ".mp3"
        with urllib.request.urlopen(req, timeout=180) as r, open(mp3, "wb") as f:
            f.write(r.read())
        _run(["ffmpeg", "-y", "-v", "error", "-i", mp3, "-ar", "24000", "-ac", "1", out_path])
        return out_path


def tts_from_settings(cfg=None):
    """settings.json'догу voice.provider боюнча диктор тандалат (дайыма бир эле үн)."""
    v = (cfg or settings.load_settings())["voice"]
    if v.get("provider") == "elevenlabs":
        return ElevenLabsTTS(v.get("elevenlabs_voice_id"), v.get("elevenlabs_model", "eleven_v3"),
                             v.get("owner_consent_confirmed", False))
    return GeminiTTS()


# ---------------- кадрларды чечмелөө ----------------
def list_real_assets(assets_dir):
    files = sorted(f for f in glob.glob(os.path.join(assets_dir, "real", "*")) if f.lower().endswith(VID_EXT + IMG_EXT))
    return files


def resolve_shots(post, assets_dir, allow_ai_fallback=False):
    """Ар кадрга булак ыйгарат. Кайтарат (shots, missing_real). Реалдуу файл жок болсо AI'ге ЖАШЫРЫН алмаштырбайт."""
    real_only = post.get("content_type") == "real_farm"
    pool = list_real_assets(assets_dir)
    used, out, missing = set(), [], []
    for s in post["shots"]:
        s = dict(s)
        want_real = real_only or s.get("source") == "real"
        if want_real:
            f = next((p for p in pool if p not in used), None)
            if f:
                used.add(f); s.update(source="real", file=f)
            elif allow_ai_fallback and not real_only:
                s["source"] = "ai"
            else:
                s["source"] = "real"; missing.append(s["n"])
        else:
            s["source"] = "ai"
        out.append(s)
    return out, missing


def srt(voiceover, total):
    words = voiceover.split()
    chunks = [" ".join(words[i:i + 5]) for i in range(0, len(words), 5)] or [""]
    per, lines, t = total / len(chunks), [], 0.0
    ts = lambda x: f"{int(x // 3600):02}:{int(x % 3600 // 60):02}:{int(x % 60):02},{int(x % 1 * 1000):03}"
    for i, c in enumerate(chunks, 1):
        lines.append(f"{i}\n{ts(t)} --> {ts(t + per)}\n{c}\n")
        t += per
    return "\n".join(lines)


# ---------------- монтаж ----------------
def _escape(p):
    return p.replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")


def normalize(src, seconds, out, onscreen="", label="", tmp="."):
    vf = ["scale=1080:1920:force_original_aspect_ratio=increase", "crop=1080:1920", "fps=30", "setsar=1"]
    for i, (text, y, size) in enumerate([(onscreen, "h*0.10", 64), (label, "h*0.03", 36)]):
        if text:
            tf = os.path.join(tmp, f"t_{os.path.basename(out)}_{i}.txt")
            with open(tf, "w", encoding="utf-8") as f:
                f.write("\n".join(textwrap.wrap(text, 22)))
            vf.append(f"drawtext=fontfile={FONT}:textfile={tf}:fontsize={size}:fontcolor=white:box=1:"
                      f"boxcolor=black@0.55:boxborderw=18:x=(w-text_w)/2:y={y}")
    is_img = src.lower().endswith(IMG_EXT)
    pre = ["-loop", "1"] if is_img else ["-stream_loop", "-1"]
    _run(["ffmpeg", "-y", "-v", "error", *pre, "-i", src, "-t", f"{seconds:.2f}", "-an", "-vf", ",".join(vf),
          "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", out])
    return out


def assemble(clips, voice, srt_path, out, music=None):
    work = os.path.dirname(out)
    lst = os.path.join(work, "concat.txt")
    with open(lst, "w") as f:
        f.writelines(f"file '{os.path.abspath(c)}'\n" for c in clips)
    joined = os.path.join(work, "joined.mp4")
    _run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", lst, "-c", "copy", joined])
    total = duration(joined)
    style = "FontName=DejaVu Sans,Bold=1,FontSize=15,PrimaryColour=&HFFFFFF&,OutlineColour=&H000000&,BorderStyle=1,Outline=3,Alignment=2,MarginV=260"
    vf = f"subtitles='{_escape(srt_path)}':force_style='{style}'"
    cmd = ["ffmpeg", "-y", "-v", "error", "-i", joined, "-i", voice]
    if music:
        cmd += ["-stream_loop", "-1", "-i", music]
        fc = ("[1:a]aresample=44100[v];[2:a]volume=0.10,aresample=44100[m];"
              "[v][m]amix=inputs=2:duration=first:normalize=0,loudnorm=I=-16:TP=-1.5[a]")
    else:
        fc = "[1:a]aresample=44100,loudnorm=I=-16:TP=-1.5[a]"
    cmd += ["-filter_complex", fc, "-vf", vf, "-map", "0:v", "-map", "[a]", "-t", f"{total:.2f}", "-c:v", "libx264",
            "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", out]
    _run(cmd)
    return out


def build(post, post_dir, veo, tts, assets_dir, allow_ai_fallback=False, niche=None):
    """Толук Reel. Кайтарат dict: status = ready | needs_footage | failed."""
    L = log.get()
    cfg = settings.load_settings()["video"]
    lang = post.get("lang", "ky")
    shots, missing = resolve_shots(post, assets_dir, allow_ai_fallback)
    if missing:
        L.warning("Реалдуу видео жетишпейт: кадр %s → assets/real/ ичине файл кошуңуз", missing)
        return {"status": "needs_footage", "missing_real_shots": missing, "shots": shots}
    os.makedirs(post_dir, exist_ok=True)
    work = os.path.join(post_dir, "work")
    os.makedirs(work, exist_ok=True)
    try:
        voice = tts.synth(post["voiceover"], os.path.join(work, "voice.wav"))
        vlen = duration(voice)
        plan = sum(float(s.get("duration", 3)) for s in shots)
        if vlen + 0.4 > plan:                       # диктор узунураак болсо акыркы кадрды узарт
            shots[-1]["duration"] = float(shots[-1].get("duration", 3)) + (vlen + 0.4 - plan)
        clips = []
        style = niche.style_bible if niche else ""
        for s in shots:
            sec = float(s.get("duration", 3))
            if s["source"] == "ai":
                src = veo.generate(f"{style} Scene: {s['visual']}", sec, os.path.join(work, f"ai_{s['n']}.mp4"))
            else:
                src = s["file"]
            label = cfg["ai_label"][lang] if s["source"] == "ai" else ""
            clips.append(normalize(src, sec, os.path.join(work, f"c{s['n']}.mp4"), s.get("onscreen", ""), label, work))
        total = sum(float(s.get("duration", 3)) for s in shots)
        sp = os.path.join(work, "subs.srt")
        with open(sp, "w", encoding="utf-8") as f:
            f.write(srt(post["voiceover"], total))
        music = next(iter(sorted(glob.glob(os.path.join(assets_dir, "music", "*.mp3")) + glob.glob(os.path.join(assets_dir, "music", "*.wav")))), None)
        out = assemble(clips, voice, sp, os.path.join(post_dir, "final.mp4"), music)
    except Exception as e:
        L.error("Видео жасоо ката: %s", e)
        return {"status": "failed", "error": str(e)}
    with open(os.path.join(post_dir, "shots.json"), "w", encoding="utf-8") as f:
        json.dump(shots, f, ensure_ascii=False, indent=2)
    return {"status": "ready", "path": out, "ai_shots": sum(s["source"] == "ai" for s in shots), "shots": shots}
