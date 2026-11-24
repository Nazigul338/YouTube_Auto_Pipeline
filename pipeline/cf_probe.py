"""Cloudflare Workers AI: акысыз лимит мониторинги + FLUX.1 schnell тести (2026-11-24).

Режимдер (env CF_MODE):
  status — сүрөт жаратпайт: журнал + Cloudflare аналитикасы → dashboard (бекер);
  test   — CF_IMAGES (≤5) сүрөт: ар биринен МУРУН бюджет текшерилет, кийин аналитикада ошол суроо
           пайда болгонго чейин күтүп (≤CF_WAIT сек) анын ЧЫНЫГЫ neuron чыгымы өлчөнөт.
Иштетүү: Actions → «☁️ Cloudflare AI сыноо». Видео системасына (make_video) тийбейт.
Натыйжа: cf_test/ (сүрөттөр, summary.json, dashboard.md — артефакт), Drive Logs/cloudflare_ai_usage.json (тарых)
жана Logs/cloudflare_ai_dashboard.md.
"""
from __future__ import annotations

import json
import os
import struct
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from . import cf_budget as cb
from .cloudflare_ai import FLUX_MODEL, CloudflareAI, CloudflareError, QuotaError

PROMPTS = [
    "cinematic photo, a person sitting alone at a desk by a large window at dawn, soft warm light, notebook and "
    "cup of tea, calm hopeful mood, shallow depth of field, no text, no logo",
    "cinematic photo, hands holding a crumpled paper with crossed-out notes under a cold desk lamp at night, "
    "tense quiet mood, shallow depth of field, no text, no logo",
    "cinematic photo, a long empty office corridor with fluorescent lights at night, a lone silhouette walking "
    "away, blue tones, no text, no logo",
    "cinematic photo, a person standing on a hill at sunrise seen from behind, wind, golden light, sense of relief, "
    "no text, no logo",
    "cinematic photo, close-up of a hand writing a short list in a notebook beside a cup of tea, morning light, "
    "warm tones, no text, no logo",
]


def jpeg_size(data: bytes) -> tuple[int, int] | None:
    """JPEG'дин туурасы/бийиктиги (SOF маркеринен), JPEG болбосо None."""
    if data[:2] != b"\xff\xd8":
        return None
    i = 2
    while i + 9 < len(data):
        if data[i] != 0xFF:
            i += 1
            continue
        marker = data[i + 1]
        if marker in (0xC0, 0xC1, 0xC2):
            h, w = struct.unpack(">HH", data[i + 5:i + 9])
            return w, h
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
            i += 2
            continue
        i += 2 + struct.unpack(">H", data[i + 2:i + 4])[0]
    return None


def _iso(t: datetime) -> str:
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def flux_usage(cf: CloudflareAI, now=None) -> dict:
    """Бүгүнкү (UTC) колдонуу: бардык моделдер жана FLUX өзүнчө."""
    n = now or datetime.now(timezone.utc)
    start = datetime(n.year, n.month, n.day, tzinfo=timezone.utc)
    u = cf.neuron_usage(_iso(start), _iso(n))
    if u.get("ok"):
        f = u["by_model"].get(FLUX_MODEL, {"requests": 0, "neurons": 0.0})
        u["flux_requests"], u["flux_neurons"] = f["requests"], f["neurons"]
    return u


def wait_measure(cf, before: dict, wait: float, poll: float, log, sleep=time.sleep) -> tuple[float | None, dict]:
    """Аналитикада FLUX суроолорунун саны өскөнчө күтөт → (бул суроонун neuron'у, жаңы абал)."""
    t0 = time.monotonic()
    while True:
        sleep(poll)
        u = flux_usage(cf)
        if u.get("ok") and u["flux_requests"] > before.get("flux_requests", 0):
            k = u["flux_requests"] - before["flux_requests"]
            return round((u["flux_neurons"] - before["flux_neurons"]) / k, 3), u
        if time.monotonic() - t0 >= wait:
            log(f"   ⏳ аналитика {wait:.0f} сек ичинде жаңырган жок — бул сүрөткө баалоо колдонулат")
            return None, u if u.get("ok") else before


def run(out_dir: Path, log=print, mode: str = "status", images: int = 0, store=None,
        wait: float = 300.0, poll: float = 20.0, sleep=time.sleep) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    images = max(0, min(cb.TEST_MAX_IMAGES, int(images))) if mode == "test" else 0
    res: dict = {"model": FLUX_MODEL, "mode": mode, "token": None, "model_available": None,
                 "analytics": None, "images": [], "ok": False}
    store = store or cb.LedgerStore()
    budget = cb.Budget(store.load())

    cf = CloudflareAI.from_env(max_images=images)
    if cf is None:
        res["error"] = "CLOUDFLARE_API_TOKEN же CLOUDFLARE_ACCOUNT_ID секрети жок"
        log(f"❌ {res['error']}")
        return res

    tok = cf.verify_token()
    res["token"] = {k: tok.get(k) for k in ("ok", "status", "kind")}
    log(f"{'✅' if tok['ok'] else '⚠️'} Токен: {tok.get('status') or tok.get('error')}")
    m = cf.model_info()
    res["model_available"] = m
    if not m["ok"]:
        log(f"❌ FLUX.1 schnell жеткиликсиз: {m.get('error')}")
        return res
    log(f"✅ Model ID текшерилди: {m['name']} ({m.get('task')})")

    u = flux_usage(cf)
    res["analytics"] = {"ok": u.get("ok"), "error": u.get("error")}
    if u.get("ok"):
        budget.set_api(u["total"])
        log(f"✅ Cloudflare аналитикасы: бүгүн {u['total']} neuron, {u['requests']} суроо "
            f"(FLUX: {u['flux_requests']} суроо, {u['flux_neurons']:.2f} neuron)")
    else:
        log(f"⚠️ Чыныгы колдонууну API'ден алуу мүмкүн болбоду: {u.get('error')} — жергиликтүү эсептегич колдонулат")

    stop = None
    for i in range(images):
        prompt = PROMPTS[i % len(PROMPTS)]
        try:
            data = cf.generate_image(prompt, steps=4, budget=budget)
        except cb.BudgetExceeded as e:
            stop = f"⛔ {e}"
            break
        except QuotaError as e:
            stop = f"⛔ Cloudflare акысыз лимит: {e} — акы төлөнүүчү режимге өтүлбөйт"
            break
        except CloudflareError as e:
            stop = f"❌ Сүрөт {i + 1}: {e} — кайра аракет жасалбайт, тест токтотулду"
            break
        rec = budget.day()["requests"][-1]
        p = out_dir / f"flux_{i + 1}.jpg"
        p.write_bytes(data)
        info = {"file": p.name, "bytes": len(data), "size": jpeg_size(data), "estimate": rec["estimate"],
                "measured": None}
        if u.get("ok"):
            meas, u = wait_measure(cf, u, wait, poll, log, sleep)
            if meas is not None:
                budget.set_measured(rec, meas)
                info["measured"] = meas
            if u.get("ok"):
                budget.set_api(u["total"])
        res["images"].append(info)
        warn = budget.check(0) if budget.used() < cb.DAILY_LIMIT * (1 - cb.SAFETY_RESERVE) else None
        log(f"✅ Сүрөт {i + 1}: {info['size']}, {len(data) // 1024} КБ; чыгым "
            f"{info['measured'] if info['measured'] is not None else '~' + str(info['estimate'])} neuron"
            + (" (чыныгы)" if info["measured"] is not None else " (баалоо)") + (f" — {warn}" if warn else ""))
    if stop:
        log(stop)
        res["stopped"] = stop

    rep = budget.report()
    video = cb.plan_video_images(480.0, rep["estimated_remaining_images"])
    hist = budget.data["days"]
    dash = cb.dashboard_md(rep, video, hist)
    res.update(report=rep, video_plan=video)
    res["dashboard_link"] = store.save(budget.to_json(), dash)
    (out_dir / "dashboard.md").write_text(dash, encoding="utf-8")
    good = [x for x in res["images"] if x["size"]]
    res["ok"] = (mode == "status") or (len(good) == images and not stop)
    log(f"📊 Колдонулду {rep['used']} / {rep['daily_limit']} neuron ({rep['used_pct']}%); дагы ~"
        f"{rep['estimated_remaining_images']} сүрөт; орточо {rep['avg_per_image']} ({rep['avg_source']})")
    return res


def _store():
    try:
        from .drive import DriveClient
        drive = DriveClient.from_env()
    except Exception as e:                       # Drive жок/ката — жергиликтүү журнал (артефакт)
        print(f"⚠️ Drive ачылган жок ({type(e).__name__}) — журнал артефактка гана сакталат")
        drive = None
    return cb.LedgerStore(drive, "YouTube_Auto", Path(os.environ.get("CF_OUT", "cf_test")) / cb.LEDGER_NAME)


def main() -> int:
    out = Path(os.environ.get("CF_OUT", "cf_test"))
    res = run(out, mode=os.environ.get("CF_MODE", "status"), images=int(os.environ.get("CF_IMAGES", "0") or 0),
              store=_store(), wait=float(os.environ.get("CF_WAIT", "300")))
    (out / "summary.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    summ = os.environ.get("GITHUB_STEP_SUMMARY")
    if summ and (out / "dashboard.md").exists():
        with open(summ, "a", encoding="utf-8") as f:
            f.write((out / "dashboard.md").read_text(encoding="utf-8"))
            if res.get("dashboard_link"):
                f.write(f"\nDrive: {res['dashboard_link']}\n")
    return 0 if res["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
