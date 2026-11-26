"""HOOK + КӨРҮҮЧҮНҮ КАРМОО (audience retention) — ар видеонун сценарийи MP4'ке чейин текшерилет.

Эреже (CLAUDE.md «🎯 VIRAL HOOK, ОБЛОЖКА, RETENTION»): көрүүчүнү алдап кликке азгыруу эмес, чыныгы кызыгуу
менен видеону көрүүгө жана улантууга ынандыруу.

s1 (сценарий жазылгандан кийин):
  local_checks(text)  — өлчөнөт: биринчи сүйлөмдүн/фразанын узундугу, саламдашуу, ортодогу «кайра жандандыруучу»
                        суроолор, кайталанган абзац башталыштары, жыйынтык абзац.
  review(g, …)        — Gemini «катаал көрүүчү-редактор»: hook (1–10), башталыш созулдубу, убада, ал видеодо
                        чындап берилеби (цитата менен), жалган убадалар, кайталоолор, ортодо кызыгуу түшкөн жерлер,
                        жыйынтыктын күчү, ушул видеонун өз retention стратегиясы.
  problems(...)       — жетишсиз болсо себептер → improve() башталышты/аягын бир жолу кайра жаздырат жана кайра текшерет.
s9: hook_timing() — даяр үндө биринчи фраза качан бүтөт (≤3 сек), viewer_checklist() — 6 акыркы суроо.
"""

from __future__ import annotations

import json
import re

from .textutil import sentences, word_count

# 2026-11-26 колдонуучунун чечими: «Hook 20 секунд болсун» — 3 секунд эрежеси алынды (биринчи сүйлөм ≤8 сөз/≤3 сек жок).
# Hook — видеонун алгачкы ~20 секунду (≈40–50 сөз). 2026-11-21 эрежеси калат: биринчи сүйлөм ≤16 сөз, биринчи ой ≤5 сек.
HOOK_SEC = 20.0               # hook бөлүгүнүн узактыгы (максаттуу)
HOOK_MAX_SEC = 25.0           # hook бөлүгү ушундан узун болсо — көйгөй (problem бөлүгү кечигет)
HOOK_FIRST_WORDS = 16         # биринчи сүйлөм (2026-11-21 viral hook эрежеси: ≤14–16 сөз)
HOOK_PHRASE_SEC = 5.0         # биринчи фраза (үтүргө/чекитке чейин) даяр үндө ушул секунддун ичинде бүтөт
FIX_ROUNDS = 2               # Hook/финал кайра жазуу айлампалары (мурун 1)
HOOK_MIN_SCORE = 8            # Hook өзүнчө: «катаал көрүүчү» ≥8/10, болбосо кайра жазылат (≤2 жолу)
ENDING_MIN_SCORE = 6
GREETINGS = ("привет", "здравствуй", "добро пожаловать", "всем привет", "с вами", "дорогие зрители",
             "сегодня поговорим", "в этом видео", "сегодня мы", "давайте поговорим", "давайте разберёмся")

REVIEW_PROMPT = """Ты — самый требовательный зритель и редактор удержания (retention) психологического YouTube-канала.
Цель канала — НЕ заманить кликом, а честно заинтересовать и удержать до конца. Оцени сценарий строго.

Название: {title}
Тип hook'а: {hook_type}

Ответь ТОЛЬКО JSON:
{{"hook_score": <1-10: заставят ли первые ~20 секунд (hook) остаться? вопрос/неожиданная мысль/сильная эмоция про
  ЛИЧНУЮ боль, страх, желание или внутреннее противоречие зрителя; даёт ли чувство «это видео про меня» и желание
  узнать, что будет дальше; по теме, без обмана и сенсаций. 8+ только если hook действительно цепляет с первой фразы
  и держит все ~20 секунд>,
 "hook_reason": "<коротко почему>",
 "hook_on_topic": <true/false: hook прямо связан с главной темой>,
 "intro_drag": <true/false: начало затянуто (приветствия, долгое вступление, лишние объяснения до сути)>,
 "promise": "<что зритель узнает, если досмотрит — как это обещано в начале>",
 "promise_delivered": <true/false: это действительно объяснено в тексте>,
 "delivered_quote": "<ДОСЛОВНАЯ короткая цитата (5–15 слов) из текста, где обещание выполняется>",
 "false_promises": ["<обещания/интриги, на которые в тексте НЕТ ответа>"],
 "repetitions": ["<мысли, повторённые без новой пользы>"],
 "sag_points": ["<где (начало фразы) в середине интерес падает>"],
 "reengagement": ["<начала фраз: вопросы/повороты, которые возвращают внимание>"],
 "ending_score": <1-10: финал чётко собирает главный урок и оставляет сильное впечатление>,
 "ending_lesson": "<главный урок финала одним предложением>",
 "retention_strategy": "<стратегия удержания ИМЕННО этого видео: какие открытые вопросы, повороты и примеры
   держат внимание и где>"}}

СЦЕНАРИЙ:
{text}"""

FIX_PROMPT = """Ты — сценарист психологического YouTube-канала. Улучши ТОЛЬКО указанные части сценария,
всё остальное оставь слово в слово. Не добавляй фактов, статистики, цитат и имён. Не обещай того, чего нет в тексте.

Что исправить:
{fixes}

Правила hook'а (первые ~20 секунд, ≈40–50 слов — главное требование канала): первое предложение — не больше {max_words} слов
(пример формы, НЕ копировать: «В твоей жизни всё хорошо. Но почему внутри ты всё равно ждёшь беды?»), без приветствий и вступлений, сразу вопрос,
неожиданная мысль или сильная эмоция про личную боль/страх/желание/внутреннее противоречие зрителя, прямо по теме
«{title}». Второе-третье предложение честно показывает, что зритель поймёт, если досмотрит (и это есть в тексте).
Тип hook'а: {hook_type}. Не используй шаблон «Ты можешь годами доказывать…».
Финал: собери главный урок ясно и сильно, без мотивационных штампов.

Верни только полный текст.

ТЕКСТ:
{text}"""


# ----------------------------------------------------------- англисче канал (2026-11-24, Tech History документалдык)
GREETINGS_EN = ("hi ", "hello", "hey guys", "welcome", "in this video", "today we", "today i", "let's talk",
                "what's up", "before we begin", "don't forget to subscribe")

REVIEW_PROMPT_EN = """You are the most demanding viewer and audience-retention editor of an English-language technology
history documentary YouTube channel. The goal is NOT to bait clicks but to honestly hook and keep viewers to the end.
Rate the script strictly.

Title: {title}
Hook type: {hook_type}

Reply ONLY with JSON:
{{"hook_score": <1-10: will the first 3 seconds make a viewer stay? a surprising fact, paradox, high stake or open
  question about the story; makes the viewer need to know what happened next; short, on topic, no deception or
  sensationalism. 8+ only if the first 3 seconds truly grab>,
 "hook_reason": "<short why>",
 "hook_on_topic": <true/false: the hook is directly about the main story>,
 "intro_drag": <true/false: the opening drags (greetings, long intro, background before the point)>,
 "promise": "<what the viewer will learn by watching to the end — as promised in the opening>",
 "promise_delivered": <true/false: the script really delivers it>,
 "delivered_quote": "<VERBATIM short quote (5-15 words) from the script where the promise is delivered>",
 "false_promises": ["<promises/teasers that are NOT answered in the script>"],
 "repetitions": ["<ideas repeated without new value>"],
 "sag_points": ["<where (sentence start) interest drops in the middle>"],
 "reengagement": ["<sentence starts: questions/turns that bring attention back>"],
 "ending_score": <1-10: the ending clearly lands the lesson/legacy of the story and leaves a strong impression>,
 "ending_lesson": "<main takeaway of the ending in one sentence>",
 "retention_strategy": "<the retention strategy of THIS video: which open questions, turns and reveals keep
   attention and where>"}}

SCRIPT:
{text}"""

FIX_PROMPT_EN = """You are the scriptwriter of a technology history documentary channel. Improve ONLY the parts listed
below; keep everything else word for word. Do NOT add facts, numbers, dates, names or quotes that are not already in
the script. Do not promise anything the script does not deliver.

What to fix:
{fixes}

Hook rules (first 3 seconds — the channel's main requirement): the first sentence is at most {max_words} words, no
greetings or intro, straight into a surprising fact, paradox, high stake or open question from the story of
"{title}". Sentences 2-3 honestly tell the viewer what they will understand by the end (and it is in the script).
Hook type: {hook_type}.
Ending: land the story's lesson and legacy clearly and strongly, without clichés.

Return only the full text.

TEXT:
{text}"""

FIX_TEXT_EN = {
    "башталыш": "Rewrite the first 2-3 sentences (the hook): {why}.",
    "убада": "The opening promises something the script does not deliver: either deliver it in the body in one "
             "paragraph, or fix/remove the promise in the opening. {why}.",
    "жыйынтык": "Rewrite the last paragraph: {why}.",
}


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", s.lower().replace("ё", "е"))).strip()


def first_phrase(text: str) -> str:
    sent = (sentences(text) or [text])[0]
    return re.split(r"(?<=[,;:—–?!.…])\s+", sent.strip())[0]


def local_checks(text: str, lang: str = "ru") -> dict:
    """Детерминдүү өлчөөлөр (Gemini'сиз)."""
    sents = sentences(text)
    first = sents[0] if sents else ""
    paras = [p for p in re.split(r"\n\s*\n", text.strip()) if p.strip()]
    n = len(sents)
    mid = sents[int(n * 0.3):int(n * 0.7)] if n else []
    starts = [" ".join(_norm(p).split()[:3]) for p in paras]
    rep_starts = sorted({s for s in starts if s and starts.count(s) > 1})
    low = _norm(first)
    return {"first_sentence": first[:240], "first_words": word_count(first),
            "first_phrase_words": word_count(first_phrase(text)),
            "greeting": next((g for g in (GREETINGS_EN if lang == "en" else GREETINGS)
                              if low.startswith(_norm(g))), None),
            "mid_questions": sum(1 for s in mid if s.rstrip().endswith("?")),
            "repeated_paragraph_starts": rep_starts[:5],
            "ending_words": word_count(paras[-1]) if paras else 0, "paragraphs": len(paras)}


def quote_in_text(quote: str, text: str) -> bool:
    """Цитата текстте чындап барбы (жалган «убада аткарылды» жообун кармоо): ≥80% маанилүү сөздөрү катар табылат."""
    q = [w for w in _norm(quote).split() if len(w) >= 4]
    if len(q) < 2:
        return False
    t = _norm(text)
    if " ".join(_norm(quote).split()) in t:
        return True
    tw = set(t.split())
    return sum(w in tw for w in q) / len(q) >= 0.8


def review(g, text: str, title: str, hook_type: str, lang: str = "ru") -> dict:
    """Gemini баалоосу. Жооп келбесе/бузук болсо — {'source': 'none'} (local_checks гана иштейт)."""
    try:
        r = g.json((REVIEW_PROMPT_EN if lang == "en" else REVIEW_PROMPT).format(title=title, hook_type=hook_type, text=text),
                   purpose="retention_review", temperature=0.2)
    except Exception as e:
        return {"source": "none", "error": f"{type(e).__name__}: {str(e)[:120]}"}
    if not isinstance(r, dict) or not isinstance(r.get("hook_score"), (int, float)):
        return {"source": "none", "error": "жооп форматка туура келген жок"}
    out = {"source": "gemini"}
    for k in ("hook_score", "ending_score"):
        out[k] = max(1, min(10, int(r.get(k) or 0)))
    for k in ("hook_on_topic", "intro_drag", "promise_delivered"):
        out[k] = bool(r.get(k))
    for k in ("hook_reason", "promise", "delivered_quote", "ending_lesson", "retention_strategy"):
        out[k] = str(r.get(k) or "")[:600]
    for k in ("false_promises", "repetitions", "sag_points", "reengagement"):
        v = r.get(k) or []
        out[k] = [str(x)[:200] for x in (v if isinstance(v, list) else [v]) if str(x).strip()][:6]
    # Gemini «аткарылды» десе да — цитатасы текстте жок болсо, ишенбейбиз
    out["quote_found"] = quote_in_text(out["delivered_quote"], text)
    if out["promise_delivered"] and not out["quote_found"]:
        out["promise_delivered"] = False
        out["promise_note"] = "цитата текстте табылган жок"
    return out


def problems(local: dict, rev: dict) -> list[str]:
    """Жетишсиз жерлер (бош тизме — даяр)."""
    p = []
    if local["greeting"]:
        p.append(f"башталышы саламдашуу/шаблон: «{local['greeting']}»")
    if local["first_words"] > HOOK_FIRST_WORDS:
        p.append(f"биринчи сүйлөм узун ({local['first_words']} сөз > {HOOK_FIRST_WORDS}) — hook'тун биринчи ою созулуп кетет")
    if rev.get("source") == "gemini":
        if rev["hook_score"] < HOOK_MIN_SCORE:
            p.append(f"hook алсыз ({rev['hook_score']}/10: {rev['hook_reason'][:120]})")
        if not rev["hook_on_topic"]:
            p.append("hook теманын өзүнө байланышпайт")
        if rev["intro_drag"]:
            p.append("башталышы созулуп кеткен")
        if not rev["promise_delivered"]:
            p.append(f"убада видеодо берилбейт: «{rev['promise'][:120]}»")
        if rev["false_promises"]:
            p.append(f"жалган убада/интрига: {rev['false_promises'][:2]}")
        if rev["ending_score"] < ENDING_MIN_SCORE:
            p.append(f"жыйынтык алсыз ({rev['ending_score']}/10)")
    return p


FIX_TEXT = {
    "башталыш": "Перепиши первые 2–3 предложения (hook): {why}.",
    "убада": "Начало обещает то, чего нет в тексте: либо выполни обещание в основной части одним абзацем, "
             "либо убери/исправь обещание в начале. {why}.",
    "жыйынтык": "Перепиши последний абзац: {why}.",
}


def fix_instructions(probs: list[str], lang: str = "ru") -> str:
    out = []
    FIX = FIX_TEXT_EN if lang == "en" else FIX_TEXT
    for p in probs:
        if "жыйынтык" in p:
            out.append(FIX["жыйынтык"].format(why=p))
        elif "убада" in p:
            out.append(FIX["убада"].format(why=p))
        else:
            out.append(FIX["башталыш"].format(why=p))
    return "\n".join(f"- {x}" for x in dict.fromkeys(out))


def improve(g, text: str, title: str, hook_type: str, log, lang: str = "ru") -> tuple[str, dict]:
    """Текшерет; жетишсиз болсо бир жолу оңдотуп кайра текшерет. → (текст, retention отчету)."""
    loc, rev = local_checks(text, lang), review(g, text, title, hook_type, lang)
    probs = problems(loc, rev)
    rounds = [{"local": loc, "review": rev, "problems": probs}]
    log(f"   🎯 Hook/retention: hook {rev.get('hook_score', '-')}/10, финал {rev.get('ending_score', '-')}/10, "
        f"биринчи сүйлөм {loc['first_words']} сөз" + (f" — оңдоо керек: {'; '.join(probs)}" if probs else " ✓"))
    for _ in range(FIX_ROUNDS):
        if not probs:
            break
        new = g.text((FIX_PROMPT_EN if lang == "en" else FIX_PROMPT).format(fixes=fix_instructions(probs, lang), max_words=HOOK_FIRST_WORDS, title=title,
                                       hook_type=hook_type, text=text), purpose="retention_fix", temperature=0.6)
        new = new.strip()
        if word_count(new) >= 0.85 * word_count(text) and new != text.strip():
            loc2, rev2 = local_checks(new, lang), review(g, new, title, hook_type, lang)
            probs2 = problems(loc2, rev2)
            rounds.append({"local": loc2, "review": rev2, "problems": probs2})
            if len(probs2) <= len(probs):
                text, loc, rev, probs = new, loc2, rev2, probs2
                log(f"   🔁 Hook/финал кайра жазылды: hook {rev.get('hook_score', '-')}/10, "
                    f"финал {rev.get('ending_score', '-')}/10" + (f"; калды: {'; '.join(probs)}" if probs else " ✓"))
            else:
                log("   ⚠ Кайра жазылган вариант начарыраак — түп текст калды")
        else:
            log("   ⚠ Кайра жазуу жарамсыз жооп берди — түп текст калды")
    return text, {"local": loc, "review": rev, "problems": probs, "rounds": len(rounds), "history": rounds,
                  "ok": not probs}


# ---------------------------------------------------------------- s9: даяр үн боюнча

def hook_timing(words: list[dict], text: str) -> dict:
    """Биринчи фраза жана биринчи сүйлөм даяр үндө качан бүтөт (timings.json сөздөрү боюнча)."""
    n_phrase, n_sent = word_count(first_phrase(text)), word_count((sentences(text) or [text])[0])
    end = lambda n: round(float(words[min(n, len(words)) - 1]["e"]), 2) if words and n else None
    return {"phrase_words": n_phrase, "phrase_end_sec": end(n_phrase), "sentence_words": n_sent,
            "sentence_end_sec": end(n_sent), "speech_start_sec": round(float(words[0]["s"]), 2) if words else None}


VIEWER_QUESTIONS = (
    ("Обложка адамдын көңүлүн бурабы?", "thumb_attention"),
    ("Hook алгачкы секунддарда кызыктырабы?", "hook_attention"),
    ("Видеонун башталышы созулуп кеткен жокпу?", "intro_fast"),
    ("Көрүүчү эмне үчүн аягына чейин көрүшү керек?", "reason_to_stay"),
    ("Обложка менен видеонун мазмуну дал келеби?", "thumb_honest"),
    ("Мурунку видеолордон чыгармачылык жактан айырмаланабы?", "creative_diff"),
)


def viewer_checklist(ret: dict, timing: dict, thumb: dict, original_ok: bool | None) -> list[dict]:
    """6 акыркы суроо → [{question, ok, note}] (None — текшерүүгө маалымат жок)."""
    rev, loc = ret.get("review") or {}, ret.get("local") or {}
    g = rev.get("source") == "gemini"
    q = thumb.get("quality") or []
    out = {}
    seen = [x for x in q if x.get("vision")]
    out["thumb_attention"] = ((all(x["vision"].get("ok") for x in seen) if seen else None) if q else False,
                              "; ".join(f"«{x['text']}» контраст {x['contrast']}, {x['words']} сөз" +
                                        (f", көңүл {x['vision']['attention']}/10, тема {x['vision']['topic_match']}/10, "
                                         f"эмоция: {x['vision']['emotion']}" if x.get("vision") else ", көрүү баасы жок")
                                        for x in q) or "обложка жок")
    pe = timing.get("phrase_end_sec")
    hook_ok = (None if pe is None and not g else
               (pe is None or pe <= HOOK_PHRASE_SEC) and not loc.get("greeting") and
               (rev.get("hook_score", 0) >= HOOK_MIN_SCORE if g else True))
    out["hook_attention"] = (hook_ok, f"биринчи фраза {pe} сек ичинде; hook {rev.get('hook_score', '-')}/10 — "
                                      f"{rev.get('hook_reason', '')[:120]}")
    out["intro_fast"] = ((not rev.get("intro_drag")) and not loc.get("greeting") if g else not loc.get("greeting"),
                         f"биринчи сүйлөм {timing.get('sentence_end_sec')} сек ({loc.get('first_words')} сөз)")
    out["reason_to_stay"] = ((rev.get("promise_delivered") and not rev.get("false_promises")) if g else None,
                             f"убада: «{rev.get('promise', '-')[:140]}» → видеодо: «{rev.get('delivered_quote', '-')[:100]}»; "
                             f"стратегия: {rev.get('retention_strategy', '-')[:160]}")
    hon = [x for x in q if "support_found" in x]
    out["thumb_honest"] = (all(x["support_found"] for x in hon) if hon else None,
                           "; ".join(f"«{x['text']}» ← «{x.get('support', '')[:80]}»" for x in hon) or "-")
    out["creative_diff"] = (original_ok, "оригиналдуулук текшерүүлөрү (концепция, визуал, сценарий, hook түрү)")
    return [{"question": t, "key": k, "ok": out[k][0], "note": out[k][1]} for t, k in VIEWER_QUESTIONS]


def dump(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=1)
