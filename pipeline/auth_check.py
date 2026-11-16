"""Google OAuth / Drive авторизациясын текшерүү (GitHub Actions'та иштейт).

    python -m pipeline.auth_check

ОКУУ жана өзүнүн убактылуу файлын түзүп-өчүрүү гана. OAuth жөндөөлөрүнө,
GitHub Secrets'ке, колдонуучунун бар файлдарына ТИЙБЕЙТ.

Текшерет:
  1. Secrets форматы (мааниси басылбайт, туура форматта экени гана).
  2. Refresh token → access token алмашуусу. Google'дун жообундагы
     `refresh_token_expires_in` талаасы бар болсо — токен «Testing» режиминде
     чыгарылган (7 күндө өчөт); жок болсо — Production токени.
  3. tokeninfo: берилген уруксаттар (scope), токен ушул клиентке таандыкпы.
  4. Токенди кайра-кайра жаңыртуу (кэшсиз) — эки жолу.
  5. Чыныгы Drive сыноосу: 20 МБ файлды (resumable, бир нече бөлүк менен) жүктөө,
     MD5 текшерүү, кайра жүктөп алуу, салыштыруу, өзүнүн сыноо папкасын өчүрүү.
Ачкычтар жана access token эч качан басылбайт; email жашырылат.
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import sys
import tempfile
import time
from pathlib import Path

import requests

from .drive import SCOPES, TOKEN_URI, DriveClient, _secret, explain_http_error, mask_email

RESULTS: list[dict] = []


def rec(name: str, ok: bool | None, note: str = "") -> None:
    RESULTS.append({"check": name, "ok": ok, "note": note})
    icon = {True: "✅", False: "❌", None: "ℹ️"}[ok]
    print(f"{icon} {name}: {note}", flush=True)


def analyze_token_response(j: dict) -> dict:
    """Google'дун token endpoint жообун талдайт (эч кандай ачкыч кайтарбайт)."""
    ok = "access_token" in j
    rte = j.get("refresh_token_expires_in")
    if not ok:
        mode = "белгисиз (токен кабыл алынган жок)"
    elif rte is not None:
        mode = "TESTING токени (мөөнөтү чектүү)"
    else:
        mode = "PRODUCTION токени (7 күндүк чек жок)"
    return {
        "ok": ok,
        "error": j.get("error"),
        "error_description": (j.get("error_description") or "")[:160],
        "refresh_token_expires_in_sec": int(rte) if rte is not None else None,
        "refresh_token_expires_in_days": round(int(rte) / 86400, 2) if rte is not None else None,
        "mode": mode,
        "scopes": sorted((j.get("scope") or "").split()),
        "token_type": j.get("token_type"),
        "access_expires_in": j.get("expires_in"),
    }


def check_formats(cid: str, secret: str, token: str) -> None:
    rec("GDRIVE_CLIENT_ID форматы", cid.endswith(".apps.googleusercontent.com") and "-" in cid,
        f"uзундугу {len(cid)}, '.apps.googleusercontent.com' менен аяктайт: "
        f"{cid.endswith('.apps.googleusercontent.com')}")
    rec("GDRIVE_CLIENT_SECRET форматы", secret.startswith("GOCSPX-") and len(secret) >= 30,
        f"узундугу {len(secret)}, 'GOCSPX-' менен башталат: {secret.startswith('GOCSPX-')}")
    rec("GDRIVE_REFRESH_TOKEN форматы", token.startswith("1//") and len(token) >= 40,
        f"узундугу {len(token)}, '1//' менен башталат (refresh token): {token.startswith('1//')}; "
        f"'ya29.' (access token) эмес: {not token.startswith('ya29.')}")


def check_token_exchange(cid: str, secret: str, token: str) -> str | None:
    r = requests.post(TOKEN_URI, data={"client_id": cid, "client_secret": secret,
                                       "refresh_token": token, "grant_type": "refresh_token"},
                      timeout=30)
    try:
        j = r.json()
    except ValueError:
        rec("Token алмашуусу", False, f"HTTP {r.status_code}, JSON эмес жооп")
        return None
    info = analyze_token_response(j)
    if not info["ok"]:
        rec("Token алмашуусу", False,
            f"HTTP {r.status_code}: {info['error']} — {info['error_description']}")
        return None
    rec("Token алмашуусу", True, f"HTTP {r.status_code}, access token {info['access_expires_in']} сек")
    if info["refresh_token_expires_in_sec"] is not None:
        rec("OAuth режими (токенден)", False,
            f"{info['mode']}: refresh_token_expires_in = {info['refresh_token_expires_in_sec']} сек "
            f"(~{info['refresh_token_expires_in_days']} күн) — токен Testing режиминде чыгарылган, "
            f"Production'до ЖАҢЫ токен алуу керек")
    else:
        rec("OAuth режими (токенден)", True, f"{info['mode']}: `refresh_token_expires_in` талаасы жок")
    drive_ok = any(s_ == SCOPES[0] for s_ in info["scopes"])
    rec("Уруксат (scope)", drive_ok, ", ".join(info["scopes"]) or "жок")
    return j.get("access_token")


def check_tokeninfo(access: str, cid: str) -> None:
    r = requests.get("https://oauth2.googleapis.com/tokeninfo", params={"access_token": access},
                     timeout=30)
    if r.status_code != 200:
        rec("tokeninfo", False, f"HTTP {r.status_code}")
        return
    j = r.json()
    aud_ok = j.get("aud") == cid or j.get("azp") == cid
    rec("Токен ушул клиентке таандык", aud_ok, f"aud дал келет: {aud_ok}")
    rec("Токендин калган өмүрү", None, f"{j.get('expires_in')} сек")


def check_refresh_twice(drive: DriveClient) -> None:
    from google.auth.transport.requests import Request

    tokens = []
    for _ in range(2):
        drive.creds.token = None            # кэшти тазалап, чыныгы жаңыртууга мажбурлайбыз
        drive.creds.refresh(Request())
        tokens.append(drive.creds.token)
        time.sleep(1)
    ok = all(tokens) and tokens[0] != tokens[1]
    rec("Токенди кайра-кайра жаңыртуу (2 жолу)", ok,
        f"эки жолу тең ийгиликтүү, жаңы access token алынды: {ok}")


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def check_drive(drive: DriveClient, root_name: str, size_mb: int = 20) -> None:
    email = drive.whoami()
    rec("Drive аккаунту", True, mask_email(email))
    try:
        q = drive.svc.about().get(fields="storageQuota").execute(num_retries=3)["storageQuota"]
        limit, used = int(q.get("limit", 0) or 0), int(q.get("usage", 0))
        free = f"{(limit - used) / 1e9:.1f} ГБ бош" if limit else "чексиз/белгисиз"
        rec("Drive орду", True, f"колдонулган {used / 1e9:.1f} ГБ, {free}")
    except Exception as e:
        rec("Drive орду", None, f"окулган жок: {type(e).__name__}")

    root = drive.find_path(root_name)
    rec(f"{root_name}/ папкасы", root is not None, "табылды" if root else "жок")
    if root is None:
        return

    folder_name = f"_auth_test_{secrets.token_hex(4)}"
    folder_id = drive.create_folder(folder_name, root)
    rec("Папка түзүү", True, f"{root_name}/{folder_name}")
    file_id = None
    try:
        with tempfile.TemporaryDirectory() as d:
            local = Path(d) / "auth_test.bin"
            with open(local, "wb") as f:
                for _ in range(size_mb):
                    f.write(os.urandom(1 << 20))
            want_md5 = hashlib.md5(local.read_bytes()).hexdigest()
            t = time.time()
            file_id = drive.upload_file(local, folder_id)
            up = time.time() - t
            meta = drive.svc.files().get(fileId=file_id, fields="size,md5Checksum").execute()
            same = meta.get("md5Checksum") == want_md5 and int(meta.get("size", 0)) == local.stat().st_size
            rec(f"Жүктөө ({size_mb} МБ, resumable, бөлүк 8 МБ)", same,
                f"{up:.1f} сек ({size_mb / up:.1f} МБ/сек), өлчөмү жана MD5 Drive'дагы менен дал келет: {same}")
            back = Path(d) / "back.bin"
            t = time.time()
            drive.download_file(file_id, back)
            down = time.time() - t
            rec("Кайра жүктөп алуу", sha256(back) == sha256(local),
                f"{down:.1f} сек, SHA-256 бирдей: {sha256(back) == sha256(local)}")
    finally:
        # ӨЗҮМ түзгөн сыноо файлын/папкасын гана өчүрөбүз (колдонуучунун файлдарына тийбейбиз)
        try:
            if file_id:
                drive.svc.files().delete(fileId=file_id).execute()
            drive.svc.files().delete(fileId=folder_id).execute()
            left = drive.list_children(root)
            gone = folder_name not in [x["name"] for x in left]
            rec("Сыноо файлын тазалоо", gone, "өзүнүн убактылуу папкасы өчүрүлдү")
        except Exception as e:
            rec("Сыноо файлын тазалоо", False,
                f"өчүрүлгөн жок ({type(e).__name__}) — Drive'да `{folder_name}` папкасын өзүңүз өчүрүңүз")


def main() -> int:
    cid, secret, token = (_secret(n) for n in ("GDRIVE_CLIENT_ID", "GDRIVE_CLIENT_SECRET",
                                                "GDRIVE_REFRESH_TOKEN"))
    missing = [n for n, v in (("GDRIVE_CLIENT_ID", cid), ("GDRIVE_CLIENT_SECRET", secret),
                              ("GDRIVE_REFRESH_TOKEN", token)) if not v]
    if missing:
        rec("GitHub Secrets", False, f"жок: {', '.join(missing)}")
        return finish(2)
    rec("GitHub Secrets", True, "үчөө тең бар (мааниси көрсөтүлбөйт)")
    check_formats(cid, secret, token)

    access = check_token_exchange(cid, secret, token)
    if access:
        check_tokeninfo(access, cid)
        try:
            drive = DriveClient(cid, secret, token)
            check_refresh_twice(drive)
            check_drive(drive, os.environ.get("YTA_DRIVE_FOLDER", "YouTube_Auto_TEST"),
                        int(os.environ.get("AUTH_TEST_MB", "20")))
        except Exception as e:
            rec("Drive сыноосу", False, explain_http_error(e))
    return finish(0 if all(r["ok"] is not False for r in RESULTS) else 1)


def finish(code: int) -> int:
    md = ["## 🔐 Google OAuth / Drive авторизациясын текшерүү", "",
          "| Текшерүү | | Жыйынтык |", "|---|---|---|"]
    for r in RESULTS:
        icon = {True: "✅", False: "❌", None: "ℹ️"}[r["ok"]]
        md.append(f"| {r['check']} | {icon} | {str(r['note']).replace('|', '/')} |")
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        Path(summary).write_text("\n".join(md) + "\n", encoding="utf-8")
    Path("auth_report.json").write_text(json.dumps(RESULTS, ensure_ascii=False, indent=1),
                                        encoding="utf-8")
    print("\n" + ("✅ Баары ийгиликтүү" if code == 0 else "❌ Кызыл пункттар бар"))
    return code


if __name__ == "__main__":
    sys.exit(main())
