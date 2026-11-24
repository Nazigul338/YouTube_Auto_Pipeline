"""Cloudflare Workers AI сыноосу: токен → FLUX.1 schnell жеткиликтүүлүгү → БИР тесттик сүрөт.

Иштетүү: Actions → «☁️ Cloudflare AI сыноо» (cloudflare_ai_test.yml). Видео системасына тийбейт.
Натыйжа: cf_test/flux_test.jpg + cf_test/summary.json (workflow артефакты).
"""
from __future__ import annotations

import json
import os
import struct
import sys
from pathlib import Path

from .cloudflare_ai import FLUX_MODEL, CloudflareAI, CloudflareError, QuotaError

TEST_PROMPT = ("cinematic photo, a person sitting alone at a desk by a large window at dawn, soft warm light, "
               "notebook and cup of tea, calm hopeful mood, shallow depth of field, no text, no logo")


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


def run(out_dir: Path, log=print) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    res: dict = {"model": FLUX_MODEL, "token": None, "model_available": None, "image": None, "ok": False}
    cf = CloudflareAI.from_env(max_images=1)
    if cf is None:
        res["error"] = "CLOUDFLARE_API_TOKEN же CLOUDFLARE_ACCOUNT_ID секрети жок"
        log(f"❌ {res['error']}")
        return res

    tok = cf.verify_token()
    res["token"] = tok
    log(f"{'✅' if tok['ok'] else '⚠️'} Токен: {tok.get('status') or tok.get('error')} ({tok.get('kind', '-')})")

    m = cf.model_info()
    res["model_available"] = m
    if not m["ok"]:
        log(f"❌ FLUX.1 schnell жеткиликсиз: {m.get('error')} (HTTP {m.get('http')})")
        return res
    log(f"✅ Модель бар: {m['name']} ({m.get('task')})")

    try:
        data = cf.generate_image(TEST_PROMPT, steps=4, seed=20261124)
    except QuotaError as e:
        res["error"] = str(e)
        log(f"⛔ Акысыз лимит: {e} — акы төлөнүүчү режимге өтүлбөйт")
        return res
    except CloudflareError as e:
        res["error"] = str(e)
        log(f"❌ Сүрөт жаралган жок: {e}")
        return res
    size = jpeg_size(data)
    path = out_dir / "flux_test.jpg"
    path.write_bytes(data)
    res["image"] = {"file": path.name, "bytes": len(data), "size": size, "prompt": TEST_PROMPT}
    res["ok"] = size is not None and len(data) > 10_000
    log(f"{'✅' if res['ok'] else '❌'} Тесттик сүрөт: {len(data) // 1024} КБ, {size} (суроолор: {cf.images_made})")
    return res


def main() -> int:
    out = Path(os.environ.get("CF_OUT", "cf_test"))
    res = run(out)
    (out / "summary.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    summ = os.environ.get("GITHUB_STEP_SUMMARY")
    if summ:
        img = res.get("image") or {}
        with open(summ, "a", encoding="utf-8") as f:
            f.write("## ☁️ Cloudflare Workers AI — FLUX.1 schnell\n\n"
                    f"- Токен: {(res.get('token') or {}).get('status')}\n"
                    f"- Модель: {'✅ бар' if (res.get('model_available') or {}).get('ok') else '❌'}\n"
                    f"- Тесттик сүрөт: {'✅ ' + str(img.get('size')) if res['ok'] else '❌ ' + str(res.get('error'))}\n"
                    "- Сүрөт: ушул run'дун Artifacts → `cloudflare-flux-test`\n")
    return 0 if res["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
