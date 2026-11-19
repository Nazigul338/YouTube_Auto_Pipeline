"""Жарыялоо дарбазасы: бекитүү → dry-run → (сыноодон кийин) автопилот."""
import json
import os

from . import config, log, settings


def _state_path():
    return os.path.join(config.OUT_DIR, "state.json")


def load_state():
    try:
        with open(_state_path(), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {"approved_publishes": 0, "published": []}


def save_state(st):
    os.makedirs(config.OUT_DIR, exist_ok=True)
    with open(_state_path(), "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False, indent=2)


def autopilot_allowed(post, cfg=None, state=None):
    """Автоматтык режим ЭКИ шартта гана: (1) жөндөөдө өзүңүз күйгүздүңүз, (2) кол менен бекитилген
    жарыялоолор жетиштүү. Ден соолук постторуна жана lint катасы барларга ЭЧ КАЧАН."""
    cfg = cfg or settings.load_settings()
    st = state or load_state()
    ap = cfg["autopilot"]
    if not ap.get("enabled"):
        return False, "autopilot өчүк (settings.json)"
    if st["approved_publishes"] < ap["required_approved_publishes"]:
        return False, f"Адегенде {ap['required_approved_publishes']} кол менен жарыялоо керек (азыр {st['approved_publishes']})"
    if post.get("needs_vet_review") or post.get("lint_issues"):
        return False, "ден соолук/каталуу пост — адам бекитиши керек"
    return True, "ok"


def publish(post, post_dir, client=None, live=False, media_urls=None, manual_approved=None):
    """post: post.json мазмуну. Кайтарат: {"dry_run":bool,"payload":..., "media_id":...}"""
    L = log.get()
    cfg = settings.load_settings()
    st = load_state()
    approved = post.get("status") == "approved"
    if not approved:
        ok, why = autopilot_allowed(post, cfg, st)
        if not ok:
            raise PermissionError(f"Жарыялоого болбойт: пост бекитилген эмес; {why}")
    if post.get("lint_issues"):
        raise PermissionError(f"lint каталары: {post['lint_issues']}")
    fmt, cap = post["format"], post.get("caption", "") + "\n\n" + " ".join(post.get("hashtags", []))
    media_urls = media_urls or {}
    payload = {"format": fmt, "caption": cap, "post_id": post.get("id")}
    video_path = os.path.join(post_dir, "final.mp4")
    if fmt == "reel":
        payload["video"] = media_urls.get("video") or (video_path if os.path.exists(video_path) else None)
        if not payload["video"]:
            raise PermissionError("Reel видеосу (final.mp4) жок — адегенде видео даярда")
    if not (live and cfg.get("publish_live") and client):
        L.info("DRY-RUN %s", payload["post_id"])
        return {"dry_run": True, "payload": payload}
    if fmt == "reel":
        v = payload["video"]
        mid = client.publish_reel(cap, video_url=v if v.startswith("http") else None,
                                  video_path=None if v.startswith("http") else v)
    elif fmt == "carousel":
        mid = client.publish_carousel(media_urls["images"], cap)
    elif fmt == "story":
        mid = client.publish_story(image_url=media_urls["images"][0])
    else:
        raise PermissionError("белгисиз формат")
    st["published"].append({"post_id": post.get("id"), "media_id": mid, "manual": approved})
    if approved:
        st["approved_publishes"] += 1
    save_state(st)
    return {"dry_run": False, "media_id": mid, "payload": payload}
