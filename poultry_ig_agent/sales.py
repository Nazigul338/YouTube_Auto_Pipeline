"""Сатуу: курс маалыматы course.json'дон гана. Бош талаа = агент ойлоп таппайт."""
import re

HANDOFF = {
    "ky": "Так маалымат үчүн Direct'ке жазыңыз — менеджер жооп берет 🙌",
    "ru": "Точную информацию уточните в Direct — менеджер ответит 🙌",
}
INTENTS = {  # intent -> (талаа, ключ сөздөр). ИРЕТИ МААНИЛҮҮ: так суроолор жалпыларынан мурун
    "duration": ("duration", ("канча убакыт", "канча күн", "канча жума", "узактыг", "сколько длит", "длитель")),
    "enroll": ("enrollment_steps", ("каттал", "жазылуу", "жазылам", "кантип кошул", "кантип алам", "кантип окуйм",
                                    "записат", "запис", "регистрац", "как попасть", "как купить")),
    "payment": ("payment_methods", ("төлөм", "төлөйт", "төлөйм", "mbank", "мбанк", "оплат", "перевод", "карта")),
    "price": ("price", ("баасы", "баа ", "канча турат", "канча сом", "канча", "кымбат", "цена", "сколько стоит",
                        "стоимост", "сколько")),
    "start": ("start_date", ("качан башта", "башталат", "когда нач", "старт", "дата")),
    "program": ("program", ("программа", "сабак", "эмне үйрөт", "эмнени үйрөт", "что узна", "чему научат", "темалар", "урок")),
    "whatsapp": ("whatsapp", ("whatsapp", "ватсап", "вотсап", "группа", "топко", "шилтеме")),
    "refund": ("refund_policy", ("кайтарым", "кайтар", "возврат", "вернуть")),
    "name": ("name", ("кандай курс", "курстун аты", "кайсы курс", "какой курс", "название")),
}
LABELS = {
    "ky": {"price": "Курстун баасы: {v}.", "payment": "Төлөм: {v} аркылуу.", "start": "Курс башталат: {v}.",
           "duration": "Курстун узактыгы: {v}.", "program": "Курстун темалары: {v}.", "refund": "Кайтаруу шарты: {v}.",
           "name": "Курс: «{v}».", "whatsapp": "WhatsApp группа: {v}", "enroll": "Курска катталуу тартиби:\n{v}"},
    "ru": {"price": "Стоимость курса: {v}.", "payment": "Оплата: через {v}.", "start": "Старт курса: {v}.",
           "duration": "Длительность: {v}.", "program": "Темы курса: {v}.", "refund": "Условия возврата: {v}.",
           "name": "Курс: «{v}».", "whatsapp": "Группа WhatsApp: {v}", "enroll": "Как записаться на курс:\n{v}"},
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
    if field == "enrollment_steps":
        return "\n".join(f"{i}. {s}" for i, s in enumerate(v, 1))
    if isinstance(v, list):
        return ", ".join(map(str, v))
    return str(v)


def match_intent(text):
    t = text.lower()
    for intent, (_, words) in INTENTS.items():
        if any(w in t for w in words):
            return intent
    return None


HEALTH_WORDS = ("оору", "ооруп", "өлүп", "өлдү", "ич өт", "дары", "дарыла", "болеет", "болезн", "умира", "лечить", "понос")
HEALTH_REPLY = {
    "ky": "Тооктордун ден соолугу боюнча сырттан диагноз коё албайбыз — жакынкы ветеринарга кайрылыңыз 🙏 "
          "Жалпы багуу боюнча суроолоруңуз болсо, Direct'ке жазыңыз.",
    "ru": "Мы не ставим диагноз дистанционно — пожалуйста, обратитесь к ветеринару 🙏 "
          "По общим вопросам содержания пишите в Direct.",
}


def answer(message, course, lang="ky"):
    """Детерминдүү жооп: ден соолук → FAQ → intent → handoff. Эч качан сан/маалымат ойлоп таппайт."""
    t = message.lower()
    if any(w in t for w in HEALTH_WORDS):
        return {"reply": HEALTH_REPLY[lang], "source": "health", "needs_human": True}
    for item in course.get("faq", []):
        kws = [w for w in re.findall(r"\w{4,}", item.get("q", "").lower())]
        if kws and sum(w in t for w in kws) >= max(1, len(kws) // 2):
            return {"reply": item["a"], "source": "faq", "needs_human": False}
    intent = match_intent(t)
    if intent:
        val = _value(INTENTS[intent][0], course, lang)
        if val:
            reply = LABELS[lang][intent].format(v=val)
            if intent in ("price", "payment") and course.get("enrollment_steps"):
                reply += "\n" + ("Катталуу тартибин билүү үчүн «катталуу» деп жазыңыз." if lang == "ky"
                                  else "Напишите «записаться», чтобы узнать порядок записи.")
            return {"reply": reply, "source": "config:" + intent, "needs_human": False}
        miss = {"ky": "Бул суроо боюнча так маалымат азырынча жок — менеджер Direct'те жооп берет 🙌",
                "ru": "Точной информации по этому вопросу пока нет — менеджер ответит в Direct 🙌"}[lang]
        return {"reply": miss, "source": "handoff:" + intent, "needs_human": True}
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
