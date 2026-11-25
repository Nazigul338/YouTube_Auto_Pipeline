"""script/meta.json'до hook маалыматы жок болгон ЭСКИ долбоорлор үчүн толуктоо (2026-11-25, Video_003).

Эски долбоордун meta.json'ында hook / hook_type / hook_card жок болчу → s6 hook карточкасын жасаган эмес, s9 «hook жок» деди.
Бар маанилерге ТИЙИЛБЕЙТ (setdefault). Карточка тексти: VIDEO_HOOK_CARD (workflow'до колдонуучу берет), болбосо сценарийдин
биринчи сүйлөмүнүн алгачкы 5 сөзү (ыңгайсыз болушу мүмкүн — ошондуктан кол менен берүү сунушталат).
"""
from __future__ import annotations

import json
import os
import re


def first_sentence(text: str) -> str:
    return re.split(r"(?<=[.!?…])\s+", text.strip(), maxsplit=1)[0] if text.strip() else ""


def ensure(ctx, log=None) -> dict:
    p = ctx.path("script", "meta.json")
    try:
        meta = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        meta = {}
    if meta.get("hook") and meta.get("hook_type") and meta.get("hook_card"):
        return meta
    try:
        text = ctx.path("script", "script.txt").read_text(encoding="utf-8")
    except Exception:
        return meta
    first = first_sentence(text)[:240]
    if not first:
        return meta
    card = (os.environ.get("VIDEO_HOOK_CARD") or "").strip()
    meta.setdefault("hook", first)
    meta.setdefault("hook_type", "question" if "?" in first else "statement")
    meta.setdefault("hook_card", card or " ".join(first.split()[:5]).upper())
    if card:
        meta["hook_card"] = card.upper()      # колдонуучу ачык берсе — ал артыкчылыктуу
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    if log:
        log(f"   🪝 Hook маалыматы толукталды (эски долбоор): «{meta['hook_card']}» ({meta['hook_type']})")
    return meta
