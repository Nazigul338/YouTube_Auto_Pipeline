"""Фактылардын булагы жана текшерүүсү (англисче «Tech History» каналы, 2026-11-24).

Эреже: фактыларды ойлоп таппа. Gemini'нин Google Search куралы акысыз ачкычта 429 берет (PROJECT_STATUS 6-бөлүк),
ошондуктан булак = Wikipedia (ачкычсыз, GitHub Actions'та иштейт):

  1. pick_articles()  — Gemini темага тиешелүү 3–5 Wikipedia макаласынын атын сунуштайт, API аркылуу тастыкталат;
  2. fetch()          — макалалардын таза тексти (ар бири ≤ ARTICLE_CHARS);
  3. сценарий ОШОЛ тексттен гана жазылат (doc_script.py);
  4. verify()         — сценарийдеги ар бир факты (дата, сан, сумма, ысым, окуя) булактагы СӨЗМӨ-СӨЗ цитата менен
                        тастыкталат; цитата булакта жок болсо же сандар дал келбесе — «тастыкталган жок»;
  5. fix()            — тастыкталбаган сүйлөмдөр алынат/жумшартылат, андан кийин кайра текшерилет.
QA (s9 check_facts): тастыкталбаган факты 0 болушу МИЛДЕТТҮҮ.

Тесттерде тармак жок: ctx.services["wiki"] = объект (search(q) -> [title], extract(title) -> text).
"""

from __future__ import annotations

import json
import re
from typing import Any

API = "https://en.wikipedia.org/w/api.php"
# Wikipedia автоматтык клиенттен User-Agent сурайт; жеке маалымат (email ж.б.) жазылбайт.
USER_AGENT = "YouTubeAutoPipeline/1.0 (documentary script research; https://github.com)"
ARTICLE_CHARS = 24000
TOTAL_CHARS = 70000
MAX_ARTICLES = 5


class Wikipedia:
    """Чыныгы Wikipedia API (requests)."""

    def __init__(self, timeout: int = 30):
        import requests

        self.s = requests.Session()
        self.s.headers["User-Agent"] = USER_AGENT
        self.timeout = timeout

    def _get(self, **params) -> dict:
        params.update(format="json", formatversion=2)
        r = self.s.get(API, params=params, timeout=self.timeout)
        r.raise_for_status()
        return r.json()

    def search(self, q: str, limit: int = 3) -> list[str]:
        d = self._get(action="query", list="search", srsearch=q, srlimit=limit)
        return [x["title"] for x in d.get("query", {}).get("search", [])]

    def extract(self, title: str) -> tuple[str, str]:
        """(канондук аты, таза текст)."""
        d = self._get(action="query", prop="extracts", explaintext=1, redirects=1, titles=title)
        pages = d.get("query", {}).get("pages", [])
        if not pages or pages[0].get("missing"):
            return title, ""
        return pages[0].get("title", title), pages[0].get("extract", "") or ""


def client(ctx):
    return ctx.services.get("wiki") if getattr(ctx, "services", None) and "wiki" in ctx.services else Wikipedia()


def url_of(title: str) -> str:
    return "https://en.wikipedia.org/wiki/" + title.replace(" ", "_")


def clean_extract(text: str) -> str:
    """Шилтемелер/адабият бөлүмдөрү алынат (фактылар негизги тексттен гана)."""
    cut = re.search(r"\n==+\s*(See also|References|Notes|Further reading|External links|Bibliography)\s*==+",
                    text)
    text = text[:cut.start()] if cut else text
    return re.sub(r"\n{3,}", "\n\n", text).strip()


PICK_PROMPT = """You research a technology-history documentary for YouTube.
Topic: {topic}
List the English Wikipedia articles that together contain the facts needed for an accurate ~8-minute documentary
about this topic: the main subject first, then the key company/product/person/event articles.
Return JSON only: {{"articles": ["<exact English Wikipedia article title>", ...]}} — 3 to {n} titles."""


# Теманын «маанилүү сөздөрү» (булак темага тиешелүүбү): run #45408572177'де Gemini жооп бербей, «The rise and fall
# of Lotus 1-2-3» издөөсү «Lotus Esprit» (унаа) макаласын берген — ушундай булак эми четке кагылат.
STOP = {"the", "a", "an", "of", "and", "or", "in", "on", "to", "for", "how", "why", "what", "who", "when", "rise",
        "fall", "history", "story", "untold", "true", "inside", "behind", "that", "which", "was", "is", "it", "its",
        "from", "with", "by", "vs", "versus", "secret", "biggest", "first", "real", "life", "death", "end", "era"}
MIN_RELEVANCE = 0.6


def topic_terms(topic: str) -> list[str]:
    """Аттар жана сандар (баш тамгасы/чоң тамгасы же цифрасы бар сөз: Lotus, 1-2-3, IBM, iPhone); алар жок болсо —
    бардык маанилүү сөздөр. «born», «killed» сыяктуу жалпы сөздөр макалада жок болушу мүмкүн — эсептелбейт."""
    words = [w for w in re.findall(r"[\w][\w.+#-]*", topic) if w.lower() not in STOP]
    named = [w for w in words if any(c.isupper() or c.isdigit() for c in w)]
    pool = named or [w for w in words if len(w) > 2]
    return list(dict.fromkeys(w.lower() for w in pool))


def relevance(topic: str, title: str, text: str) -> float:
    """Теманын маанилүү сөздөрүнүн кайсы үлүшү макаланын атында/башында бар (0..1)."""
    terms = topic_terms(topic)
    if not terms:
        return 1.0
    hay = (title + " " + text[:8000]).lower()
    return sum(t in hay for t in terms) / len(terms)


def pick_articles(g, wiki, topic: str, log, n: int = MAX_ARTICLES) -> list[dict]:
    """[{title, url, text}] — бош болсо StageError чакыруучу тарапта.

    Gemini макала тизмесин бербесе — TransientError (кийин кайра): теманы «болжолдоп» издеген булак туура эмес
    болушу мүмкүн. Биринчи (негизги) макала темага тиешелүү болушу МИЛДЕТТҮҮ (relevance ≥ MIN_RELEVANCE)."""
    from .errors import TransientError

    try:
        r = g.json(PICK_PROMPT.format(topic=topic, n=n), purpose="sources_pick", temperature=0.2)
        wanted = [str(x) for x in (r.get("articles") if isinstance(r, dict) else r) or [] if str(x).strip()]
    except Exception as e:
        raise TransientError(f"Gemini Wikipedia макалаларын тандай алган жок ({type(e).__name__}) — кийин кайра")
    wanted = (wanted or [])[:n] + [topic]
    out, seen, total = [], set(), 0
    for w in wanted:
        if len(out) >= n or total >= TOTAL_CHARS:
            break
        try:
            hits = wiki.search(w, 1) or []
            if not hits:
                continue
            title, text = wiki.extract(hits[0])
        except Exception as e:
            log(f"   ⚠ Wikipedia «{w}»: {type(e).__name__}: {str(e)[:100]}")
            continue
        text = clean_extract(text)[:ARTICLE_CHARS]
        if title in seen or len(text) < 800:
            continue
        if not out and relevance(topic, title, text) < MIN_RELEVANCE:   # негизги булак темага тиешелүү эмес
            log(f"   ⚠ «{title}» темага тиешелүү эмес (relevance {relevance(topic, title, text):.2f}) — өткөрүлдү")
            continue
        seen.add(title)
        text = text[:max(0, TOTAL_CHARS - total)]
        total += len(text)
        out.append({"title": title, "url": url_of(title), "text": text})
        log(f"   📚 Булак: {title} ({len(text)} белги)")
    return out


def sources_block(arts: list[dict]) -> str:
    return "\n\n".join(f"=== SOURCE {i + 1}: {a['title']} ===\n{a['text']}" for i, a in enumerate(arts))


# ----------------------------------------------------------------------------------------- факты текшерүү
VERIFY_PROMPT = """You are a strict fact-checker for a history documentary. Below are SOURCES (Wikipedia text) and a
SCRIPT. Find EVERY factual claim in the script: dates and years, numbers, prices, sales, amounts, names of people,
companies and products, places, "first/largest/only" claims, who did what, and quotes.
For each claim decide if the SOURCES directly support it.

Return JSON only:
{{"claims": [{{"sentence": "<the script sentence, VERBATIM>",
  "claim": "<the factual claim in a few words>",
  "supported": <true/false>,
  "source": <source number or 0>,
  "quote": "<VERBATIM quote (8-40 words) from that SOURCE that proves the claim; empty if unsupported>"}}]}}
Rules: a claim is supported ONLY if the quote states it (same numbers, same names, same year). General storytelling
without facts ("Imagine a small office…", opinions, transitions) is not a claim — skip it.

SOURCES:
{sources}

SCRIPT:
{script}"""


def _n(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w$%.,\s-]", " ", s.lower())).strip()


NUM_RE = re.compile(r"\d[\d,.]*")


def numbers(s: str) -> set[str]:
    return {x.replace(",", "").rstrip(".") for x in NUM_RE.findall(s)}


def quote_in_sources(quote: str, arts: list[dict]) -> bool:
    """Цитата булакта чындап барбы: толук дал келүү же маанилүү сөздөрүнүн ≥85% катар бир сүйлөмдө."""
    q = _n(quote)
    if len(q.split()) < 4:
        return False
    for a in arts:
        t = _n(a["text"])
        if q in t:
            return True
    qw = [w for w in q.split() if len(w) >= 4 or w[:1].isdigit()]
    if len(qw) < 3:
        return False
    for a in arts:
        for sent in re.split(r"(?<=[.!?])\s+", a["text"]):
            sw = set(_n(sent).split())
            if sum(w in sw for w in qw) / len(qw) >= 0.85:
                return True
    return False


def check_claim(c: dict, arts: list[dict]) -> tuple[bool, str]:
    """Gemini «supported» десе да — цитата булакта жок же сценарийдеги сан цитатада жок болсо, кабыл алынбайт."""
    if not c.get("supported"):
        return False, "булакта жок (Gemini)"
    quote = str(c.get("quote") or "")
    if not quote_in_sources(quote, arts):
        return False, "цитата булактан табылган жок"
    missing = {x for x in numbers(c.get("claim", "")) | numbers(c.get("sentence", ""))
               if len(x) >= 2} - numbers(quote)
    # сценарийдеги сан цитатада жок болсо (мис. 1981 ордуна 1983) — тастыкталган жок; бирок сөз менен жазылган
    # сандар («three») жана тексттеги убакыт белгилери (мис. «8 minutes») Gemini'дин claim'инде гана текшерилет
    claim_nums = {x for x in numbers(c.get("claim", "")) if len(x) >= 2}
    if claim_nums - numbers(quote):
        return False, f"сан цитатада жок: {sorted(claim_nums - numbers(quote))[:3]}"
    return True, "ok" if not missing else f"ok (сүйлөмдөгү башка сандар: {sorted(missing)[:3]})"


def verify(g, script: str, arts: list[dict], log) -> dict:
    """→ {claims: [...+ok, why], unsupported: [...], n, n_ok, source}."""
    try:
        r = g.json(VERIFY_PROMPT.format(sources=sources_block(arts), script=script),
                   purpose="fact_verify", temperature=0.1)
    except Exception as e:
        log(f"   ⚠ Факты текшерүү жооп берген жок: {type(e).__name__}")
        return {"source": "none", "claims": [], "unsupported": [], "n": 0, "n_ok": 0,
                "error": f"{type(e).__name__}: {str(e)[:150]}"}
    claims = r.get("claims") if isinstance(r, dict) else r
    out = []
    for c in claims if isinstance(claims, list) else []:
        if not isinstance(c, dict) or not str(c.get("sentence") or c.get("claim") or "").strip():
            continue
        ok, why = check_claim(c, arts)
        out.append({"sentence": str(c.get("sentence", ""))[:400], "claim": str(c.get("claim", ""))[:200],
                    "source": c.get("source"), "quote": str(c.get("quote", ""))[:400], "ok": ok, "why": why})
    bad = [c for c in out if not c["ok"]]
    return {"source": "gemini", "claims": out, "unsupported": bad, "n": len(out), "n_ok": len(out) - len(bad)}


FIX_PROMPT = """You edit a technology-history documentary script. The sentences below contain claims that the SOURCES
do NOT support. For each one: correct it using ONLY the SOURCES (exact numbers, names, years), or remove the unsupported
detail, or rewrite the sentence without that fact. Keep everything else word for word, keep the length and the flow.
Do NOT add any new facts that are not in the SOURCES. Return only the full corrected script.

UNSUPPORTED:
{bad}

SOURCES:
{sources}

SCRIPT:
{script}"""


def fix(g, script: str, report: dict, arts: list[dict]) -> str:
    bad = "\n".join(f"- «{c['sentence']}» → {c['claim']} ({c['why']})" for c in report["unsupported"][:25])
    return g.text(FIX_PROMPT.format(bad=bad, sources=sources_block(arts), script=script),
                  purpose="fact_fix", temperature=0.3).strip()


def dump(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=1)
