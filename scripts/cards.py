"""书封卡片图生成。素材池为空时用它兜底，也用于封面图。

一张卡片 = 渐变底 + 序号 + 书名 + 作者 + 金句
"""
import os

from PIL import Image, ImageDraw, ImageFont

W, H = 1080, 1920
# 合规字体：项目内自带的 Noto Sans SC / Noto Serif SC（Google Fonts，SIL OFL 1.1，
# 允许商用）。原先用的 C:\Windows\Fonts\msyh*.ttc（微软雅黑）商用需另购授权，
# 是短视频字体维权的高发项，2026-11-11 起全部替换。授权凭证见 assets/fonts/README.md。
FONT_DIR = os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "assets", "fonts")
F_BOLD = os.path.join(FONT_DIR, "NotoSansSC_700Bold.ttf")
F_REG = os.path.join(FONT_DIR, "NotoSansSC_400Regular.ttf")
F_SERIF = os.path.join(FONT_DIR, "NotoSerifSC_700Bold.ttf")

THEMES = {
    "ink": ((18, 22, 34), (38, 46, 66), (232, 196, 120)),
    "paper": ((244, 239, 230), (222, 212, 196), (58, 46, 38)),
    "forest": ((16, 38, 34), (32, 66, 56), (196, 226, 168)),
    "plum": ((32, 18, 28), (62, 30, 46), (240, 200, 210)),
    "night": ((12, 16, 40), (26, 38, 80), (168, 206, 255)),
    # 暖白日光：浅底 + 赭铜点缀，用于自省向选题，跟夜色系形成反差
    "dawn": ((250, 244, 232), (234, 216, 190), (146, 74, 38)),
}

_DARK_FG = (255, 255, 255)
_DARK_FG_DIM = (240, 240, 240)
_LIGHT_FG = (40, 34, 30)
_LIGHT_FG_DIM = (86, 74, 64)


def is_light(theme: str) -> bool:
    """底色偏亮时正文要转深色，否则写死的白字会糊在浅底上。

    也供 build.py 判断字幕是否要换成浅底样式。
    """
    bg1 = THEMES.get(theme, THEMES["ink"])[0]
    return (bg1[0] * 299 + bg1[1] * 587 + bg1[2] * 114) / 1000 > 150


def _palette(theme: str):
    bg1, bg2, accent = THEMES.get(theme, THEMES["ink"])
    light = is_light(theme)
    fg = _LIGHT_FG if light else _DARK_FG
    fg_dim = _LIGHT_FG_DIM if light else _DARK_FG_DIM
    # 纹理线：浅底压暗、深底提亮，都保持"纸上压痕"的淡度
    delta = -12 if light else 8
    line = tuple(max(0, min(255, c + delta)) for c in bg1)
    return bg1, bg2, accent, fg, fg_dim, line, light


def _decor(d, line):
    for i in range(0, W, 90):
        d.line([(i, 0), (i - H // 2, H)], fill=line, width=1)


def _moon(d, bg1, bg2):
    """封面/结尾卡的浅色圆形：既像月亮，也像一枚六便士。"""
    r, cx, cy = 170, W - 250, 350
    moon = tuple(max(0, c - 18) for c in bg2)
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=moon)
    d.ellipse([cx - r + 22, cy - r + 22, cx + r - 22, cy + r - 22],
              outline=tuple(max(0, c - 34) for c in bg2), width=3)


def _font(path, size):
    for p in (path, F_BOLD, F_REG):
        try:
            return ImageFont.truetype(p, size)
        except Exception:
            continue
    return ImageFont.load_default()


def _gradient(size, c1, c2, angle=1.0):
    w, h = size
    base = Image.new("RGB", (1, h))
    px = base.load()
    for y in range(h):
        t = y / max(1, h - 1)
        px[0, y] = tuple(int(c1[i] + (c2[i] - c1[i]) * t) for i in range(3))
    return base.resize((w, h), Image.BILINEAR)


def _text_w(draw, s, font):
    b = draw.textbbox((0, 0), s, font=font)
    return b[2] - b[0], b[3] - b[1]


_PUNCT = "，。！？；：、）」》】!?;:%"


def _wrap(draw, text, font, max_w):
    lines, cur = [], ""
    for ch in text:
        if _text_w(draw, cur + ch, font)[0] > max_w and cur:
            if ch in _PUNCT:
                lines.append(cur + ch)
                cur = ""
            else:
                lines.append(cur)
                cur = ch
        else:
            cur += ch
    if cur:
        lines.append(cur)
    return lines


def make_card(book: dict, idx: int, total: int, out_path: str,
              theme: str = "ink", brand: str = ""):
    bg1, bg2, accent, fg, fg_dim, line, light = _palette(theme)
    img = _gradient((W, H), bg1, bg2)
    d = ImageDraw.Draw(img)
    _decor(d, line)

    f_brand = _font(F_REG, 34)
    f_idx = _font(F_BOLD, 150)
    f_name = _font(F_BOLD, 96)
    f_author = _font(F_REG, 40)
    f_quote = _font(F_REG, 46)

    num = "%02d" % idx
    d.text((78, 210), num, font=f_idx, fill=tuple(int(c * 0.55 + 30) for c in accent))

    d.rectangle([80, 400, 96, 430], fill=accent)
    d.text((116, 396), "%d / %d" % (idx, total), font=f_author, fill=accent)

    y = 500
    for ln in _wrap(d, book.get("name", ""), f_name, W - 160)[:3]:
        d.text((80, y), ln, font=f_name, fill=fg)
        y += 118

    author = book.get("author") or ""
    if author:
        d.text((84, y + 10), author, font=f_author, fill=accent)
        y += 90

    quote = book.get("quote") or book.get("line") or ""
    if quote:
        qy = max(y + 120, 1150)
        d.line([(80, qy - 50), (140, qy - 50)], fill=accent, width=4)
        f_q = _font(F_REG, 46)
        for ln in _wrap(d, quote, f_q, W - 200)[:5]:
            d.text((80, qy), ln, font=f_q, fill=fg_dim)
            qy += 74

    if brand:
        d.text((80, H - 150), brand, font=_font(F_REG, 32),
               fill=tuple(int(c * 0.7) for c in accent))

    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    img.save(out_path, quality=92)
    return out_path


def make_quote_card(book: dict, idx: int, total: int, quote: str,
                    out_path: str, theme: str = "ink", brand: str = "",
                    label: str = "金句"):
    """单本书模式的金句卡：序号 + 书名 + 作者 + 大字金句。"""
    bg1, bg2, accent, fg, fg_dim, line, light = _palette(theme)
    img = _gradient((W, H), bg1, bg2)
    d = ImageDraw.Draw(img)
    _decor(d, line)

    f_idx = _font(F_BOLD, 110)
    f_small = _font(F_REG, 36)
    f_name = _font(F_BOLD, 62)
    f_quote = _font(F_BOLD, 58)

    accent_dim = tuple(int(c * 0.55 + 30) for c in accent)
    d.text((78, 180), "%02d" % idx, font=f_idx, fill=accent_dim)
    d.text((84, 320), "%s %d / %d" % (label, idx, total), font=f_small, fill=accent)

    y = 430
    name = (book.get("book") or book.get("name") or "").strip().strip("《》")
    if name:
        for ln in _wrap(d, "《%s》" % name, f_name, W - 160)[:2]:
            d.text((80, y), ln, font=f_name, fill=fg)
            y += 84
    author = book.get("author") or ""
    if author:
        d.text((84, y + 4), author, font=f_small, fill=accent)
        y += 64

    qy = max(y + 70, 720)
    d.line([(80, qy - 44), (150, qy - 44)], fill=accent, width=5)
    qy += 16
    for ln in _wrap(d, quote, f_quote, W - 200)[:7]:
        d.text((80, qy), ln, font=f_quote, fill=fg_dim)
        qy += 96

    if brand:
        d.text((80, H - 150), brand, font=_font(F_REG, 32),
               fill=tuple(int(c * 0.7) for c in accent))

    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    img.save(out_path, quality=92)
    return out_path


def make_insight_card(book: dict, insight: str, out_path: str,
                      theme: str = "ink", brand: str = "",
                      label: str = "读完之后"):
    """立意卡：全片唯一的观点输出，版式比金句卡更重、更静。"""
    bg1, bg2, accent, fg, fg_dim, line, light = _palette(theme)
    img = _gradient((W, H), bg1, bg2)
    d = ImageDraw.Draw(img)
    _decor(d, line)

    f_label = _font(F_REG, 36)
    f_mark = _font(F_BOLD, 210)
    f_text = _font(F_BOLD, 70)
    f_name = _font(F_REG, 38)

    d.text((80, 286), label, font=f_label, fill=accent)
    d.line([(80, 366), (210, 366)], fill=accent, width=5)

    d.text((52, 396), "\u201c", font=f_mark,
           fill=tuple(int(c * 0.42 + 18) for c in accent))

    lines = _wrap(d, insight, f_text, W - 175)[:8]
    total_h = len(lines) * 112
    y = max(660, (H - total_h) // 2 - 40)
    for ln in lines:
        d.text((80, y), ln, font=f_text, fill=fg)
        y += 112

    name = (book.get("book") or "").strip().strip("《》")
    author = book.get("author") or ""
    sign = ("《%s》" % name) if name else ""
    if author:
        sign = (sign + "  " + author).strip()
    if sign:
        d.text((80, y + 66), sign, font=f_name, fill=accent)

    if brand:
        d.text((80, H - 150), brand, font=_font(F_REG, 32),
               fill=tuple(int(c * 0.7) for c in accent))

    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    img.save(out_path, quality=92)
    return out_path


def make_cover(title: str, subtitle: str, out_path: str, theme: str = "ink"):
    bg1, bg2, accent, fg, fg_dim, line, light = _palette(theme)
    img = _gradient((W, H), bg1, bg2)
    d = ImageDraw.Draw(img)
    _decor(d, line)
    # 圆饰是「月亮 / 六便士」的专属意象，只在 dawn 出现；paper 走纯旧纸留白
    if light and theme == "dawn":
        _moon(d, bg1, bg2)

    f_t = _font(F_BOLD, 118)
    f_s = _font(F_REG, 52)

    lines = _wrap(d, title, f_t, W - 180)
    total_h = len(lines) * 150
    y = (H - total_h) // 2 - 60
    for ln in lines:
        d.text((90, y), ln, font=f_t, fill=fg)
        y += 150
    if subtitle:
        d.text((92, y + 40), subtitle, font=f_s, fill=accent)
    d.rectangle([90, y + 140, 220, y + 148], fill=accent)

    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    img.save(out_path, quality=92)
    return out_path
