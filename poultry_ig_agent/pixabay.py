"""Pixabay стоктон видео (Pixabay Content License: бекер, коммерциялык колдонууга болот).
Ачкыч: POULTRY_PIXABAY_API_KEY (GitHub Secret). Видео серверге жүктөлөт (hotlink эмес); клиптер licenses.json'го жазылат.
Pixabay видеолорунун көбү горизонталдуу — монтажда ортосунан 9:16 кесилет."""
import json
import os
import urllib.error
import urllib.parse
import urllib.request

from . import log
from .pexels import FALLBACK_QUERIES, StockError, keywords

API = "https://pixabay.com/api/videos/"


def pick_file(hit, min_h=720):
    """Эң кичине, бирок бийиктиги ≥ min_h болгон вариант (large/medium/small)."""
    vids = [v for v in (hit.get("videos") or {}).values() if isinstance(v, dict) and v.get("url") and v.get("height")]
    ok = [v for v in vids if v["height"] >= min_h]
    return min(ok, key=lambda v: v["height"]) if ok else None


class PixabayStock:
    def __init__(self, key=None, transport=None, downloader=None):
        self.key = key or os.environ.get("POULTRY_PIXABAY_API_KEY")
        if not self.key:
            raise StockError("POULTRY_PIXABAY_API_KEY коюлган эмес (GitHub Secrets'ке кошуңуз)")
        self.tx, self.dl, self.used = transport, downloader, set()
        self.log = log.get()

    def search(self, query, per_page=20):
        q = urllib.parse.urlencode({"key": self.key, "q": query[:100], "video_type": "film", "safesearch": "true",
                                    "per_page": per_page})
        url = f"{API}?{q}"
        if self.tx:
            return self.tx(url).get("hits", [])
        req = urllib.request.Request(url, headers={"User-Agent": "poultry-ig-agent"})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.load(r).get("hits", [])
        except urllib.error.HTTPError as e:   # ачкыч URL'де — катада көрсөтүлбөйт
            raise StockError(f"Pixabay HTTP {e.code}") from None

    def find(self, visual, min_seconds):
        for q in [keywords(visual)] + list(FALLBACK_QUERIES):
            if not q:
                continue
            for h in self.search(q):
                if h["id"] in self.used or h.get("duration", 0) < min(min_seconds, 8):
                    continue
                f = pick_file(h)
                if f:
                    self.used.add(h["id"])
                    return h, f, q
        raise StockError(f"Pixabay'дан ылайыктуу видео табылган жок: {visual[:60]}")

    def fetch(self, visual, min_seconds, out_path):
        h, f, q = self.find(visual, min_seconds)
        if self.dl:
            self.dl(f["url"], out_path)
        else:
            req = urllib.request.Request(f["url"], headers={"User-Agent": "poultry-ig-agent"})
            with urllib.request.urlopen(req, timeout=180) as r, open(out_path, "wb") as fh:
                fh.write(r.read())
        lic = {"source": "Pixabay", "id": h["id"], "url": h.get("pageURL"), "author": h.get("user"),
               "query": q, "license": "https://pixabay.com/service/license-summary/"}
        self.log.info("Pixabay клип %s (%s) — %s", h["id"], q, lic["author"])
        return out_path, lic


def make_stock():
    """Кайсы ачкыч бар болсо ошону колдонот: адегенде Pixabay, анан Pexels."""
    if os.environ.get("POULTRY_PIXABAY_API_KEY"):
        return PixabayStock()
    if os.environ.get("POULTRY_PEXELS_API_KEY"):
        from .pexels import PexelsStock
        return PexelsStock()
    raise StockError("Сток ачкычы жок: POULTRY_PIXABAY_API_KEY же POULTRY_PEXELS_API_KEY кошуңуз")
