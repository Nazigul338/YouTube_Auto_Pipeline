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


GITHUB_START = "2026-11-16"     # GitHub системасынын биринчи видеосу (Video_001, run #43974637107)
COLAB_TEMP_MEDIA = (".mp4", ".mov", ".wav", ".mp3", ".m4a")


def colab_era(r: dict) -> bool:
    """Colab мезгилиндеги файл: YouTube_Auto (TEST эмес) ичинде 16-ноябрга чейин түзүлгөн же Long_Videos'то,
    же «Colab Notebooks» папкасында."""
    f = r["folder"]
    if f.startswith("Colab Notebooks"):
        return True
    if not (f == "YouTube_Auto" or f.startswith("YouTube_Auto/")):
        return False
    return "/Long_Videos" in f or (r.get("created") or "9999") < GITHUB_START


def colab_rest(r: dict) -> tuple[bool, str]:
    """Colab мезгилинен калган, азыркы системага кереги жок УБАКТЫЛУУ/ТЕСТ медиа (катаал)."""
    path = f"{r['folder']}/{r['name']}"
    parts = r["folder"].split("/")
    if not colab_era(r):
        return False, "Colab мезгилине кирбейт"
    if "video_001" in path.lower():
        return False, "Video_001 (Colab нускасы) — жалгыз нуска, сакталат"
    if r["folder"].startswith("Colab Notebooks") or r.get("mime", "").startswith("application/vnd.google"):
        return False, "блокнот/документ (код) — сакталат"
    if any(x in parts for x in ("Music", "Sound_Effects", "Licenses", "Final_Videos", "Thumbnails", "Clips",
                                "Projects", "Logs", "Scripts", "Subtitles")):
        return False, "азыркы система колдонгон папка — сакталат"
    if not r["name"].lower().endswith(COLAB_TEMP_MEDIA):
        return False, "медиа эмес (сценарий/лицензия/маалымат) — сакталат"
    if r["folder"] == "YouTube_Auto":
        return True, "Colab'тын тамырдагы сынак аудиосу/музыкасы (система колдонбойт)"
    if r["folder"] == "YouTube_Auto/Long_Videos/audio" and r["name"].startswith("test_"):
        return True, "Colab'тагы үн сынагы (test_*.wav)"
    return False, "ачык эреже жок — сакталат"


def eligible_set(r: dict, which: str) -> tuple[bool, str]:
    """extra: Colab доорундагы Long_Videos/clips_2k/extra_0*.mp4 (азыркы система колдонбойт);
    preview: _preview/Video_003_cinematic_60s.mp4 + _sheet.jpg (Video_003'тун превьюсу, даяр MP4 эмес)."""
    path = f"{r['folder']}/{r['name']}"
    if which == "keep_latest":   # колдонуучу 2026-11-25: «Акыркы жасалган видеону калтыр, калган видеолорду өчүр»
        keep = "Video_004_cinematic.mp4"  # акыркы даяр видео (реестр: Video_004 ready, 2026-11-21)
        if (r["folder"].split("/")[0] in ("YouTube_Auto", "YouTube_Auto_TEST", "YouTube_Auto_EN", "YouTube_Auto_EN_TEST")
                and r["name"].lower().endswith(".mp4") and r["name"] != keep):
            return True, "даяр/превью видео — колдонуучу акыркысын гана калтырууну буйруду (визуалдык изи реестрде калат)"
        return False, "акыркы видео же видео эмес"
    if which == "colab_videos":   # колдонуучунун ачык буйругу 2026-11-25: «Colabдагы бүт видеолорду өчүрүп сал»
        # Colab'тагы Video_001 версиясы да кошулат (колдонуучу ачык тандады); учурдагы Final_Videos/Video_001.mp4 кирбейт.
        if (r["folder"].startswith("YouTube_Auto/Long_Videos") and r["name"].lower().endswith(".mp4")
                and (r.get("created") or "9999") < GITHUB_START and "Final_Videos" not in path):
            return True, "Colab мезгилиндеги видео (азыркы система колдонбойт; колдонуучу ачык тандады)"
        return False, "топко кирбейт"
    if "video_001" in path.lower() or "Final_Videos" in path:
        return False, "корголгон"
    if which == "extra":
        if r["folder"] == "YouTube_Auto/Long_Videos/clips_2k" and EXTRA_RE.match(r["name"]):
            return True, "Colab доорундагы эски клип (азыркы система Long_Videos'ту колдонбойт)"
        return False, "топко кирбейт"
    if which == "colab_rest":
        return colab_rest(r)
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
    L += ["", f"## Текшерилген, бирок САКТАЛА турган файлдар ({len(excluded)} файл, "
          f"{sum(r['bytes'] for r, _ in excluded) / 1_048_576:.0f} МБ)", "| Файл | МБ | Папка | Себеби |",
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


NAMED_RE = re.compile(r"^Video_00(2|5)(?![0-9])")     # Video_002 / Video_005 (Video_0050 эмес)
SYSTEM_ROOTS = ("YouTube_Auto", "YouTube_Auto_TEST", "YouTube_Auto_EN", "YouTube_Auto_EN_TEST")
NAMED_MAX_BYTES = 200 * 1024 * 1024      # бир элемент ~200 МБ'ден чоң болсо — токтойт (күтүлбөгөн нерсе)
NAMED_MAX_ITEMS = 120


def named_plan(svc) -> list[dict]:
    """Video_002 / Video_005 деген аттагы папкалар жана файлдар (системанын тамырларында, себетте эмес).
    Папка трешке кетсе ичиндегилери да кетет, ошондуктан жогорку деңгээлдегилер гана алынат."""
    def lst(q, fields):
        out, tok = [], None
        while True:
            r = svc.files().list(q=q, fields=f"nextPageToken, files({fields})", pageSize=1000, pageToken=tok,
                                 spaces="drive").execute(num_retries=3)
            out += r.get("files", [])
            tok = r.get("nextPageToken")
            if not tok:
                return out
    folders = {f["id"]: f for f in lst("mimeType = 'application/vnd.google-apps.folder' and trashed = false", "id,name,parents")}
    files = lst("mimeType != 'application/vnd.google-apps.folder' and trashed = false and 'me' in owners",
                "id,name,parents,size,mimeType")

    def chain(pid, d=0):
        names = []
        while pid and pid in folders and d < 30:
            names.append(folders[pid]["name"])
            pid, d = (folders[pid].get("parents") or [None])[0], d + 1
        return list(reversed(names))
    items = []
    for kind, src in (("folder", list(folders.values())), ("file", files)):
        for x in src:
            if not NAMED_RE.match(x["name"]):
                continue
            ch = chain((x.get("parents") or [None])[0])
            if not ch or ch[0] not in SYSTEM_ROOTS:
                continue
            items.append({"id": x["id"], "name": x["name"], "kind": kind, "path": "/".join(ch),
                          "bytes": int(x.get("size") or 0), "mime": x.get("mimeType", "")})
    top = [i for i in items if not any(NAMED_RE.match(n) for n in i["path"].split("/"))]
    return sorted(top, key=lambda i: i["path"] + "/" + i["name"])


def trash_named(svc, log=print) -> dict:
    plan_ = named_plan(svc)
    bad = [i for i in plan_ if i["bytes"] > NAMED_MAX_BYTES or "Final_Videos" in i["path"]
           or i["name"].startswith("_registry")]
    if bad or len(plan_) > NAMED_MAX_ITEMS:
        raise SystemExit(f"⛔ Күтүлбөгөн нерсе: {len(plan_)} элемент, шектүү: {[b['name'] for b in bad][:5]} — эч нерсе жасалган жок")
    for i in plan_:
        log(f"   • {i['kind']}: {i['path']}/{i['name']} ({i['bytes'] / 1_048_576:.1f} МБ)")
    done, failed = [], []
    for i in plan_:
        try:
            svc.files().update(fileId=i["id"], body={"trashed": True}, fields="id").execute(num_retries=3)
            chk = svc.files().get(fileId=i["id"], fields="trashed").execute(num_retries=3)
            (done if chk.get("trashed") else failed).append(i)
        except Exception as e:
            failed.append({**i, "error": type(e).__name__})
    log(f"🗑 Video_002/Video_005: себетке жылдырылды {len(done)} элемент; ката: {len(failed)}")
    return {"trashed": [f"{i['path']}/{i['name']}" for i in done], "failed": [i["name"] for i in failed]}


RESTORE_NAMES = {"Video_001.mp4": 515922558, "Video_001_cinematic.mp4": 443086950,
                 "Video_003_cinematic.mp4": 363401299}


def restore(svc, log=print) -> list[dict]:
    """Колдонуучунун суроосу (2026-11-25): Video_001 MP4'терин себеттен КАЙТАРУУ (телефонго жүктөп алуу үчүн).
    Аты ЖАНА байт көлөмү дал келген, себеттеги, колдонуучуга таандык файлдар гана; trashed=False. Башкага тийбейт."""
    out, tok = [], None
    while True:
        r = svc.files().list(q="trashed = true and 'me' in owners and mimeType = 'video/mp4'",
                             fields="nextPageToken, files(id,name,size,parents)", pageSize=200,
                             pageToken=tok).execute(num_retries=3)
        for f in r.get("files", []):
            if RESTORE_NAMES.get(f["name"]) == int(f.get("size") or 0):
                svc.files().update(fileId=f["id"], body={"trashed": False}, fields="id").execute(num_retries=3)
                chk = svc.files().get(fileId=f["id"], fields="id,name,trashed,webViewLink,size").execute(num_retries=3)
                if not chk.get("trashed"):
                    out.append(chk)
                    log(f"♻️ Кайтарылды: {chk['name']} ({int(chk['size']) / 1_048_576:.0f} МБ) {chk.get('webViewLink', '')}")
        tok = r.get("nextPageToken")
        if not tok:
            return out


TRASH_FINAL = {"Video_003_cinematic.mp4": 289269797,        # колдонуучу телефонго жүктөдү (2026-11-26) — аты + байт дал келсе
               "Video_001_cinematic.mp4": 443086950, "Video_004_cinematic.mp4": 333151574}


def trash_final(svc, log=print) -> dict:
    """Колдонуучунун так суроосу: Video_003 MP4'ти телефонго жүктөгөндөн кийин Drive'дан өчүрүү.
    Себетке гана жылдырылат (биротоло өчүрүлбөйт). Аты ЖАНА байт көлөмү дал келген, колдонуучуга таандык файл гана;
    Final_Videos ичинде. Обложка/сценарий/аудио/лицензия/реестр/клип базасына тийилбейт."""
    done, failed, seen = [], [], set()
    for name, size in TRASH_FINAL.items():
        r = svc.files().list(q=f"name = '{name}' and trashed = false and 'me' in owners",
                             fields="files(id,name,size,parents)", pageSize=50).execute(num_retries=3)
        for f in r.get("files", []):
            if int(f.get("size") or 0) != size or f["id"] in seen:
                continue
            seen.add(f["id"])
            par = svc.files().get(fileId=f["parents"][0], fields="name").execute(num_retries=3)["name"] if f.get("parents") else ""
            if par != "Final_Videos":
                log(f"   ⏭ {par}/{name}: Final_Videos эмес — тийбедим")
                continue
            try:
                svc.files().update(fileId=f["id"], body={"trashed": True}, fields="id").execute(num_retries=3)
                chk = svc.files().get(fileId=f["id"], fields="trashed").execute(num_retries=3)
                (done if chk.get("trashed") else failed).append(name)
                log(f"🗑 Себетке жылдырылды: {par}/{name} ({size / 1_048_576:.0f} МБ)")
            except Exception as e:
                failed.append(name)
                log(f"   ❌ {name}: {type(e).__name__}")
    return {"trashed": done, "failed": failed}


def main() -> int:
    from .drive import DriveClient
    drive = DriveClient.from_env()
    if drive is None:
        print("❌ GDRIVE_* секреттери жок")
        return 2
    if os.environ.get("CLEAN_MODE") == "trash_named":
        res = trash_named(drive.svc)
        print(json.dumps(res, ensure_ascii=False))
        return 1 if res["failed"] else 0
    if os.environ.get("CLEAN_MODE") == "trash_final":
        res = trash_final(drive.svc)
        print(json.dumps(res, ensure_ascii=False))
        return 1 if res["failed"] or not res["trashed"] else 0
    if os.environ.get("CLEAN_MODE") == "restore":
        res = restore(drive.svc)
        print(json.dumps([{"name": x["name"], "link": x.get("webViewLink")} for x in res], ensure_ascii=False))
        return 0   # бир бөлүгү мурун эле кайтарылган болушу мүмкүн — ката эмес
    rows = Inventory(drive.svc).collect()["rows"]
    which = os.environ.get("CLEAN_SET", "tests")
    p = plan(rows, which)
    old = ([r for r in rows if r["cat"] == "candidate"] if which == "tests"
           else [r for r in rows if colab_era(r)] if which == "colab_rest" else [])
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
