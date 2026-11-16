"""Видеолорду сактоочу жай: Google Drive (иштеп чыгаруу) же жергиликтүү папка (тесттер).

Drive'дагы түзүлүш (колдонуучунун талабы боюнча):

    YouTube_Auto/
      Projects/        ← ар видеонун иштөө папкасы (state.json, сценарий, сахналар, логдор…)
        _registry.json ← бардык видеолордун реестри жана тарыхы (кайталанбоо үчүн)
        Video_001/
      Scripts/         ← Video_001.txt
      Audio/           ← Video_001_voice.wav
      Subtitles/       ← Video_001.srt, Video_001.ass
      Clips/           ← Video_001_clips.json (клиптердин тизмеси, булактары)
      Music/           ← колдонуучунун китепканасы (система ӨЗГӨРТПӨЙТ)
      Final_Videos/    ← Video_001.mp4 (QA өткөндө гана)
      Logs/            ← Video_001.log
      Licenses/        ← Video_001_LICENSE.txt

Эскертүү: `YouTube_Auto/` ичиндеги башка эски папкаларга (Long_Videos ж.б.) система тийбейт.
"""

from __future__ import annotations

import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

ROOT_NAME = "YouTube_Auto"
FOLDERS = ["Projects", "Scripts", "Audio", "Subtitles", "Clips", "Music",
           "Final_Videos", "Logs", "Licenses"]
REGISTRY = "_registry.json"
PROJECT_SUBFOLDERS = ["script", "audio", "subtitles", "clips", "animation", "music",
                      "render", "logs"]


def heavy(rel: str) -> bool:
    """Drive'дагы Projects/ ичине жүктөлбөй турган оор/кайра түзүлө турган файлдар."""
    if rel.startswith("render/"):
        return True
    if rel.startswith(("clips/", "music/")) and not rel.endswith((".json", ".txt")):
        return True
    if rel in ("audio/mix.wav",):
        return True
    return rel.endswith(".mp4")


def video_id_from_number(n: int) -> str:
    return f"Video_{n:03d}"


def next_video_id(registry: dict) -> str:
    nums = [int(m.group(1)) for k in registry.get("videos", {})
            if (m := re.fullmatch(r"Video_(\d+)", k))]
    return video_id_from_number(max(nums, default=0) + 1)


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Store:
    """Жалпы интерфейс."""

    def ensure_layout(self) -> None: ...
    def load_registry(self) -> dict: ...
    def save_registry(self, registry: dict) -> None: ...
    def pull_project(self, video_id: str, dest: Path) -> bool: ...
    def push_project(self, src: Path, video_id: str, log: Callable[[str], None] = print) -> int: ...
    def pull_music(self, dest: Path) -> int: ...
    def publish(self, folder: str, local: Path, name: str) -> None: ...
    def read_text(self, folder: str, name: str) -> str | None: ...
    def describe(self) -> str: ...


class LocalStore(Store):
    """Тесттер жана жергиликтүү иштетүү үчүн: Drive'дын ордуна жөнөкөй папка."""

    def __init__(self, root: Path):
        self.root = Path(root) / ROOT_NAME

    def describe(self) -> str:
        return f"жергиликтүү папка {self.root}"

    def ensure_layout(self) -> None:
        for f in FOLDERS:
            (self.root / f).mkdir(parents=True, exist_ok=True)

    def load_registry(self) -> dict:
        p = self.root / "Projects" / REGISTRY
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {"videos": {}}

    def save_registry(self, registry: dict) -> None:
        p = self.root / "Projects" / REGISTRY
        p.write_text(json.dumps(registry, ensure_ascii=False, indent=1), encoding="utf-8")

    def pull_project(self, video_id: str, dest: Path) -> bool:
        src = self.root / "Projects" / video_id
        if not src.exists():
            return False
        shutil.copytree(src, dest, dirs_exist_ok=True)
        return True

    def push_project(self, src: Path, video_id: str, log: Callable[[str], None] = print) -> int:
        dst = self.root / "Projects" / video_id
        n = 0
        for p in src.rglob("*"):
            rel = p.relative_to(src).as_posix()
            if p.is_file() and not heavy(rel) and p.suffix != ".tmp":
                (dst / rel).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(p, dst / rel)
                n += 1
        return n

    def pull_music(self, dest: Path) -> int:
        src = self.root / "Music"
        if not src.exists():
            return 0
        shutil.copytree(src, dest, dirs_exist_ok=True)
        return sum(1 for p in dest.rglob("*") if p.is_file())

    def publish(self, folder: str, local: Path, name: str) -> None:
        (self.root / folder).mkdir(parents=True, exist_ok=True)
        shutil.copy2(local, self.root / folder / name)

    def read_text(self, folder: str, name: str) -> str | None:
        p = self.root / folder / name
        return p.read_text(encoding="utf-8") if p.exists() else None

    def save_music_tags(self, data: dict) -> None:
        p = self.root / "Music" / "_tags.json"
        if p.parent.exists():
            p.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


class DriveStore(Store):
    """Google Drive аркылуу (GitHub Actions'та)."""

    def __init__(self, drive, root_name: str = ROOT_NAME, music_root: str = ROOT_NAME):
        self.drive = drive
        self.root_name = root_name
        self.music_root = music_root   # сынак режиминде да музыка негизги папкадан окулат
        self.ids: dict[str, str] = {}

    def describe(self) -> str:
        return f"Google Drive → {self.root_name}/"

    def _folder(self, name: str) -> str:
        if name not in self.ids:
            self.ids[name] = self.drive.ensure_path(self.root_name, name)
        return self.ids[name]

    def ensure_layout(self) -> None:
        for f in FOLDERS:
            if f == "Music":  # колдонуучунун папкасы — түзбөйбүз, табабыз гана
                mid = self.drive.find_path(self.music_root, "Music")
                if mid:
                    self.ids["Music"] = mid
                continue
            self._folder(f)

    def load_registry(self) -> dict:
        return self.drive.read_json(REGISTRY, self._folder("Projects"), {"videos": {}})

    def save_registry(self, registry: dict) -> None:
        self.drive.write_json(REGISTRY, self._folder("Projects"), registry)

    def pull_project(self, video_id: str, dest: Path) -> bool:
        pid = self.drive.find_folder(video_id, self._folder("Projects"))
        if not pid:
            return False
        self.drive.download_tree(pid, dest)
        return True

    def push_project(self, src: Path, video_id: str, log: Callable[[str], None] = print) -> int:
        projects = self._folder("Projects")
        pid = self.drive.find_folder(video_id, projects) or self.drive.create_folder(video_id, projects)
        return self.drive.sync_up(src, pid, skip=heavy, log=log)

    def pull_music(self, dest: Path) -> int:
        from .music import AUDIO_EXT

        mid = self.ids.get("Music") or self.drive.find_path(self.music_root, "Music")
        if not mid:
            return 0
        n = 0
        for rel, item in self.drive.walk(mid):
            if Path(rel).suffix.lower() in AUDIO_EXT or rel.endswith(".json"):
                target = dest / rel
                if not target.exists():
                    self.drive.download_file(item["id"], target)
                n += 1
        return n

    def publish(self, folder: str, local: Path, name: str) -> None:
        self.drive.put_file(local, self._folder(folder), name)

    def read_text(self, folder: str, name: str) -> str | None:
        item = self.drive.find_file(name, self._folder(folder))
        if not item:
            return None
        import tempfile

        with tempfile.TemporaryDirectory() as d:
            return self.drive.download_file(item["id"], Path(d) / name).read_text(encoding="utf-8")

    # Музыканын маанай белгилерин сактоо (Music/ ичиндеги системанын бир гана файлы)
    def save_music_tags(self, data: dict) -> None:
        mid = self.ids.get("Music") or self.drive.find_path(self.music_root, "Music")
        if mid:
            self.drive.write_json("_tags.json", mid, data)
