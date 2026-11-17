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
    "Slightly slower on key ideas, gradually building energy towards the end."
)
EMPHASIS_TMPL = " Put clear emphasis on: {words}."

# Абзац коюлуучу жерлер (сөздөр өзгөрбөйт)
_PIVOTS = r"(Но|И вот|Запомни|Представь|Подумай|Вот почему|Именно поэтому|А теперь|Сегодня)"


def requested() -> bool:
    return os.environ.get("YTA_VOICE_STYLE", "").strip().lower() == "motivational"


def enabled(store=None) -> bool:
    if not requested():
        return False
    from .storage import LocalStore

    if isinstance(store, LocalStore):
        return True
    root = store.root_name if store is not None and hasattr(store, "root_name") \
        else os.environ.get("YTA_DRIVE_FOLDER", "")
    return root == TEST_ROOT


def direction(keywords: list[str] | None = None) -> str:
    kws = [k.strip() for k in (keywords or []) if k and k.strip()][:6]
    return MOTIVATIONAL_STYLE + (EMPHASIS_TMPL.format(words=", ".join(f"«{k}»" for k in kws)) if kws else "")


def shape_text(text: str) -> str:
    """Паузалар үчүн тыныш белгилери/абзацтар. Сөздөрдүн тизмеси ӨЗГӨРБӨЙТ."""
    t = re.sub(r"\s+", " ", text).strip()
    t = re.sub(r"([?!])\s+(?=[А-ЯЁA-Z«])", r"\1\n\n", t)                 # суроо/илептен кийин — пауза
    t = re.sub(rf"([.…])\s+{_PIVOTS}\b", lambda m: f"{m.group(1)}\n\n{m.group(2)}", t)
    t = re.sub(r"\s*\.\.\.\s*", "… ", t).replace("… \n", "…\n")
    return t.strip()


def words(text: str) -> list[str]:
    return re.findall(r"[\wЁё]+", text.lower())
