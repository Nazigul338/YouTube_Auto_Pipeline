"""Pexels стоктон вертикалдуу видео издөө (Pexels License: бекер, коммерциялык колдонууга болот, атрибуция милдеттүү эмес).
Ачкыч: POULTRY_PEXELS_API_KEY (GitHub Secret). Ар бир колдонулган клип licenses.json'го жазылат."""
import json
import os
import re
import urllib.parse
import urllib.request

from . import log

API = "https://api.pexels.com/videos/search"
FALLBACK_QUERIES = ("baby chicken", "chicken farm", "hens", "chicken coop", "rooster")
STOP = {"a", "an", "the", "of", "in", "on", "with", "and", "or", "to", "for", "at", "is", "are", "close-up", "shot",
        "soft", "natural", "close", "light", "looking", "camera", "background", "out", "focus", "small", "up"}


class StockError(RuntimeError):
    pass


ANCHORS = ("chick", "chicks", "chicken", "chickens", "hen", "hens", "rooster", "poultry", "coop", "brooder", "broiler")
DETAILS = ("water", "drinking", "feed", "feeding", "eating", "egg", "eggs", "straw", "bedding", "lamp", "heat", "coop",
           "farm", "nest", "incubator", "farmer", "barn")
# 'chick' жалгыз жетишсиз: Pixabay аны өрдөк/каз балапандарына да коёт
RELEVANT = ("chicken", "hen", "hens", "rooster", "poultry", "broiler", "fowl", "cockerel", "pullet", "brooder", "coop")
NEGATIVE = ("duck", "goose", "geese", "gosling", "swan", "sparrow", "pigeon", "ostrich", "parrot", "penguin", "owl",
            "eagle", "seagull", "gull", "pelican", "flamingo", "heron", "stork", "turkey", "quail", "peacock")


def keywords(visual, n=5):
    words = [w for w in re.findall(r"[a-zA-Z]+", (visual or "").lower()) if w not in STOP and len(w) > 2]
    return " ".join(list(dict.fromkeys(words))[:n])


def poultry_query(visual):
    """Кыска суроо: бир тоок сөзү + бир деталь (узун суроо тиешесиз натыйжа берет: 'running' → чуркаган адам)."""
    words = re.findall(r"[a-zA-Z]+", (visual or "").lower())
    anchor = next((w for w in words if w in ANCHORS), "chicks")
    if anchor in ("chick", "chicks"):
        anchor = "baby chicken"            # 'chicks' жалгыз → өрдөк/каз балапандары да чыгат
    elif anchor in ("brooder", "coop"):
        anchor = "chicken " + anchor
    detail = next((w for w in words if w in DETAILS and w not in anchor), "")
    return f"{anchor} {detail}".strip()


def relevant(text):
    t = (text or "").lower()
    words = set(re.findall(r"[a-z]+", t))
    if any(n in words or n + "s" in words or n + "lings" in words or n + "ling" in words for n in NEGATIVE):
        return False
    return any(r in words or r + "s" in words for r in RELEVANT)


def excluded_ids():
    """POULTRY_STOCK_EXCLUDE=1,2,3 — сериянын башка бөлүктөрүндө колдонулган клиптер."""
    return {int(x) for x in os.environ.get("POULTRY_STOCK_EXCLUDE", "").replace(" ", "").split(",") if x.isdigit()}


def _get(url, key, transport=None):
    if transport:
        return transport(url)
    req = urllib.request.Request(url, headers={"Authorization": key, "User-Agent": "poultry-ig-agent"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def pick_file(video, min_h=1280):
    """Эң ылайыктуу mp4: вертикалдуу, бийиктиги ≥ min_h, бирок 4K'дан кичине (көлөмү үчүн)."""
    files = [f for f in video.get("video_files", []) if f.get("file_type") == "video/mp4" and f.get("height") and f.get("width")]
    vert = [f for f in files if f["height"] >= f["width"] and min_h <= f["height"] <= 2160]
    pool = vert or [f for f in files if f["height"] >= 720]
    return min(pool, key=lambda f: f["height"]) if pool else None


class PexelsStock:
    def __init__(self, key=None, transport=None, downloader=None):
        self.key = key or os.environ.get("POULTRY_PEXELS_API_KEY")
        if not self.key:
            raise StockError("POULTRY_PEXELS_API_KEY коюлган эмес (GitHub Secrets'ке кошуңуз)")
        self.tx, self.dl, self.used = transport, downloader, excluded_ids()
        self.log = log.get()

    def search(self, query, per_page=15):
        q = urllib.parse.urlencode({"query": query, "orientation": "portrait", "per_page": per_page, "size": "medium"})
        return _get(f"{API}?{q}", self.key, self.tx).get("videos", [])

    def find(self, visual, min_seconds):
        for q in [poultry_query(visual)] + list(FALLBACK_QUERIES):
            for v in self.search(q):
                if v["id"] in self.used or v.get("duration", 0) < min(min_seconds, 8):
                    continue
                if not relevant(v.get("url", "")):          # Pexels: URL slug'ында тоок сөзү болушу керек
                    continue
                f = pick_file(v)
                if f:
                    self.used.add(v["id"])
                    return v, f, q
        raise StockError(f"Pexels'тен ылайыктуу видео табылган жок: {visual[:60]}")

    def fetch(self, visual, min_seconds, out_path):
        v, f, q = self.find(visual, min_seconds)
        if self.dl:
            self.dl(f["link"], out_path)
        else:
            req = urllib.request.Request(f["link"], headers={"User-Agent": "poultry-ig-agent"})
            with urllib.request.urlopen(req, timeout=180) as r, open(out_path, "wb") as fh:
                fh.write(r.read())
        lic = {"source": "Pexels", "id": v["id"], "url": v.get("url"), "author": (v.get("user") or {}).get("name"),
               "author_url": (v.get("user") or {}).get("url"), "query": q, "license": "https://www.pexels.com/license/"}
        self.log.info("Pexels клип %s (%s) — %s", v["id"], q, lic["author"])
        return out_path, lic
