"""Cloudflare Workers AI — сүрөт жаратуу, бир нече модель (СЫНАК, 2026-11-28; видео системасына кошулган ЭМЕС).

`cloudflare_ai.py` (FLUX.1 schnell клиенти, 2026-11-24) өзгөрбөйт; бул модуль анын туташуусун колдонуп:
  - аккаунттагы бардык Text-to-Image моделдерин API'ден окуйт (аты, сүрөттөмө, баа/касиеттер — Cloudflare'дин өзү
    кайтарганындай; документация сайты бул чөйрөдөн жабык болгондуктан API — негизги булак);
  - моделдин input-схемасына жараша суроо түзөт (JSON же multipart/form-data) жана жоопту (base64 JSON же
    чийки PNG/JPEG) сүрөт байттарына айлантат;
  - бир суроо, кайра аракетсиз; күнүмдүк акысыз лимит `cf_budget` менен суроодон МУРУН текшерилет.
Коопсуздук: токен жана account ID логго/файлга жазылбайт (`CloudflareAI._safe`).
"""
from __future__ import annotations

import base64
import json
import urllib.error
import urllib.parse
import urllib.request
import uuid

from .cloudflare_ai import API, CloudflareAI, CloudflareError, QuotaError

# «Реалдуу кинематографиялык» сүрөт үчүн тандоо ирети (аккаунтта бар биринчиси алынат).
PREFERRED = (
    "@cf/black-forest-labs/flux-2-dev",
    "@cf/leonardo/lucid-origin",
    "@cf/leonardo/phoenix-1.0",
    "@cf/black-forest-labs/flux-1-schnell",
)
# Баасы белгисиз моделдин суроосуна бюджетте коюлган коопсуз (чоң) баалоо, neuron.
UNKNOWN_COST = 600.0


def _request_raw(cf: CloudflareAI, method: str, path: str, data: bytes | None, ctype: str | None
                 ) -> tuple[int, str, bytes]:
    """→ (HTTP код, Content-Type, байттар). Тармак катасында URL/секрет чыкпайт."""
    url = API + path.replace("{account}", urllib.parse.quote(cf._account, safe=""))
    headers = {"Authorization": f"Bearer {cf._token}"}
    if ctype:
        headers["Content-Type"] = ctype
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=cf.timeout) as r:
            return r.status, r.headers.get("Content-Type", ""), r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.headers.get("Content-Type", "") if e.headers else "", e.read() or b""
    except Exception as e:
        raise CloudflareError(cf._safe(f"тармак катасы: {type(e).__name__}")) from None


def list_image_models(cf: CloudflareAI) -> dict:
    """Аккаунттагы Text-to-Image моделдери: [{name, description, properties}]."""
    code, p = cf._request("GET", "/accounts/{account}/ai/models/search?task=Text-to-Image&per_page=100")
    if code != 200 or not p.get("success"):
        return {"ok": False, "http": code, "error": cf._errors(p)}
    out = []
    for m in p.get("result") or []:
        props = {str(x.get("property_id")): x.get("value") for x in (m.get("properties") or []) if isinstance(x, dict)}
        out.append({"name": m.get("name"), "description": (m.get("description") or "")[:240], "properties": props})
    return {"ok": True, "models": sorted(out, key=lambda m: m["name"] or "")}


def model_schema(cf: CloudflareAI, model: str) -> dict:
    code, p = cf._request("GET", "/accounts/{account}/ai/models/schema?model=" + urllib.parse.quote(model, safe=""))
    if code != 200 or not p.get("success"):
        return {}
    return p.get("result") or {}


def input_spec(schema: dict) -> dict:
    """Схемадан: {"multipart": bool, "props": {аты: {type, maximum, minimum, default}}}."""
    inp = schema.get("input") or {}
    multipart = "multipart" in (inp.get("properties") or {}) or "multipart" in inp
    props = inp.get("properties") or {}
    if multipart:
        mp = (inp.get("properties") or {}).get("multipart") or inp.get("multipart") or {}
        props = ((mp.get("properties") or {}).get("body") or {}).get("properties") or mp.get("properties") or props
    return {"multipart": multipart,
            "props": {k: {kk: v.get(kk) for kk in ("type", "maximum", "minimum", "default")}
                      for k, v in props.items() if isinstance(v, dict)}}


def build_inputs(spec: dict, prompt: str, width: int, height: int, steps: int | None) -> dict:
    """Схема кабыл алган талааларды гана толтурат (run #45426693536: ашыкча `seed` → 400)."""
    props = spec.get("props") or {}
    body: dict = {"prompt": prompt[:2048]}

    def fit(name, val):
        lim = props.get(name) or {}
        if lim.get("maximum") is not None:
            val = min(val, lim["maximum"])
        if lim.get("minimum") is not None:
            val = max(val, lim["minimum"])
        return int(val)

    if "width" in props:
        body["width"] = fit("width", width)
    if "height" in props:
        body["height"] = fit("height", height)
    if steps is not None:
        for k in ("steps", "num_steps"):
            if k in props:
                body[k] = fit(k, steps)
                break
    return body


def _multipart(fields: dict) -> tuple[bytes, str]:
    b = uuid.uuid4().hex
    parts = []
    for k, v in fields.items():
        parts.append(f'--{b}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode())
    return b"".join(parts) + f"--{b}--\r\n".encode(), f"multipart/form-data; boundary={b}"


def decode_image(code: int, ctype: str, data: bytes, cf: CloudflareAI) -> bytes:
    if code == 200 and ctype.startswith("image/"):
        return data
    try:
        p = json.loads(data.decode() or "{}")
    except Exception:
        p = {}
    if code == 429 or any(str(e.get("code")) in ("3036", "3040") for e in p.get("errors") or [] if isinstance(e, dict)):
        raise QuotaError(f"акысыз лимит/чек: {cf._errors(p)}")
    if code != 200 or not p.get("success", True):
        raise CloudflareError(f"HTTP {code}: {cf._errors(p)}")
    img = (p.get("result") or {}).get("image") if isinstance(p.get("result"), dict) else None
    if not img:
        raise CloudflareError("жоопто сүрөт жок")
    return base64.b64decode(img)


def generate(cf: CloudflareAI, model: str, prompt: str, *, width: int = 1344, height: int = 768,
             steps: int | None = None, spec: dict | None = None, budget=None, est: float = UNKNOWN_COST) -> tuple[bytes, dict]:
    """Бир сүрөт, кайра аракетсиз. → (байттар, жиберилген параметрлер). budget берилсе — суроодон МУРУН текшерүү."""
    if cf.images_made >= cf.max_images:
        raise CloudflareError(f"чек: бир иштетүүдө {cf.max_images} сүрөттөн ашык жаратылбайт")
    spec = spec if spec is not None else input_spec(model_schema(cf, model))
    inputs = build_inputs(spec, prompt, width, height, steps)
    if budget is not None:
        budget.check(est)                                   # BudgetExceeded → суроо жиберилбейт
    if spec.get("multipart"):
        data, ctype = _multipart(inputs)
    else:
        data, ctype = json.dumps(inputs).encode(), "application/json"
    cf.images_made += 1
    code, rtype, raw = _request_raw(cf, "POST", f"/accounts/{{account}}/ai/run/{model}", data, ctype)
    try:
        img = decode_image(code, rtype, raw, cf)
    except CloudflareError as e:
        if budget is not None:
            budget.record(False, est, note=str(e))
        raise
    if budget is not None:
        budget.record(True, est)
    return img, {k: v for k, v in inputs.items() if k != "prompt"}


def pick_model(available: list[str], wanted: str = "") -> str | None:
    if wanted:
        return wanted if wanted in available else None
    return next((m for m in PREFERRED if m in available), None)


def image_size(data: bytes) -> tuple[int, int] | None:
    """PNG же JPEG өлчөмү."""
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")
    from .cf_probe import jpeg_size
    return jpeg_size(data)
