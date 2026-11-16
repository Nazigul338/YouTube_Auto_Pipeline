"""5-этап: Видеоклиптер (кадрлардын планы жана материалдар).

  - Ар сахнанын чыныгы убактысы (4-этаптан) ~3 сек кадрларга бөлүнөт; кесүү
    чектери сөздөрдүн ортосуна туура келет (сөз ортосунан эмес).
  - Ар кадрга ошол сахнанын издөө сөздөрү боюнча клип тандалат.
  - Клип КАЙТАЛАНБАЙТ: бул видеодо да, мурунку видеолордо да (реестрдеги тарых).
  - Видео табылбаса — Pixabay сүрөтү (6-этапта кыймылга келтирилет).
  - Ар материалдын булагы, автору, шилтемеси, лицензиясы жазылат.
"""

from __future__ import annotations

import hashlib
import json
import random
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from .. import media
from ..stock import Asset, from_env
from .base import Context, Stage, StageError

TAIL_SEC = 1.5          # үн бүткөндөн кийин видео ушунча улантылат (музыка менен)
MIN_SHOT, MAX_SHOT = 2.0, 4.2


def plan_shots(scene_times: list[dict], words: list[dict], total: float,
               target: float = 3.0) -> list[dict]:
    """Сахналарды ~target сек кадрларга бөлөт, чектерди сөздөрдүн арасына жылдырат."""
    gaps = [(words[i]["e"] + words[i + 1]["s"]) / 2 for i in range(len(words) - 1)]
    shots = []
    for i, sc in enumerate(scene_times):
        a = 0.0 if i == 0 else sc["start"]
        b = scene_times[i + 1]["start"] if i + 1 < len(scene_times) else total
        d = b - a
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


def pick_offset(real_duration: float, shot_dur: float, u: float) -> float:
    """Клиптин ичинен кесүү башталышы. Ар дайым offset + shot_dur ≤ чыныгы узактык − 0.3.

    real_duration — файлдын ЧЫНЫГЫ видео агымынын узактыгы (API метаданныйы эмес).
    u — [0,1) кокус сан (кайталануучу).
    """
    room = max(0.0, real_duration - shot_dur - 0.3)
    return round(min(room, 0.5 + u * max(0.0, room - 0.5)), 2)


def used_history(registry: dict, video_id: str) -> set[str]:
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
        shots = plan_shots(timing["scenes"], timing["words"], total)
        stock = ctx.services.get("stock") or from_env()
        rng = random.Random(int(hashlib.md5(ctx.video_id.encode()).hexdigest(), 16))

        used = used_history(ctx.registry, ctx.video_id)
        ctx.log(f"   {len(shots)} кадр (орточо {total / len(shots):.1f} сек); "
                f"мурунку видеолордо колдонулган клиптер: {len(used)}")
        cache: dict[str, list[Asset]] = {}

        def candidates(scene: dict, need: float) -> list[Asset]:
            queries = list(scene["queries"])
            if scene.get("visual"):
                queries.append(" ".join(scene["visual"].split()[:5]))
            pools = []
            for q in queries:
                key = f"v|{q}"
                if key not in cache:
                    cache[key] = stock.videos(q, min_duration=MIN_SHOT + 0.5)
                pools.append([a for a in cache[key] if a.duration >= need + 0.4])
            out, seen = [], set()
            for row in range(max((len(p) for p in pools), default=0)):  # кезектешип: ар түрдүүлүк
                for p in pools:
                    if row < len(p) and p[row].id not in seen:
                        seen.add(p[row].id)
                        out.append(p[row])
            return out

        def image_candidates(scene: dict) -> list[Asset]:
            out = []
            for q in scene["queries"][:2]:
                key = f"i|{q}"
                if key not in cache:
                    cache[key] = stock.images(q)
                out += cache[key]
            return out

        chosen: list[Asset | None] = [None] * len(shots)
        pool_by_shot: dict[int, list[Asset]] = {}
        images_used = 0
        for sh in shots:
            sc = scenes[sh["scene"]]
            pool = [a for a in candidates(sc, sh["dur"]) if a.id not in used]
            if not pool:
                pool = [a for a in image_candidates(sc) if a.id not in used]
            if not pool:
                raise StageError(f"{sh['scene']}-сахна үчүн жаңы (колдонулбаган) материал "
                                 f"табылган жок: {sc['queries']}")
            chosen[sh["i"]] = pool[0]
            pool_by_shot[sh["i"]] = pool[1:]
            used.add(pool[0].id)
            images_used += pool[0].kind == "image"

        # жүктөө (параллель) + текшерүү; бузук файл болсо — кийинки талапкер
        cdir = ctx.path("clips")

        def fetch(i: int) -> tuple[int, Asset, Path, float | None]:
            a = chosen[i]
            for _ in range(4):
                ext = ".mp4" if a.kind == "video" else ".jpg"
                path = cdir / f"{a.id.replace(':', '_')}{ext}"
                try:
                    stock.download(a, path)
                    real = None
                    if a.kind == "video":
                        # ЧЫНЫГЫ видео агымынын узактыгы (API'ники эмес, файлдыкы):
                        # Pixabay метаданныйы файлга дал келбей калышы мүмкүн.
                        real = media.stream_durations(path)["video"]
                        if real is None or real < shots[i]["dur"] + MIN_CLIP_ROOM:
                            raise StageError(f"клип кыска: чыныгы {real} сек")
                    return i, a, path, real
                except Exception:
                    path.unlink(missing_ok=True)
                    nxt = [x for x in pool_by_shot.get(i, []) if x.id not in used]
                    if not nxt:
                        raise
                    a = nxt[0]
                    used.add(a.id)
                    pool_by_shot[i].remove(a)
            raise StageError(f"{i}-кадрдын материалын жүктөө ишке ашкан жок")

        with ThreadPoolExecutor(4) as ex:
            results = list(ex.map(fetch, range(len(shots))))

        licenses = []
        for i, a, path, real in results:
            sh = shots[i]
            sh.update({"kind": a.kind, "asset": a.id, "file": path.name, "source": a.source,
                       "query": a.query, "url": a.url})
            if a.kind == "video":
                sh["real_duration"] = round(real, 2)
                sh["offset"] = pick_offset(real, sh["dur"], rng.random())
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
        if ctx.store:
            ctx.store.publish("Clips", lic, f"{ctx.video_id}_clips.json")
        ctx.log(f"   ✓ {len(shots)} кадр, {len(ids)} уникалдуу материал "
                f"(видео: {len(shots) - images_used}, сүрөт: {images_used})")
        return {"shots_file": str(out), "licenses_file": str(lic), "shots": len(shots),
                "unique": len(ids), "images": images_used}

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
