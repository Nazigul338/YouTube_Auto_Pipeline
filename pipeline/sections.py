"""МОТИВАЦИЯ + ПСИХОЛОГИЯ форматынын түзүлүшү (колдонуучунун бекиткен планы, 2026-11-24).

7 бөлүк: hook → problem → causes → story (БИР негизги турмуштук окуя) → meaning (окуянын психологиялык мааниси +
темага кайтуу) → practice (практикалык кеңештер) → finale (мотивациялык жыйынтык).

Милдеттүү эрежелер:
  №1 Hook алгачкы 3 секундда (retention.py: биринчи сүйлөм ≤8 сөз, үндө ≤3.0 сек, баа ≥8/10).
  №2 БИР гана окуя: сценарийдин ортосунда (25–65%), 10–25% көлөмү, андан кийин мааниси жана темага кайтуу,
     ойдон чыгарылганы чыныгы деп көрсөтүлбөйт, мурунку видеолордун окуясын кайталабайт.
  Көңүлдү ар 20–40 сек сайын жандандыруу (жаңы ой/суроо/мисал/бурулуш): эки бурулуштун ортосу ≤40 сек.

Бир Gemini суроосу бөлүктөрдү, окуяны жана бурулуштарды белгилейт (квота үнөмү); эрежелер жергиликтүү текшерилет.
"""
from __future__ import annotations

import json
import re

from .story import _find
from .textutil import jaccard

KEYS = ["hook", "problem", "causes", "story", "meaning", "practice", "finale"]
REAL_WPS = 2.1              # чыныгы TTS ылдамдыгы (~126 сөз/мүн)
STORY_START = (0.25, 0.65)  # окуя сценарийдин ушул үлүшүнүн ичинде башталат («ортосунда»)
STORY_SHARE = (0.10, 0.25)  # окуянын көлөмү (кошумча элемент — негизги мазмун эмес)
TURN_GAP_SEC = 40.0         # көңүлдү жандандыруучу эки бурулуштун ортосу
FIX_MIN_SHARE = 0.55        # оңдолгон вариант ушундан кыска болсо гана ташталат
STORY_JACCARD = 0.22        # мурунку окуя менен 3-грамма окшоштугу
STORY_COSINE = 0.88         # embedding окшоштугу
REAL_CLAIMS = ("реальная история", "реальной истории", "правдивая история", "это произошло на самом деле",
               "это случилось на самом деле", "основано на реальных", "мой знакомый", "моя знакомая",
               "мой друг", "моя подруга", "мой клиент", "моя клиентка", "я знал одного", "я знаю одного",
               "я знала одну", "я знаю одну", "один мой", "одна моя")
EXAMPLE_MARKERS = ("представь", "представьте", "например", "возьмём", "возьмем", "допустим", "вообрази",
                   "пример", "такую ситуацию", "условно", "назовём", "назовем")

MAP_PROMPT = """Ты — редактор психологического YouTube-канала. Ниже сценарий (русский, для озвучки).
Разметь его. Верни ТОЛЬКО JSON-объект:
{{
 "sections": [{{"section": "<ключ>", "starts": "<первые 6 слов раздела ДОСЛОВНО из текста>"}}],
 "stories": [{{"starts": "<первые 6 слов истории дословно>", "ends": "<последние 6 слов истории дословно>",
              "summary": "<2 предложения: кто, что произошло, чем закончилось>"}}],
 "turns": ["<первые 6 слов дословно>", ...]
}}
Ключи разделов по порядку: {keys}.
hook — первые фразы-зацепка; problem — раскрытие психологической проблемы; causes — причины;
story — жизненная история/пример с конкретным человеком и ситуацией; meaning — психологический смысл этой истории
и возвращение к теме; practice — практические советы; finale — мотивационный финал.
"stories": ВСЕ отдельные развёрнутые истории о конкретном человеке (не считай короткие примеры в одно предложение
вроде «например, когда ты…»).
"turns": начала ВСЕХ моментов, которые заново цепляют внимание: новая мысль, вопрос к зрителю, пример,
неожиданный факт или поворот (обычно 12–25 на сценарий).

СЦЕНАРИЙ:
{text}"""

FIX_PROMPT = """Ты — автор мотивационно-психологических сценариев для русскоязычного YouTube-канала.
Исправь сценарий по замечаниям редактора. Тема: «{topic}».
Формат (обязателен): 1) hook — первые 3 секунды, первое предложение не длиннее 8 слов; 2) раскрытие
психологической проблемы; 3) причины; 4) ОДНА короткая жизненная история (60–100 секунд, 10–25% текста) в середине,
явно поданная как пример («Представь…», «Например…»), без диалогов и без утверждений, что это реальный случай;
5) психологический смысл истории и возвращение к теме; 6) 3–4 практических шага и одно упражнение; 7) сильный
мотивационный финал. Каждые 20–40 секунд — новая мысль, вопрос, пример или поворот.
ЗАМЕЧАНИЯ:
{why}
Сохрани всё, что не затронуто замечаниями. Объём — НЕ МЕНЬШЕ {n} слов (не сокращай текст!).
Подсказка по месту истории: история начинается не раньше {a}-го слова и не позже {b}-го слова; перед ней — проблема
и причины, после неё — её смысл. Если долго нет нового поворота — вставь вопрос к зрителю или новый поворот мысли
примерно через каждые 60–80 слов.
Верни ТОЛЬКО исправленный текст для озвучки (без заголовков и пояснений).

ТЕКСТ:
{text}"""


def enabled(cfg) -> bool:
    """Ниша профилинде `structure: mp7` болсо (motivation.yaml)."""
    return (getattr(cfg, "niche_data", None) or {}).get("structure") == "mp7"


def _low(s: str) -> str:
    return " " + s.lower().replace("ё", "е") + " "


def map_sections(g, text: str) -> dict:
    """Gemini белгилөөсү → сөз индекстери. Ката болсо {"ok": False}."""
    words = text.split()
    try:
        r = g.json(MAP_PROMPT.format(keys=", ".join(KEYS), text=text), purpose="format_map", temperature=0.1)
    except Exception as e:
        return {"ok": False, "error": type(e).__name__, "n": len(words)}
    if not isinstance(r, dict):
        return {"ok": False, "error": "not_dict", "n": len(words)}
    starts: dict[str, int] = {}
    last = 0
    for a in r.get("sections") or []:
        if isinstance(a, dict) and a.get("section") in KEYS and a["section"] not in starts:
            i = _find(words, str(a.get("starts", "")), last)
            if i is not None and (i > last or not starts):
                starts[a["section"]] = i
                last = i
    if starts:
        starts["hook"] = 0
    stories = []
    for s in r.get("stories") or []:
        if not isinstance(s, dict):
            continue
        a = _find(words, str(s.get("starts", "")), 0)
        if a is None:
            continue
        b = _find(words, str(s.get("ends", "")), a)
        e = min(len(words), (b + len(str(s.get("ends", "")).split())) if b is not None else a)
        stories.append({"w0": a, "w1": max(e, a), "summary": str(s.get("summary", ""))[:400]})
    turns = sorted({i for t in r.get("turns") or [] if isinstance(t, str)
                    for i in [_find(words, t, 0)] if i is not None})
    keys = [k for k in KEYS if k in starts]
    secs = [{"section": k, "w0": starts[k], "w1": starts[keys[j + 1]] if j + 1 < len(keys) else len(words)}
            for j, k in enumerate(keys)]
    return {"ok": True, "n": len(words), "sections": secs, "stories": stories, "turns": turns}


def story_span(info: dict) -> tuple[int, int] | None:
    """Негизги окуянын сөз аралыгы: Gemini'дин «stories» белгиси, болбосо «story» бөлүгү."""
    if info.get("stories"):
        s = max(info["stories"], key=lambda x: x["w1"] - x["w0"])
        if s["w1"] > s["w0"]:
            return s["w0"], s["w1"]
    sec = next((s for s in info.get("sections", []) if s["section"] == "story"), None)
    return (sec["w0"], sec["w1"]) if sec else None


def check(info: dict, text: str, prev: list[dict] | None = None, g=None) -> dict:
    """Эрежелер → {"problems": [...], "story": {...}, "max_gap_sec": ...}. info = map_sections()."""
    p: list[str] = []
    n = max(1, info.get("n") or len(text.split()))
    if not info.get("ok"):
        return {"problems": [f"түзүлүш белгиленген жок ({info.get('error')})"], "story": {}, "max_gap_sec": None}
    keys = [s["section"] for s in info["sections"]]
    missing = [k for k in KEYS if k not in keys]
    if missing:
        p.append(f"бөлүктөр жок: {', '.join(missing)}")
    if len(info["stories"]) > 1:
        p.append(f"окуя {len(info['stories'])} — бир гана негизги окуя болушу керек")
    span = story_span(info)
    st: dict = {}
    if not span:
        p.append("негизги турмуштук окуя жок")
    else:
        a, b = span
        share, pos = (b - a) / n, a / n
        words = text.split()
        body = " ".join(words[a:b])
        lead = " ".join(words[max(0, a - 25):b])
        st = {"w0": a, "w1": b, "share": round(share, 3), "start": round(pos, 3),
              "summary": (info["stories"] or [{}])[0].get("summary", "") if info["stories"] else body[:300],
              "marked_example": any(m in _low(lead) for m in EXAMPLE_MARKERS)}
        if not STORY_START[0] <= pos <= STORY_START[1]:
            p.append(f"окуя ортосунда эмес ({pos:.0%}; керек {STORY_START[0]:.0%}–{STORY_START[1]:.0%})")
        if not STORY_SHARE[0] <= share <= STORY_SHARE[1]:
            p.append(f"окуянын көлөмү {share:.0%} (керек {STORY_SHARE[0]:.0%}–{STORY_SHARE[1]:.0%})")
        if not st["marked_example"]:
            p.append("окуя мисал катары белгиленген эмес («Представь…», «Например…»)")
        if body.count("«") >= 3 or len(re.findall(r"(?m)^\s*[—–-]\s", body)) >= 2:
            p.append("окуяда диалогдор бар (кино сюжет эмес, диктор баяндайт)")
        meaning = next((s for s in info["sections"] if s["section"] == "meaning"), None)
        if not meaning or meaning["w0"] < a:
            p.append("окуядан кийин анын психологиялык мааниси жок")
        if prev and st.get("summary"):
            st["similar"] = story_similarity(st["summary"], prev, g)
            if st["similar"]["too_similar"]:
                p.append(f"окуя {st['similar']['closest']} видеосунун окуясына окшош — жаңы окуя керек")
    claims = [c for c in REAL_CLAIMS if c in _low(text)]
    if claims:
        p.append(f"ойдон чыгарылган мисал чыныгы катары көрсөтүлгөн: «{claims[0]}»")
    gaps = [b - a for a, b in zip([0] + info["turns"], info["turns"] + [n])]
    max_gap = round(max(gaps) / REAL_WPS, 1) if gaps else None
    if not info["turns"]:
        p.append("көңүлдү жандандыруучу бурулуштар белгиленген жок")
    elif max_gap and max_gap > TURN_GAP_SEC:
        p.append(f"{max_gap:.0f} сек жаңы ой/суроо/бурулушсуз (керек ≤{TURN_GAP_SEC:.0f} сек)")
    return {"problems": p, "story": st, "max_gap_sec": max_gap}


def story_similarity(summary: str, prev: list[dict], g=None) -> dict:
    """prev: [{"id", "story_summary"}] — мурунку видеолордун окуялары."""
    others = [x for x in prev if x.get("story_summary")]
    best, who = 0.0, None
    for x in others:
        j = jaccard(summary, x["story_summary"], n=3)
        if j > best:
            best, who = j, x.get("id")
    cos = None
    if g is not None and others and hasattr(g, "embed"):
        try:
            from .textutil import cosine

            vec = g.embed([summary] + [x["story_summary"] for x in others])
            cs = [cosine(vec[0], v) for v in vec[1:]]
            k = max(range(len(cs)), key=cs.__getitem__)
            cos = round(cs[k], 4)
            if cos >= STORY_COSINE:
                who = others[k].get("id")
        except Exception:
            cos = None
    return {"jaccard": round(best, 3), "cosine": cos, "closest": who,
            "too_similar": best >= STORY_JACCARD or (cos is not None and cos >= STORY_COSINE)}


def previous_stories(registry: dict, video_id: str) -> list[dict]:
    return [{"id": vid, "story_summary": e.get("story_example")}
            for vid, e in (registry or {}).get("videos", {}).items()
            if vid != video_id and e.get("story_example")]


def enforce(g, text: str, topic: str, prev: list[dict], log, tries: int = 2) -> tuple[str, dict, dict]:
    """Белгилейт → текшерет → бузулса, замечаниялар менен оңдотот (≤tries). → (текст, info, отчет)."""
    info = map_sections(g, text)
    rep = check(info, text, prev, g)
    for k in range(tries):
        if not rep["problems"]:
            break
        log(f"   ⚠ Формат ({k + 1}/{tries}): {'; '.join(rep['problems'])} — оңдолот")
        try:
            new = g.text(FIX_PROMPT.format(topic=topic, why="\n".join(f"- {x}" for x in rep["problems"]),
                                           n=len(text.split()), a=int(STORY_START[0] * len(text.split())) + 10,
                                           b=int(0.55 * len(text.split())), text=text),
                         purpose="format_fix", temperature=0.6).strip()
        except Exception as e:
            log(f"   ⚠ Формат оңдолгон жок ({type(e).__name__})")
            break
        # run #45354695418: Gemini оңдогондо текстти ~20%дан ашык кыскартып, эки вариант тең ташталган.
        # Кыскараак вариант да кабыл алынат — s1 андан кийин adjust_length менен 1100–1200 сөзгө жеткирет.
        if len(new.split()) < FIX_MIN_SHARE * len(text.split()):
            log(f"   ⚠ Оңдолгон вариант өтө кыска ({len(new.split())} сөз) — түп текст калды")
            continue
        info2 = map_sections(g, new)
        rep2 = check(info2, new, prev, g)
        if len(rep2["problems"]) < len(rep["problems"]) or (not rep2["problems"]):
            text, info, rep = new, info2, rep2
    return text, info, rep


SCENE_RULE = """
THIS VIDEO'S STRUCTURE (motivation + psychology monologue, NOT a film): each scene is tagged with its part.
- [hook]: the very first scene is the 3-second hook — the most striking, emotional, on-topic image of the video.
- [story]: the ONE life example told by the narrator — show its place, objects, light and mood (hands, back,
  silhouette, everyday details); no faces in close-up, no text.
- [meaning]/[causes]/[problem]: show the psychological idea through real human situations or clear visual metaphors.
- [practice]: show the concrete action of each advice (writing, breathing, walking, a small step).
- [finale]: strong, hopeful, forward-moving images.
"""


def scene_labels(info: dict, texts: list[str]) -> list[str | None]:
    """Ар сахнанын бөлүгү (сахна башталган сөз индекси боюнча)."""
    if not info or not info.get("ok") or not info.get("sections"):
        return [None] * len(texts)
    out, w = [], 0
    for t in texts:
        sec = next((x["section"] for x in info["sections"] if x["w0"] <= w < x["w1"]), info["sections"][-1]["section"])
        out.append(sec)
        w += len(t.split())
    if out:
        out[0] = "hook"
    return out


def dump(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=1)
