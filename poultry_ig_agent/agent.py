"""Poultry Farm Instagram Agent.

Командалар:
  python agent.py plan  [--days 7]        → апталык контент планы (plan.json)
  python agent.py make  [--n 3]           → планга ылайык постторду (draft) даярдайт
  python agent.py list                    → draft'тардын абалы
  python agent.py approve <id>            → мен бекитем (approved)
  python agent.py reject  <id>            → четке кагуу

Жарыялоо ТОЛУКТАЙ автоматтык эмес: статусу 'approved' болгон пост гана жөнөтүлөт.
"""
import argparse
import datetime as dt
import json
import os
import re

import config
import lint
import llm
import render

PLAN_FILE = "plan.json"


def _path(*p):
    return os.path.join(config.OUT_DIR, *p)


def _slug(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower())[:30].strip("-") or "post"


def _load_plan():
    with open(_path(PLAN_FILE), encoding="utf-8") as f:
        return json.load(f)


def _existing_hooks():
    hooks = []
    if os.path.isdir(config.OUT_DIR):
        for d in os.listdir(config.OUT_DIR):
            p = _path(d, "post.json")
            if os.path.exists(p):
                with open(p, encoding="utf-8") as f:
                    hooks.append(json.load(f).get("hook", ""))
    return hooks


def cmd_plan(days=7, generate=llm.generate_json):
    pillars = "\n".join(f"- {k}: {v}" for k, v in config.PILLARS.items())
    rules = "\n".join(f"- {r}" for r in config.RULES)
    prompt = f"""Сен Instagram үчүн кичи тоок фермасынын контент стратегисин.
Тил: кыргыз. Стиль: {config.BRAND_VOICE}
Эрежелер:\n{rules}
Тирөөчтөр:\n{pillars}
Мурунку hook'тор (кайталаба): {_existing_hooks()[-20:]}
{days} күнгө план түз. Reel жана карусель аралаш, тирөөчтөр айкалышсын.
JSON кайтар: {{"items":[{{"day":1,"pillar":"...","format":"reel|carousel","topic":"...","angle":"..."}}]}}"""
    plan = generate(prompt)
    os.makedirs(config.OUT_DIR, exist_ok=True)
    with open(_path(PLAN_FILE), "w", encoding="utf-8") as f:
        json.dump(plan, f, ensure_ascii=False, indent=2)
    return plan


def _post_prompt(item):
    rules = "\n".join(f"- {r}" for r in config.RULES)
    fmt = item["format"]
    shape = ('{"hook":"","voiceover":"20-30 секундга ~60-80 сөз","caption":"","hashtags":["#..."],"shots":["сүрөттөө идеясы"]}'
             if fmt == "reel" else
             '{"hook":"","slides":[{"title":"кыска","body":"1-2 сүйлөм"}],"caption":"","hashtags":["#..."]}')
    return f"""Сен Instagram тоок фермасынын автору. Тил: кыргыз. {config.BRAND_VOICE}
Эрежелер:\n{rules}
Тирөөч: {item['pillar']} ({config.PILLARS.get(item['pillar'], '')})
Формат: {fmt}. Тема: {item['topic']}. Бурч: {item.get('angle', '')}
Биринчи сап (hook) күчтүү жана оригиналдуу болсун. Аягында комментарийге чакырык.
{'Каруселде 6-8 слайд.' if fmt == 'carousel' else ''}
Бул JSON түзүмүндө кайтар: {shape}"""


def make_post(item, generate=llm.generate_json, tries=2):
    post, issues = {}, []
    for _ in range(tries):
        prompt = _post_prompt(item)
        if issues:
            prompt += f"\nМурунку вариантта ката бар, оңдо: {issues}"
        post = generate(prompt)
        post.update(format=item["format"], pillar=item["pillar"], topic=item["topic"])
        issues = lint.lint_post(post)
        if not issues:
            break
    post["lint_issues"] = issues
    post["status"] = "pending_review" if not issues else "needs_fix"
    return post


def save_post(post, today=None):
    today = today or dt.date.today().isoformat()
    pid = f"{today}-{_slug(post.get('topic', ''))}-{post['format']}"
    d = _path(pid)
    os.makedirs(d, exist_ok=True)
    post["id"] = pid
    if post["format"] == "carousel":
        slides = post.get("slides", [])
        for i, s in enumerate(slides):
            render.render_slide(s.get("title", ""), s.get("body", ""), i, len(slides),
                                os.path.join(d, f"slide_{i + 1:02d}.png"))
    with open(os.path.join(d, "caption.txt"), "w", encoding="utf-8") as f:
        f.write(post.get("caption", "") + "\n\n" + " ".join(post.get("hashtags", [])))
    with open(os.path.join(d, "post.json"), "w", encoding="utf-8") as f:
        json.dump(post, f, ensure_ascii=False, indent=2)
    return pid


def cmd_make(n=3, generate=llm.generate_json):
    plan = _load_plan()
    ids = []
    for item in plan["items"][:n]:
        ids.append(save_post(make_post(item, generate)))
    return ids


def set_status(pid, status):
    p = _path(pid, "post.json")
    with open(p, encoding="utf-8") as f:
        post = json.load(f)
    if status == "approved" and post.get("lint_issues"):
        raise SystemExit(f"Бекитүүгө болбойт, адегенде оңдоо керек: {post['lint_issues']}")
    post["status"] = status
    with open(p, "w", encoding="utf-8") as f:
        json.dump(post, f, ensure_ascii=False, indent=2)


def cmd_list():
    rows = []
    for d in sorted(os.listdir(config.OUT_DIR)) if os.path.isdir(config.OUT_DIR) else []:
        p = _path(d, "post.json")
        if os.path.exists(p):
            with open(p, encoding="utf-8") as f:
                rows.append((d, json.load(f)["status"]))
    return rows


def main(argv=None):
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sp = sub.add_parser("plan"); sp.add_argument("--days", type=int, default=7)
    sm = sub.add_parser("make"); sm.add_argument("--n", type=int, default=3)
    sub.add_parser("list")
    for c in ("approve", "reject"):
        sub.add_parser(c).add_argument("id")
    a = ap.parse_args(argv)
    if a.cmd == "plan":
        print(json.dumps(cmd_plan(a.days), ensure_ascii=False, indent=2))
    elif a.cmd == "make":
        print("\n".join(cmd_make(a.n)))
    elif a.cmd == "list":
        for pid, st in cmd_list():
            print(f"{st:15} {pid}")
    else:
        set_status(a.id, "approved" if a.cmd == "approve" else "rejected")
        print("OK")


if __name__ == "__main__":
    main()
