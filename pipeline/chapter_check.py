"""Даяр MP4'тин тайм-коддорун ЧЫНДАП текшерүү (2026-11-25): MP4 Drive'дан жүктөлөт, Whisper бардык аудионун сөздөрүн
убактысы менен окуйт, ар главанын биринчи сөздөрү МП4'те канчанчы секундда айтыларын тапкан убакытты
YouTube сүрөттөмөсүндөгү тайм-код менен салыштырат. Эч нерсе Drive'га жазылбайт/өчүрүлбөйт (окуу гана).

Иштетүү: Actions → «⏱ Тайм-код текшерүү» (chapter_check.yml). Натыйжа: логдо жана артефактта.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

from . import media
from .asr import norm_word, transcribe

TOLERANCE = 3.0     # сек: YouTube главасы ушунча айырмада болсо да көрүүчүгө сезилбейт

# (тайм-код секундада, главанын биринчи сөздөрү сценарийден) — сүрөттөмөдөгү тайм-коддор менен бирдей
CHAPTERS = {
    "Video_001_cinematic.mp4": [
        (0, "сколько квадратных метров"), (26, "мы привыкли думать"), (76, "представьте вымышленного человека"),
        (173, "почему наше сознание"), (229, "попробуйте посмотреть на"), (258, "возьмем другой вымышленный"),
        (360, "задумайтесь на секунду"), (394, "демонтаж инфраструктуры мести"), (445, "как начать этот"),
        (526, "настоящий реванш в")],
    "Video_004_cinematic.mp4": [
        (0, "представьте что вы"), (15, "кажется абсолютно логичным"), (63, "когда мы рассматриваем"),
        (86, "у многих из нас"), (112, "остановка в этом"), (143, "возьмем вымышленный но"),
        (174, "для сергея как"), (202, "похожая история часто"), (263, "это проявление маскирующейся"),
        (295, "мы часто относимся"), (319, "когда мы пытаемся"), (343, "чтобы выйти из"),
        (370, "разрешить себе отдыхать"), (413, "практический шаг который"), (463, "со временем эти"),
        (490, "настоящий отдых начинается")],
}


def find_phrase(words: list[tuple[str, float, float]], phrase: str, near: float, window: float = 40.0):
    """Фразанын биринчи 3 сөзүн (болбосо 2) `near` секундага ЖАКЫН жерден издейт. → башталуу убактысы же None."""
    key = [norm_word(w) for w in phrase.split()]
    for n in (min(3, len(key)), 2):
        k = key[:n]
        hits = [words[i][1] for i in range(len(words) - n + 1) if [w[0] for w in words[i:i + n]] == k]
        hits = [t for t in hits if abs(t - near) <= window]
        if hits:
            return min(hits, key=lambda t: abs(t - near))
    return None


def check(name: str, words: list[tuple[str, float, float]], chapters=None) -> list[dict]:
    rows = []
    for sec, phrase in (chapters or CHAPTERS[name]):
        t = find_phrase(words, phrase, sec)
        rows.append({"claimed": sec, "actual": None if t is None else round(t, 1),
                     "delta": None if t is None else round(t - sec, 1), "phrase": phrase,
                     "ok": t is not None and abs(t - sec) <= TOLERANCE})
    return rows


def fmt(sec: float) -> str:
    return f"{int(sec // 60)}:{int(sec % 60):02d}"


def main() -> int:
    from .drive import DriveClient
    drive = DriveClient.from_env()
    if drive is None:
        print("❌ GDRIVE_* секреттери жок")
        return 2
    folder = drive.find_path("YouTube_Auto_TEST", "Final_Videos")
    report, ok_all = {}, True
    for name in CHAPTERS:
        item = drive.find_file(name, folder) if folder else None
        if not item:
            print(f"❌ {name}: Drive'да табылган жок")
            ok_all = False
            continue
        with tempfile.TemporaryDirectory() as d:
            p = drive.download_file(item["id"], Path(d) / name)
            dur = media.stream_durations(p)
            words = transcribe(p, model="small")
        rows = check(name, words)
        report[name] = {"duration": dur, "chapters": rows}
        print(f"\n== {name}: узактыгы {fmt(dur.get('format') or 0)} (видео {dur.get('video')}, аудио {dur.get('audio')})")
        for r in rows:
            mark = "✅" if r["ok"] else "❌"
            print(f"  {mark} {fmt(r['claimed'])}  → чындыгы {fmt(r['actual']) if r['actual'] is not None else '—'}"
                  f" (Δ {r['delta']} сек) «{r['phrase']}»")
        ok_all &= all(r["ok"] for r in rows)
    out = Path(os.environ.get("CHK_OUT", "chapter_check"))
    out.mkdir(parents=True, exist_ok=True)
    (out / "result.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print("\n" + ("✅ Бардык тайм-коддор дал келет" if ok_all else "⚠️ Айрым тайм-коддор дал келген жок"))
    return 0 if ok_all else 1


if __name__ == "__main__":
    sys.exit(main())
