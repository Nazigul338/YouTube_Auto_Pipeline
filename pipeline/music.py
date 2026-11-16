"""Музыка китепканасы: тректерди табуу, булагын/лицензиясын аныктоо, тандоо.

Булак ПАПКАНЫН АТЫНАН аныкталат (телефондо JSON жазуунун кереги жок):

    Music/
      Pixabay/                              ← Pixabay Music'тен жүктөлгөндөр
      YouTube_Audio_Library/                ← автор көрсөтүү талап КЫЛБАГАНДАР
      YouTube_Audio_Library_Attribution/    ← автор көрсөтүү талап КЫЛГАНДАР

Папкага трек салуу — ал трек ошол булактын шартына ылайык экенин сиз
тастыктаганыңызды билдирет. Система муну `licenses.json`'го жазат
(`basis: "folder_chosen_by_owner"`), бирок лицензияны өзү текшере албайт.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path, PurePath
from typing import Iterable

AUDIO_EXT = {".mp3", ".wav", ".m4a", ".ogg"}

# ачкыч (папка аты нормалдаштырылган) → (булак, лицензия, автор көрсөтүү керекпи)
SOURCES: dict[str, tuple[str, str, bool | None]] = {
    "pixabay": ("Pixabay Music", "Pixabay Content License", False),
    "pixabay_music": ("Pixabay Music", "Pixabay Content License", False),
    "youtube_audio_library": (
        "YouTube Audio Library", "YouTube Audio Library license (no attribution)", False),
    "youtube_audio_library_attribution": (
        "YouTube Audio Library", "YouTube Audio Library license (attribution required)", True),
}
UNKNOWN_SOURCE = ("Unknown", "Unknown — verify the license manually", None)


def normalize_key(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def classify(relpath: str | PurePath) -> tuple[str, str, bool | None]:
    """Музыка папкасына салыштырмалуу жол → (булак, лицензия, attribution)."""
    parts = PurePath(relpath).parts
    if len(parts) < 2:  # папкасыз, түздөн-түз Music/ ичинде
        return UNKNOWN_SOURCE
    return SOURCES.get(normalize_key(parts[0]), UNKNOWN_SOURCE)


def clean_title(stem: str) -> str:
    return re.sub(r"[_\-]+", " ", stem).strip()


@dataclass
class Track:
    path: Path
    rel: str
    title: str
    source: str
    license: str
    attribution_required: bool | None

    @property
    def is_known(self) -> bool:
        return self.source != UNKNOWN_SOURCE[0]

    def license_record(self) -> dict:
        """licenses.json үчүн жазуу."""
        return {
            "type": "music",
            "file": self.rel,
            "title": self.title,
            "source": self.source,
            "license": self.license,
            "attribution_required": self.attribution_required,
            "basis": "folder_chosen_by_owner",
        }


def scan(music_root: Path) -> list[Track]:
    root = Path(music_root)
    if not root.exists():
        return []
    tracks = []
    for p in sorted(root.rglob("*")):
        if p.is_file() and p.suffix.lower() in AUDIO_EXT:
            rel = p.relative_to(root).as_posix()
            source, lic, attr = classify(rel)
            tracks.append(Track(p, rel, clean_title(p.stem), source, lic, attr))
    return tracks


def library_report(relpaths: Iterable[str]) -> tuple[int, dict[str, int], int]:
    """(жалпы трек, булак боюнча саны, булагы белгисиздердин саны)."""
    by_source: dict[str, int] = {}
    unknown = 0
    total = 0
    for rel in relpaths:
        if PurePath(rel).suffix.lower() not in AUDIO_EXT:
            continue
        total += 1
        source = classify(rel)[0]
        by_source[source] = by_source.get(source, 0) + 1
        if source == UNKNOWN_SOURCE[0]:
            unknown += 1
    return total, by_source, unknown


def describe_report(total: int, by_source: dict[str, int], unknown: int) -> str:
    if total == 0:
        return "бош — тректерди Pixabay/ же YouTube_Audio_Library/ папкасына салыңыз"
    parts = ", ".join(f"{k}: {v}" for k, v in sorted(by_source.items()))
    note = f"{total} трек ({parts})"
    if unknown:
        note += (f"; ⚠ {unknown} трек булагы белгисиз — аларды Pixabay/ же "
                 "YouTube_Audio_Library/ папкасына жылдырыңыз")
    return note


def pick(tracks: list[Track], used: list[str] | None = None) -> Track | None:
    """Эң эле аз/эң эски колдонулган тректи тандайт (кайталанбоо үчүн).

    used — мурун колдонулган файлдардын тизмеси (эскиден жаңыга).
    Булагы белгисиз тректер тандалбайт.
    """
    used = used or []
    usable = [t for t in tracks if t.is_known]
    if not usable:
        return None

    def rank(t: Track) -> tuple[int, str]:
        # колдонулбагандар алгач (-1), андан кийин эң эскиси
        return (used.index(t.rel) if t.rel in used else -1, t.rel)

    return min(usable, key=rank)


def attribution_text(track: Track) -> str | None:
    """Автор көрсөтүү талап болсо, видеонун сүрөттөмөсүнө кошула турган сап."""
    if track.attribution_required:
        return f"Music: {track.title} — {track.source}"
    return None
