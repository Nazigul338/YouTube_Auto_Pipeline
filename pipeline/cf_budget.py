"""Cloudflare Workers AI — акысыз күнүмдүк лимитти коргоо жана сүрөт бюджети (2026-11-24).

Акысыз лимит: 10 000 neuron / күн, UTC 00:00'дө жаңырат. Акы төлөнүүчү колдонууга ӨТҮЛБӨЙТ:
  - коопсуздук резерви 10% → иш жүзүндө 9 000 neuron'дон ашпайт;
  - ар бир сүрөттөн МУРУН бюджет текшерилет (колдонулганы + бул сүрөттүн баасы ≤ 9 000), болбосо BudgetExceeded;
  - колдонулган сан = max(жергиликтүү журнал, Cloudflare аналитикасы) — кайсынысы көп болсо ошол (коопсуз жак);
  - 90% колдонулганда эскертүү; ката болсо кайра аракет жок (cloudflare_ai.generate_image).

Чыгым эки жол менен эсептелет:
  1) ЧЫНЫГЫ — Cloudflare GraphQL Analytics (`aiInferenceAdaptiveGroups.sum.totalNeurons`), эгер токенде
     «Account Analytics: Read» уруксаты болсо. Аналитика бир нече мүнөт кечигет.
  2) БААЛОО — Cloudflare'дин жарыяланган баасы боюнча (FLUX.1 schnell: 512×512 плитка $0.0000528, кадам
     $0.0001056; 1 000 neuron = $0.011) → 4.8 neuron/плитка + 9.6 neuron/кадам. 1024×1024, 4 кадам ≈ 57.6.
  Чыныгы өлчөм болсо ал колдонулат; жок болсо баалоо экени отчетто ачык жазылат.

Журнал (тарых күндөр боюнча, эч качан өчүрүлбөйт): Drive `YouTube_Auto/Logs/cloudflare_ai_usage.json`
(жергиликтүү иштетүүдө — `work/cloudflare_ai_usage.json`).
"""
from __future__ import annotations

import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path

DAILY_LIMIT = 10_000
SAFETY_RESERVE = 0.10
WARN_AT = 0.90              # 10% резерв менен 90% = токтоо чеги (9 000); эрте эскертүү 9 000'дин 90%ында (8 100)
TILE_NEURONS = 0.0000528 / 0.011 * 1000      # 4.8 — 512×512 плитка
STEP_NEURONS = 0.0001056 / 0.011 * 1000      # 9.6 — бир кадам
LEDGER_NAME = "cloudflare_ai_usage.json"
DASHBOARD_NAME = "cloudflare_ai_dashboard.md"
TEST_MAX_IMAGES = 5                          # биринчи тестте 5 сүрөттөн ашпайт


class BudgetExceeded(RuntimeError):
    """Бул сүрөт акысыз лимиттин коопсуз бөлүгүнөн ашат — генерация токтотулат."""


def estimate_neurons(width: int = 1024, height: int = 1024, steps: int = 4) -> float:
    tiles = math.ceil(width / 512) * math.ceil(height / 512)
    return round(tiles * TILE_NEURONS + steps * STEP_NEURONS, 2)


def utc_day(now: datetime | None = None) -> str:
    return (now or datetime.now(timezone.utc)).strftime("%Y-%m-%d")


def next_reset(now: datetime | None = None) -> str:
    n = now or datetime.now(timezone.utc)
    return (datetime(n.year, n.month, n.day, tzinfo=timezone.utc) + timedelta(days=1)).strftime("%Y-%m-%d 00:00 UTC")


class Budget:
    def __init__(self, data: dict | None = None, model: str = "@cf/black-forest-labs/flux-1-schnell",
                 now=None):
        self.data = data if isinstance(data, dict) else {}
        self.data.setdefault("days", {})
        self.data["daily_limit"] = DAILY_LIMIT
        self.data["safety_reserve"] = SAFETY_RESERVE
        self.model = model
        self._now = now or (lambda: datetime.now(timezone.utc))

    # ── күн ────────────────────────────────────────────────────────────────
    @property
    def today(self) -> str:
        return utc_day(self._now())

    def day(self, d: str | None = None) -> dict:
        """Күндүн жазуусу (UTC 00:00'дө жаңы күн — эскилери тарых катары калат)."""
        return self.data["days"].setdefault(d or self.today, {
            "model": self.model, "requests": [], "images": 0, "local_neurons": 0.0,
            "api_neurons": None, "api_checked_at": None})

    # ── эсеп ───────────────────────────────────────────────────────────────
    def used(self, d: str | None = None) -> float:
        x = self.day(d)
        return max(float(x["local_neurons"]), float(x["api_neurons"] or 0.0))

    def avg_per_image(self, d: str | None = None) -> tuple[float, str]:
        """Орточо neuron/сүрөт: чыныгы өлчөнгөндөрдөн (бар болсо), болбосо баалоо."""
        reqs = [r for days in self.data["days"].values() for r in days.get("requests", []) if r.get("ok")]
        real = [r["measured"] for r in reqs if r.get("measured")]
        if real:
            return round(sum(real) / len(real), 2), "чыныгы (Cloudflare аналитикасы)"
        return estimate_neurons(), "баалоо (жарыяланган баа)"

    def capacity(self, d: str | None = None) -> dict:
        used = self.used(d)
        avg, src = self.avg_per_image(d)
        available = DAILY_LIMIT - used - DAILY_LIMIT * SAFETY_RESERVE
        return {"available": max(0.0, round(available, 2)),
                "max_images": max(0, math.floor(available / avg)) if avg > 0 else 0,
                "avg": avg, "avg_source": src}

    def check(self, est: float) -> str | None:
        """Сүрөттөн МУРУН: лимиттен ашса BudgetExceeded; 90%га жакын болсо эскертүү тексти."""
        used = self.used()
        hard = DAILY_LIMIT * (1 - SAFETY_RESERVE)
        if used + est > hard:
            raise BudgetExceeded(f"акысыз лимит коргоосу: колдонулду {used:.0f} + бул сүрөт ~{est:.0f} > "
                                 f"{hard:.0f} neuron (10 000 − 10% резерв) — генерация токтотулду, "
                                 f"жаңыруу {next_reset(self._now())}")
        if used + est >= hard * WARN_AT:
            return (f"⚠️ акысыз лимиттин {100 * (used + est) / DAILY_LIMIT:.0f}% колдонулду — "
                    f"{hard:.0f} neuron'го (90%) жеткенде генерация токтойт")
        return None

    def record(self, ok: bool, est: float, measured: float | None = None, note: str = "") -> dict:
        x = self.day()
        rec = {"t": self._now().strftime("%H:%M:%S"), "ok": ok, "estimate": est,
               "measured": measured, "note": note[:200]}
        x["requests"].append(rec)
        if ok:
            x["images"] += 1
            x["local_neurons"] = round(x["local_neurons"] + (measured or est), 2)
        return rec

    def set_measured(self, rec: dict, measured: float) -> None:
        """Аналитика кечигип келгенде: жазуунун чыныгы чыгымын коюп, жергиликтүү эсепти оңдойт."""
        x = self.day()
        old = rec.get("measured") or rec["estimate"]
        rec["measured"] = round(measured, 3)
        x["local_neurons"] = round(x["local_neurons"] - old + measured, 3)

    def set_api(self, neurons: float | None) -> None:
        x = self.day()
        x["api_neurons"] = None if neurons is None else round(float(neurons), 3)
        x["api_checked_at"] = self._now().strftime("%Y-%m-%dT%H:%M:%SZ")

    # ── отчет ──────────────────────────────────────────────────────────────
    def report(self, d: str | None = None) -> dict:
        d = d or self.today
        x = self.day(d)
        cap = self.capacity(d)
        used = self.used(d)
        return {"date": d, "reset": next_reset(datetime.strptime(d, "%Y-%m-%d").replace(tzinfo=timezone.utc)),
                "model": x.get("model", self.model), "daily_limit": DAILY_LIMIT,
                "used": round(used, 2), "remaining": round(max(0.0, DAILY_LIMIT - used), 2),
                "used_pct": round(100 * used / DAILY_LIMIT, 2),
                "used_source": ("Cloudflare аналитикасы" if x.get("api_neurons") is not None
                                and x["api_neurons"] >= x["local_neurons"] else "жергиликтүү журнал"),
                "images": x["images"], "avg_per_image": cap["avg"], "avg_source": cap["avg_source"],
                "safety_reserve": int(DAILY_LIMIT * SAFETY_RESERVE),
                "available_for_images": cap["available"], "estimated_remaining_images": cap["max_images"],
                "warning": used >= DAILY_LIMIT * (1 - SAFETY_RESERVE) * WARN_AT}

    def to_json(self) -> dict:
        self.data["updated"] = self._now().strftime("%Y-%m-%dT%H:%M:%SZ")
        return self.data


def dashboard_md(rep: dict, video: dict | None = None, history: dict | None = None) -> str:
    bar = "█" * int(rep["used_pct"] // 5) + "░" * (20 - int(rep["used_pct"] // 5))
    lines = [
        "## ☁️ Cloudflare Workers AI — акысыз лимит",
        "",
        f"| Көрсөткүч | Маани |", "|---|---|",
        f"| Күн (UTC) | {rep['date']} (жаңыруу {rep['reset']}) |",
        f"| Модель | `{rep['model']}` |",
        f"| Бүгүнкү акысыз лимит | {rep['daily_limit']:,} neuron |",
        f"| Колдонулду | {rep['used']:,} neuron ({rep['used_source']}) |",
        f"| Калды | {rep['remaining']:,} neuron |",
        f"| Колдонулушу | {rep['used_pct']}% `{bar}` |",
        f"| Бүгүн жаралган сүрөт | {rep['images']} |",
        f"| Орточо neuron/сүрөт | {rep['avg_per_image']} ({rep['avg_source']}) |",
        f"| Коопсуздук резерви | {rep['safety_reserve']:,} neuron (10%) |",
        f"| Дагы жаратууга болот | **{rep['estimated_remaining_images']} сүрөт** |",
    ]
    if rep["warning"]:
        lines += ["", "> ⚠️ Коопсуз бюджеттин 90%ы колдонулду — 9 000 neuron'го (лимиттин 90%) жеткенде генерация токтойт."]
    if video:
        lines += ["", "### 8 мүнөттүк видео үчүн план",
                  f"- Толук сүрөт менен жабуу үчүн: {video['full_coverage']} сүрөт (ар бири ~{video['hold']} сек, кыймыл менен)",
                  f"- Бүгүнкү бюджет менен: **{video['images']} сүрөт**; калган {video['stock_sec']:.0f} сек — Pixabay",
                  "- Бөлүштүрүү (маанилүүсү биринчи): " + ", ".join(f"{k} {v}" for k, v in video["by_section"].items())]
    if history:
        lines += ["", "### Тарых", "| Күн | Сүрөт | Neuron |", "|---|---|---|"]
        for d, x in sorted(history.items())[-14:]:
            lines.append(f"| {d} | {x.get('images', 0)} | "
                         f"{max(x.get('local_neurons') or 0, x.get('api_neurons') or 0):.1f} |")
    return "\n".join(lines) + "\n"


# ── 8 мүнөттүк видео үчүн сүрөт планы ─────────────────────────────────────
# Маанилүүлүк ирети: hook (алгачкы 3 сек) → окуя → финал → маани → проблема → себептер → практика.
SECTION_PRIORITY = ["hook", "story", "finale", "meaning", "problem", "causes", "practice"]
DEFAULT_SHARES = {"hook": 0.05, "problem": 0.10, "causes": 0.20, "story": 0.18, "meaning": 0.12,
                  "practice": 0.27, "finale": 0.08}


def plan_video_images(duration: float, max_images: int, hold: float = 7.0,
                      shares: dict | None = None) -> dict:
    """Видео үчүн сүрөт санын бөлүштүрөт. Ар сүрөт ~hold сек (zoom/pan кыймылы менен) колдонулат —
    ар 3–4 сек жаңы сүрөт талап кылынбайт. Бюджет жетпесе маанилүү бөлүктөргө биринчи берилет,
    калганы Pixabay клиптери менен жабылат. Сценарийге дал келбеген сүрөт колдонулбайт — бул сан ЖОГОРКУ чек,
    ар сүрөт s5'тин AI маани баалоосунан өтүшү керек."""
    shares = shares or DEFAULT_SHARES
    need = {k: max(1, math.ceil(duration * shares.get(k, 0) / hold)) for k in SECTION_PRIORITY if shares.get(k)}
    left, by = max(0, int(max_images)), {}
    for k in SECTION_PRIORITY:
        if k in need:
            by[k] = min(need[k], left)
            left -= by[k]
    used = sum(by.values())
    return {"duration": duration, "hold": hold, "full_coverage": sum(need.values()), "images": used,
            "by_section": by, "stock_sec": max(0.0, duration - used * hold)}


def shares_from_format(fmt: dict) -> dict | None:
    """script/format.json'дон бөлүктөрдүн чыныгы үлүшү (бар болсо)."""
    info = (fmt or {}).get("info") or {}
    n = info.get("n") or 0
    if not n or not info.get("sections"):
        return None
    return {s["section"]: (s["w1"] - s["w0"]) / n for s in info["sections"]}


# ── журналды сактоо (Drive же жергиликтүү) ───────────────────────────────
class LedgerStore:
    def __init__(self, drive=None, root: str = "YouTube_Auto", local: Path | None = None):
        self.drive, self.root = drive, root
        self.local = local or Path("work") / LEDGER_NAME
        self._logs = None

    def _logs_id(self):
        if self.drive and self._logs is None:
            self._logs = self.drive.find_path(self.root, "Logs")
        return self._logs

    def load(self) -> dict:
        if self._logs_id():
            item = self.drive.find_file(LEDGER_NAME, self._logs)
            if item:
                import tempfile
                with tempfile.TemporaryDirectory() as d:
                    p = self.drive.download_file(item["id"], Path(d) / LEDGER_NAME)
                    return json.loads(p.read_text(encoding="utf-8"))
            return {}
        return json.loads(self.local.read_text(encoding="utf-8")) if self.local.exists() else {}

    def save(self, data: dict, dashboard: str | None = None) -> str | None:
        self.local.parent.mkdir(parents=True, exist_ok=True)
        self.local.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        link = None
        if self._logs_id():
            self.drive.write_json(LEDGER_NAME, self._logs, data)
            if dashboard:
                p = self.local.with_name(DASHBOARD_NAME)
                p.write_text(dashboard, encoding="utf-8")
                fid = self.drive.put_file(p, self._logs, DASHBOARD_NAME)
                link = f"https://drive.google.com/file/d/{fid}/view" if fid else None
        return link
