"""Scene continuity checker (кино-окуя форматы): каарман бир видеодо БИР адам бойдон калсын.

Сток-видеодо бир эле актер 150 кадрда табылбайт — ошондуктан:
  1. каарман ЖҮЗҮ/денеси менен көрүнгөн кадрлар (s2 `hero` = face/body) Gemini көзү менен профилге баалонот,
     эң дал келгени — visual reference (кадр-эталон);
  2. калган кадрлар эталон менен салыштырылат: «ушул эле адам болушу мүмкүнбү» (жыныс, жаш, чач, дене, кийим);
  3. дал келбеген кадр ошол эле көз ирмемди БЕТ КӨРСӨТПӨЙ айткан кадрга (колдор, силуэт, буюм, жай —
     s2 `detail_query`) алмаштырылат (кинодо да колдонулган ыкма).
Натыйжа `clips/continuity.json` → s9 `check_story` (милдеттүү үлүш).
"""

from __future__ import annotations

import json

REF_PROMPT = """These are frames from stock videos for ONE protagonist of a short film.
Protagonist profile: {profile}
For EACH image (Image 0..N) rate 0-10 how well the visible main person could play this protagonist: gender and age range
matter most, then hair and build; clothes may differ. Also say whether the face is clearly visible.
0 = no person / clearly a different gender or age.
Return JSON array only: [{{"i": <index>, "match": <0-10>, "face": <true/false>}}]"""

SAME_PROMPT = """Image 0 is the REFERENCE protagonist of a short film ({profile}).
For EACH other image (Image 1..N) answer: could the main person be the SAME character in the same story (same gender,
similar age, hair, build and clothing style)? Different lighting/angle is fine. If there is no person, same=false.
Return JSON array only: [{{"i": <index>, "same": <0-10>, "person": <true/false>}}]"""

BATCH = 10
SAME_MIN = 5
REF_MIN = 4
MAX_REPLACE = 45
CHECK_VIS = ("face", "body")


def profile_text(hero: dict) -> str:
    return f"{hero.get('descriptor', '')}; {hero.get('look', {})}"


def choose_reference(gem, frames: dict[int, bytes], hero: dict) -> tuple[int | None, dict[int, int]]:
    """Профилге эң дал келген (бети ачык) кадр → эталон."""
    idx = list(frames)[:12]
    if not idx:
        return None, {}
    r = gem.judge_image([frames[i] for i in idx], REF_PROMPT.format(profile=profile_text(hero)),
                        purpose="continuity_ref")
    scores = {}
    for x in r if isinstance(r, list) else []:
        try:
            k = int(x.get("i"))
            if 0 <= k < len(idx):
                scores[idx[k]] = int(x.get("match") or 0) + (2 if x.get("face") else 0)
        except (TypeError, ValueError):
            continue
    if not scores:
        return None, {}
    best = max(scores, key=scores.get)
    # run #44898457854: «≥6» өтө катуу болуп эталон табылган жок (сток-видеодо кийим/чач так дал келбейт) —
    # эталон = эң жакын адам (≥4: жыныс/жаш дал келет), калгандары ушуга салыштырылат
    return (best if scores[best] >= REF_MIN else None), scores


def compare_to_reference(gem, ref: bytes, frames: dict[int, bytes], hero: dict) -> dict[int, int]:
    out: dict[int, int] = {}
    idx = list(frames)
    for b in range(0, len(idx), BATCH):
        part = idx[b:b + BATCH]
        try:
            r = gem.judge_image([ref] + [frames[i] for i in part], SAME_PROMPT.format(profile=profile_text(hero)),
                                purpose="continuity_same")
        except Exception:
            continue
        for x in r if isinstance(r, list) else []:
            try:
                k = int(x.get("i")) - 1
                if 0 <= k < len(part):
                    out[part[k]] = int(x.get("same") or 0) if x.get("person", True) else 0
            except (TypeError, ValueError):
                continue
    return out


def enforce(stage, ctx, results, shots, scenes, chosen, pool_of, finder, fetch, off_u, pick_offset) -> tuple[list, dict]:
    """s5 (кино форматы): каарман кадрларын текшерүү жана дал келбегендерин алмаштыруу."""
    try:
        hero = json.loads(ctx.path("script", "story.json").read_text(encoding="utf-8"))["hero"]
    except Exception:
        return results, {"skipped": "story.json жок"}
    from .stages.base import gemini_of

    gem = gemini_of(ctx)
    if not hasattr(gem, "judge_image"):
        return results, {"skipped": "көрүү кызматы жок"}
    by_i = {r[0]: r for r in results}
    check = [i for i in by_i if scenes[shots[i]["scene"]].get("hero") in CHECK_VIS]
    frames = {}
    for i in check:
        _, a, path, real, _, _ = by_i[i]
        off = pick_offset(real, shots[i]["dur"], off_u(i)) if real else 0.0
        try:
            frames[i] = stage._frame(path, a.kind, off, shots[i]["dur"])
        except Exception:
            continue
    stats = {"hero_shots": len(check), "checked": 0, "consistent": 0, "replaced": 0, "kept_unfixed": 0,
             "reference_shot": None, "scores": {}}
    if not frames:
        return results, stats
    try:
        ref_i, ref_scores = choose_reference(gem, frames, hero)
    except Exception as e:
        return results, dict(stats, skipped=f"эталон тандалган жок: {type(e).__name__}")
    if ref_i is None:
        return results, dict(stats, skipped="профилге дал келген кадр табылган жок")
    stats["reference_shot"] = ref_i
    same = compare_to_reference(gem, frames[ref_i], {k: v for k, v in frames.items() if k != ref_i}, hero)
    same[ref_i] = 10
    stats["checked"] = len(same)
    stats["scores"] = {str(k): v for k, v in same.items()}
    bad = sorted((i for i, v in same.items() if v < SAME_MIN), key=lambda i: same[i])[:MAX_REPLACE]
    for i in bad:
        sc = scenes[shots[i]["scene"]]
        q = sc.get("detail_query") or ""
        nxt = finder.beat_candidate(q, shots[i]["dur"]) if q else None
        if nxt is None:
            stats["kept_unfixed"] += 1
            continue
        old = chosen[i]
        chosen[i] = (nxt, "fresh", 0.0)
        try:
            by_i[i] = fetch(i)
            stats["replaced"] += 1
            stats["scores"][str(i)] = "detail"
        except Exception:
            chosen[i] = old
            stats["kept_unfixed"] += 1
    stats["consistent"] = sum(1 for v in same.values() if v >= SAME_MIN)
    fixed = stats["consistent"] + stats["replaced"]
    stats["rate"] = round(fixed / max(1, stats["checked"]), 3)
    ctx.path("clips", "continuity.json").write_text(json.dumps(dict(stats, hero=hero.get("descriptor")),
                                                               ensure_ascii=False, indent=1), encoding="utf-8")
    return [by_i[i] for i in sorted(by_i)], stats
