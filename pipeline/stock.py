"""Сток-материалдар: Pixabay (негизги) жана Pexels (ачкыч болсо).

Probe жыйынтыгы: Pixabay лимити 100 суроо / 60 сек; видеолордо `small` = 1920×1080.
Лицензия: Pixabay Content License — коммерциялык колдонууга болот, автор көрсөтүү
милдеттүү эмес, бирок өзгөртүлбөгөн түрдө сатууга/таратууга болбойт. Ар клиптин
булагы, автору жана шилтемеси licenses.json'го жазылат.
"""

from __future__ import annotations

import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

import requests

from .errors import StageError, TransientError

# Бренддер/логотиптер (товардык белги — монетизацияга тобокел): тегинде/шилтемесинде болсо клип алынбайт.
BRAND_WORDS = frozenset("""
youtube logo logos trademark brand facebook instagram tiktok twitter whatsapp telegram snapchat
google iphone samsung microsoft android netflix spotify nike adidas
cocacola pepsi mcdonalds starbucks tesla bmw mercedes ferrari bitcoin
""".split())


def brand_risk(text: str) -> bool:
    """Тег же шилтеме бренд/логотипти көрсөтсө True."""
    w = [x for x in re.split(r"[^a-z0-9]+", (text or "").lower()) if x]
    words = set(w) | {a + b for a, b in zip(w, w[1:])}   # «coca-cola» → «cocacola»
    return bool(words & BRAND_WORDS)


PIXABAY_LICENSE = ("Pixabay Content License", "https://pixabay.com/service/license-summary/")
PEXELS_LICENSE = ("Pexels License", "https://www.pexels.com/license/")


@dataclass
class Asset:
    source: str            # pixabay / pexels
    kind: str              # video / image
    id: str                # "pixabay:12345"
    url: str               # жүктөө шилтемеси
    width: int
    height: int
    duration: float        # сүрөт үчүн 0
    page_url: str
    author: str
    license: str
    license_url: str
    tags: str = ""
    query: str = ""
    extra: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


class Stock:
    def __init__(self, pixabay_key: str, pexels_key: str | None = None,
                 min_interval: float = 0.7, sleep=time.sleep):
        self.pixabay_key = pixabay_key
        self.pexels_key = pexels_key
        self.min_interval = min_interval
        self.sleep = sleep
        self._last = 0.0
        self.session = requests.Session()

    def _get(self, url: str, params: dict, headers: dict | None = None) -> dict:
        for attempt in range(4):
            wait = self.min_interval - (time.time() - self._last)
            if wait > 0:
                self.sleep(wait)
            self._last = time.time()
            try:
                r = self.session.get(url, params=params, headers=headers or {}, timeout=30)
            except requests.RequestException as e:
                if attempt == 3:
                    raise TransientError(f"Сток API'ге туташуу ишке ашкан жок: {type(e).__name__}")
                self.sleep(5 * (attempt + 1))
                continue
            if r.status_code == 429 or r.status_code >= 500:
                self.sleep(20 * (attempt + 1))
                continue
            if r.status_code != 200:
                raise StageError(f"Сток API: HTTP {r.status_code} — {r.text[:120]}")
            return r.json()
        raise TransientError("Сток API лимити: кийинчерээк кайра аракет кылыңыз")

    # -------------------------------------------------------------- videos
    def videos(self, query: str, min_duration: float = 3.0, page: int = 1) -> list[Asset]:
        out = self._pixabay_videos(query, min_duration, page)
        if self.pexels_key:
            try:
                out += self._pexels_videos(query, min_duration, page)
            except StageError:
                pass
        return out

    def _pixabay_videos(self, query: str, min_duration: float, page: int = 1) -> list[Asset]:
        d = self._get("https://pixabay.com/api/videos/",
                      {"key": self.pixabay_key, "q": query[:100], "per_page": 50,
                       "page": page, "safesearch": "true"})
        out = []
        for h in d.get("hits", []):
            vids = h.get("videos", {})
            pick = None
            for size in ("small", "medium", "large"):  # эң кичине ≥1920 вариант
                v = vids.get(size) or {}
                if (v.get("width") or 0) >= 1920 and (v.get("height") or 0) >= 1080 and v.get("url"):
                    pick = v
                    break
            if not pick or pick["width"] <= pick["height"] or h.get("duration", 0) < min_duration:
                continue
            if brand_risk(h.get("tags", "")):
                continue
            out.append(Asset("pixabay", "video", f"pixabay:{h['id']}", pick["url"], pick["width"],
                             pick["height"], float(h.get("duration", 0)), h.get("pageURL", ""),
                             h.get("user", ""), *PIXABAY_LICENSE, tags=h.get("tags", ""),
                             query=query))
        return out

    def _pexels_videos(self, query: str, min_duration: float, page: int = 1) -> list[Asset]:
        d = self._get("https://api.pexels.com/videos/search",
                      {"query": query, "per_page": 40, "page": page, "orientation": "landscape"},
                      {"Authorization": self.pexels_key})
        out = []
        for v in d.get("videos", []):
            files = sorted([f for f in v.get("video_files", [])
                            if (f.get("width") or 0) >= 1920 and (f.get("height") or 0) >= 1080],
                           key=lambda f: f["width"])
            if not files or v.get("duration", 0) < min_duration:
                continue
            if brand_risk(v.get("url", "")):   # Pexels: тег жок, шилтемеде сүрөттөмө бар
                continue
            f = files[0]
            out.append(Asset("pexels", "video", f"pexels:{v['id']}", f["link"], f["width"],
                             f["height"], float(v.get("duration", 0)), v.get("url", ""),
                             (v.get("user") or {}).get("name", ""), *PEXELS_LICENSE, query=query))
        return out

    # -------------------------------------------------------------- images
    def images(self, query: str, page: int = 1) -> list[Asset]:
        d = self._get("https://pixabay.com/api/",
                      {"key": self.pixabay_key, "q": query[:100], "per_page": 40, "page": page,
                       "image_type": "photo", "orientation": "horizontal", "min_width": 1920,
                       "safesearch": "true"})
        out = []
        for h in d.get("hits", []):
            url = h.get("largeImageURL")
            if not url or brand_risk(h.get("tags", "")):
                continue
            out.append(Asset("pixabay", "image", f"pixabay-img:{h['id']}", url,
                             h.get("imageWidth", 0), h.get("imageHeight", 0), 0.0,
                             h.get("pageURL", ""), h.get("user", ""), *PIXABAY_LICENSE,
                             tags=h.get("tags", ""), query=query))
        return out

    # -------------------------------------------------------------- download
    def download(self, asset: Asset, dest: Path) -> Path:
        if dest.exists() and dest.stat().st_size > 10_000:
            return dest
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_suffix(dest.suffix + ".part")
        for attempt in range(3):
            try:
                with self.session.get(asset.url, stream=True, timeout=120) as r:
                    if r.status_code != 200:
                        raise requests.RequestException(f"HTTP {r.status_code}")
                    with open(tmp, "wb") as f:
                        for chunk in r.iter_content(1 << 20):
                            f.write(chunk)
                tmp.rename(dest)
                return dest
            except requests.RequestException:
                self.sleep(3 * (attempt + 1))
        raise TransientError(f"Жүктөө ишке ашкан жок: {asset.id}")


def from_env() -> Stock:
    from .config import get_secret

    key = get_secret("PIXABAY_API_KEY")
    if not key:
        raise StageError("PIXABAY_API_KEY жок")
    return Stock(key, get_secret("PEXELS_API_KEY"))
