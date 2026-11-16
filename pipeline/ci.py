"""GitHub Actions үчүн кирүү чекити.

    python -m pipeline.ci                # видео жасоо (VIDEO_TOPIC чөйрө өзгөрмөсүнөн)
    python -m pipeline.ci --check        # жөндөөнү гана текшерүү (ачкычтар, Drive)

Иштеши:
  1. Drive'дан Music/ папкасын жүктөп алат (бар болсо);
  2. runner.run() менен видеону жасайт (жаңы папкага);
  3. Видео папкасын (ийгиликтүү болсо да, ката болсо да) Drive'дагы
     YouTube_Auto/Videos/ ичине жүктөйт;
  4. GitHub'дын «Summary» бетине кыскача жыйынтык жазат.

Чыгуу коду: 0 — ката жок, 1 — кайсы бир этап катага учурады.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Any

from .config import Config, get_secret, load_config
from .drive import (DriveClient, _secret, check_client_credentials,
                    drive_secrets_present, explain_http_error)
from .runner import run
from .stages import STAGE_NAMES, STAGES
from .music import AUDIO_EXT as MUSIC_EXT, describe_report, library_report
from .stages.s0_check import OPTIONAL_SECRETS, REQUIRED_SECRETS
from .state import DONE, FAILED, STATUS_ICON, VideoState

DRIVE_ROOT_NAME = os.environ.get("YTA_DRIVE_FOLDER", "YouTube_Auto")


def _summary(text: str) -> None:
    """GitHub Actions Summary бетине жазуу (бар болсо)."""
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a", encoding="utf-8") as f:
            f.write(text + "\n")


def pull_music(drive: DriveClient, cfg: Config) -> int:
    folder_id = drive.find_path(DRIVE_ROOT_NAME, cfg.music_dirname)  # түзбөйт
    if folder_id is None:
        print(f"⚠ Drive'да {DRIVE_ROOT_NAME}/{cfg.music_dirname} папкасы жок — музыка өткөрүлдү")
        return 0
    files = drive.download_folder(folder_id, cfg.music_root, only_ext=MUSIC_EXT)
    return len(files)


def run_ci(topic: str, niche: str, workdir: Path, *,
           drive: DriveClient | None = None,
           stop_after: str | None = None) -> int:
    workdir.mkdir(parents=True, exist_ok=True)
    cfg = load_config(niche, drive_root=str(workdir))

    if drive is not None:
        try:
            print(f"☁️  Drive туташты: {drive.whoami()}")
            n = pull_music(drive, cfg)
            print(f"🎵 Музыка Drive'дан жүктөлдү: {n} файл")
        except Exception as e:
            print(f"⚠ Drive'дан музыканы алуу ишке ашкан жок: {explain_http_error(e)}")
    else:
        print("⚠ Drive ачкычтары (GDRIVE_*) жок — видео Drive'га жүктөлбөйт.")

    state = run(topic, niche, new=True, cfg=cfg, stop_after=stop_after)

    uploaded_to: str | None = None
    if drive is not None:
        try:
            videos_id = drive.ensure_path(DRIVE_ROOT_NAME, cfg.videos_dirname)
            print(f"\n☁️  Drive'га жүктөлүүдө: {DRIVE_ROOT_NAME}/{cfg.videos_dirname}/{state.folder.name}")
            drive.upload_tree(state.folder, videos_id)
            uploaded_to = f"{DRIVE_ROOT_NAME}/{cfg.videos_dirname}/{state.folder.name}"
            print("✅ Drive'га жүктөлдү")
        except Exception as e:
            print(f"❌ Drive'га жүктөө ишке ашкан жок: {explain_http_error(e)}")
            _write_summary(state, None)
            return 1

    _write_summary(state, uploaded_to)
    return 1 if any(state.status(n) == FAILED for n in STAGE_NAMES) else 0


def _write_summary(state: VideoState, uploaded_to: str | None) -> None:
    titles = {s.name: s.title for s in STAGES}
    lines = [f"## 🎬 {state.topic}", ""]
    for name in STAGE_NAMES:
        st = state.stage(name)
        err = f" — `{st['error'].splitlines()[0]}`" if st["status"] == FAILED else ""
        lines.append(f"- {STATUS_ICON.get(st['status'], '?')} {titles[name]}{err}")
    lines.append("")
    if uploaded_to:
        lines.append(f"📁 Drive: `{uploaded_to}`")
    else:
        lines.append("⚠️ Drive'га жүктөлгөн жок (GDRIVE_* ачкычтарын текшериңиз).")
    done = sum(1 for n in STAGE_NAMES if state.status(n) == DONE)
    if done < len(STAGE_NAMES) and not any(state.status(n) == FAILED for n in STAGE_NAMES):
        lines.append(f"\nℹ️ Система азырынча {done}/{len(STAGE_NAMES)} этапка чейин иштелип чыккан.")
    _summary("\n".join(lines))


# ---------------------------------------------------------------- --check
def run_check() -> int:
    """Жөндөөнү текшерүү: ачкычтар бар беле, Drive ачылабы, Pixabay жана Gemini жооп береби."""
    ok_all = True
    rows: list[tuple[str, bool, str]] = []

    def add(name: str, ok: bool, note: str = "") -> None:
        nonlocal ok_all
        ok_all &= ok
        rows.append((name, ok, note))

    for name in REQUIRED_SECRETS:
        add(name, bool(get_secret(name)), "" if get_secret(name) else "Secrets'те жок")
    for name in OPTIONAL_SECRETS:
        rows.append((name + " (милдеттүү эмес)", bool(get_secret(name)), ""))

    # Pixabay
    key = get_secret("PIXABAY_API_KEY")
    if key:
        try:
            import requests
            r = requests.get("https://pixabay.com/api/videos/",
                             params={"key": key, "q": "sunrise", "per_page": 3}, timeout=30)
            note = f"HTTP {r.status_code}"
            if r.status_code != 200:
                note += f": {r.text.strip()[:80]}"   # Pixabay ката тексти (ачкыч жок)
            add("Pixabay API", r.status_code == 200, note)
        except Exception as e:
            add("Pixabay API", False, type(e).__name__)

    # Gemini
    key = get_secret("GOOGLE_API_KEY")
    if key:
        try:
            from google import genai
            client = genai.Client(api_key=key)
            names = [m.name for m, _ in zip(client.models.list(), range(1))]
            add("Gemini API", bool(names), "ачкыч иштейт")
        except Exception as e:
            add("Gemini API", False, type(e).__name__)

    # Drive
    if drive_secrets_present():
        try:
            ok, note = check_client_credentials(_secret("GDRIVE_CLIENT_ID"),
                                                _secret("GDRIVE_CLIENT_SECRET"))
            add("Drive: Client ID + Secret", ok, note)
        except Exception as e:
            add("Drive: Client ID + Secret", False, type(e).__name__)
        try:
            drive = DriveClient.from_env()
            email = drive.whoami()
            music_id = drive.find_path(DRIVE_ROOT_NAME, "Music")  # окуу гана, түзбөйт
            add("Google Drive", True, f"аккаунт: {email}")
            if music_id is None:
                rows.append((f"Музыка ({DRIVE_ROOT_NAME}/Music)", False,
                             f"{DRIVE_ROOT_NAME}/Music папкасы жок — түзүп, музыка салыңыз"))
            else:
                rel = [r for r, _ in drive.walk(music_id)]
                total, by_source, unknown = library_report(rel)
                rows.append((f"Музыка ({DRIVE_ROOT_NAME}/Music)", total > 0,
                             describe_report(total, by_source, unknown)))
        except Exception as e:
            add("Google Drive", False, explain_http_error(e))
    else:
        add("Google Drive", False, "GDRIVE_CLIENT_ID / _SECRET / _REFRESH_TOKEN жок")

    print("\n📋 ЖӨНДӨӨНҮН ТЕКШЕРҮҮСҮ")
    md = ["## 📋 Жөндөөнү текшерүү", "", "| Текшерүү | Жыйынтык | Эскертүү |", "|---|---|---|"]
    for name, ok, note in rows:
        icon = "✅" if ok else "❌"
        print(f"  {icon} {name} {('— ' + note) if note else ''}")
        md.append(f"| {name} | {icon} | {note} |")
    _summary("\n".join(md))
    print("\n" + ("✅ Баары даяр!" if ok_all else "❌ Кызыл пункттарды оңдоңуз (docs/GITHUB_ACTIONS_SETUP.md)."))
    return 0 if ok_all else 1


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="YouTube Auto Pipeline — CI режими")
    p.add_argument("--check", action="store_true", help="жөндөөнү гана текшерүү")
    p.add_argument("--topic", default=os.environ.get("VIDEO_TOPIC", ""))
    p.add_argument("--niche", default=os.environ.get("VIDEO_NICHE") or "motivation")
    p.add_argument("--stop-after", default=os.environ.get("VIDEO_STOP_AFTER") or None)
    p.add_argument("--workdir", default=os.environ.get("YTA_WORKDIR", "work"))
    args = p.parse_args(argv)

    if args.check:
        return run_check()
    if not args.topic.strip():
        print("❌ Тема бош. Workflow'до «topic» талаасын толтуруңуз.")
        return 2
    stop_after = None if args.stop_after in (None, "", "none") else args.stop_after
    return run_ci(args.topic, args.niche, Path(args.workdir),
                  drive=DriveClient.from_env(), stop_after=stop_after)


if __name__ == "__main__":
    sys.exit(main())
