"""Sound Effects Library — үн эффекттери (СЫНАК режими гана: YTA_SFX=1 + YouTube_Auto_TEST).

Китепкана (аудионун өзү ачык репозиторийде САКТАЛБАЙТ — лицензиялар «өзүнчө таратууга» тыюу салат):

    Drive: YouTube_Auto/Sound_Effects/<категория>/<файл>.wav + <файл>.metadata.json
    Репо:  assets/sound_effects/<категория>/  (структура, README, metadata үлгүсү; аудио .gitignore'до)

Категориялар: cinematic, atmosphere, nature, transitions, impact, emotional.

ЛИЦЕНЗИЯ КАПКАСЫ: аудио видеого ушул шарттардын БААРЫ аткарылганда гана кошулат:
  - жанында `<файл>.metadata.json` бар, милдеттүү талаалары толук;
  - `commercial_use` = true (каналдын ээси текшерип белгилеген);
  - лицензия уруксат берилген тизмеде (ALLOWED_LICENSES);
  - metadata'дагы категория папкага дал келет;
  - `sha256` жазылса — файлга дал келет (файл алмашып кетсе колдонулбайт).
Бир шарт аткарылбаса — аудио ЧЕТКЕ КАГЫЛАТ (себеби логго), видео эффектсиз деле жасалат.

Тандоо (сценага жараша): сахналардын маанайы (scenes.json), сахна алмашуулары жана диктордун
паузалары (timings.json, Whisper), кадрлардын тегдери (shots.json).
  transitions — сахна алмашканда, ≥20 сек аралык менен; impact — dramatic/tense/determined сахнанын
  башында (≤3, ≥45 сек); emotional/cinematic — hopeful/inspired сахнанын башында (≤3, ≥60 сек);
  nature/atmosphere — сахнанын фону (табият тегдери → nature; тынч маанай → atmosphere), ≤50% убакыт.
Деңгээл (диктордун өлчөнгөн катуулугуна салыштырмалуу): «сокку» эффекттери диктордун ПАУЗАСЫНА коюлат,
12–14 LU акырын (пик ≤ −6 dBFS); фондор 22–24 LU акырын жана музыка менен бирге диктор сүйлөгөндө
басаңдайт (sidechain). QA: диктор эффекттерден ≥10 LU катуу.

ZvukiPro ж.б. сайттардан АВТОМАТТЫК ЖҮКТӨӨ/SCRAPING ЖОК: аудиону каналдын ээси өзү салат.
"""

from __future__ import annotations

import hashlib
import json
import os
import random
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

FOLDER = "Sound_Effects"
CATEGORIES = ("cinematic", "atmosphere", "nature", "transitions", "impact", "emotional")
HIT_CATS = ("transitions", "impact", "cinematic", "emotional")
BED_CATS = ("atmosphere", "nature")
AUDIO_EXT = {".wav", ".mp3", ".ogg", ".m4a", ".flac"}
META_SUFFIX = ".metadata.json"
REPO_ASSETS = Path(__file__).resolve().parents[1] / "assets" / "sound_effects"

# Колдонуучу бекиткен лицензиялар (2026-11-19). Ачкыч — нормалдаштырылган аты.
ALLOWED_LICENSES = {
    "cc0": "CC0 1.0 (Public Domain)",
    "cc0 1.0": "CC0 1.0 (Public Domain)",
    "cc0 1.0 universal": "CC0 1.0 (Public Domain)",
    "creative commons zero": "CC0 1.0 (Public Domain)",
    "pixabay content license": "Pixabay Content License",
    "pixabay license": "Pixabay Content License",
    "mixkit free license": "Mixkit Free License",
    "mixkit sound effects free license": "Mixkit Free License",
}
REQUIRED = ("title", "file", "category", "source", "source_url", "license", "commercial_use",
            "verified_by", "verified_at")

# Деңгээлдер — диктордун ӨЛЧӨНГӨН катуулугуна салыштырмалуу (LU төмөн; mean_volume ≈ LUFS)
REL_LU = {"transitions": 14.0, "impact": 12.0, "cinematic": 13.0, "emotional": 14.0,
          "atmosphere": 24.0, "nature": 22.0}
PEAK_CEIL_DB = -6.0        # эффекттин пиги мындан ашпайт
TRACK_REL_LU = {"hit": 11.0, "bed": 17.0}   # трек диктордон канча LU акырын (ЧЫНЫГЫ өлчөө); 13/23 угулган эмес (2026-11-20)
MAX_GAIN_DB = 12.0
# Тандоо эрежелери
MIN_PAUSE = 0.35          # диктордун паузасы (сек)
SNAP = 1.0                # сахна чеги ↔ пауза (сек)
HIT_SPACING = 12.0
TRANS_SPACING, IMPACT_SPACING, SWELL_SPACING = 20.0, 45.0, 60.0
MAX_IMPACT, MAX_SWELL, MAX_HITS = 3, 3, 30
BED_MIN_SCENE, BED_SHARE, BED_FADE = 12.0, 0.5, 1.5
IMPACT_EMO = {"dramatic", "tense", "determined"}
SWELL_EMO = {"hopeful", "inspired"}
CALM_EMO = {"calm", "reflective", "sad"}
NATURE_WORDS = {"nature", "forest", "tree", "trees", "sea", "ocean", "wave", "waves", "beach", "rain",
                "river", "water", "waterfall", "stream", "lake", "bird", "birds", "wind", "field",
                "grass", "mountain", "mountains", "storm", "thunder", "fire", "campfire", "night"}


# ---------------------------------------------------------------- режим

def requested() -> bool:
    return os.environ.get("YTA_SFX", "").strip().lower() in ("1", "true", "yes")


def enabled(store=None) -> bool:
    """Желек + СЫНАК папкасы (LocalStore — тесттер). Production'го колдонуучунун уруксаты керек."""
    if not requested():
        return False
    from . import cinematic
    from .storage import LocalStore

    if isinstance(store, LocalStore):
        return True
    return cinematic.root_name(store) == cinematic.TEST_ROOT


def blocked_reason(store=None) -> str | None:
    if requested() and not enabled(store):
        from . import cinematic

        return (f"YTA_SFX=1, бирок папка «{cinematic.root_name(store) or '?'}» — үн эффекттери "
                f"{cinematic.TEST_ROOT} үчүн гана. Өчүк калды.")
    return None


# ---------------------------------------------------------------- китепкана жана лицензия

@dataclass
class Sfx:
    rel: str                      # "<категория>/<файл>"
    path: Path
    category: str
    meta: dict
    sha256: str
    tags: set = field(default_factory=set)
    moods: set = field(default_factory=set)

    def license_record(self) -> dict:
        m = self.meta
        return {"file": self.rel, "title": m["title"], "source": m["source"], "source_url": m["source_url"],
                "author": m.get("author", ""), "license": license_name(m["license"]),
                "license_url": m.get("license_url", ""), "commercial_use": True,
                "attribution_required": bool(m.get("attribution_required")),
                "verified_by": m["verified_by"], "verified_at": m["verified_at"], "sha256": self.sha256}


def license_name(raw: str) -> str | None:
    """Уруксат берилген лицензиянын так аты (лакап аты да, так аты да кабыл алынат) же None."""
    key = re.sub(r"\s+", " ", str(raw or "").strip().lower())
    if key in ALLOWED_LICENSES:
        return ALLOWED_LICENSES[key]
    canon = {v.lower(): v for v in ALLOWED_LICENSES.values()}
    return canon.get(key)


def sha256_of(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def check_meta(meta: dict | None, category: str, filename: str, digest: str | None) -> str | None:
    """None — аудио колдонууга болот; болбосо четке кагуунун себеби (кыргызча)."""
    if not isinstance(meta, dict):
        return "metadata.json жок же туура эмес JSON"
    missing = [k for k in REQUIRED if meta.get(k) in (None, "", [])]
    if missing:
        return "metadata толук эмес: " + ", ".join(missing)
    if meta.get("commercial_use") is not True:
        return "commercial_use ≠ true (коммерциялык колдонууга уруксат тастыкталган эмес)"
    if not license_name(meta["license"]):
        return f"лицензия «{meta['license']}» уруксат берилген тизмеде жок"
    if str(meta["category"]).strip().lower() != category:
        return f"категория «{meta['category']}» папкага («{category}») дал келбейт"
    if str(meta["file"]).strip() != filename:
        return f"metadata'дагы файл «{meta['file']}» ≠ «{filename}»"
    want = str(meta.get("sha256") or "").strip().lower()
    if want and digest and want != digest:
        return "sha256 дал келбейт (файл алмашкан)"
    return None


def load_library(*roots: Path) -> tuple[list[Sfx], list[dict]]:
    """Китепкананы окуйт: (уруксат берилгендер, четке кагылгандар [{file, reason}])."""
    ok: list[Sfx] = []
    rejected: list[dict] = []
    seen: set[str] = set()
    for root in roots:
        if not root or not Path(root).exists():
            continue
        for cat in CATEGORIES:
            d = Path(root) / cat
            if not d.is_dir():
                continue
            for p in sorted(d.iterdir()):
                if p.suffix.lower() not in AUDIO_EXT or not p.is_file():
                    continue
                rel = f"{cat}/{p.name}"
                if rel in seen:
                    continue
                seen.add(rel)
                mp = p.with_name(p.stem + META_SUFFIX)
                try:
                    meta = json.loads(mp.read_text(encoding="utf-8")) if mp.exists() else None
                except (ValueError, OSError):
                    meta = None
                digest = sha256_of(p)
                why = check_meta(meta, cat, p.name, digest)
                if why:
                    rejected.append({"file": rel, "reason": why})
                    continue
                ok.append(Sfx(rel, p, cat, meta, digest,
                              {str(t).lower() for t in meta.get("tags", [])},
                              {str(t).lower() for t in meta.get("mood", [])}))
    return ok, rejected


# ---------------------------------------------------------------- өлчөө (FFmpeg)

def measure(p: Path) -> dict:
    """Узактык, пик жана орточо деңгээл (volumedetect) — кыска эффекттерге да иштейт."""
    r = subprocess.run(["ffmpeg", "-hide_banner", "-v", "info", "-i", str(p), "-af", "volumedetect",
                        "-f", "null", "-"], capture_output=True, text=True, timeout=120)
    peak = re.search(r"max_volume:\s*(-?[\d.]+) dB", r.stderr)
    mean = re.search(r"mean_volume:\s*(-?[\d.]+) dB", r.stderr)
    dur = re.search(r"Duration:\s*(\d+):(\d+):([\d.]+)", r.stderr)
    d = (int(dur.group(1)) * 3600 + int(dur.group(2)) * 60 + float(dur.group(3))) if dur else 0.0
    return {"dur": round(d, 3), "peak": float(peak.group(1)) if peak else None,
            "mean": float(mean.group(1)) if mean else None}


def gain_for(category: str, m: dict, voice_lufs: float) -> float:
    """Эффект диктордон REL_LU[category] төмөн угулсун; пик PEAK_CEIL_DB'ден ашпасын."""
    target = voice_lufs - REL_LU[category]
    g = target - (m["mean"] if m.get("mean") is not None else target)
    if m.get("peak") is not None:
        g = min(g, PEAK_CEIL_DB - m["peak"])
    return round(min(MAX_GAIN_DB, g), 2)


# ---------------------------------------------------------------- тандоо

def pauses(words: list[dict], total: float, min_gap: float = MIN_PAUSE) -> list[tuple[float, float]]:
    """Диктор сүйлөбөгөн аралыктар [(башы, аягы)]."""
    out = []
    prev = 0.0
    for w in words:
        if w["s"] - prev >= min_gap:
            out.append((round(prev, 3), round(w["s"], 3)))
        prev = max(prev, w["e"])
    if total - prev >= min_gap:
        out.append((round(prev, 3), round(total, 3)))
    return out


def near_pause(t: float, gaps: list[tuple[float, float]], snap: float = SNAP):
    best = None
    for a, b in gaps:
        dist = 0.0 if a <= t <= b else min(abs(t - a), abs(t - b))
        if dist <= snap and (best is None or dist < best[0]):
            best = (dist, a, b)
    return (best[1], best[2]) if best else None


def _pick(rng: random.Random, items: list[Sfx], recent: list[str], *, mood: str = "", tags: set = frozenset()):
    if not items:
        return None
    fresh = [s for s in items if s.rel not in recent[-2:]] or items

    def score(s: Sfx) -> int:
        return (2 if mood and mood in s.moods else 0) + len(s.tags & tags)

    top = max(score(s) for s in fresh)
    return rng.choice([s for s in fresh if score(s) == top])


def plan(scenes: list[dict], timing: dict, shots: list[dict], library: list[Sfx],
         total: float, seed: str) -> list[dict]:
    """Эффекттердин планы: [{t, dur, rel, category, kind: hit|bed, reason, in_pause}]."""
    rng = random.Random(f"sfx:{seed}")
    by_cat: dict[str, list[Sfx]] = {c: [s for s in library if s.category == c] for c in CATEGORIES}
    if not library:
        return []
    emo = {s["id"]: s.get("emotion", "") for s in scenes}
    st = timing.get("scenes", [])
    gaps = pauses(timing.get("words", []), total)
    events: list[dict] = []
    recent: list[str] = []
    last = {"hit": -1e9, "transitions": -1e9, "impact": -1e9, "swell": -1e9}
    n_imp = n_swell = 0

    # 1) «сокку» эффекттери — сахна чектеринде, диктордун паузасында
    for k in range(1, len(st)):
        t0 = st[k]["start"]
        gap = near_pause(t0, gaps)
        if not gap or t0 - last["hit"] < HIT_SPACING or len(events) >= MAX_HITS:
            continue
        e = emo.get(st[k]["id"], "")
        cat = reason = None
        if e in IMPACT_EMO and n_imp < MAX_IMPACT and t0 - last["impact"] >= IMPACT_SPACING and by_cat["impact"]:
            cat, reason = "impact", f"сахна {st[k]['id']}: {e}"
        elif e in SWELL_EMO and n_swell < MAX_SWELL and t0 - last["swell"] >= SWELL_SPACING and \
                (by_cat["emotional"] or by_cat["cinematic"]):
            cat = "emotional" if by_cat["emotional"] and (not by_cat["cinematic"] or rng.random() < 0.6) \
                else "cinematic"
            reason = f"сахна {st[k]['id']}: {e}"
        elif t0 - last["transitions"] >= TRANS_SPACING and by_cat["transitions"] and rng.random() < 0.75:
            cat, reason = "transitions", f"сахна {st[k - 1]['id']}→{st[k]['id']}"
        if not cat:
            continue
        s = _pick(rng, by_cat[cat], recent, mood=e)
        a, b = gap
        t = round(a + 0.05, 3)
        dur = round(min(s.meta.get("_dur") or 2.0, (b - t) + 0.6, 4.0), 3)
        if dur < 0.2:
            continue
        events.append({"t": t, "dur": dur, "rel": s.rel, "category": cat, "kind": "hit",
                       "reason": reason, "in_pause": True, "pause": [a, b]})
        recent.append(s.rel)
        last["hit"] = t0
        if cat == "impact":
            n_imp += 1
            last["impact"] = t0
        elif cat in ("emotional", "cinematic"):
            n_swell += 1
            last["swell"] = t0
        else:
            last["transitions"] = t0

    # 2) фондор — сахнанын маанайына/кадрлардын тегине жараша
    bed_time = 0.0
    prev_bed = None
    for i, sc in enumerate(st):
        a = sc["start"] if i else 0.0
        b = st[i + 1]["start"] if i + 1 < len(st) else total
        if b - a < BED_MIN_SCENE or bed_time + (b - a) > total * BED_SHARE:
            continue
        tags: set = set()
        for sh in shots:
            if sh.get("scene") == sc["id"]:
                txt = " ".join(str(sh.get(k) or "") for k in ("tags", "query", "theme"))
                tags |= set(re.split(r"[^a-z]+", txt.lower()))
        e = emo.get(sc["id"], "")
        nature = tags & NATURE_WORDS
        if nature and by_cat["nature"]:
            cat, reason = "nature", "кадрларда: " + ", ".join(sorted(nature)[:3])
        elif e in CALM_EMO and by_cat["atmosphere"]:
            cat, reason = "atmosphere", f"маанай: {e}"
        else:
            continue
        s = _pick(rng, [x for x in by_cat[cat] if x.rel != prev_bed] or by_cat[cat], recent, mood=e, tags=nature)
        events.append({"t": round(a, 3), "dur": round(b - a, 3), "rel": s.rel, "category": cat, "kind": "bed",
                       "reason": reason, "in_pause": None})
        bed_time += b - a
        prev_bed = s.rel
    return sorted(events, key=lambda ev: ev["t"])


# ---------------------------------------------------------------- рендер (FFmpeg)

def render(events: list[dict], files: dict[str, Path], gains: dict[str, float], total: float,
           out: Path, run: Callable | None = None) -> Path | None:
    """Бир түрдөгү эффекттерди (hit же bed) бир стерео трекке жыйнайт. Эффект жок болсо None."""
    if not events:
        return None
    args = ["ffmpeg", "-y", "-v", "error"]
    chains = []
    for n, ev in enumerate(events):
        if ev["kind"] == "bed":
            args += ["-stream_loop", "-1"]
        args += ["-i", str(files[ev["rel"]])]
        d = ev["dur"]
        fi = BED_FADE if ev["kind"] == "bed" else 0.01
        fo = min(BED_FADE if ev["kind"] == "bed" else 0.25, d / 2)
        ms = int(round(ev["t"] * 1000))
        chains.append(f"[{n}:a]aresample=48000,aformat=channel_layouts=stereo,atrim=0:{d:.3f},"
                      f"asetpts=PTS-STARTPTS,volume={gains[ev['rel']]:.2f}dB,afade=t=in:d={fi:.2f},"
                      f"afade=t=out:st={max(0.0, d - fo):.3f}:d={fo:.3f},adelay={ms}|{ms}[e{n}]")
    ins = "".join(f"[e{n}]" for n in range(len(events)))
    graph = ";".join(chains) + f";{ins}amix=inputs={len(events)}:normalize=0:duration=longest,apad[o]"
    args += ["-filter_complex", graph, "-map", "[o]", "-t", f"{total:.3f}", "-ar", "48000", "-ac", "2", str(out)]
    if run:
        run(args, "үн эффекттери")
    else:
        subprocess.run(args, check=True, capture_output=True, timeout=1800)
    return out


def library_roots(cfg) -> list[Path]:
    roots = [REPO_ASSETS]
    drive_root = getattr(cfg, "drive_root", None)
    if drive_root:
        roots.insert(0, Path(drive_root) / FOLDER)
    return roots


def build_sfx(ctx, scenes: list[dict], total: float) -> dict:
    from . import media

    lib, rejected = load_library(*library_roots(ctx.cfg))
    for r in rejected:
        ctx.log(f"   🔇 SFX четке кагылды: {r['file']} — {r['reason']}")
    info: dict[str, Any] = {"library_ok": len(lib), "rejected": rejected, "events": [], "licenses": []}
    if not lib:
        ctx.log("   🔇 Үн эффекттери: лицензиясы текшерилген аудио жок — эффектсиз улантылат")
        _save(ctx, info)
        return info
    meas = {}
    for s in lib:
        meas[s.rel] = measure(s.path)
        s.meta["_dur"] = meas[s.rel]["dur"]
    timing = json.loads(ctx.path("subtitles", "timings.json").read_text(encoding="utf-8"))
    shots = json.loads(ctx.path("clips", "shots.json").read_text(encoding="utf-8")).get("shots", [])
    events = plan(scenes, timing, shots, lib, total, ctx.video_id)
    by_rel = {s.rel: s for s in lib}
    voice_lufs = media.loudness(ctx.path("audio", "voice.wav"))["I"] or -16.0
    info["voice_lufs"] = voice_lufs
    gains = {rel: gain_for(by_rel[rel].category, meas[rel], voice_lufs) for rel in {e["rel"] for e in events}}
    for e in events:
        e["gain_db"] = gains[e["rel"]]
    info.update(events=events, gains=gains,
                licenses=[by_rel[r].license_record() for r in sorted(gains)],
                measured={r: meas[r] for r in gains})
    files = {s.rel: s.path for s in lib}
    _render_all(ctx, info, files, total, media.run)
    hits = sum(1 for e in events if e["kind"] == "hit")
    ctx.log(f"   🔊 Үн эффекттери: {hits} эффект (паузада), {len(events) - hits} фон; китепкана {len(lib)} "
            f"(четке кагылды {len(rejected)})")
    _save(ctx, info)
    return info


def _render_all(ctx, info: dict, files: dict[str, Path], total: float, run) -> None:
    ev = info["events"]
    gains = info["gains"]
    voice = info.get("voice_lufs")
    for kind, name in (("bed", "sfx_bed.wav"), ("hit", "sfx_hits.wav")):
        part = [e for e in ev if e["kind"] == kind]
        out = render(part, files, gains, total, ctx.path("audio", name), run)
        info[f"{kind}_file"] = str(out) if out else None
        if out and voice is not None:
            info[f"{kind}_trim_db"] = trim_track(out, voice - TRACK_REL_LU[kind], run)


def trim_track(path: Path, target_lufs: float, run=None) -> float:
    """Даяр эффект трегинин ЧЫНЫГЫ катуулугун (LUFS) өлчөп, максатка тууралайт (−20…+6 dB).

    Себеби (run #44576373873): кыска эффекттин бир бөлүгү гана колдонулат (паузага чейин), ал эми
    файлдын орточо деңгээли тынч «куйругун» да эсептейт — трек болжолдон ~5 LU катуу чыккан.
    """
    from . import media

    lufs = media.loudness(path)["I"]
    if lufs is None or lufs < -69:
        return 0.0
    delta = round(max(-20.0, min(6.0, target_lufs - lufs)), 2)
    if abs(delta) < 0.1:
        return 0.0
    tmp = path.with_name(path.stem + "_trim.wav")
    args = ["ffmpeg", "-y", "-v", "error", "-i", str(path), "-af", f"volume={delta:.2f}dB",
            "-ar", "48000", "-ac", "2", str(tmp)]
    if run:
        run(args, "үн эффекттеринин деңгээли")
    else:
        subprocess.run(args, check=True, capture_output=True, timeout=600)
    tmp.replace(path)
    return delta


def _save(ctx, info: dict) -> None:
    ctx.path("music", "sfx.json").write_text(json.dumps(info, ensure_ascii=False, indent=1), encoding="utf-8")


def tracks_for_mix(ctx, total: float) -> tuple[Path | None, Path | None]:
    """mix() үчүн: (фон, сокку) WAV'дары. Жаңы runner'де sfx.json боюнча кайра түзүлөт."""
    p = ctx.path("music", "sfx.json")
    if not p.exists():
        return None, None
    info = json.loads(p.read_text(encoding="utf-8"))
    if not info.get("events"):
        return None, None
    bed, hits = ctx.path("audio", "sfx_bed.wav"), ctx.path("audio", "sfx_hits.wav")
    need_bed = any(e["kind"] == "bed" for e in info["events"])
    need_hit = any(e["kind"] == "hit" for e in info["events"])
    if (need_bed and not bed.exists()) or (need_hit and not hits.exists()):
        from . import media
        from .errors import StageError

        lib, _ = load_library(*library_roots(ctx.cfg))
        files = {s.rel: s.path for s in lib}
        sha = {s.rel: s.sha256 for s in lib}
        for lic in info["licenses"]:
            if sha.get(lic["file"]) != lic["sha256"]:
                raise StageError(f"Үн эффекти «{lic['file']}» китепканада жок же өзгөргөн — "
                                 f"7-этапты кайра иштетиңиз (rerun_from: s7_music)")
        _render_all(ctx, info, files, total, media.run)
    return (bed if need_bed else None), (hits if need_hit else None)
