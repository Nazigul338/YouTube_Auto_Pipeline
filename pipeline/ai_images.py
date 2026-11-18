"""AI-сүрөттөр (Gemini API, СЫНАК режими): сценарийдин маанисине жараша оригиналдуу 16:9 сүрөттөр.

Принциптер:
  - Gemini API СҮРӨТ гана жаратат (Veo/видео колдонулбайт).
  - Негизги материал — Pixabay/Pexels видеолору. AI-сүрөт сток туура келбеген (AI баасы ≤2/5) же
    маанилүү (сахнанын биринчи) кадрларга гана коюлат; катар эки AI-сүрөт болбойт (слайд-шоу болбосун).
  - Ар видеонун өз визуалдык стили (`STYLES`) — мурунку видеонукун кайталабайт.
  - Чыгым көзөмөлү: бир видеого ≤ YTA_AI_IMAGE_MAX сүрөт жана ≤ YTA_AI_IMAGE_BUDGET доллар; ар сүрөттүн баасы
    `PRICE_USD` боюнча эсептелет, отчет `clips/ai_images.json`.
  - Кэш: Drive `AI_Images/` + `_ai_images.json` индекси. Ошол эле видеону кайра иштеткенде сүрөт кайра
    ЖАРАТЫЛБАЙТ (акча кетпейт). Башка видеонун сүрөтү колдонулбайт (кайталанбасын).
  - Ката/квота (429, billing жок, 5xx) → AI-сүрөттөр токтойт, кадрлар сток бойдон калат. Видео токтобойт.
  - Ачкыч GitHub Secrets'теги GOOGLE_API_KEY гана; логго жазылбайт.

Режим: `YTA_AI_IMAGES=1` + cinematic СЫНАК режими (YouTube_Auto_TEST). Production'да өчүк.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

FOLDER = "AI_Images"
INDEX = "_ai_images.json"

# Gemini API баалары (USD / 1 сүрөт, 2026-11; ai.google.dev/pricing). Белгисиз модель — эң кымбаты менен эсептелет.
PRICE_USD = {
    "gemini-2.5-flash-image": 0.039,
    "gemini-2.5-flash-image-preview": 0.039,
    "gemini-3-pro-image-preview": 0.134,
    "imagen-4.0-fast-generate-001": 0.02,
    "imagen-4.0-generate-001": 0.04,
}
UNKNOWN_PRICE = 0.134
DEFAULT_MODELS = ("gemini-2.5-flash-image",)
DEFAULT_MAX = 12
DEFAULT_BUDGET = 0.50

LICENSE = "AI-generated — Google Gemini API (Generative AI Additional Terms; SynthID watermark)"
LICENSE_URL = "https://ai.google.dev/gemini-api/terms"

# Ар видеонун визуалдык тили (тандоо видео ID'ге жараша, мурунку видеонукунан айырмаланат)
STYLES = [
    "cinematic photograph, anamorphic lens, shallow depth of field, soft natural light, subtle film grain",
    "moody chiaroscuro photograph, deep shadows, single warm light source, dramatic contrast",
    "soft dreamy photograph, morning haze, pastel tones, gentle bokeh, calm atmosphere",
    "epic wide landscape photograph, golden hour, volumetric light rays, sense of scale",
    "minimalist fine-art photograph, negative space, muted palette, symbolic composition",
    "documentary-style photograph, candid moment, natural colors, realistic textures",
]

PROMPT_RULES = (
    "Write ONE English prompt per item for an image generator. The image must visually express the MEANING "
    "of the narration (a concrete visual metaphor or a scene), not illustrate words literally. Rules: "
    "widescreen 16:9 composition; keep the lower third calm and uncluttered (subtitles go there); "
    "NO text, letters, numbers, captions, logos, watermarks, brands; NO celebrities, NO real or identifiable "
    "people, NO famous places that could mislead; anonymous people only from behind, in silhouette or far away; "
    "no violence, no gore, nothing sexual, nothing shocking (YouTube advertiser-friendly). "
    "Each prompt 25-45 words, ends with the given visual style. Return JSON array of objects "
    '{"i": <item number>, "prompt": "..."} only.'
)


def requested() -> bool:
    return os.environ.get("YTA_AI_IMAGES", "").strip() in ("1", "true", "yes")


def enabled(store=None) -> bool:
    from . import cinematic

    return requested() and cinematic.enabled(store)


def price(model: str) -> float:
    return PRICE_USD.get(model, UNKNOWN_PRICE)


def models() -> list[str]:
    env = os.environ.get("YTA_AI_IMAGE_MODELS", "").strip()
    return [m.strip() for m in env.split(",") if m.strip()] if env else list(DEFAULT_MODELS)


# ---------------------------------------------------------------- бюджет
@dataclass
class Budget:
    max_images: int = DEFAULT_MAX
    max_usd: float = DEFAULT_BUDGET
    spent: float = 0.0
    generated: int = 0
    cached: int = 0
    failed: int = 0
    stopped: str = ""
    items: list = field(default_factory=list)

    @classmethod
    def from_env(cls) -> "Budget":
        def num(name, default, cast):
            try:
                return cast(os.environ.get(name, "") or default)
            except ValueError:
                return default
        return cls(max_images=num("YTA_AI_IMAGE_MAX", DEFAULT_MAX, int),
                   max_usd=num("YTA_AI_IMAGE_BUDGET", DEFAULT_BUDGET, float))

    def can(self, model: str) -> bool:
        if self.stopped:
            return False
        if self.generated + self.cached >= self.max_images:
            return False
        return self.spent + price(model) <= self.max_usd + 1e-9

    def add(self, model: str) -> None:
        self.generated += 1
        self.spent = round(self.spent + price(model), 4)

    def report(self) -> dict:
        return {"generated": self.generated, "cached": self.cached, "failed": self.failed,
                "cost_usd": round(self.spent, 4), "max_images": self.max_images, "budget_usd": self.max_usd,
                "stopped": self.stopped, "items": self.items}


# ---------------------------------------------------------------- стиль жана кадр тандоо
def pick_style(video_id: str, registry: dict) -> str:
    """Видеонун стили: ID боюнча туруктуу, бирок акыркы видеонукунан башка."""
    prev = [v.get("ai_style") for k, v in sorted((registry.get("videos") or {}).items())
            if k != video_id and v.get("ai_style")]
    own = ((registry.get("videos") or {}).get(video_id) or {}).get("ai_style")
    if own in STYLES:
        return own
    start = int(hashlib.md5(video_id.encode()).hexdigest(), 16) % len(STYLES)
    for k in range(len(STYLES)):
        s = STYLES[(start + k) % len(STYLES)]
        if not prev or s != prev[-1]:
            return s
    return STYLES[start]


def select_slots(shots: list[dict], scores: dict[int, int], limit: int, low: int = 2) -> list[int]:
    """AI-сүрөт коюла турган кадрлар: (1) сток мааниге туура келбеген (баа ≤ low) — эң начары биринчи;
    (2) калган орунга — баасы 3 болгон сахнанын биринчи кадрлары. Кошуна эки кадр AI болбойт,
    бир сахнада ≤2."""
    if limit <= 0:
        return []
    first = {sh["i"] for k, sh in enumerate(shots) if k == 0 or shots[k - 1]["scene"] != sh["scene"]}
    bad = sorted((i for i, s in scores.items() if s <= low), key=lambda i: (scores[i], i))
    mid = sorted(i for i, s in scores.items() if s == low + 1 and i in first)
    scene_of = {sh["i"]: sh["scene"] for sh in shots}
    chosen: list[int] = []
    per_scene: dict = {}
    for i in bad + mid:
        if len(chosen) >= limit:
            break
        if any(abs(i - j) <= 1 for j in chosen):
            continue
        sc = scene_of.get(i)
        if per_scene.get(sc, 0) >= 2:
            continue
        chosen.append(i)
        per_scene[sc] = per_scene.get(sc, 0) + 1
    return sorted(chosen)


def write_prompts(gemini, items: list[tuple[int, str]], style: str) -> dict[int, str]:
    """{кадр: prompt} — бир Gemini текст суроосу менен (бардык кадрлар бирге — арзан)."""
    if not items:
        return {}
    lines = [f"Item {i}: narration (Russian): {text[:400]}" for i, text in items]
    prompt = f"{PROMPT_RULES}\nVisual style for ALL prompts: {style}\n\n" + "\n".join(lines)
    data = gemini.json(prompt, purpose="ai_image_prompts", temperature=0.8)
    out = {}
    for d in data if isinstance(data, list) else []:
        try:
            i, p = int(d["i"]), str(d["prompt"]).strip()
        except (KeyError, TypeError, ValueError):
            continue
        if p:
            out[i] = p if style.split(",")[0] in p else f"{p}, {style}"
    return out


def cache_key(model: str, prompt: str) -> str:
    return hashlib.sha1(f"{model}|{prompt}".encode()).hexdigest()[:16]


# ---------------------------------------------------------------- кэш (Drive AI_Images/)
class Cache:
    def __init__(self, store, log: Callable[[str], None] = print):
        self.store = store
        self.log = log
        self.index: dict = {}
        if store is not None:
            try:
                raw = store.read_text(FOLDER, INDEX)
                self.index = json.loads(raw) if raw else {}
            except Exception as e:
                self.log(f"   ⚠️ AI-сүрөт индекси окулган жок ({type(e).__name__}) — жаңысы түзүлөт")

    def owner(self, key: str) -> str | None:
        return (self.index.get(key) or {}).get("video_id")

    def get(self, key: str, video_id: str, dest: Path) -> bool:
        """Ошол эле видеонун мурун жаратылган сүрөтү гана кайра колдонулат."""
        e = self.index.get(key)
        if not e or e.get("video_id") != video_id or self.store is None:
            return False
        try:
            return bool(self.store.fetch(FOLDER, e["file"], dest))
        except Exception:
            return False

    def put(self, key: str, video_id: str, path: Path, meta: dict) -> None:
        self.index[key] = {"video_id": video_id, "file": path.name, "created": time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                                                                              time.gmtime()), **meta}
        if self.store is not None:
            self.store.publish(FOLDER, path, path.name)

    def save(self, tmp: Path) -> None:
        if self.store is None:
            return
        p = tmp / INDEX
        p.write_text(json.dumps(self.index, ensure_ascii=False, indent=1), encoding="utf-8")
        self.store.publish(FOLDER, p, INDEX)


# ---------------------------------------------------------------- генерация
def generate_bytes(client, model: str, prompt: str) -> bytes:
    """Бир сүрөт (PNG/JPEG байттары). 16:9 модельдин өзүнө айтылат."""
    from google.genai import types

    if model.startswith("imagen"):
        r = client.models.generate_images(model=model, prompt=prompt, config=types.GenerateImagesConfig(
            number_of_images=1, aspect_ratio="16:9"))
        imgs = r.generated_images or []
        if not imgs:
            raise ValueError("сүрөт келген жок (коопсуздук чыпкасы же бош жооп)")
        return imgs[0].image.image_bytes
    cfg = types.GenerateContentConfig(response_modalities=["IMAGE"],
                                      image_config=types.ImageConfig(aspect_ratio="16:9"))
    r = client.models.generate_content(model=model, contents=prompt, config=cfg)
    for cand in r.candidates or []:
        for part in (getattr(cand.content, "parts", None) or []):
            data = getattr(getattr(part, "inline_data", None), "data", None)
            if data:
                return data
    raise ValueError("сүрөт келген жок (коопсуздук чыпкасы же бош жооп)")


def to_frame(raw: Path, out: Path) -> Path:
    """1920×1080 JPEG (кесилип толтурулат — кара тилке жок)."""
    r = subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(raw), "-vf",
                        "scale=1920:1080:force_original_aspect_ratio=increase:flags=lanczos,crop=1920:1080,setsar=1",
                        "-frames:v", "1", "-q:v", "2", str(out)], capture_output=True, text=True, timeout=120)
    if r.returncode != 0 or not out.exists():
        raise ValueError(f"сүрөт ачылган жок: {r.stderr[-200:]}")
    return out


def make_asset(key: str, model: str, prompt: str):
    from .stock import Asset

    return Asset(source="gemini", kind="image", id=f"gemini:{key}", url="", width=1920, height=1080,
                 duration=0.0, page_url="", author=f"AI-generated ({model})", license=LICENSE,
                 license_url=LICENSE_URL, tags=prompt[:300], query=prompt[:200],
                 extra={"model": model, "prompt": prompt})


def produce(gemini, cache: Cache, budget: Budget, video_id: str, prompt: str, dest_dir: Path,
            log: Callable[[str], None] = print) -> tuple[Any, Path] | None:
    """Бир кадр үчүн AI-сүрөт: кэштен же жаңы. (Asset, jpg) же None (бюджет/ката → сток калат)."""
    for model in models():
        key = cache_key(model, prompt)
        out = dest_dir / f"gemini_{key}.jpg"
        if cache.get(key, video_id, out):
            budget.cached += 1
            budget.items.append({"key": key, "model": model, "usd": 0.0, "cached": True})
            return make_asset(key, model, prompt), out
        if cache.owner(key) not in (None, video_id):        # башка видеонуку — кайталабайбыз
            prompt = prompt + ", alternative composition"
            key = cache_key(model, prompt)
            out = dest_dir / f"gemini_{key}.jpg"
        if not budget.can(model):
            if not budget.stopped and budget.spent + price(model) > budget.max_usd:
                budget.stopped = f"бюджет чеги ${budget.max_usd:.2f}"
            return None
        raw = dest_dir / f"gemini_{key}.raw"

        def fn(m: str, _p=prompt) -> bytes:
            return generate_bytes(gemini.client, m, _p)

        try:
            data = gemini._call([model], fn, "ai_image", attempts=2)
        except Exception as e:
            from .errors import QuotaExhausted

            budget.failed += 1
            msg = str(e)
            if isinstance(e, QuotaExhausted) or "429" in msg or "RESOURCE_EXHAUSTED" in msg or "billing" in msg.lower():
                budget.stopped = "квота/billing (429) — AI-сүрөттөр токтоду, сток калат"
            elif budget.failed >= 3:
                budget.stopped = f"катар каталар ({type(e).__name__})"
            log(f"   ⚠️ AI-сүрөт ({model}) жаратылган жок: {type(e).__name__}: {msg[:160]}")
            continue
        raw.write_bytes(data)
        try:
            to_frame(raw, out)
        finally:
            raw.unlink(missing_ok=True)
        budget.add(model)
        budget.items.append({"key": key, "model": model, "usd": price(model), "cached": False})
        cache.put(key, video_id, out, {"model": model, "prompt": prompt, "usd": price(model)})
        return make_asset(key, model, prompt), out
    return None
