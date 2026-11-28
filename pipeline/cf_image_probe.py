"""Cloudflare Workers AI — секреттерди/уруксаттарды/моделдерди текшерүү жана 1 кинематографиялык тест сүрөт.

Режимдер (env CF_MODE):
  models — сүрөт ЖАРАТПАЙТ (бекер): токен, account ID, Workers AI окуу уруксаты, аналитика уруксаты,
           аккаунттагы бардык Text-to-Image моделдери (баасы/касиеттери API'ден), тандалган моделдердин схемасы;
  image  — ошол текшерүүлөр + 1 сүрөт (CF_MODEL же PREFERRED ирети), бюджет суроодон МУРУН текшерилет,
           чыныгы чыгым аналитикадан өлчөнөт, сүрөт + метаберилиштер Drive'га:
           YouTube_Auto_TEST/Projects/_cloudflare_ai_test/ (бар файлдын үстүнөн жазылбайт).
Видео системасына (make_video) ТИЙБЕЙТ. Секреттердин маанилери эч жерге чыкпайт.
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from . import cf_budget as cb
from . import cf_images as ci
from .cloudflare_ai import FLUX_MODEL, CloudflareAI, CloudflareError, QuotaError

TEST_FOLDER = ("YouTube_Auto_TEST", "Projects", "_cloudflare_ai_test")

PROMPT = ("Cinematic film still, 35mm anamorphic, a young woman sitting alone at a kitchen table late at night, "
          "holding a handwritten thank-you card from her team, a faint uneasy half-smile, eyes looking away from "
          "the card, warm tungsten pendant lamp above, cold blue light from the window behind, shallow depth of "
          "field, natural skin texture, subtle film grain, muted teal and amber color grade, realistic, "
          "photographic, no text on screen, no logo, no watermark")


def _iso(t: datetime) -> str:
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def model_usage(cf: CloudflareAI, model: str) -> dict:
    n = datetime.now(timezone.utc)
    u = cf.neuron_usage(_iso(datetime(n.year, n.month, n.day, tzinfo=timezone.utc)), _iso(n))
    if u.get("ok"):
        m = u["by_model"].get(model, {"requests": 0, "neurons": 0.0})
        u["m_requests"], u["m_neurons"] = m["requests"], m["neurons"]
    return u


def measure(cf, model, before: dict, wait: float, poll: float, sleep=time.sleep) -> float | None:
    t0 = time.monotonic()
    while time.monotonic() - t0 < wait:
        sleep(poll)
        u = model_usage(cf, model)
        if u.get("ok") and u["m_requests"] > before.get("m_requests", 0):
            return round(u["m_neurons"] - before["m_neurons"], 3)
    return None


def checks(cf: CloudflareAI, log) -> dict:
    """Секреттердин маанисин чыгарбай: токен активдүүбү, account ID туурабы, уруксаттар."""
    r: dict = {}
    tok = cf.verify_token()
    r["token"] = {"ok": tok.get("ok"), "status": tok.get("status"), "kind": tok.get("kind")}
    log(f"{'✅' if tok.get('ok') else '❌'} API Token: {tok.get('status') or tok.get('error')} "
        f"({'account' if tok.get('kind') == 'accounts' else 'user'} токени)")
    ms = ci.list_image_models(cf)
    r["models"] = ms
    r["account_id_ok"] = bool(ms.get("ok"))
    r["perm_workers_ai_read"] = bool(ms.get("ok"))
    if ms.get("ok"):
        log(f"✅ Account ID туура жана Workers AI окуу уруксаты бар: {len(ms['models'])} Text-to-Image модели")
    else:
        log(f"❌ Account ID же Workers AI уруксаты: HTTP {ms.get('http')} {ms.get('error')}")
    u = model_usage(cf, FLUX_MODEL)
    r["perm_analytics_read"] = bool(u.get("ok"))
    r["today"] = {"neurons": u.get("total"), "requests": u.get("requests")} if u.get("ok") else None
    log(f"{'✅' if u.get('ok') else '⚠️'} Account Analytics: Read — "
        + (f"бар; бүгүн {u['total']} neuron, {u['requests']} суроо" if u.get("ok")
           else f"жок ({u.get('error')}) — чыгым баалоо менен гана"))
    return r


def models_md(r: dict, schemas: dict) -> str:
    lines = ["## ☁️ Cloudflare Workers AI — сүрөт моделдери", "",
             f"- Токен: {'✅ ' + str(r['token']['status']) if r['token']['ok'] else '❌'}",
             f"- Account ID / Workers AI окуу: {'✅' if r['account_id_ok'] else '❌'}",
             f"- Workers AI иштетүү (run): {r.get('perm_run', 'текшерилген жок (сүрөт жаратылган жок)')}",
             f"- Analytics: Read: {'✅' if r['perm_analytics_read'] else '⚠️ жок'}", "",
             "| Модель | Касиеттер (API'ден: баа ж.б.) |", "|---|---|"]
    for m in (r["models"].get("models") or []):
        props = "; ".join(f"{k}={json.dumps(v, ensure_ascii=False)[:160]}" for k, v in m["properties"].items())
        lines.append(f"| `{m['name']}` | {props or '-'} |")
    for name, sp in schemas.items():
        lines += ["", f"**{name}** — {'multipart' if sp.get('multipart') else 'JSON'}; параметрлер: "
                  + ", ".join(f"{k}({v.get('type')}, max {v.get('maximum')})" for k, v in sp["props"].items())]
    return "\n".join(lines) + "\n"


def run(out: Path, mode: str = "models", model: str = "", log=print, drive=None, store=None,
        wait: float = 240.0, poll: float = 20.0, sleep=time.sleep) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    res: dict = {"mode": mode, "ok": False}
    cf = CloudflareAI.from_env(max_images=1 if mode == "image" else 0, timeout=180.0)
    if cf is None:
        res["error"] = "CLOUDFLARE_API_TOKEN же CLOUDFLARE_ACCOUNT_ID секрети жок"
        log("❌ " + res["error"])
        return res
    r = checks(cf, log)
    res.update(r)
    if not (r["token"]["ok"] and r["account_id_ok"]):
        return res
    names = [m["name"] for m in r["models"]["models"]]
    schemas = {}
    for name in [m for m in ci.PREFERRED if m in names] + ([model] if model and model in names else []):
        schemas[name] = ci.input_spec(ci.model_schema(cf, name))
    res["schemas"] = schemas
    if mode != "image":
        res["ok"] = True
        (out / "models.md").write_text(models_md(r, schemas), encoding="utf-8")
        return res

    chosen = ci.pick_model(names, model)
    if not chosen:
        res["error"] = f"модель табылган жок: {model or 'PREFERRED тизмесинен бири да жок'}"
        log("❌ " + res["error"])
        return res
    store = store or cb.LedgerStore(None, local=out / cb.LEDGER_NAME)
    budget = cb.Budget(store.load())
    if r["today"]:
        budget.set_api(r["today"]["neurons"])
    props = next((m["properties"] for m in r["models"]["models"] if m["name"] == chosen), {})
    steps = 4 if chosen == FLUX_MODEL else ci.DEFAULT_STEPS
    cost = ci.estimate_cost(props, 1344, 768, steps)
    if chosen == FLUX_MODEL:
        est, src = cb.estimate_neurons(1024, 1024, 4), "жарыяланган баа (1024×1024, 4 кадам)"
    elif cost:
        est, src = cost["neurons"], f"API баасы: {cost['tiles']} плитка × + {cost['steps']} кадам = ${cost['usd']}"
    else:
        est, src = ci.UNKNOWN_COST, "баасы белгисиз — коопсуз чоң баалоо"
    res["cost_estimate"] = {"neurons": est, "source": src, "usd_if_paid": round(est / 1000 * ci.USD_PER_1K_NEURONS, 4)}
    before = model_usage(cf, chosen)
    log(f"🎨 Модель: {chosen}; алдын ала баа ~{est} neuron ({src}); бүгүн колдонулду {budget.used():.0f}")
    t0 = time.monotonic()
    try:
        img, params = ci.generate(cf, chosen, PROMPT, width=1344, height=768, steps=steps,
                                  spec=schemas.get(chosen), budget=budget, est=est)
    except cb.BudgetExceeded as e:
        res["error"] = f"⛔ {e}"
    except QuotaError as e:
        res["error"] = f"⛔ акысыз лимит: {e} — акы төлөнүүчү режимге өтүлбөйт"
    except CloudflareError as e:
        res["error"] = f"❌ {e} — кайра аракет жасалбайт"
        res["perm_run"] = "❌" if "10000" in str(e) or "403" in str(e) else "?"
    if res.get("error"):
        log(res["error"])
        store.save(budget.to_json())
        return res
    secs = round(time.monotonic() - t0, 1)
    res["perm_run"] = "✅"
    ext = "png" if img[:8] == b"\x89PNG\r\n\x1a\n" else "jpg"
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    name = f"cf_{chosen.rsplit('/', 1)[-1]}_{stamp}"
    p = out / f"{name}.{ext}"
    p.write_bytes(img)
    measured = measure(cf, chosen, before, wait, poll, sleep) if before.get("ok") else None
    rec = budget.day()["requests"][-1]
    if measured is not None:
        budget.set_measured(rec, measured)
    meta = {"model": chosen, "prompt": PROMPT, "params": params, "size": ci.image_size(img), "bytes": len(img),
            "seconds": secs, "neurons_estimate": est, "neurons_measured": measured,
            "usd_if_paid": round((measured or est) / 1000 * ci.USD_PER_1K_NEURONS, 5), "cost_source": src,
            "created_utc": stamp, "note": "TEST — видео системасына кошулган эмес"}
    (out / f"{name}.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    res["image"] = meta
    log(f"✅ Сүрөт: {meta['size']}, {len(img) // 1024} КБ, {secs} сек; чыгым "
        + (f"{measured} neuron (чыныгы)" if measured is not None else f"~{est} neuron (баалоо)"))
    if drive is not None:
        try:
            fid = drive.ensure_path(*TEST_FOLDER)
            res["drive_image"] = drive.upload_file(p, fid)
            drive.upload_file(out / f"{name}.json", fid)
            log(f"✅ Drive: {'/'.join(TEST_FOLDER)}/{p.name}")
        except Exception as e:
            res["drive_error"] = type(e).__name__
            log(f"⚠️ Drive'га сакталган жок ({type(e).__name__}) — артефактта бар")
    store.save(budget.to_json())
    (out / "models.md").write_text(models_md(r | {"perm_run": "✅"}, schemas), encoding="utf-8")
    res["ok"] = True
    return res


def main() -> int:
    out = Path(os.environ.get("CF_OUT", "cf_test"))
    drive = None
    try:
        from .drive import DriveClient
        drive = DriveClient.from_env()
    except Exception as e:
        print(f"⚠️ Drive ачылган жок ({type(e).__name__})")
    store = cb.LedgerStore(drive, "YouTube_Auto", out / cb.LEDGER_NAME)
    res = run(out, os.environ.get("CF_MODE", "models"), os.environ.get("CF_MODEL", "").strip(),
              drive=drive if os.environ.get("CF_MODE") == "image" else None, store=store)
    (out / "summary.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    summ = os.environ.get("GITHUB_STEP_SUMMARY")
    if summ and (out / "models.md").exists():
        with open(summ, "a", encoding="utf-8") as f:
            f.write((out / "models.md").read_text(encoding="utf-8"))
    print(json.dumps({k: v for k, v in res.items() if k != "models"}, ensure_ascii=False, indent=1)[:4000])
    for m in (res.get("models") or {}).get("models") or []:
        print("MODEL", m["name"], json.dumps(m["properties"], ensure_ascii=False)[:400])
    return 0 if res.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
