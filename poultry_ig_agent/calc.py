"""Бройлер экономикасы — ТЕК сиз киргизген сандар менен, детерминдүү (LLM сан ойлобойт)."""
import json

REQUIRED = ("chicks", "chick_price", "feed_price_per_kg", "feed_per_bird_kg", "mortality_pct",
            "avg_live_weight_kg", "sell_price_per_kg", "other_costs")
LABELS = {
    "ky": ["Баштапкы эсеп (мисал)", "Чыгымдар", "Түшүм", "Пайда / жоготуу", "Бул сиз киргизген болжолдор менен мисал эсеп, кепилдик эмес."],
    "ru": ["Пример расчёта", "Расходы", "Выручка", "Прибыль / убыток", "Это пример по введённым вами допущениям, не гарантия."],
}


def compute(p):
    miss = [k for k in REQUIRED if p.get(k) in (None, "")]
    if miss:
        raise ValueError("calc киргизүүлөрү жетишпейт: " + ", ".join(miss))
    alive = p["chicks"] * (1 - p["mortality_pct"] / 100)
    chicks_cost = p["chicks"] * p["chick_price"]
    feed_cost = p["chicks"] * p["feed_per_bird_kg"] * p["feed_price_per_kg"]
    cost = chicks_cost + feed_cost + p["other_costs"]
    revenue = alive * p["avg_live_weight_kg"] * p["sell_price_per_kg"]
    return {"alive": round(alive, 1), "chicks_cost": round(chicks_cost), "feed_cost": round(feed_cost),
            "cost": round(cost), "revenue": round(revenue), "profit": round(revenue - cost),
            "profit_per_bird": round((revenue - cost) / p["chicks"], 1)}


def to_post(p, lang="ky", currency=""):
    r = compute(p)
    L = LABELS[lang]
    cur = f" {currency}".rstrip()
    slides = [
        {"title": L[0], "body": f"{p['chicks']} балапан, өлүм {p['mortality_pct']}%" if lang == "ky" else f"{p['chicks']} цыплят, падёж {p['mortality_pct']}%"},
        {"title": L[1], "body": f"Балапан: {r['chicks_cost']}{cur}\nЖем: {r['feed_cost']}{cur}\nБашка: {p['other_costs']}{cur}\nЖалпы: {r['cost']}{cur}"},
        {"title": L[2], "body": f"{r['alive']} баш × {p['avg_live_weight_kg']} кг × {p['sell_price_per_kg']}{cur} = {r['revenue']}{cur}"},
        {"title": L[3], "body": f"{r['profit']}{cur} ({r['profit_per_bird']}{cur} / баш)"},
        {"title": "⚠️", "body": L[4]},
    ]
    return {"format": "carousel", "lang": lang, "calc": True, "purpose": "education", "topic_key": "economics",
            "topic": "Бройлер эсеби" if lang == "ky" else "Расчёт бройлеров", "hook": slides[0]["title"],
            "caption": L[4] + "\nӨз сандарыңыз менен эсептеп көрүңүз: комментарийге жазыңыз 👇" if lang == "ky" else L[4] + "\nПосчитайте со своими цифрами — пишите в комментариях 👇",
            "hashtags": ["#тоокферма", "#бройлер"] if lang == "ky" else ["#бройлеры", "#птицеводство"], "slides": slides, "calc_result": r}


def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)
