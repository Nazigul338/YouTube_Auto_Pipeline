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
from ..errors import TransientError
from ..stock import Asset, from_env
from .base import Context, Stage, StageError

TAIL_SEC = 1.5          # үн бүткөндөн кийин видео ушунча улантылат (музыка менен)
TARGET_SHOT = 3.7       # орточо кадр (3–4 сек → 8 мүнөткө ~120–160 кадр)
MIN_SHOT, MAX_SHOT = 2.5, 4.4
MAX_REUSE_FRACTION = 0.05   # акыркы чара: кадрлардын ушунча үлүшү гана мурда колдонулган клип болушу мүмкүн


STRICT_MIN, STRICT_MAX = 2.8, 4.4      # катуу режим: ар кадр ушул чекте (сөз чеги мүмкүн болсо гана жылдырылат)


# сценарийге жараша темп: тынч/ойлуу сахна — узунураак кадр, чыңалган/чечкиндүү — кыскараак (2.8–4.4 ичинде)
PACE = {"calm": 4.0, "reflective": 3.9, "sad": 4.0, "hopeful": 3.6, "inspired": 3.4,
        "determined": 3.2, "tense": 3.0, "dramatic": 3.1}


def scene_targets(scenes: dict) -> dict:
    """{сахна id: кадрдын максаттуу узактыгы} — эмоцияга жараша."""
    return {sid: PACE.get(sc.get("emotion", ""), 3.6) for sid, sc in scenes.items()}


def strict_cuts(a: float, b: float, gaps: list[float], target: float = 3.6) -> list[float]:
    """a..b аралыгын 2.8–4.4 сек кадрларга бөлөт; кесүү сөз чегине (±0.35 сек) жылдырылат, бирок чектен чыкпайт.
    target — сахнанын темпи (тынч ≈4.0, чыңалган ≈3.0)."""
    d = b - a

    def violation(k: int) -> float:
        x = d / k
        return max(0.0, STRICT_MIN - x, x - STRICT_MAX)

    # чектен эң аз чыккан k (барабар болсо — 3.6 сек'ке жакыны): 4.6 сек сахна 2×2.3 эмес, 1 кадр болот
    k = min(range(1, int(d / 2.0) + 2), key=lambda n: (round(violation(n), 3), abs(d / n - target)))
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
               target: float = TARGET_SHOT, strict: bool = False,
               targets: dict | None = None) -> list[dict]:
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
            cuts = strict_cuts(a, b, gaps, (targets or {}).get(sc["id"], 3.6))
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


DARK_FILTER = "blackdetect=d=0.25:pic_th=0.95:pix_th=0.07"   # QA'дан (0.98/0.04) катуураак: grade караңгылатат


def dark_seconds(path: Path, offset: float, dur: float) -> float:
    """Клиптин КОЛДОНУЛА ТУРГАН бөлүгүндөгү кара/өтө караңгы секунддар (run #44921404755: 291–293 сек кара экран)."""
    import re
    import subprocess

    try:
        r = subprocess.run(["ffmpeg", "-v", "info", "-ss", f"{offset:.2f}", "-t", f"{dur:.2f}", "-i", str(path),
                            "-vf", f"scale=160:-2,fps=8,{DARK_FILTER}", "-an", "-f", "null", "-"],
                           capture_output=True, text=True, timeout=60)
    except Exception:
        return 0.0
    return round(sum(float(x) for x in re.findall(r"black_duration:([\d.]+)", r.stderr)), 2)


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

    @staticmethod
    def targets(ctx, scenes: dict) -> dict:
        """Сахналардын темпи: эмоция (PACE) × видеонун монтаж концепциясынын ыргагы (edit_concept)."""
        t = scene_targets(scenes)
        from .. import edit_concept
        if edit_concept.enabled(ctx):
            t = edit_concept.pacing_targets(t, scenes, edit_concept.get(ctx, list(scenes.values())))
        return t

    def run(self, ctx: Context) -> dict[str, Any]:
        scenes = {s["id"]: s for s in
                  json.loads(ctx.path("scenes.json").read_text(encoding="utf-8"))["scenes"]}
        timing = json.loads(ctx.path("subtitles", "timings.json").read_text(encoding="utf-8"))
        total = timing["duration"] + TAIL_SEC
        from .. import cinematic
        quality = cinematic.enabled(ctx.store)           # СЫНАК: катуу темп (2.8–4.4) + AI маани текшерүүсү
        shots = plan_shots(timing["scenes"], timing["words"], total, strict=quality,
                           targets=self.targets(ctx, scenes) if quality else None)
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
        from .. import edit_concept
        brief = edit_concept.get(ctx, list(scenes.values())) if quality and edit_concept.enabled(ctx) else None
        motif_q = 0
        for sid in sorted(by_scene):
            sc = scenes[sid]
            sc.setdefault("theme", detect_theme(sc.get("text", "")))
            mq = (brief or {}).get("scene_motifs", {}).get(str(sid))
            if mq and mq.lower() not in {q.lower() for q in sc.get("queries", [])}:
                sc["queries"] = [mq] + list(sc.get("queries", []))   # концепциянын мотив-кадры биринчи изделет
                motif_q += 1
            group = by_scene[sid]
            pool = finder.pool_for(sc, len(group), max(s["dur"] for s in group))
            for sh in group:
                a, tier, score = finder.pick(sc, pool, sh["dur"], allow_stale=reused < max_reuse)
                reused += tier == "reused"
                chosen[sh["i"]] = (a, tier, score)
                pool_of[sh["i"]] = pool
        if brief:
            ctx.log(f"   🎬 Концепция «{brief['name']}»: {motif_q} сахнага мотив-кадр издөөсү кошулду")
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
        from .. import story as _st
        if _st.is_story(ctx.cfg):        # кино-окуя: окуянын көз ирмемдери так — көбүрөөк кадр алмаштырылат
            self.MAX_REPLACE = 50        # (run #44903598138: 91/167 кадр ≤2/5, 25 гана алмаштырылчу)
            self.film = True             # кадр режиссёрдун планына (visual_prompt) бааланат; алмаштыруу 3 айлампа
        if quality:
            results, ai_stats = self.ai_relevance(ctx, results, shots, scenes, chosen, pool_of, finder, fetch, off_u)
            ctx.log(f"   🎯 AI маани текшерүү: бааланды {ai_stats.get('rated', 0)}/{len(shots)}, ≤2/5 болгон "
                    f"{ai_stats.get('low', 0)}, алмаштырылды {ai_stats.get('replaced', 0)}, "
                    f"орточо {ai_stats.get('avg', 0):.2f}/5")
        cont: dict = {}
        from .. import story as _story
        if quality and _story.is_story(ctx.cfg):    # кино-окуя: каарман бир адам бойдон калсын
            from .. import continuity
            results, cont = continuity.enforce(self, ctx, results, shots, scenes, chosen, pool_of, finder, fetch,
                                               off_u, pick_offset)
            ctx.log(f"   🧍 Continuity: каарман кадрлары {cont.get('hero_shots', 0)}, текшерилди {cont.get('checked', 0)}, "
                    f"туура {cont.get('consistent', 0)} (бет көрүнгөн {cont.get('faces', 0)}, башка жыныс "
                    f"{cont.get('wrong_gender', 0)}), бетсиз кадрга алмаштырылды {cont.get('replaced', 0)}, "
                    f"оңдолбоду {cont.get('kept_unfixed', 0)}, үлүш {cont.get('rate')}"
                    + (f" — ⚠ {cont['skipped']}" if cont.get("skipped") else ""))
        dark = (self.replace_dark(ctx, results, shots, scenes, chosen, pool_of, finder, fetch, off_u)
                if quality else {"found": 0})
        if dark["found"]:
            results = dark.pop("results")
            ctx.log(f"   🌑 Караңгы клиптер: {dark['found']} табылды, {dark['replaced']} алмаштырылды")
        dark.pop("results", None)
        ai_img: dict = {}
        from .. import ai_images
        if quality and ai_stats and ai_images.enabled(ctx.store):
            results, ai_img = self.add_ai_images(ctx, results, shots, scenes, ai_stats)

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
            if sc.get("hero"):
                sh.update({"hero": sc["hero"], "act": sc.get("act"), "shot_type": sc.get("shot")})
                if cont.get("scores", {}).get(str(i)) is not None:
                    sh["continuity"] = cont["scores"][str(i)]
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
        if cont and not cont.get("skipped"):
            res["continuity_rate"] = cont.get("rate")
        if ai_img:
            res["ai_images"] = ai_img["used"]
            res["ai_images_cost_usd"] = ai_img["cost_usd"]
        return res

    def replace_dark(self, ctx, results, shots, scenes, chosen, pool_of, finder, fetch, off_u) -> dict:
        """Кара/өтө караңгы клип (колдонулган бөлүгүндө ≥0.4 сек) → ошол сахнанын башка клиби (3 аракет)."""
        by_i = {r[0]: r for r in results}
        found = replaced = 0
        for i in sorted(by_i):
            for attempt in range(3):
                _, a, path, real, _, _ = by_i[i]
                if a.kind != "video":
                    break
                off = pick_offset(real, shots[i]["dur"], off_u(i)) if real and off_u else 0.0
                if dark_seconds(path, off, shots[i]["dur"]) < 0.4:
                    if attempt:
                        replaced += 1
                    break
                found += attempt == 0
                q = scenes[shots[i]["scene"]].get("detail_query") or ""
                nxt = (finder.beat_candidate(q, shots[i]["dur"]) if q and attempt == 0 else None) \
                    or finder.replacement(pool_of[i], shots[i]["dur"])
                if nxt is None:
                    break
                old = chosen[i]
                chosen[i] = (nxt, "fresh", 0.0)
                try:
                    by_i[i] = fetch(i)
                except Exception:
                    chosen[i] = old
                    break
        return {"found": found, "replaced": replaced, "results": [by_i[i] for i in sorted(by_i)]}

    def add_ai_images(self, ctx, results, shots, scenes, ai_stats):
        """Gemini AI-сүрөттөрү (СЫНАК): сток мааниге туура келбеген кадрларга гана, бюджет чегинде.
        AI-сүрөт да Gemini менен бааланат — стоктон жакшы болсо гана коюлат."""
        from .. import ai_images as ai

        g = ctx.services.get("gemini")
        budget = ai.Budget.from_env()
        style = ai.pick_style(ctx.video_id, ctx.registry)
        scores = dict(ai_stats["scores"])
        slots = ai.select_slots(shots, scores, budget.max_images, self.LOW_SCORE)
        info = {"style": style, "slots": slots, "used": 0, "kept": [], "rejected": []}
        text = lambda i: scenes[shots[i]["scene"]]["text"]
        if not slots or g is None:
            ctx.log("   🖼 AI-сүрөт: керек болгон кадр жок" if g else "   🖼 AI-сүрөт: Gemini жок")
            info.update(budget.report())
            info["cost_usd"] = 0.0
            return results, info
        try:
            prompts = ai.write_prompts(g, [(i, text(i)) for i in slots], style)
        except Exception as e:
            ctx.log(f"   ⚠️ AI-сүрөт prompt'тору жазылган жок ({type(e).__name__}) — сток калат")
            prompts = {}
        cache = ai.Cache(ctx.store, ctx.log)
        cand = {}
        for i in slots:
            if i not in prompts:
                continue
            got = ai.produce(g, cache, budget, ctx.video_id, prompts[i], ctx.path("clips"), ctx.log)
            if got is None:
                if budget.stopped:
                    ctx.log(f"   🖼 AI-сүрөт токтоду: {budget.stopped}")
                    break
                continue
            cand[i] = got
        by_i = {r[0]: r for r in results}
        if cand:
            new = self._rate(ctx, [(i, self._frame(p, "image", 0.0, shots[i]["dur"]), text(i))
                                   for i, (a, p) in cand.items()])
            for i, (a, p) in cand.items():
                old, sn = scores.get(i, 0), new.get(i)
                ok = (sn is not None and sn > old and sn >= 3) or (sn is None and old <= self.LOW_SCORE)
                row = {"shot": i, "stock_score": old, "ai_score": sn, "prompt": a.extra["prompt"],
                       "file": p.name, "model": a.extra["model"]}
                if ok:
                    by_i[i] = (i, a, p, None, "ai", 0.0)
                    if sn is not None:
                        scores[i] = sn
                    info["kept"].append(row)
                else:
                    info["rejected"].append(row)
        try:
            cache.save(ctx.path("clips"))
        except Exception as e:
            ctx.log(f"   ⚠️ AI-сүрөт индекси сакталган жок: {type(e).__name__}")
        ai_stats["scores"] = scores
        if scores:
            ai_stats["avg"] = sum(scores.values()) / len(scores)
        ctx.registry.setdefault("videos", {}).setdefault(ctx.video_id, {})["ai_style"] = style
        info.update(budget.report())
        info["used"] = len(info["kept"])
        ctx.path("clips", "ai_images.json").write_text(json.dumps(info, ensure_ascii=False, indent=1),
                                                       encoding="utf-8")
        ctx.log(f"   🖼 AI-сүрөт (Gemini): орун {len(slots)}, жаратылды {budget.generated}, кэштен {budget.cached}, "
                f"коюлду {info['used']}, четке кагылды {len(info['rejected'])}; чыгым ${budget.spent:.3f} "
                f"(чек ${budget.max_usd:.2f}){'; ' + budget.stopped if budget.stopped else ''}")
        return [by_i[i] for i in sorted(by_i)], info

    LOW_SCORE = 2          # ≤2/5 — клип сахнанын текстине дал келбейт
    MAX_REPLACE = 25
    RATE_BATCH = 8

    @staticmethod
    def _frame(path: Path, kind: str, offset: float, dur: float) -> bytes:
        from .s9_qa import frame_jpg

        if kind == "image":       # жалгыз сүрөттө `-ss` колдонулбайт (FFmpeg 6.1 бош кайтарат)
            import subprocess

            r = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-frames:v", "1", "-vf", "scale=640:-2",
                                "-f", "image2", "-c:v", "mjpeg", "-"], capture_output=True, timeout=60)
            return r.stdout
        return frame_jpg(path, offset + dur / 2)

    RATE_PASSES = 3        # Gemini 503 («жогорку суроо») болсо — токтоп туруп кайра аракет
    RATE_WAIT = 120

    def _rate(self, ctx, items: list[tuple[int, bytes, str]]) -> dict[int, int]:
        """[(кадр, jpg, сахна тексти)] → {кадр: 1..5}.

        Gemini убактылуу жеткиликсиз болсо (сынакта 503 бардык моделде: 8/168 гана бааланган) — 2 катар
        ийгиликсиз пакеттен кийин токтоп, RATE_WAIT сек күтүп, бааланбагандарды кайра аракеттейт (≤RATE_PASSES жолу).
        """
        import time

        out: dict[int, int] = {}
        todo = [x for x in items if x[1]]
        for attempt in range(1, self.RATE_PASSES + 1):
            failures = 0
            for k in range(0, len(todo), self.RATE_BATCH):
                part = todo[k:k + self.RATE_BATCH]
                if all(i in out for i, _, _ in part):
                    continue
                try:
                    from .base import gemini_of

                    pairs = [(j, tx) for _, j, tx in part]
                    scores = (gemini_of(ctx).rate_frames(pairs, film=True) if getattr(self, "film", False)
                              else gemini_of(ctx).rate_frames(pairs))
                    failures = 0
                except Exception as e:
                    failures += 1
                    ctx.log(f"   ⚠️ AI баа берген жок ({type(e).__name__}); аракет {attempt}/{self.RATE_PASSES}")
                    if failures >= 2:
                        break
                    continue
                for (i, _, _), s in zip(part, scores):
                    if isinstance(s, int) and 1 <= s <= 5:
                        out[i] = s
            if all(i in out for i, _, _ in todo) or attempt == self.RATE_PASSES:
                break
            ctx.log(f"   ⏳ {len(todo) - len(out)} кадр бааланган жок — {self.RATE_WAIT} сек күтүп кайра")
            time.sleep(self.RATE_WAIT)
        return out

    BEAT_PROMPT = """You are a film editor for a Russian-language psychology/motivation YouTube video.
For each numbered shot you get the exact Russian narration heard during that shot. The current stock clip
does not show its meaning. Invent ONE concrete visual idea per shot and two different 2-4 word English
stock-footage search queries for it.
{rules}
Return a JSON array only: [{{"i": <shot number>, "idea": "<1 short English sentence>", "queries": ["...", "..."]}}]

SHOTS:
{shots}"""

    @staticmethod
    def shot_texts(ctx, shots) -> dict[int, str]:
        """Ар кадрда диктор так эмне деп жатат (Whisper убакыттары боюнча)."""
        if not hasattr(ctx, "path"):
            return {}
        p = ctx.path("subtitles", "timings.json")
        words = json.loads(p.read_text(encoding="utf-8")).get("words", []) if p.exists() else []
        return {sh["i"]: " ".join(w["w"] for w in words if w["e"] > sh["start"] - 0.3 and w["s"] < sh["end"] + 0.3)
                for sh in shots}

    FILM_BEAT_RULES = ("\nTHIS IS A FACELESS, ATMOSPHERIC SHORT FILM about one protagonist ({hero}); the narrator tells "
                       "the story, the picture carries its PLACE, LIGHT, OBJECTS and MOOD. Each shot comes with the "
                       "PLANNED FILM SHOT as a hint. Find stock footage that is easy to find and true to this moment: "
                       "the same kind of place or a key object, hands, back, silhouette, point of view, a fitting visual "
                       "metaphor, matching light and emotion; never a visible face, no text on screen. Prefer short, "
                       "common search phrases (2-4 words). If a person is in the query, include the gender word "
                       "('man'/'woman').\n")

    BEAT_CHUNK = 20

    def visual_beats(self, ctx, idx: list[int], stext: dict[int, str], film: bool = False) -> dict[int, tuple[str, list[str]]]:
        """Начар кадрлар үчүн маанини көрсөткөн өзүнчө идея + издөө сөздөрү (бир Gemini суроо). Ката болсо — {}."""
        from ..visual_rules import VISUAL_RULES
        from .base import gemini_of

        todo = [i for i in idx if stext.get(i)]
        if not todo:
            return {}
        from .. import edit_concept
        world = ""
        try:
            if edit_concept.enabled(ctx):
                b = (getattr(ctx, "registry", {}) or {}).get("videos", {}).get(getattr(ctx, "video_id", ""), {}).get("edit_brief")
                if b:
                    world = (f"\nTHIS VIDEO'S OWN VISUAL WORLD (stay inside it): {b['world']} "
                             f"Recurring motifs: {', '.join(b['motifs'])}.\n")
        except Exception:
            world = ""
        if film:
            try:
                hero = json.loads(ctx.path("script", "story.json").read_text(encoding="utf-8"))["hero"]
                world += self.FILM_BEAT_RULES.format(hero=hero.get("descriptor", ""))
            except Exception:
                world += self.FILM_BEAT_RULES.format(hero="see shots")
        out: dict[int, tuple[str, list[str]]] = {}
        seen: set[str] = set()
        failed = 0
        # run #45002414086: 50 кадр бир суроодо → 503/JSONDecodeError → БААРЫ жоголду. Бөлүк-бөлүк (ар бири өзүнчө).
        for k in range(0, len(todo), self.BEAT_CHUNK):
            part = todo[k:k + self.BEAT_CHUNK]
            try:
                data = gemini_of(ctx).json(self.BEAT_PROMPT.format(
                    rules=VISUAL_RULES + world,
                    shots="\n".join(f"{i}. {stext[i][:450 if film else 300]}" for i in part)),
                    purpose="visual_beats", temperature=0.7)
            except Exception as e:
                failed += 1
                ctx.log(f"   ⚠️ Кадр идеялары ({len(part)} кадр) жазылган жок ({type(e).__name__}) — запас клиптер")
                continue
            for row in data if isinstance(data, list) else []:
                try:
                    i = int(row.get("i"))
                except (TypeError, ValueError, AttributeError):
                    continue
                qs = [q.strip() for q in row.get("queries", []) if isinstance(q, str) and q.strip()
                      and q.strip().lower() not in seen][:2]
                if i in part and qs:
                    seen.update(q.lower() for q in qs)        # бир видеодо бир идея эки жолу эмес
                    out[i] = (str(row.get("idea", ""))[:160], qs)
        return out

    def ai_relevance(self, ctx, results, shots, scenes, chosen, pool_of, finder, fetch, off_u):
        """Ар кадрды (клиптин ортосунан) ОШОЛ кадрдагы диктордун сөзүнө Gemini менен баалайт; ≤2/5 болсо —
        сөздүн маанисин көрсөткөн өзүнчө идея боюнча жаңы клип издейт (жок болсо — сахнанын запас клиби),
        жаңысы жакшыраак бааланса гана алмаштырат."""
        by_i = {r[0]: r for r in results}
        stext = self.shot_texts(ctx, shots)

        def text(i: int) -> str:
            scn = scenes[shots[i]["scene"]]
            sc = scn["text"]
            st = stext.get(i, "")
            base = f"«{st}» (scene context: {sc[:150]})" if st else sc
            if getattr(self, "film", False) and scn.get("visual_prompt"):    # кино: режиссёрдун пландаган кадры
                return f"{base} PLANNED FILM SHOT: {scn['visual_prompt'][:200]}"
            return base
        items = []
        for i, a, path, real, tier, score in results:
            sh = shots[i]
            off = pick_offset(real, sh["dur"], off_u(i)) if real else 0.0
            items.append((i, self._frame(path, a.kind, off, sh["dur"]), text(i)))
        scores = self._rate(ctx, items)
        low = sorted((i for i, s in scores.items() if s <= self.LOW_SCORE), key=lambda i: scores[i])
        replaced = 0
        beats: dict = {}
        beat_used: dict[int, str] = {}
        trial: dict[int, tuple] = {}
        film = getattr(self, "film", False)
        btext = {i: text(i) for i in low} if film else stext
        # run #44921404755: бир айлампада 99 начар кадрдын 17'си гана алмашты → кино форматта 2 айлампа
        # run #45002414086: 2 айлампа × 50 = 100 < 139 начар кадр → кино форматта 3 айлампа
        for round_ in range(3 if film else 1):
            todo = sorted((i for i in low if scores.get(i, 5) <= self.LOW_SCORE),
                          key=lambda i: scores[i])[: self.MAX_REPLACE]
            if not todo:
                break
            rb = self.visual_beats(ctx, todo, btext, film=film)
            beats.update(rb)
            cur: dict[int, tuple] = {}
            for i in todo:
                nxt = None
                for q in rb.get(i, ("", []))[1]:
                    nxt = finder.beat_candidate(q, shots[i]["dur"])
                    if nxt is not None:
                        beat_used[i] = rb[i][0]
                        break
                if nxt is None:
                    nxt = finder.replacement(pool_of[i], shots[i]["dur"])
                if nxt is None:
                    continue
                chosen[i] = (nxt, "fresh", 0.0)
                try:
                    cur[i] = fetch(i)
                except Exception:
                    continue
            if not cur:
                continue
            new_items = []
            for i, r in cur.items():
                sh = shots[i]
                off = pick_offset(r[3], sh["dur"], off_u(i)) if r[3] else 0.0
                new_items.append((i, self._frame(r[2], r[1].kind, off, sh["dur"]), text(i)))
            new_scores = self._rate(ctx, new_items)
            for i, r in cur.items():
                trial[i] = r
                if new_scores.get(i, 0) > scores.get(i, 5):
                    by_i[i] = r
                    scores[i] = new_scores[i]
                    replaced += 1
        out = [by_i[i] for i in sorted(by_i)]
        avg = sum(scores.values()) / len(scores) if scores else 0.0
        beats_won = sum(1 for i in beat_used if by_i[i] is trial.get(i))
        if beats:
            ctx.log(f"   💡 Кадр идеялары: {len(beats)} жазылды, {len(beat_used)} боюнча клип табылды, "
                    f"{beats_won} алмаштырылды")
        return out, {"rated": len(scores), "low": len(low), "replaced": replaced, "avg": avg, "scores": scores,
                     "beats": {str(i): beat_used[i] for i in beat_used}, "beats_won": beats_won}

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
            if s.get("source") == "gemini":            # AI-сүрөт: Drive кэшинен (кайра жаратылбайт)
                from ..ai_images import FOLDER
                if ctx.store is None or not ctx.store.fetch(FOLDER, s["file"], ctx.path("clips", s["file"])):
                    raise StageError(f"AI-сүрөт кэште жок: {s['file']}")
                return
            a = Asset(s["source"], s["kind"], s["asset"], s["url"], 1920, 1080, 0.0, "", "", "", "")
            try:
                stock.download(a, ctx.path("clips", s["file"]))
            except TransientError as e:
                fresh = stock.refresh_url(s["asset"]) if hasattr(stock, "refresh_url") else None
                if not fresh:
                    raise StageError(f"{e}. Клиптин жаңы шилтемеси табылган жок (балким булактан өчүрүлгөн) — "
                                     f"5-этаптан кайра иштетиңиз (rerun_from: s5_visuals)") from e
                ctx.log(f"   ↻ {s['asset']}: эски шилтеме иштебейт — API'ден жаңы шилтеме алынды")
                a.url = s["url"] = fresh
                stock.download(a, ctx.path("clips", s["file"]))

        with ThreadPoolExecutor(4) as ex:
            list(ex.map(get, missing))
        # жаңыланган шилтемелер сакталсын (кийинки runner эскисин колдонбосун)
        ctx.path("clips", "shots.json").write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    return data["shots"]
