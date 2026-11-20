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
import urllib.error
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

    STYLES = {
        "plain": None,
        "warm": ("Read the following Kyrgyz text aloud in a warm, natural, conversational tone, like an experienced "
                 "farmer kindly explaining to a friend. Use clear, correct Kyrgyz pronunciation (including ө, ү, ң), "
                 "natural pauses and lively intonation. Read ONLY the text after 'TEXT:', never these instructions.\nTEXT:\n"),
    }

    def __init__(self, voice=None, tries=3, wait=4, style=None, allow_fallback=True):
        self.voice = voice or os.environ.get("POULTRY_TTS_VOICE", "Kore")
        self.tries, self.wait = tries, wait
        # False: эскирээк запас моделге (кыргызча начарыраак) ЖАШЫРЫН өтпөйт — квота бүтсө ката берет
        self.models = config.TTS_MODELS if allow_fallback else config.TTS_MODELS[:1]
        self.style = style or "plain"
        self.last_model = None

    def synth(self, text, out_path):
        key = llm.api_key()
        prefix = self.STYLES.get(self.style) or ""
        body = json.dumps({"contents": [{"parts": [{"text": prefix + text}]}], "generationConfig": {
            "responseModalities": ["AUDIO"],
            "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": self.voice}}}}}).encode()
        errors = []
        for m in self.models:
            for attempt in range(self.tries):
                try:
                    req = urllib.request.Request(f"{config.API_BASE}/models/{m}:generateContent", body,
                                                 {"Content-Type": "application/json", "x-goog-api-key": key})
                    data = json.load(urllib.request.urlopen(req, timeout=120))
                    cand = (data.get("candidates") or [{}])[0]
                    parts = (cand.get("content") or {}).get("parts") or []
                    if not parts or "inlineData" not in parts[0]:
                        # аудиосуз жооп (finishReason=OTHER ж.б.) — кокус болот, кайра аракет
                        raise VideoError(f"аудио жок (finishReason={cand.get('finishReason')})")
                    pcm = base64.b64decode(parts[0]["inlineData"]["data"])
                    with wave.open(out_path, "wb") as w:
                        w.setnchannels(1); w.setsampwidth(2); w.setframerate(24000); w.writeframes(pcm)
                    self.last_model = m
                    log.get().info("TTS ✅ модель=%s үн=%s стиль=%s аракет=%d%s", m, self.voice, self.style, attempt + 1,
                                   f" (мурунку каталар: {errors})" if errors else "")
                    return out_path
                except urllib.error.HTTPError as e:  # ачкыч логго чыкпайт
                    errors.append(f"{m}#{attempt + 1}: HTTP {e.code} {e.read().decode('utf-8', 'replace')[:120]}")
                    if e.code not in (429, 500, 503):
                        break
                except Exception as e:
                    errors.append(f"{m}#{attempt + 1}: {type(e).__name__}: {str(e)[:120]}")
                time.sleep(self.wait * (attempt + 1))
        quota = any("HTTP 429" in e for e in errors)
        raise VideoError(("TTS квотасы бүттү (эртең кайра аракет кылыңыз). " if quota else "TTS ишке ашкан жок: ")
                         + " | ".join(errors)[:600])


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


class KaniTTS:
    """Kani TTS (NineNineSix, Apache-2.0) — бекер, кыргызча модель. Модель бир жолу жүктөлөт.
    Оор китепканалар (torch, nemo) керек: requirements-kani.txt. ref_audio берилсе (kani-tts-2) үн клондолот —
    үн ээсинин уруксаты менен гана."""

    def __init__(self, model="nineninesix/kani-tts-400m-ky", ref_audio=None, consent=False, loader=None):
        if ref_audio and not consent:
            raise VideoError("Клон үчүн үн ээсинин уруксаты тастыкталган эмес (voice.owner_consent_confirmed)")
        self.model_name, self.ref = model, ref_audio
        self._loader, self._model, self._emb = loader, None, None

    def _load(self):
        if self._model is None:
            if self._loader:
                self._model = self._loader(self.model_name)
            else:
                try:
                    from kani_tts import KaniTTS as _K
                except ImportError:
                    raise VideoError("kani-tts орнотулган эмес: pip install -r poultry_ig_agent/requirements-kani.txt")
                self._model = _K(self.model_name)
                if self.ref:
                    from kani_tts import SpeakerEmbedder
                    self._emb = SpeakerEmbedder(device="cpu").embed_audio_file(self.ref)
        return self._model

    def synth(self, text, out_path):
        m = self._load()
        kw = {"speaker_emb": self._emb} if self._emb is not None else {}
        audio, _ = m(text, **kw)
        raw = out_path + ".kani.wav"
        m.save_audio(audio, raw)
        _run(["ffmpeg", "-y", "-v", "error", "-i", raw, "-ar", "24000", "-ac", "1", out_path])
        return out_path


def drive_direct(url):
    """Google Drive бөлүшүү шилтемесин түз жүктөө шилтемесине айлантат."""
    import re
    m = re.search(r"/file/d/([\w-]+)", url) or re.search(r"[?&]id=([\w-]+)", url)
    if "drive.google.com" in url and m:
        return f"https://drive.google.com/uc?export=download&id={m.group(1)}"
    return url


class FileTTS:
    """Даяр үн файлы (мис. Akylai'да клондолгон үн менен жасалган mp3/wav). Текстти өзү окубайт —
    файл ушул Reel'дин voiceover.txt текстинен жасалган болушу керек. Файл репозиторийге САКТАЛБАЙТ."""

    def __init__(self, source, consent=False):
        if not consent:
            raise VideoError("Үн ээсинин уруксаты тастыкталган эмес (settings.json → voice.owner_consent_confirmed)")
        if not source:
            raise VideoError("Үн файлынын шилтемеси/жолу берилген жок")
        self.source = source

    def synth(self, text, out_path):
        src = self.source
        if src.startswith("http"):
            raw = out_path + ".src"
            req = urllib.request.Request(drive_direct(src), headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=180) as r, open(raw, "wb") as f:
                data = r.read()
                if data[:15].lower().startswith((b"<!doctype", b"<html")):
                    raise VideoError("Шилтеме аудио эмес, HTML берди: Drive'да «Шилтемеси бар бардык адамдар» уруксатын коюңуз")
                f.write(data)
            src = raw
        _run(["ffmpeg", "-y", "-v", "error", "-i", src, "-ar", "24000", "-ac", "1", out_path])
        return out_path


def tts_from_settings(cfg=None, voice_file=None):
    if voice_file:
        v = (cfg or settings.load_settings())["voice"]
        return FileTTS(voice_file, v.get("owner_consent_confirmed", False))
    """settings.json'догу voice.provider боюнча диктор тандалат (дайыма бир эле үн)."""
    v = (cfg or settings.load_settings())["voice"]
    if v.get("provider") == "kani":
        return KaniTTS(v.get("kani_model", "nineninesix/kani-tts-400m-ky"), v.get("kani_ref_audio"),
                       v.get("owner_consent_confirmed", False))
    if v.get("provider", "gemini") == "gemini":
        t = GeminiTTS(v.get("gemini_voice"), style=v.get("gemini_style"),
                      allow_fallback=v.get("allow_tts_fallback", False))
        ref = v.get("reference_sample")
        if ref:
            ref = ref if os.path.isabs(ref) else os.path.join(os.path.dirname(__file__), ref)
            if os.path.exists(ref):
                return ConsistentTTS(t, ref, v.get("consistency_tolerance", 0.10))
        return t
    if v.get("provider") == "elevenlabs":
        return ElevenLabsTTS(v.get("elevenlabs_voice_id"), v.get("elevenlabs_model", "eleven_v3"),
                             v.get("owner_consent_confirmed", False))
    return GeminiTTS()


def voice_signature(path):
    """Үндүн жөнөкөй 'колу': (F0 медианасы Гц, спектрдик центроид Гц). Бир эле үн экенин болжолдуу салыштыруу үчүн."""
    import numpy as np
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", path, "-ac", "1", "-ar", "16000", "-f", "s16le", "-"],
                         capture_output=True, check=True).stdout
    x = np.frombuffer(raw, dtype=np.int16).astype(float)
    sr, fr, f0, cent = 16000, 640, [], []
    win = np.hanning(fr); freqs = np.fft.rfftfreq(fr, 1 / sr)
    for i in range(0, len(x) - fr, fr // 2):
        s = x[i:i + fr] - x[i:i + fr].mean()
        if np.sqrt((s ** 2).mean()) < 900:
            continue
        w = s * win
        ac = np.correlate(w, w, "full")[fr - 1:]
        lo, hi = int(sr / 400), int(sr / 60)
        k = lo + int(np.argmax(ac[lo:hi]))
        if ac[k] > 0.45 * ac[0]:
            f0.append(sr / k)
        X = np.abs(np.fft.rfft(w)); cent.append(float((X * freqs).sum() / X.sum()))
    if not f0 or not cent:
        return None
    return float(np.median(f0)), float(np.median(cent))


def signature_distance(a, b):
    """Салыштырмалуу айырма (0 = окшош). Тембр (центроид) — негизги белги; F0 интонацияга жараша көбүрөөк
    өзгөрөт, ошондуктан анын салмагы жарым. Калибровка (2026-11-20, колдонуучунун кулагы): 1/3 ✓ 6.5%,
    2/3 ✓ 9.5%, 3/3 ✗ 13.8% (башка үн угулган)."""
    return max(abs(a[1] - b[1]) / b[1], 0.5 * abs(a[0] - b[0]) / b[0])


class ConsistentTTS:
    """TTS'ти орой үлгүгө салыштырат: айырма чоң болсо кайра чыгарат, эң жакынын тандайт.
    Gemini'нин стиль нускамасы ар бир чыгарылышта үндүн тембрин бир аз өзгөртүшү мүмкүн."""

    def __init__(self, tts, reference, tolerance=0.10, max_tries=3):
        self.tts, self.ref_path, self.tol, self.max_tries = tts, reference, tolerance, max_tries
        self.voice, self.style = getattr(tts, "voice", None), getattr(tts, "style", None)
        self.last_model, self.report = None, []

    def synth(self, text, out_path):
        ref = voice_signature(self.ref_path)
        best = None
        for i in range(self.max_tries):
            cand = f"{out_path}.try{i}.wav"
            self.tts.synth(text, cand)
            self.last_model = getattr(self.tts, "last_model", None)
            sig = voice_signature(cand)
            d = signature_distance(sig, ref) if (sig and ref) else 0.0
            self.report.append({"try": i + 1, "f0": round(sig[0]) if sig else None,
                                "centroid": round(sig[1]) if sig else None, "distance": round(d, 3)})
            log.get().info("Үн шайкештиги %d: F0=%s центроид=%s айырма=%.0f%% (чек %.0f%%)", i + 1,
                           self.report[-1]["f0"], self.report[-1]["centroid"], d * 100, self.tol * 100)
            if best is None or d < best[0]:
                best = (d, cand)
            if d <= self.tol:
                break
        os.replace(best[1], out_path)
        for i in range(self.max_tries):
            p = f"{out_path}.try{i}.wav"
            if os.path.exists(p):
                os.remove(p)
        if best[0] > self.tol:
            log.get().warning("Үн үлгүдөн %.0f%% айырмаланат — эң жакыны алынды, кулак менен текшериңиз", best[0] * 100)
        return out_path


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
        if s.get("source") == "stock":          # мурунку build'дин сток кадры — кайра сток/реал изделет, AI'ге ӨТПӨЙТ
            s["source"] = "real"
            s.pop("file", None); s.pop("stock", None)
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
    chunks = [" ".join(words[i:i + 4]) for i in range(0, len(words), 4)] or [""]
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
    for i, (text, y0, size) in enumerate([(onscreen, 0.12, 64), (label, 0.04, 36)]):
        if not text:
            continue
        for j, line in enumerate(textwrap.wrap(text, 24)[:4]):   # ар сап өзүнчө: ffmpeg 7+ '\n'ди □ кылып көрсөтөт
            tf = os.path.join(tmp, f"t_{os.path.basename(out)}_{i}_{j}.txt")
            with open(tf, "w", encoding="utf-8") as f:
                f.write(line)
            y = f"h*{y0}+{j * int(size * 1.45)}"
            vf.append(f"drawtext=fontfile={FONT}:textfile={tf}:fontsize={size}:fontcolor=white:box=1:"
                      f"boxcolor=black@0.55:boxborderw=14:x=(w-text_w)/2:y={y}")
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
    style = "FontName=DejaVu Sans,Bold=1,FontSize=11,PrimaryColour=&HFFFFFF&,OutlineColour=&H000000&,BorderStyle=1,Outline=2,Alignment=2,MarginV=78"  # 288-масштаб: ≈520px ылдыйдан — Instagram'дын caption/баскыч аймагынан жогору (y<1440)
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


def fill_stock(shots, missing, stock, work):
    """Өз видеосу жок кадрларды стоктон толуктайт (real_farm эмес посттор үчүн гана чакырылат)."""
    lics, still = [], []
    for s in shots:
        if s["n"] in missing:
            try:
                path, lic = stock.fetch(s.get("visual", ""), float(s.get("duration", 4)), os.path.join(work, f"stock_{s['n']}.mp4"))
                s.update(source="stock", file=path, stock=lic)
                lics.append({"shot": s["n"], **lic})
            except Exception as e:
                log.get().warning("Кадр %s үчүн сток табылган жок: %s", s["n"], e)
                still.append(s["n"])
    return lics, still


def fit_durations(shots, voice_seconds, pad=0.5, max_shot=8.0):
    """Кадрлардын узундугун диктордун узундугуна пропорционалдуу тууралайт (акыркы кадр гана узарбасын)."""
    plan = sum(float(s.get("duration", 3)) for s in shots) or 1
    target = voice_seconds + pad
    if target > plan:
        k = target / plan
        for s in shots:
            s["duration"] = round(min(float(s.get("duration", 3)) * k, max_shot), 2)
        rest = target - sum(s["duration"] for s in shots)
        if rest > 0.05:
            shots[-1]["duration"] = round(shots[-1]["duration"] + rest, 2)
    return shots


def build(post, post_dir, veo, tts, assets_dir, allow_ai_fallback=False, niche=None, stock=None):
    """Толук Reel. Кайтарат dict: status = ready | needs_footage | failed."""
    L = log.get()
    cfg = settings.load_settings()["video"]
    lang = post.get("lang", "ky")
    shots, missing = resolve_shots(post, assets_dir, allow_ai_fallback)
    licenses = []
    if missing and stock is not None and post.get("content_type") != "real_farm":
        work0 = os.path.join(post_dir, "work")
        os.makedirs(work0, exist_ok=True)
        licenses, missing = fill_stock(shots, missing, stock, work0)
    if missing:
        L.warning("Реалдуу видео жетишпейт: кадр %s → assets/real/ ичине файл кошуңуз", missing)
        return {"status": "needs_footage", "missing_real_shots": missing, "shots": shots}
    os.makedirs(post_dir, exist_ok=True)
    work = os.path.join(post_dir, "work")
    os.makedirs(work, exist_ok=True)
    try:
        voice = tts.synth(post["voiceover"], os.path.join(work, "voice.wav"))
        vlen = duration(voice)
        fit_durations(shots, vlen)
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
    if licenses:
        with open(os.path.join(post_dir, "licenses.json"), "w", encoding="utf-8") as f:
            json.dump(licenses, f, ensure_ascii=False, indent=2)
    return {"status": "ready", "path": out, "tts_model": getattr(tts, "last_model", None),
            "ai_shots": sum(s["source"] == "ai" for s in shots),
            "stock_shots": sum(s["source"] == "stock" for s in shots), "shots": shots, "licenses": licenses}
