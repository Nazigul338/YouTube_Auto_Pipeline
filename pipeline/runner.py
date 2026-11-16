"""Этаптарды ирети менен иштетүүчү негизги модуль.

GitHub Actions'та `pipeline.ci` аркылуу `execute()` чакырылат.
Жергиликтүү тест үчүн `run()` (папканы өзү түзөт).
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
from .stages.base import Context, NotImplementedStage, StageError, TransientError
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
    return execute(ctx, rerun_from=rerun_from, stop_after=stop_after)


def execute(ctx: Context, *, rerun_from: str | None = None, stop_after: str | None = None,
            checkpoint: Callable[[VideoState], None] | None = None,
            sleep: Callable[[float], None] | None = None) -> VideoState:
    """Этаптарды ирети менен аткарат.

    checkpoint — ар бир этаптан кийин (ийгиликтүү же ийгиликсиз) чакырылат:
                 GitHub'та абалды Drive'га сактоо үчүн.
    TransientError (API убактылуу иштебесе) — этап кайра аракет кылынат.
    """
    state, log = ctx.state, ctx.log
    sleep = sleep or time.sleep
    for arg in (rerun_from, stop_after):
        if arg and arg not in STAGE_NAMES:
            raise ValueError(f"Белгисиз этап: '{arg}'. Бар этаптар: {STAGE_NAMES}")

    if rerun_from:
        start = STAGE_NAMES.index(rerun_from)
        for name in STAGE_NAMES[start:]:
            state.reset(name)
        log(f"🔁 «{rerun_from}» этабынан баштап кайра иштетилет.")

    def save_point() -> None:
        if checkpoint:
            try:
                checkpoint(state)
            except Exception as e:  # сактоо катасы этапты бузбасын, бирок унчукпай калбасын
                log(f"⚠ Абалды сактоо ишке ашкан жок: {type(e).__name__}: {e}")

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
        t0 = time.time()
        attempts = 1 + max(0, getattr(stage, "retries", 1))
        stop = False
        for attempt in range(1, attempts + 1):
            state.mark_running(stage.name)
            try:
                outputs = stage.run(ctx)
                stage.verify(ctx, outputs)
            except NotImplementedStage as e:
                state.reset(stage.name)
                log(f"⏸ {header}: {e}")
                log("\nСистема ушул жерге чейин иштеди. Бүткөн этаптар сакталды.")
                stop = True
            except TransientError as e:
                if attempt < attempts:
                    wait = 30 * attempt
                    log(f"⚠ {header}: убактылуу ката ({e}). {wait} сек кийин кайра аракет "
                        f"({attempt + 1}/{attempts})...")
                    sleep(wait)
                    continue
                state.mark_failed(stage.name, str(e))
                _report_failure(log, i, stage, str(e), detail=None)
                stop = True
            except StageError as e:
                state.mark_failed(stage.name, str(e))
                _report_failure(log, i, stage, str(e), detail=None)
                stop = True
            except Exception as e:  # күтүлбөгөн ката
                detail = traceback.format_exc()
                state.mark_failed(stage.name, f"{type(e).__name__}: {e}")
                _report_failure(log, i, stage, f"{type(e).__name__}: {e}", detail)
                stop = True
            else:
                state.mark_done(stage.name, outputs)
                log(f"✅ {header} — даяр ({time.time() - t0:.0f} сек)")
                if stop_after == stage.name:
                    log(f"\n⏹ «{stage.title}» этабынан кийин токтотулду (stop_after).")
                    stop = True
            break
        save_point()
        if stop:
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
    log("\nОңдогондон кийин ушул видеонун ID'си менен кайра иштетиңиз — "
        "система ушул этаптан улантат.")
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
