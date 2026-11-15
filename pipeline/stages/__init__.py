"""Этаптардын тизмеси — ушул ирет менен иштетилет."""

from __future__ import annotations

from .base import PlannedStage, Stage
from .s0_check import CheckStage


def _planned(name: str, title: str) -> Stage:
    stage = PlannedStage()
    stage.name, stage.title = name, title
    return stage


STAGES: list[Stage] = [
    CheckStage(),
    _planned("s1_script", "Сценарий"),
    _planned("s2_scenes", "Сахналарга бөлүү"),
    _planned("s3_voice", "Үн (TTS)"),
    _planned("s4_subtitles", "Субтитрлер"),
    _planned("s5_visuals", "Видеоклиптер"),
    _planned("s6_music", "Фондук музыка"),
    _planned("s7_render", "Монтаж"),
    _planned("s8_qa", "Сапатты текшерүү"),
]

STAGE_NAMES = [s.name for s in STAGES]
STAGES_BY_NAME = {s.name: s for s in STAGES}
