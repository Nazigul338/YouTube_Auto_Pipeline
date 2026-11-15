"""Ар бир видеонун абалын `state.json` файлында сактоо.

Бул файлдын жардамы менен:
- кайсы этап бүткөнү, кайсы этапта ката чыкканы көрүнөт;
- Colab өчүп калса, калган жеринен улантууга болот;
- бир гана этапты кайра иштетүүгө болот.
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PENDING = "pending"
RUNNING = "running"
DONE = "done"
FAILED = "failed"

STATUS_ICON = {PENDING: "⏳", RUNNING: "🔄", DONE: "✅", FAILED: "❌"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class VideoState:
    FILENAME = "state.json"

    def __init__(self, folder: Path, data: dict[str, Any]):
        self.folder = Path(folder)
        self.data = data

    # ---------- жүктөө / сактоо ----------
    @classmethod
    def create(cls, folder: Path, topic: str, niche: str,
               stage_names: list[str]) -> "VideoState":
        data = {
            "topic": topic,
            "niche": niche,
            "created_at": _now(),
            "updated_at": _now(),
            "stages": {
                name: {"status": PENDING, "attempts": 0} for name in stage_names
            },
        }
        state = cls(folder, data)
        state.save()
        return state

    @classmethod
    def load(cls, folder: Path) -> "VideoState":
        path = Path(folder) / cls.FILENAME
        with open(path, encoding="utf-8") as f:
            return cls(Path(folder), json.load(f))

    @classmethod
    def exists(cls, folder: Path) -> bool:
        return (Path(folder) / cls.FILENAME).exists()

    def save(self) -> None:
        """Атомдук сактоо: файл жарымы жазылып бузулуп калбайт."""
        self.data["updated_at"] = _now()
        self.folder.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.folder, suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, self.folder / self.FILENAME)

    # ---------- этаптар ----------
    def ensure_stages(self, stage_names: list[str]) -> None:
        """Жаңы этап кошулса, эски state.json'го да кошулат."""
        stages = self.data.setdefault("stages", {})
        for name in stage_names:
            stages.setdefault(name, {"status": PENDING, "attempts": 0})

    def stage(self, name: str) -> dict[str, Any]:
        return self.data["stages"][name]

    def status(self, name: str) -> str:
        return self.stage(name)["status"]

    def mark_running(self, name: str) -> None:
        st = self.stage(name)
        st["status"] = RUNNING
        st["attempts"] = st.get("attempts", 0) + 1
        st["started_at"] = _now()
        st.pop("error", None)
        self.save()

    def mark_done(self, name: str, outputs: dict[str, Any] | None = None) -> None:
        st = self.stage(name)
        st["status"] = DONE
        st["finished_at"] = _now()
        if outputs:
            st["outputs"] = outputs
        self.save()

    def mark_failed(self, name: str, error: str) -> None:
        st = self.stage(name)
        st["status"] = FAILED
        st["finished_at"] = _now()
        st["error"] = error
        self.save()

    def reset(self, name: str) -> None:
        """Этапты кайра иштетүү үчүн 'pending' абалына кайтаруу.

        Файлдар өчүрүлбөйт — этап жаңы версия катары сактайт.
        """
        st = self.stage(name)
        st["status"] = PENDING
        st.pop("error", None)
        self.save()

    def outputs(self, name: str) -> dict[str, Any]:
        return self.stage(name).get("outputs", {})

    @property
    def topic(self) -> str:
        return self.data["topic"]

    @property
    def niche(self) -> str:
        return self.data["niche"]
