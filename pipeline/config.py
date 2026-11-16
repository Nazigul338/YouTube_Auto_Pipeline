"""Системанын жалпы жөндөөлөрү.

Бардык өзгөрмө параметрлер ушул жерде жана `niches/<ниша>.yaml` ичинде.
Код ичинде жолдор, моделдер же үн аттары катуу жазылбайт.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

NICHES_DIR = Path(__file__).parent / "niches"

# Жергиликтүү иштөө папкасы (GitHub Actions runner'де). Drive — storage.py аркылуу.
DEFAULT_DRIVE_ROOT = "work"


@dataclass
class Config:
    # --- Жолдор ---
    drive_root: str = DEFAULT_DRIVE_ROOT
    videos_dirname: str = "Videos"          # ар бир видеонун папкасы ушул жерде
    music_dirname: str = "Music"            # YouTube Audio Library'ден жүктөлгөн музыка

    # --- Видео ---
    width: int = 1920
    height: int = 1080
    fps: int = 30
    shot_min_sec: float = 2.5               # эреже 5: орточо ~3 сек,
    shot_max_sec: float = 3.5               # чеги ой/сүйлөмгө жараша жылат
    min_duration_sec: int = 490             # 8:10 — орто-реклама үчүн 8:00дөн ашык

    # --- Моделдер (ирети = артыкчылык; биринчиси иштебесе — кийинкиси) ---
    # Тизме probe сыноосунун жыйынтыгы боюнча (2026-11-16).
    text_models: tuple = ("gemini-3.8-flash", "gemini-3.7-flash", "gemini-3.6-flash",
                          "gemini-3.5-flash")
    tts_models: tuple = ("gemini-3.8-flash-tts", "gemini-2.5-flash-preview-tts")
    embed_model: str = "gemini-embedding-001"
    tts_voice: str = "Algenib"
    whisper_model: str = "small"            # GitHub runner: 4 CPU

    # --- Сценарий ---
    language: str = "ru"
    words_min: int = 1100
    words_max: int = 1200

    # --- Аудио ---
    voice_lufs: float = -14.0
    music_db: float = -20.0                 # музыка үнгө салыштырмалуу

    # --- Ниша ---
    niche: str = "motivation"
    niche_data: dict[str, Any] = field(default_factory=dict)

    @property
    def videos_root(self) -> Path:
        return Path(self.drive_root) / self.videos_dirname

    @property
    def music_root(self) -> Path:
        return Path(self.drive_root) / self.music_dirname


def load_niche(name: str) -> dict[str, Any]:
    path = NICHES_DIR / f"{name}.yaml"
    if not path.exists():
        available = sorted(p.stem for p in NICHES_DIR.glob("*.yaml"))
        raise FileNotFoundError(
            f"'{name}' нишасы табылган жок. Бар нишалар: {available}"
        )
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_config(niche: str = "motivation", drive_root: str | None = None,
                **overrides: Any) -> Config:
    """Нишанын YAML файлын окуп, Config түзөт.

    Ырааттуулук: демейки маанилер → ниша YAML'дагы `config:` → overrides.
    """
    data = load_niche(niche)
    cfg = Config(niche=niche, niche_data=data)

    for key, value in (data.get("config") or {}).items():
        if not hasattr(cfg, key):
            raise KeyError(f"{niche}.yaml: белгисиз параметр '{key}'")
        setattr(cfg, key, value)

    root = drive_root or os.environ.get("YTA_DRIVE_ROOT")
    if root:
        cfg.drive_root = root

    for key, value in overrides.items():
        if not hasattr(cfg, key):
            raise KeyError(f"Белгисиз параметр: '{key}'")
        setattr(cfg, key, value)
    return cfg


def get_secret(name: str) -> str | None:
    """API ачкычын чөйрө өзгөрмөсүнөн алуу (GitHub Secrets → env).

    Ачкычтар эч качан кодго, логго же Drive'га жазылбайт.
    """
    value = os.environ.get(name, "").strip()
    return value or None
