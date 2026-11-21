"""2-этап: Сценарийди сахналарга бөлүү.

Ишенимдүүлүк үчүн текстти МЕН бөлөм (сүйлөмдөрдүн чегинде, 16–34 сөз), ал эми
Gemini ар бир сахнага гана маалымат кошот: эмоция, визуалдык идея, англисче
издөө сөздөрү, белгилене турган сөздөр, экрандагы кыска текст, музыка маанайы.
Ошентип сахналардын тексти сценарийден бир тамгага да айырмаланбайт.
"""

from __future__ import annotations

import json
import re
from typing import Any

from ..visual_rules import VISUAL_RULES
from ..clipmemory import ClipMemory
from ..clipsearch import THEME_KEYS, detect_theme
from ..textutil import group_sentences, norm, word_count
from .base import Context, Stage, StageError, gemini_of

EMOTIONS = ["calm", "tense", "sad", "hopeful", "determined", "reflective", "inspired", "dramatic"]

PROMPT = """You are a film director and editor for a Russian-language psychology/motivation YouTube channel.
Below is the narration split into numbered scenes (Russian). For EVERY scene return metadata.

Return a JSON array with exactly {n} objects, in the same order, each:
{{
  "id": <scene number>,
  "emotion": one of {emotions},
  "visual": "<1 sentence, English: what the viewer should SEE; concrete, cinematic, metaphorical if abstract>",
  "theme": one of {themes} (the main subject of THIS scene),
  "queries": [5 different 2-4 word English stock-footage search queries for THIS scene:
              1) literal real-life footage of the idea, 2) a human situation that SHOWS the idea (not a literal
              picture of a metaphor word), 3) a different setting/place, 4) a close-up detail (hands, face,
              meaningful object), 5) mood/atmosphere with people],
  "keywords": ["<1-2 important Russian words or short phrases copied EXACTLY from this scene's text>"],
  "on_screen_text": "<optional: 2-5 Russian words for an animated title card, only for key ideas, else empty>",
  "music_mood": one of {moods}
}}

Rules:
- Visuals must illustrate the meaning of THIS scene, not generic "success" images.
- Prefer real-life footage queries (people, hands, city, nature, objects); avoid text, logos, faces of celebrities.
- Vary the visuals between neighbouring scenes; never repeat the same query twice in the whole video.
- Match the scene's meaning: fear, laziness, success, discipline, stress, relationships, etc. need
  DIFFERENT visuals — do not fall back to generic sunsets/mountains.
- Do NOT use these queries (already overused in earlier videos): {avoid}
{visual_rules}
- on_screen_text in at most 1 of every 4 scenes.
- Output JSON only.

SCENES:
{scenes}"""


SHOTS = ("wide", "medium", "close_up", "extreme_close_up", "over_shoulder", "pov", "insert")
CAMERAS = ("static", "slow_push_in", "pull_out", "pan", "tilt", "handheld", "tracking")
HERO_VIS = ("face", "body", "back", "hands", "none")

STORY_EXTRA = """
THIS VIDEO IS A SHORT CINEMATIC FILM about one protagonist. Scenes are consecutive moments of ONE story — the
shots must continue each other logically (e.g. comes home tired → opens the door → empty room → looks at the phone →
waits → sits alone by the window), never random illustrations.
Protagonist (keep the look IDENTICAL in every scene): {hero}
Stock search descriptor of the protagonist: "{descriptor}"
Act of each scene is given in [brackets]. Plan the camera like a director.
For EVERY scene ALSO return:
  "shot": one of {shots}, "camera": one of {cameras},
  "lighting": "<english, e.g. cold window light at dusk>", "location": "<english filmable place>",
  "hero": one of {hero_vis} (how the protagonist appears; vary it: faces only where emotion matters),
  "visual_prompt": "<english cinematic still description of the shot (subject, action, framing, light, mood);
                     when the protagonist is visible include the full descriptor>",
  "detail_query": "<2-4 word english stock query for an alternative shot WITHOUT a visible face that tells the same
                    moment (hands, silhouette, object, place)>"
For scenes where the protagonist is visible ("face"/"body"/"back"), the FIRST query must start with the gender and
age of the descriptor (e.g. "woman 40s ...") plus the action.
"""


def story_context(ctx, texts: list[str]) -> tuple[str, list[str], dict] | None:
    """story.json болсо: (кошумча промпт, ар сахнанын акты, каарман)."""
    from .. import story

    if not story.is_story(ctx.cfg):
        return None
    try:
        data = json.loads(ctx.path("script", "story.json").read_text(encoding="utf-8"))
    except Exception:
        return None
    hero, acts = data["hero"], data.get("acts") or []
    w, out = 0, []
    for t in texts:
        out.append(story.act_of_word(acts, w))
        w += len(t.split())
    extra = STORY_EXTRA.format(hero=story.hero_text(hero), descriptor=hero["descriptor"], shots=SHOTS,
                               cameras=CAMERAS, hero_vis=HERO_VIS)
    return extra, out, hero


def hero_core(hero: dict) -> str:
    return f"{hero['gender']} {int(hero.get('age', 35)) // 10 * 10}s"


class ScenesStage(Stage):
    name = "s2_scenes"
    title = "Сахналарга бөлүү"
    retries = 2

    def run(self, ctx: Context) -> dict[str, Any]:
        script = ctx.path("script", "script.txt").read_text(encoding="utf-8")
        texts = group_sentences(script)
        if norm(" ".join(texts)) != norm(script):
            raise StageError("Сахналарга бөлүүдө текст жоголду (ички ката)")
        moods = ctx.cfg.niche_data.get("music_moods", ["cinematic"])

        mem = ClipMemory.load(ctx.store, ctx.registry)
        avoid = mem.top_queries(40)
        avoid_set = {q.lower() for q in avoid}
        g = gemini_of(ctx)
        sctx = story_context(ctx, texts)
        acts = sctx[1] if sctx else [None] * len(texts)
        numbered = "\n".join(f"{i + 1}. " + (f"[{acts[i]}] " if acts[i] else "") + t for i, t in enumerate(texts))
        meta = g.json(PROMPT.format(n=len(texts), emotions=EMOTIONS, moods=moods, scenes=numbered,
                                  themes=THEME_KEYS, avoid="; ".join(avoid) or "(none)",
                                  visual_rules=VISUAL_RULES) + (sctx[0] if sctx else ""),
                      purpose="scenes", temperature=0.6)
        if isinstance(meta, dict):
            meta = meta.get("scenes") or next((v for v in meta.values() if isinstance(v, list)), [])
        if not isinstance(meta, list) or len(meta) != len(texts):
            raise StageError(f"Gemini {len(texts)} сахна үчүн {len(meta) if isinstance(meta, list) else 0} "
                             f"жооп берди")

        scenes = []
        for i, (text, m) in enumerate(zip(texts, meta)):
            m = m if isinstance(m, dict) else {}
            queries = [q.strip() for q in m.get("queries", []) if isinstance(q, str) and q.strip()]
            # мурунку видеолордо көп колдонулган сөздөр — аягына (башкалары биринчи изделет)
            queries = [q for q in queries if q.lower() not in avoid_set] + \
                      [q for q in queries if q.lower() in avoid_set]
            theme = m.get("theme") if m.get("theme") in THEME_KEYS else detect_theme(text)
            low = text.lower()
            keywords = [k.strip() for k in m.get("keywords", [])
                        if isinstance(k, str) and k.strip() and k.strip().lower() in low][:2]
            ost = (m.get("on_screen_text") or "").strip()
            scenes.append({
                "id": i + 1,
                "text": text,
                "words": word_count(text),
                "emotion": m.get("emotion") if m.get("emotion") in EMOTIONS else "reflective",
                "visual": (m.get("visual") or "").strip(),
                "theme": theme,
                "queries": queries[:6] or [ctx.cfg.niche_data.get("visual_style", "cinematic")],
                "keywords": keywords,
                "on_screen_text": ost if 0 < word_count(ost) <= 6 else "",
                "music_mood": m.get("music_mood") if m.get("music_mood") in moods else moods[0],
            })
            if sctx:                           # кино-сахнанын планы (режиссёрдук разбивка)
                hero = sctx[2]
                vis = m.get("hero") if m.get("hero") in HERO_VIS else "none"
                sc = scenes[-1]
                sc.update({"act": acts[i], "shot": m.get("shot") if m.get("shot") in SHOTS else "medium",
                           "camera": m.get("camera") if m.get("camera") in CAMERAS else "static",
                           "lighting": str(m.get("lighting") or "")[:120], "location": str(m.get("location") or "")[:120],
                           "hero": vis, "visual_prompt": str(m.get("visual_prompt") or "")[:400],
                           "detail_query": str(m.get("detail_query") or "")[:60]})
                core = hero_core(hero)
                if vis in ("face", "body", "back") and sc["queries"] and hero["gender"] not in sc["queries"][0].lower():
                    sc["queries"][0] = f"{core} {sc['queries'][0]}"[:60]
                if sc["detail_query"]:
                    sc["queries"] = sc["queries"][:6] + [sc["detail_query"]]

        no_query = sum(1 for s in scenes if len(s["queries"]) < 2)
        if no_query > len(scenes) // 3:
            raise StageError(f"{no_query} сахнада издөө сөздөрү жетишсиз")
        out = ctx.path("scenes.json")
        out.write_text(json.dumps({"scenes": scenes}, ensure_ascii=False, indent=1), encoding="utf-8")
        if sctx:
            from collections import Counter

            ctx.log(f"   🎥 Кино-разбивка: планы {dict(Counter(s['shot'] for s in scenes))}; каарман "
                    f"{dict(Counter(s['hero'] for s in scenes))}; актылар {dict(Counter(s['act'] for s in scenes))}")
        ctx.log(f"   ✓ {len(scenes)} сахна; маанайлар: "
                + ", ".join(sorted({s['music_mood'] for s in scenes})))
        return {"scenes_file": str(out), "count": len(scenes)}
