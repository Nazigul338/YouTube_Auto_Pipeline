"""Smart Video Memory: колдонулган Pixabay клиптеринин туруктуу базасы.

Максат: 100–500+ видеодо бир клип кайра-кайра колдонулбасын.

Сакталышы (Google Drive, `YouTube_Auto/Projects/`):
    _clip_memory.json      ← негизги база (машина үчүн, кичирейтилген JSON)
    Clips/clip_memory.csv  ← ошол эле маалымат, телефондон Sheets/Excel менен окууга ыңгайлуу

Бир клип = бир жазуу. Жазуунун `uses` тизмеси: ким (видео №), качан, кайсы тема, кайсы издөө
сөзү менен колдонгон. Клип кайра колдонулса (акыркы чара) — `uses`'ка кошулат.

Тесттик режим (`YouTube_Auto_TEST/`) өзүнүн базасын колдонот: чыныгы видеолорду булгабайт.
Видео кайра иштетилсе (`release`) анын мурунку жазуулары бошотулат — өзүн өзү бөгөттөбөйт.
"""

from __future__ import annotations

import csv
import io
import re
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Iterable

MEMORY_FILE = "_clip_memory.json"
CSV_NAME = "clip_memory.csv"
CSV_COLUMNS = ["pixabay_id", "source", "kind", "page_url", "video", "date", "topic", "theme",
               "query", "status"]


def video_num(video_id: str) -> int:
    m = re.search(r"(\d+)$", video_id or "")
    return int(m.group(1)) if m else 0


def today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def short_id(clip_id: str) -> str:
    """'pixabay:123' → '123' (CSV үчүн)."""
    return clip_id.split(":", 1)[-1]


class ClipMemory:
    def __init__(self, data: dict | None = None):
        data = data or {}
        self.clips: dict[str, dict[str, Any]] = dict(data.get("clips", {}))

    # ------------------------------------------------------------ I/O
    def to_json(self) -> dict:
        return {"version": 1, "updated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "clips": self.clips}

    @classmethod
    def load(cls, store: Any, registry: dict | None = None) -> "ClipMemory":
        raw = store.load_clip_memory() if store is not None and hasattr(store, "load_clip_memory") \
            else None
        mem = cls(raw)
        if registry:
            mem.import_registry(registry)
        return mem

    def save(self, store: Any, csv_path=None) -> None:
        """Базаны Drive'га (JSON) жана CSV көчүрмөсүн Clips/ папкасына жазат."""
        if store is None or not hasattr(store, "save_clip_memory"):
            return
        store.save_clip_memory(self.to_json())
        if csv_path is not None:
            from pathlib import Path

            p = Path(csv_path)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(self.to_csv(), encoding="utf-8")
            store.publish("Clips", p, CSV_NAME)

    # ------------------------------------------------------------ суроолор
    def used_by_others(self, video_id: str) -> set[str]:
        """Башка видеолордо колдонулган клиптердин ID'лери."""
        return {cid for cid, r in self.clips.items()
                if any(u.get("video") != video_id for u in r.get("uses", []))}

    def last_use_num(self, clip_id: str, exclude_video: str | None = None) -> int:
        r = self.clips.get(clip_id)
        nums = [video_num(u.get("video", "")) for u in (r or {}).get("uses", [])
                if u.get("video") != exclude_video]
        return max(nums, default=-1)

    def clips_of(self, video_id: str) -> set[str]:
        return {cid for cid, r in self.clips.items()
                if any(u.get("video") == video_id for u in r.get("uses", []))}

    def top_queries(self, n: int = 40) -> list[str]:
        """Эң көп колдонулган издөө сөздөрү — жаңы видеодо алардан качуу үчүн."""
        c = Counter(u.get("query", "").lower() for r in self.clips.values()
                    for u in r.get("uses", []) if u.get("query"))
        return [q for q, _ in c.most_common(n)]

    def stats(self) -> dict:
        videos = {u.get("video") for r in self.clips.values() for u in r.get("uses", [])}
        return {"clips": len(self.clips), "videos": len(videos),
                "reused_clips": sum(1 for r in self.clips.values() if len(r.get("uses", [])) > 1)}

    # ------------------------------------------------------------ жазуу
    def release(self, video_id: str) -> int:
        """Видеонун мурунку жазууларын алат (кайра иштетүү/rerun үчүн). Саны кайтарылат."""
        n = 0
        for cid in list(self.clips):
            uses = self.clips[cid].get("uses", [])
            keep = [u for u in uses if u.get("video") != video_id]
            if len(keep) != len(uses):
                n += 1
                if keep:
                    self.clips[cid]["uses"] = keep
                else:
                    del self.clips[cid]
        return n

    def reserve(self, video_id: str, topic: str, shots: Iterable[dict],
                date: str | None = None) -> int:
        """Видеонун клиптерин базага жазат (мурунку жазууларын алмаштырат)."""
        self.release(video_id)
        n = 0
        for s in shots:
            cid = s["asset"]
            rec = self.clips.setdefault(cid, {
                "id": cid, "source": s.get("source", "pixabay"), "kind": s.get("kind", "video"),
                "url": s.get("page_url") or s.get("url", ""), "uses": []})
            if not rec.get("url"):
                rec["url"] = s.get("page_url") or ""
            rec["uses"].append({"video": video_id, "date": date or today(), "topic": topic,
                                "theme": s.get("theme", ""), "query": s.get("query", ""),
                                "scene": s.get("scene"), "status": "reserved",
                                "reused": bool(s.get("reused"))})
            n += 1
        return n

    def mark_published(self, video_id: str) -> int:
        n = 0
        for r in self.clips.values():
            for u in r.get("uses", []):
                if u.get("video") == video_id and u.get("status") != "published":
                    u["status"] = "published"
                    n += 1
        return n

    def import_registry(self, registry: dict) -> int:
        """Эски реестрдеги `clip_ids`'ти (Smart Memory'ге чейинки видеолор) базага көчүрөт."""
        n = 0
        for vid, v in registry.get("videos", {}).items():
            for cid in v.get("clip_ids", []):
                rec = self.clips.get(cid)
                if rec and any(u.get("video") == vid for u in rec.get("uses", [])):
                    continue
                rec = self.clips.setdefault(cid, {"id": cid, "source": cid.split(":")[0].split("-")[0],
                                                  "kind": "image" if "-img" in cid else "video",
                                                  "url": "", "uses": []})
                rec["uses"].append({"video": vid, "date": (v.get("created") or "")[:10],
                                    "topic": v.get("topic", ""), "theme": "", "query": "",
                                    "scene": None, "status": "imported", "reused": False})
                n += 1
        return n

    # ------------------------------------------------------------ CSV
    def to_csv(self) -> str:
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(CSV_COLUMNS)
        rows = []
        for cid, r in self.clips.items():
            for u in r.get("uses", []):
                rows.append([short_id(cid), r.get("source", ""), r.get("kind", ""), r.get("url", ""),
                             u.get("video", ""), u.get("date", ""), u.get("topic", ""),
                             u.get("theme", ""), u.get("query", ""), u.get("status", "")])
        rows.sort(key=lambda x: (video_num(x[4]), x[0]))
        w.writerows(rows)
        return buf.getvalue()
