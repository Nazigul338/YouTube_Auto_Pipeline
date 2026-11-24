"""Cloudflare Workers AI — FLUX.1 [schnell] сүрөт жаратуу (2026-11-24, СЫНАК; негизги видео системасына кошулган эмес).

Ачкычтар GitHub Secrets'тен гана, environment variables аркылуу келет:
  CLOUDFLARE_API_TOKEN, CLOUDFLARE_ACCOUNT_ID
Коопсуздук:
  - токен жана account ID эч качан логго/катага чыкпайт (`_safe` аларды жашырат);
  - сүрөт суроосу КАЙТАЛАНБАЙТ (ката болсо дагы) — ашыкча колдонуу болбосун;
  - бир иштетүүдө `max_images` (демейки 1) сүрөттөн көп жаратылбайт;
  - акысыз күнүмдүк лимит (10 000 neuron) бүтсө — QuotaError, акы төлөнүүчү режимге өтүлбөйт.
"""
from __future__ import annotations

import base64
import json
import os
import urllib.error
import urllib.parse
import urllib.request

API = "https://api.cloudflare.com/client/v4"
FLUX_MODEL = "@cf/black-forest-labs/flux-1-schnell"
FLUX_MAX_STEPS = 8          # Cloudflare чеги; 4 — тез жана арзан демейки


class CloudflareError(RuntimeError):
    pass


class QuotaError(CloudflareError):
    """Акысыз күнүмдүк лимит бүттү (же 429) — кайра аракет жасалбайт."""


class CloudflareAI:
    def __init__(self, token: str, account_id: str, timeout: float = 120.0, max_images: int = 1):
        if not token or not account_id:
            raise CloudflareError("CLOUDFLARE_API_TOKEN же CLOUDFLARE_ACCOUNT_ID жок")
        self._token = token.strip()
        self._account = account_id.strip()
        self.timeout = timeout
        self.max_images = max_images
        self.images_made = 0

    @classmethod
    def from_env(cls, **kw) -> "CloudflareAI | None":
        tok, acc = os.environ.get("CLOUDFLARE_API_TOKEN", ""), os.environ.get("CLOUDFLARE_ACCOUNT_ID", "")
        return cls(tok, acc, **kw) if tok.strip() and acc.strip() else None

    # ── ички ──────────────────────────────────────────────────────────────
    def _safe(self, s: str) -> str:
        """Текстттен токенди жана account ID'ни өчүрөт (ката билдирүүлөрү үчүн)."""
        for secret in (self._token, self._account):
            if secret:
                s = s.replace(secret, "***")
        return s

    def _request(self, method: str, path: str, body: dict | None = None) -> tuple[int, dict]:
        url = API + path.replace("{account}", urllib.parse.quote(self._account, safe=""))
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method, headers={
            "Authorization": f"Bearer {self._token}", "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                return r.status, json.loads(r.read().decode() or "{}")
        except urllib.error.HTTPError as e:
            try:
                payload = json.loads(e.read().decode() or "{}")
            except Exception:
                payload = {}
            return e.code, payload
        except Exception as e:          # тармак катасы — URL (account ID) логго түшпөсүн
            raise CloudflareError(self._safe(f"тармак катасы: {type(e).__name__}")) from None

    def _errors(self, payload: dict) -> str:
        errs = payload.get("errors") or []
        txt = "; ".join(f"{x.get('code')}: {x.get('message')}" for x in errs if isinstance(x, dict))
        return self._safe(txt or "белгисиз ката")[:300]

    # ── API ───────────────────────────────────────────────────────────────
    def verify_token(self) -> dict:
        """Токен активдүүбү (user же account токени)."""
        for path in ("/user/tokens/verify", "/accounts/{account}/tokens/verify"):
            code, p = self._request("GET", path)
            if code == 200 and p.get("success"):
                return {"ok": p.get("result", {}).get("status") == "active",
                        "status": p.get("result", {}).get("status"), "kind": path.split("/")[1]}
        return {"ok": False, "status": None, "error": self._errors(p), "http": code}

    def model_info(self, name: str = FLUX_MODEL) -> dict:
        """Модель аккаунтта жеткиликтүүбү (Workers AI каталогунан)."""
        q = urllib.parse.quote(name.rsplit("/", 1)[-1])
        code, p = self._request("GET", f"/accounts/{{account}}/ai/models/search?search={q}&per_page=50")
        if code != 200 or not p.get("success"):
            return {"ok": False, "http": code, "error": self._errors(p)}
        found = next((m for m in p.get("result") or [] if m.get("name") == name), None)
        if not found:
            return {"ok": False, "http": code, "error": f"{name} каталогдо табылган жок"}
        return {"ok": True, "name": found.get("name"), "task": (found.get("task") or {}).get("name"),
                "description": (found.get("description") or "")[:200]}

    def generate_image(self, prompt: str, steps: int = 4, budget=None) -> bytes:
        """FLUX.1 schnell → JPEG байттары. Бир гана суроо, кайра аракетсиз.
        Модель схемасы prompt жана steps гана кабыл алат (run #45426693536: `seed` → 400 «unevaluated properties»).
        budget (cf_budget.Budget) берилсе: суроодон МУРУН акысыз лимит текшерилет (ашса BudgetExceeded),
        кийин чыгым журналга жазылат (ийгиликсиз суроо да)."""
        if self.images_made >= self.max_images:
            raise CloudflareError(f"чек: бир иштетүүдө {self.max_images} сүрөттөн ашык жаратылбайт")
        steps = max(1, min(FLUX_MAX_STEPS, int(steps)))
        est = None
        if budget is not None:
            from .cf_budget import estimate_neurons
            est = estimate_neurons(1024, 1024, steps)
            budget.check(est)                       # BudgetExceeded → суроо жиберилбейт
        body = {"prompt": prompt[:2048], "steps": steps}
        self.images_made += 1               # суроо жиберилгенге чейин эсептелет (ката болсо да)
        code, p = self._request("POST", f"/accounts/{{account}}/ai/run/{FLUX_MODEL}", body)
        ok = code == 200 and p.get("success") and (p.get("result") or {}).get("image")
        if budget is not None:
            budget.record(bool(ok), est, note="" if ok else f"HTTP {code}: {self._errors(p)}")
        if code == 429 or any(str(e.get("code")) in ("3036", "3040") for e in p.get("errors") or []
                              if isinstance(e, dict)):
            raise QuotaError(f"акысыз лимит/чек: {self._errors(p)}")
        if code != 200 or not p.get("success"):
            raise CloudflareError(f"HTTP {code}: {self._errors(p)}")
        img = (p.get("result") or {}).get("image")
        if not img:
            raise CloudflareError("жоопто сүрөт жок")
        return base64.b64decode(img)

    # ── колдонуу аналитикасы (акысыз GraphQL; сүрөт жаратпайт) ─────────────
    USAGE_QUERY = """query Usage($acc: string!, $start: Time!, $end: Time!) {
  viewer { accounts(filter: {accountTag: $acc}) {
    aiInferenceAdaptiveGroups(limit: 100, filter: {datetime_geq: $start, datetime_leq: $end}) {
      count
      sum { totalNeurons }
      dimensions { modelId }
    }
  } }
}"""

    def neuron_usage(self, start: str, end: str) -> dict:
        """Cloudflare GraphQL Analytics: [start, end] аралыгындагы neuron жана суроо саны (моделдер боюнча).
        Токенде «Account Analytics: Read» уруксаты жок болсо → {"ok": False, "error": ...}."""
        code, p = self._request("POST", "/graphql", {"query": self.USAGE_QUERY,
                                                     "variables": {"acc": self._account, "start": start, "end": end}})
        if code != 200 or p.get("errors") or not p.get("data"):
            errs = p.get("errors") or []
            msg = "; ".join(str(e.get("message")) for e in errs if isinstance(e, dict)) or f"HTTP {code}"
            return {"ok": False, "error": self._safe(msg)[:300]}
        try:
            groups = p["data"]["viewer"]["accounts"][0]["aiInferenceAdaptiveGroups"] or []
        except (KeyError, IndexError, TypeError):
            return {"ok": False, "error": "аналитика жообу күтүлгөн түрдө эмес"}
        by = {}
        for g in groups:
            m = (g.get("dimensions") or {}).get("modelId") or "?"
            by.setdefault(m, {"requests": 0, "neurons": 0.0})
            by[m]["requests"] += int(g.get("count") or 0)
            by[m]["neurons"] += float((g.get("sum") or {}).get("totalNeurons") or 0.0)
        return {"ok": True, "total": round(sum(v["neurons"] for v in by.values()), 3),
                "requests": sum(v["requests"] for v in by.values()), "by_model": by}
