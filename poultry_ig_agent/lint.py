"""Постту жарыялоо алдында автоматтык текшерүү (эрежелер бузулса — 'needs_fix')."""
import re

import config


def lint_post(post):
    issues = []
    texts = [post.get("hook", ""), post.get("caption", "")]
    texts += [s.get("title", "") + " " + s.get("body", "") for s in post.get("slides", [])]
    texts += [post.get("voiceover", "")]
    blob = "\n".join(texts)
    for pat in config.BANNED_PATTERNS:
        m = re.search(pat, blob, flags=re.IGNORECASE)
        if m:
            issues.append(f"Тыюу салынган сөз/үлгү: «{m.group(0)}»")
    if len(post.get("caption", "")) > config.CAPTION_MAX:
        issues.append("Caption өтө узун")
    tags = post.get("hashtags", [])
    if len(tags) > config.HASHTAGS_MAX:
        issues.append("Хэштег өтө көп")
    if post.get("format") == "carousel" and not (3 <= len(post.get("slides", [])) <= 10):
        issues.append("Каруселде 3–10 слайд болушу керек")
    if post.get("format") == "reel" and not post.get("voiceover"):
        issues.append("Reel үчүн voiceover жок")
    if not post.get("hook"):
        issues.append("Hook (биринчи сап) жок")
    return issues
