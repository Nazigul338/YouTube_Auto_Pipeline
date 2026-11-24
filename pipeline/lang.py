"""Каналдын тили жана форматы (2026-11-24: англисче «Tech History» каналы кошулду).

Орусча мотивация каналы (ru, mp7) өзгөрбөйт: бул жердеги функциялар ru үчүн мурунку маанилерди кайтарат.
"""

from __future__ import annotations

NAMES = {"ru": "Russian", "en": "English"}


def code(cfg) -> str:
    return (getattr(cfg, "language", None) or "ru").lower()


def is_en(cfg) -> bool:
    return code(cfg) == "en"


def name(cfg) -> str:
    return NAMES.get(code(cfg), "Russian")


def structure(cfg) -> str:
    return (getattr(cfg, "niche_data", None) or {}).get("structure", "")


def is_doc(cfg) -> bool:
    """Документалдык тарых форматы (`structure: doc`, niches/tech_history.yaml)."""
    return structure(cfg) == "doc"


def localize(prompt: str, cfg) -> str:
    """Орусча каналга жазылган англисче промпттордогу каналдын сыпаттамасын алмаштырат (ru — өзгөрүүсүз)."""
    if not is_en(cfg):
        return prompt
    desc = (getattr(cfg, "niche_data", None) or {}).get("channel_desc", "English-language documentary")
    return (prompt.replace("Russian-language psychology/motivation", desc)
            .replace("Russian-language psychology", desc)
            .replace("Russian narration", "English narration"))
