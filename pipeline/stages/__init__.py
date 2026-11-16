"""Этаптардын тизмеси — ушул ирет менен иштетилет."""

from __future__ import annotations

from .base import PlannedStage, Stage
from .s0_check import CheckStage
from .s1_script import ScriptStage
from .s2_scenes import ScenesStage


def _planned(name: str, title: str) -> Stage:
    stage = PlannedStage()
    stage.name, stage.title = name, title
    return stage


# Ирети docs/VIDEO_RULES.md, 14-эреже боюнча:
# Topic → Script → Scenes → TTS → Subtitles → Clips → Animation → Music → Montage → QA → Final MP4
STAGES: list[Stage] = [
    CheckStage(),
    ScriptStage(),
    ScenesStage(),
    _planned("s3_voice", "Үн (Gemini TTS)"),
    _planned("s4_subtitles", "Субтитрлер (Whisper)"),
    _planned("s5_visuals", "Видеоклиптер"),
    _planned("s6_animation", "Анимация жана эффекттер"),
    _planned("s7_music", "Фондук музыка"),
    _planned("s8_render", "Монтаж (FFmpeg)"),
    _planned("s9_qa", "Сапатты текшерүү жана Final MP4"),
]

STAGE_NAMES = [s.name for s in STAGES]
STAGES_BY_NAME = {s.name: s for s in STAGES}
