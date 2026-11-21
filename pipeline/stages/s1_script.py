"""1-этап: Сценарий (Gemini, орус тилинде).

Эрежелер (docs/VIDEO_RULES.md 2, 3, 12):
  - ар видеого башка баяндоо стили (эң аз колдонулганы);
  - фактылар өзүнчө текшерилет: далилсиз статистика/изилдөө/цитата алынат;
  - 1100–1200 сөз; кайталанган сүйлөм жок;
  - мурунку сценарийлерге окшош эмес (5-грамма + embedding);
  - текст озвучка үчүн гана: аталыш, ремарка, эмодзи жок.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from ..textutil import cosine, duplicate_sentences, jaccard, word_count
from .base import Context, Stage, StageError, gemini_of

JACCARD_MAX = 0.10   # 5-грамма боюнча: ушундан жогору — көчүрүүгө жакын
COSINE_MAX = 0.95    # embedding боюнча: ушундан жогору — мазмуну дээрлик бирдей
PREV_LIMIT = 12


def clean_script(text: str) -> str:
    """Озвучкага кирбей турган нерселерди алып салат."""
    lines = []
    for line in text.replace("\r", "").split("\n"):
        s = line.strip()
        if re.match(r"^(#+|\*\*?[^*]+\*\*?:?$|НАЗВАНИЕ:|Название:|Заголовок:)", s):
            continue
        s = re.sub(r"\[[^\]]{0,80}\]", "", s)            # [пауза], [музыка]
        s = re.sub(r"\*+([^*]+)\*+", r"\1", s)            # **жирный**
        s = re.sub(r"^\s*[-•]\s+", "", s)
        s = re.sub(r"[\U0001F300-\U0001FAFF☀-➿]", "", s)  # эмодзи
        lines.append(s.strip())
    text = "\n".join(lines)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def split_title(text: str) -> tuple[str, str]:
    m = re.search(r"^\s*НАЗВАНИЕ\s*:\s*(.+)$", text, re.M | re.I)
    title = m.group(1).strip().strip('"«»') if m else ""
    body = text[m.end():] if m else text
    return title, clean_script(body)


HOOK_TYPES = {   # видеонун алгачкы 2 сүйлөмү (~8 сек) — ар видеодо мурункулардан БАШКА түр
    "question": "личный, неудобный вопрос зрителю, на который хочется ответить честно",
    "paradox": "парадокс: два утверждения, которые кажутся несовместимыми, но оба правда",
    "micro_story": "сцена из жизни в настоящем времени: конкретный человек, место, деталь, момент напряжения",
    "provocative": "неожиданное утверждение, которое идёт против привычного мнения (без лжи и без кликбейта)",
    "scenario": "«Представьте…»: зритель мысленно оказывается в конкретной ситуации второго лица",
    "observation": "точное наблюдение о мелочи, которую делают почти все, но не замечают",
}
HOOK_BANNED = ("сегодня поговорим", "в этом видео", "привет", "добро пожаловать", "давайте разберёмся",
               "задумывались ли вы когда-нибудь")


def choose_hook(registry: dict, video_id: str) -> str:
    """Hook түрү: эң аз колдонулган жана акыркы видеодогудан башка."""
    hist = [v.get("hook_type") for k, v in sorted(registry.get("videos", {}).items()) if k != video_id]
    last = next((h for h in reversed(hist) if h), None)
    seed = int(hashlib.md5(video_id.encode()).hexdigest(), 16)
    return min((k for k in HOOK_TYPES if k != last), key=lambda k: (hist.count(k), (hash_str(k) ^ seed) % 97))


def hash_str(s: str) -> int:
    return int(hashlib.md5(s.encode()).hexdigest(), 16)


def split_hook_card(text: str) -> tuple[str, str]:
    """«КАРТОЧКА: …» сабын алат (экранга чыга турган hook), тексттен өчүрөт."""
    m = re.search(r"^\s*КАРТОЧКА\s*:\s*(.+)$", text, re.M | re.I)
    if not m:
        return "", text
    card = m.group(1).strip().strip('"«»')[:40]
    return card, (text[:m.start()] + text[m.end():]).strip()


def choose_style(styles: dict[str, str], registry: dict, video_id: str) -> str:
    used: dict[str, int] = {k: 0 for k in styles}
    last: dict[str, int] = {k: -1 for k in styles}
    for i, (vid, v) in enumerate(sorted(registry.get("videos", {}).items())):
        s = v.get("style")
        if s in used and vid != video_id:
            used[s] += 1
            last[s] = i
    seed = int(hashlib.md5(video_id.encode()).hexdigest(), 16)
    return min(styles, key=lambda k: (used[k], last[k], (hash(k) ^ seed) % 1000))


def previous_scripts(ctx: Context) -> list[dict[str, Any]]:
    out = []
    videos = ctx.registry.get("videos", {})
    for vid in sorted(videos, reverse=True):
        v = videos[vid]
        if vid == ctx.video_id or not v.get("script"):
            continue
        text = ctx.store.read_text("Scripts", f"{vid}.txt") if ctx.store else None
        if text:
            out.append({"id": vid, "title": v.get("title", ""), "style": v.get("style", ""),
                        "hook": " ".join(text.split()[:40]), "text": text})
        if len(out) >= PREV_LIMIT:
            break
    return out


def build_prompt(topic: str, niche: dict, style_text: str, prev: list[dict], cfg, hook: str = "question") -> str:
    rules = "\n".join(f"- {r}" for r in niche.get("script_rules", []))
    avoid = "\n".join(f"- «{p['title']}»: {p['hook']}…" for p in prev[:8]) or "- (пока нет)"
    return f"""{niche.get('script_role', '').strip()}

ТЕМА ВИДЕО: {topic}

СТИЛЬ ПОВЕСТВОВАНИЯ ЭТОГО ВИДЕО:
{style_text.strip()}

ПРАВИЛА:
{rules}
- Объём: строго {cfg.words_min}–{cfg.words_max} слов (это ~8 минут озвучки). Это важно.
- Текст только для озвучки: без заголовков, ремарок в скобках, эмодзи, нумерованных списков.
- Пиши абзацами по 2–5 предложений, живым разговорным русским языком.
- Если приводишь пример человека — он вымышленный, и это понятно из текста.
- Запрещено: выдуманные исследования, проценты, цифры, имена учёных и цитаты,
  в которых ты не уверен полностью; медицинские и финансовые рекомендации.
- Психологические механизмы объясняй осторожно: «часто», «у многих», а не «всегда», «у всех».
- ОРИГИНАЛЬНОСТЬ (главное правило канала, YouTube «inauthentic content»): дай зрителю НОВУЮ мысль,
  понятное психологическое объяснение, конкретный жизненный пример и практическую пользу.
  Запрещены пустые мотивационные штампы («поверь в себя», «всё в твоих руках», «никогда не сдавайся»,
  «выйди из зоны комфорта») и общие слова без содержания. Каждый абзац должен добавлять смысл.
- Пиши так, чтобы текст можно было ПОКАЗАТЬ: конкретные люди, действия, места и предметы, а не абстракции.

HOOK — ПЕРВЫЕ 3–5 СЕКУНД решают, останется ли зритель:
- Тип hook'а этого видео: {HOOK_TYPES.get(hook, HOOK_TYPES["question"])}.
- Первое предложение — не больше 14 слов: сразу интересный вопрос, неожиданная мысль или сильная эмоция.
  Обращайся к личной боли, страху, желанию или внутреннему противоречию зрителя, прямо по теме видео.
- Второе-третье предложение честно показывает, что зритель поймёт, если досмотрит, — и это ДОЛЖНО быть
  раскрыто в тексте. Никаких обещаний, на которые в видео нет ответа.
- Без приветствий, долгих вступлений и лишних объяснений до сути.
- Запрещено начинать с: {", ".join("«" + b + "»" for b in HOOK_BANNED)}.
- Начало должно быть совсем другим, чем у наших предыдущих видео (ниже). Не копируй чужие примеры hook'ов.

УДЕРЖАНИЕ ЗРИТЕЛЯ (до самого конца):
- Каждая часть даёт новое: мысль, жизненный пример или психологическое объяснение. Без повторов.
- В середине — 2–3 честных поворота или вопроса, которые возвращают внимание (и на них есть ответ).
- Темп живой: середина не должна «проседать».
- Финал ясно и сильно собирает главный урок видео (без штампов).

НАШИ ПРЕДЫДУЩИЕ ВИДЕО (не повторяй их начало, примеры, метафоры и структуру):
{avoid}

ФОРМАТ ОТВЕТА:
НАЗВАНИЕ: <честное, не кликбейтное название для YouTube, до 70 символов>
КАРТОЧКА: <2–5 слов: самая цепляющая мысль hook'а, для экрана в первые секунды>

<полный текст для озвучки>"""


FACT_PROMPT = """Ты — строгий редактор-фактчекер психологического YouTube-канала.
Проверь текст ниже. Найди утверждения, которые выдают себя за факты:
статистика, проценты, «исследования показали», имена учёных, цитаты, медицинские утверждения,
категоричные обобщения («все люди», «всегда»).
Для каждого: если это не общеизвестный и проверяемый факт — удали или переформулируй
осторожно и честно (как мнение, наблюдение или «многие замечают…»).
Не добавляй новых фактов. Не меняй стиль, длину и структуру сверх необходимого.

Ответ строго в формате:
===ТЕКСТ===
<полный исправленный текст>
===ИЗМЕНЕНИЯ===
<список изменений, по одному в строке; «нет» если изменений не было>

ТЕКСТ:
"""


def fact_review(g, text: str) -> tuple[str, str]:
    out = g.text(FACT_PROMPT + text, purpose="fact_check", temperature=0.2)
    m = re.search(r"===ТЕКСТ===\s*(.*?)\s*===ИЗМЕНЕНИЯ===\s*(.*)", out, re.S)
    if not m:
        return text, "(факт текшерүү жообу форматка туура келген жок — түп текст калды)"
    fixed = clean_script(m.group(1))
    # коопсуздук: редактор текстти 30%дан ашык кыскартса — кабыл албайбыз
    if word_count(fixed) < 0.7 * word_count(text):
        return text, "(редактор текстти өтө кыскартты — түп текст калды)"
    return fixed, m.group(2).strip()


def adjust_length(g, text: str, lo: int, hi: int, log) -> str:
    for attempt in range(3):
        n = word_count(text)
        if lo <= n <= hi:
            return text
        target = (lo + hi) // 2
        action = (f"Расширь текст до ~{target} слов: добавь один новый жизненный пример "
                  f"или практический шаг, а не «воду»." if n < lo else
                  f"Сократи текст до ~{target} слов: убери повторы и второстепенное, "
                  f"сохрани начало, пример и финал.")
        log(f"   ✎ Сөз саны {n} → {target} ({attempt + 1}-аракет)")
        new = clean_script(g.text(
            f"Сейчас в тексте {n} слов. {action}\nСохрани стиль и смысл. "
            f"Не добавляй фактов, статистики и цитат. Верни только полный текст.\n\nТЕКСТ:\n{text}",
            purpose="length", temperature=0.5))
        if word_count(new) > 200:
            text = new
    n = word_count(text)
    if not (lo - 60 <= n <= hi + 60):
        raise StageError(f"Сценарийдин көлөмүн {lo}–{hi} сөзгө келтирүү ишке ашкан жок ({n} сөз)")
    return text


def fix_duplicates(g, text: str) -> str:
    dups = duplicate_sentences(text)
    if not dups:
        return text
    listed = "\n".join(f"- {d}" for d in dups)
    new = clean_script(g.text(
        "В тексте повторяются предложения:\n" + listed +
        "\nПерепиши только повторы другими словами (второе вхождение), остальное не меняй. "
        "Верни только полный текст.\n\nТЕКСТ:\n" + text, purpose="dedupe", temperature=0.4))
    return new if word_count(new) > 0.8 * word_count(text) else text


def similarity(g, text: str, prev: list[dict], log) -> dict:
    res = {"max_jaccard": 0.0, "max_cosine": None, "closest": None}
    for p in prev:
        j = jaccard(text, p["text"])
        if j > res["max_jaccard"]:
            res["max_jaccard"], res["closest"] = round(j, 4), p["id"]
    if prev:
        try:
            vecs = g.embed([text] + [p["text"] for p in prev])
            cs = [cosine(vecs[0], v) for v in vecs[1:]]
            i = max(range(len(cs)), key=cs.__getitem__)
            res["max_cosine"] = round(cs[i], 4)
            if cs[i] >= COSINE_MAX:
                res["closest"] = prev[i]["id"]
        except Exception as e:  # embedding жок болсо — 5-грамма жетиштүү
            log(f"   ⚠ Embedding окшоштугу өлчөнгөн жок: {type(e).__name__}")
    res["too_similar"] = res["max_jaccard"] >= JACCARD_MAX or \
        (res["max_cosine"] is not None and res["max_cosine"] >= COSINE_MAX)
    return res


class ScriptStage(Stage):
    name = "s1_script"
    title = "Сценарий"
    retries = 2

    def run(self, ctx: Context) -> dict[str, Any]:
        g = gemini_of(ctx)
        cfg, niche, topic = ctx.cfg, ctx.cfg.niche_data, ctx.state.topic
        styles: dict[str, str] = niche.get("narrative_styles") or {"default": ""}
        prev = previous_scripts(ctx)
        ctx.log(f"   Мурунку сценарийлер (салыштыруу үчүн): {len(prev)}")

        tried: list[str] = []
        for round_ in range(2):
            pool = {k: v for k, v in styles.items() if k not in tried} or styles
            style = choose_style(pool, ctx.registry, ctx.video_id)
            tried.append(style)
            ctx.log(f"   Баяндоо стили: {style}")

            hook = choose_hook(ctx.registry, ctx.video_id)
            draft = g.text(build_prompt(topic, niche, styles[style], prev, cfg, hook),
                           purpose="script_draft", temperature=0.95)
            hook_card, draft_wo = split_hook_card(draft)
            title, body = split_title(draft_wo)
            ctx.path("script", f"draft_{round_ + 1}.txt").write_text(draft, encoding="utf-8")
            if word_count(body) < 0.4 * cfg.words_min:
                raise StageError(f"Gemini өтө кыска текст берди ({word_count(body)} сөз)")

            text, changes = fact_review(g, body)
            text = adjust_length(g, text, cfg.words_min, cfg.words_max, ctx.log)
            text = fix_duplicates(g, text)
            text = adjust_length(g, text, cfg.words_min, cfg.words_max, ctx.log)
            dups = duplicate_sentences(text)
            if dups:
                raise StageError(f"Кайталанган сүйлөмдөр калды: {dups[:2]}")

            sim = similarity(g, text, prev, ctx.log)
            ctx.log(f"   Окшоштук: 5-грамма {sim['max_jaccard']}, embedding {sim['max_cosine']}")
            if not sim["too_similar"]:
                break
            ctx.log(f"   ⚠ {sim['closest']} менен өтө окшош — башка стилде кайра жазылат")
        else:
            raise StageError(f"Сценарий мурунку видеого ({sim['closest']}) өтө окшош бойдон калды")

        # Hook + удержание: катаал «көрүүчү» баалайт, жетишсиз болсо башталыш/финал кайра жазылат
        from .. import retention

        fixed, ret = retention.improve(g, text, title, hook, ctx.log)
        if fixed != text:
            fixed = adjust_length(g, fixed, cfg.words_min, cfg.words_max, ctx.log)
            if not duplicate_sentences(fixed):
                text = fixed
        ctx.path("script", "retention.json").write_text(retention.dump(ret), encoding="utf-8")

        script = ctx.path("script", "script.txt")
        script.write_text(text + "\n", encoding="utf-8")
        ctx.path("script", "fact_check.txt").write_text(changes + "\n", encoding="utf-8")
        first = " ".join(re.split(r"(?<=[.!?…])\s+", text.strip())[:2])
        bad_open = next((b for b in HOOK_BANNED if first.lower().startswith(b)), None)
        if bad_open:
            ctx.log(f"   ⚠ Hook шаблон менен башталды («{bad_open}») — QA текшерет")
        meta = {"title": title, "style": style, "words": word_count(text), "hook_type": hook,
                "hook": first[:240], "hook_card": hook_card or " ".join(first.split()[:5]),
                "hook_score": ret["review"].get("hook_score"), "hook_promise": ret["review"].get("promise", ""),
                "retention_strategy": ret["review"].get("retention_strategy", ""), "retention_ok": ret["ok"],
                "similarity": sim, "fact_check_changes": changes.count("\n") + 1
                if changes and changes.lower() != "нет" else 0}
        meta_file = ctx.path("script", "meta.json")
        meta_file.write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
        ctx.log(f"   ✓ «{title}» — {meta['words']} сөз, стиль: {style}")

        entry = ctx.registry.setdefault("videos", {}).setdefault(ctx.video_id, {})
        entry.update({"title": title, "style": style, "script": True, "hook_type": hook})
        if ctx.store:
            ctx.store.publish("Scripts", script, f"{ctx.video_id}.txt")
        return {"script_path": str(script), "meta_file": str(meta_file)}

    def verify(self, ctx: Context, outputs: dict[str, Any] | None) -> None:
        super().verify(ctx, outputs)
        n = word_count(ctx.path("script", "script.txt").read_text(encoding="utf-8"))
        if not (ctx.cfg.words_min - 60 <= n <= ctx.cfg.words_max + 60):
            raise StageError(f"Сценарийде {n} сөз — {ctx.cfg.words_min}–{ctx.cfg.words_max} керек")
