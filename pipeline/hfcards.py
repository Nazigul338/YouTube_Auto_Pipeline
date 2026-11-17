"""HyperFrames текст-карточкалары (cinematic СЫНАК режими гана).

Ар карточка өзүнчө HyperFrames долбоору катары түзүлүп (`templates/hyperframes/card/`), тунук фон менен
ProRes 4444 MOV'го рендерленет, анан 8-этапта ошол кадрдын үстүнө коюлат (2 кирүүлүү кичине ffmpeg).

Ишенимдүүлүк: HyperFrames жок/иштебей калса же натыйжа текшерүүдөн өтпөсө (узактык, alpha, өлчөм) —
ошол карточка мурункудай ASS карточкасы бойдон калат (видео токтобойт).

Талаптар: Node ≥ 22, `tools/hyperframes` ичинде `npm ci` (hyperframes 0.9.61, gsap, @fontsource/montserrat),
Chrome (workflow'до `hyperframes browser ensure`, же HYPERFRAMES_BROWSER_PATH). Телеметрия өчүк.
"""

from __future__ import annotations

import html
import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Callable

REPO = Path(__file__).resolve().parents[1]
TEMPLATE = REPO / "templates" / "hyperframes" / "card"
FPS = 30
RENDER_TIMEOUT = 300
ASSETS = {
    "gsap.min.js": "gsap/dist/gsap.min.js",
    "montserrat-cyrillic-800-normal.woff2": "@fontsource/montserrat/files/montserrat-cyrillic-800-normal.woff2",
    "montserrat-latin-800-normal.woff2": "@fontsource/montserrat/files/montserrat-latin-800-normal.woff2",
}


def requested() -> bool:
    return os.environ.get("YTA_HYPERFRAMES", "").strip() in ("1", "true", "yes")


def tools_dir() -> Path:
    return Path(os.environ.get("YTA_HF_DIR") or REPO / "tools" / "hyperframes")


def cli() -> Path:
    return tools_dir() / "node_modules" / ".bin" / "hyperframes"


def available() -> tuple[bool, str]:
    """(иштейби, себеби). Node жана CLI орнотулганбы, ресурстар барбы."""
    if shutil.which("node") is None:
        return False, "node табылган жок"
    if not cli().exists():
        return False, f"hyperframes CLI жок ({cli()}) — `npm ci` иштетилген эмес"
    for name, rel in ASSETS.items():
        if not (tools_dir() / "node_modules" / rel).exists():
            return False, f"ресурс жок: {rel}"
    if not (TEMPLATE / "index.html").exists():
        return False, "шаблон жок"
    return True, "ok"


def accent_css(card_color_ass: str) -> str:
    """ASS түсү &H00BBGGRR& → CSS #RRGGBB (концепциянын түсү сакталат)."""
    h = card_color_ass.strip("&H").rstrip("&")[-6:]
    try:
        bb, gg, rr = h[0:2], h[2:4], h[4:6]
        return f"#{rr}{gg}{bb}"
    except Exception:
        return "#f2c14e"


def build_html(text: str, dur: float, accent: str = "#f2c14e") -> str:
    words = [w for w in text.split() if w]
    size = 104 if len(text) <= 18 else 92 if len(text) <= 30 else 80
    lines = 1 if len(text) <= 22 else 2
    tpl = (TEMPLATE / "index.html").read_text(encoding="utf-8")
    words_html = "".join(f'<span class="w">{html.escape(w)}</span>' for w in words)
    return (tpl.replace("__WORDS_HTML__", words_html)
               .replace("__DUR__", f"{dur:.3f}")
               .replace("__SIZE__", str(size))
               .replace("__LINE_OFFSET__", str(int(size * 0.62 * lines + 34)))
               .replace("__STAGGER__", f"{min(0.16, 0.9 / max(1, len(words))):.3f}")
               .replace("__ACCENT__", accent))


def make_project(text: str, dur: float, dest: Path, accent: str = "#f2c14e") -> Path:
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "assets").mkdir(exist_ok=True)
    for name, rel in ASSETS.items():
        shutil.copy2(tools_dir() / "node_modules" / rel, dest / "assets" / name)
    (dest / "index.html").write_text(build_html(text, dur, accent), encoding="utf-8")
    (dest / "hyperframes.json").write_text(json.dumps({"paths": {"assets": "assets"}}), encoding="utf-8")
    return dest


def validate(path: Path, dur: float) -> tuple[bool, str]:
    """Тунук фон (alpha), 1920×1080, узактык ≈ dur (±2 кадр)."""
    try:
        r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-count_packets",
                            "-show_entries", "stream=width,height,pix_fmt,nb_read_packets",
                            "-of", "json", str(path)], capture_output=True, text=True, timeout=60)
        s = json.loads(r.stdout)["streams"][0]
    except Exception as e:
        return False, f"ffprobe: {type(e).__name__}"
    frames = int(s.get("nb_read_packets") or 0)
    want = round(dur * FPS)
    if (s.get("width"), s.get("height")) != (1920, 1080):
        return False, f"өлчөм {s.get('width')}x{s.get('height')}"
    if not (s.get("pix_fmt") or "").startswith(("yuva", "rgba", "gbrap", "argb", "bgra", "ya")):
        return False, f"alpha жок ({s.get('pix_fmt')})"
    if abs(frames - want) > 2:
        return False, f"{frames} кадр, күтүлгөнү {want}"
    return True, f"{frames} кадр, {s.get('pix_fmt')}"


def render_card(text: str, dur: float, workdir: Path, accent: str = "#f2c14e",
                timeout: int = RENDER_TIMEOUT) -> tuple[Path | None, str]:
    """Бир карточканы рендерлейт. (mov_path же None, түшүндүрмө).

    Жол АБСОЛЮТТУК болушу шарт: CLI `cwd=proj` менен иштейт, ошондуктан салыштырмалуу `-o` долбоордун ичине
    эки эсе уяланып жазылат (runner'де 9 карточканын баары ушундан «жок» болуп калган, run #44097307823).
    """
    proj = make_project(text, dur, Path(workdir).resolve(), accent)
    out = proj / "card.mov"
    env = dict(os.environ, HYPERFRAMES_NO_TELEMETRY="1", DO_NOT_TRACK="1", HYPERFRAMES_SKIP_SKILLS="1")
    try:
        r = subprocess.run([str(cli()), "render", "--format", "mov", "--fps", str(FPS), "--quality", "delivery",
                            "--no-browser-gpu", "--quiet", "-o", str(out)],
                           cwd=proj, env=env, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return None, f"{timeout} сек ичинде бүткөн жок"
    if r.returncode != 0 or not out.exists():
        tail = " ".join((r.stderr or r.stdout or "").strip().splitlines()[-3:])[:300]
        return None, f"render катасы (код {r.returncode}): {tail}"
    ok, why = validate(out, dur)
    return (out if ok else None), why


def render_all(cards: list[dict], workdir: Path, accent: str,
               log: Callable[[str], None] = print) -> dict[int, Path]:
    """{карточканын индекси: mov}. Ишке ашпагандары кайтарылбайт (алар ASS бойдон калат)."""
    ok, why = available()
    if not ok:
        log(f"   ⚠️ HyperFrames жеткиликсиз ({why}) — бардык карточкалар ASS бойдон калат")
        return {}
    done: dict[int, Path] = {}
    for k, c in enumerate(cards):
        path, why = render_card(c["text"], c["dur"], workdir / f"card_{k:02d}", accent)
        log(f"   {'✓' if path else '⚠️'} HyperFrames карточка {k + 1}/{len(cards)} «{c['text']}»: {why}"
            + ("" if path else " → ASS карточкасы колдонулат"))
        if path:
            done[k] = path
    return done
