"""6-этап: Анимация жана эффекттер (план + экрандагы тексттер).

  - Видеонун ВИЗУАЛДЫК КОНЦЕПЦИЯСЫ (түс градациясы, виньетка, өтүүлөр, тексттин стили)
    ар видеого башка: эң аз колдонулганы тандалат (эреже 12).
  - Ар кадрдын кыймылы: zoom in/out, pan, жай түртүү — кошуна кадрларда кайталанбайт,
    эмоцияга жараша ылдамдыгы өзгөрөт (тынч сахна — жай, драмалык — тезирээк).
  - Сүрөттөр (статикалык) Ken Burns кыймылы менен «тирилтилет».
  - Өтүүлөр: сахнанын ичинде — кесүү, сахналардын ортосунда — жумшак (dissolve/slide).
  - Маанилүү ойлор — анимацияланган текст-карточка (scenes.on_screen_text).
  Натыйжа: animation/plan.json жана animation/overlays.ass (8-этап колдонот).
"""

from __future__ import annotations

import hashlib
import json
import random
from typing import Any

from .base import Context, Stage, StageError
from .s4_subtitles import ts_ass

CONCEPTS: dict[str, dict] = {
    "warm_cinematic": {"grade": "eq=contrast=1.06:saturation=1.08:gamma=0.98,"
                                "colorbalance=rs=0.04:gs=0.01:bs=-0.04",
                       "vignette": "PI/5", "transitions": ["fade", "dissolve"],
                       "card_color": "&H00E6F2FF&", "card_font": "Montserrat Bold"},
    "cool_moody": {"grade": "eq=contrast=1.08:saturation=0.86:gamma=0.97,"
                            "colorbalance=rs=-0.04:gs=0.0:bs=0.05",
                   "vignette": "PI/4", "transitions": ["fade", "smoothleft"],
                   "card_color": "&H00FFF0DC&", "card_font": "Montserrat SemiBold"},
    "teal_orange": {"grade": "eq=contrast=1.1:saturation=1.05,"
                             "colorbalance=rs=0.05:bs=-0.05:rh=-0.03:bh=0.04",
                    "vignette": "PI/5", "transitions": ["dissolve", "smoothright"],
                    "card_color": "&H0060C8FF&", "card_font": "Montserrat Bold"},
    "muted_film": {"grade": "eq=contrast=1.04:saturation=0.72:gamma=1.02,"
                            "colorbalance=rs=0.02:bs=0.02",
                   "vignette": "PI/4.5", "transitions": ["fade", "fadegrays"],
                   "card_color": "&H00F5F5F5&", "card_font": "DejaVu Serif Bold"},
    "golden_hour": {"grade": "eq=contrast=1.05:saturation=1.12:gamma=0.97,"
                             "colorbalance=rs=0.06:gs=0.03:bs=-0.06",
                    "vignette": "PI/5.5", "transitions": ["dissolve", "fade"],
                    "card_color": "&H0080DCFF&", "card_font": "Montserrat Bold"},
}
MOTIONS = ["zoom_in", "zoom_out", "pan_right", "pan_left", "pan_up", "push_in"]
SPEED = {"calm": 0.7, "reflective": 0.7, "sad": 0.6, "hopeful": 0.9, "tense": 1.2,
         "determined": 1.1, "inspired": 1.0, "dramatic": 1.3}


THEME_CONCEPTS = {   # cinematic СЫНАК: теманын маанайына ылайык түс концепциялары
    "fear": ["cool_moody", "muted_film"], "stress": ["cool_moody", "muted_film"],
    "failure": ["muted_film", "cool_moody"], "laziness": ["muted_film", "warm_cinematic"],
    "time": ["muted_film", "golden_hour"], "success": ["golden_hour", "warm_cinematic", "teal_orange"],
    "motivation": ["golden_hour", "teal_orange", "warm_cinematic"], "confidence": ["teal_orange", "golden_hour"],
    "discipline": ["teal_orange", "warm_cinematic"], "psychology": ["teal_orange", "cool_moody"],
    "change": ["teal_orange", "golden_hour"], "relationships": ["warm_cinematic", "golden_hour"],
    "health": ["warm_cinematic", "golden_hour"], "money": ["teal_orange", "cool_moody"],
}


def dominant_theme(scenes: list[dict]) -> str:
    from collections import Counter

    c = Counter(s.get("theme") for s in scenes if s.get("theme") and s.get("theme") != "general")
    return c.most_common(1)[0][0] if c else "general"


def choose_concept(registry: dict, video_id: str, theme: str | None = None) -> str:
    """Эң аз колдонулган концепция. Видео кайра иштетилсе — мурунку концепция САКТАЛАТ (түс секирбейт).

    Мурун тең салмакта `hash(k)` колдонулган: Python аны ар процессте башка эсептейт → rerun'до концепция
    өзгөрүп калган (Video_003: muted_film → teal_orange, түс салыштырмасы бузулган).
    """
    prev = (registry.get("videos", {}).get(video_id) or {}).get("concept")
    if prev in CONCEPTS:
        return prev
    allowed = THEME_CONCEPTS.get(theme or "", list(CONCEPTS))
    used = {k: 0 for k in CONCEPTS}
    for vid, v in registry.get("videos", {}).items():
        if vid != video_id and v.get("concept") in used:
            used[v["concept"]] += 1
    seed = int(hashlib.md5(video_id.encode()).hexdigest(), 16)
    return min(allowed, key=lambda k: (used[k], (int(hashlib.md5(k.encode()).hexdigest(), 16) ^ seed) % 997))


HOOK_CARD = (0.4, 3.4)     # hook карточкасы видеонун алгачкы секунддарында


def card_items(scenes: list[dict], scene_times: dict[int, dict], min_gap: float = 12,
               hook: str = "") -> list[dict]:
    """Карточкалар: [{start, end, text}] (ASS жана HyperFrames экөө тең ушуну колдонот).
    hook — видеонун башындагы карточка (сценарийдин «КАРТОЧКА:» сабы): алгачкы секунддарда көңүл бурат."""
    items = []
    last_end = -99.0
    hook = (hook or "").strip().replace("{", "").replace("}", "")
    if hook:
        items.append({"start": HOOK_CARD[0], "end": HOOK_CARD[1], "text": hook.upper(), "hook": True})
        last_end = HOOK_CARD[1]
    for s in scenes:
        txt = (s.get("on_screen_text") or "").strip().replace("{", "").replace("}", "")
        t = scene_times.get(s["id"])
        if not txt or not t or t["start"] - last_end < min_gap:   # карточкалар сейрек (концепцияга жараша)
            continue
        start = t["start"] + 0.25
        end = min(start + 2.6, t["end"])
        if end - start < 1.2:
            continue
        items.append({"start": round(start, 3), "end": round(end, 3), "text": txt.upper()})
        last_end = end
    return items


def card_line(c: dict) -> str:
    return (f"Dialogue: 1,{ts_ass(c['start'])},{ts_ass(c['end'])},Card,,0,0,0,,"
            r"{\fad(260,320)\fscx92\fscy92\t(0,380,\fscx100\fscy100)\blur0.6}" + c["text"])


def card_events(scenes: list[dict], scene_times: dict[int, dict], concept: dict, min_gap: float = 12,
                hook: str = "") -> list[str]:
    return [card_line(c) for c in card_items(scenes, scene_times, min_gap, hook)]


class AnimationStage(Stage):
    name = "s6_animation"
    title = "Анимация жана эффекттер"
    retries = 0

    def run(self, ctx: Context) -> dict[str, Any]:
        shots = json.loads(ctx.path("clips", "shots.json").read_text(encoding="utf-8"))["shots"]
        scenes = json.loads(ctx.path("scenes.json").read_text(encoding="utf-8"))["scenes"]
        by_id = {s["id"]: s for s in scenes}
        timing = json.loads(ctx.path("subtitles", "timings.json").read_text(encoding="utf-8"))
        scene_times = {s["id"]: s for s in timing["scenes"]}

        from .. import cinematic
        cine = cinematic.enabled(ctx.store)       # СЫНАК режими гана (TEST папкасы + желек)
        theme = dominant_theme(scenes) if cine else None
        name = choose_concept(ctx.registry, ctx.video_id, theme)
        ec = None
        from .. import edit_concept
        if cine and edit_concept.enabled(ctx):   # ар видеонун ӨЗ чыгармачылык концепциясы (оригиналдуулук)
            ec = edit_concept.get(ctx, scenes)
            name = ec["name"]
            concept = edit_concept.concept_params(ec)
        else:
            concept = CONCEPTS[name]
        if cinematic.blocked_reason(ctx.store):
            ctx.log("   ⚠️ " + cinematic.blocked_reason(ctx.store))
        prev_trans = None
        rng = random.Random(int(hashlib.md5((ctx.video_id + name).encode()).hexdigest(), 16))
        plan = []
        prev_motion = None
        for i, sh in enumerate(shots):
            sc = by_id[sh["scene"]]
            options = [m for m in MOTIONS if m != prev_motion]
            motion = rng.choice(options)
            prev_motion = motion
            nxt = shots[i + 1] if i + 1 < len(shots) else None
            if nxt is None:
                trans = None
            elif nxt["scene"] != sh["scene"]:
                if cine:
                    n_scenes = len({s["scene"] for s in shots})
                    used_black = sum(1 for p_ in plan if (p_["transition_out"] or {}).get("type") == "fadeblack")
                    prev_trans = cinematic.transition_for(
                        rng, prev_trans, sc["emotion"], by_id[nxt["scene"]]["emotion"], used_black, n_scenes,
                        palette=edit_concept.transition_palette(ec) if ec else None)
                    trans = {"type": prev_trans, "dur": 0.0 if prev_trans == "cut" else
                             (ec["transition_sec"] if ec else cinematic.TRANSITION_SEC)}
                else:
                    trans = {"type": rng.choice(concept["transitions"]), "dur": 0.5}
            else:
                trans = {"type": "cut", "dur": 0.0}
            plan.append({"i": i, "motion": motion,
                         "intensity": round(SPEED.get(sc["emotion"], 1.0) * (1.25 if sh["kind"] == "image" else 1.0), 2),
                         "transition_out": trans})

        if cine:   # кыймыл v2: мааниге жараша, жумшак, ар түрдүү (pipeline/motion.py)
            from .. import motion as motion_v2

            mrng = random.Random(int(hashlib.md5((ctx.video_id + "motion").encode()).hexdigest(), 16))
            prefer = edit_concept.motion_prefer(ec) if ec else None
            scale = ec["motion_intensity"] if ec else 1.0
            for p_, m in zip(plan, motion_v2.plan_motions(shots, by_id, mrng, prefer=prefer)):
                p_["motion"], p_["intensity"] = m["motion"], round(m["intensity"] * scale, 2)

        gap = 4.0 * concept.get("card_every", 3)       # концепция: карточкалардын жыштыгы
        hook = ""
        if cine:   # видеонун башындагы hook карточкасы (s1 «КАРТОЧКА:»)
            from .. import hookmeta
            hookmeta.ensure(ctx, ctx.log)      # эски долбоор: meta.json'до hook жок болсо толуктайт
            try:
                hook = json.loads(ctx.path("script", "meta.json").read_text(encoding="utf-8")).get("hook_card", "")
            except Exception:
                hook = ""
        cards = card_events(scenes, scene_times, concept, gap, hook)
        if cine:   # HyperFrames үчүн структуралуу тизме (8-этап колдонот; иштебесе ASS калат)
            ctx.path("animation", "cards.json").write_text(
                json.dumps(card_items(scenes, scene_times, gap, hook), ensure_ascii=False, indent=1), encoding="utf-8")
        header = ("[Script Info]\nScriptType: v4.00+\nPlayResX: 1920\nPlayResY: 1080\n"
                  "ScaledBorderAndShadow: yes\n\n[V4+ Styles]\n"
                  "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, "
                  "BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, "
                  "BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
                  f"Style: Card,{concept['card_font']},86,{concept['card_color']},&H00FFFFFF&,"
                  "&H64000000&,&H00000000&,-1,0,0,0,100,100,3,0,1,2,4,5,200,200,0,204\n\n"
                  "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, "
                  "Effect, Text\n")
        ass = ctx.path("animation", "overlays.ass")
        ass.write_text(header + "\n".join(cards) + "\n", encoding="utf-8")

        if cine:
            from .. import motion as motion_v2

            counts = {m: sum(motion_v2.parse(p["motion"])[0] == m for p in plan) for m in motion_v2.TYPES}
        else:
            counts = {m: sum(p["motion"] == m for p in plan) for m in MOTIONS}
        if max(counts.values()) > 0.45 * len(plan):
            raise StageError(f"Кыймылдар бир түрдүү болуп калды: {counts}")
        out = ctx.path("animation", "plan.json")
        out.write_text(json.dumps({"concept": name, "concept_params": concept, "shots": plan,
                                   "cinematic": cine, "theme": theme},
                                  ensure_ascii=False, indent=1), encoding="utf-8")
        ctx.registry.setdefault("videos", {}).setdefault(ctx.video_id, {})["concept"] = name
        ctx.log(f"   ✓ Концепция: {name}; текст-карточкалар: {len(cards)}; кыймылдар: {counts}"
                + ("; 🎞 CINEMATIC (сынак): өтүүлөр " + str(sorted({p['transition_out']['type'] for p in plan
                                                                    if p['transition_out'] and p['transition_out']['type'] != 'cut'}))
                   if cine else ""))
        return {"plan_file": str(out), "overlays_file": str(ass), "concept": name,
                "cards": len(cards)}
