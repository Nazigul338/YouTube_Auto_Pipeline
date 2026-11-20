"""Акылдуу издөө: сахнанын маанисине жараша Pixabay клиптерин табуу (кайталанбастан).

Агым (ар сахна үчүн):
  1. Сахнанын өз издөө сөздөрү (s2: Gemini түзгөн, мурунку видеолордо көп колдонулгандардан сакташып).
  2. Жетишсиз болсо — ошол сөздөрдүн 2–3-беттери.
  3. Дагы жетишсиз болсо — башка ачкыч сөздөр: сахнанын теması боюнча визуалдык сөздөр,
     `visual` сүйлөмүнөн сөз айкаштары, модификаторлор («close up», «silhouette»…).
  4. Клиптер тагдары боюнча: жаңы-узун → жаңы-кыска (s8 узартат) → жаңы сүрөт → (акыркы чара) эң эски
     колдонулган клип.
Тандоодо Pixabay `tags` менен сахнанын сөздөрү дал келгени жогору коюлат.
Суроо саны бир видеого чектелген (Pixabay: 100 суроо/мүнөт; Stock өзү ылдамдыкты тыят).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable

from .clipmemory import ClipMemory
from .errors import StageError

MAX_SEARCH_CALLS = 500
EXTRA_MARGIN = 2           # сахнадагы кадр санынан ашык талапкер
LONG_ROOM = 0.4            # узак клип: узактыгы ≥ кадр + 0.4 сек

STOP = {"the", "a", "an", "of", "in", "on", "at", "to", "and", "with", "for", "from", "by", "up",
        "is", "are", "into", "over", "his", "her", "their", "its", "that", "this", "as", "or",
        "close", "view", "shot", "scene", "background", "footage", "video", "person", "people"}

MODIFIERS = ["close up", "silhouette", "slow motion", "aerial view", "time lapse", "sunset",
             "night", "hands", "rain", "walking"]

# тема → (орусча тамырлар, визуалдык издөө сөздөрү)
THEMES: dict[str, tuple[tuple[str, ...], list[str]]] = {
    "fear": (("страх", "боят", "тревог", "паник", "риск", "ужас"),
             ["person standing cliff edge", "dark corridor light", "storm clouds", "foggy forest path",
              "shadow on wall", "lonely silhouette dusk"]),
    "laziness": (("лень", "ленив", "прокраст", "откладыва", "диван", "бездель", "апати"),
                 ["person lying couch", "alarm clock morning", "unmade bed sunlight", "clock ticking",
                  "scrolling phone night", "empty desk"]),
    "success": (("успех", "достиж", "побед", "результат", "вершин"),
                ["mountain summit sunrise", "hiker reaching peak", "runner finish line",
                 "city skyline sunrise", "rock climbing", "winner celebrating"]),
    "motivation": (("мотивац", "цел", "мечт", "энерги", "вдохнов", "стремлен"),
                   ["sunrise mountains", "man running dawn", "road ahead horizon", "stairs going up",
                    "archery target arrow", "hand reaching sunlight"]),
    "discipline": (("дисциплин", "режим", "привычк", "регуляр", "ежедневн", "рутин"),
                   ["morning routine", "planner writing", "gym weights", "lacing running shoes",
                    "clock hands", "checklist pen"]),
    "psychology": (("психолог", "мозг", "мышлен", "сознан", "подсознан", "эмоци", "мысл"),
                   ["human brain", "silhouette head thoughts", "mirror reflection", "maze top view",
                    "rain window thoughtful", "neurons network"]),
    "stress": (("стресс", "выгоран", "усталост", "напряж", "перегруз"),
               ["tired office worker", "rain on window", "deep breath meditation", "calm lake morning",
                "crowded subway", "rubbing temples"]),
    "relationships": (("отношен", "друз", "семь", "общен", "одиночеств", "любов", "довери"),
                      ["friends laughing", "holding hands", "family dinner", "talking cafe",
                       "empty bench park", "handshake"]),
    "confidence": (("уверенн", "самооцен", "сомнен", "неуверен"),
                   ["confident man walking", "looking in mirror", "speaking on stage",
                    "street walking determined", "arms raised sunrise", "smiling portrait"]),
    "time": (("время", "срок", "сегодня", "завтра", "жизн", "годы", "возраст"),
             ["hourglass sand", "clock time lapse", "sunset time lapse", "calendar pages",
              "city time lapse", "old pocket watch"]),
    "money": (("деньг", "финанс", "доход", "карьер", "бизнес", "работ"),
              ["office laptop", "coins stack", "business meeting", "entrepreneur working",
               "business district", "counting money"]),
    "health": (("здоров", "сон", "спорт", "тело", "питани", "бег"),
               ["jogging park", "healthy breakfast", "yoga sunrise", "sleeping peacefully",
                "stretching morning", "swimming pool"]),
    "change": (("измен", "перемен", "начат", "нов", "решени", "выбор"),
               ["crossroads path", "door opening light", "butterfly cocoon", "fork in road",
                "sunrise new day", "turning page book"]),
    "failure": (("ошибк", "неудач", "провал", "падени", "поражен"),
                ["fall and stand up", "broken glass", "rainy street alone", "crumpled paper",
                 "sad man window", "cracked wall"]),
}
THEME_KEYS = list(THEMES) + ["general"]


def terms(text: str) -> set[str]:
    out = set()
    for w in re.findall(r"[a-zA-Z]{3,}", (text or "").lower()):
        if w in STOP:
            continue
        out.add(w[:-1] if w.endswith("s") and len(w) > 4 else w)
    return out


def detect_theme(text: str) -> str:
    low = (text or "").lower().replace("ё", "е")
    best, score = "general", 0
    for key, (stems, _) in THEMES.items():
        s = sum(low.count(st) for st in stems)
        if s > score:
            best, score = key, s
    return best


def relevance(asset, scene: dict) -> float:
    """0..1: Pixabay `tags` сахнанын издөө/визуал сөздөрүнө канчалык дал келет."""
    tags = terms((asset.tags or "").replace(",", " "))
    if not tags:
        return 0.0
    want = terms(asset.query) | terms(scene.get("visual", "")) \
        | {t for q in scene.get("queries", [])[:2] for t in terms(q)}
    if not want:
        return 0.0
    return min(1.0, len(tags & want) / max(1, min(len(want), 4)))


def expand_queries(scene: dict, tried: set[str]) -> list[str]:
    """Башка ачкыч сөздөр (дал келген тартипте, кайталабастан)."""
    out: list[str] = []

    def add(q: str):
        q = " ".join(q.split())[:60]
        if q and q.lower() not in tried and q.lower() not in {x.lower() for x in out}:
            out.append(q)

    theme = scene.get("theme") or detect_theme(scene.get("text", ""))
    for q in THEMES.get(theme, ("", []))[1]:
        add(q)
    vis = [w for w in re.findall(r"[a-zA-Z]+", (scene.get("visual") or "").lower()) if w not in STOP]
    for i in range(0, max(0, len(vis) - 1), 2):
        add(" ".join(vis[i:i + 3]))
    for q in scene.get("queries", [])[:3]:
        for m in MODIFIERS[:4]:
            add(f"{q} {m}")
    # соңку запас: башка темалардын «жалпы» сөздөрү
    for key, (_, qs) in THEMES.items():
        if key != theme:
            add(qs[0])
    return out


@dataclass
class Cand:
    asset: Any
    score: float
    rank: int
    qidx: int
    long: bool


@dataclass
class Pool:
    """Бир сахнанын талапкерлери (тартиби боюнча)."""
    fresh: list[Cand] = field(default_factory=list)       # мурда колдонулбаган
    stale: list[Cand] = field(default_factory=list)       # башка видеолордо колдонулган
    images: list[Any] = field(default_factory=list)
    seen: set[str] = field(default_factory=set)

    def key(self, c: Cand):
        return (-round(c.score * 2) / 2, c.rank, c.qidx)


class ClipFinder:
    def __init__(self, stock, memory: ClipMemory, video_id: str, min_duration: float,
                 log: Callable[[str], None] = print, budget: int = MAX_SEARCH_CALLS):
        self.stock, self.memory, self.video_id = stock, memory, video_id
        self.min_duration, self.log, self.budget = min_duration, log, budget
        self.others = memory.used_by_others(video_id)
        self.taken: set[str] = set()
        self.cache: dict[tuple, list] = {}
        self.calls = 0
        self.expanded_scenes = 0

    # -------------------------------------------------------------- суроо
    def search(self, kind: str, q: str, page: int = 1) -> list:
        key = (kind, q.lower(), page)
        if key in self.cache:
            return self.cache[key]
        if self.calls >= self.budget:
            return []
        self.calls += 1
        try:
            res = (self.stock.videos(q, min_duration=self.min_duration, page=page) if kind == "video"
                   else self.stock.images(q, page=page))
        except StageError:
            if page == 1:
                raise
            res = []           # Pixabay: бет диапазондон чыкты (HTTP 400) — натыйжа бүттү
        self.cache[key] = res
        return res

    def _absorb(self, pool: Pool, assets: list, qidx: int, scene: dict, need: float) -> None:
        for rank, a in enumerate(assets):
            if a.id in pool.seen or a.id in self.taken:
                continue
            pool.seen.add(a.id)
            c = Cand(a, relevance(a, scene), rank, qidx, a.duration >= need + LONG_ROOM)
            (pool.stale if a.id in self.others else pool.fresh).append(c)

    def _enough(self, pool: Pool, n: int) -> bool:
        return sum(1 for c in pool.fresh if c.long) >= n + EXTRA_MARGIN

    # -------------------------------------------------------------- сахна
    def pool_for(self, scene: dict, n_shots: int, need: float) -> Pool:
        pool = Pool()
        queries = list(scene["queries"])
        if scene.get("visual"):
            queries.append(" ".join(scene["visual"].split()[:5]))
        tried = {q.lower() for q in queries}
        # 1) өз сөздөрү
        for qi, q in enumerate(queries):
            self._absorb(pool, self.search("video", q), qi, scene, need)
        # 2) кийинки беттер
        if not self._enough(pool, n_shots):
            for page in (2, 3):
                for qi, q in enumerate(queries[:3]):
                    self._absorb(pool, self.search("video", q, page), qi, scene, need)
                if self._enough(pool, n_shots):
                    break
        # 3) башка ачкыч сөздөр
        if not self._enough(pool, n_shots):
            self.expanded_scenes += 1
            extra = expand_queries(scene, tried)
            for k, q in enumerate(extra[:14]):
                self._absorb(pool, self.search("video", q), len(queries) + k, scene, need)
                if self._enough(pool, n_shots):
                    break
            if not self._enough(pool, n_shots):
                for k, q in enumerate(extra[:4]):
                    self._absorb(pool, self.search("video", q, 2), len(queries) + k, scene, need)
        pool.fresh.sort(key=pool.key)
        pool.stale.sort(key=lambda c: (self.memory.last_use_num(c.asset.id, self.video_id), pool.key(c)))
        return pool

    def fresh_images(self, scene: dict, pool: Pool) -> None:
        if pool.images:
            return
        for q in scene["queries"][:2] + expand_queries(scene, set())[:2]:
            for a in self.search("image", q):
                if a.id not in self.taken and a.id not in self.others \
                        and a.id not in {x.id for x in pool.images}:
                    pool.images.append(a)

    # -------------------------------------------------------------- тандоо
    def pick(self, scene: dict, pool: Pool, dur: float, allow_stale: bool) -> tuple[Any, str, float]:
        """(asset, tier, relevance). tier: fresh | short | image | reused."""
        want = dur + LONG_ROOM
        for c in pool.fresh:
            if c.asset.id not in self.taken and c.asset.duration >= want:
                return self._take(c.asset, "fresh", c.score)
        for c in pool.fresh:
            if c.asset.id not in self.taken:
                return self._take(c.asset, "short", c.score)
        self.fresh_images(scene, pool)
        for a in pool.images:
            if a.id not in self.taken:
                return self._take(a, "image", 0.0)
        if allow_stale:
            for c in pool.stale:
                if c.asset.id not in self.taken:
                    return self._take(c.asset, "reused", c.score)
        raise StageError(f"{scene['id']}-сахна үчүн жаңы (колдонулбаган) материал табылган жок "
                         f"(суроо: {self.calls}); сөздөр: {scene['queries']}")

    def _take(self, asset, tier: str, score: float):
        self.taken.add(asset.id)
        return asset, tier, score

    def beat_candidate(self, query: str, dur: float):
        """Бир кадр үчүн өзүнчө маанилик суроо (visual beat): жаңы, мурда колдонулбаган, узундугу жетиштүү клип."""
        for a in self.search("video", query):
            if a.id not in self.taken and a.id not in self.others and a.duration >= dur + LONG_ROOM:
                return self._take(a, "fresh", 0.0)[0]
        return None

    def replacement(self, pool: Pool, dur: float):
        """Жүктөө/узактык ишке ашпаса — ошол сахнадан кийинки жаңы клип."""
        for c in pool.fresh:
            if c.asset.id not in self.taken:
                return self._take(c.asset, "fresh", c.score)[0]
        return None
