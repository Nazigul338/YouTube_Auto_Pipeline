"""Сатуу: курс маалыматы course.json'дон гана. Бош талаа = агент ойлоп таппайт."""
import re

HANDOFF = {
    "ky": "Так маалымат үчүн Direct'ке жазыңыз — менеджер жооп берет 🙌",
    "ru": "Точную информацию уточните в Direct — менеджер ответит 🙌",
}
INTENTS = {  # intent -> (талаа, ключ сөздөр)
    "price": ("price", ("баасы", "канча", "кымбат", "цена", "сколько стоит", "стоимост", "сколько")),
    "payment": ("payment_methods", ("төлөм", "төлөйт", "оплат", "перевод", "карта")),
    "start": ("start_date", ("качан башта", "башталат", "когда нач", "старт", "дата")),
    "duration": ("duration", ("канча убакыт", "узактыг", "сколько длит", "длитель")),
    "program": ("program", ("программа", "эмне үйрөт", "что узна", "чему научат", "темалар")),
    "whatsapp": ("whatsapp", ("whatsapp", "ватсап", "группа", "топ")),
    "refund": ("refund_policy", ("кайтарым", "кайтар", "возврат", "вернуть")),
}


def price_text(course):
    if course.get("price") in (None, ""):
        return None
    return f"{course['price']} {course.get('currency') or ''}".strip()


def whatsapp_link(course):
    c = course.get("contacts", {})
    return c.get("whatsapp_group_url") or (f"https://wa.me/{re.sub(r'[^0-9]', '', c['whatsapp_number'])}" if c.get("whatsapp_number") else None)


def ready(course):
    return bool(course.get("name"))


def brief(course):
    """LLM prompt үчүн: бар болгон факттар гана."""
    facts = {k: v for k, v in course.items() if not k.startswith("_") and v not in (None, "", [], {})}
    if price_text(course):
        facts["price_text"] = price_text(course)
    return facts


def _value(field, course, lang):
    if field == "whatsapp":
        link = whatsapp_link(course)
        return f"WhatsApp: {link}" if link else None
    v = course.get(field)
    if v in (None, "", []):
        return None
    if field == "price":
        return price_text(course)
    if isinstance(v, list):
        return "; ".join(map(str, v))
    return str(v)


def match_intent(text):
    t = text.lower()
    for intent, (_, words) in INTENTS.items():
        if any(w in t for w in words):
            return intent
    return None


def answer(message, course, lang="ky"):
    """Детерминдүү жооп: FAQ → intent → handoff. Эч качан сан ойлоп таппайт."""
    t = message.lower()
    for item in course.get("faq", []):
        kws = [w for w in re.findall(r"\w{4,}", item.get("q", "").lower())]
        if kws and sum(w in t for w in kws) >= max(1, len(kws) // 2):
            return {"reply": item["a"], "source": "faq", "needs_human": False}
    intent = match_intent(t)
    if intent:
        val = _value(INTENTS[intent][0], course, lang)
        if val:
            return {"reply": val, "source": "config:" + intent, "needs_human": False}
        return {"reply": HANDOFF[lang], "source": "handoff:" + intent, "needs_human": True}
    return {"reply": HANDOFF[lang], "source": "handoff", "needs_human": True}


def draft_dm_reply(message, course, lang="ky", generate=None):
    r = answer(message, course, lang)
    if r["source"].startswith(("faq", "config")) or generate is None:
        return r
    prompt = (f"Сен тоок ферма курсунун администраторусуң. Тил: {'кыргыз' if lang == 'ky' else 'орус'}. "
              f"Кардарга КЫСКА, жылуу жооп жаз. ТЕК ушул фактыларды колдон: {brief(course)}. "
              f"Фактыда жок нерсени (баа, дата, кепилдик) АЙТПА, анда «Direct/менеджер» деп жөнөт. Алдаба, шашылтпа.\n"
              f"Кардардын билдирүүсү: {message!r}\nJSON: {{\"reply\":\"...\"}}")
    out = generate(prompt)
    return {"reply": out.get("reply", HANDOFF[lang]), "source": "llm", "needs_human": True}


def invite(course, lang="ky"):
    link = whatsapp_link(course)
    if not link:
        return HANDOFF[lang]
    return ("Суроолоруңуз болсо WhatsApp тобуна кошулуңуз: " if lang == "ky" else "Присоединяйтесь к группе WhatsApp: ") + link


def check(post, course):
    """Сатуу постунун чынчылдыгы."""
    issues = []
    if post.get("purpose") != "sales":
        return issues
    if not ready(course):
        issues.append("course.json толтурулган эмес (name жок) — сатуу постун бекитүүгө болбойт")
    txt = (post.get("caption", "") + " " + post.get("voiceover", "")).lower()
    if not post.get("cta", {}).get("text"):
        issues.append("Сатуу постунда CTA жок")
    if re.search(r"(кепилдик|гарантия|гарантир)", txt):
        issues.append("Кепилдик убадасы тыюу салынган")
    return issues
