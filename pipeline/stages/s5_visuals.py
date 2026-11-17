"""5-этап: Видеоклиптер (кадрлардын планы жана материалдар) — Smart Video Memory менен.

  - Ар сахнанын чыныгы убактысы (4-этаптан) 3–4 сек кадрларга бөлүнөт (8 мүнөткө ~120–160 кадр);
    кесүү чектери сөздөрдүн ортосуна туура келет (сөз ортосунан эмес).
  - Ар кадрга сахнанын мааниси боюнча клип тандалат (`clipsearch.ClipFinder`):
    сахнанын сөздөрү → кийинки беттер → башка ачкыч сөздөр (тема боюнча).
  - Клип КАЙТАЛАНБАЙТ: бул видеодо да, мурунку видеолордо да — туруктуу база
    `Projects/_clip_memory.json` (+ `Clips/clip_memory.csv`, `clipmemory.py`).
    Жаңы клип жетишпесе гана: жаңы клип (кыска, s8 узартат) → жаңы сүрөт → акыркы чара: эң эски
    колдонулган клип (≤ MAX_REUSE_FRACTION, белгиленет).
  - Ар материалдын булагы, автору, шилтемеси, лицензиясы жазылат.
"""

from __future__ import annotations

import hashlib
import json
import math
import random
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from .. import media
from ..clipmemory import ClipMemory
from ..clipsearch import ClipFinder, Pool, detect_theme
from ..stock import Asset, from_env
from .base import Context, Stage, StageError

TAIL_SEC = 1.5          # үн бүткөндөн кийин видео ушунча улантылат (музыка менен)
TARGET_SHOT = 3.7       # орточо кадр (3–4 сек → 8 мүнөткө ~120–160 кадр)
MIN_SHOT, MAX_SHOT = 2.5, 4.4
MAX_REUSE_FRACTION = 0.05   # акыркы чара: кадрлардын ушунча үлүшү гана мурда колдонулган клип болушу мүмкүн


STRICT_MIN, STRICT_MAX = 2.8, 4.4      # катуу режим: ар кадр ушул чекте (сөз чеги мүмкүн болсо гана жылдырылат)


def strict_cuts(a: float, b: float, gaps: list[float]) -> list[float]:
    """a..b аралыгын 2.8–4.4 сек кадрларга бөлөт; кесүү сөз чегине (±0.35 сек) жылдырылат, бирок чектен чыкпайт."""
    d = b - a

    def violation(k: int) -> float:
        x = d / k
        return max(0.0, STRICT_MIN - x, x - STRICT_MAX)

    # чектен эң аз чыккан k (барабар болсо — 3.6 сек'ке жакыны): 4.6 сек сахна 2×2.3 эмес, 1 кадр болот
    k = min(range(1, int(d / 2.0) + 2), key=lambda n: (round(violation(n), 3), abs(d / n - 3.6)))
    cuts = [a]
    for j in range(1, k):
        ideal = a + j * d / k
        lo = cuts[-1] + STRICT_MIN
        hi = cuts[-1] + STRICT_MAX
        rest = k - j                       # кесүүдөн кийин калган кадрлар
        lo = max(lo, b - rest * STRICT_MAX)
        hi = min(hi, b - rest * STRICT_MIN)
        near = [g for g in gaps if abs(g - ideal) <= 0.35 and lo <= g <= hi]
        cuts.append(min(near, key=lambda g: abs(g - ideal)) if near else min(max(ideal, lo), hi) if lo <= hi else ideal)
    cuts.append(b)
    return cuts


def plan_shots(scene_times: list[dict], words: list[dict], total: float,
               target: float = TARGET_SHOT, strict: bool = False) -> list[dict]:
    """Сахналарды ~target сек кадрларга бөлөт, чектерди сөздөрдүн арасына жылдырат.

    strict=True (сынак): ар кадр 2.8–4.4 сек (мүмкүн болгон жерде), мурунку режим — эркин (2.3–4.8 чыгып калган).
    """
    gaps = [(words[i]["e"] + words[i + 1]["s"]) / 2 for i in range(len(words) - 1)]
    shots = []
    for i, sc in enumerate(scene_times):
        a = 0.0 if i == 0 else sc["start"]
        b = scene_times[i + 1]["start"] if i + 1 < len(scene_times) else total
        d = b - a
        if strict:
            cuts = strict_cuts(a, b, gaps)
            for s, e in zip(cuts, cuts[1:]):
                shots.append({"i": len(shots), "scene": sc["id"], "start": round(s, 3),
                              "end": round(e, 3), "dur": round(e - s, 3)})
            continue
        k = max(1, round(d / target))
        while k > 1 and d / k < MIN_SHOT + 0.3:
            k -= 1
        while d / k > MAX_SHOT:
            k += 1
        cuts = [a]
        for j in range(1, k):
            t = a + j * d / k
            near = [g for g in gaps if abs(g - t) <= 0.6 and cuts[-1] + MIN_SHOT * 0.8 < g < b - MIN_SHOT * 0.8]
            cuts.append(min(near, key=lambda g: abs(g - t)) if near else t)
        cuts.append(b)
        for s, e in zip(cuts, cuts[1:]):
            shots.append({"i": len(shots), "scene": sc["id"], "start": round(s, 3),
                          "end": round(e, 3), "dur": round(e - s, 3)})
    return shots


MIN_CLIP_ROOM = 0.6     # клип кадрдан ушунча секунд узун болушу керек (offset үчүн орун)
MIN_USABLE = 1.0        # андан кыска клип жараксыз; ортосу — s8 `-stream_loop` менен узартат


def pick_offset(real_duration: float, shot_dur: float, u: float) -> float:
    """Клиптин ичинен кесүү башталышы. Ар дайым offset + shot_dur ≤ чыныгы узактык − 0.3.

    real_duration — файлдын ЧЫНЫГЫ видео агымынын узактыгы (API метаданныйы эмес).
    u — [0,1) кокус сан (кайталануучу).
    """
    room = max(0.0, real_duration - shot_dur - 0.3)
    return round(min(room, 0.5 + u * max(0.0, room - 0.5)), 2)


def used_history(registry: dict, video_id: str) -> set[str]:
    """(Эски жол) реестрден башка видеолордун клиптери. Азыр ClipMemory колдонулат."""
    used: set[str] = set()
    for vid, v in registry.get("videos", {}).items():
        if vid != video_id:
            used.update(v.get("clip_ids", []))
    return used


class VisualsStage(Stage):
    name = "s5_visuals"
    title = "Видеоклиптер"
    retries = 2

    def run(self, ctx: Context) -> dict[str, Any]:
        scenes = {s["id"]: s for s in
                  json.loads(ctx.path("scenes.json").read_text(encoding="utf-8"))["scenes"]}
        timing = json.loads(ctx.path("subtitles", "timings.json").read_text(encoding="utf-8"))
        total = timing["duration"] + TAIL_SEC
        from .. import cinematic
        quality = cinematic.enabled(ctx.store)           # СЫНАК: катуу темп (2.8–4.4) + AI маани текшерүүсү
        shots = plan_shots(timing["scenes"], timing["words"], total, strict=quality)
        stock = ctx.services.get("stock") or from_env()
        rng = random.Random(int(hashlib.md5(ctx.video_id.encode()).hexdigest(), 16))

        mem = ClipMemory.load(ctx.store, ctx.registry)
        released = mem.release(ctx.video_id)          # кайра иштетүүдө өзүн өзү бөгөттөбөйт
        finder = ClipFinder(stock, mem, ctx.video_id, min_duration=MIN_SHOT + 0.5, log=ctx.log)
        ctx.log(f"   {len(shots)} кадр (орточо {total / len(shots):.1f} сек); клип базасы: "
                f"{mem.stats()['clips']} клип / {mem.stats()['videos']} видео"
                + (f"; бул видеонун мурунку {released} жазуусу бошотулду" if released else ""))

        by_scene: dict[int, list[dict]] = {}
        for sh in shots:
            by_scene.setdefault(sh["scene"], []).append(sh)
        max_reuse = math.ceil(MAX_REUSE_FRACTION * len(shots))
        chosen: dict[int, tuple[Asset, str, float]] = {}
        pool_of: dict[int, Pool] = {}
        reused = 0
        for sid in sorted(by_scene):
            sc = scenes[sid]
            sc.setdefault("theme", detect_theme(sc.get("text", "")))
            group = by_scene[sid]
            pool = finder.pool_for(sc, len(group), max(s["dur"] for s in group))
            for sh in group:
                a, tier, score = finder.pick(sc, pool, sh["dur"], allow_stale=reused < max_reuse)
                reused += tier == "reused"
                chosen[sh["i"]] = (a, tier, score)
                pool_of[sh["i"]] = pool
        ctx.log(f"   Издөө: {finder.calls} Pixabay суроо; кеңейтилген сахна: {finder.expanded_scenes}; "
                f"кайра колдонулган клип: {reused}")

        # жүктөө (параллель) + текшерүү; бузук/кыска файл болсо — ошол сахнанын кийинки жаңы клиби
        cdir = ctx.path("clips")
        lock = threading.Lock()

        def fetch(i: int) -> tuple[int, Asset, Path, float | None, str, float]:
            a, tier, score = chosen[i]
            best: tuple[Asset, Path, float, str, float] | None = None
            for _ in range(6):
                ext = ".mp4" if a.kind == "video" else ".jpg"
                path = cdir / f"{a.id.replace(':', '_')}{ext}"
                short = False
                try:
                    stock.download(a, path)
                    real = None
                    if a.kind == "video":
                        # ЧЫНЫГЫ видео агымынын узактыгы (API'ники эмес, файлдыкы)
                        real = media.stream_durations(path)["video"]
                        if real is None:
                            raise StageError("клип ачылган жок")
                        if real < shots[i]["dur"] + MIN_CLIP_ROOM:
                            short = True
                            if real >= MIN_USABLE and (best is None or real > best[2]):
                                best = (a, path, real, tier, score)
                            raise StageError(f"клип кыска: чыныгы {real:.1f} сек")
                    return i, a, path, real, tier, score
                except Exception:
                    keep = best is not None and best[1] == path
                    if not keep and not short:
                        path.unlink(missing_ok=True)
                    with lock:
                        nxt = finder.replacement(pool_of[i], shots[i]["dur"])
                    if nxt is None:
                        if best is not None:       # кыска, бирок колдонууга болот → s8 узартат
                            return (i, best[0], best[1], best[2], "short", best[4])
                        raise
                    a, tier, score = nxt, "fresh", 0.0
            raise StageError(f"{i}-кадрдын материалын жүктөө ишке ашкан жок")

        with ThreadPoolExecutor(4) as ex:
            results = list(ex.map(fetch, range(len(shots))))

        def off_u(i: int) -> float:
            """Кадрдын кесүү орду үчүн туруктуу кокус сан (AI баалаган кадр ЧЫНЫГЫ көрүнө турган кадр болсун)."""
            return random.Random(f"{ctx.video_id}:{i}").random()

        ai_stats: dict = {}
        if quality:
            results, ai_stats = self.ai_relevance(ctx, results, shots, scenes, chosen, pool_of, finder, fetch, off_u)
            ctx.log(f"   🎯 AI маани текшерүү: бааланды {ai_stats.get('rated', 0)}/{len(shots)}, ≤2/5 болгон "
                    f"{ai_stats.get('low', 0)}, алмаштырылды {ai_stats.get('replaced', 0)}, "
                    f"орточо {ai_stats.get('avg', 0):.2f}/5")

        licenses = []
        images_used = extended = 0
        for i, a, path, real, tier, score in results:
            sh = shots[i]
            sc = scenes[sh["scene"]]
            sh.update({"kind": a.kind, "asset": a.id, "file": path.name, "source": a.source,
                       "query": a.query, "url": a.url, "page_url": a.page_url, "tier": tier,
                       "theme": sc.get("theme", ""), "match": round(score, 2),
                       "reused": tier == "reused" or a.id in finder.others})
            if ai_stats:
                sh["ai_score"] = ai_stats["scores"].get(i)
            images_used += a.kind == "image"
            if a.kind == "video":
                sh["real_duration"] = round(real, 2)
                sh["offset"] = pick_offset(real, sh["dur"], off_u(i) if quality else rng.random())
                if real < sh["dur"] + MIN_CLIP_ROOM:
                    sh["extend"] = True          # s8 бул кадрды кайталап узартат
                    extended += 1
            licenses.append({"shot": i, "type": a.kind, "source": a.source, "id": a.id,
                             "author": a.author, "page_url": a.page_url, "license": a.license,
                             "license_url": a.license_url, "file": path.name,
                             "query": a.query})

        out = ctx.path("clips", "shots.json")
        out.write_text(json.dumps({"total": total, "shots": shots}, ensure_ascii=False, indent=1),
                       encoding="utf-8")
        lic = ctx.path("clips", "licenses.json")
        lic.write_text(json.dumps(licenses, ensure_ascii=False, indent=1), encoding="utf-8")
        ids = sorted({s["asset"] for s in shots})
        entry = ctx.registry.setdefault("videos", {}).setdefault(ctx.video_id, {})
        entry["clip_ids"] = ids

        # Smart Video Memory: базага ДАРОО жазабыз (кийинки этаптар жыгылса да клиптер бөгөттөлгөн бойдон калат)
        topic = getattr(ctx.state, "topic", "") or entry.get("topic", "")
        mem.reserve(ctx.video_id, topic, shots)
        mem.save(ctx.store, ctx.path("clips", "clip_memory.csv"))
        if ctx.store:
            ctx.store.publish("Clips", lic, f"{ctx.video_id}_clips.json")
        n_reused = sum(1 for s in shots if s["reused"])
        themes = sorted({s["theme"] for s in shots if s.get("theme")})
        ctx.log(f"   ✓ {len(shots)} кадр, {len(ids)} уникалдуу материал "
                f"(видео: {len(shots) - images_used}, сүрөт: {images_used}); жаңы: {len(shots) - n_reused}, "
                f"кайра колдонулган: {n_reused}; узартылуучу: {extended}; темалар: {', '.join(themes)}")
        res = {"shots_file": str(out), "licenses_file": str(lic), "shots": len(shots),
               "unique": len(ids), "images": images_used, "reused": n_reused,
               "extended": extended, "search_calls": finder.calls}
        if ai_stats:
            res["ai_avg"] = round(ai_stats["avg"], 2)
            res["ai_replaced"] = ai_stats["replaced"]
        return res

    LOW_SCORE = 2          # ≤2/5 — клип сахнанын текстине дал келбейт
    MAX_REPLACE = 25
    RATE_BATCH = 8

    @staticmethod
    def _frame(path: Path, kind: str, offset: float, dur: float) -> bytes:
        from .s9_qa import frame_jpg

        return frame_jpg(path, 0.0 if kind == "image" else offset + dur / 2)

    def _rate(self, ctx, items: list[tuple[int, bytes, str]]) -> dict[int, int]:
        """[(кадр, jpg, сахна тексти)] → {кадр: 1..5}. Gemini квотасы бүтсө — бош (текшерүү өткөрүлөт)."""
        from .base import gemini_of

        out: dict[int, int] = {}
        for k in range(0, len(items), self.RATE_BATCH):
            part = [x for x in items[k:k + self.RATE_BATCH] if x[1]]
            if not part:
                continue
            try:
                scores = gemini_of(ctx).rate_frames([(j, tx) for _, j, tx in part])
            except Exception as e:
                ctx.log(f"   ⚠️ AI баа берген жок ({type(e).__name__}) — калган кадрлар текшерилген эмес")
                break
            for (i, _, _), s in zip(part, scores):
                if isinstance(s, int) and 1 <= s <= 5:
                    out[i] = s
        return out

    def ai_relevance(self, ctx, results, shots, scenes, chosen, pool_of, finder, fetch, off_u):
        """Ар кадрды (клиптин ортосунан) сахнанын текстине Gemini менен баалайт; ≤2/5 болсо — ошол сахнанын
        кийинки жаңы клибине алмаштырат (жакшыраса гана)."""
        by_i = {r[0]: r for r in results}
        text = lambda i: scenes[shots[i]["scene"]]["text"]
        items = []
        for i, a, path, real, tier, score in results:
            sh = shots[i]
            off = pick_offset(real, sh["dur"], off_u(i)) if real else 0.0
            items.append((i, self._frame(path, a.kind, off, sh["dur"]), text(i)))
        scores = self._rate(ctx, items)
        low = sorted((i for i, s in scores.items() if s <= self.LOW_SCORE), key=lambda i: scores[i])
        replaced = 0
        trial: dict[int, tuple] = {}
        for i in low[: self.MAX_REPLACE]:
            nxt = finder.replacement(pool_of[i], shots[i]["dur"])
            if nxt is None:
                continue
            chosen[i] = (nxt, "fresh", 0.0)
            try:
                trial[i] = fetch(i)
            except Exception:
                continue
        if trial:
            new_items = []
            for i, r in trial.items():
                sh = shots[i]
                off = pick_offset(r[3], sh["dur"], off_u(i)) if r[3] else 0.0
                new_items.append((i, self._frame(r[2], r[1].kind, off, sh["dur"]), text(i)))
            new_scores = self._rate(ctx, new_items)
            for i, r in trial.items():
                if new_scores.get(i, 0) > scores.get(i, 5):
                    by_i[i] = r
                    scores[i] = new_scores[i]
                    replaced += 1
        out = [by_i[i] for i in sorted(by_i)]
        avg = sum(scores.values()) / len(scores) if scores else 0.0
        return out, {"rated": len(scores), "low": len(low), "replaced": replaced, "avg": avg, "scores": scores}

    def verify(self, ctx: Context, outputs: dict[str, Any] | None) -> None:
        super().verify(ctx, outputs)
        if outputs["unique"] != outputs["shots"]:
            raise StageError("Бир клип бир нече кадрда колдонулуп калды")


def ensure_media(ctx: Context) -> list[dict]:
    """Кийинки этаптар үчүн: клиптер жок болсо (жаңы runner) — кайра жүктөйт."""
    data = json.loads(ctx.path("clips", "shots.json").read_text(encoding="utf-8"))
    missing = [s for s in data["shots"] if not ctx.path("clips", s["file"]).exists()]
    if missing:
        stock = ctx.services.get("stock") or from_env()
        ctx.log(f"   ⬇ {len(missing)} материал кайра жүктөлүүдө (мурунку иштетүүдөн)")

        def get(s):
            a = Asset(s["source"], s["kind"], s["asset"], s["url"], 1920, 1080, 0.0, "", "", "", "")
            stock.download(a, ctx.path("clips", s["file"]))

        with ThreadPoolExecutor(4) as ex:
            list(ex.map(get, missing))
    return data["shots"]
