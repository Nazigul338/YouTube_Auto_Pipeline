"""Ветеринардык коопсуздук: дозасыз, диагнозсуз, булагы бар, ветеринарга багыттоочу.

ЭСКЕРТҮҮ: булактар домен боюнча ишенимдүү тизмеге каршы текшерилет, бирок
мазмуну автоматтык ТАСТЫКТАЛБАЙТ. Ошондуктан ден соолукка байланышкан пост ар дайым
`needs_vet_review=True` болот жана адам (сиз/ветеринар) бекитмейинче жарыяланбайт.
"""
from urllib.parse import urlparse

AI_NOTE = {
    "ky": "🎬 Айрым кадрлар — иллюстрация (AI менен түзүлгөн), чыныгы ферма видеосу эмес.",
    "ru": "🎬 Часть кадров — иллюстрации (созданы с помощью AI), это не съёмки реальной фермы.",
}


AI_VOICE_NOTE = {
    "ky": "🎙 Диктордун үнү AI менен түзүлгөн (үн ээсинин уруксаты менен).",
    "ru": "🎙 Голос диктора создан с помощью AI (с согласия владельца голоса).",
}


def _text(post):
    parts = [post.get("topic", ""), post.get("hook", ""), post.get("caption", ""), post.get("voiceover", "")]
    parts += [s.get("title", "") + " " + s.get("body", "") for s in post.get("slides", [])]
    parts += [f.get("text", "") for f in post.get("frames", [])]
    return " ".join(parts).lower()


def is_health(post, niche):
    t = niche.topics.get(post.get("topic_key", ""), {})
    if t.get("health"):
        return True
    txt = _text(post)
    return any(term in txt for term in niche.health_terms)


def trusted(url, niche):
    host = (urlparse(url or "").hostname or "").lower()
    for d in niche.trusted_domains:
        if (d.startswith(".") and host.endswith(d)) or host == d or host.endswith("." + d):
            return True
    return False


def ensure_disclaimers(post, niche):
    """Ден соолук поста үчүн ветеринар эскертүүсүн жана булактарды caption'ко кошот (кайталабайт)."""
    lang = post.get("lang", "ky")
    cap = post.get("caption", "")
    if is_health(post, niche):
        post["needs_vet_review"] = True
        if "ветеринар" not in cap.lower():
            cap += "\n\n" + niche.disclaimers[lang]
        srcs = [s for s in post.get("sources", []) if trusted(s.get("url"), niche)]
        if srcs and "Булак" not in cap and "Источник" not in cap:
            label = "Булактар" if lang == "ky" else "Источники"
            cap += f"\n{label}: " + ", ".join(urlparse(s["url"]).hostname for s in srcs)
    if any(s.get("source") == "ai" for s in post.get("shots", [])) and AI_NOTE[lang] not in cap:
        cap += "\n\n" + AI_NOTE[lang]
    if post.get("ai_voice") and AI_VOICE_NOTE[lang] not in cap:
        cap += "\n" + AI_VOICE_NOTE[lang]
    post["caption"] = cap
    return post


def check(post, niche):
    issues = []
    if not is_health(post, niche):
        return issues
    lang = post.get("lang", "ky")
    if "ветеринар" not in post.get("caption", "").lower():
        issues.append("Ден соолук постунда ветеринарга кайрылуу эскертүүсү жок")
    srcs = post.get("sources", [])
    if not srcs:
        issues.append("Ден соолук постунда ишенимдүү булак (sources) көрсөтүлгөн эмес")
    for s in srcs:
        if not (urlparse(s.get("url") or "").hostname):
            issues.append(f"Булак шилтеме эмес, жөн гана сүрөттөмө: «{(s.get('url') or '')[:60]}» — так сайт керек")
        elif not trusted(s.get("url"), niche):
            issues.append(f"Ишенимсиз/белгисиз булак домени: {urlparse(s.get('url') or '').hostname}")
    return issues
