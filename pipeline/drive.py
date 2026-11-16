"""Google Drive менен иштөө (GitHub Actions үчүн).

Colab'да Drive `/content/drive` катары туташат, ал эми GitHub Actions'та андай
мүмкүнчүлүк жок. Ошондуктан бул жерде Drive API аркылуу:
  - Music/ папкасындагы музыканы жүктөп алабыз;
  - даяр видео папкасын Videos/ ичине жүктөйбүз.

Кирүү үчүн 3 жашыруун маани (GitHub Secrets) керек:
  GDRIVE_CLIENT_ID, GDRIVE_CLIENT_SECRET, GDRIVE_REFRESH_TOKEN
"""

from __future__ import annotations

import io
import mimetypes
import os
import time
from pathlib import Path
from typing import Any, Callable

TOKEN_URI = "https://oauth2.googleapis.com/token"
SCOPES = ["https://www.googleapis.com/auth/drive"]
FOLDER_MIME = "application/vnd.google-apps.folder"
SECRET_NAMES = ("GDRIVE_CLIENT_ID", "GDRIVE_CLIENT_SECRET", "GDRIVE_REFRESH_TOKEN")
CHUNK = 8 * 1024 * 1024


class DriveError(Exception):
    pass


def _secret(name: str) -> str:
    """Ачкычтын четиндеги бош орун/жаңы сап Google'ду алдап коёт — кесебиз."""
    return os.environ.get(name, "").strip()


def drive_secrets_present() -> bool:
    return all(_secret(n) for n in SECRET_NAMES)


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("'", "\\'")


def check_client_credentials(client_id: str, client_secret: str,
                             post=None) -> tuple[bool, str]:
    """Client ID/Secret жарактуубу — токенсиз текшерүү.

    Google'го ЖАЛГАН refresh token жөнөтөбүз. Google адегенде клиентти текшерет:
      invalid_client → ID же Secret туура эмес;
      invalid_grant  → клиент туура (жалган токен гана четке кагылды).
    """
    if post is None:
        import requests
        post = requests.post
    resp = post(TOKEN_URI, data={
        "client_id": client_id, "client_secret": client_secret,
        "refresh_token": "dummy-token-for-client-check",
        "grant_type": "refresh_token"}, timeout=30)
    try:
        error = resp.json().get("error", "")
    except Exception:
        return False, f"Google күтүлбөгөн жооп берди (HTTP {resp.status_code})"
    if error == "invalid_grant":
        return True, "Client ID/Secret туура (Google кабыл алды)"
    if error == "invalid_client":
        return False, "Client ID же Client secret туура эмес"
    return False, f"белгисиз жооп: {error or resp.status_code}"


class DriveClient:
    def __init__(self, client_id: str, client_secret: str, refresh_token: str):
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build

        creds = Credentials(
            None,
            refresh_token=refresh_token,
            token_uri=TOKEN_URI,
            client_id=client_id,
            client_secret=client_secret,
            scopes=SCOPES,
        )
        self.creds = creds
        self.svc = build("drive", "v3", credentials=creds, cache_discovery=False)

    @classmethod
    def from_env(cls) -> "DriveClient | None":
        """Ачкычтар бар болсо — клиент, жок болсо — None."""
        if not drive_secrets_present():
            return None
        return cls(*(_secret(n) for n in SECRET_NAMES))

    # ---------- окуу ----------
    def whoami(self) -> str:
        about = self.svc.about().get(fields="user(emailAddress)").execute(num_retries=3)
        return about["user"]["emailAddress"]

    def list_children(self, parent_id: str) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        token = None
        while True:
            resp = self.svc.files().list(
                q=f"'{parent_id}' in parents and trashed = false",
                fields="nextPageToken, files(id, name, mimeType, size, md5Checksum)",
                pageSize=200,
                pageToken=token,
            ).execute(num_retries=3)
            items.extend(resp.get("files", []))
            token = resp.get("nextPageToken")
            if not token:
                return items

    def walk(self, folder_id: str, prefix: str = "") -> list[tuple[str, dict[str, Any]]]:
        """Папканы рекурсивдүү окуйт: [(салыштырмалуу жол, файл маалыматы), ...]."""
        out: list[tuple[str, dict[str, Any]]] = []
        for item in self.list_children(folder_id):
            rel = f"{prefix}{item['name']}"
            if item["mimeType"] == FOLDER_MIME:
                out += self.walk(item["id"], rel + "/")
            else:
                out.append((rel, item))
        return out

    def find_folder(self, name: str, parent_id: str = "root") -> str | None:
        resp = self.svc.files().list(
            q=(f"name = '{_escape(name)}' and '{parent_id}' in parents "
               f"and mimeType = '{FOLDER_MIME}' and trashed = false"),
            fields="files(id)",
            pageSize=1,
        ).execute(num_retries=3)
        files = resp.get("files", [])
        return files[0]["id"] if files else None

    def create_folder(self, name: str, parent_id: str = "root") -> str:
        meta = {"name": name, "mimeType": FOLDER_MIME, "parents": [parent_id]}
        return self.svc.files().create(body=meta, fields="id").execute(num_retries=3)["id"]

    def find_path(self, *names: str) -> str | None:
        """Папкалар чынжырын ТАБАТ (эч нерсе түзбөйт). Жок болсо None."""
        parent = "root"
        for name in names:
            parent = self.find_folder(name, parent)
            if parent is None:
                return None
        return parent

    def ensure_path(self, *names: str) -> str:
        """Папкалар чынжырын табат же түзөт: ("YouTube_Auto", "Music") → id."""
        parent = "root"
        for name in names:
            parent = self.find_folder(name, parent) or self.create_folder(name, parent)
        return parent

    # ---------- жүктөп алуу ----------
    def download_folder(self, folder_id: str, dest: Path,
                        only_ext: set[str] | None = None) -> list[Path]:
        """Папканы (ичиндегилери менен) жергиликтүү `dest` ичине жүктөйт."""
        from googleapiclient.http import MediaIoBaseDownload

        dest.mkdir(parents=True, exist_ok=True)
        saved: list[Path] = []
        for item in self.list_children(folder_id):
            if item["mimeType"] == FOLDER_MIME:
                saved += self.download_folder(item["id"], dest / item["name"], only_ext)
                continue
            if item["mimeType"].startswith("application/vnd.google-apps"):
                continue  # Google Docs/Sheets — аудио эмес
            if only_ext and Path(item["name"]).suffix.lower() not in only_ext:
                continue
            target = dest / item["name"]
            request = self.svc.files().get_media(fileId=item["id"])
            with open(target, "wb") as fh:
                dl = MediaIoBaseDownload(fh, request, chunksize=CHUNK)
                done = False
                while not done:
                    _, done = dl.next_chunk(num_retries=3)
            saved.append(target)
        return saved

    # ---------- жүктөө ----------
    def _resumable(self, make_req: Callable[[], Any], what: str, tries: int = 4,
                   sleep: Callable[[float], None] = time.sleep) -> str:
        """Resumable жүктөөнү аягына чыгарат. Тармак/окуу таймауту (мис. 516 МБ видео, `TimeoutError: The
        read operation timed out`) болсо — жүктөө башынан кайра башталат (4 жолу). Баары ишке ашпаса —
        TransientError (кийинки ишке киргизүүдө система ошол этаптан улантат)."""
        import httplib2
        from googleapiclient.errors import HttpError

        from .errors import TransientError

        last: Exception | None = None
        for attempt in range(tries):
            try:
                req = make_req()
                response = None
                while response is None:
                    _, response = req.next_chunk(num_retries=5)
                return response["id"]
            except HttpError as e:
                if getattr(e.resp, "status", 0) not in (429, 500, 502, 503, 504):
                    raise
                last = e
            except (OSError, httplib2.HttpLib2Error) as e:   # TimeoutError, ConnectionError, SSLError ⊂ OSError
                last = e
            if attempt < tries - 1:
                sleep(10 * (attempt + 1))
        raise TransientError(f"Drive'га жүктөө ({what}) {tries} аракеттен кийин ишке ашкан жок: "
                             f"{type(last).__name__}. Кайра иштетсеңиз улантылат.")

    def upload_file(self, local: Path, parent_id: str) -> str:
        """Файлды жүктөйт. Эч качан бар файлдын үстүнөн жазбайт."""
        from googleapiclient.http import MediaFileUpload

        mime = mimetypes.guess_type(local.name)[0] or "application/octet-stream"
        meta = {"name": local.name, "parents": [parent_id]}

        def make():
            media = MediaFileUpload(str(local), mimetype=mime, resumable=True, chunksize=CHUNK)
            return self.svc.files().create(body=meta, media_body=media, fields="id")

        return self._resumable(make, local.name)

    def upload_tree(self, local_dir: Path, parent_id: str,
                    log: Callable[[str], None] = print) -> str:
        """Жергиликтүү папканы Drive'га жүктөйт. Жаңы папканын id'син кайтарат."""
        folder_id = self.create_folder(local_dir.name, parent_id)
        for path in sorted(local_dir.iterdir()):
            if path.is_dir():
                self.upload_tree(path, folder_id, log)
            elif path.suffix != ".tmp":
                log(f"   ⬆ {local_dir.name}/{path.name}")
                self.upload_file(path, folder_id)
        return folder_id

    # ---------- системанын өз файлдары (жаңыртууга болот) ----------
    def find_file(self, name: str, parent_id: str) -> dict[str, Any] | None:
        resp = self.svc.files().list(
            q=(f"name = '{_escape(name)}' and '{parent_id}' in parents "
               f"and mimeType != '{FOLDER_MIME}' and trashed = false"),
            fields="files(id, name, size, md5Checksum)", pageSize=1,
        ).execute(num_retries=3)
        files = resp.get("files", [])
        return files[0] if files else None

    def update_file(self, file_id: str, local: Path) -> str:
        """Системанын ӨЗ файлын (state.json, лог ж.б.) жаңы мазмун менен алмаштырат."""
        from googleapiclient.http import MediaFileUpload

        mime = mimetypes.guess_type(local.name)[0] or "application/octet-stream"

        def make():
            media = MediaFileUpload(str(local), mimetype=mime, resumable=True, chunksize=CHUNK)
            return self.svc.files().update(fileId=file_id, media_body=media, fields="id")

        return self._resumable(make, local.name)

    def put_file(self, local: Path, parent_id: str, name: str | None = None) -> str:
        """Ушул аталыштагы файл бар болсо — жаңыртат, жок болсо — түзөт.

        Колдонуучунун файлдарына эмес, системанын папкаларына гана колдонулат.
        """
        name = name or local.name
        existing = self.find_file(name, parent_id)
        if existing:
            if existing.get("md5Checksum") and existing["md5Checksum"] == _md5(local):
                return existing["id"]
            return self.update_file(existing["id"], local)
        from googleapiclient.http import MediaFileUpload

        mime = mimetypes.guess_type(name)[0] or "application/octet-stream"

        def make():
            media = MediaFileUpload(str(local), mimetype=mime, resumable=True, chunksize=CHUNK)
            return self.svc.files().create(body={"name": name, "parents": [parent_id]},
                                           media_body=media, fields="id")

        return self._resumable(make, name)

    def sync_up(self, local_dir: Path, folder_id: str,
                skip: Callable[[str], bool] = lambda rel: False,
                log: Callable[[str], None] = lambda m: None) -> int:
        """Жергиликтүү папканы Drive'дагы папка менен шайкештейт (өзгөргөндөрүн гана).

        Салыштыруу MD5 боюнча. Drive'да гана бар файлдар ӨЧҮРҮЛБӨЙТ.
        """
        remote = {rel: item for rel, item in self.walk(folder_id)}
        folders: dict[str, str] = {"": folder_id}
        sent = 0
        for path in sorted(p for p in local_dir.rglob("*") if p.is_file()):
            rel = path.relative_to(local_dir).as_posix()
            if path.suffix == ".tmp" or skip(rel):
                continue
            item = remote.get(rel)
            if item and item.get("md5Checksum") == _md5(path):
                continue
            parent_rel = rel.rsplit("/", 1)[0] if "/" in rel else ""
            parent = self._ensure_rel(folder_id, parent_rel, folders)
            if item:
                self.update_file(item["id"], path)
            else:
                self.put_file(path, parent)
            sent += 1
            log(f"   ⬆ {rel}")
        return sent

    def _ensure_rel(self, root_id: str, rel: str, cache: dict[str, str]) -> str:
        if rel in cache:
            return cache[rel]
        parent_rel, _, name = rel.rpartition("/")
        parent = self._ensure_rel(root_id, parent_rel, cache)
        cache[rel] = self.find_folder(name, parent) or self.create_folder(name, parent)
        return cache[rel]

    def download_file(self, file_id: str, dest: Path) -> Path:
        from googleapiclient.http import MediaIoBaseDownload

        dest.parent.mkdir(parents=True, exist_ok=True)
        request = self.svc.files().get_media(fileId=file_id)
        with open(dest, "wb") as fh:
            dl = MediaIoBaseDownload(fh, request, chunksize=CHUNK)
            done = False
            while not done:
                _, done = dl.next_chunk(num_retries=3)
        return dest

    def download_tree(self, folder_id: str, dest: Path,
                      skip: Callable[[str], bool] = lambda rel: False) -> int:
        n = 0
        for rel, item in self.walk(folder_id):
            if item["mimeType"].startswith("application/vnd.google-apps") or skip(rel):
                continue
            self.download_file(item["id"], dest / rel)
            n += 1
        return n

    def read_json(self, name: str, parent_id: str, default: Any = None) -> Any:
        import json
        import tempfile

        item = self.find_file(name, parent_id)
        if not item:
            return default
        with tempfile.TemporaryDirectory() as d:
            p = self.download_file(item["id"], Path(d) / name)
            return json.loads(p.read_text(encoding="utf-8"))

    def write_json(self, name: str, parent_id: str, data: Any, compact: bool = False) -> str:
        import json
        import tempfile

        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / name
            text = (json.dumps(data, ensure_ascii=False, separators=(",", ":")) if compact
                    else json.dumps(data, ensure_ascii=False, indent=1))
            p.write_text(text, encoding="utf-8")
            return self.put_file(p, parent_id, name)


def _md5(path: Path) -> str:
    import hashlib

    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def mask_email(email: str) -> str:
    """Ачык логдо email толук көрүнбөсүн: nazi.t...@gmail.com → n***@gmail.com."""
    if "@" not in email:
        return "***"
    user, domain = email.split("@", 1)
    return f"{user[:1]}***@{domain}"


def explain_http_error(exc: Exception) -> str:
    """Drive/OAuth катасын түшүнүктүү кылып кыскартат (ачкычтарды көрсөтпөстөн)."""
    text = str(exc).lower()
    name = type(exc).__name__

    # Токен/клиент көйгөйлөрү (google.auth.exceptions.RefreshError)
    if "invalid_grant" in text:
        return (f"{name} — refresh token эскирген же жокко чыгарылган. "
                "OAuth Playground'до жаңы токен алып, GDRIVE_REFRESH_TOKEN'ди алмаштырыңыз "
                "(колдонмо 'Testing' режиминде болсо, токен 7 күндөн кийин өчөт)")
    if "invalid_client" in text or "unauthorized_client" in text:
        return (f"{name} — Client ID/Secret туура эмес, же токен башка клиент менен алынган. "
                "GDRIVE_CLIENT_ID, GDRIVE_CLIENT_SECRET жана токен бир эле клиентке таандык болсун")
    if "access_denied" in text:
        return f"{name} — уруксат берилген эмес (Audience → Test users'ке Gmail'иңизди кошуңуз)"
    if name == "RefreshError":
        return f"{name} — токенди жаңыртуу ишке ашкан жок (GDRIVE_* маанилерин текшериңиз)"

    status = getattr(getattr(exc, "resp", None), "status", None)
    hints = {
        400: "суроо туура эмес",
        401: "авторизация катасы: GDRIVE_* ачкычтарын текшериңиз",
        403: "уруксат жок, Drive API күйгүзүлгөн эмес, же квота бүттү",
        404: "папка/файл табылган жок",
    }
    return f"{name} (HTTP {status}) — {hints.get(status, 'белгисиз ката')}"
