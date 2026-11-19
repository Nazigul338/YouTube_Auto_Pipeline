"""Poultry Farm Instagram Agent (Кыргызстан, тоок ферма ниша).

Негизги команда:
  python -m poultry_ig_agent.agent run --topic broiler --type education --format reel --lang ky [--video]
Башкалары: plan | make | list | approve <id> [--vet-reviewed] | reject <id> | publish <id> [--live]
           | report | dm "<текст>" | calc --inputs f.json | check

Жарыялоо ар дайым адам бекитүүсүнөн кийин; автопилот settings.json'до өзүңүз күйгүзгөндө гана жана
кол менен бекитилген жарыялоолор жетиштүү болгондон кийин гана (publisher.autopilot_allowed).
"""
import argparse
import datetime as dt
import hashlib
import json
import os

from . import analytics, calc, config, lint, llm, log, niche as niche_mod, publisher, render, safety, sales, settings, video

PLAN_FILE = "plan.json"
NICHE = niche_mod.get("poultry")


def _path(*p):
    return os.path.join(config.OUT_DIR, *p)


def _slug(s):
    return hashlib.sha1(s.encode("utf-8")).hexdigest()[:8]


def _load_plan():
    with open(_path(PLAN_FILE), encoding="utf-8") as f:
        return json.load(f)


def _posts():
    out = []
    if os.path.isdir(config.OUT_DIR):
        for d in sorted(os.listdir(config.OUT_DIR)):
            p = _path(d, "post.json")
            if os.path.exists(p):
                with open(p, encoding="utf-8") as f:
                    out.append(json.load(f))
    return out


def _existing_hooks():
    return [p.get("hook", "") for p in _posts()]


def pick_topic():
    """Эң аз колдонулган теманы тандайт (айлануу)."""
    used = {}
    for p in _posts():
        used[p.get("topic_key")] = used.get(p.get("topic_key"), 0) + 1
    return min(NICHE.topics, key=lambda k: used.get(k, 0))


def normalize(post):
    """LLM жообун бир түзүмгө келтирет (булак/хэштег/кадр/cta ар кандай формада келиши мүмкүн)."""
    if not isinstance(post, dict):
        raise ValueError("LLM JSON объект кайтарган жок")
    srcs = post.get("sources") or []
    if isinstance(srcs, (str, dict)):
        srcs = [srcs]
    post["sources"] = [({"url": s} if isinstance(s, str) else s) for s in srcs if isinstance(s, (str, dict))]
    tags = post.get("hashtags") or []
    if isinstance(tags, str):
        tags = tags.replace(",", " ").split()
    post["hashtags"] = [t if t.startswith("#") else "#" + t for t in map(str, tags) if t.strip()]
    cta = post.get("cta")
    if isinstance(cta, str):
        post["cta"] = {"type": "comment", "text": cta}
    elif not isinstance(cta, dict):
        post["cta"] = {}
    shots = post.get("shots")
    if isinstance(shots, list):
        fixed = []
        for i, s in enumerate(shots, 1):
            if isinstance(s, str):
                s = {"visual": s}
            if isinstance(s, dict):
                s.setdefault("n", i)
                try:
                    s["duration"] = float(s.get("duration", 4))
                except (TypeError, ValueError):
                    s["duration"] = 4.0
                fixed.append(s)
        post["shots"] = fixed
    for k in ("slides", "frames"):
        if k in post and isinstance(post[k], list):
            post[k] = [x if isinstance(x, dict) else {"text": str(x), "title": str(x), "body": ""} for x in post[k]]
    return post


def review(post, course=None, video_cfg=None):
    course = course if course is not None else settings.load_course()
    safety.ensure_disclaimers(post, NICHE)
    return lint.lint_post(post, course, video_cfg) + safety.check(post, NICHE) + sales.check(post, course)


# ---------- идея / план ----------
def cmd_plan(days=7, generate=llm.generate_json):
    topics = "\n".join(f"- {k}: {v['ky']}" for k, v in NICHE.topics.items())
    types = "\n".join(f"- {k}: {v}" for k, v in NICHE.content_types.items())
    rules = "\n".join(f"- {r}" for r in config.RULES)
    prompt = f"""Сен Кыргызстандагы тоок ферма Instagram аккаунтунун контент стратегисин.
Аудитория: кыргыз тилдүү тоок багуучулар, фермерлер, тоок чарбасын баштоону каалагандар.
Стиль: {config.BRAND_VOICE}
Эрежелер:\n{rules}
Темалар:\n{topics}
Контент түрлөрү:\n{types}
Мурунку hook'тор (кайталаба): {_existing_hooks()[-20:]}
{days} күнгө идея түз: темалар жана түрлөр айкалышсын, Reel/Stories/карусель аралаш. Ар идея ky ЖАНА ru үчүн өзүнчө жазылат.
JSON: {{"items":[{{"day":1,"topic_key":"<темадан>","content_type":"<түрдөн>","format":"reel|story|carousel","topic":"...","angle":"..."}}]}}"""
    plan = generate(prompt)
    os.makedirs(config.OUT_DIR, exist_ok=True)
    with open(_path(PLAN_FILE), "w", encoding="utf-8") as f:
        json.dump(plan, f, ensure_ascii=False, indent=2)
    return plan


# ---------- пост ----------
def _post_prompt(item, course):
    lang = item.get("lang", "ky")
    ctype = item.get("content_type") or item.get("pillar", "education")
    tkey = item.get("topic_key", "")
    tinfo = NICHE.topics.get(tkey, {})
    rules = "\n".join(f"- {r}" for r in config.RULES)
    fmt = item["format"]
    health = ""
    if tinfo.get("health") or ctype == "customer_q":
        health = ("\nДЕН СООЛУК ЭРЕЖЕЛЕРИ: дозаны/дарыны/антибиотикти ЖАЗБА; диагноз коюуга аракет кылба; "
                  "жалпы алдын алуу гана; аягында ветеринарга кайрылууну эскерт; \"sources\" ичине ишенимдүү уюмдун "
                  "ТАМЫР доменин гана (мис. https://www.woah.org) бер, так баракчаны/URL жолун ОЙЛОП ТАППА; белгисиз болсо [] бер.")
    sell = ""
    if ctype == "sales":
        sell = (f"\nСАТУУ: курс фактылары (ТЕК ушулар): {sales.brief(course)}. Жок нерсени (баа/дата) эскербе. "
                f"Көрүүчүгө пайдасын чынчыл көрсөт, шашылтпа, кепилдик берби. CTA: Direct'ке «КУРС» деп жазуу же WhatsApp тобуна кошулуу.")
    shapes = {
        "reel": '{"hook":"биринчи 2 секунд, күчтүү","hook_onscreen":"экрандагы кыска жазуу","voiceover":"диктордук текст ~70-90 сөз, 25-35 сек",'
                '"shots":[{"n":1,"duration":3,"source":"real|ai","visual":"кадр сүрөттөмөсү (англисче, Veo үчүн ылайыктуу)","onscreen":"кыска жазуу"}],'
                '"caption":"","hashtags":["#.."],"cta":{"type":"comment|direct","text":"..."},"sources":[]}',
        "story": '{"hook":"","frames":[{"text":"кыска","sticker":"poll|question|none","options":["",""]}],"caption":"","hashtags":[],"cta":{"type":"direct","text":""},"sources":[]}',
        "carousel": '{"hook":"","slides":[{"title":"кыска","body":"1-2 сүйлөм"}],"caption":"","hashtags":["#.."],"cta":{"type":"comment","text":""},"sources":[]}',
    }
    extra = {"reel": "Reels: 5-8 кадр, бардыгы 3-6 сек, жалпы 25-35 сек. Реалдуу ферма көрүнүшү керек кадрларга source=real, жалпы иллюстрацияга source=ai.",
             "carousel": "Каруселде 6-8 слайд.", "story": "Story: 3-5 кадр, акыркысы Direct/WhatsApp чакырыгы."}[fmt]
    return f"""Сен Кыргызстандагы тоок ферма Instagram автору. Тил: {config.LANG_NAMES[lang]} (бардык текст ушул тилде, табигый). {config.BRAND_VOICE}
Эрежелер:\n{rules}
Тема: {tinfo.get(lang, item.get('topic', ''))} | Түрү: {ctype} — {NICHE.content_types.get(ctype, '')}
Идея: {item.get('topic', '')}. Бурч: {item.get('angle', '')}
Формат: {fmt}. {extra}{health}{sell}
Hook биринчи 2 секундда көрүүчүнү токтотсун; кайталанма шаблон болбосун. Аягында комментарий же Direct чакырыгы.
JSON түзүмү: {shapes[fmt]}"""


def make_post(item, generate=llm.generate_json, tries=2, course=None):
    course = course if course is not None else settings.load_course()
    vcfg = settings.load_settings()["video"]
    post, issues = {}, []
    for _ in range(tries):
        prompt = _post_prompt(item, course)
        if issues:
            prompt += f"\nМурунку вариантта ката бар, оңдо: {issues}"
        post = normalize(generate(prompt))
        ctype = item.get("content_type") or item.get("pillar", "education")
        post.update(format=item["format"], topic=item.get("topic", ""), topic_key=item.get("topic_key", ""),
                    content_type=ctype, pillar=ctype, purpose="sales" if ctype == "sales" else "education",
                    lang=item.get("lang", "ky"))
        post["hashtags"] = list(dict.fromkeys(post.get("hashtags", []) + NICHE.base_hashtags[post["lang"]]))[:config.HASHTAGS_MAX]
        issues = review(post, course, vcfg)
        if not issues:
            break
    post["lint_issues"] = issues
    post["status"] = "pending_review" if not issues else "needs_fix"
    return post


def make_post_from_text(text, item, generate=llm.generate_json, tries=2, course=None):
    """Колдонуучунун ӨЗ диктор тексти: сөзмө-сөз сакталат. LLM кадр/жазуу/caption гана кошот."""
    import re as _re
    text = text.strip()
    if not text:
        raise ValueError("Текст бош")
    course = course if course is not None else settings.load_course()
    vcfg = settings.load_settings()["video"]
    lang = item.get("lang", "ky")
    words = len(text.split())
    rules = "\n".join(f"- {r}" for r in config.RULES)
    base = (f"Сен Instagram Reels монтажерусуң. Тил: {config.LANG_NAMES[lang]}. Төмөнкү диктор тексти АВТОРДУКУ — "
            f"аны ӨЗГӨРТПӨ, кайталаба, кыскартпа. Ушул текстке гана: 4-8 кадр (ар бири 3-6 сек, жалпы ≈ {max(15, round(words / 2.3))} сек), "
            f"экрандагы кыска жазуулар, hook_onscreen, caption, 3-8 хэштег, cta жаз.\nЭрежелер:\n{rules}\n"
            f"ДИКТОР ТЕКСТИ:\n<<<{text}>>>\n"
            'JSON: {"hook_onscreen":"","shots":[{"n":1,"duration":4,"source":"real|ai","visual":"англисче кадр сүрөттөмөсү","onscreen":""}],'
            '"caption":"","hashtags":[],"cta":{"type":"comment|direct","text":""},"sources":[]}')
    post, issues = {}, []
    for _ in range(tries):
        prompt = base + (f"\nМурунку вариантта ката бар, оңдо: {issues}" if issues else "")
        post = normalize(generate(prompt))
        first = _re.split(r"(?<=[.!?])\s+", text)[0]
        ctype = item.get("content_type", "education")
        post.update(format="reel", voiceover=text, hook=first, own_text=True, lang=lang,
                    topic=item.get("topic", first[:60]), topic_key=item.get("topic_key", ""),
                    content_type=ctype, pillar=ctype, purpose="sales" if ctype == "sales" else "education")
        post["hashtags"] = list(dict.fromkeys(post.get("hashtags", []) + NICHE.base_hashtags[lang]))[:config.HASHTAGS_MAX]
        issues = review(post, course, vcfg)
        if not issues:
            break
    post["lint_issues"] = issues
    post["status"] = "pending_review" if not issues else "needs_fix"
    return post


def save_post(post, today=None):
    today = today or dt.date.today().isoformat()
    pid = f"{today}-{_slug(post.get('topic', '') + post.get('hook', ''))}-{post['format']}-{post.get('lang', 'ky')}"
    d = _path(pid)
    os.makedirs(d, exist_ok=True)
    post["id"] = pid
    if post["format"] == "carousel":
        slides = post.get("slides", [])
        for i, s in enumerate(slides):
            render.render_slide(s.get("title", ""), s.get("body", ""), i, len(slides), os.path.join(d, f"slide_{i + 1:02d}.png"))
    if post["format"] == "story":
        fr = post.get("frames", [])
        for i, f in enumerate(fr):
            render.render_story_frame(f.get("text", ""), i, len(fr), os.path.join(d, f"story_{i + 1:02d}.png"),
                                      f.get("options") if f.get("sticker") in ("poll", "question") else None,
                                      f.get("sticker") if f.get("sticker") not in (None, "none") else None)
    if post.get("voiceover"):   # Akylai/башка кызматка көчүрүү үчүн таза текст
        with open(os.path.join(d, "voiceover.txt"), "w", encoding="utf-8") as f:
            f.write(post["voiceover"].strip() + "\n")
    with open(os.path.join(d, "caption.txt"), "w", encoding="utf-8") as f:
        f.write(post.get("caption", "") + "\n\n" + " ".join(post.get("hashtags", [])))
    with open(os.path.join(d, "post.json"), "w", encoding="utf-8") as f:
        json.dump(post, f, ensure_ascii=False, indent=2)
    return pid


def attach_video(pid, veo=None, tts=None, allow_ai_fallback=False, voice_file=None, stock=None):
    d = _path(pid)
    with open(os.path.join(d, "post.json"), encoding="utf-8") as f:
        post = json.load(f)
    tts = tts or video.tts_from_settings(voice_file=voice_file)
    post["ai_voice"] = settings.load_settings()["voice"].get("disclose_ai_voice", True)
    res = video.build(post, d, veo or video.VeoProvider(), tts,
                      os.path.join(os.path.dirname(__file__), "assets"), allow_ai_fallback, NICHE, stock=stock)
    if res["status"] == "ready":
        post["shots"] = res["shots"]
        if res.get("licenses"):
            post["licenses"] = res["licenses"]
        post["lint_issues"] = review(post)          # AI ачыктоосу caption'ко кошулсун
        post["video"] = "final.mp4"
    post["video_status"] = res["status"]
    with open(os.path.join(d, "post.json"), "w", encoding="utf-8") as f:
        json.dump(post, f, ensure_ascii=False, indent=2)
    return res


def run(topic_key=None, content_type="education", fmt="reel", lang="ky", make_video=False, generate=llm.generate_json,
        veo=None, tts=None, allow_ai_fallback=False, own_text=None):
    """START: контент → пост → (видео) → бекитүүгө даяр пакет. own_text берилсе — автордун тексти сөзмө-сөз."""
    if own_text and own_text.strip():
        item = {"topic_key": topic_key or "", "content_type": content_type, "lang": lang}
        if topic_key:
            item["topic"] = NICHE.topics[topic_key]["ky"]
        pid = save_post(make_post_from_text(own_text, item, generate))
        res = {"id": pid, "own_text": True}
        if make_video:
            res["video"] = attach_video(pid, veo, tts, allow_ai_fallback)["status"]
        return res
    topic_key = topic_key or pick_topic()
    item = {"topic_key": topic_key, "content_type": content_type, "format": fmt, "lang": lang,
            "topic": NICHE.topics[topic_key]["ky"], "angle": ""}
    pid = save_post(make_post(item, generate))
    res = {"id": pid}
    if make_video and fmt == "reel":
        res["video"] = attach_video(pid, veo, tts, allow_ai_fallback)["status"]
    return res


def cmd_voice(pid, tts=None):
    """Постун диктор текстин settings'теги үн менен окуп, voice.mp3 кылат (видеосуз угуп текшерүү үчүн)."""
    d = _path(pid)
    with open(os.path.join(d, "post.json"), encoding="utf-8") as f:
        post = json.load(f)
    if not post.get("voiceover"):
        raise ValueError("Бул постто диктор тексти жок")
    tts = tts or video.tts_from_settings()
    wav = os.path.join(d, "voice.wav")
    tts.synth(post["voiceover"], wav)
    mp3 = os.path.join(d, "voice.mp3")
    video._run(["ffmpeg", "-y", "-v", "error", "-i", wav, "-ac", "1", "-b:a", "96k", mp3])
    os.remove(wav)
    return {"mp3": mp3, "seconds": round(video.duration(mp3), 2)}


def cmd_make(n=3, generate=llm.generate_json):
    ids = []
    for item in _load_plan()["items"][:n]:
        for lang in config.LANGS:
            ids.append(save_post(make_post({**item, "lang": lang}, generate)))
    return ids


def set_status(pid, status, vet_reviewed=False):
    p = _path(pid, "post.json")
    with open(p, encoding="utf-8") as f:
        post = json.load(f)
    if status == "approved":
        if post.get("lint_issues"):
            raise SystemExit(f"Бекитүүгө болбойт, адегенде оңдоо керек: {post['lint_issues']}")
        if post.get("needs_vet_review") and not vet_reviewed:
            raise SystemExit("Ден соолук посту: фактыларды ветеринар/ишенимдүү булак менен текшерип, --vet-reviewed менен бекит")
    post["status"] = status
    with open(p, "w", encoding="utf-8") as f:
        json.dump(post, f, ensure_ascii=False, indent=2)


def cmd_list():
    return [(p["id"], p["status"]) for p in _posts()]


def cmd_publish(pid, live=False, media_urls=None, client=None):
    d = _path(pid)
    with open(os.path.join(d, "post.json"), encoding="utf-8") as f:
        post = json.load(f)
    if live and client is None:
        from .instagram import InstagramClient
        client = InstagramClient(version=settings.load_settings()["graph_version"])
    return publisher.publish(post, d, client, live, media_urls)


def cmd_report(client, today=None):
    rows = analytics.count_leads(client, analytics.collect(client))
    st = publisher.load_state()
    by_media = {x["media_id"]: x["post_id"] for x in st["published"]}
    meta = {}
    for p in _posts():
        for mid, pid in by_media.items():
            if pid == p["id"]:
                meta[mid] = {"purpose": p.get("purpose"), "lang": p.get("lang"), "content_type": p.get("content_type")}
    text = analytics.build_report(rows, meta, today)
    os.makedirs(_path("reports"), exist_ok=True)
    out = _path("reports", f"{today or dt.date.today().isoformat()}.md")
    with open(out, "w", encoding="utf-8") as f:
        f.write(text)
    return out


def cmd_check():
    names = ["POULTRY_GEMINI_API_KEY", "POULTRY_IG_ACCESS_TOKEN", "POULTRY_IG_USER_ID", "POULTRY_ELEVENLABS_API_KEY"]
    course = settings.load_course()
    return {**{n: bool(os.environ.get(n)) for n in names}, "course_filled": sales.ready(course),
            "real_footage_files": len(video.list_real_assets(os.path.join(os.path.dirname(__file__), "assets")))}


def main(argv=None):
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--topic", default="", choices=[""] + list(NICHE.topics))
    r.add_argument("--type", default="education", choices=list(NICHE.content_types))
    r.add_argument("--format", default="reel", choices=["reel", "story", "carousel"])
    r.add_argument("--lang", default=settings.load_settings()["default_lang"], choices=list(config.LANGS))
    r.add_argument("--video", action="store_true")
    r.add_argument("--allow-ai-fallback", action="store_true")
    r.add_argument("--own-text-file", default=None, help="өз диктор текстиңиз (сөзмө-сөз окулат)")
    sp = sub.add_parser("plan"); sp.add_argument("--days", type=int, default=7)
    sm = sub.add_parser("make"); sm.add_argument("--n", type=int, default=3)
    sub.add_parser("list"); sub.add_parser("check"); sub.add_parser("report")
    ap_ = sub.add_parser("approve"); ap_.add_argument("id"); ap_.add_argument("--vet-reviewed", action="store_true")
    sub.add_parser("reject").add_argument("id")
    pb = sub.add_parser("publish"); pb.add_argument("id"); pb.add_argument("--live", action="store_true")
    dm = sub.add_parser("dm"); dm.add_argument("text"); dm.add_argument("--lang", default="ky")
    vo = sub.add_parser("voice"); vo.add_argument("id")
    vd = sub.add_parser("video"); vd.add_argument("id"); vd.add_argument("--voice-file", default=None)
    vd.add_argument("--allow-ai-fallback", action="store_true")
    vd.add_argument("--stock", action="store_true", help="өз видеосу жок кадрларды Pexels'тен толуктоо")
    c = sub.add_parser("calc"); c.add_argument("--inputs", required=True); c.add_argument("--lang", default="ky")
    a = ap.parse_args(argv)
    L = log.get()
    try:
        if a.cmd == "run":
            own = open(a.own_text_file, encoding="utf-8").read() if a.own_text_file else None
            print(json.dumps(run(a.topic or None, a.type, a.format, a.lang, a.video, allow_ai_fallback=a.allow_ai_fallback,
                                 own_text=own), ensure_ascii=False))
        elif a.cmd == "plan":
            print(json.dumps(cmd_plan(a.days), ensure_ascii=False, indent=2))
        elif a.cmd == "make":
            print("\n".join(cmd_make(a.n)))
        elif a.cmd == "list":
            for pid, st in cmd_list():
                print(f"{st:15} {pid}")
        elif a.cmd == "check":
            print(json.dumps(cmd_check(), indent=2))
        elif a.cmd == "approve":
            set_status(a.id, "approved", a.vet_reviewed); print("OK")
        elif a.cmd == "reject":
            set_status(a.id, "rejected"); print("OK")
        elif a.cmd == "publish":
            print(json.dumps(cmd_publish(a.id, a.live), ensure_ascii=False, indent=2))
        elif a.cmd == "report":
            from .instagram import InstagramClient
            print(cmd_report(InstagramClient(version=settings.load_settings()["graph_version"])))
        elif a.cmd == "dm":
            print(json.dumps(sales.draft_dm_reply(a.text, settings.load_course(), a.lang, llm.generate_json if os.environ.get("POULTRY_GEMINI_API_KEY") else None), ensure_ascii=False, indent=2))
        elif a.cmd == "voice":
            print(json.dumps(cmd_voice(a.id), ensure_ascii=False))
        elif a.cmd == "video":
            from .pexels import PexelsStock
            st = PexelsStock() if a.stock else None
            print(json.dumps(attach_video(a.id, allow_ai_fallback=a.allow_ai_fallback, voice_file=a.voice_file, stock=st)["status"]))
        elif a.cmd == "calc":
            cur = settings.load_course().get("currency") or ""
            cp = calc.to_post(calc.load(a.inputs), a.lang, cur)
            cp["lint_issues"] = review(cp)
            cp["status"] = "pending_review" if not cp["lint_issues"] else "needs_fix"
            print(save_post(cp))
    except Exception as e:
        L.error("%s командасы ишке ашкан жок: %s", a.cmd, e, exc_info=True)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
