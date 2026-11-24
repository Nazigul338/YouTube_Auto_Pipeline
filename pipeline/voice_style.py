"""Мотивациялык диктор стили (СЫНАК режими гана).

КООПСУЗДУК: `YTA_VOICE_STYLE=motivational` жана Drive папкасы `YouTube_Auto_TEST` болгондо гана иштейт
(cinematic режими сыяктуу). Production'до учурдагы TTS (Algenib + niche `tts_style`) өзгөрүүсүз калат.

Эмне кылат:
  - Режиссёрдук нускама: терең, күчтүү, жетилген эркек үн; көрүүчүгө түз кайрылуу; маанилүү сөздөргө басым;
    «…» жана «—» жерлеринде драмалык пауза; бир калыптуу эмес, акырында энергия көтөрүлөт.
  - Басым жасала турган сөздөр — сахнанын `keywords`'унан (s2) бөлүккө жараша нускамага кошулат.
  - Текстке ПАУЗА белгилери: риторикалык суроодон/илептен кийин абзац, «но/и вот/запомни…» алдында «—».
    СӨЗДӨР ӨЗГӨРБӨЙТ (тыныш белгилери жана абзацтар гана) → Whisper текшерүүсү жана субтитрлер бузулбайт.
"""

from __future__ import annotations

import os
import re

TEST_ROOT = "YouTube_Auto_TEST"

MOTIVATIONAL_STYLE = (
    "You are a professional Russian motivational narrator. Deep, powerful, mature male voice; "
    "warm chest resonance; serious, confident and sincere. Speak directly to one listener, as if "
    "looking them in the eyes. Clear, precise Russian diction. Vary the intonation: calm and low "
    "for reflection, firmer and stronger for calls to action; never monotone or robotic. "
    "Make a short dramatic pause at every '…' and '—' and after rhetorical questions. "
    "Slightly slower on key ideas, gradually building energy towards the end. "
    "Hit the very first sentence immediately, with no warm-up: it is the hook of the first 3 seconds. "
    "When the one example story in the middle is told, become a little softer and more intimate; return to a "
    "firm, strong delivery for the practical advice and the final call."
)
STORY_STYLE = (   # кино-окуя форматы (2026-11-21): закадровый голос короткометражного фильма
    "You are the Russian voice-over narrator of a short cinematic psychological film. Deep, warm, intimate "
    "mature male voice; you TELL a story, you do not lecture or call to action. Quiet, observant tone in "
    "everyday scenes; restrained tension in the conflict; a soft, slower moment at the turning point; "
    "gentle hope at the end. Read dialogue lines in quotes slightly lighter and more natural than narration, "
    "without acting out voices. Clear Russian diction; natural pauses at '…', '—' and between scenes; never "
    "theatrical, never monotone."
)
EMPHASIS_TMPL = " Put clear emphasis on: {words}."

# Абзац коюлуучу жерлер (сөздөр өзгөрбөйт)
_PIVOTS = r"(Но|И вот|Запомни|Представь|Подумай|Вот почему|Именно поэтому|А теперь|Сегодня)"


def requested() -> bool:
    return os.environ.get("YTA_VOICE_STYLE", "").strip().lower() == "motivational"


def enabled(store=None) -> bool:
    """Желек + уруксат берилген папка (СЫНАК; 2026-11-20ден production да — cinematic.PRODUCTION_APPROVED)."""
    if not requested():
        return False
    from . import cinematic

    if store is None:
        root = os.environ.get("YTA_DRIVE_FOLDER", "")
        return root == TEST_ROOT or (cinematic.PRODUCTION_APPROVED and root == cinematic.PROD_ROOT)
    return cinematic.allowed_root(store)


def direction(keywords: list[str] | None = None, story: bool = False) -> str:
    kws = [k.strip() for k in (keywords or []) if k and k.strip()][:6]
    return (STORY_STYLE if story else MOTIVATIONAL_STYLE) + (EMPHASIS_TMPL.format(words=", ".join(f"«{k}»" for k in kws)) if kws else "")


def shape_text(text: str) -> str:
    """Паузалар үчүн тыныш белгилери/абзацтар. Сөздөрдүн тизмеси ӨЗГӨРБӨЙТ."""
    t = re.sub(r"\s+", " ", text).strip()
    t = re.sub(r"([?!])\s+(?=[А-ЯЁA-Z«])", r"\1\n\n", t)                 # суроо/илептен кийин — пауза
    t = re.sub(rf"([.…])\s+{_PIVOTS}\b", lambda m: f"{m.group(1)}\n\n{m.group(2)}", t)
    t = re.sub(r"\s*\.\.\.\s*", "… ", t).replace("… \n", "…\n")
    return t.strip()


def words(text: str) -> list[str]:
    return re.findall(r"[\wЁё]+", text.lower())
