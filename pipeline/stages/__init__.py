"""Этаптардын тизмеси — ушул ирет менен иштетилет."""

from __future__ import annotations

from .base import PlannedStage, Stage
from .s0_check import CheckStage
from .s1_script import ScriptStage
from .s2_scenes import ScenesStage
from .s3_voice import VoiceStage
from .s4_subtitles import SubtitlesStage
from .s5_visuals import VisualsStage
from .s6_animation import AnimationStage
from .s7_music import MusicStage
from .s8_render import RenderStage
from .s9_qa import QAStage


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
    VoiceStage(),
    SubtitlesStage(),
    VisualsStage(),
    AnimationStage(),
    MusicStage(),
    RenderStage(),
    QAStage(),
]

STAGE_NAMES = [s.name for s in STAGES]
STAGES_BY_NAME = {s.name: s for s in STAGES}
