"""Drive инвентаризациясы — ОКУУ ГАНА (2026-11-25). Эч нерсе өчүрүлбөйт, жылдырылбайт, жазылбайт.

Эмне кылат:
  1) Drive'дын көлөмүн (лимит, колдонулган, анын ичинде Drive/Себет/Gmail+Photos) көрсөтөт;
  2) бардык файлдарды (себеттегилер өзүнчө) толук жолу жана көлөмү менен тизмелейт;
  3) ар файлды категорияга бөлөт: protected (Video_001, сценарий/код/лицензия/журнал, даяр видеолор, музыка) ·
     candidate (тесттик/кайра түзүлө турган медиа — өчүрүүгө СУНУШ гана) · user (системанын папкасынан тышкары —
     колдонуучу өзү чечет) · active (иштеп жаткан Video_006);
  4) Video_001'дин толуктугун текшерет (сценарий, аудио, субтитр, клиптер тизмеси, акыркы MP4).
Иштетүү: Actions → «🗂 Drive инвентаризациясы» (drive_inventory.yml). Отчет логдо + артефактта.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

FOLDER = "application/vnd.google-apps.folder"
SYSTEM_ROOTS = ("YouTube_Auto", "YouTube_Auto_TEST", "YouTube_Auto_EN", "YouTube_Auto_EN_TEST")
KEEP_EXT = {".txt", ".json", ".srt", ".ass", ".vtt", ".md", ".yaml", ".yml", ".py", ".csv", ".pdf", ".html", ".log"}
MEDIA_EXT = {".mp4", ".mov", ".mkv", ".webm", ".wav", ".mp3", ".m4a", ".aac", ".flac", ".png", ".jpg", ".jpeg",
             ".webp", ".zip"}
ACTIVE = ("Video_006",)          # иштеп жаткан сынак (2026-11-25) — тийилбейт
FINAL_RE = re.compile(r"^Video_\d{3}\.mp4$")   # даяр видеонун негизги MP4'ү


def mb(n) -> float:
    return round(int(n or 0) / 1_048_576, 1)


ABANDONED = ("Video_005",)      # колдонуучунун чечими 2026-11-24: кино-окуя сынагы улантылбайт
INTERMEDIATE = ("music_bed.wav", "voice_raw.wav", "gap.wav")


def classify(path: str, name: str, mime: str) -> tuple[str, str]:
    """→ (категория, себеби). Шектүү болсо ар дайым САКТОО тарапка (run #45537869128'ден кийин катаалдатылды:
    даяр видеолор TEST/Final_Videos'то турат; Colab доорундагы `video_001_*` кичине тамга менен)."""
    ext = os.path.splitext(name)[1].lower()
    parts = path.split("/")
    root = parts[0] if parts else ""
    low = path.lower()
    if "video_001" in low:
        return "protected", "Video_001 (сценарий/аудио/клиптер/MP4) — өзгөртүлбөйт"
    if mime.startswith("application/vnd.google-apps") or ext in KEEP_EXT:
        return "protected", "сценарий/метадайын/код/лицензия/журнал (кичине, келечекте керек)"
    if any(a in path for a in ACTIVE):
        return "active", "иштеп жаткан сынак видеосу"
    if root not in SYSTEM_ROOTS:
        return "user", "системанын папкасынан тышкары — колдонуучу өзү чечет"
    if "Final_Videos" in parts:
        return "protected", "даяр видео (Final_Videos) — бир видеонун эки версиясы болсо, кайсынысы калаарын сиз чечесиз"
    if "Thumbnails" in parts:
        return "protected", "даяр обложка"
    if any(x in parts for x in ("Licenses", "Music", "Sound_Effects", "SFX", "Sfx", "sfx")):
        return "protected", "лицензия / музыка / үн эффекттеринин китепканасы (кийинки видеолор колдонот)"
    if ext not in MEDIA_EXT:
        return "protected", "медиа эмес файл"
    if any(a in path for a in ABANDONED):
        return "candidate", "Video_005 — токтотулган кино-окуя сынагы, даяр видео жок"
    if "/audio/chunks/" in path + "/" or name in INTERMEDIATE:
        return "candidate", "аралык аудио (бөлүктөр/фон/чийки үн) — акыркы MP4'тө бар, кайра түзүлөт"
    if any(x in parts for x in ("_preview", "_diagnose", "_voice_test", "test_2k")):
        return "candidate", "сынак/превью/диагностика файлы"
    if "thumbnails" in parts and name.startswith("f_"):
        return "candidate", "обложка үчүн алынган кадр (обложка өзү Thumbnails/'та)"
    if len(parts) > 1 and parts[-2] == "Audio" and name.endswith("_voice.wav"):
        return "candidate", "Projects/…/audio/voice.wav'дын көчүрмөсү (бир нускасы калат)"
    if name == "voice.wav":
        return "protected", "даяр видеонун диктор үнү (бир нускасы)"
    return "keep_review", "эски/белгисиз медиа — кошумча текшерүүсүз өчүрүлбөйт, сиз чечесиз"


class Inventory:
    def __init__(self, svc):
        self.svc = svc

    def _list(self, q: str, fields: str) -> list[dict]:
        out, tok = [], None
        while True:
            r = self.svc.files().list(q=q, fields=f"nextPageToken, files({fields})", pageSize=1000,
                                      pageToken=tok, spaces="drive").execute(num_retries=3)
            out += r.get("files", [])
            tok = r.get("nextPageToken")
            if not tok:
                return out

    def quota(self) -> dict:
        q = self.svc.about().get(fields="storageQuota").execute(num_retries=3)["storageQuota"]
        return {k: int(v) for k, v in q.items()}

    def collect(self) -> dict:
        folders = {f["id"]: f for f in self._list(f"mimeType = '{FOLDER}' and trashed = false", "id,name,parents")}

        def path_of(pid: str | None, depth=0) -> str:
            if not pid or pid not in folders or depth > 30:
                return ""
            f = folders[pid]
            up = path_of((f.get("parents") or [None])[0], depth + 1)
            return f"{up}/{f['name']}" if up else f["name"]
        files = self._list(f"mimeType != '{FOLDER}' and trashed = false and 'me' in owners",
                           "id,name,size,mimeType,parents,modifiedTime,createdTime,md5Checksum")
        trash = self._list("trashed = true and 'me' in owners", "id,name,size,mimeType,modifiedTime")
        rows = []
        for f in files:
            folder = path_of((f.get("parents") or [None])[0]) or "(Менин Drive'ым — тамыр)"
            cat, why = classify(folder + "/" + f["name"], f["name"], f["mimeType"])
            rows.append({"id": f["id"], "name": f["name"], "folder": folder, "mb": mb(f.get("size")), "bytes": int(f.get("size") or 0),
                         "modified": f.get("modifiedTime", "")[:10], "created": f.get("createdTime", "")[:10], "mime": f["mimeType"], "md5": f.get("md5Checksum"), "cat": cat,
                         "why": why})
        # кайталанган көчүрмө (бир эле md5, бирөөсү protected эмес) — белгилейт гана
        by_md5: dict = {}
        for r in rows:
            if r["md5"] and r["bytes"] > 5_000_000:
                by_md5.setdefault(r["md5"], []).append(r)
        for group in by_md5.values():
            if len(group) > 1:
                for r in group:
                    r["duplicate_of"] = [f"{x['folder']}/{x['name']}" for x in group if x is not r]
        return {"rows": rows, "trash": [{"name": t["name"], "mb": mb(t.get("size")),
                                         "modified": t.get("modifiedTime", "")[:10]} for t in trash]}


VIDEO_001_PARTS = {
    "сценарий": lambda p, n: "/Video_001/script/" in p + "/" and n.endswith(".txt"),
    "аудио (диктор)": lambda p, n: "/Video_001/audio" in p + "/" and n.endswith((".wav", ".mp3", ".json")),
    "субтитрлер": lambda p, n: "/Video_001/subtitles" in p + "/" and n.endswith((".srt", ".ass")),
    "клиптердин тизмеси/лицензиялары": lambda p, n: ("/Video_001/clips" in p + "/" and n.endswith(".json"))
    or n.startswith("Video_001_clips") or ("Licenses" in p and "Video_001" in n),
    "акыркы MP4": lambda p, n: n == "Video_001.mp4",
}


def check_video_001(rows: list[dict]) -> dict:
    out = {}
    for part, test in VIDEO_001_PARTS.items():
        hits = [r for r in rows if test(r["folder"], r["name"])]
        out[part] = [f"{r['folder']}/{r['name']} ({r['mb']} МБ)" for r in hits]
    return out


def report(q: dict, data: dict) -> str:
    rows, trash = data["rows"], data["trash"]
    G = 1024 ** 3
    lines = ["# 🗂 Drive инвентаризациясы (окуу гана — эч нерсе өчүрүлгөн жок)", "",
             f"- Лимит: {q.get('limit', 0) / G:.2f} ГБ; колдонулду: {q.get('usage', 0) / G:.2f} ГБ",
             f"- Анын ичинде Drive: {q.get('usageInDrive', 0) / G:.2f} ГБ; Себет: {q.get('usageInDriveTrash', 0) / G:.2f} ГБ; "
             f"Gmail+Photos (Drive'дан тышкары): {(q.get('usage', 0) - q.get('usageInDrive', 0)) / G:.2f} ГБ", ""]
    cats = {}
    for r in rows:
        c = cats.setdefault(r["cat"], [0, 0.0])
        c[0] += 1
        c[1] += r["mb"]
    names = {"protected": "🔒 Маанилүү (сакталат)", "candidate": "🧪 Тесттик (өчүрүүгө СУНУШ)",
             "user": "👤 Системадан тышкары (сиз чечесиз)", "active": "▶️ Иштеп жаткан (тийилбейт)",
             "keep_review": "🔎 Системанын медиасы (кошумча текшерүү)"}
    lines += ["## Категориялар", "| Категория | Файл | МБ |", "|---|---|---|"]
    for k, (n, s) in sorted(cats.items(), key=lambda x: -x[1][1]):
        lines.append(f"| {names.get(k, k)} | {n} | {s:.0f} |")
    for k in ("candidate", "user", "keep_review"):
        sel = sorted((r for r in rows if r["cat"] == k), key=lambda r: -r["bytes"])
        if not sel:
            continue
        lines += ["", f"## {names[k]} — толук тизме ({len(sel)} файл, {sum(r['mb'] for r in sel):.0f} МБ)",
                  "| # | Файл | МБ | Папка | Өзгөргөн | Эскертүү |", "|---|---|---|---|---|---|"]
        for i, r in enumerate(sel, 1):
            dup = f"көчүрмөсү бар: {r['duplicate_of'][0]}" if r.get("duplicate_of") else r["why"]
            lines.append(f"| {i} | {r['name']} | {r['mb']} | {r['folder']} | {r['modified']} | {dup} |")
    prot = [r for r in rows if r["cat"] == "protected"]
    lines += ["", f"## 🔒 Маанилүү файлдар: {len(prot)} файл, {sum(r['mb'] for r in prot):.0f} МБ (папкалар боюнча)",
              "| Папка | Файл | МБ |", "|---|---|---|"]
    byf: dict = {}
    for r in prot:
        x = byf.setdefault(r["folder"], [0, 0.0])
        x[0] += 1
        x[1] += r["mb"]
    for f, (n, s) in sorted(byf.items(), key=lambda x: -x[1][1])[:60]:
        lines.append(f"| {f} | {n} | {s:.1f} |")
    if trash:
        lines += ["", f"## 🗑 Себетте: {len(trash)} файл, {sum(t['mb'] for t in trash):.0f} МБ (орун ээлеп турат)",
                  "| Файл | МБ | Өзгөргөн |", "|---|---|---|"]
        for t in sorted(trash, key=lambda t: -t["mb"])[:80]:
            lines.append(f"| {t['name']} | {t['mb']} | {t['modified']} |")
    v1 = check_video_001(rows)
    lines += ["", "## Video_001 толуктугу"]
    for part, hits in v1.items():
        lines.append(f"- {'✅' if hits else '❌'} {part}: " + ("; ".join(hits[:4]) + (" …" if len(hits) > 4 else "")
                                                         if hits else "ТАБЫЛГАН ЖОК"))
    return "\n".join(lines) + "\n"


def main() -> int:
    from .drive import DriveClient
    drive = DriveClient.from_env()
    if drive is None:
        print("❌ GDRIVE_* секреттери жок")
        return 2
    inv = Inventory(drive.svc)
    q = inv.quota()
    data = inv.collect()
    md = report(q, data)
    out = Path(os.environ.get("INV_OUT", "drive_inventory"))
    out.mkdir(parents=True, exist_ok=True)
    (out / "inventory.md").write_text(md, encoding="utf-8")
    (out / "inventory.json").write_text(json.dumps({"quota": q, **data}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(md)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as f:
            f.write(md[:900_000])
    return 0


if __name__ == "__main__":
    sys.exit(main())
