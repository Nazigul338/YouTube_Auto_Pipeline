"""0-этап: Чөйрөнү текшерүү.

Видео жасоодон мурун керектүү нерселердин баары бар экенин текшерет:
FFmpeg, API ачкычтары, Drive'га жазуу мүмкүнчүлүгү, музыка папкасы, диск орду.
"""

from __future__ import annotations

import shutil
from typing import Any

from ..config import get_secret
from .base import Context, Stage, StageError

REQUIRED_SECRETS = ["GOOGLE_API_KEY", "PIXABAY_API_KEY"]
OPTIONAL_SECRETS = ["PEXELS_API_KEY"]
MUSIC_EXT = {".mp3", ".wav", ".m4a", ".ogg"}
MIN_FREE_GB = 5


class CheckStage(Stage):
    name = "s0_check"
    title = "Чөйрөнү текшерүү"
    always_run = True  # Colab ар ачылганда чөйрө жаңыдан текшерилет

    def run(self, ctx: Context) -> dict[str, Any]:
        problems: list[str] = []
        report: dict[str, Any] = {}

        # 1. FFmpeg
        for tool in ("ffmpeg", "ffprobe"):
            ok = shutil.which(tool) is not None
            report[tool] = ok
            ctx.log(f"   {'✓' if ok else '✗'} {tool}")
            if not ok:
                problems.append(f"{tool} орнотулган эмес")

        # 2. API ачкычтары (маанилери эч жерге жазылбайт)
        for name in REQUIRED_SECRETS:
            ok = bool(get_secret(name))
            report[name] = ok
            ctx.log(f"   {'✓' if ok else '✗'} {name}")
            if not ok:
                problems.append(
                    f"{name} табылган жок. Colab → сол панель 🔑 Secrets → "
                    f"'{name}' кошуп, 'Notebook access' күйгүзүңүз"
                )
        for name in OPTIONAL_SECRETS:
            ok = bool(get_secret(name))
            report[name] = ok
            ctx.log(f"   {'✓' if ok else '–'} {name} (милдеттүү эмес)")

        # 3. Drive'га жазуу
        probe = ctx.path("logs", ".write_test")
        try:
            probe.parent.mkdir(parents=True, exist_ok=True)
            probe.write_text("ok", encoding="utf-8")
            probe.unlink()
            report["drive_writable"] = True
            ctx.log("   ✓ Drive'га жазууга болот")
        except OSError as e:
            report["drive_writable"] = False
            problems.append(f"Drive'га жазуу мүмкүн эмес: {e}")

        # 4. Музыка (YouTube Audio Library'ден колго жүктөлөт)
        music_root = ctx.cfg.music_root
        music_root.mkdir(parents=True, exist_ok=True)
        tracks = [p for p in music_root.rglob("*") if p.suffix.lower() in MUSIC_EXT]
        report["music_tracks"] = len(tracks)
        if tracks:
            ctx.log(f"   ✓ Музыка: {len(tracks)} трек ({music_root})")
        else:
            ctx.log(
                f"   ⚠ Музыка папкасы бош: {music_root}\n"
                "     YouTube Studio → Audio Library'ден 3–5 трек жүктөп, ушул "
                "папкага салыңыз. (Музыка этабына чейин керек болот.)"
            )

        # 5. Диск орду (Colab'дын убактылуу диски)
        free_gb = shutil.disk_usage("/").free / 1024**3
        report["free_gb"] = round(free_gb, 1)
        ctx.log(f"   {'✓' if free_gb >= MIN_FREE_GB else '✗'} Бош орун: {free_gb:.1f} GB")
        if free_gb < MIN_FREE_GB:
            problems.append(f"Дискте орун аз ({free_gb:.1f} GB, керек ≥ {MIN_FREE_GB} GB)")

        if problems:
            raise StageError("Төмөнкүлөрдү оңдоңуз:\n  • " + "\n  • ".join(problems))

        report_path = ctx.path("logs", "check_report.json")
        import json
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2),
                               encoding="utf-8")
        return {"report_file": str(report_path)}
