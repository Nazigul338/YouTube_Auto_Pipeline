"""7-этап: Фондук музыка (тандоо + аралаштыруу).

  - Китепкана: Drive → YouTube_Auto/Music/<булак>/ (булагы белгисиз трек колдонулбайт).
  - Маанай: ар трек БИР ЖОЛУ Gemini аркылуу «угулат» (маанай, энергия, вокал бар-жогу);
    жыйынтык Music/_tags.json'го сакталат — кийинки видеолордо кайра сурабайт.
  - Тандоо: сахналардын басымдуу маанайына дал келген, вокалсыз, эң аз колдонулган трек.
  - Аралаштыруу: музыка циклге алынат/кесилет, башы-аягы жумшак; диктор сүйлөгөндө
    музыка автоматтык басаңдайт (sidechain ducking); жыйынтык −14 LUFS.
  - Лицензия жана атрибуция жазылат.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .. import media, sfx
from ..music import attribution_text, scan
from .base import Context, Stage, StageError, gemini_of

MUSIC_BED_LUFS = -31.0     # дикторго (−16) салыштырмалуу ~15 LU төмөн
DUCK = "threshold=0.02:ratio=6:attack=25:release=450:makeup=1"
# СЫНАК (cinematic): «угулуучу» музыка. Колдонуучу (2026-11-20): «фоновой музыка, үн эффект жок го» —
# −31 LUFS + ratio 6 басаңдатуу сүйлөө учурунда музыканы диктордон ~26 LU төмөн түшүргөн (телефондо угулбайт).
AUDIBLE_BED_LUFS = -21.0     # сүйлөө учурунда диктордон ~12 LU акырын (мурунку жол: ~27 LU — угулбайт)
AUDIBLE_DUCK = "threshold=0.05:ratio=2.5:attack=60:release=900:makeup=1"
AUDIBLE_RANGE = (9.0, 16.0)   # диктор − басаңдатылган музыка, LU: угулат, бирок дикторду баспайт
TAG_PROMPT = ("Listen to this music track. Return JSON only: "
              '{{"mood": one of {moods}, "energy": "low"|"medium"|"high", '
              '"vocals": true|false}}. "vocals" is true if there is any singing or speech.')


def load_tags(music_root: Path) -> dict:
    p = music_root / "_tags.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def tag_tracks(ctx: Context, tracks, tags: dict, limit: int = 20) -> int:
    moods = ctx.cfg.niche_data.get("music_moods", [])
    g = gemini_of(ctx)
    new = 0
    for t in tracks:
        if t.rel in tags or new >= limit:
            continue
        try:
            from ..gemini import parse_json

            ans = parse_json(g.ask_about_file(t.path, TAG_PROMPT.format(moods=moods),
                                              purpose="music_tags"))
            mood = ans.get("mood") if ans.get("mood") in moods else None
            tags[t.rel] = {"mood": mood, "energy": ans.get("energy"),
                           "vocals": bool(ans.get("vocals"))}
            new += 1
            ctx.log(f"   🏷 {t.title}: {mood}, вокал: {tags[t.rel]['vocals']}")
        except Exception as e:
            ctx.log(f"   ⚠ «{t.title}» маанайы аныкталган жок: {type(e).__name__}")
    return new


def video_mood(scenes: list[dict]) -> str:
    weight: dict[str, int] = {}
    for s in scenes:
        weight[s["music_mood"]] = weight.get(s["music_mood"], 0) + s.get("words", 1)
    return max(weight, key=weight.get)


def used_by_finished(registry: dict, video_id: str) -> set[str]:
    """Башка ДАЯР видеолор колдонгон тректер (колдонуучу 2026-11-25: «фондук музыканы кайталап койбо»)."""
    return {v["music"] for k, v in registry.get("videos", {}).items()
            if k != video_id and v.get("status") == "ready" and v.get("music")}


def pick_track(tracks, tags: dict, mood: str, registry: dict, video_id: str):
    """Тандоо: (1) башка даяр видеолордун трегин ЖАНА бул видеонун мурунку трегин (кайра иштетүүдө) ЧЫГАРЫП салат —
    жаңы трек болбосо гана (китепкана түгөнсө) эң аз колдонулганы; (2) калгандардан маанайы дал келгени, анан эң аз
    колдонулганы. Кайтарат: (трек, себеп, күч менен кайталандыбы)."""
    usable = [t for t in tracks if t.is_known and not tags.get(t.rel, {}).get("vocals")]
    if not usable:
        return None, "вокалсыз, булагы белгилүү трек жок", False
    history = [v.get("music") for k, v in sorted(registry.get("videos", {}).items())
               if k != video_id and v.get("music")]
    own_prev = (registry.get("videos", {}).get(video_id) or {}).get("music")
    avoid = used_by_finished(registry, video_id) | ({own_prev} if own_prev else set())
    fresh = [t for t in usable if t.rel not in avoid]
    forced = not fresh
    pool = fresh or usable

    def rank(t):
        mood_ok = 0 if tags.get(t.rel, {}).get("mood") == mood else 1
        uses = history.count(t.rel)
        last = max((i for i, m in enumerate(history) if m == t.rel), default=-1)
        return (mood_ok, uses, last, t.rel)

    best = min(pool, key=rank)
    why = "маанайы дал келет" if tags.get(best.rel, {}).get("mood") == mood else \
        "маанайы дал келген жаңы вокалсыз трек жок — эң жакыны"
    if forced:
        why = "⚠ жаңы трек калган жок (китепкана түгөндү) — эң аз колдонулганы кайталанды"
    elif avoid:
        why += f"; мурунку трек(тер) чыгарылды: {len(avoid & {t.rel for t in usable})}"
    return best, why, forced


def audible_mode(ctx: Context) -> bool:
    from .. import cinematic

    return cinematic.enabled(ctx.store)


# Кино-окуянын музыкалык аркасы (актыга жараша фон деңгээли, дБ): интрига → тааныштыруу акырын → чыңалуу →
# бурулушта эмоционалдык чоку → өзгөрүү → үмүт. ±2 дБ — диктор/угулуу QA чегинде калат.
ARC_DB = {"hook": 1.0, "introduction": -1.5, "conflict": 0.5, "development": 0.0, "turning_point": 2.0,
          "transformation": 1.0, "final_message": 1.5}


def story_arc(ctx: Context) -> list[tuple[float, float, float]] | None:
    from .. import story

    if not story.is_story(ctx.cfg):
        return None
    try:
        acts = json.loads(ctx.path("script", "story.json").read_text(encoding="utf-8"))["acts"]
        words = json.loads(ctx.path("subtitles", "timings.json").read_text(encoding="utf-8"))["words"]
    except Exception:
        return None
    return [(a["start"], a["end"], ARC_DB.get(a["act"], 0.0)) for a in story.act_times(acts, words)]


def arc_filter(arc: list[tuple[float, float, float]] | None) -> str:
    """volume=…:eval=frame — актынын убактысында фон деңгээли (кадамдуу, ±2 дБ — ducking астында билинбейт)."""
    if not arc:
        return ""
    expr = "1"
    for a, b, db in reversed(arc):
        g = 10 ** (db / 20)
        expr = f"if(between(t\\,{a:.2f}\\,{b:.2f})\\,{g:.4f}\\,{expr})"
    return f",volume='{expr}':eval=frame"


def mix(ctx: Context, track_path: Path, total: float, sfx_bed: Path | None = None,
        sfx_hits: Path | None = None, audible: bool = False, level: float = 0.0,
        arc: list[tuple[float, float, float]] | None = None) -> dict:
    voice = ctx.path("audio", "voice.wav")
    bed = ctx.path("audio", "music_bed.wav")
    out = ctx.path("audio", "mix.wav")
    # 1) музыканын «төшөгү»: цикл, узактык, деңгээл, жумшак башталыш/аяктоо
    media.run(["ffmpeg", "-y", "-v", "error", "-stream_loop", "-1", "-i", str(track_path),
               "-t", f"{total:.3f}", "-af",
               f"loudnorm=I={(AUDIBLE_BED_LUFS + level) if audible else MUSIC_BED_LUFS}:TP=-6:LRA=11,afade=t=in:d=2.5,"
               f"afade=t=out:st={max(0.0, total - 3.5):.3f}:d=3.5" + arc_filter(arc),
               "-ar", "48000", "-ac", "2", str(bed)], "музыканы даярдоо")
    # 2) диктор сүйлөгөндө басаңдатуу + аралаштыруу + акыркы деңгээл
    duck = AUDIBLE_DUCK if audible else DUCK
    if sfx_bed is None and sfx_hits is None and not audible:   # негизги жол (өзгөргөн жок)
        media.run(["ffmpeg", "-y", "-v", "error", "-i", str(voice), "-i", str(bed), "-filter_complex",
                   "[0:a]aresample=48000,pan=stereo|c0=c0|c1=c0,apad[v];"
                   "[v]asplit=2[vk][vm];"
                   "[1:a][vk]sidechaincompress=threshold=0.02:ratio=6:attack=25:release=450:makeup=1[duck];"
                   "[vm][duck]amix=inputs=2:duration=longest:normalize=0,"
                   "loudnorm=I=-14:TP=-1.5:LRA=11[m]",
                   "-map", "[m]", "-t", f"{total:.3f}", "-ar", "48000", "-ac", "2", str(out)],
                  "аралаштыруу")
    else:   # СЫНАК: угулуучу музыка / үн эффекттери (фон музыка менен бирге басаңдайт; «сокку» — паузада)
        ins = ["-i", str(voice), "-i", str(bed)]
        g = "[0:a]aresample=48000,pan=stereo|c0=c0|c1=c0,apad[v];[v]asplit=2[vk][vm];"
        if sfx_bed is not None:
            ins += ["-i", str(sfx_bed)]
            g += "[1:a][2:a]amix=inputs=2:duration=first:normalize=0[bx];"
        else:
            g += "[1:a]anull[bx];"
        g += f"[bx][vk]sidechaincompress={duck}[duck];"
        if sfx_hits is not None:
            ins += ["-i", str(sfx_hits)]
            n = len(ins) // 2 - 1
            g += f"[vm][duck][{n}:a]amix=inputs=3:duration=first:normalize=0,"
        else:
            g += "[vm][duck]amix=inputs=2:duration=first:normalize=0,"
        g += "loudnorm=I=-14:TP=-1.5:LRA=11[m]"
        media.run(["ffmpeg", "-y", "-v", "error", *ins, "-filter_complex", g,
                   "-map", "[m]", "-t", f"{total:.3f}", "-ar", "48000", "-ac", "2", str(out)],
                  "аралаштыруу (+ үн эффекттери)")
    # loudnorm (бир өтүү) кескин эффекттерде чыныгы пикти ашырып жибериши мүмкүн (Video_005: +1.1 dBTP) → кепилдик
    res = {"bed_lufs": media.loudness(bed)["I"], "voice_lufs": media.loudness(voice)["I"],
           "mix": media.limit_true_peak(out, out)}
    if audible:   # угулган деңгээл: диктор сүйлөгөндө басаңдатылган музыка (+фон эффекттери) өзүнчө өлчөнөт
        tmp = ctx.path("audio", "_ducked_check.wav")
        ins = ["-i", str(voice), "-i", str(bed)] + (["-i", str(sfx_bed)] if sfx_bed is not None else [])
        g = ("[0:a]aresample=48000,pan=stereo|c0=c0|c1=c0,apad[vk];"
             + ("[1:a][2:a]amix=inputs=2:duration=first:normalize=0[bx];" if sfx_bed is not None else "[1:a]anull[bx];")
             + f"[bx][vk]sidechaincompress={duck}[d]")
        media.run(["ffmpeg", "-y", "-v", "error", *ins, "-filter_complex", g, "-map", "[d]",
                   "-t", f"{total:.3f}", "-ar", "48000", "-ac", "2", str(tmp)], "музыканын угулушу")
        res["music_ducked_lufs"] = media.loudness(tmp)["I"]
        res["profile"] = "audible"
        tmp.unlink(missing_ok=True)
    for key, p in (("sfx_bed_lufs", sfx_bed), ("sfx_hits_lufs", sfx_hits)):
        if p is not None:
            res[key] = media.loudness(p)["I"]
    return res


class MusicStage(Stage):
    name = "s7_music"
    title = "Фондук музыка"
    retries = 1

    def run(self, ctx: Context) -> dict[str, Any]:
        scenes = json.loads(ctx.path("scenes.json").read_text(encoding="utf-8"))["scenes"]
        total = json.loads(ctx.path("clips", "shots.json").read_text(encoding="utf-8"))["total"]
        root = ctx.cfg.music_root
        tracks = scan(root)
        if not [t for t in tracks if t.is_known]:
            raise StageError("Музыка китепканасында булагы белгилүү трек жок "
                             "(Drive → YouTube_Auto/Music/<булак>/)")
        tags = load_tags(root)
        if tag_tracks(ctx, tracks, tags):
            (root / "_tags.json").write_text(json.dumps(tags, ensure_ascii=False, indent=1),
                                             encoding="utf-8")
            if ctx.store and hasattr(ctx.store, "save_music_tags"):
                ctx.store.save_music_tags(tags)

        mood = video_mood(scenes)
        from .. import edit_concept
        brief = edit_concept.get(ctx, scenes) if edit_concept.enabled(ctx) else None
        if brief and brief.get("music_mood") and any(v.get("mood") == brief["music_mood"] for v in tags.values()):
            mood = brief["music_mood"]          # концепциянын музыкалык атмосферасы
        track, why, forced_repeat = pick_track(tracks, tags, mood, ctx.registry, ctx.video_id)
        if track is None:
            raise StageError(f"Музыка тандалган жок: {why}")
        ctx.log(f"   Видеонун маанайы: {mood} → «{track.title}» ({why})")

        sfx_bed = sfx_hits = None
        if sfx.enabled(ctx.store):   # СЫНАК гана (YTA_SFX=1 + YouTube_Auto_TEST)
            sfx.build_sfx(ctx, scenes, total)
            sfx_bed, sfx_hits = sfx.tracks_for_mix(ctx, total)
        else:
            if sfx.blocked_reason(ctx.store):
                ctx.log("   ⚠️ " + sfx.blocked_reason(ctx.store))
            stale = ctx.path("music", "sfx.json")
            if stale.exists():
                stale.unlink()   # мурунку сынактын эффекттери бул жолу колдонулбайт
        levels = mix(ctx, track.path, total, sfx_bed, sfx_hits, audible=audible_mode(ctx),
                     level=float((brief or {}).get("music_level", 0.0)), arc=story_arc(ctx))
        rel = levels["voice_lufs"] - levels["bed_lufs"]
        if levels.get("music_ducked_lufs") is not None:   # СЫНАК: чыныгы угулган деңгээл
            rel = levels["voice_lufs"] - levels["music_ducked_lufs"]
            levels["voice_minus_ducked_music_lu"] = round(rel, 1)
            ctx.log(f"   🎵 Угулган музыка (басаңдатылгандан кийин) диктордон {rel:.1f} LU акырын "
                    f"(керек {AUDIBLE_RANGE[0]:.0f}–{AUDIBLE_RANGE[1]:.0f})")
        sfx_vals = [levels[k] for k in ("sfx_bed_lufs", "sfx_hits_lufs") if levels.get(k) is not None]
        if sfx_vals:
            levels["voice_minus_sfx_lu"] = round(levels["voice_lufs"] - max(sfx_vals), 1)
            ctx.log(f"   🔊 Диктор эффекттерден {levels['voice_minus_sfx_lu']} LU катуу (керек ≥ 10)")
        ctx.log(f"   ✓ Аралаштырылды: диктор {levels['voice_lufs']:.1f} LUFS, музыка "
                f"{levels['bed_lufs']:.1f} LUFS (айырма {rel:.1f} LU), жыйынтык {levels['mix']['I']} LUFS")
        arc = story_arc(ctx)
        if arc:
            ctx.log("   🎼 Музыкалык арка (актыга жараша): " + ", ".join(f"{a:.0f}–{b:.0f}с {db:+.1f}дБ" for a, b, db in arc))
        info = {"track": track.rel, "title": track.title, "mood": mood, "why": why, "arc": arc,
                "tags": tags.get(track.rel), "levels": levels, "voice_minus_music_lu": round(rel, 1),
                "license": track.license_record(), "attribution": attribution_text(track),
                "repeat_forced": forced_repeat}
        out = ctx.path("music", "music.json")
        out.write_text(json.dumps(info, ensure_ascii=False, indent=1), encoding="utf-8")
        ctx.registry.setdefault("videos", {}).setdefault(ctx.video_id, {})["music"] = track.rel
        return {"music_file": str(out), "mix_path": str(ctx.path("audio", "mix.wav"))}


def ensure_mix(ctx: Context) -> Path:
    """mix.wav Drive'га жүктөлбөйт (оор) — жаңы runner'де кайра түзүлөт."""
    out = ctx.path("audio", "mix.wav")
    if not out.exists():
        info = json.loads(ctx.path("music", "music.json").read_text(encoding="utf-8"))
        total = json.loads(ctx.path("clips", "shots.json").read_text(encoding="utf-8"))["total"]
        bed, hits = sfx.tracks_for_mix(ctx, total)
        b = ctx.registry.get("videos", {}).get(ctx.video_id, {}).get("edit_brief") or {}
        mix(ctx, ctx.cfg.music_root / info["track"], total, bed, hits, audible=audible_mode(ctx),
            level=float(b.get("music_level", 0.0)) if audible_mode(ctx) else 0.0)
    return out
