"""Текст менен иштөөчү жардамчы функциялар (сөз саны, сүйлөмдөр, окшоштук)."""

from __future__ import annotations

import math
import re

WORD_RE = re.compile(r"[\wЀ-ӿ]+(?:[-’'][\wЀ-ӿ]+)*", re.U)
SENT_RE = re.compile(r"(?<=[.!?…])\s+(?=[\"«(]?[A-ZА-ЯЁ0-9—–-])")


def words(text: str) -> list[str]:
    return WORD_RE.findall(text)


def word_count(text: str) -> int:
    return len(words(text))


def norm(text: str) -> str:
    t = text.lower().replace("ё", "е")
    return " ".join(words(t))


def sentences(text: str) -> list[str]:
    out = []
    for para in re.split(r"\n\s*\n|\n", text.strip()):
        para = para.strip()
        if para:
            out += [s.strip() for s in SENT_RE.split(para) if s.strip()]
    return out


def duplicate_sentences(text: str, min_words: int = 5) -> list[str]:
    seen, dups = set(), []
    for s in sentences(text):
        n = norm(s)
        if len(n.split()) < min_words:
            continue
        if n in seen:
            dups.append(s)
        seen.add(n)
    return dups


def shingles(text: str, n: int = 5) -> set[tuple[str, ...]]:
    w = norm(text).split()
    return {tuple(w[i:i + n]) for i in range(max(0, len(w) - n + 1))}


def jaccard(a: str, b: str, n: int = 5) -> float:
    sa, sb = shingles(a, n), shingles(b, n)
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def cosine(u: list[float], v: list[float]) -> float:
    dot = sum(x * y for x, y in zip(u, v))
    nu = math.sqrt(sum(x * x for x in u))
    nv = math.sqrt(sum(y * y for y in v))
    return dot / (nu * nv) if nu and nv else 0.0


def group_sentences(text: str, min_words: int = 16, max_words: int = 34) -> list[str]:
    """Сценарийди сахналарга бөлөт: сүйлөмдөрдүн чегинде, абзацты бузбастан."""
    groups: list[str] = []
    for para in [p.strip() for p in re.split(r"\n\s*\n|\n", text.strip()) if p.strip()]:
        cur: list[str] = []
        cur_n = 0
        for s in SENT_RE.split(para):
            s = s.strip()
            if not s:
                continue
            n = word_count(s)
            if cur and cur_n + n > max_words and cur_n >= min_words // 2:
                groups.append(" ".join(cur))
                cur, cur_n = [], 0
            cur.append(s)
            cur_n += n
        if cur:
            if groups and cur_n < min_words // 2 and word_count(groups[-1]) + cur_n <= max_words + 8:
                groups[-1] = groups[-1] + " " + " ".join(cur)  # абзацтын кичинекей калдыгы
            else:
                groups.append(" ".join(cur))
    return groups
