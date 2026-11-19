"""Постту жарыялоо алдында автоматтык текшерүү (эрежелер бузулса — 'needs_fix')."""
import re

from . import config, safety


def _blob(post):
    texts = [post.get("hook", ""), post.get("hook_onscreen", ""), post.get("caption", ""), post.get("voiceover", "")]
    texts += [s.get("title", "") + " " + s.get("body", "") for s in post.get("slides", [])]
    texts += [f.get("text", "") + " " + " ".join(f.get("options", [])) for f in post.get("frames", [])]
    texts += [sh.get("onscreen", "") for sh in post.get("shots", [])]
    texts += [post.get("cta", {}).get("text", "")]
    blob = "\n".join(t for t in texts if t)
    for note in list(safety.AI_NOTE.values()) + list(safety.AI_VOICE_NOTE.values()) + list(safety.STOCK_NOTE.values()):      # милдеттүү AI ачыктоосу тыюу эмес
        blob = blob.replace(note, "")
    return blob


def lint_post(post, course=None, video_cfg=None):
    issues = []
    blob = _blob(post)
    for pat in config.BANNED_PATTERNS:
        m = re.search(pat, blob, flags=re.IGNORECASE)
        if m:
            issues.append(f"Тыюу салынган сөз/үлгү: «{m.group(0)}»")
    if not post.get("calc"):
        price_digits = re.sub(r"\D", "", str((course or {}).get("price") or ""))
        for pat in config.NUMERIC_PATTERNS:
            for m in re.finditer(pat, blob, flags=re.IGNORECASE):
                if price_digits and price_digits in re.sub(r"\D", "", m.group(0)):
                    continue  # course.json'дагы ырасталган баа
                issues.append(f"Ырасталбаган сан/баа: «{m.group(0)}» (course.json же calc аркылуу гана)")
    if len(post.get("caption", "")) > config.CAPTION_MAX:
        issues.append("Caption өтө узун")
    if len(post.get("hashtags", [])) > config.HASHTAGS_MAX:
        issues.append("Хэштег өтө көп")
    if not post.get("hook"):
        issues.append("Hook (биринчи сап) жок")
    fmt = post.get("format")
    if fmt == "carousel" and not (3 <= len(post.get("slides", [])) <= 10):
        issues.append("Каруселде 3–10 слайд болушу керек")
    if fmt == "story" and not (1 <= len(post.get("frames", [])) <= 7):
        issues.append("Story'де 1–7 кадр болушу керек")
    if fmt == "reel":
        if not post.get("voiceover"):
            issues.append("Reel үчүн voiceover жок")
        shots = post.get("shots", [])
        if len(shots) < 3 or not all(isinstance(s, dict) and s.get("visual") for s in shots):
            issues.append("Reel'де кеминде 3 кадр (visual менен) болушу керек")
        else:
            vc = video_cfg or {"min_seconds": 15, "max_seconds": 60}
            total = sum(float(s.get("duration", 0) or 0) for s in shots)
            if not (vc["min_seconds"] <= total <= vc["max_seconds"]):
                issues.append(f"Reel узактыгы {total:g}с — {vc['min_seconds']}–{vc['max_seconds']}с болушу керек")
        if not post.get("cta", {}).get("text"):
            issues.append("Комментарий/Direct'ке чакырык (cta) жок")
    return issues
