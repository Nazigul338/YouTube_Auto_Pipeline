"""GitHub Actions үчүн кирүү чекити (Colab талап кылынбайт).

    python -m pipeline.ci --topic "..."            # жаңы видео (Video_NNN)
    python -m pipeline.ci --video-id Video_003     # токтоп калган видеону улантуу
    python -m pipeline.ci --check                  # жөндөөнү текшерүү

Иштеши:
  1. Drive'да YouTube_Auto/ түзүлүшүн даярдайт, реестрди окуйт;
  2. жаңы ID берет же Projects/<ID>/ ичинен мурунку абалды жүктөйт;
  3. Music/ китепканасын жүктөйт;
  4. этаптарды аткарат; АР БИР этаптан кийин абал Drive'га сакталат;
  5. GitHub'дын Summary бетине жыйынтык жазат.

Чыгуу коду: 0 — ката жок, 1 — этап катага учурады, 2 — жөндөө катасы.
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .config import get_secret, load_config
from .drive import (DriveClient, _secret, check_client_credentials, drive_secrets_present,
                    explain_http_error, mask_email)
from .music import describe_report, library_report
from .runner import _make_logger, execute
from .stages import STAGE_NAMES, STAGES
from .stages.base import Context
from .stages.s0_check import OPTIONAL_SECRETS, REQUIRED_SECRETS
from .state import DONE, FAILED, STATUS_ICON, VideoState
from .storage import (PROJECT_SUBFOLDERS, ROOT_NAME, DriveStore, Store, next_video_id, now)

DRIVE_ROOT_NAME = os.environ.get("YTA_DRIVE_FOLDER", ROOT_NAME)


def _summary(text: str) -> None:
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a", encoding="utf-8") as f:
            f.write(text + "\n")


def prepare_folder(folder: Path) -> None:
    for sub in PROJECT_SUBFOLDERS:
        (folder / sub).mkdir(parents=True, exist_ok=True)


REWORK_FROM = "s4_subtitles"
MAX_REWORKS = 2


def needs_rework(state, entry: dict) -> bool:
    """QA окшоштук таап концепцияны жокко чыгарганбы (edit_brief жок, rejected_briefs бар)?"""
    stages = state.data.get("stages", {})
    return ("s9_qa" in stages and state.status("s9_qa") == FAILED and not entry.get("edit_brief")
            and bool(entry.get("rejected_briefs")) and entry.get("reworks", 0) < MAX_REWORKS)


def auto_rework(ctx, state, entry: dict, rerun, log):
    """ОРИГИНАЛДУУЛУК: видео мурункуга окшош чыкса — ЖАҢЫ концепция түзүлүп, монтаж s4'төн кайра (≤MAX_REWORKS)."""
    while needs_rework(state, entry):
        entry["reworks"] = entry.get("reworks", 0) + 1
        entry.setdefault("rework_log", []).append({"n": entry["reworks"], "reason": entry["rejected_briefs"][-1]})
        log(f"🔁 Видео мурунку видеого окшош чыкты ({entry['rejected_briefs'][-1].get('reason', '')[:120]}) — "
            f"жаңы монтаж концепциясы менен автоматтык кайра монтаж №{entry['reworks']} "
            f"({entry.get('rework_from', REWORK_FROM)}'тан)")
        state = rerun()
    return state


def run_ci(topic: str, niche: str, workdir: Path, *, store: Store | None,
           video_id: str | None = None, rerun_from: str | None = None,
           stop_after: str | None = None, services: dict | None = None) -> int:
    if store is None:
        msg = ("❌ Google Drive туташкан эмес (GDRIVE_* ачкычтары жок). Видео сакталбай калбашы "
               "үчүн иш башталган жок.")
        print(msg)
        _summary(msg)
        return 2
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    cfg = load_config(niche, drive_root=str(workdir))

    print(f"☁️  Сактоочу жай: {store.describe()}")
    store.ensure_layout()
    registry = store.load_registry()
    registry.setdefault("videos", {})

    if video_id:
        video_id = video_id.strip()
        folder = workdir / "Projects" / video_id
        if not store.pull_project(video_id, folder) or not VideoState.exists(folder):
            msg = f"❌ {video_id} табылган жок (Drive → {DRIVE_ROOT_NAME}/Projects/{video_id})."
            print(msg)
            _summary(msg)
            return 2
        prepare_folder(folder)
        state = VideoState.load(folder)
        state.ensure_stages(STAGE_NAMES)
        state.save()
        topic = state.topic
        resumed = True
    else:
        topic = (topic or "").strip()
        if not topic:
            print("❌ Тема бош. Workflow'до «topic» талаасын толтуруңуз.")
            return 2
        video_id = next_video_id(registry)
        registry["videos"][video_id] = {"topic": topic, "niche": niche, "created": now(),
                                        "status": "in_progress"}
        store.save_registry(registry)  # ID'ни дароо ээлеп коёбуз
        folder = workdir / "Projects" / video_id
        prepare_folder(folder)
        state = VideoState.create(folder, topic, niche, STAGE_NAMES)
        state.data["video_id"] = video_id
        state.save()
        resumed = False

    entry0 = registry["videos"].setdefault(video_id, {"topic": topic, "niche": niche})
    entry0["stopped_by_user"] = bool(stop_after)   # атайын токтотулган сыноо автоматтык уланбайт
    n = store.pull_music(cfg.music_root)
    from . import sfx as _sfx

    n_sfx = store.pull_sfx(Path(cfg.drive_root) / _sfx.FOLDER) if _sfx.enabled(store) else None
    log = _make_logger(folder)
    log("=" * 56)
    log(f"🎬 {video_id}: {topic}")
    log("↩️  Мурунку абалдан улантылат." if resumed else "🆕 Жаңы видео.")
    log(f"🎵 Музыка китепканасы: {n} файл")
    if n_sfx is not None:
        log(f"🔊 Үн эффекттеринин китепканасы (СЫНАК): {n_sfx} файл")
    log("=" * 56)

    ctx = Context(cfg=cfg, state=state, folder=folder, log=log, video_id=video_id,
                  store=store, registry=registry, services=services or {})

    def checkpoint(st: VideoState) -> None:
        entry = registry["videos"].setdefault(video_id, {"topic": topic})
        entry["status"] = _status(st)
        entry["updated"] = now()
        failed = next((n for n in STAGE_NAMES if st.status(n) == FAILED), None)
        entry["failure_kind"] = st.stage(failed).get("kind", "error") if failed else None
        store.push_project(folder, video_id, log=lambda m: None)
        store.save_registry(registry)
        log_file = folder / "logs" / "run.log"
        if log_file.exists():
            store.publish("Logs", log_file, f"{video_id}.log")

    state = execute(ctx, rerun_from=rerun_from, stop_after=stop_after, checkpoint=checkpoint)
    ent_ = registry["videos"].get(video_id, {})
    state = auto_rework(ctx, state, ent_,
                        lambda: execute(ctx, rerun_from=ent_.pop("rework_from", REWORK_FROM), stop_after=stop_after,
                                        checkpoint=checkpoint), log)
    _write_summary(state, video_id, registry["videos"].get(video_id, {}).get("final_url"))
    return 1 if any(state.status(n) == FAILED for n in STAGE_NAMES) else 0


def _status(state: VideoState) -> str:
    if any(state.status(n) == FAILED for n in STAGE_NAMES):
        return "failed"
    if all(state.status(n) == DONE for n in STAGE_NAMES):
        return "ready"
    return "in_progress"


def _write_summary(state: VideoState, video_id: str, url: str | None = None) -> None:
    titles = {s.name: s.title for s in STAGES}
    lines = [f"## 🎬 {video_id}: {state.topic}", ""]
    if url and _status(state) == "ready":    # шилтеме эң башында — телефондон бир басуу менен ачылат
        lines += [f"### ▶️ [ВИДЕОНУ КӨРҮҮ (Google Drive)]({url})", "", url, ""]
    for name in STAGE_NAMES:
        st = state.stage(name)
        err = f" — `{st['error'].splitlines()[0][:200]}`" if st["status"] == FAILED else ""
        lines.append(f"- {STATUS_ICON.get(st['status'], '?')} {titles[name]}{err}")
    lines += ["", f"📁 Drive: `{DRIVE_ROOT_NAME}/Projects/{video_id}/`"]
    status = _status(state)
    if status == "ready":
        lines.append(f"✅ Даяр видео: `Final_Videos/{video_id}.mp4`" + (f" — {url}" if url else ""))
    else:
        lines.append(f"\nℹ️ Улантуу үчүн: Run workflow → **video_id** = `{video_id}`")
    _summary("\n".join(lines))


# ---------------------------------------------------------------- авто-улантуу
RESUMABLE_KINDS = {"quota", "transient"}   # чыныгы каталар (error) автоматтык уланбайт
MAX_AUTO_RESUMES = 6
MAX_AGE_DAYS = 10
STALE_MINUTES = 20      # in_progress ушундан эски болсо — иш үзүлгөн (убакыт бүткөн/жокко чыгарылган)


def _parse(ts: str | None) -> datetime | None:
    try:
        return datetime.fromisoformat(ts) if ts else None
    except ValueError:
        return None


def find_pending(registry: dict, now_dt: datetime | None = None) -> str | None:
    """Автоматтык улантууга татыктуу эң эски видеонун ID'си (же None)."""
    now_dt = now_dt or datetime.now(timezone.utc)
    for vid, v in sorted(registry.get("videos", {}).items()):
        status = v.get("status")
        if "stopped_by_user" not in v:
            continue   # эски форматтагы жазуу (сыноодон калган) — автоматтык уланбайт
        if status not in ("failed", "in_progress") or v.get("stopped_by_user") or v.get("abandoned"):
            continue
        if v.get("auto_resumes", 0) >= MAX_AUTO_RESUMES:
            continue
        created = _parse(v.get("created"))
        if created and now_dt - created > timedelta(days=MAX_AGE_DAYS):
            continue
        if status == "failed" and v.get("failure_kind") not in RESUMABLE_KINDS:
            continue
        if status == "in_progress":
            updated = _parse(v.get("updated") or v.get("created"))
            if updated and now_dt - updated < timedelta(minutes=STALE_MINUTES):
                continue   # азыр башка иш аткарылып жатышы мүмкүн
        return vid
    return None


def run_resume(workdir: Path, *, store: Store | None, services: dict | None = None,
               now_dt: datetime | None = None) -> int:
    """Токтоп калган видеолордун эң эскисин улантат. Квота/убактылуу ката — тынч (0)."""
    if store is None:
        msg = "❌ Google Drive туташкан эмес (GDRIVE_* ачкычтары жок)."
        print(msg)
        _summary(msg)
        return 2
    store.ensure_layout()
    registry = store.load_registry()
    vid = find_pending(registry, now_dt)
    if vid is None:
        msg = "✅ Улантууга видео жок (баары даяр же улантууга татыктуу эмес)."
        print(msg)
        _summary("## 🔁 Автоматтык улантуу\n" + msg)
        return 0
    entry = registry["videos"][vid]
    entry["auto_resumes"] = entry.get("auto_resumes", 0) + 1
    store.save_registry(registry)
    print(f"🔁 Автоматтык улантуу: {vid} «{entry.get('topic', '')}» "
          f"(аракет {entry['auto_resumes']}/{MAX_AUTO_RESUMES}, мурунку абал: "
          f"{entry.get('status')}/{entry.get('failure_kind')})")
    code = run_ci("", entry.get("niche") or "motivation", Path(workdir), store=store,
                  video_id=vid, services=services)
    after = store.load_registry()["videos"].get(vid, {})
    if code == 1 and after.get("failure_kind") in RESUMABLE_KINDS:
        note = ("күнүмдүк квота дагы бүтүк" if after["failure_kind"] == "quota"
                else "убактылуу ката")
        msg = f"⏳ {vid}: {note} — кийинки автоматтык аракетте уланат (ката эмес)."
        print(msg)
        _summary(msg)
        return 0
    return code


# ---------------------------------------------------------------- --check
def run_check() -> int:
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

    key = get_secret("PIXABAY_API_KEY")
    if key:
        try:
            import requests
            r = requests.get("https://pixabay.com/api/videos/",
                             params={"key": key, "q": "sunrise", "per_page": 3}, timeout=30)
            note = f"HTTP {r.status_code}"
            if r.status_code != 200:
                note += f": {r.text.strip()[:80]}"
            add("Pixabay API", r.status_code == 200, note)
        except Exception as e:
            add("Pixabay API", False, type(e).__name__)

    key = get_secret("GOOGLE_API_KEY")
    if key:
        try:
            from google import genai
            client = genai.Client(api_key=key)
            names = [m.name for m, _ in zip(client.models.list(), range(1))]
            add("Gemini API", bool(names), "ачкыч иштейт")
        except Exception as e:
            add("Gemini API", False, type(e).__name__)

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
            music_id = drive.find_path(DRIVE_ROOT_NAME, "Music")
            add("Google Drive", True, f"аккаунт: {mask_email(email)}")
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


def _none(v: str | None) -> str | None:
    return None if v in (None, "", "none") else v


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="YouTube Auto Pipeline — GitHub Actions")
    p.add_argument("--check", action="store_true", help="жөндөөнү гана текшерүү")
    p.add_argument("--resume-pending", action="store_true",
                   help="токтоп калган видеолордун эң эскисин автоматтык улантуу")
    p.add_argument("--topic", default=os.environ.get("VIDEO_TOPIC", ""))
    p.add_argument("--video-id", default=os.environ.get("VIDEO_ID", ""))
    p.add_argument("--niche", default=os.environ.get("VIDEO_NICHE") or "psych_story")
    p.add_argument("--rerun-from", default=os.environ.get("VIDEO_RERUN_FROM") or None)
    p.add_argument("--stop-after", default=os.environ.get("VIDEO_STOP_AFTER") or None)
    p.add_argument("--workdir", default=os.environ.get("YTA_WORKDIR", "work"))
    args = p.parse_args(argv)

    if args.check:
        return run_check()
    store = None
    if drive_secrets_present():
        try:
            drive = DriveClient.from_env()
            print(f"☁️  Drive туташты: {mask_email(drive.whoami())}")
            store = DriveStore(drive, DRIVE_ROOT_NAME)
        except Exception as e:
            print(f"❌ Drive'га кирүү ишке ашкан жок: {explain_http_error(e)}")
            return 2
    if args.resume_pending:
        return run_resume(Path(args.workdir), store=store)
    return run_ci(args.topic, args.niche, Path(args.workdir), store=store,
                  video_id=_none(args.video_id), rerun_from=_none(args.rerun_from),
                  stop_after=_none(args.stop_after))


if __name__ == "__main__":
    sys.exit(main())
