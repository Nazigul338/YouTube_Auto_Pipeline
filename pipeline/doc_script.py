"""Англисче «Tech History» документалдык сценарийи (s1, `structure: doc`, 2026-11-24).

Орусча мотивация жолуна (s1_script.ScriptStage) тийбейт — s1 `lang.is_doc(cfg)` болсо ушул жерге өтөт.

Ирети:
  1. Wikipedia булактары (sources.pick_articles) — булак жок болсо видео ЖАСАЛБАЙТ (ойдон факты жок);
  2. сценарий ОШОЛ булактардан гана (1150–1300 сөз ≈ 8 мүн), өз hook түрү, мурункулардан башка;
  3. көлөм, кайталоо, мурункулар менен окшоштук (s1 функциялары, тилге көз карандысыз);
  4. hook/retention (retention.improve, lang="en");
  5. факты текшерүү (sources.verify): тастыкталбагандар оңдолот (≤ FACT_ROUNDS), калса — StageError.
Чыгат: script.txt, meta.json, retention.json, sources.json, facts.json, fact_check.txt (s1 менен бирдей + 2 файл).
"""

from __future__ import annotations

import json
import re
from typing import Any

from . import retention, sources
from .stages.base import Context, StageError, gemini_of
from .textutil import duplicate_sentences, word_count

FACT_ROUNDS = 3

HOOK_TYPES_EN = {
    "paradox": "a paradox from the story: two true facts that seem impossible together",
    "stakes": "the moment everything was at stake — what could have been lost, in one concrete image",
    "question": "an open question the viewer cannot answer yet, about how or why it happened",
    "cold_open": "drop the viewer into one concrete historical moment (place, year, object) right before the turn",
    "number": "one striking, sourced number that makes the story feel unbelievable",
    "reversal": "the ending first: how it turned out — and the hint that the path there was not what you think",
}
HOOK_BANNED_EN = ("hi ", "hello", "welcome", "in this video", "today we", "today i", "let's talk",
                  "have you ever wondered", "what's up")

SCRIPT_PROMPT = """{role}

TOPIC OF THIS VIDEO: {topic}

NARRATIVE APPROACH OF THIS VIDEO:
{style}

FACTS — THE MOST IMPORTANT RULE:
- Use ONLY facts that are stated in the SOURCES below (dates, numbers, money, names, places, events, quotes).
- If a detail is not in the SOURCES, do not mention it. Never invent dialogue, quotes, numbers or "on that night…"
  scenes. You may describe the general atmosphere of the era without specific facts.
- Do not present guesses as facts; use "reportedly"/"according to" only if the SOURCES say so.

RULES:
{rules}
- Length: strictly {wmin}–{wmax} words (~8 minutes of narration). This is important.
- Narration text only: no headings, no stage directions in brackets, no emoji, no numbered lists.
- Paragraphs of 2–5 sentences, vivid spoken English, short sentences.
- Write so it can be SHOWN: concrete objects, machines, places and actions of the era.

HOOK — THE FIRST 3 SECONDS:
- Hook type of this video: {hook}.
- First sentence: at most 10 words. No greeting, no "in this video". Straight into the story.
- Sentences 2–3 honestly tell the viewer what they will understand by the end — and the script MUST deliver it.

RETENTION (every 20–40 seconds something new): a new fact, a turn, a question or a consequence. In the middle,
2–3 honest open questions or reversals (answered later). The ending lands the legacy/lesson of the story clearly.

OUR PREVIOUS VIDEOS (do not repeat their opening, structure or angle):
{previous}

RESPONSE FORMAT:
TITLE: <honest, curiosity-driven YouTube title, max 70 characters, no clickbait>
CARD: <2–5 words: the hook's punch, for the screen in the first second>

<full narration text>

SOURCES:
{sources}"""

LENGTH_PROMPT = """The script has {n} words. {action}
Keep the style and the meaning. Do NOT add facts, numbers, names or quotes that are not already in the text.
Return only the full text.

TEXT:
{text}"""

DEDUPE_PROMPT = """These sentences are repeated in the text:
{dups}
Rewrite only the repeated sentences (the second occurrence) in other words; keep everything else.
Return only the full text.

TEXT:
{text}"""


def clean(text: str) -> str:
    lines = []
    for line in text.replace("\r", "").split("\n"):
        s = line.strip()
        if re.match(r"^(#+|\*\*?[^*]+\*\*?:?$|TITLE:|Title:|CARD:|Card:|SOURCES?:)", s):
            continue
        s = re.sub(r"\[[^\]]{0,80}\]", "", s)
        s = re.sub(r"\*+([^*]+)\*+", r"\1", s)
        s = re.sub(r"^\s*[-•]\s+", "", s)
        s = re.sub(r"[\U0001F300-\U0001FAFF☀-➿]", "", s)
        lines.append(s.strip())
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def split_draft(draft: str) -> tuple[str, str, str]:
    """(title, card, body)."""
    tm = re.search(r"^\s*TITLE\s*:\s*(.+)$", draft, re.M | re.I)
    cm = re.search(r"^\s*CARD\s*:\s*(.+)$", draft, re.M | re.I)
    title = tm.group(1).strip().strip('"“”') if tm else ""
    card = cm.group(1).strip().strip('"“”')[:40] if cm else ""
    body = draft[max(tm.end() if tm else 0, cm.end() if cm else 0):]
    body = re.split(r"\n\s*SOURCES?\s*:", body)[0]
    return title, card, clean(body)


def adjust_length(g, text: str, lo: int, hi: int, log) -> str:
    for attempt in range(3):
        n = word_count(text)
        if lo <= n <= hi:
            return text
        target = (lo + hi) // 2
        action = (f"Expand it to ~{target} words: deepen an existing moment with sourced detail already in the text, "
                  f"or explain a consequence — no filler." if n < lo else
                  f"Shorten it to ~{target} words: remove repetition and secondary details; keep the hook, the "
                  f"turning point and the ending.")
        log(f"   ✎ Сөз саны {n} → {target} ({attempt + 1}-аракет)")
        new = clean(g.text(LENGTH_PROMPT.format(n=n, action=action, text=text), purpose="length", temperature=0.5))
        if word_count(new) > 200 and abs(word_count(new) - target) < abs(n - target):
            text = new
    n = word_count(text)
    if not (lo - 60 <= n <= hi + 60):
        raise StageError(f"Сценарийдин көлөмүн {lo}–{hi} сөзгө келтирүү ишке ашкан жок ({n} сөз)")
    return text


def fix_duplicates(g, text: str) -> str:
    dups = duplicate_sentences(text)
    if not dups:
        return text
    new = clean(g.text(DEDUPE_PROMPT.format(dups="\n".join(f"- {d}" for d in dups), text=text),
                       purpose="dedupe", temperature=0.4))
    return new if word_count(new) > 0.8 * word_count(text) else text


def choose_hook(registry: dict, video_id: str) -> str:
    from .stages.s1_script import hash_str
    import hashlib

    hist = [v.get("hook_type") for k, v in sorted(registry.get("videos", {}).items()) if k != video_id]
    last = next((h for h in reversed(hist) if h), None)
    seed = int(hashlib.md5(video_id.encode()).hexdigest(), 16)
    return min((k for k in HOOK_TYPES_EN if k != last), key=lambda k: (hist.count(k), (hash_str(k) ^ seed) % 97))


def facts_pass(g, text: str, arts: list[dict], cfg, log) -> tuple[str, dict, list[dict]]:
    """Тастыкталбаган фактылар калбаганча оңдойт. → (текст, акыркы отчет, тарых)."""
    hist = []
    rep = sources.verify(g, text, arts, log)
    hist.append({k: rep.get(k) for k in ("n", "n_ok", "source")})
    for rnd in range(FACT_ROUNDS):
        log(f"   🔎 Фактылар: {rep['n_ok']}/{rep['n']} булак менен тастыкталды" +
            (f"; тастыкталбаган {len(rep['unsupported'])}: " +
             "; ".join(c['claim'][:60] for c in rep['unsupported'][:4]) if rep["unsupported"] else " ✓"))
        if rep["source"] != "gemini" or not rep["unsupported"]:
            break
        new = clean(sources.fix(g, text, rep, arts))
        if word_count(new) < 0.75 * word_count(text) or duplicate_sentences(new):
            log("   ⚠ Факты оңдоосу жарамсыз жооп берди — кайра аракет")
            continue
        if word_count(new) < cfg.words_min - 60:
            new = adjust_length(g, new, cfg.words_min, cfg.words_max, log)
        text = new
        rep = sources.verify(g, text, arts, log)
        hist.append({k: rep.get(k) for k in ("n", "n_ok", "source")})
    return text, rep, hist


def run(ctx: Context) -> dict[str, Any]:
    from .stages.s1_script import choose_style, previous_scripts, similarity

    g = gemini_of(ctx)
    cfg, niche, topic = ctx.cfg, ctx.cfg.niche_data, ctx.state.topic
    log = ctx.log

    # 1. Булактар (кэш: s1 кайра иштесе Wikipedia кайра суралбайт)
    src_file = ctx.path("script", "sources.json")
    if src_file.exists():
        arts = json.loads(src_file.read_text(encoding="utf-8"))["articles"]
        log(f"   📚 Булактар кэштен: {len(arts)}")
    else:
        arts = sources.pick_articles(g, sources.client(ctx), topic, log)
        if not arts:
            raise StageError("Wikipedia'дан булак табылган жок — фактысыз документалдык видео жасалбайт "
                             "(теманы англисче так жазыңыз)")
        src_file.write_text(sources.dump({"topic": topic, "articles": arts}), encoding="utf-8")

    prev = previous_scripts(ctx)
    log(f"   Мурунку сценарийлер (салыштыруу үчүн): {len(prev)}")
    styles: dict[str, str] = niche.get("narrative_styles") or {"default": ""}
    rules = "\n".join(f"- {r}" for r in niche.get("script_rules", []))
    avoid = "\n".join(f"- \"{p['title']}\": {p['hook']}…" for p in prev[:8]) or "- (none yet)"

    tried: list[str] = []
    sim: dict = {}
    for round_ in range(2):
        pool = {k: v for k, v in styles.items() if k not in tried} or styles
        style = choose_style(pool, ctx.registry, ctx.video_id)
        tried.append(style)
        hook = choose_hook(ctx.registry, ctx.video_id)
        log(f"   Баяндоо стили: {style}; hook түрү: {hook}")
        prompt = SCRIPT_PROMPT.format(role=niche.get("script_role", "").strip(), topic=topic, style=styles[style],
                                      rules=rules, wmin=cfg.words_min, wmax=cfg.words_max,
                                      hook=HOOK_TYPES_EN[hook], previous=avoid,
                                      sources=sources.sources_block(arts))
        draft = g.text(prompt, purpose="script_draft", temperature=0.85)
        ctx.path("script", f"draft_{round_ + 1}.txt").write_text(draft, encoding="utf-8")
        title, card, text = split_draft(draft)
        if word_count(text) < 0.4 * cfg.words_min:
            raise StageError(f"Gemini өтө кыска текст берди ({word_count(text)} сөз)")
        text = adjust_length(g, text, cfg.words_min, cfg.words_max, log)
        text = fix_duplicates(g, text)
        text = adjust_length(g, text, cfg.words_min, cfg.words_max, log)
        sim = similarity(g, text, prev, log)
        log(f"   Окшоштук: 5-грамма {sim['max_jaccard']}, embedding {sim['max_cosine']}")
        if not sim["too_similar"]:
            break
        log(f"   ⚠ {sim['closest']} менен өтө окшош — башка стилде кайра жазылат")
    else:
        raise StageError(f"Сценарий мурунку видеого ({sim['closest']}) өтө окшош бойдон калды")

    # 2. Hook + retention (англисче катаал көрүүчү)
    fixed, ret = retention.improve(g, text, title, hook, log, lang="en")
    if fixed != text:
        fixed = adjust_length(g, clean(fixed), cfg.words_min, cfg.words_max, log)
        if not duplicate_sentences(fixed):
            text = fixed
    ctx.path("script", "retention.json").write_text(retention.dump(ret), encoding="utf-8")

    # 3. Фактылар — акыркы текст боюнча (hook оңдоосу да текшерилет)
    text, frep, fhist = facts_pass(g, text, arts, cfg, log)
    ctx.path("script", "facts.json").write_text(sources.dump(
        {"report": frep, "history": fhist, "sources": [{"title": a["title"], "url": a["url"]} for a in arts]}),
        encoding="utf-8")
    if frep["source"] != "gemini":
        raise StageError("Фактыларды текшерүү аткарылган жок (Gemini жооп бербеди) — видео улантылбайт")
    if frep["unsupported"]:
        raise StageError(f"{len(frep['unsupported'])} факты булак менен тастыкталган жок: " +
                         "; ".join(c["claim"][:60] for c in frep["unsupported"][:3]))
    if duplicate_sentences(text):
        raise StageError(f"Кайталанган сүйлөмдөр калды: {duplicate_sentences(text)[:2]}")

    script = ctx.path("script", "script.txt")
    script.write_text(text + "\n", encoding="utf-8")
    changes = f"{frep['n_ok']}/{frep['n']} факты Wikipedia булагы менен тастыкталды; айлампалар: {len(fhist)}"
    ctx.path("script", "fact_check.txt").write_text(changes + "\n", encoding="utf-8")
    first = " ".join(re.split(r"(?<=[.!?…])\s+", text.strip())[:2])
    meta = {"title": title, "style": style, "words": word_count(text), "hook_type": hook, "language": "en",
            "hook": first[:240], "hook_card": card or " ".join(first.split()[:5]),
            "hook_score": ret["review"].get("hook_score"), "hook_promise": ret["review"].get("promise", ""),
            "retention_strategy": ret["review"].get("retention_strategy", ""), "retention_ok": ret["ok"],
            "similarity": sim, "fact_check_changes": len(fhist) - 1, "facts": {"n": frep["n"], "ok": frep["n_ok"]},
            "sources": [{"title": a["title"], "url": a["url"]} for a in arts]}
    meta_file = ctx.path("script", "meta.json")
    meta_file.write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    log(f"   ✓ «{title}» — {meta['words']} сөз, стиль: {style}, фактылар {frep['n_ok']}/{frep['n']}")

    entry = ctx.registry.setdefault("videos", {}).setdefault(ctx.video_id, {})
    entry.update({"title": title, "style": style, "script": True, "hook_type": hook, "format": "doc",
                  "sources": [a["title"] for a in arts]})
    if ctx.store:
        ctx.store.publish("Scripts", script, f"{ctx.video_id}.txt")
    return {"script_path": str(script), "meta_file": str(meta_file)}
