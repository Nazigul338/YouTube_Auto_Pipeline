"""CINEMATIC PSYCHOLOGICAL STORYTELLING (2026-11-21) — канал форматы: ар видео = бир каармандын кыска кино-окуясы.

Ниша `psych_story` (`format: story`) болгондо иштейт; эски `motivation` видеолору (Video_001 ж.б.) өзгөрбөйт.

  character_profile()  — Character profile generator: каармандын туруктуу профили (жашы, чачы, кийими, мүнөзү,
                         көйгөйү, мамилелери) + англисче визуалдык дескриптор (visual reference) — мурунку
                         каармандардан башка (аты/кесиби/жашоосу кайталанбайт).
  outline()            — Story generator: 7 актылуу драматургия (HOOK … FINAL MESSAGE), бурулуш, өзгөрүү, сабак,
                         психологиялык негиз; мурунку сюжеттерге окшош болсо кайра жазылат.
  script_prompt()      — сценарий (орусча, үчүнчү жак, азыркы чак, табигый кыска диалогдор).
  map_acts()           — даяр тексттеги актылардын чеги (сөз индекси) → убакыт (s4 timings).
  check_*()            — QA: түзүлүш, документалдык деп көрсөтүү жок, диагноз жок, сюжет оригиналдуу.
Scene breakdown / cinematic visual prompt — s2 (`SCENE_EXTRA`), continuity — `pipeline/continuity.py`.
"""

from __future__ import annotations

import json
import re

from .textutil import jaccard, word_count

ACTS = (  # (ачкыч, аталышы, башталышы сек, аягы сек) — багыт катары (окуянын табигый өнүгүшүнө жараша)
    ("hook", "HOOK", 0, 20),
    ("introduction", "INTRODUCTION", 20, 90),
    ("conflict", "CONFLICT", 90, 210),
    ("development", "DEVELOPMENT", 210, 300),
    ("turning_point", "TURNING POINT", 300, 375),
    ("transformation", "TRANSFORMATION", 375, 440),
    ("final_message", "FINAL MESSAGE", 440, 480),
)
ACT_KEYS = [a[0] for a in ACTS]
TOTAL_SEC = 480
PLOT_SIMILAR = 0.22          # логлайн+актылар 3-грамма jaccard — андан жогору болсо сюжет окшош
DOCUMENTARY = ("реальная история", "реальной истории", "история основана на реальных", "это произошло на самом деле",
               "это случилось на самом деле", "основано на реальных событиях", "правдивая история")
DIAGNOSIS = ("диагноз", "тревожное расстройство", "психическое расстройство", "психическое заболевание",
             "генерализованн", "окр ", "обсессивно-компульсивн", "депрессивное расстройство", "клиническ")

CHARACTER_PROMPT = """You create the protagonist of an ORIGINAL short cinematic psychological story (Russian-language
YouTube channel). Topic of the episode: «{topic}»
Requirement for the hero: {hero_hint}

Our PREVIOUS heroes (yours must be a clearly different person: other name, age, job, life, city type):
{previous}

The hero will be shown with real stock footage, so the look must be COMMON and easy to find on stock video sites
(ordinary clothes, natural hair colour), and must stay the SAME in every scene.
Return JSON only:
{{"name": "<Russian first name>", "age": <25-60>, "gender": "woman"|"man",
 "look": {{"hair": "<english, e.g. short dark hair>", "build": "<english>", "clothes": "<english: 1-2 main items with
   colours worn through the story>", "detail": "<english: one recognisable detail, e.g. glasses, wristwatch>"}},
 "descriptor": "<english 6-10 words for stock search, e.g. 'woman 30s short dark hair grey sweater'>",
 "occupation": "<Russian>", "home": "<Russian: where and how they live>", "personality": "<Russian, 1 sentence>",
 "core_problem": "<Russian: the inner psychological problem of THIS episode>",
 "inner_belief": "<Russian: the hidden belief that drives the problem>",
 "relationships": [{{"name": "<Russian>", "role": "<Russian: who this is to the hero>"}}],
 "signature_objects": ["<english: 2-3 objects that recur in the story, e.g. phone, kettle, notebook>"]}}"""

OUTLINE_PROMPT = """You are a screenwriter of short cinematic psychological films (8 minutes, narrated in Russian).
Topic: «{topic}»
Hero: {hero}

Write an ORIGINAL story. Structure (timings are a guide, the story may breathe):
{acts}

Rules: one concrete life situation with real stakes; logical actions; natural, restrained emotions (no melodrama,
no tragedy for shock); other people with their own motives; an unexpected but believable turning point; the hero
makes a decision and changes; the psychological insight is grounded in well-established psychology (name the concept
honestly, e.g. "intolerance of uncertainty", "need for control", "safety behaviours" — no invented studies or numbers);
no diagnosis, no therapy promises; the story is fiction and must not pretend to be a documentary.

Our PREVIOUS stories (do NOT repeat their plot, situation, twist or lesson — not even with other names):
{previous}
{feedback}
Return JSON only:
{{"logline": "<Russian, 1-2 sentences>", "acts": [{{"act": "<one of {keys}>", "summary": "<Russian 1-3 sentences>",
  "location": "<english, filmable place>", "key_moment": "<english: the visual moment of this act>",
  "emotion": "<english>"}} … 7 items in order],
 "turning_point": "<Russian>", "transformation": "<Russian>", "lesson": "<Russian: the takeaway for the viewer>",
 "psychology": {{"concept": "<english/russian name of the established concept>", "basis": "<Russian: how it is
   understood in psychology, carefully>"}},
 "viewer_questions": ["<Russian: questions the viewer will want answered, e.g. what happened to her?>"]}}"""

SCRIPT_PROMPT = """{role}

ТЕМА ЭПИЗОДА: {topic}

ФОРМАТ: кинематографичная психологическая история (короткометражный фильм, ~8 минут озвучки). Зритель не слушает
лекцию — он ПРОЖИВАЕТ историю героя. Рассказ от третьего лица, в настоящем времени, как закадровый голос в кино:
конкретные действия, детали, звуки, свет, паузы. Короткие естественные диалоги: каждая реплика ТОЛЬКО в кавычках-ёлочках
«…» (иначе зритель не поймёт, что говорит герой); не больше 1–3 реплик подряд.

ГЕРОЙ (не меняй его внешность и факты): {hero}

СЮЖЕТ (следуй ему, раскрывая каждую часть живыми сценами):
{outline}

СТРУКТУРА И ОБЪЁМ ЧАСТЕЙ (≈135 слов в минуту; держи пропорции — поворот ПОСЛЕ середины):
{acts}

ПРАВИЛА:
{rules}
- Объём: строго {words_min}–{words_max} слов.
- Только текст для озвучки: без заголовков, ремарок в скобках, меток актов, эмодзи и списков.
- HOOK (первые 20 секунд): сразу показывай проблему или загадочный момент; первое предложение — не больше 14 слов;
  без приветствий. В первые 5–10 секунд у зрителя должен возникнуть вопрос: что с этим человеком? чем это кончится?
  Не обещай того, чего нет в истории.
- Психологическую мысль вплетай в историю (через мысли, поступки и вывод героя); поясняй осторожно
  («часто», «у многих»), без диагнозов и медицинских советов, без выдуманных исследований и цифр.
- История вымышлена: не называй её реальной/документальной.
- Без мотивационных штампов. В финале — сильный, тёплый, честный вывод для зрителя.
- Тип первого предложения: {hook_type}.

НАШИ ПРЕДЫДУЩИЕ ИСТОРИИ (не повторяй их сюжет, ходы и фразы): {previous}

ФОРМАТ ОТВЕТА:
НАЗВАНИЕ: <честное, интригующее название, до 70 символов>
КАРТОЧКА: <2–5 слов для экрана в первые секунды>

<полный текст для озвучки>"""

ACT_MAP_PROMPT = """Below is a narrated short story (Russian). Split it into these acts in order: {keys}.
For each act return the FIRST 6 words of the sentence where it begins, copied EXACTLY from the text.
Return JSON only: [{{"act": "<key>", "starts": "<first 6 words>"}}]

TEXT:
{text}"""


# ---------------------------------------------------------------- генераторлор

def previous_stories(registry: dict, video_id: str) -> list[dict]:
    return [dict(v["story"], id=k) for k, v in sorted(registry.get("videos", {}).items())
            if k != video_id and isinstance(v.get("story"), dict)]


def _norm_profile(r: dict) -> dict:
    look = r.get("look") if isinstance(r.get("look"), dict) else {}
    p = {"name": str(r.get("name") or "Герой")[:30], "age": int(r.get("age") or 35) if str(r.get("age") or "").isdigit()
         or isinstance(r.get("age"), int) else 35,
         "gender": r.get("gender") if r.get("gender") in ("woman", "man") else "woman",
         "look": {k: str(look.get(k, ""))[:80] for k in ("hair", "build", "clothes", "detail")},
         "descriptor": str(r.get("descriptor") or "")[:90]}
    for k in ("occupation", "home", "personality", "core_problem", "inner_belief"):
        p[k] = str(r.get(k) or "")[:300]
    p["relationships"] = [{"name": str(x.get("name", ""))[:30], "role": str(x.get("role", ""))[:80]}
                          for x in (r.get("relationships") or []) if isinstance(x, dict)][:4]
    p["signature_objects"] = [str(x)[:40] for x in (r.get("signature_objects") or [])][:3]
    if not p["descriptor"]:
        p["descriptor"] = f"{p['gender']} {p['age'] // 10 * 10}s {p['look']['hair']} {p['look']['clothes']}".strip()
    return p


def character_profile(g, topic: str, prev: list[dict], hero_hint: str = "") -> dict:
    prev_txt = "\n".join(f"- {s.get('id')}: {s.get('name')}, {s.get('age')}, {s.get('occupation')} — {s.get('logline', '')[:120]}"
                         for s in prev[-10:]) or "- (none yet)"
    taken = {(s.get("name") or "").lower() for s in prev}
    for _ in range(3):
        r = g.json(CHARACTER_PROMPT.format(topic=topic, previous=prev_txt, hero_hint=hero_hint or "-"),
                   purpose="story_character", temperature=0.9)
        if isinstance(r, dict) and r.get("name") and r["name"].lower() not in taken:
            return _norm_profile(r)
    if isinstance(r, dict) and r.get("name"):
        return _norm_profile(r)
    raise ValueError("Gemini каармандын профилин берген жок")


def hero_text(p: dict) -> str:
    rel = "; ".join(f"{x['name']} — {x['role']}" for x in p.get("relationships", []))
    return (f"{p['name']}, {p['age']} лет ({p['gender']}), {p['occupation']}. Внешность: {p['look']}. "
            f"Живёт: {p['home']}. Характер: {p['personality']}. Проблема: {p['core_problem']}. "
            f"Скрытое убеждение: {p['inner_belief']}. Окружение: {rel or '-'}. Предметы: {', '.join(p['signature_objects'])}")


WPS = 2.25                  # ~135 сөз/мүн


def acts_text(words: int = 1150) -> str:
    return "\n".join(f"{k + 1}. {name} — {a // 60}:{a % 60:02d}–{b // 60}:{b % 60:02d}, ≈{round(words * (b - a) / TOTAL_SEC, -1):.0f} слов"
                     for k, (_, name, a, b) in enumerate(ACTS))


def word_times(acts: list[dict], n_words: int) -> list[dict]:
    """Үн жок кезде (s1) актылардын болжолдуу убактысы: сөз индекси → сек (түз пропорция 8 мүн)."""
    k = TOTAL_SEC / max(1, n_words)
    return [dict(a, start=round(a["w0"] * k, 1), end=round(a["w1"] * k, 1)) for a in acts]


STRUCTURE_FIX = ("\nВНИМАНИЕ: предыдущий вариант нарушил структуру ({why}). Соблюдай объём каждой части: HOOK короткий, "
                 "поворот — во второй половине, финал короткий и без длинных советов.\n")
EXPAND_HINT = ("Расширь текст до ~{target} слов ВНУТРИ истории: добавь живые детали, действия и короткие реплики в сцены "
               "конфликта и развития (середина). НЕ добавляй советов, упражнений и рассуждений в конец; финал не удлиняй.")
SHRINK_HINT = ("Сократи текст до ~{target} слов: убери повторы и рассуждения, особенно в финале; сохрани все сцены, "
               "поворот и реплики в «ёлочках».")


PLOT_COSINE = 0.90          # embedding окшоштугу (сценарийлер 0.79 болгон — run #44745978945)


def plot_text(o: dict) -> str:
    return (o.get("logline", "") + " " + " ".join(a.get("summary", "") for a in o.get("acts", [])) +
            " " + o.get("turning_point", ""))


def plot_similarity(o: dict, prev: list[dict], g=None) -> tuple[float, str | None, float | None]:
    """→ (3-грамма jaccard, эң окшош видео, embedding cosine|None)."""
    text = plot_text(o)
    best, who = 0.0, None
    for s in prev:
        other = s.get("plot_text") or s.get("logline") or ""
        j = jaccard(text, other, n=3) if other else 0.0
        if j > best:
            best, who = j, s.get("id")
    cos = None
    others = [s for s in prev if s.get("plot_text") or s.get("logline")]
    if g is not None and others and hasattr(g, "embed"):
        try:
            from .textutil import cosine

            vec = g.embed([text] + [s.get("plot_text") or s.get("logline") for s in others])
            cs = [cosine(vec[0], v) for v in vec[1:]]
            k = max(range(len(cs)), key=cs.__getitem__)
            cos = round(cs[k], 4)
            if cos >= PLOT_COSINE:
                who = others[k].get("id")
        except Exception:
            cos = None
    return round(best, 3), who, cos


def _norm_outline(r: dict) -> dict | None:
    if not isinstance(r, dict) or not isinstance(r.get("acts"), list):
        return None
    acts = {}
    for a in r["acts"]:
        if isinstance(a, dict) and a.get("act") in ACT_KEYS and a["act"] not in acts:
            acts[a["act"]] = {k: str(a.get(k, ""))[:400] for k in ("summary", "location", "key_moment", "emotion")}
    if len(acts) < 6:
        return None
    psy = r.get("psychology") if isinstance(r.get("psychology"), dict) else {}
    return {"logline": str(r.get("logline", ""))[:400], "acts": [dict(acts.get(k, {}), act=k) for k in ACT_KEYS],
            "turning_point": str(r.get("turning_point", ""))[:400], "transformation": str(r.get("transformation", ""))[:400],
            "lesson": str(r.get("lesson", ""))[:300],
            "psychology": {"concept": str(psy.get("concept", ""))[:120], "basis": str(psy.get("basis", ""))[:500]},
            "viewer_questions": [str(x)[:120] for x in (r.get("viewer_questions") or [])][:4]}


def outline(g, topic: str, hero: dict, prev: list[dict], log) -> dict:
    prev_txt = "\n".join(f"- {s.get('id')}: {s.get('logline', '')[:200]} | поворот: {s.get('turning_point', '')[:120]} "
                         f"| урок: {s.get('lesson', '')[:100]}" for s in prev[-10:]) or "- (none yet)"
    feedback, best = "", None
    for attempt in range(3):
        o = _norm_outline(g.json(OUTLINE_PROMPT.format(topic=topic, hero=hero_text(hero), acts=acts_text(),
                                                       previous=prev_txt, keys=", ".join(ACT_KEYS), feedback=feedback),
                                 purpose="story_outline", temperature=0.9))
        if not o:
            continue
        sim, who, cos = plot_similarity(o, prev, g)
        o["plot_similarity"], o["plot_cosine"], o["closest"] = sim, cos, who
        best = o
        if sim < PLOT_SIMILAR and (cos is None or cos < PLOT_COSINE):
            return o
        log(f"   ⚠ Сюжет {who} менен окшош (3-грамма {sim}, embedding {cos}) — кайра жазылат")
        feedback = f"\nYOUR PREVIOUS ATTEMPT WAS TOO SIMILAR TO {who}: change the situation, the twist and the lesson.\n"
    if best:
        return best
    raise ValueError("Gemini сюжет түзгөн жок")


def outline_text(o: dict) -> str:
    lines = [f"Логлайн: {o['logline']}"]
    lines += [f"- {a['act'].upper()}: {a.get('summary', '')} (место: {a.get('location', '')})" for a in o["acts"]]
    lines += [f"Поворот: {o['turning_point']}", f"Изменение: {o['transformation']}", f"Урок: {o['lesson']}",
              f"Психология: {o['psychology']['concept']} — {o['psychology']['basis']}"]
    return "\n".join(lines)


def script_prompt(topic: str, niche: dict, hero: dict, o: dict, prev: list[dict], cfg, hook_type: str) -> str:
    rules = "\n".join(f"- {r}" for r in niche.get("script_rules", []))
    prev_txt = "; ".join(f"«{s.get('title', '')}»: {s.get('logline', '')[:120]}" for s in prev[-6:]) or "(пока нет)"
    return SCRIPT_PROMPT.format(role=niche.get("script_role", "").strip(), topic=topic, hero=hero_text(hero),
                                outline=outline_text(o), acts=acts_text((cfg.words_min + cfg.words_max) // 2), rules=rules, words_min=cfg.words_min,
                                words_max=cfg.words_max, hook_type=hook_type, previous=prev_txt)


# ---------------------------------------------------------------- актылар

def _find(words: list[str], starts: str, after: int) -> int | None:
    key = [w for w in re.findall(r"\w+", starts.lower().replace("ё", "е"))][:6]
    if len(key) < 3:
        return None
    low = [re.sub(r"[^\w]", "", w.lower().replace("ё", "е")) for w in words]
    for i in range(after, len(low) - len(key) + 1):
        if low[i:i + len(key)] == key:
            return i
    for i in range(after, len(low) - 3):              # жумшак: биринчи 3 сөз
        if low[i:i + 3] == key[:3]:
            return i
    return None


def map_acts(g, text: str) -> list[dict]:
    """Актылардын башталыш сөз индекси. Gemini жоопсуз/туура эмес болсо — ACTS үлүшү боюнча (proportional)."""
    words = text.split()
    n = len(words)
    starts: dict[str, int] = {}
    method = "gemini"
    try:
        r = g.json(ACT_MAP_PROMPT.format(keys=", ".join(ACT_KEYS), text=text), purpose="story_acts", temperature=0.1)
        last = 0
        for a in r if isinstance(r, list) else []:
            if isinstance(a, dict) and a.get("act") in ACT_KEYS and a["act"] not in starts:
                i = _find(words, str(a.get("starts", "")), last)
                if i is not None and (i > last or not starts):
                    starts[a["act"]] = i
                    last = i
    except Exception:
        pass
    if 5 <= len(starts) < len(ACT_KEYS) and starts.get("hook", 0) == 0:
        # Gemini бир-эки актыны белгилебей койду (Video_005: final_message жок → QA «актылар толук эмес»):
        # жетишпегени коңшуларынын ортосуна, үлүшү боюнча + сүйлөмдүн башына жылдырылып толукталат
        for j, (k, _, a, _) in enumerate(ACTS):
            if k in starts:
                continue
            lo = max([starts[x] for x in ACT_KEYS[:j] if x in starts], default=0)
            hi = min([starts[x] for x in ACT_KEYS[j + 1:] if x in starts], default=n)
            want = min(max(int(n * a / TOTAL_SEC), lo + 1), hi - 1)
            cands = [i for i in range(lo + 1, hi) if i > 0 and words[i - 1][-1:] in ".!?…"]
            pos = min(cands, key=lambda i: abs(i - want)) if cands else want
            if lo < pos < hi:
                starts[k] = pos
        if len(starts) == len(ACT_KEYS):
            method = "gemini+fill"
    if len(starts) < len(ACT_KEYS) or starts.get("hook", 0) != 0:
        method = "proportional"
        starts = {k: int(n * a / TOTAL_SEC) for k, _, a, _ in ACTS}
    starts["hook"] = 0
    keys = [k for k in ACT_KEYS if k in starts]
    out = []
    for j, k in enumerate(keys):
        e = starts[keys[j + 1]] if j + 1 < len(keys) else n
        out.append({"act": k, "w0": starts[k], "w1": e, "method": method})
    return out


def act_times(acts: list[dict], words: list[dict]) -> list[dict]:
    """Сөз индексинен даяр үндөгү убакыт (timings.json words)."""
    out = []
    for a in acts:
        s = words[min(a["w0"], len(words) - 1)]["s"] if words else 0.0
        e = words[min(max(a["w1"] - 1, 0), len(words) - 1)]["e"] if words else 0.0
        out.append(dict(a, start=round(float(s), 1), end=round(float(e), 1)))
    return out


def act_of_word(acts: list[dict], w: int) -> str:
    return next((a["act"] for a in acts if a["w0"] <= w < a["w1"]), acts[-1]["act"] if acts else "hook")


# ---------------------------------------------------------------- QA

def check_structure(times: list[dict], duration: float) -> list[str]:
    """Түзүлүш: 7 акт ирети менен, hook ≤30 сек, бурулуш 50–85%, ар акт ≥3% (окуя «тиштелип» калбасын)."""
    p = []
    keys = [a["act"] for a in times]
    if keys != [k for k in ACT_KEYS if k in keys] or len(keys) < 7:
        p.append(f"актылар толук эмес/ирети бузук: {keys}")
    by = {a["act"]: a for a in times}
    if "hook" in by and by["hook"]["end"] > 30:
        p.append(f"hook узун ({by['hook']['end']:.0f} сек > 30)")
    if "turning_point" in by and duration:
        r = by["turning_point"]["start"] / duration
        if not 0.45 <= r <= 0.85:
            p.append(f"бурулуш {r:.0%} убакта (керек 45–85%)")
    for a in times:
        if duration and (a["end"] - a["start"]) < 0.03 * duration:
            p.append(f"«{a['act']}» өтө кыска ({a['end'] - a['start']:.0f} сек)")
    return p


def check_text(text: str) -> list[str]:
    low = " " + text.lower().replace("ё", "е") + " "
    p = [f"документалдык деп көрсөтүлгөн: «{d}»" for d in DOCUMENTARY if d in low]
    p += [f"диагноз/медициналык сөз: «{d.strip()}»" for d in DIAGNOSIS if d in low]
    return p


def registry_entry(hero: dict, o: dict, title: str) -> dict:
    """Реестрге (кийинки видеолор салыштырат): ким, эмне болду, кандай сабак."""
    return {"name": hero["name"], "age": hero["age"], "gender": hero["gender"], "occupation": hero["occupation"],
            "descriptor": hero["descriptor"], "logline": o["logline"], "turning_point": o["turning_point"],
            "lesson": o["lesson"], "concept": o["psychology"]["concept"], "title": title,
            "plot_text": plot_text(o)}


def dump(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=1)


def is_story(cfg) -> bool:
    return (getattr(cfg, "niche_data", None) or {}).get("format") == "story"


def words_of(text: str) -> int:
    return word_count(text)


# --- Hook'тун узундугу ЧЫНЫГЫ үнгө жараша (run #44921404755: s1 болжолу 8 мүн/түз пропорция → hook «≤30»,
#     даяр үндө 38 сек; биринчи сүйлөм 10 сөз = 5.02 сек, кино-диктор жай окуйт) ---
REAL_WPS = 2.1              # кино-диктордун чыныгы ылдамдыгы (Video_005: ~1150 сөз / 545 сек)
HOOK_MAX_EST = 24.0         # s1 болжолу (QA чеги 30 сек — запас)
FIRST_SENT_WORDS = 9        # биринчи сүйлөм ≤9 сөз → ≤~4.5 сек

HOOK_FIX_PROMPT = """Это HOOK (самое начало) короткого фильма-рассказа на русском. Он слишком длинный для первых секунд видео.
Перепиши ТОЛЬКО этот фрагмент: не более {max_words} слов; первое предложение не длиннее {first} слов и сразу вызывает
вопрос «что с этим человеком происходит / чем это закончится?». Сохрани то же событие, героя, детали и смысл; без
приветствий, без советов, без новых фактов. Реплики — только в «ёлочках». Верни только новый текст фрагмента.

ФРАГМЕНТ:
{hook}"""


def first_sentence_words(text: str) -> int:
    import re

    s = re.split(r"(?<=[.!?…])\s+", text.strip(), maxsplit=1)[0] if text.strip() else ""
    return len(s.split())


def hook_problems(text: str, acts: list[dict]) -> list[str]:
    p = []
    hook = next((a for a in acts if a["act"] == "hook"), None)
    if hook and (hook["w1"] - hook["w0"]) / REAL_WPS > HOOK_MAX_EST:
        p.append(f"hook ~{(hook['w1'] - hook['w0']) / REAL_WPS:.0f} сек (> {HOOK_MAX_EST:.0f})")
    if first_sentence_words(text) > FIRST_SENT_WORDS:
        p.append(f"биринчи сүйлөм {first_sentence_words(text)} сөз (> {FIRST_SENT_WORDS})")
    return p


def tighten_hook(g, text: str, acts: list[dict], log, tries: int = 2) -> tuple[str, list[dict]]:
    """Hook акты/биринчи сүйлөм узун болсо — ОШОЛ фрагмент гана кыскартылат (калган окуя тийилбейт)."""
    for _ in range(tries):
        why = hook_problems(text, acts)
        if not why:
            break
        hook = next((a for a in acts if a["act"] == "hook"), None)
        if not hook or hook["w1"] <= 0:
            break
        words = text.split()
        try:
            new = g.text(HOOK_FIX_PROMPT.format(max_words=int(HOOK_MAX_EST * REAL_WPS) - 4, first=FIRST_SENT_WORDS,
                                                hook=" ".join(words[:hook["w1"]])),
                         purpose="story_hook_fix", temperature=0.7).strip().strip('"')
        except Exception as e:
            log(f"   ⚠ Hook кыскарган жок ({type(e).__name__})")
            break
        if not new or len(new.split()) >= hook["w1"] and first_sentence_words(new) >= first_sentence_words(text):
            break
        cand = new + " " + " ".join(words[hook["w1"]:])
        cand_acts = map_acts(g, cand)
        if len(hook_problems(cand, cand_acts)) <= len(why):
            log(f"   ✂ Hook кыскартылды ({'; '.join(why)}): {hook['w1']} → {len(new.split())} сөз")
            text, acts = cand, cand_acts
    return text, acts
