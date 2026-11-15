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

# Google Drive'дагы негизги папка (Colab'да)
DEFAULT_DRIVE_ROOT = "/content/drive/MyDrive/YouTube_Auto"


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
    shot_min_sec: float = 3.0
    shot_max_sec: float = 4.0

    # --- Моделдер ---
    script_model: str = "gemini-3.8-flash"
    tts_model: str = "gemini-3.8-flash-tts"
    tts_voice: str = "Algenib"
    whisper_model: str = "small"            # бекер Colab (CPU) үчүн

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
    """API ачкычын коопсуз алуу: Colab Secrets → чөйрө өзгөрмөсү.

    Ачкычтар эч качан кодго, логго же Drive'га жазылбайт.
    """
    try:
        from google.colab import userdata  # type: ignore

        try:
            value = userdata.get(name)
            if value and value.strip():
                return value.strip()
        except Exception:
            pass
    except ImportError:
        pass
    value = os.environ.get(name, "").strip()
    return value or None
