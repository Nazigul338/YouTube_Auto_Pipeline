"""Жума сайын отчет: эмне иштеди, эмнени жакшыртуу керек. Эсеп-кысап детерминдүү (LLM жок)."""
import datetime as dt
import re

from . import sales

INTENT = re.compile(r"(баасы|канча|курс|записа|цена|сколько|\+?996|whatsapp|ватсап|катыш|хочу|кызык)", re.I)


def collect(client, limit=30):
    rows = []
    for m in client.recent_media(limit):
        mt = client.media_insights(m["id"])
        rows.append({"id": m["id"], "link": m.get("permalink"), "type": m.get("media_product_type") or m.get("media_type"),
                     "ts": m.get("timestamp", ""), "caption": (m.get("caption") or "")[:60],
                     "likes": m.get("like_count", 0), "comments": m.get("comments_count", 0), **mt})
    return rows


def count_leads(client, rows, per_post=50):
    """Кардар кызыгуусунун жакындоо көрсөткүчү: комментарийлерде баа/курс/номер сурагандар."""
    for r in rows:
        try:
            cs = client.list_comments(r["id"], per_post)
        except Exception:
            cs = []
        r["leads"] = sum(1 for c in cs if INTENT.search(c.get("text", "")))
    return rows


def _top(rows, key, n=3):
    ranked = sorted((r for r in rows if r.get(key)), key=lambda r: r[key], reverse=True)[:n]
    return [f"{r['caption'] or r['id']} — {r[key]}" + (f" ({r['link']})" if r.get("link") else "") for r in ranked] or ["маалымат жок"]


def build_report(rows, meta=None, today=None):
    """meta: {media_id: {"purpose":..,"content_type":..,"lang":..}} — өз постторубуздун тегдери."""
    meta = meta or {}
    today = today or dt.date.today().isoformat()
    L = [f"# Жумалык отчет — {today}", ""]
    for title, key in [("Эң көп көрүлгөн", "views"), ("Эң көп сакталган", "saved"), ("Эң көп бөлүшүлгөн", "shares"),
                       ("Жазылуучу алып келген", "follows"), ("Кардар кызыгуусу (комментарий-лид)", "leads")]:
        L += [f"## {title}"] + [f"{i}. {t}" for i, t in enumerate(_top(rows, key), 1)] + [""]
    L += ["_Лид — комментарийдеги баа/курс/номер суроолору; бул так атрибуция эмес, жакындоо көрсөткүч._", ""]
    # топтор боюнча орточо
    groups = {}
    for r in rows:
        tag = meta.get(r["id"], {})
        for g in (tag.get("purpose"), tag.get("lang"), r.get("type")):
            if g:
                groups.setdefault(g, []).append(r)
    avg = lambda rs, k: sum(x.get(k, 0) or 0 for x in rs) / max(1, len(rs))
    L.append("## Топтор боюнча орточо (views / saved / shares)")
    for g, rs in sorted(groups.items()):
        L.append(f"- {g} (n={len(rs)}): {avg(rs, 'views'):.0f} / {avg(rs, 'saved'):.1f} / {avg(rs, 'shares'):.1f}")
    L += ["", "## Кийинки жумага"]
    L += suggestions(rows, groups, avg)
    return "\n".join(L)


def suggestions(rows, groups, avg):
    out = []
    if len(rows) < 5:
        return ["- Маалымат аз (<5 пост): жыйынтык чыгарбай, туруктуу ритм менен жарыялоону улант."]
    best = max(groups.items(), key=lambda kv: avg(kv[1], "views"))
    out.append(f"- Эң жакшы көрүлгөн топ: «{best[0]}» — ушундай форматты көбөйт.")
    sv = max(groups.items(), key=lambda kv: avg(kv[1], "saved"))
    out.append(f"- Сактоо көп: «{sv[0]}» — практикалык/эсеп контентти көбөйт, аягына «сактап кой» чакырыгын кош.")
    low = [r for r in rows if (r.get("views") or 0) < avg(rows, "views") * 0.4]
    if low:
        out.append(f"- {len(low)} пост орточодон 60%+ төмөн: алардын биринчи 2 секундун (hook) кайра ойлон.")
    if not any(r.get("leads") for r in rows):
        out.append("- Лид жок: сатуу постторуна так CTA («Direct'ке «КУРС» деп жазыңыз») кош.")
    return out
