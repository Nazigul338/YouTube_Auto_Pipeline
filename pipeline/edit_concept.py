"""Ар бир видеонун ӨЗҮНЧӨ чыгармачылык монтаж концепциясы (оригиналдуулук — №1 приоритет).

Колдонуучу (2026-11-20): «5 даяр вариант менен чектелбе; түс, ритм, кыймыл, структура, өтүүлөр, субтитр жана
визуалдык баяндоо — бирдиктүү концепция болсун; мурункуларга окшош болсо — жаңы концепция иштеп чыгып кайра текшер».
YouTube «Inauthentic content» (repetitive / mass-produced, 2025-07-15).

1. Gemini видеонун темасын, эмоционалдык жолун жана сахналарын окуп, ӨЗ концепциясын жазат (`BRIEF_PROMPT`):
   визуалдык дүйнө, кайталануучу мотивдер, сахна сайын мотив-кадр, түс (сандык параметрлер), ыргак (базалык
   кадр + 4 акт), кыймыл жана өтүү салмактары, субтитрдин шрифти/түсү/формасы, карточкалардын жыштыгы, музыка маанайы.
2. Код аны коопсуз чектерге кысат (`normalize`) — QA/YouTube чектери бузулбайт.
3. Мурунку ДАЯР видеолор менен 7 топ боюнча салыштырылат (`compare`); окшош болсо — Gemini'ге «кайсы топтор окшош»
   айтылып, концепция КАЙРА жазылат (≤ MAX_ATTEMPTS). Gemini иштебесе — параметрдик запас (эң алыс вариант).
4. Видео кайра иштетилсе — сакталган концепция колдонулат. Video_001 (эски, концепциясыз) — LEGACY катары салыштырылат.

Этаптар: s4 (субтитр), s5 (ыргак + мотив-кадрлар + кадр идеялары), s6 (түс, кыймыл, өтүү, карточкалар),
s7 (музыка маанайы/деңгээли), s8 (түс/карточка — plan.json аркылуу), s9 (салыштыруу, милдеттүү).
"""

from __future__ import annotations

import hashlib
import json
import random
import re

MOTION_TYPES = ("zoom_in", "zoom_out", "pan_left", "pan_right", "pan_up", "pan_down", "ken_burns", "dolly",
                "dolly_out", "handheld")
TRANSITION_TYPES = ("dissolve", "fade", "fadeblack", "fadegrays", "smoothleft", "smoothright", "smoothup",
                    "smoothdown", "wipeleft", "wiperight", "slideleft", "slideright", "cut")
FONTS = ("Montserrat Bold", "Montserrat SemiBold", "Montserrat Black", "DejaVu Sans Bold", "DejaVu Serif Bold")
GROUPS = ("grade", "pacing", "motion", "transitions", "subtitles", "music", "motifs")
MIN_GROUPS = 4          # ар бир мурунку даяр видеодон кеминде ушунча топ айырмаланат
MIN_MEAN = 0.30         # жана орточо аралык (0..1)
GROUP_DIFF = 0.25       # топ «айырмаланат» деп эсептелген чек
MAX_ATTEMPTS = 3

RANGES = {"contrast": (1.0, 1.16), "saturation": (0.7, 1.2), "gamma": (0.95, 1.05), "warmth": (-1.0, 1.0),
          "tint": (-1.0, 1.0), "vignette": (3.5, 6.0), "base_shot": (2.9, 4.3), "act_pace": (0.85, 1.15),
          "motion_intensity": (0.6, 1.3), "transition_sec": (0.35, 0.9), "sub_outline": (2.5, 6.0),
          "sub_size": (66, 76), "card_every": (3, 7), "music_level": (-2.0, 2.0)}

THEME_MOTIFS = {   # запас (Gemini иштебесе) — темага жараша кайталануучу мотивдер
    "fear": ["dark corridor", "trembling hands", "foggy street", "closed door"],
    "stress": ["crowded subway", "clock ticking", "tired eyes", "rain on window"],
    "relationships": ["two cups of tea", "empty chair", "hands holding", "kitchen at night"],
    "psychology": ["mirror reflection", "window light", "notebook writing", "quiet room"],
    "confidence": ["walking forward", "open road", "deep breath", "city morning"],
    "motivation": ["running at dawn", "climbing stairs", "sunrise window", "tying shoes"],
    "time": ["old clock", "calendar pages", "sand falling", "train window"],
    "change": ["packing boxes", "new road", "door opening", "seasons trees"],
}

BRIEF_PROMPT = """You are the director and editor of a Russian-language psychology YouTube channel.
Design an ORIGINAL, unified montage concept for THIS video only. Every element must serve its theme:
visual world, recurring visual motifs, colour, editing rhythm by act, camera movement, transitions,
subtitle look, title-card frequency and music atmosphere must feel like one creative idea.

Video title: {title}
Dominant theme: {theme}
Emotional path of the scenes: {arc}
Scenes (id. text):
{scenes}

Concepts of our PREVIOUS videos (yours must look and feel clearly different from each):
{previous}
{feedback}
{rules}
Return JSON only:
{{"name": "<2-4 word concept name>", "world": "<1-2 sentences: the visual world and how the story is told>",
  "motifs": ["<3-5 recurring concrete filmable motifs, 1-3 English words each>"],
  "scene_motifs": {{"<scene id>": "<2-4 word English stock query using a motif that fits this scene>"}},
  "grade": {{"contrast": 1.0-1.16, "saturation": 0.7-1.2, "gamma": 0.95-1.05, "warmth": -1..1, "tint": -1..1,
             "vignette": 3.5-6}},
  "base_shot": 2.9-4.3, "act_pace": [hook, build, turn, resolve each 0.85-1.15; <1 = faster cuts],
  "motion": {{<weights 0..1 for {motions}>}}, "motion_intensity": 0.6-1.3,
  "transitions": {{<weights 0..1 for {transitions}>}}, "transition_sec": 0.35-0.9,
  "subtitles": {{"font": one of {fonts}, "primary": "#RRGGBB", "highlight": "#RRGGBB", "outline": 2.5-6,
                 "box": true|false, "size": 66-76}},
  "cards": {{"every": 3-7, "color": "#RRGGBB"}},
  "music_mood": one of {moods}, "music_level": -2..2}}"""


# ---------------------------------------------------------------- нормалдаштыруу

def _clamp(v, key, default):
    lo, hi = RANGES[key]
    try:
        x = float(v)
    except (TypeError, ValueError):
        x = default
    return round(min(hi, max(lo, x)), 3)


def _hex(v, default: str) -> str:
    return v.upper() if isinstance(v, str) and re.fullmatch(r"#[0-9A-Fa-f]{6}", v) else default


def _weights(d, keys) -> dict:
    out = {}
    for k in keys:
        try:
            out[k] = max(0.0, min(1.0, float((d or {}).get(k, 0))))
        except (TypeError, ValueError):
            out[k] = 0.0
    s = sum(out.values())
    if s <= 0:
        out = {k: 1.0 for k in keys}
        s = float(len(keys))
    return {k: round(v / s, 3) for k, v in out.items()}


def normalize(raw: dict, moods: list[str] | None = None, scene_ids: list | None = None) -> dict:
    """Gemini'нин жообун коопсуз чектерге кысат (QA: кадр 2.9–4.3 сек, субтитр ≥64 px ж.б.)."""
    raw = raw if isinstance(raw, dict) else {}
    g = raw.get("grade") or {}
    sub = raw.get("subtitles") or {}
    cards = raw.get("cards") or {}
    pace = list(raw.get("act_pace") or [1, 1, 1, 1])[:4] + [1] * 4
    motifs = [str(m).strip()[:40] for m in (raw.get("motifs") or []) if str(m).strip()][:5]
    sm = raw.get("scene_motifs") or {}
    ids = {str(i) for i in (scene_ids or [])}
    return {
        "name": str(raw.get("name") or "untitled")[:60], "world": str(raw.get("world") or "")[:300],
        "motifs": motifs,
        "scene_motifs": {str(k): str(v)[:60] for k, v in sm.items() if (not ids or str(k) in ids) and str(v).strip()},
        "grade": {k: _clamp(g.get(k), k, d) for k, d in
                  (("contrast", 1.06), ("saturation", 1.0), ("gamma", 1.0), ("warmth", 0.0), ("tint", 0.0),
                   ("vignette", 5.0))},
        "base_shot": _clamp(raw.get("base_shot"), "base_shot", 3.6),
        "act_pace": [_clamp(x, "act_pace", 1.0) for x in pace[:4]],
        "motion": _weights(raw.get("motion"), MOTION_TYPES),
        "motion_intensity": _clamp(raw.get("motion_intensity"), "motion_intensity", 1.0),
        "transitions": _weights(raw.get("transitions"), TRANSITION_TYPES),
        "transition_sec": _clamp(raw.get("transition_sec"), "transition_sec", 0.7),
        "subtitles": {"font": sub.get("font") if sub.get("font") in FONTS else FONTS[0],
                      "primary": _hex(sub.get("primary"), "#FFFFFF"), "highlight": _hex(sub.get("highlight"), "#FFC83F"),
                      "outline": _clamp(sub.get("outline"), "sub_outline", 4.4), "box": bool(sub.get("box")),
                      "size": int(_clamp(sub.get("size"), "sub_size", 72))},
        "cards": {"every": int(_clamp(cards.get("every"), "card_every", 4)), "color": _hex(cards.get("color"), "#F2C14E")},
        "music_mood": raw.get("music_mood") if (not moods or raw.get("music_mood") in moods) else (moods or [""])[0],
        "music_level": _clamp(raw.get("music_level"), "music_level", 0.0),
    }


# ---------------------------------------------------------------- колдонуу (этаптар үчүн)

def grade_filter(b: dict) -> str:
    g = b["grade"]
    w, t = g["warmth"], g["tint"]
    return (f"eq=contrast={g['contrast']:.3f}:saturation={g['saturation']:.3f}:gamma={g['gamma']:.3f},"
            f"colorbalance=rs={0.05 * w:.3f}:gs={0.03 * t:.3f}:bs={-0.05 * w:.3f}:"
            f"rh={0.02 * w:.3f}:bh={-0.02 * w:.3f}")


def ass_color(hex_rgb: str, alpha: str = "00") -> str:
    h = hex_rgb.lstrip("#")
    return f"&H{alpha}{h[4:6]}{h[2:4]}{h[0:2]}".upper()


def concept_params(b: dict) -> dict:
    """s6/s8 `plan.json → concept_params` (s8 ушуну окуйт)."""
    font = "Montserrat Bold" if b["subtitles"]["font"].startswith("Montserrat") else "DejaVu Sans Bold"
    return {"grade": grade_filter(b), "vignette": f"PI/{b['grade']['vignette']:.2f}",
            "transitions": [t for t, w in sorted(b["transitions"].items(), key=lambda x: -x[1]) if w > 0][:4],
            "card_color": ass_color(b["cards"]["color"]), "card_font": font, "card_every": b["cards"]["every"],
            "transition_sec": b["transition_sec"], "brief_name": b["name"]}


def motion_prefer(b: dict) -> list[str]:
    return [t for t, w in sorted(b["motion"].items(), key=lambda x: -x[1]) if w > 0][:4]


def transition_palette(b: dict, n: int = 20) -> list[str]:
    """Салмак боюнча палитра (cinematic.transition_for rng.choice'ке)."""
    out = []
    for t, w in b["transitions"].items():
        out += [t] * int(round(w * n))
    return out or ["fade"]


def pacing_targets(targets: dict, scenes: dict, b: dict) -> dict:
    """s5: сахна темпи = базалык кадр × (эмоция / 3.6) × актынын ыргагы; 2.9–4.3 сек."""
    ids = sorted(targets)
    n = len(ids)
    out = {}
    for k, sid in enumerate(ids):
        act = b["act_pace"][min(3, int(4 * k / max(1, n)))]
        v = b["base_shot"] * (targets[sid] / 3.6) * act
        out[sid] = round(min(4.3, max(2.9, v)), 2)
    return out


def subtitle_style(b: dict, font: str, margin: int) -> tuple[str, str]:
    """s4: (ASS «Style: Sub,…» сабы, ачкыч сөздүн түс тегги). Өлчөм/орун QA чегинде (≥64 px, түбүнөн 60–140)."""
    s = b["subtitles"]
    box = s["box"]
    style = (f"Style: Sub,{font},{s['size']},{ass_color(s['primary'])},{ass_color(s['primary'])},"
             f"{'&H64000000' if box else '&H00101010'},{'&H64000000' if box else '&H96000000'},"
             f"-1,0,0,0,100,100,0.6,0,{3 if box else 1},{s['outline']},{0 if box else 2.0},2,200,200,{margin},204")
    h = s["highlight"].lstrip("#")
    return style, "{\\c&H" + (h[4:6] + h[2:4] + h[0:2]).upper() + "&}"


# ---------------------------------------------------------------- салыштыруу

def _vec_dist(a: dict, b: dict) -> float:
    keys = set(a) | set(b)
    return sum(abs(a.get(k, 0) - b.get(k, 0)) for k in keys) / 2


def _norm(v, key):
    lo, hi = RANGES[key]
    return (v - lo) / (hi - lo)


def _rgb(h: str):
    h = h.lstrip("#")
    return [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]


def group_distances(a: dict, b: dict) -> dict:
    """7 топ боюнча 0..1 аралык."""
    ga, gb = a["grade"], b["grade"]
    grade = sum(abs(_norm(ga[k], k) - _norm(gb[k], k)) for k in ga) / len(ga) * 2.2
    pacing = (abs(_norm(a["base_shot"], "base_shot") - _norm(b["base_shot"], "base_shot")) +
              sum(abs(x - y) for x, y in zip(a["act_pace"], b["act_pace"])) / 0.3 / 4) / 1.5
    motion = _vec_dist(a["motion"], b["motion"]) + abs(a["motion_intensity"] - b["motion_intensity"]) / 0.7 * 0.3
    trans = _vec_dist(a["transitions"], b["transitions"]) + abs(a["transition_sec"] - b["transition_sec"]) / 0.55 * 0.3
    sa, sb = a["subtitles"], b["subtitles"]
    subs = ((sa["font"] != sb["font"]) * 0.3 + (sa["box"] != sb["box"]) * 0.3 +
            sum(abs(x - y) for x, y in zip(_rgb(sa["primary"]), _rgb(sb["primary"]))) / 3 * 0.3 +
            sum(abs(x - y) for x, y in zip(_rgb(sa["highlight"]), _rgb(sb["highlight"]))) / 3 * 0.6 +
            abs(sa["size"] - sb["size"]) / 10 * 0.2)
    music = (a["music_mood"] != b["music_mood"]) * 0.8 + abs(a["music_level"] - b["music_level"]) / 4 * 0.2
    ma, mb = {m.lower() for m in a["motifs"]}, {m.lower() for m in b["motifs"]}
    motifs = 1.0 - (len(ma & mb) / len(ma | mb) if (ma | mb) else 0.0) if (ma and mb) else 1.0
    return {k: round(min(1.0, v), 3) for k, v in zip(GROUPS, (grade, pacing, motion, trans, subs, music, motifs))}


def compare(a: dict, b: dict) -> dict:
    d = group_distances(a, b)
    differ = [k for k, v in d.items() if v >= GROUP_DIFF]
    mean = round(sum(d.values()) / len(d), 3)
    return {"groups": d, "differ": differ, "same": [k for k in GROUPS if k not in differ], "mean": mean,
            "ok": len(differ) >= MIN_GROUPS and mean >= MIN_MEAN}


LEGACY_GRADES = {   # s6 CONCEPTS → болжолдуу параметрлер (Video_001 сыяктуу эски видеолор үчүн)
    "warm_cinematic": (1.06, 1.08, 0.98, 0.8, 0.2), "cool_moody": (1.08, 0.86, 0.97, -0.8, 0.0),
    "teal_orange": (1.1, 1.05, 1.0, 0.0, 0.0), "muted_film": (1.04, 0.72, 1.02, 0.2, 0.0),
    "golden_hour": (1.05, 1.12, 0.97, 1.0, 0.6)}


def legacy_brief(entry: dict) -> dict:
    """Концепциясыз эски видео (Video_001) — эски эрежелердин болжолдуу концепциясы (салыштыруу үчүн гана)."""
    c, s, gm, w, t = LEGACY_GRADES.get(entry.get("concept"), (1.06, 1.0, 1.0, 0.0, 0.0))
    return normalize({"name": "legacy", "grade": {"contrast": c, "saturation": s, "gamma": gm, "warmth": w, "tint": t,
                                                  "vignette": 5.0},
                      "base_shot": 3.5, "act_pace": [1, 1, 1, 1], "motion": {k: 1 for k in MOTION_TYPES},
                      "transitions": {"dissolve": 5, "fade": 5, "smoothleft": 2, "smoothright": 1, "fadeblack": 1},
                      "transition_sec": 0.7, "subtitles": {"font": "Montserrat Bold", "primary": "#FFFFFF",
                                                           "highlight": "#FFC83F", "outline": 4.4, "box": False,
                                                           "size": 72},
                      "music_mood": (entry.get("fingerprint") or {}).get("music_mood") or "", "motifs": []})


def brief_of(entry: dict) -> dict:
    return entry["edit_brief"] if entry.get("edit_brief") else legacy_brief(entry)


def finished_others(registry: dict, video_id: str) -> dict[str, dict]:
    return {vid: v for vid, v in registry.get("videos", {}).items()
            if vid != video_id and (v.get("final") or v.get("final_cinematic"))}


def check_against(b: dict, registry: dict, video_id: str) -> dict[str, dict]:
    return {vid: compare(b, brief_of(v)) for vid, v in finished_others(registry, video_id).items()}


# ---------------------------------------------------------------- түзүү

def fallback(registry: dict, video_id: str, theme: str, moods: list[str], scene_ids: list) -> dict:
    """Gemini жок болсо: 300 кокус (бирок туруктуу) концепциядан мурункулардан эң алысы."""
    rng = random.Random(int(hashlib.md5(f"brief:{video_id}".encode()).hexdigest(), 16))
    prev = [brief_of(v) for v in finished_others(registry, video_id).values()]
    best, best_key = None, None
    for _ in range(300):
        raw = {"name": f"{theme} variation", "motifs": rng.sample(THEME_MOTIFS.get(theme, THEME_MOTIFS["psychology"]), 3),
               "grade": {k: rng.uniform(*RANGES[k]) for k in ("contrast", "saturation", "gamma", "warmth", "tint",
                                                               "vignette")},
               "base_shot": rng.uniform(*RANGES["base_shot"]), "act_pace": [rng.uniform(0.85, 1.15) for _ in range(4)],
               "motion": {k: rng.random() ** 2 for k in MOTION_TYPES},
               "motion_intensity": rng.uniform(*RANGES["motion_intensity"]),
               "transitions": {k: rng.random() ** 3 for k in TRANSITION_TYPES},
               "transition_sec": rng.uniform(*RANGES["transition_sec"]),
               "subtitles": {"font": rng.choice(FONTS), "primary": "#%02X%02X%02X" % tuple(rng.randint(225, 255)
                                                                                          for _ in range(3)),
                             "highlight": "#%02X%02X%02X" % tuple(rng.randint(60, 255) for _ in range(3)),
                             "outline": rng.uniform(2.5, 6), "box": rng.random() < 0.4, "size": rng.randint(66, 76)},
               "cards": {"every": rng.randint(3, 7), "color": "#%02X%02X%02X" % tuple(rng.randint(80, 255) for _ in range(3))},
               "music_mood": rng.choice(moods) if moods else "", "music_level": rng.uniform(-2, 2)}
        b = normalize(raw, moods, scene_ids)
        res = [compare(b, p) for p in prev]
        key = (min((len(r["differ"]) for r in res), default=7), min((r["mean"] for r in res), default=1.0))
        if best_key is None or key > best_key:
            best, best_key = b, key
    best["source"] = "fallback"
    return best


def create(ctx, scenes: list[dict], title: str = "") -> dict:
    """Gemini концепция жазат → кысуу → мурункулар менен салыштыруу → окшош болсо кайра (≤MAX_ATTEMPTS) → запас."""
    from .stages.s6_animation import dominant_theme
    from .visual_rules import VISUAL_RULES

    theme = dominant_theme(scenes)
    moods = list(ctx.cfg.niche_data.get("music_moods", [])) if getattr(ctx, "cfg", None) else []
    ids = [s["id"] for s in scenes]
    prev = finished_others(ctx.registry, ctx.video_id)
    prev_txt = "\n".join(f"- {vid}: {json.dumps({k: brief_of(v)[k] for k in ('name', 'world', 'motifs', 'grade', 'base_shot', 'music_mood')}, ensure_ascii=False)}"
                         for vid, v in list(prev.items())[-8:]) or "- (none yet)"
    feedback, log = "", []
    g = None
    try:
        from .stages.base import gemini_of
        g = gemini_of(ctx)
    except Exception:
        g = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        if g is None:
            break
        try:
            raw = g.json(BRIEF_PROMPT.format(
                title=title or ctx.video_id, theme=theme, arc=" → ".join(s.get("emotion", "") for s in scenes),
                scenes="\n".join(f"{s['id']}. {s.get('text', '')[:140]}" for s in scenes), previous=prev_txt,
                feedback=feedback, rules=VISUAL_RULES, motions=", ".join(MOTION_TYPES),
                transitions=", ".join(TRANSITION_TYPES), fonts=", ".join(FONTS), moods=", ".join(moods)),
                purpose="edit_brief", temperature=0.95)
        except Exception as e:
            log.append(f"{attempt}: Gemini {type(e).__name__}")
            break
        if not isinstance(raw, dict) or not raw.get("grade"):
            log.append(f"{attempt}: жооп бош")
            continue
        b = normalize(raw, moods, ids)
        res = check_against(b, ctx.registry, ctx.video_id)
        bad = {vid: r for vid, r in res.items() if not r["ok"]}
        if not bad:
            b.update(source="gemini", attempts=attempt, theme=theme, checks=res)
            return b
        feedback = ("\nYOUR PREVIOUS ATTEMPT WAS TOO SIMILAR — redesign it. " + "; ".join(
            f"vs {vid}: same {r['same']}" for vid, r in bad.items()) + "\n")
        log.append(f"{attempt}: окшош {', '.join(bad)}")
    b = fallback(ctx.registry, ctx.video_id, theme, moods, ids)
    b.update(theme=theme, attempts_log=log, checks=check_against(b, ctx.registry, ctx.video_id))
    return b


def enabled(ctx) -> bool:
    from . import cinematic

    return cinematic.enabled(getattr(ctx, "store", None))


def get(ctx, scenes: list[dict] | None = None) -> dict:
    """Видеонун концепциясы (бир жолу түзүлөт → реестр + Projects/<ID>/edit_brief.json). Кайра иштетүүдө өзгөрбөйт."""
    entry = ctx.registry.setdefault("videos", {}).setdefault(ctx.video_id, {})
    if entry.get("edit_brief"):
        return entry["edit_brief"]
    p = ctx.path("edit_brief.json")
    if p.exists():
        entry["edit_brief"] = json.loads(p.read_text(encoding="utf-8"))
        return entry["edit_brief"]
    if scenes is None:
        scenes = json.loads(ctx.path("scenes.json").read_text(encoding="utf-8"))["scenes"]
    title = ""
    try:
        title = json.loads(ctx.path("script", "meta.json").read_text(encoding="utf-8")).get("title", "")
    except Exception:
        pass
    b = create(ctx, scenes, title)
    entry["edit_brief"] = b
    p.write_text(json.dumps(b, ensure_ascii=False, indent=1), encoding="utf-8")
    worst = min((len(r["differ"]) for r in b.get("checks", {}).values()), default=None)
    ctx.log(f"   🎬 Монтаж концепциясы «{b['name']}» ({b.get('source')}, тема {b.get('theme')}): {b['world'][:120]} | "
            f"мотивдер: {', '.join(b['motifs'])} | кадр {b['base_shot']} сек, акт {b['act_pace']} | "
            f"мурункулардан айырма: {'—' if worst is None else f'≥{worst}/7 топ'}")
    return b


def reject(ctx, reason: str, rework_from: str = "s4_subtitles") -> None:
    """QA окшоштук тапса: концепция жокко чыгарылат — кийинки иштетүүдө ЖАҢЫ концепция түзүлөт.
    rework_from — кайсы этаптан кайра: монтаж окшош → s4; кадрлардын өзү окшош (клиптер) → s5 (жаңы клиптер)."""
    entry = ctx.registry.setdefault("videos", {}).setdefault(ctx.video_id, {})
    order = ("s4_subtitles", "s5_visuals")
    cur = entry.get("rework_from")
    entry["rework_from"] = rework_from if cur not in order or order.index(rework_from) > order.index(cur) else cur
    old = entry.pop("edit_brief", None)
    if old:
        entry.setdefault("rejected_briefs", []).append({"name": old.get("name"), "reason": reason[:200]})
    try:
        ctx.path("edit_brief.json").unlink(missing_ok=True)
    except Exception:
        pass
