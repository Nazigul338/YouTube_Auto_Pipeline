"""ДАЯР видеолорду визуалдык салыштыруу (оригиналдуулук — №1). Видеолор ӨЗГӨРБӨЙТ, окулат гана.

Даяр MP4'тен «визуалдык из» (fingerprint) алынат:
  frames      — ар SAMPLE_SEC сайын кадрдын dHash'ы (64 бит) → кайталанган/өтө окшош кадрлар
  palette     — HSV гистограммасы (түс дүйнөсү)
  composition — 3×3 тор боюнча контур (edge) энергиясы жана жарыгы (кадр композициясы)
  rhythm      — кесүүлөрдүн убактысы (FFmpeg scene detection) → кадр узундугунун бөлүштүрүлүшү
  structure   — видео 10 бөлүккө: ар бөлүктүн кесүү жыштыгы жана жарыгы (монтаждын түзүлүшү)
  transitions — plan.json'дагы өтүүлөрдүн бөлүштүрүлүшү (болсо)

`compare(a, b)` → ар өлчөмдүн аралыгы + `too_similar` (кадрлардын ≥15% дээрлик бирдей, же 6 өлчөмдүн ≥4 окшош
жана алардын ≥2си монтаж өлчөмү: ыргак/өтүүлөр/түзүлүш). Чыныгы калибровка: run #44737672862 —
Video_003 ↔ Video_001 (экөө тең эски бир шаблон): окшош кадр 4%, окшош: композиция, жарык, ыргак, өтүүлөр → ӨТӨ ОКШОШ.

CLI (GitHub Actions `🎞 Визуалдык из`):  VIDEOS="Video_001:Video_001_cinematic.mp4,…" python -m pipeline.visual_compare
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

SAMPLE_SEC = 2.0
W, H = 64, 36
SCENE_THR = 0.28
DUP_HAMMING = 6
DUP_LIMIT = 0.15
SIMILAR = {"palette": 0.10, "composition": 0.05, "brightness": 0.06, "rhythm": 0.12, "structure": 0.25,
           "transitions": 0.25}
MAX_SIMILAR = 4
MONTAGE = ("rhythm", "transitions", "structure")


# ---------------------------------------------------------------- өлчөө

def _frames(video: Path) -> np.ndarray:
    r = subprocess.run(["ffmpeg", "-v", "error", "-i", str(video), "-an", "-vf",
                        f"fps=1/{SAMPLE_SEC},scale={W}:{H},format=rgb24", "-f", "rawvideo", "-"],
                       capture_output=True, timeout=3600)
    n = len(r.stdout) // (W * H * 3)
    return np.frombuffer(r.stdout[: n * W * H * 3], np.uint8).reshape(n, H, W, 3).astype(np.float32) / 255.0


def _cuts(video: Path) -> list[float]:
    r = subprocess.run(["ffmpeg", "-hide_banner", "-v", "info", "-i", str(video), "-an", "-vf",
                        f"scale=160:-2,select='gt(scene,{SCENE_THR})',showinfo", "-f", "null", "-"],
                       capture_output=True, text=True, timeout=3600)
    import re

    return [float(x) for x in re.findall(r"pts_time:([\d.]+)", r.stderr)]


def dhash(gray: np.ndarray) -> int:
    """9×8 кичирейтилген боз кадрдан 64-бит dHash."""
    h, w = gray.shape
    ys = (np.arange(8) * h / 8).astype(int)
    xs = (np.arange(9) * w / 9).astype(int)
    small = gray[np.ix_(ys, xs)]
    bits = (small[:, 1:] > small[:, :-1]).flatten()
    return int("".join("1" if b else "0" for b in bits), 2)


def _hsv_hist(rgb: np.ndarray) -> np.ndarray:
    mx, mn = rgb.max(-1), rgb.min(-1)
    v, d = mx, mx - mn
    s = np.where(mx > 0, d / np.maximum(mx, 1e-6), 0)
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    hue = np.where(d == 0, 0, np.where(mx == r, ((g - b) / np.maximum(d, 1e-6)) % 6,
                                       np.where(mx == g, (b - r) / np.maximum(d, 1e-6) + 2,
                                                (r - g) / np.maximum(d, 1e-6) + 4))) / 6
    hh = np.histogram(hue, 12, (0, 1), weights=s)[0]
    sh = np.histogram(s, 4, (0, 1))[0]
    vh = np.histogram(v, 6, (0, 1))[0]
    vec = np.concatenate([hh / max(hh.sum(), 1e-6), sh / max(sh.sum(), 1e-6), vh / max(vh.sum(), 1e-6)])
    return vec / 3


def _grid(x: np.ndarray) -> np.ndarray:
    h, w = x.shape
    return np.array([x[i * h // 3:(i + 1) * h // 3, j * w // 3:(j + 1) * w // 3].mean()
                     for i in range(3) for j in range(3)])


def fingerprint(video: Path, plan: dict | None = None) -> dict:
    fr = _frames(video)
    if not len(fr):
        raise ValueError("видеодон кадр алынган жок")
    gray = fr.mean(-1)
    hashes = [f"{dhash(g):016x}" for g in gray]
    pal = np.mean([_hsv_hist(f) for f in fr], 0)
    edges = []
    for g in gray:
        gx, gy = np.abs(np.diff(g, axis=1))[:-1, :], np.abs(np.diff(g, axis=0))[:, :-1]
        e = _grid(gx + gy)
        edges.append(e / max(e.sum(), 1e-6))
    comp = np.mean(edges, 0)
    bright = np.mean([_grid(g) for g in gray], 0)
    total = len(fr) * SAMPLE_SEC
    cuts = _cuts(video)
    shots = np.diff([0.0] + cuts + [total]) if cuts else np.array([total])
    shots = shots[shots > 0.3]
    parts = 10
    struct = []
    for k in range(parts):
        a, b = total * k / parts, total * (k + 1) / parts
        n_c = sum(1 for c in cuts if a <= c < b)
        seg = gray[int(a / SAMPLE_SEC):max(int(a / SAMPLE_SEC) + 1, int(b / SAMPLE_SEC))]
        struct.append([n_c / max(b - a, 1e-6) * 60, float(seg.mean()) if len(seg) else 0.0])
    trans = {}
    if plan:
        for p in plan.get("shots", []):
            t = (p.get("transition_out") or {}).get("type")
            if t and t != "cut":
                trans[t] = trans.get(t, 0) + 1
        s = sum(trans.values()) or 1
        trans = {k: round(v / s, 3) for k, v in trans.items()}
    return {"version": 1, "duration": round(total, 1), "frames": hashes,
            "palette": [round(float(x), 4) for x in pal], "composition": [round(float(x), 4) for x in comp],
            "brightness": [round(float(x), 4) for x in bright],
            "rhythm": {"cuts_per_min": round(len(cuts) / max(total, 1) * 60, 2),
                       "mean": round(float(shots.mean()), 2), "std": round(float(shots.std()), 2),
                       "p10": round(float(np.percentile(shots, 10)), 2), "p90": round(float(np.percentile(shots, 90)), 2)},
            "structure": [[round(a, 2), round(b, 3)] for a, b in struct], "transitions": trans}


# ---------------------------------------------------------------- салыштыруу

def _ham(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


def compare(a: dict, b: dict) -> dict:
    ha = [int(x, 16) for x in a["frames"]]
    hb = [int(x, 16) for x in b["frames"]]
    dup = sum(1 for x in ha if hb and min(_ham(x, y) for y in hb) <= DUP_HAMMING) / max(1, len(ha))
    d = {"palette": float(np.abs(np.array(a["palette"]) - np.array(b["palette"])).sum() / 2),
         "composition": float(np.abs(np.array(a["composition"]) - np.array(b["composition"])).sum() / 2),
         "brightness": float(np.abs(np.array(a["brightness"]) - np.array(b["brightness"])).mean())}
    ra, rb = a["rhythm"], b["rhythm"]
    d["rhythm"] = float(min(1.0, abs(ra["mean"] - rb["mean"]) / max(ra["mean"], rb["mean"], 1e-6) +
                            abs(ra["std"] - rb["std"]) / max(ra["std"] + rb["std"], 1e-6) * 0.5 +
                            abs(ra["p90"] - rb["p90"]) / max(ra["p90"], rb["p90"], 1e-6) * 0.5))
    sa, sb = np.array(a["structure"]), np.array(b["structure"])
    corr = []
    for k in range(2):
        x, y = sa[:, k], sb[:, k]
        if x.std() > 1e-6 and y.std() > 1e-6:
            corr.append(float(np.corrcoef(x, y)[0, 1]))
    d["structure"] = float((1 - (np.mean(corr) if corr else 0.0)) / 2)
    if a.get("transitions") and b.get("transitions"):
        keys = set(a["transitions"]) | set(b["transitions"])
        d["transitions"] = float(sum(abs(a["transitions"].get(k, 0) - b["transitions"].get(k, 0)) for k in keys) / 2)
    similar = [k for k, v in d.items() if v < SIMILAR[k]]
    # композиция/жарык сток видеолордо табигый окшош болот (run #44737672862) — шаблон деп эсептөө үчүн
    # МОНТАЖ өлчөмдөрүнүн (ыргак, өтүүлөр, түзүлүш) кеминде экөө окшош болушу керек
    montage = [k for k in similar if k in MONTAGE]
    too = dup >= DUP_LIMIT or (len(similar) >= MAX_SIMILAR and len(montage) >= 2)
    return {"dup_frames": round(dup, 3), "distances": {k: round(v, 3) for k, v in d.items()},
            "similar": similar, "too_similar": too}


def against_finished(fp: dict, registry: dict, video_id: str) -> dict[str, dict]:
    from .edit_concept import finished_others

    return {vid: compare(fp, v["visual_fp"]) for vid, v in finished_others(registry, video_id).items()
            if v.get("visual_fp")}


# ---------------------------------------------------------------- CLI (Drive'дагы даяр видеолор)

def main() -> int:
    from .drive import DriveClient
    from .storage import DriveStore

    root = os.environ.get("YTA_DRIVE_FOLDER", "YouTube_Auto_TEST")
    items = [x.split(":", 1) for x in os.environ.get("VIDEOS", "").split(",") if ":" in x]
    drive = DriveClient.from_env()
    if drive is None or not items:
        print("❌ GDRIVE_* же VIDEOS жок")
        return 2
    store = DriveStore(drive, root)
    reg = store.load_registry()
    fid = drive.find_path(root, "Final_Videos")
    fps = {}
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        for vid, name in items:
            f = drive.find_file(name, fid) if fid else None
            if not f:
                print(f"❌ {name} табылган жок")
                continue
            src = drive.download_file(f["id"], d / name)
            plan = None
            an = drive.find_path(root, "Projects", vid, "animation")
            pj = drive.find_file("plan.json", an) if an else None
            if pj:
                plan = json.loads(drive.download_file(pj["id"], d / f"{vid}_plan.json").read_text(encoding="utf-8"))
            fps[vid] = fingerprint(src, plan)
            reg.setdefault("videos", {}).setdefault(vid, {})["visual_fp"] = fps[vid]
            r = fps[vid]["rhythm"]
            print(f"✓ {vid}: {len(fps[vid]['frames'])} кадр, {r['cuts_per_min']} кесүү/мүн, кадр {r['mean']}±{r['std']} сек")
            src.unlink()
    store.save_registry(reg)
    vids = list(fps)
    for i in range(len(vids)):
        for j in range(i + 1, len(vids)):
            c = compare(fps[vids[j]], fps[vids[i]])
            print(f"🔎 {vids[j]} ↔ {vids[i]}: окшош кадр {c['dup_frames']:.0%}; аралыктар {c['distances']}; "
                  f"окшош өлчөмдөр {c['similar']} → {'❌ ӨТӨ ОКШОШ' if c['too_similar'] else '✅ айырмаланат'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
