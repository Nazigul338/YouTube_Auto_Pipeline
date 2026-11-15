"""Бардык этаптардын негизги классы.

Жаңы этап кошуу үчүн:
1. `Stage` классынан мурастап, `name`, `title` жана `run()` жазыңыз.
2. `stages/__init__.py` ичиндеги `STAGES` тизмесине кошуңуз.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from ..config import Config
from ..state import VideoState


class StageError(Exception):
    """Этаптын түшүнүктүү катасы (колдонуучуга кыргызча көрсөтүлөт)."""


class NotImplementedStage(Exception):
    """Этап азырынча иштелип чыга элек."""


@dataclass
class Context:
    cfg: Config
    state: VideoState
    folder: Path
    log: Callable[[str], None]

    def path(self, *parts: str) -> Path:
        return self.folder.joinpath(*parts)


class Stage:
    name: str = ""          # state.json'догу ачкыч, мис. "s1_script"
    title: str = ""         # колдонуучуга көрүнгөн ат, мис. "Сценарий"
    always_run: bool = False  # True: ар бир иштетүүдө кайра аткарылат (мис. текшерүү)

    def run(self, ctx: Context) -> dict[str, Any] | None:
        """Этаптын иши. Жыйынтык файлдардын жолдорун dict кылып кайтарат."""
        raise NotImplementedError

    def verify(self, ctx: Context, outputs: dict[str, Any] | None) -> None:
        """Жыйынтыкты текшерүү. Ката болсо StageError чыгарат.

        Демейки: outputs ичиндеги бардык файлдар бар жана бош эмес.
        """
        for key, value in (outputs or {}).items():
            if isinstance(value, str) and key.endswith(("_path", "_file")):
                p = Path(value)
                if not p.exists() or p.stat().st_size == 0:
                    raise StageError(f"'{key}' файлы түзүлгөн жок же бош: {p}")


class PlannedStage(Stage):
    """Кийинки кадамдарда иштелип чыга турган этап үчүн орун."""

    def run(self, ctx: Context) -> dict[str, Any] | None:
        raise NotImplementedStage(
            f"«{self.title}» этабы азырынча даяр эмес — кийинки кадамда кошулат."
        )
