"""Ар бир видеонун ӨЗҮНЧӨ монтаж концепциясы (оригиналдуулук — №1 приоритет, колдонуучу 2026-11-20).

YouTube'дун «Inauthentic content» (repetitive / mass-produced, 2025-07-15) эрежеси: бир шаблонду кайра колдонбо.
Ар видеонун темасы талданып, ушул өлчөмдөр боюнча өзүнчө концепция түзүлөт:

    grade        — түс/жарык дүйнөсү (s6 CONCEPTS)
    pacing       — кадр алмашуу ритми (s5: сахнанын темпине көбөйтүүчү)
    motion       — камера кыймылдарынын палитрасы (motion.plan_motions prefer)
    transitions  — өтүүлөрдүн палитрасы (cinematic.transition_for palette)
    subtitles    — субтитрдин визуалдык стили (s4 ASS)
    (+ s7 музыка трек/маанай, s1 баяндоо стили — QA'да салыштырылат)

Тандоо: темага ылайыктуулук + МУРУНКУ даяр видеолордон эң алыс комбинация (ар биринен ≥ MIN_DIFF өлчөм айырмаланат).
Видео кайра иштетилсе — сакталган концепция колдонулат (стиль секирбейт). Video_001 (биринчи даяр видео) өзгөрбөйт:
анын концепциясы LEGACY катары эсептелип, кийинкилер андан айырмаланат.
"""

from __future__ import annotations

import hashlib
import itertools
import json
from collections import Counter

GRADES = ("warm_cinematic", "cool_moody", "teal_orange", "muted_film", "golden_hour")

PACING = {   # сахнанын базалык темпине (s5 PACE) көбөйтүүчү; s5 жыйынтыкты 2.9–4.3 сек чегинде кармайт
    "steady": {"mul": 1.0, "ramp": 0.0},
    "breathing": {"mul": 1.08, "ramp": 0.0},       # кенен, тынч ыргак
    "pulse": {"mul": 0.88, "ramp": 0.0},           # тыгыз, динамикалуу
    "slow_burn": {"mul": 1.1, "ramp": -0.22},      # жайдан башталып, аягына карай тездейт
}

MOTION = {   # артыкчылыктуу кыймылдар (motion.TYPES ичинен)
    "gentle_drift": ["zoom_out", "pan_up", "ken_burns", "zoom_in"],
    "push_dolly": ["dolly", "dolly_out", "zoom_in", "pan_up"],
    "lateral": ["pan_left", "pan_right", "dolly", "zoom_out"],
    "handheld_doc": ["handheld", "pan_right", "zoom_in", "pan_left"],
    "still_breath": ["ken_burns", "zoom_in", "zoom_out", "pan_down"],
}

TRANSITIONS = {   # сахналар ортосундагы өтүүлөр (xfade аттары; "cut" — түз кесүү)
    "soft_dissolve": ["dissolve", "fade", "dissolve"],
    "dip_to_black": ["fadeblack", "fade", "dissolve"],
    "directional": ["smoothleft", "smoothright", "smoothup"],
    "film_fade": ["fadegrays", "fade", "dissolve"],
    "hard_cuts": ["cut", "cut", "fade"],
}

SUBTITLES = {   # ASS түстөрү (&HAABBGGRR) жана чек; өлчөм/орун QA чегинде (≥64 px, түбүнөн 60–140 px)
    "classic": {"primary": "&H00FFFFFF", "outline": "&H00101010", "back": "&H96000000", "border": 1,
                "outline_w": 4.4, "shadow": 2.0, "highlight": "&H3FC8FF&", "size": 72},
    "warm_cream": {"primary": "&H00DCF0FA", "outline": "&H00202838", "back": "&H96000000", "border": 1,
                   "outline_w": 4.0, "shadow": 2.5, "highlight": "&H4FA0FF&", "size": 72},
    "boxed": {"primary": "&H00FFFFFF", "outline": "&H64000000", "back": "&H64000000", "border": 3,
              "outline_w": 6.0, "shadow": 0.0, "highlight": "&H3FD8FF&", "size": 68},
    "minimal": {"primary": "&H00F2F2F2", "outline": "&H00181818", "back": "&H80000000", "border": 1,
                "outline_w": 3.0, "shadow": 1.2, "highlight": "&HE8D27A&", "size": 70},
    "accent_blue": {"primary": "&H00FFFFFF", "outline": "&H00241A10", "back": "&H96000000", "border": 1,
                    "outline_w": 4.2, "shadow": 2.0, "highlight": "&HFFC864&", "size": 72},
}

DIMS = ("grade", "pacing", "motion", "transitions", "subtitles")
MIN_DIFF = 3        # ар бир мурунку даяр видеодон кеминде ушунча монтаж өлчөмү айырмаланат
LEGACY = {"pacing": "steady", "motion": "legacy_mix", "transitions": "legacy_mix", "subtitles": "classic"}

# Тема → ылайыктуу варианттар (артыкчылык; катуу чектөө эмес)
THEME_PREFS = {
    "calm": {"pacing": ["breathing", "slow_burn"], "motion": ["gentle_drift", "still_breath"],
             "transitions": ["soft_dissolve", "dip_to_black", "film_fade"], "subtitles": ["minimal", "warm_cream"]},
    "drive": {"pacing": ["pulse", "slow_burn"], "motion": ["push_dolly", "lateral", "handheld_doc"],
              "transitions": ["directional", "hard_cuts"], "subtitles": ["boxed", "accent_blue", "classic"]},
    "warm": {"pacing": ["steady", "breathing"], "motion": ["gentle_drift", "push_dolly", "handheld_doc"],
             "transitions": ["soft_dissolve", "film_fade"], "subtitles": ["warm_cream", "classic"]},
}
THEME_GROUP = {"fear": "calm", "stress": "calm", "failure": "calm", "time": "calm", "laziness": "calm",
               "success": "drive", "motivation": "drive", "confidence": "drive", "discipline": "drive",
               "change": "drive", "money": "drive",
               "relationships": "warm", "psychology": "warm", "health": "warm"}


def fingerprint(entry: dict) -> dict:
    """Реестрдеги видеонун монтаж өлчөмдөрү (концепциясыз эски видео — LEGACY)."""
    ec = entry.get("edit_concept") or {}
    fp = {d: ec.get(d) or LEGACY.get(d) for d in DIMS}
    fp["grade"] = ec.get("grade") or entry.get("concept")
    return fp


def finished_others(registry: dict, video_id: str) -> dict[str, dict]:
    return {vid: v for vid, v in registry.get("videos", {}).items()
            if vid != video_id and (v.get("final") or v.get("final_cinematic"))}


def distance(a: dict, b: dict) -> int:
    return sum(1 for d in DIMS if a.get(d) and b.get(d) and a[d] != b[d]) + \
        sum(1 for d in DIMS if a.get(d) and not b.get(d))      # белгисиз → айырмалуу деп эсептелет


def choose(registry: dict, video_id: str, theme: str, theme_grades: list[str] | None = None) -> dict:
    """Темага ылайык жана мурункулардан эң алыс концепция. Сакталган болсо — ошол."""
    entry = registry.get("videos", {}).get(video_id) or {}
    if entry.get("edit_concept", {}).get("grade") in GRADES:
        return entry["edit_concept"]
    prev = [fingerprint(v) for v in finished_others(registry, video_id).values()]
    prefs = THEME_PREFS.get(THEME_GROUP.get(theme, ""), {})
    grades_ok = set(theme_grades or GRADES)
    seed = int(hashlib.md5(video_id.encode()).hexdigest(), 16)
    used = Counter(v for fp in prev for v in fp.values())
    best, best_key = None, None
    for combo in itertools.product(GRADES, PACING, MOTION, TRANSITIONS, SUBTITLES):
        c = dict(zip(DIMS, combo))
        dmin = min((distance(c, p) for p in prev), default=len(DIMS))
        fit = (c["grade"] in grades_ok) + sum(c[d] in prefs.get(d, ()) for d in DIMS if d != "grade")
        fresh = -sum(used[v] for v in c.values())            # бүт тарыхта аз колдонулгандар
        tie = int(hashlib.md5(f"{seed}:{combo}".encode()).hexdigest(), 16) % 1000
        key = (min(dmin, MIN_DIFF + 1), fit, dmin, fresh, tie)
        if best_key is None or key > best_key:
            best, best_key = c, key
    best["theme"] = theme
    best["min_distance"] = min((distance(best, p) for p in prev), default=None)
    return best


def get(ctx, scenes: list[dict] | None = None) -> dict:
    """Видеонун концепциясы (бир жолу түзүлөт → реестр + Projects/<ID>/edit_concept.json)."""
    entry = ctx.registry.setdefault("videos", {}).setdefault(ctx.video_id, {})
    if entry.get("edit_concept", {}).get("grade") in GRADES:
        return entry["edit_concept"]
    p = ctx.path("edit_concept.json")
    if p.exists():
        ec = json.loads(p.read_text(encoding="utf-8"))
        entry["edit_concept"] = ec
        return ec
    if scenes is None:
        scenes = json.loads(ctx.path("scenes.json").read_text(encoding="utf-8"))["scenes"]
    from .stages.s6_animation import THEME_CONCEPTS, dominant_theme

    theme = dominant_theme(scenes)
    ec = choose(ctx.registry, ctx.video_id, theme, THEME_CONCEPTS.get(theme))
    entry["edit_concept"] = ec
    p.write_text(json.dumps(ec, ensure_ascii=False, indent=1), encoding="utf-8")
    ctx.log(f"   🎬 Монтаж концепциясы ({theme}): " + ", ".join(f"{d}={ec[d]}" for d in DIMS) +
            (f"; мурункулардан айырма ≥{ec['min_distance']}/{len(DIMS)}" if ec.get("min_distance") is not None else ""))
    return ec


def enabled(ctx) -> bool:
    from . import cinematic

    return cinematic.enabled(getattr(ctx, "store", None))


def pacing_targets(targets: dict, scenes: dict, ec: dict) -> dict:
    """s5: сахналардын темпин концепцияга жараша өзгөртөт (2.9–4.3 сек)."""
    prof = PACING.get(ec.get("pacing"), PACING["steady"])
    ids = sorted(targets)
    n = max(1, len(ids) - 1)
    out = {}
    for k, sid in enumerate(ids):
        v = targets[sid] * prof["mul"] * (1 + prof["ramp"] * (k / n))
        out[sid] = round(min(4.3, max(2.9, v)), 2)
    return out
