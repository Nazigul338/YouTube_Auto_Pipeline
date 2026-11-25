"""Drive тазалоо — КАТААЛ план жана СЕБЕТКЕ жылдыруу (2026-11-25, колдонуучунун шарттары менен).

Колдонуучунун шарттары:
  1) тизме кайра текшерилет;  2) Video_001/003/004'түн MP4, сценарий, аудио, лицензиясына ТИЙИЛБЕЙТ
  (коопсуздук үчүн бул долбоорлордун ЭЧ БИР файлына тийилбейт);  3) клиптер базасы өчүрүлбөйт;
  4) кайталанган файлдар md5+көлөм менен чындап бирдей экени текшерилет;  5) өчүрүлө турганы өзүнчө тизме;
  6) колдонуучунун акыркы уруксатысыз эч нерсе жасалбайт;  7) биротоло өчүрүлбөйт — СЕБЕТКЕ гана жылдырылат.

Режимдер (env CLEAN_MODE):
  plan  — тизме + план коду (эч нерсе өзгөрбөйт);
  trash — CLEAN_CODE планга дал келсе гана, ошол файлдарды files.update(trashed=True) менен себетке жылдырат.
          `files.delete` жана `emptyTrash` КОДДО ЖОК. Ар файлдан кийин trashed=True экени текшерилет.
Эскертүү: себеттеги файлдар Google'да 30 күн сакталат жана ошол убакка чейин орун ЭЭЛЕЙ БЕРЕТ.
"""
from __future__ import annotations

import hashlib
import re
import json
import os
import sys
from pathlib import Path

from .drive_inventory import Inventory, classify

PROTECTED_PROJECTS = ("Video_001", "Video_003", "Video_004", "Video_006")
NEVER_FOLDERS = ("Final_Videos", "Thumbnails", "Licenses", "Clips", "Music", "Sound_Effects", "Scripts",
                 "Subtitles", "Logs", "clips", "clips_2k", "final", "audio")   # audio: Long_Videos/audio (video_001)
TRASH_SAFE_FOLDERS = ("test_2k", "_preview", "_diagnose", "_voice_test")
MEDIA = (".mp4", ".mov", ".wav", ".mp3", ".m4a", ".png", ".jpg", ".jpeg")


def eligible(r: dict) -> tuple[bool, str]:
    """Файл себетке жылдырылышы мүмкүнбү (бардык шарт аткарылса гана True)."""
    path = f"{r['folder']}/{r['name']}"
    parts = r["folder"].split("/")
    if "video_001" in path.lower():
        return False, "Video_001"
    if any(p in path for p in PROTECTED_PROJECTS):
        return False, "корголгон долбоор (001/003/004/006)"
    if not r["name"].lower().endswith(MEDIA):
        return False, "медиа эмес (сценарий/лицензия/метадайын)"
    if not parts or parts[0] not in ("YouTube_Auto", "YouTube_Auto_TEST"):
        return False, "системанын папкасы эмес"
    if classify(path, r["name"], r.get("mime", "video/mp4"))[0] not in ("candidate",):
        return False, "инвентаризацияда тесттик эмес"
    if "Video_005" in path:
        return True, "Video_005 — токтотулган кино-окуя сынагы (даяр видео жок)"
    if any(f in parts for f in NEVER_FOLDERS):
        return False, "корголгон папка"
    if any(f in parts for f in TRASH_SAFE_FOLDERS):
        return True, f"сынак/превью/диагностика папкасы ({next(f for f in TRASH_SAFE_FOLDERS if f in parts)})"
    return False, "ачык эреже жок — сакталат"


# Колдонуучу өзү атаган кошумча топтор (2026-11-25): ар бири өзүнчө план коду менен, өзүнчө уруксат.
EXTRA_RE = re.compile(r"^extra_0\d\.mp4$")


def eligible_set(r: dict, which: str) -> tuple[bool, str]:
    """extra: Colab доорундагы Long_Videos/clips_2k/extra_0*.mp4 (азыркы система колдонбойт);
    preview: _preview/Video_003_cinematic_60s.mp4 + _sheet.jpg (Video_003'тун превьюсу, даяр MP4 эмес)."""
    path = f"{r['folder']}/{r['name']}"
    if "video_001" in path.lower() or "Final_Videos" in path:
        return False, "корголгон"
    if which == "extra":
        if r["folder"] == "YouTube_Auto/Long_Videos/clips_2k" and EXTRA_RE.match(r["name"]):
            return True, "Colab доорундагы эски клип (азыркы система Long_Videos'ту колдонбойт)"
        return False, "топко кирбейт"
    if which == "colab_clips":   # колдонуучунун буйругу 2026-11-25: «Колабдагы бүт эски видео клиптерди өчүр»
        if r["folder"] in ("YouTube_Auto/Long_Videos/clips", "YouTube_Auto/Long_Videos/clips_2k") \
                and r["name"].lower().endswith(".mp4"):
            return True, "Colab доорундагы эски видео клип (азыркы система Long_Videos'ту колдонбойт)"
        return False, "топко кирбейт"
    if which == "preview":
        if r["folder"] == "YouTube_Auto_TEST/_preview" and r["name"].startswith("Video_003_cinematic_"):
            return True, "Video_003'тун 60 сек превьюсу/кадр барагы (даяр MP4 Final_Videos'то калат)"
        return False, "топко кирбейт"
    return eligible(r)


def plan(rows: list[dict], which: str = "tests") -> dict:
    sel, dups = [], []
    for r in rows:
        ok, why = eligible_set(r, which)
        if ok:
            sel.append({**r, "why": why})
    # кайталанган көчүрмөлөрдү ЧЫНДАП текшерүү: md5 + көлөм бирдей
    by: dict = {}
    for r in rows:
        if r.get("md5"):
            by.setdefault((r["md5"], r["bytes"]), []).append(r)
    ids = {r["id"] for r in sel}
    for r in sel:
        same = [x for x in by.get((r.get("md5"), r["bytes"]), []) if x["id"] != r["id"]]
        if same:
            kept = [x for x in same if x["id"] not in ids]
            r["duplicate"] = {"identical_md5": r["md5"], "bytes": r["bytes"],
                              "copies": [f"{x['folder']}/{x['name']}" for x in same],
                              "copy_kept": bool(kept)}
            dups.append(r)
    sel.sort(key=lambda r: -r["bytes"])
    code = hashlib.sha256("\n".join(sorted(r["id"] for r in sel)).encode()).hexdigest()[:10]
    return {"files": sel, "count": len(sel), "bytes": sum(r["bytes"] for r in sel), "code": code,
            "duplicates": len(dups)}


def plan_md(p: dict, excluded: list[tuple[dict, str]]) -> str:
    L = ["# 🧹 Drive тазалоо ПЛАНЫ (эч нерсе өзгөргөн жок)", "",
         f"- Себетке жылдырыла турган: **{p['count']} файл, {p['bytes'] / 1_048_576:.0f} МБ**",
         f"- План коду: **{p['code']}** (уруксат бергенде ушул код керек; файлдар өзгөрсө код да өзгөрөт)",
         "- Биротоло өчүрүлбөйт: Google Drive себетине гана (30 күн калыбына келтирүүгө болот).",
         "- ⚠️ Себеттеги файлдар орун ээлей берет — орун себет тазалангандан кийин гана бошойт.", "",
         "| # | Файл | МБ | Папка | Себеби | Көчүрмө текшерүүсү (md5) |", "|---|---|---|---|---|---|"]
    for i, r in enumerate(p["files"], 1):
        d = r.get("duplicate")
        dd = (f"бирдей ✅ md5 {d['identical_md5'][:8]}…, {d['bytes']} байт; көчүрмө: {d['copies'][0]}"
              + ("" if d["copy_kept"] else " (экөө тең пландa)")) if d else "—"
        L.append(f"| {i} | {r['name']} | {r['mb']} ({r['bytes']} байт) | {r['folder']} | {r['why']} | {dd} |")
    if not excluded:
        return "\n".join(L) + "\n"
    L += ["", f"## Мурунку 73 тизмеден ЧЫГАРЫЛГАНДАР ({len(excluded)} файл) — сакталат", "| Файл | МБ | Папка | Себеби |",
          "|---|---|---|---|"]
    for r, why in sorted(excluded, key=lambda x: -x[0]["bytes"]):
        L.append(f"| {r['name']} | {r['mb']} | {r['folder']} | {why} |")
    return "\n".join(L) + "\n"


def trash(svc, p: dict, code: str, log=print) -> dict:
    """Код дал келсе гана: ар файлды СЕБЕТКЕ (trashed=True). delete/emptyTrash колдонулбайт."""
    if code != p["code"]:
        raise SystemExit(f"⛔ План коду дал келбейт (берилди {code!r}, азыркы план {p['code']}) — эч нерсе жасалган жок")
    done, failed = [], []
    for r in p["files"]:
        try:
            svc.files().update(fileId=r["id"], body={"trashed": True}, fields="id,trashed").execute(num_retries=3)
            chk = svc.files().get(fileId=r["id"], fields="trashed").execute(num_retries=3)
            (done if chk.get("trashed") else failed).append(r)
        except Exception as e:
            failed.append({**r, "error": type(e).__name__})
    log(f"🗑 Себетке жылдырылды: {len(done)} файл ({sum(x['bytes'] for x in done) / 1_048_576:.0f} МБ); ката: {len(failed)}")
    for r in failed:
        log(f"   ❌ {r['folder']}/{r['name']}: {r.get('error', 'trashed текшерилген жок')}")
    return {"trashed": [f"{r['folder']}/{r['name']}" for r in done],
            "failed": [f"{r['folder']}/{r['name']}" for r in failed]}


def main() -> int:
    from .drive import DriveClient
    drive = DriveClient.from_env()
    if drive is None:
        print("❌ GDRIVE_* секреттери жок")
        return 2
    rows = Inventory(drive.svc).collect()["rows"]
    which = os.environ.get("CLEAN_SET", "tests")
    p = plan(rows, which)
    old = [r for r in rows if r["cat"] == "candidate"] if which == "tests" else []
    ids = {r["id"] for r in p["files"]}
    excluded = [(r, eligible(r)[1]) for r in old if r["id"] not in ids]
    md = plan_md(p, excluded)
    out = Path(os.environ.get("CLEAN_OUT", "drive_cleanup"))
    out.mkdir(parents=True, exist_ok=True)
    (out / "plan.md").write_text(md, encoding="utf-8")
    print(md)
    res = {"plan_code": p["code"], "count": p["count"], "bytes": p["bytes"]}
    if os.environ.get("CLEAN_MODE", "plan") == "trash":
        res.update(trash(drive.svc, p, os.environ.get("CLEAN_CODE", "").strip()))
    (out / "result.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as f:
            f.write(md[:900_000])
    return 1 if res.get("failed") else 0


if __name__ == "__main__":
    sys.exit(main())
