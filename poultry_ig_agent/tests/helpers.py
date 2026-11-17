import json
import os
import tempfile

from poultry_ig_agent import config


def tmp_out():
    d = tempfile.mkdtemp()
    config.OUT_DIR = d
    return d


def course_file(**over):
    c = {"name": "Тоок фермасы курсу", "price": 3000, "currency": "сом", "payment_methods": ["Elsom", "банк картасы"],
         "contacts": {"whatsapp_group_url": "https://chat.whatsapp.com/xyz"}, "start_date": "1-декабрь",
         "program": ["Жем", "Тооканы уюштуруу"], "faq": [{"q": "Сертификат берилеби?", "a": "Ооба, аягында сертификат берилет."}]}
    c.update(over)
    fd, p = tempfile.mkstemp(suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(c, f, ensure_ascii=False)
    return p


def shots(n=5, src="ai"):
    return [{"n": i + 1, "duration": 5, "source": src, "visual": "hens in coop", "onscreen": f"Кадр {i + 1}"} for i in range(n)]


def fake(prompt):
    ru = "орус" in prompt
    if '"items"' in prompt:
        return {"items": [
            {"day": 1, "topic_key": "broiler", "content_type": "education", "format": "carousel", "topic": "Бройлер", "angle": "a"},
            {"day": 2, "topic_key": "daily", "content_type": "real_farm", "format": "reel", "topic": "Эртең", "angle": "b"}]}
    base = {"hook": "Утро на ферме" if ru else "Таң атты", "caption": "Комментарийге жазыңыз 👇", "hashtags": ["#ферма"],
            "cta": {"type": "comment", "text": "Суроо?"}, "sources": []}
    if '"frames"' in prompt:
        return {**base, "frames": [{"text": "Суроо?", "sticker": "poll", "options": ["Ооба", "Жок"]}]}
    if '"slides"' in prompt:
        return {**base, "slides": [{"title": f"T{i}", "body": "Текст."} for i in range(6)]}
    return {**base, "voiceover": "Рассвет на ферме." if ru else "Таң атты, ферма ойгонду.", "hook_onscreen": "Таң!", "shots": shots()}
