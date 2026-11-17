"""Расмий Meta Instagram Graph API клиенти (Instagram professional аккаунт).

Керек: POULTRY_IG_ACCESS_TOKEN, POULTRY_IG_USER_ID (GitHub Secrets). Эндпоинттердин аттары жана версиясы
Meta документациясына негизделген, бирок бул код ЧЫНЫГЫ API менен али текшерилген эмес —
тесттер жасалма transport менен өтөт. Биринчи жарыялоо dry-run → кол менен бекитүү менен болот.
Чектер: Reels/Stories/посттор үчүн медиа ачык URL же resumable upload аркылуу берилет; DM'ге жооп
адатта кардар жазгандан кийин 24 саат ичинде гана уруксат.
"""
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

from . import log

GRAPH = "https://graph.facebook.com"
RUPLOAD = "https://rupload.facebook.com/ig-api-upload"
INSIGHT_METRICS = ("views", "reach", "saved", "shares", "likes", "comments", "total_interactions", "follows")


class IGError(RuntimeError):
    pass


def default_transport(method, url, params=None, data=None, headers=None):
    params = dict(params or {})
    body = data
    if method == "GET" and params:
        url += "?" + urllib.parse.urlencode(params)
    elif params:
        body = urllib.parse.urlencode(params).encode()
    req = urllib.request.Request(url, data=body, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            raw = r.read()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:300]
        raise IGError(f"HTTP {e.code}: {detail}") from None


class InstagramClient:
    def __init__(self, token=None, user_id=None, version="v23.0", transport=default_transport, sleep=time.sleep):
        self.token = token or os.environ.get("POULTRY_IG_ACCESS_TOKEN")
        self.user_id = user_id or os.environ.get("POULTRY_IG_USER_ID")
        if not self.token or not self.user_id:
            raise IGError("POULTRY_IG_ACCESS_TOKEN / POULTRY_IG_USER_ID коюлган эмес")
        self.v, self.tx, self.sleep = version, transport, sleep
        self.log = log.get()

    def _call(self, method, path, params=None):
        params = {**(params or {}), "access_token": self.token}
        try:
            return self.tx(method, f"{GRAPH}/{self.v}/{path}", params)
        except IGError as e:
            self.log.error("IG %s %s: %s", method, path, str(e).replace(self.token, "***"))
            raise

    # ---------- жарыялоо ----------
    def _wait(self, container, tries=40, delay=5):
        for _ in range(tries):
            st = self._call("GET", container, {"fields": "status_code,status"}).get("status_code")
            if st == "FINISHED":
                return
            if st in ("ERROR", "EXPIRED"):
                raise IGError(f"Container {container}: {st}")
            self.sleep(delay)
        raise IGError(f"Container {container}: күтүү убактысы бүттү")

    def _publish(self, container):
        self._wait(container)
        out = self._call("POST", f"{self.user_id}/media_publish", {"creation_id": container})
        self.log.info("Жарыяланды: media_id=%s", out.get("id"))
        return out["id"]

    def publish_reel(self, caption, video_url=None, video_path=None, share_to_feed=True):
        if bool(video_url) == bool(video_path):
            raise IGError("video_url же video_path — экөөнүн бирин гана бер")
        params = {"media_type": "REELS", "caption": caption, "share_to_feed": str(share_to_feed).lower()}
        if video_url:
            params["video_url"] = video_url
        else:
            params["upload_type"] = "resumable"
        cid = self._call("POST", f"{self.user_id}/media", params)["id"]
        if video_path:
            size = os.path.getsize(video_path)
            with open(video_path, "rb") as f:
                self.tx("POST", f"{RUPLOAD}/{self.v}/{cid}", None, f.read(),
                        {"Authorization": f"OAuth {self.token}", "offset": "0", "file_size": str(size)})
        return self._publish(cid)

    def publish_photo(self, image_url, caption):
        cid = self._call("POST", f"{self.user_id}/media", {"image_url": image_url, "caption": caption})["id"]
        return self._publish(cid)

    def publish_carousel(self, image_urls, caption):
        if not 2 <= len(image_urls) <= 10:
            raise IGError("Карусель: 2–10 сүрөт")
        kids = [self._call("POST", f"{self.user_id}/media", {"image_url": u, "is_carousel_item": "true"})["id"]
                for u in image_urls]
        cid = self._call("POST", f"{self.user_id}/media",
                         {"media_type": "CAROUSEL", "children": ",".join(kids), "caption": caption})["id"]
        return self._publish(cid)

    def publish_story(self, image_url=None, video_url=None):
        p = {"media_type": "STORIES"}
        p.update({"image_url": image_url} if image_url else {"video_url": video_url})
        return self._publish(self._call("POST", f"{self.user_id}/media", p)["id"])

    # ---------- комментарий ----------
    def list_comments(self, media_id, limit=50):
        return self._call("GET", f"{media_id}/comments",
                          {"fields": "id,text,username,timestamp,hidden", "limit": limit}).get("data", [])

    def reply_comment(self, comment_id, message):
        return self._call("POST", f"{comment_id}/replies", {"message": message})

    def hide_comment(self, comment_id, hide=True):
        return self._call("POST", comment_id, {"hide": str(hide).lower()})

    # ---------- Direct ----------
    def list_conversations(self, limit=20):
        return self._call("GET", f"{self.user_id}/conversations",
                          {"platform": "instagram", "fields": "id,updated_time,messages.limit(5){message,from,created_time}",
                           "limit": limit}).get("data", [])

    def send_dm(self, recipient_id, text):
        """Кардар жазгандан кийинки уруксат берилген терезеде гана иштейт."""
        params = {"recipient": json.dumps({"id": recipient_id}), "message": json.dumps({"text": text})}
        return self._call("POST", f"{self.user_id}/messages", params)

    # ---------- статистика ----------
    def recent_media(self, limit=30):
        return self._call("GET", f"{self.user_id}/media", {
            "fields": "id,caption,media_type,media_product_type,permalink,timestamp,like_count,comments_count",
            "limit": limit}).get("data", [])

    def media_insights(self, media_id, metrics=INSIGHT_METRICS):
        """Бир метрика колдоого алынбаса калгандарын кайтарат (медиа түрүнө жараша айырмалуу)."""
        out = {}
        for m in metrics:
            try:
                data = self._call("GET", f"{media_id}/insights", {"metric": m}).get("data", [])
                if data:
                    out[m] = data[0]["values"][0]["value"]
            except IGError:
                continue
        return out
