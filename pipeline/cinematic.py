"""Cinematic режими (СЫНАК): табигый кино стилиндеги түс, жарык, grain, glow, өтүүлөр.

КООПСУЗДУК: бул режим ЭКИ шарт аткарылганда гана иштейт:
  1) `YTA_CINEMATIC=1` (атайын workflow «🎞 Cinematic сынак» коёт);
  2) Drive папкасы — `YouTube_Auto_TEST` (негизги `YouTube_Auto` эмес).
Негизги өндүрүштө (YouTube_Auto) желек коюлса да режим ӨЧҮК калат — колдонуучунун уруксатысыз
production'го өтпөйт. Бул модулдун функциялары режим өчүк болгондо эч жерде чакырылбайт.

Эффекттер (бардыгы жумшак, «байкалбай жакшыртуу» принциби):
  - tone: жумшак S-ийри (контраст), көлөкөлөрдү бир аз көтөрүү, highlights'ты жумшак басуу;
  - concept tint: s6 концепциясынын түсү (warm/cool/…) — мурункудай;
  - glow: ачык жерлерден гана бүдөмүк жарык (luma'да screen, 14%) — түс бузулбайт;
  - grain: luma'да жумшак убакыт боюнча ызы-чуу (пленка сымал);
  - кадр-кадр бирдейлөө: ар клиптин орточо жарыгы/каныккандыгы өлчөнүп, максатка жакындатылат;
  - blur background: 16:9'га туура келбеген материал кесилбей, бүдөмүк фондо борборго коюлат;
  - өтүүлөр: dissolve/fade көбүрөөк, slide жана «караңгы аркылуу» сейрек, 0.7 сек.
Letterbox (кара тилкелер) КОЛДОНУЛБАЙТ.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

TEST_ROOT = "YouTube_Auto_TEST"

# ---------------------------------------------------------------- режим

def requested() -> bool:
    return os.environ.get("YTA_CINEMATIC", "").strip() in ("1", "true", "yes")


def root_name(store=None) -> str:
    if store is not None and hasattr(store, "root_name"):
        return store.root_name
    return os.environ.get("YTA_DRIVE_FOLDER", "")


def enabled(store=None) -> bool:
    """Cinematic режими күйүкпү. Жергиликтүү тесттерде (LocalStore) — желек боюнча гана."""
    if not requested():
        return False
    from .storage import LocalStore

    if isinstance(store, LocalStore):
        return True
    return root_name(store) == TEST_ROOT


def blocked_reason(store=None) -> str | None:
    """Желек коюлган, бирок production папкасы болсо — себеби (логго)."""
    if requested() and not enabled(store):
        return (f"YTA_CINEMATIC=1, бирок папка «{root_name(store) or '?'}» — cinematic режими "
                f"{TEST_ROOT} үчүн гана (production'го колдонуучунун уруксаты керек). Өчүк калды.")
    return None


# ---------------------------------------------------------------- түс жана жарык

TONE = ("curves=master='0/0.025 0.2/0.17 0.5/0.5 0.8/0.83 1/0.965',"   # жумшак S, көлөкө/highlight
        "eq=contrast=1.03:saturation=1.02")
GLOW = ("split=2[cna][cnb];[cnb]curves=all='0/0 0.6/0 1/1',gblur=sigma=22[cng];"
        "[cna][cng]blend=c0_mode=screen:c0_opacity=0.14:c1_mode=normal:c1_opacity=1:"
        "c2_mode=normal:c2_opacity=1")
GRAIN = "noise=c0s=3:c0f=t+u"          # жеңилирээк grain (файл өлчөмү азаят)


def look_chain(concept_grade: str) -> str:
    """Финалдык кодировкадагы look (субтитрлерден МУРУН — субтитр grain/glow'дон таза калат)."""
    return f"format=yuv420p,{TONE},{concept_grade},{GLOW},{GRAIN}"


# ---------------------------------------------------------------- өтүүлөр

# fadeblack («караңгы аркылуу») — сейрек (~7%): run #44097307823'дө 1/7 салмак 19% берип, ашыкча караңгы болгон
TRANSITIONS = ["dissolve", "fade"] * 5 + ["smoothleft", "smoothright", "smoothleft", "fadeblack"]
TRANSITION_SEC = 0.7


def pick_transition(rng, prev: str | None) -> str:
    """Кошуна өтүүлөр кайталанбасын; fadeblack (караңгы аркылуу) катар келбесин."""
    options = [t for t in TRANSITIONS if t != prev or t in ("dissolve", "fade")]
    if prev == "fadeblack":
        options = [t for t in options if t != "fadeblack"]
    return rng.choice(options)


_GROUP = {"calm": "low", "reflective": "low", "sad": "low", "hopeful": "up", "inspired": "up",
          "determined": "up", "tense": "high", "dramatic": "high"}


def transition_for(rng, prev: str | None, emo_a: str, emo_b: str, used_black: int, total: int) -> str:
    """Сахналар ортосундагы өтүү — эмоциянын өзгөрүшүнө жараша (мазмунга ылайык):
    ошол эле маанай → dissolve/fade; энергия көтөрүлсө → slide; чыңалуудан тынчтыкка (бурулуш) → караңгы аркылуу
    (fadeblack, ≤8% жана катар эмес)."""
    a, b = _GROUP.get(emo_a, "low"), _GROUP.get(emo_b, "low")
    black_ok = prev != "fadeblack" and used_black < max(1, int(0.08 * total))
    if a == "high" and b == "low" and black_ok and rng.random() < 0.6:
        return "fadeblack"
    if a != b and (b in ("up", "high")):
        return rng.choice(["smoothleft", "smoothright"])
    return rng.choice(["dissolve", "fade", "dissolve"])


# ---------------------------------------------------------------- кадр-кадр бирдейлөө

TARGET_Y = 0.43        # орточо жарык (0..1, tv-range ичинде)
TARGET_SAT = 0.20      # орточо каныккандык (SATAVG/255)
MAX_BRIGHT = 0.07
SAT_RANGE = (0.93, 1.10)             # каныккандыкты бирдейлөө жумшак (±10%)


def measure(clip: Path, offset: float, dur: float, kind: str = "video") -> dict | None:
    """Клиптин колдонула турган бөлүгүнүн орточо жарыгы (YAVG) жана каныккандыгы (SATAVG), 0..1."""
    src = (["-loop", "1", "-t", "1", "-i", str(clip)] if kind == "image"
           else ["-ss", f"{max(0.0, offset):.3f}", "-t", f"{max(0.5, dur):.3f}", "-i", str(clip)])
    try:
        r = subprocess.run(["ffmpeg", "-hide_banner", "-v", "info", *src, "-vf",
                            "fps=2,scale=320:-2,format=yuv420p,signalstats,metadata=print",
                            "-an", "-f", "null", "-"], capture_output=True, text=True, timeout=120)
    except subprocess.TimeoutExpired:
        return None
    ys = [float(x) for x in re.findall(r"signalstats\.YAVG=([\d.]+)", r.stderr)]
    ss = [float(x) for x in re.findall(r"signalstats\.SATAVG=([\d.]+)", r.stderr)]
    if not ys:
        return None
    return {"y": sum(ys) / len(ys) / 255.0, "sat": (sum(ss) / len(ss) / 255.0) if ss else None}


def match_filter(stats: dict | None) -> str:
    """Клипти максаттык жарыкка/каныккандыкка ЖАРЫМ-ЖАРТЫЛАЙ жакындатат (табигый калсын)."""
    if not stats:
        return ""
    b = max(-MAX_BRIGHT, min(MAX_BRIGHT, (TARGET_Y - stats["y"]) * 0.5))
    s = 1.0
    if stats.get("sat"):
        s = max(SAT_RANGE[0], min(SAT_RANGE[1], 1 + (TARGET_SAT / max(stats["sat"], 0.02) - 1) * 0.35))
    if abs(b) < 0.005 and abs(s - 1) < 0.01:
        return ""
    return f"eq=brightness={b:.3f}:saturation={s:.3f}"


# ---------------------------------------------------------------- 16:9'га туура келбеген материал

def dims(path: Path) -> tuple[int, int] | None:
    try:
        r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                            "stream=width,height:stream_side_data=rotation", "-of", "csv=p=0", str(path)],
                           capture_output=True, text=True, timeout=30)
        nums = [int(x) for x in re.findall(r"-?\d+", r.stdout)]
        w, h = nums[0], nums[1]
        if len(nums) > 2 and abs(nums[2]) in (90, 270):
            w, h = h, w
        return w, h
    except Exception:
        return None


def needs_blur_bg(w: int, h: int) -> bool:
    """16:9 = 1.78. 1.5..2.1 аралыгы — кесүү менен (сапат жоголбойт); башкасы — blur background."""
    r = w / h if h else 1.78
    return r < 1.5 or r > 2.1


def blur_bg_filter(W: int = 1920, H: int = 1080) -> str:
    """Материал кесилбейт: бүдөмүк, бир аз караңгы фон + борбордо толук кадр. Кара тилке жок."""
    return (f"split=2[bga][bgb];[bga]scale={W}:{H}:force_original_aspect_ratio=increase,"
            f"crop={W}:{H},gblur=sigma=38,eq=brightness=-0.07:saturation=0.85[bgc];"
            f"[bgb]scale={W}:{H}:force_original_aspect_ratio=decrease[bgf];"
            f"[bgc][bgf]overlay=(W-w)/2:(H-h)/2,setsar=1")


def shot_prefilter(clip: Path, kind: str, offset: float, dur: float) -> tuple[str, dict]:
    """render_shot'ко кошулуучу чыпка (кыймылдан МУРУН) жана маалымат (debug үчүн)."""
    info: dict = {}
    parts = []
    d = dims(clip)
    if d and needs_blur_bg(*d):
        parts.append(blur_bg_filter())
        info["blur_bg"] = f"{d[0]}x{d[1]}"
    st = measure(clip, offset, dur, kind)
    m = match_filter(st)
    if m:
        parts.append(m)
    if st:
        info["y"], info["sat"] = round(st["y"], 3), (round(st["sat"], 3) if st.get("sat") else None)
    info["match"] = m
    return ",".join(parts), info
