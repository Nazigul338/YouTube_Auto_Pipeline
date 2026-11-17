"""Үн лабораториясы (СЫНАК): бир эле орусча мотивациялык текстти ар кандай үн/интонацияда окутуп салыштырат.

    YTA_DRIVE_FOLDER=YouTube_Auto_TEST python -m pipeline.voice_lab

Үлгүлөр (ар бири = 1 TTS суроо; акысыз квота аз болгондуктан 4 гана):
  A  Algenib + учурдагы стиль (niche tts_style)             — азыркы өндүрүш
  B  Algenib + мотивациялык режиссура + паузалар/басым      — жаңы интонация
  C  Orus    + мотивациялык режиссура                         — салыштыруу үчүн башка эркек үн
  D  Charon  + мотивациялык режиссура                         — салыштыруу үчүн башка эркек үн
Өлчөөлөр: узактык, темп (сөз/мүн), Whisper дикция (текст канча так угулду), паузалар, үндүн бийиктиги
(F0 медиана — төмөн = терең) жана интонациянын өзгөрүлмөлүүлүгү (жарым тон, аз = монотон),
музыка менен аралаштыргандагы «үн − музыка» айырмасы (QA талабы ≥ 10 LU).
Натыйжа Drive'га: `YouTube_Auto_TEST/_voice_test/` (MP3: үн гана жана музыка менен) + отчет.
Production'го эч нерсе жазылбайт.
"""

from __future__ import annotations

import json
import math
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

from . import media, voice_style

TEXT = (
    "Ты когда-нибудь замечал, как легко отложить важное на завтра? Кажется, что впереди ещё много "
    "времени… Но время не ждёт. Каждый день, который ты откладываешь, становится выбором — выбором "
    "остаться на месте. Запомни: никто не придёт и не сделает это за тебя. Сила не в том, чтобы ни разу "
    "не упасть. Сила в том, чтобы подняться — снова и снова. Начни с малого. Один шаг сегодня. Ещё один "
    "завтра. И однажды ты оглянешься и не узнаешь себя. Так чего же ты ждёшь? Твоя жизнь начинается "
    "прямо сейчас."
)
KEYWORDS = ["время не ждёт", "никто не придёт", "подняться", "один шаг", "прямо сейчас"]


def variants(baseline_style: str) -> list[dict]:
    shaped = voice_style.shape_text(TEXT)
    direction = voice_style.direction(KEYWORDS)
    return [
        {"id": "A", "label": "Algenib — учурдагы стиль", "voice": "Algenib", "style": baseline_style,
         "text": TEXT},
        {"id": "B", "label": "Algenib — мотивациялык режиссура", "voice": "Algenib", "style": direction,
         "text": shaped},
        {"id": "C", "label": "Orus — мотивациялык режиссура", "voice": "Orus", "style": direction,
         "text": shaped},
        {"id": "D", "label": "Charon — мотивациялык режиссура", "voice": "Charon", "style": direction,
         "text": shaped},
    ]


def pitch_stats(wav: Path) -> dict:
    """Жөнөкөй автокорреляция менен F0 (75–300 Гц): медиана жана өзгөрүлмөлүүлүк (жарым тон std)."""
    import numpy as np

    x = media.decode_float32(wav, 16000)
    sr, n, hop = 16000, 640, 320
    f0 = []
    for i in range(0, len(x) - n, hop):
        fr = x[i:i + n] * np.hanning(n)
        if np.sqrt(np.mean(fr ** 2)) < 0.02:
            continue
        ac = np.correlate(fr, fr, "full")[n - 1:]
        lo, hi = sr // 300, sr // 75
        k = lo + int(np.argmax(ac[lo:hi]))
        if ac[0] > 0 and ac[k] / ac[0] > 0.45:
            f0.append(sr / k)
    if len(f0) < 20:
        return {"f0_median": None, "f0_var_semitones": None}
    f = np.array(f0)
    med = float(np.median(f))
    st = 12 * np.log2(f / med)
    return {"f0_median": round(med, 1), "f0_var_semitones": round(float(np.std(st)), 2)}


def analyze(wav: Path, text: str, listen) -> dict:
    from .stages.s3_voice import check_heard
    from . import asr

    dur = media.duration(wav)
    exp = [asr.norm_word(w) for w in text.split() if asr.norm_word(w)]
    heard = [w for w, _, _ in listen(wav, text)]
    extra, cov, gap = check_heard(exp, heard)
    pauses = [d for s, d in media.silences(wav, -38, 0.35) if 0.2 < s < dur - 0.4]
    return {"duration": round(dur, 2), "wpm": round(len(exp) / (dur / 60), 1),
            "diction_coverage": round(cov, 3), "instruction_read": extra > 1, "max_gap_words": gap,
            "pauses": len(pauses), "longest_pause": round(max(pauses), 2) if pauses else 0.0,
            **pitch_stats(wav)}


def with_music(voice_wav: Path, track: Path, out_dir: Path) -> dict:
    """s7 аралаштыруусу (ducking) менен: «үн − музыка» айырмасы."""
    from .stages.s7_music import mix

    d = out_dir / "mix"
    (d / "audio").mkdir(parents=True, exist_ok=True)
    norm = d / "audio" / "voice.wav"
    media.run(["ffmpeg", "-y", "-v", "error", "-i", str(voice_wav), "-af",
               "highpass=f=60,loudnorm=I=-16:TP=-1.5:LRA=11", "-ar", "48000", "-ac", "1", str(norm)],
              "үн нормалдаштыруу")
    ctx = SimpleNamespace(path=lambda *p: d.joinpath(*p))
    lv = mix(ctx, track, media.duration(norm) + 1.0)
    return {"mix_path": d / "audio" / "mix.wav", "voice_minus_music_lu": round(lv["voice_lufs"] - lv["bed_lufs"], 1)}


def mp3(src: Path, dst: Path) -> Path:
    media.run(["ffmpeg", "-y", "-v", "error", "-i", str(src), "-c:a", "libmp3lame", "-b:a", "192k", str(dst)], "mp3")
    return dst


def main() -> int:
    from .config import load_config
    from .drive import DriveClient
    from .gemini import from_config
    from . import asr
    from .storage import DriveStore

    root = os.environ.get("YTA_DRIVE_FOLDER", "YouTube_Auto_TEST")
    if root != "YouTube_Auto_TEST":
        print("❌ Үн лабораториясы TEST папкасында гана иштейт")
        return 2
    cfg = load_config("motivation")
    g = from_config(cfg, log=print)
    listen = asr.get(SimpleNamespace(services={}, cfg=cfg, log=print))
    drive = DriveClient.from_env()
    store = DriveStore(drive, root) if drive else None
    rows, links = [], {}
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        track = None
        if store:
            store.ensure_layout()
            n = store.pull_music(d / "music")
            tracks = sorted(p for p in (d / "music").rglob("*") if p.suffix.lower() in (".mp3", ".wav", ".m4a"))
            track = tracks[0] if tracks else None
            print(f"🎵 Музыка: {n} файл; тест үчүн: {track.name if track else 'жок'}")
        for v in variants(cfg.niche_data.get("tts_style", "")):
            wav = d / f"{v['id']}.wav"
            try:
                pcm, rate = g.tts(v["text"], voice=v["voice"], style=v["style"], variant=0)
            except Exception as e:
                print(f"⚠️ {v['id']} ({v['label']}): TTS иштеген жок — {type(e).__name__}: {str(e)[:160]}")
                rows.append({**v, "error": f"{type(e).__name__}"})
                continue
            media.write_wav(wav, pcm, rate)
            a = analyze(wav, TEXT, listen)
            row = {"id": v["id"], "label": v["label"], "voice": v["voice"], **a}
            if track:
                m = with_music(wav, track, d / v["id"])
                row["voice_minus_music_lu"] = m["voice_minus_music_lu"]
                if store:
                    links[f"{v['id']}_music"] = store.publish("_voice_test", mp3(m["mix_path"], d / f"{v['id']}_music.mp3"),
                                                            f"{v['id']}_{v['voice']}_with_music.mp3")
            if store:
                links[v["id"]] = store.publish("_voice_test", mp3(wav, d / f"{v['id']}.mp3"),
                                               f"{v['id']}_{v['voice']}_voice.mp3")
            rows.append(row)
            print(json.dumps(row, ensure_ascii=False))
        table = ["| Үлгү | Узактык | Темп | Дикция | Паузалар (эң узун) | F0 медиана | Интонация (жарым тон) | Үн−музыка | Угуу |",
                 "|---|---|---|---|---|---|---|---|---|"]
        for r in rows:
            if "error" in r:
                table.append(f"| {r['id']} {r['label']} | TTS иштеген жок: {r['error']} | | | | | | | |")
                continue
            table.append(
                f"| {r['id']} {r['label']} | {r['duration']} сек | {r['wpm']} | {r['diction_coverage']:.0%}"
                f"{' ⚠️ нускама окулду' if r['instruction_read'] else ''} | {r['pauses']} ({r['longest_pause']} сек) | "
                f"{r['f0_median']} Гц | {r['f0_var_semitones']} | {r.get('voice_minus_music_lu', '—')} LU | "
                f"[үн]({links.get(r['id'], '')}) · [музыка менен]({links.get(r['id'] + '_music', '')}) |")
        md = "\n".join(table)
        print(md)
        report = d / "voice_report.json"
        report.write_text(json.dumps({"text": TEXT, "rows": rows, "links": links}, ensure_ascii=False, indent=1),
                          encoding="utf-8")
        if store:
            store.publish("_voice_test", report, "voice_report.json")
        path = os.environ.get("GITHUB_STEP_SUMMARY")
        if path:
            with open(path, "a", encoding="utf-8") as f:
                f.write("## 🎙 Үн лабораториясы\n\nТекст:\n\n> " + TEXT + "\n\n" + md + "\n")
    return 0 if any("error" not in r for r in rows) else 1


if __name__ == "__main__":
    sys.exit(main())
