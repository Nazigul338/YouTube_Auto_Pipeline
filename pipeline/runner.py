"""Этаптарды ирети менен иштетүүчү негизги модуль.

Колдонуу (Colab'да):
    from pipeline.runner import run
    run("Почему ты откладываешь жизнь на завтра")
"""

from __future__ import annotations

import time
import traceback
from datetime import datetime
from pathlib import Path
from typing import Callable

from .config import Config, load_config
from .project import find_video_folder, list_videos, new_video_folder
from .stages import STAGE_NAMES, STAGES
from .stages.base import Context, NotImplementedStage, StageError
from .state import DONE, FAILED, STATUS_ICON, VideoState


def _make_logger(folder: Path) -> Callable[[str], None]:
    log_file = folder / "logs" / "run.log"
    log_file.parent.mkdir(parents=True, exist_ok=True)

    def log(msg: str) -> None:
        print(msg, flush=True)
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(log_file, "a", encoding="utf-8") as f:
            for line in str(msg).splitlines() or [""]:
                f.write(f"[{stamp}] {line}\n")

    return log


def _open_project(cfg: Config, topic: str, new: bool) -> tuple[Path, VideoState, bool]:
    if not new:
        folder = find_video_folder(cfg, topic)
        if folder is not None:
            state = VideoState.load(folder)
            state.ensure_stages(STAGE_NAMES)
            state.save()
            return folder, state, True
    folder = new_video_folder(cfg, topic)
    return folder, VideoState.create(folder, topic, cfg.niche, STAGE_NAMES), False


def run(topic: str, niche: str = "motivation", *, new: bool = False,
        rerun_from: str | None = None, stop_after: str | None = None,
        cfg: Config | None = None) -> VideoState:
    """Видеону башынан аягына чейин (же калган жеринен) жасайт.

    topic       — видеонун темасы.
    niche       — ниша профили (niches/<ниша>.yaml).
    new         — True: ушул тема мурун болсо да, жаңы папка түзөт.
    rerun_from  — ушул этаптан баштап кайра иштетет (мис. "s3_voice").
                  Мурунку файлдар өчүрүлбөйт, жаңы версия түзүлөт.
    stop_after  — ушул этаптан кийин токтойт (этап-этабы менен текшерүү үчүн).
    """
    topic = (topic or "").strip()
    if not topic:
        raise ValueError("Тема бош. TOPIC талаасына теманы жазыңыз.")
    for arg in (rerun_from, stop_after):
        if arg and arg not in STAGE_NAMES:
            raise ValueError(f"Белгисиз этап: '{arg}'. Бар этаптар: {STAGE_NAMES}")

    cfg = cfg or load_config(niche)
    folder, state, resumed = _open_project(cfg, topic, new)
    log = _make_logger(folder)
    ctx = Context(cfg=cfg, state=state, folder=folder, log=log)

    log("=" * 56)
    log(f"🎬 ТЕМА: {topic}")
    log(f"📁 Папка: {folder}")
    log("↩️  Мурунку иш табылды — калган жеринен улантабыз." if resumed
        else "🆕 Жаңы видео папкасы түзүлдү.")
    log("=" * 56)

    if rerun_from:
        start = STAGE_NAMES.index(rerun_from)
        for name in STAGE_NAMES[start:]:
            state.reset(name)
        log(f"🔁 «{rerun_from}» этабынан баштап кайра иштетилет.")

    total = len(STAGES)
    t_all = time.time()

    for i, stage in enumerate(STAGES):
        header = f"[{i}/{total - 1}] {stage.title}"
        if state.status(stage.name) == DONE and not stage.always_run:
            log(f"{STATUS_ICON[DONE]} {header} — мурун бүткөн, өткөрүп жиберилди")
            if stop_after == stage.name:
                break
            continue

        log(f"\n🔄 {header} ...")
        state.mark_running(stage.name)
        t0 = time.time()
        try:
            outputs = stage.run(ctx)
            stage.verify(ctx, outputs)
        except NotImplementedStage as e:
            state.reset(stage.name)
            log(f"⏸ {header}: {e}")
            log("\nСистема ушул жерге чейин иштеди. Бүткөн этаптар сакталды.")
            break
        except StageError as e:
            state.mark_failed(stage.name, str(e))
            _report_failure(log, i, stage, str(e), detail=None)
            break
        except Exception as e:  # күтүлбөгөн ката
            detail = traceback.format_exc()
            state.mark_failed(stage.name, f"{type(e).__name__}: {e}")
            _report_failure(log, i, stage, f"{type(e).__name__}: {e}", detail)
            break
        else:
            state.mark_done(stage.name, outputs)
            log(f"✅ {header} — даяр ({time.time() - t0:.0f} сек)")
            if stop_after == stage.name:
                log(f"\n⏹ «{stage.title}» этабынан кийин токтотулду (stop_after).")
                break

    log(f"\n⏱ Жалпы убакыт: {(time.time() - t_all) / 60:.1f} мүн")
    print_status(state)
    return state


def _report_failure(log, i, stage, message, detail) -> None:
    log("\n" + "!" * 56)
    log(f"❌ {i}-ЭТАП ({stage.title}) ИШТЕГЕН ЖОК")
    log(f"Себеби: {message}")
    if detail:
        log("--- Техникалык маалымат ---")
        log(detail.strip()[-3000:])
    log(f"\nОңдогондон кийин кайра ▶ басыңыз — система ушул этаптан улантат.")
    log("!" * 56)


def print_status(state: VideoState) -> None:
    print("\n📋 ЭТАПТАРДЫН АБАЛЫ:")
    titles = {s.name: s.title for s in STAGES}
    for name in STAGE_NAMES:
        st = state.stage(name)
        icon = STATUS_ICON.get(st["status"], "?")
        extra = f" — {st['error'].splitlines()[0]}" if st["status"] == FAILED else ""
        print(f"  {icon} {titles.get(name, name)}{extra}")


def show_videos(niche: str = "motivation") -> None:
    """Drive'дагы бардык видеолордун тизмеси жана абалы."""
    cfg = load_config(niche)
    videos = list_videos(cfg)
    if not videos:
        print("Азырынча видео жок.")
        return
    for folder in videos:
        state = VideoState.load(folder)
        done = sum(1 for n in STAGE_NAMES
                   if n in state.data["stages"] and state.status(n) == DONE)
        print(f"📁 {folder.name}  —  {done}/{len(STAGE_NAMES)} этап  —  {state.topic}")
