"""Ар бир видео үчүн өзүнчө папка түзүү жана файлдарды коопсуз сактоо."""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

from .config import Config
from .state import VideoState

from .storage import PROJECT_SUBFOLDERS as SUBFOLDERS  # noqa: E402

_TRANSLIT = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e",
    "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "h", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "sch",
    "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
    "ң": "n", "ө": "o", "ү": "u",
}


def slugify(text: str, max_len: int = 50) -> str:
    """'Почему ты откладываешь' → 'pochemu-ty-otkladyvaesh'."""
    text = "".join(_TRANSLIT.get(ch, ch) for ch in text.lower())
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return (text[:max_len].rstrip("-")) or "video"


def find_video_folder(cfg: Config, topic: str) -> Path | None:
    """Ушул тема менен мурун түзүлгөн папканы табуу (эң акыркысы)."""
    root = cfg.videos_root
    if not root.exists():
        return None
    matches = []
    for folder in root.iterdir():
        if folder.is_dir() and VideoState.exists(folder):
            try:
                if VideoState.load(folder).topic.strip() == topic.strip():
                    matches.append(folder)
            except Exception:
                continue
    return sorted(matches)[-1] if matches else None


def new_video_folder(cfg: Config, topic: str) -> Path:
    """Жаңы папка: Videos/2026-11-15_tema-slug (бар болсо _2, _3 ...)."""
    base = f"{date.today().isoformat()}_{slugify(topic)}"
    folder = cfg.videos_root / base
    n = 2
    while folder.exists():
        folder = cfg.videos_root / f"{base}_{n}"
        n += 1
    folder.mkdir(parents=True)
    for sub in SUBFOLDERS:
        (folder / sub).mkdir()
    return folder


def versioned_path(path: Path) -> Path:
    """Файл бар болсо, үстүнөн жазбай жаңы ат берет: script.txt → script_v2.txt."""
    path = Path(path)
    if not path.exists():
        return path
    n = 2
    while True:
        candidate = path.with_name(f"{path.stem}_v{n}{path.suffix}")
        if not candidate.exists():
            return candidate
        n += 1


def list_videos(cfg: Config) -> list[Path]:
    root = cfg.videos_root
    if not root.exists():
        return []
    return sorted(p for p in root.iterdir() if p.is_dir() and VideoState.exists(p))
