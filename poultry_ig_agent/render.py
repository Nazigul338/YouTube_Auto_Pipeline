"""Карусель слайддарын Pillow менен PNG кылып чыгарат (4:5)."""
import textwrap

from PIL import Image, ImageDraw, ImageFont

from . import config

FONTS = ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
         "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]
PALETTES = [("#2b1d0e", "#f6c453"), ("#1f3a2b", "#f4efe1"), ("#f4efe1", "#3b2a14"), ("#7a3b1d", "#fff4dc")]


def _font(size):
    for f in FONTS:
        try:
            return ImageFont.truetype(f, size)
        except OSError:
            continue
    return ImageFont.load_default()


def render_slide(title, body, idx, total, path):
    w, h = config.SLIDE_SIZE
    bg, fg = PALETTES[idx % len(PALETTES)]
    img = Image.new("RGB", (w, h), bg)
    d = ImageDraw.Draw(img)
    y = 180
    for line in textwrap.wrap(title, 20)[:4]:
        d.text((90, y), line, font=_font(80), fill=fg)
        y += 100
    y += 50
    for line in textwrap.wrap(body, 32)[:12]:
        d.text((90, y), line, font=_font(48), fill=fg)
        y += 66
    d.text((90, h - 110), f"{idx + 1}/{total}", font=_font(36), fill=fg)
    img.save(path)
    return path


def render_story_frame(text, idx, total, path, options=None, sticker=None):
    """9:16 Story кадры (1080x1920). Сурамжылоо/добуш — Instagram стикерин колдонуучу өзү кошот (API чектөөсү)."""
    w, h = 1080, 1920
    bg, fg = PALETTES[idx % len(PALETTES)]
    img = Image.new("RGB", (w, h), bg)
    d = ImageDraw.Draw(img)
    y = 420
    for line in textwrap.wrap(text, 18)[:8]:
        d.text((90, y), line, font=_font(86), fill=fg)
        y += 112
    if options:
        y += 60
        for o in options[:4]:
            d.rounded_rectangle((90, y, w - 90, y + 110), 30, outline=fg, width=4)
            d.text((130, y + 24), o[:32], font=_font(48), fill=fg)
            y += 140
    if sticker:
        d.text((90, h - 220), f"[{sticker} стикерин колдонуңуз]", font=_font(36), fill=fg)
    d.text((90, h - 110), f"{idx + 1}/{total}", font=_font(36), fill=fg)
    img.save(path)
    return path
