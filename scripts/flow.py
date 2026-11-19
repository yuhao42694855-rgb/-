# -*- coding: utf-8 -*-
"""flow 模式：连续镜头的 30 秒级短视频（不分页）。

2026-11-14 用户要求：「不是这种分页的」「做顺畅一些」「背景阳光一点」
「最后那个地方能不能改一下」。本脚本独立于 verse.py，不改动日更模板。

与 verse 的区别：
  · 画面：5–6 段自有静物底图用 1.2s 长交叉溶解串成**一条连续底片**，
    不再「一句一张卡硬切」；全程无切卡黑帧、无页码、无说明书式 UI。
  · 背景：暖阳亮调（去色后 S 曲线提亮 + 暖色映射 + 径向阳光 + 中部乳白罩），
    文字改深墨色，告别近纯黑。
  · 字幕：中文逐字渐显 + 每句 \fad 柔和进出；短句单行显示（不再强制两行），
    英文独立轨绝对定位，中英间距恒定。
  · 片头：自绘浅色立体书封烘焙进第一段，随长溶解自然淡出，不单独切卡。
  · 片尾：去掉白底搜索条卡，改为暖光留白 + 问句淡入 + 可截图动作。

2026-11-14 15:46 用户澄清「阳光是画面清新阳光的背景，不是亮度」→
改用 assets/flow/ 下 3 张新生成的自有 AI 清新实拍图（白纱窗光／绿叶／浅木桌面／
大量留白，均值 210–224），保留原色不去色、不做暖褐映射，文字统一深墨无描边。
这 3 张是本轮唯一调用图像生成模型的产物，约 15–30 积分；此前「提亮旧暗图」
的版本已作废，未新生成图片的说法只适用于第一版连续镜头。

合规不变：全自写文案、非原文摘录、自有 AI 图（无真人正脸/真实书封/品牌，
生成图底部 8% 裁掉自带水印）、SIL OFL 字体、程序化 BGM、
片头片尾左下角 28px 白底黑字 AI 标识 + 文件元数据隐式 AIGC 字段；
发布时仍须在投稿页主动声明。

2026-11-16 新增 vivid 主题：同一批自有黑白素材做高饱和渐变映射
（靛紫→玫红→金橙）+ 双色柔光 + 彩色书封 + 亮金大字屏，纯代码绘制、0 积分。
背景：用户嫌暗调「死气沉沉」；色彩量化显示参考片其实更暗更灰（近黑 72–84%），
故这一版是按用户偏好主动提艳，不是复刻参考片。任务 JSON 里 theme="vivid"、
palette="warm"/"cool" 即可切换；noir/sun 两条旧主题完全不受影响。

用法：python scripts/flow.py queue/flow-xxx.json
"""
import glob
import json
import math
import os
import sys

from PIL import (Image, ImageChops, ImageDraw, ImageEnhance, ImageFilter,
                 ImageFont, ImageOps, ImageStat)

import beat_audio  # 2026-11-17 节奏层：分幕配乐 + 句间留白 + 重音落点
import build as buildmod
import compose
import tts as ttsmod
import verse  # 复用 ensure_bgm / 字体路径 / 时间格式
from utils import ass_time, ensure_dir, ffmpeg_exe, media_duration
from utils import run as run_cmd

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, "scripts"))
FONTS = os.path.join(BASE, "assets", "fonts")
BG_DIR = os.path.join(BASE, "assets", "verse")
FLOW_BG_DIR = os.path.join(BASE, "assets", "flow")
W, H = 1080, 1920
FPS = 30

F_SERIF = os.path.join(FONTS, "NotoSerifSC_700Bold.ttf")
F_BOLD = os.path.join(FONTS, "NotoSansSC_700Bold.ttf")
F_REG = os.path.join(FONTS, "NotoSansSC_400Regular.ttf")

INK = (30, 35, 40)          # 深墨
SUB = (74, 91, 107)         # 暖褐灰（英文）
GREY = (90, 85, 80)         # 声明灰
ORANGE = (224, 112, 26)     # 强调橙
PAPER = (252, 248, 238)     # 乳白
THEME = "sun"  # sun=清新阳光版 / noir=对标参考号黑白人像版 / vivid=高饱和艳丽版
PALETTE = "warm"  # vivid 配色：warm=靛紫玫红金橙 / cool=靛蓝青紫
SEARCH_WORD = "算了"  # 片尾自制搜索卡里的词，任务 JSON 可覆盖
PHOTO_SOURCE = False  # True=改用 Pexels 实拍参考图（任务 JSON photo_source）
VIVID_GOLD = (255, 186, 58)
VIVID_CYAN = (80, 220, 255)
VIVID_PINK = (255, 82, 148)


def _font(path, size):
    return ImageFont.truetype(path, size)


def _center(d, y, s, font, fill):
    box = d.textbbox((0, 0), s, font=font)
    d.text(((W - (box[2] - box[0])) // 2 - box[0], y), s, font=font, fill=fill)


def _fit(d, s, path, size, max_w, min_size=36):
    f = _font(path, size)
    while size > min_size:
        box = d.textbbox((0, 0), s, font=f)
        if box[2] - box[0] <= max_w:
            break
        size -= 3
        f = _font(path, size)
    return f


def _cover(im, w=W, h=H):
    sw, sh = im.size
    scale = max(w / sw, h / sh)
    nw, nh = int(sw * scale), int(sh * scale)
    im = im.resize((nw, nh), Image.LANCZOS)
    x, y = (nw - w) // 2, (nh - h) // 2
    return im.crop((x, y, x + w, y + h))


# ---------------------------------------------------------------- 清新阳光底图
def sun_bg(idx: int = 0, variant: int = 0, tail: bool = False) -> Image.Image:
    """清新阳光实拍感底图（assets/flow/，2026-11-14 新生成的自有 AI 图）。

    2026-11-14 15:46 用户澄清：「我说的阳光是画面清新阳光的背景噢，不是亮度」。
    第一版只是把旧的暗调静物图（茶盏/窗棂/背影）用 S 曲线提亮成米金色，
    内容依然是沉的静物，不是清新。这里换成白纱窗光 / 绿叶 / 浅木桌面 /
    大量留白的高调照片，**保留原本的绿与白，不去色、不做暖褐映射**，
    否则清新感立刻变成旧米色。
    """
    fs = sorted(glob.glob(os.path.join(FLOW_BG_DIR, "*.png")))
    src = Image.open(fs[idx % len(fs)]).convert("RGB")
    # 生成图右下角自带「AI生成 / WORKBUDDY」水印，裁掉底部 8% 再构图
    src = src.crop((0, 0, src.width, int(src.height * 0.92)))
    if variant % 2:
        src = ImageOps.mirror(src)
    sw, sh = src.size
    # 每屏换一点构图（幅度 <5%），避免 6 段看起来像同一张静帧
    z = 1.0 + 0.025 * (variant % 3)
    cw, ch = int(sw / z), int(sh / z)
    ox = int((sw - cw) * (0.18 + 0.22 * (variant % 3)))
    oy = int((sh - ch) * (0.10 + 0.24 * ((variant // 3) % 2)))
    im = _cover(src.crop((ox, oy, ox + cw, oy + ch)))
    im = im.filter(ImageFilter.UnsharpMask(radius=1.0, percent=85, threshold=3))

    # 极轻的一层冷白提亮：只加空气感，不改色相、不压暗、不去饱和
    air = Image.new("RGB", (W, H), (0, 0, 0))
    ad = ImageDraw.Draw(air)
    gx = int(W * (0.76 if variant % 2 == 0 else 0.22))
    gy = int(H * (0.22 if not tail else 0.34))
    rad = int(W * (0.78 if not tail else 0.95))
    peak = 34 if not tail else 48
    for rr in range(rad, 0, -18):
        a = int(peak * (1 - rr / float(rad)) ** 2)
        ad.ellipse([gx - rr, gy - rr, gx + rr, gy + rr],
                   fill=(a, a, int(a * 0.92)))
    air = air.filter(ImageFilter.GaussianBlur(96))
    im = ImageChops.screen(im, air)

    # 文字区只加一层很薄的乳白雾（0.10），保证深墨字在亮底上稳，
    # 但不能像上一版 0.30 那样把绿叶和窗光糊成一片米色。
    veil = Image.new("RGB", (W, H), PAPER)
    mask = Image.new("L", (1, H))
    for y in range(H):
        if y < 760:
            v = 0.0
        elif y < 940:
            v = 0.10 * (y - 760) / 180.0
        elif y < 1400:
            v = 0.10
        elif y < 1580:
            v = 0.10 * (1580 - y) / 180.0
        else:
            v = 0.0
        mask.putpixel((0, y), int(v * 255))
    mask = mask.resize((W, H))
    im = Image.composite(veil, im, mask)

    # 绿叶垂枝图（flow_03）的叶子正好压在顶部书名作者上。给 y<430 加一层
    # 渐隐白雾，只把标题区托干净，不破坏下半部的绿叶与光斑。
    # 2026-11-14 16:05 修正：原先只对片尾 tail=True 生效，但正文 6 段循环里
    # 也会轮到这张图（抽帧 04_正文中 发现书名被浓绿叶片压住），
    # 所以改为「只要用到绿叶图就加」，片尾与正文标题区保持一致。
    leafy = (idx % len(fs)) == 2
    if leafy or tail:
        top = Image.new("L", (1, H))
        for y in range(H):
            if y < 330:
                v = 0.62
            elif y < 430:
                v = 0.62 * (430 - y) / 100.0
            else:
                v = 0.0
            top.putpixel((0, y), int(v * 255))
        top = top.resize((W, H))
        im = Image.composite(Image.new("RGB", (W, H), (250, 249, 245)), im, top)
    return im


def sun_book(im, job):
    """片头浅色立体书封：烘焙进第一段底图，随长溶解自然淡出。"""
    cw, ch = 400, 570
    x0, y0 = (W - cw) // 2, 700
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ld = ImageDraw.Draw(layer)
    # 亮底用浅灰褐柔阴影，避免脏黑块压掉清新感
    ld.rectangle([x0 + 22, y0 + 28, x0 + cw + 22, y0 + ch + 28], fill=(120, 110, 96, 55))
    ld.rectangle([x0 + 10, y0 + 14, x0 + cw + 10, y0 + ch + 14], fill=(120, 110, 96, 70))
    im = Image.alpha_composite(im.convert("RGBA"), layer).convert("RGB")
    d = ImageDraw.Draw(im)
    d.rectangle([x0 - 16, y0 + 6, x0, y0 + ch + 6], fill=(126, 96, 66))
    d.rectangle([x0 + cw, y0 + 6, x0 + cw + 10, y0 + ch + 6],
                fill=(226, 208, 180), outline=(168, 140, 106), width=1)
    for k in range(9):
        yy = y0 + 54 + k * 58
        d.line([(x0 + cw + 1, yy), (x0 + cw + 9, yy)], fill=(178, 152, 120), width=1)
    d.rectangle([x0 - 16, y0 + ch, x0 + cw + 10, y0 + ch + 8], fill=(196, 172, 138))
    # 浅米纸面 + 左侧暖光
    paper = Image.new("RGB", (cw, ch))
    pd = ImageDraw.Draw(paper)
    for x in range(cw):
        t = x / float(cw)
        pd.line([(x, 0), (x, ch)],
                fill=(int(250 - 34 * t), int(243 - 40 * t), int(230 - 52 * t)))
    lg = Image.new("RGB", (cw, ch), (0, 0, 0))
    lgd = ImageDraw.Draw(lg)
    for rr in range(360, 0, -12):
        a = int(60 * (1 - rr / 360.0) ** 2)
        lgd.ellipse([-20 - rr, -30 - rr, -20 + rr, -30 + rr],
                    fill=(a, int(a * 0.58), int(a * 0.24)))
    lg = lg.filter(ImageFilter.GaussianBlur(48))
    im.paste(ImageChops.screen(paper, lg), (x0, y0))
    d = ImageDraw.Draw(im)
    d.rectangle([x0, y0, x0 + cw, y0 + ch], outline=(150, 122, 88), width=2)
    d.rectangle([x0 + 24, y0 + 24, x0 + cw - 24, y0 + ch - 24],
                outline=(190, 160, 118), width=1)
    name = job.get("book", "").strip().strip("《》")
    f = _fit(d, name, F_SERIF, 64, cw - 72, min_size=38)
    box = d.textbbox((0, 0), name, font=f)
    d.text((x0 + (cw - (box[2] - box[0])) // 2 - box[0], y0 + 118),
           name, font=f, fill=(32, 36, 40))
    f2 = _font(F_REG, 25)
    for k, ln in enumerate(["读书感悟 · 自写文案", "非原文摘录 · 示意封面"]):
        box = d.textbbox((0, 0), ln, font=f2)
        d.text((x0 + (cw - (box[2] - box[0])) // 2 - box[0], y0 + 246 + k * 42),
               ln, font=f2, fill=(112, 96, 76))
    d.line([(x0 + 88, y0 + 418), (x0 + cw - 88, y0 + 418)], fill=ORANGE, width=3)
    d.ellipse([x0 + cw // 2 - 36, y0 + 450, x0 + cw // 2 + 36, y0 + 522],
              outline=ORANGE, width=3)
    return im


def badge_png(path):
    """片头/片尾左下角显著 AI 标识：28px 白底黑字胶囊 + 橙竖条（法规下限）。"""
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    f = _font(F_BOLD, 28)
    s = "AI 生成内容"
    box = d.textbbox((0, 0), s, font=f)
    tw, th = box[2] - box[0], box[3] - box[1]
    pad_x, pad_y = 14, 8
    x0, y0 = 84, H - 140
    x1, y1 = x0 + tw + pad_x * 2, y0 + th + pad_y * 2
    # 用户 2026-11-14「不想要 AI 水印特别醒目」：不加描边、不加阴影、
    # 不加放大动画，白底黑字细胶囊保持 28px 放在左下角，克制不抢画面。
    # 但 28px + 白底黑字高对比是《标识办法》「显著」的下限，不再缩小、
    # 不改灰字、不去橙竖条；发布页 AI 声明仍须手动勾选。
    d.rounded_rectangle([x0, y0, x1, y1], radius=7, fill=(250, 250, 248, 242))
    d.rectangle([x0 + 6, y0 + 7, x0 + 9, y1 - 7], fill=ORANGE + (255,))
    d.text((x0 + pad_x - box[0], y0 + pad_y - box[1]), s, font=f, fill=(22, 26, 32, 255))
    layer.save(path)


# ------------------------------------------- 对标参考号：黑白人像 + 局部橙

def _verse_files():
    fs = glob.glob(os.path.join(BG_DIR, "*.png"))
    human = next((f for f in fs if "背影" in f), fs[0])
    window = next((f for f in fs if "窗棂" in f), fs[min(1, len(fs) - 1)])
    still = next((f for f in fs if "茶盏" in f), fs[-1])
    return [human, window, still]


def noir_bg(idx: int = 0, variant: int = 0, tail: bool = False) -> Image.Image:
    """自有黑白摄影素材：人形背影占屏 + 局部亮橙 + 上下压黑托白字。

    与参考片对齐的是观感（黑白人像/摄影温度/局部橙/大留白），素材全部自有，
    不使用真人正脸照片、真实书封或平台 UI。
    """
    fs = _verse_files()
    src = Image.open(fs[idx % len(fs)]).convert("RGB")
    # 自有 AI 图右下角自带「AI生成 / WORKBUDDY」，裁掉底部 8%
    src = src.crop((0, 0, src.width, int(src.height * 0.92)))
    if idx % 3 == 0:
        # 人形那张额外放大取景，让肩线/后脑占据下半屏
        z = 1.30 + 0.04 * (variant % 2)
        sw, sh = src.size
        cw, ch = int(sw / z), int(sh / z)
        ox = (sw - cw) // 2
        oy = int((sh - ch) * 0.60)
        src = src.crop((ox, oy, ox + cw, oy + ch))
    elif variant % 2:
        src = ImageOps.mirror(src)
    im = _cover(src)

    g = ImageOps.grayscale(im)
    g = ImageEnhance.Contrast(g).enhance(1.20)
    g = ImageEnhance.Brightness(g).enhance(0.92)
    im = ImageOps.colorize(g, (5, 6, 8), (226, 228, 230)).convert("RGB")
    im = im.filter(ImageFilter.UnsharpMask(radius=1.1, percent=95, threshold=3))

    # 局部柔橙跟着主体走，不是固定贴纸
    glow = Image.new("RGB", (W, H), (0, 0, 0))
    gd = ImageDraw.Draw(glow)
    gx = int(W * (0.30 if variant % 2 == 0 else 0.72))
    gy = int(H * (0.55 if not tail else 0.42))
    for rr in range(540, 0, -20):
        a = int(105 * (1 - rr / 540.0) ** 2)
        gd.ellipse([gx - rr, gy - rr, gx + rr, gy + rr],
                   fill=(a, int(a * 0.46), int(a * 0.09)))
    glow = glow.filter(ImageFilter.GaussianBlur(96))
    im = ImageChops.screen(im, glow)

    # 顶部/底部压黑，保证白字与顶部书名作者干净
    vig = Image.new("L", (1, H))
    for y in range(H):
        if y < 430:
            v = 0.58 * (1 - y / 430.0) + 0.06
        elif y > 1480:
            v = 0.06 + 0.58 * ((y - 1480) / float(H - 1480))
        else:
            v = 0.0
        vig.putpixel((0, y), int(v * 255))
    vig = vig.resize((W, H))
    im = Image.composite(Image.new("RGB", (W, H), (4, 5, 7)), im, vig)

    if tail:
        # 自制「搜索条」式片尾卡：素色、无平台 logo / 无抖音码 / 无账号名
        d = ImageDraw.Draw(im)
        x0, y0, x1, y1 = 110, 1480, 970, 1640
        d.rounded_rectangle([x0, y0, x1, y1], radius=24,
                            fill=(22, 24, 28), outline=(76, 78, 82), width=2)
        d.ellipse([x0 + 44, y0 + 52, x0 + 104, y0 + 112],
                  outline=ORANGE, width=6)
        d.line([(x0 + 98, y0 + 106), (x0 + 128, y0 + 136)], fill=ORANGE, width=6)
        q = "搜索 · " + SEARCH_WORD
        f = _font(F_SERIF, 46)
        box = d.textbbox((0, 0), q, font=f)
        d.text((x0 + 156 - box[0], y0 + 58 - box[1]), q, font=f,
               fill=(240, 241, 242))
        # 第二行避开放大镜柄，且不与 ASS 的 save_line 重复
        d.text((x0 + 190, y0 + 118), "把这一帧留给自己",
               font=_font(F_REG, 24), fill=(168, 170, 174))
    return im


def noir_book(im, job):
    """暗调立体示意书封（自绘，非真实书封美术）。"""
    cw, ch = 420, 600
    x0, y0 = (W - cw) // 2, 700
    d = ImageDraw.Draw(im)
    d.rectangle([x0 + 20, y0 + 26, x0 + cw + 20, y0 + ch + 26], fill=(2, 3, 5))
    d.rectangle([x0 + 9, y0 + 13, x0 + cw + 9, y0 + ch + 13], fill=(8, 9, 12))
    d.rectangle([x0 - 18, y0 + 6, x0, y0 + ch + 6], fill=(38, 34, 30))
    d.rectangle([x0 + cw, y0 + 6, x0 + cw + 11, y0 + ch + 6], fill=(150, 146, 138))
    for k in range(9):
        yy = y0 + 60 + k * 58
        d.line([(x0 + cw + 1, yy), (x0 + cw + 10, yy)], fill=(92, 90, 84), width=1)
    paper = Image.new("RGB", (cw, ch))
    pd = ImageDraw.Draw(paper)
    for x in range(cw):
        t = x / float(cw)
        pd.line([(x, 0), (x, ch)],
                fill=(int(52 - 24 * t), int(53 - 24 * t), int(56 - 24 * t)))
    lg = Image.new("RGB", (cw, ch), (0, 0, 0))
    lgd = ImageDraw.Draw(lg)
    for rr in range(340, 0, -12):
        a = int(58 * (1 - rr / 340.0) ** 2)
        lgd.ellipse([-20 - rr, -30 - rr, -20 + rr, -30 + rr],
                    fill=(a, int(a * 0.56), int(a * 0.22)))
    lg = lg.filter(ImageFilter.GaussianBlur(46))
    im.paste(ImageChops.screen(paper, lg), (x0, y0))
    d = ImageDraw.Draw(im)
    d.rectangle([x0, y0, x0 + cw, y0 + ch], outline=(104, 100, 92), width=2)
    d.rectangle([x0 + 22, y0 + 22, x0 + cw - 22, y0 + ch - 22],
                outline=(72, 70, 66), width=1)
    name = job.get("book", "").strip().strip("《》")
    f = _fit(d, name, F_SERIF, 68, cw - 70, min_size=40)
    box = d.textbbox((0, 0), name, font=f)
    d.text((x0 + (cw - (box[2] - box[0])) // 2 - box[0], y0 + 150),
           name, font=f, fill=(238, 239, 240))
    d.line([(x0 + 92, y0 + 300), (x0 + cw - 92, y0 + 300)], fill=ORANGE, width=3)
    for k, ln in enumerate(["读书感悟 · 自写文案", "示意封面 · 非真实书封"]):
        f2 = _font(F_REG, 24)
        box = d.textbbox((0, 0), ln, font=f2)
        d.text((x0 + (cw - (box[2] - box[0])) // 2 - box[0], y0 + 400 + k * 40),
               ln, font=f2, fill=(150, 152, 156))
    return im


# ------------------------------- 实拍参考图：B 人形剪影 + C 柔光层 + A 留白过渡
# 依据 douyin/背景参考_2026-11-16.md：B 组补「人味」收益最大、C 组纯抽象渐变
# 只能当柔光层、A 组做留白过渡。全部 Pexels 免费可商用，只有背影/剪影，无正脸。
PHOTO_DIR = os.path.join(BASE, "assets", "photo")
PHOTO_SEQ = [
    "b3_13661616",   # 彩色光下的人形剪影：B+C 的天然交集
    "b5_15057563",   # 拱窗背影
    "b2_25677297",   # 窗前抱头剪影
    "b3_13661616",   # 彩色人形剪影回环：正好落在 15s 的「够了」大字屏
    "b4_20786271",   # 窗边背影
    "b1_8319595",    # 窗前城市剪影
    "a3_7649774",    # 翻开的书 + 尤加利（留白过渡）
    "a2_37804903",   # 窗边阅读角（留白过渡）
]
PHOTO_TAIL = "a1_37302579"   # 窗边书堆 + 绿植，大片亮窗留白
PHOTO_SOFT = ["c6_30501775", "c4_29901621", "c1_7135057"]


def _photo_file(tag):
    p = os.path.join(PHOTO_DIR, tag + ".jpg")
    if os.path.exists(p):
        return p
    fs = glob.glob(os.path.join(PHOTO_DIR, tag.split("_")[0] + "_*.jpg"))
    if fs:
        return fs[0]
    raise FileNotFoundError("缺少实拍参考图: " + p)


def _photo_shade():
    """分段线性压暗留字区：叠黑让白字更锐利，插值避免横向硬边。"""
    kp = [(0, 0.54), (300, 0.40), (430, 0.24), (820, 0.18),
          (1120, 0.24), (1460, 0.30), (1620, 0.44), (1919, 0.62)]
    m = Image.new("L", (1, H))
    for y in range(H):
        v = kp[-1][1]
        for k in range(len(kp) - 1):
            if kp[k][0] <= y <= kp[k + 1][0]:
                y0, v0 = kp[k]
                y1, v1 = kp[k + 1]
                v = v0 + (v1 - v0) * ((y - y0) / float(y1 - y0))
                break
        m.putpixel((0, y), int(v * 255))
    return m.resize((W, H))


def _photo_readability(im):
    """按留字区实测亮度自适应补压暗：亮窗/书页段也保证白字锐利。

    只压顶部书名区与中部字幕区，纵向线性插值无横向硬边；暗调人形段
    亮度本来就够，返回原图不额外压黑，避免又变成「死气沉沉」。
    """
    g = ImageOps.grayscale(im)
    top = ImageStat.Stat(g.crop((0, 120, W, 430))).mean[0]
    mid = ImageStat.Stat(g.crop((0, 1050, W, 1450))).mean[0]
    a_top = max(0.0, min(0.55, (top - 60) / 145.0))
    a_mid = max(0.0, min(0.64, (mid - 60) / 145.0))
    if a_top < 0.02 and a_mid < 0.02:
        return im
    kp = [(0, a_top), (330, a_top), (430, a_top * 0.75),
          (760, a_top * 0.20 + a_mid * 0.10),
          (1000, a_mid * 0.85), (1120, a_mid), (1450, a_mid),
          (1620, a_mid * 0.45), (1919, 0.16)]
    m = Image.new("L", (1, H))
    for y in range(H):
        v = kp[-1][1]
        for k in range(len(kp) - 1):
            if kp[k][0] <= y <= kp[k + 1][0]:
                y0, v0 = kp[k]
                y1, v1 = kp[k + 1]
                v = v0 + (v1 - v0) * ((y - y0) / float(y1 - y0))
                break
        m.putpixel((0, y), int(v * 255))
    return Image.composite(Image.new("RGB", (W, H), (10, 5, 26)), im,
                           m.resize((W, H)))


def photo_bg(idx: int = 0, variant: int = 0, tail: bool = False) -> Image.Image:
    """Pexels 实拍图底：人形背影/剪影主画面 + 高饱和渐变柔光 + 留白过渡。

    与纯程序化 vivid 的区别：保留真实摄影的布料、轮廓光、颗粒，不再是 AI 剪影。
    1200x1800 -> 1080x1920 只需 1.07 倍放大，文字与主体都不重采样多次。
    """
    tag = PHOTO_TAIL if tail else PHOTO_SEQ[variant % len(PHOTO_SEQ)]
    im = _cover(Image.open(_photo_file(tag)).convert("RGB"))
    im = ImageEnhance.Contrast(im).enhance(1.08)
    im = im.filter(ImageFilter.UnsharpMask(radius=1.0, percent=80, threshold=3))

    # C 组渐变只作柔光层：本身已很艳的图少叠，避免糊成 PPT 色卡
    sat = ImageStat.Stat(im.convert("HSV").split()[1]).mean[0] / 255.0
    strength = 0.18 if sat > 0.32 else 0.46
    soft = _cover(Image.open(_photo_file(PHOTO_SOFT[variant % 3])).convert("RGB"))
    soft = soft.filter(ImageFilter.GaussianBlur(90))
    soft = ImageEnhance.Brightness(soft).enhance(0.50)
    im = Image.blend(im, ImageChops.screen(im, soft), strength)

    # 近黑白的实拍图（抱头剪影 / 城市剪影）补一层紫→玫→金橙渐变映射，
    # 只混 45% 保留窗框斑驳与布料质感，避免整段发灰又不变成纯色卡
    if sat < 0.20:
        g = ImageOps.autocontrast(ImageOps.grayscale(im), cutoff=1)
        rs, gs, bs = _grad_lut(VIVID_STOPS["warm"])
        im = Image.blend(im, Image.merge("RGB", (g.point(rs), g.point(gs),
                                                 g.point(bs))), 0.45)

    # 压暗：顶部常驻书名 / 中部字幕 / 底部声明，白字可读；
    # 亮窗与书页段按实测亮度再补一层，暗调人形段不额外压黑
    im = Image.composite(Image.new("RGB", (W, H), (14, 6, 32)), im, _photo_shade())
    im = _photo_readability(im)

    if tail:
        # 自制素色搜索卡：无平台 logo / 无抖音码 / 无账号水印
        d = ImageDraw.Draw(im)
        x0, y0, x1, y1 = 110, 1480, 970, 1640
        d.rounded_rectangle([x0, y0, x1, y1], radius=24,
                            fill=(36, 12, 74), outline=VIVID_GOLD, width=3)
        d.ellipse([x0 + 44, y0 + 52, x0 + 104, y0 + 112],
                  outline=VIVID_GOLD, width=6)
        d.line([(x0 + 98, y0 + 106), (x0 + 128, y0 + 136)],
               fill=VIVID_GOLD, width=6)
        q = "搜索 · " + SEARCH_WORD
        f = _font(F_SERIF, 46)
        box = d.textbbox((0, 0), q, font=f)
        d.text((x0 + 156 - box[0], y0 + 58 - box[1]), q, font=f,
               fill=(255, 246, 226))
        d.text((x0 + 190, y0 + 118), "把这一帧留给自己",
               font=_font(F_REG, 24), fill=(234, 196, 226))
    return im


def photo_book(im, job):
    """实拍版片头：暗晕托底 + 自绘玫紫金橙示意书封（长书名自动折两行）。"""
    im = Image.blend(im, Image.new("RGB", (W, H), (10, 4, 28)), 0.24)
    cw, ch = 420, 600
    x0, y0 = (W - cw) // 2, 700
    d = ImageDraw.Draw(im)
    d.rectangle([x0 + 20, y0 + 26, x0 + cw + 20, y0 + ch + 26], fill=(12, 4, 36))
    d.rectangle([x0 + 9, y0 + 13, x0 + cw + 9, y0 + ch + 13], fill=(28, 8, 58))
    d.rectangle([x0 - 18, y0 + 6, x0, y0 + ch + 6], fill=(96, 22, 92))
    d.rectangle([x0 + cw, y0 + 6, x0 + cw + 11, y0 + ch + 6],
                fill=(255, 196, 120))
    for k in range(9):
        yy = y0 + 60 + k * 58
        d.line([(x0 + cw + 1, yy), (x0 + cw + 10, yy)],
               fill=(232, 152, 150), width=1)
    paper = Image.new("RGB", (cw, ch))
    pd = ImageDraw.Draw(paper)
    for x in range(cw):
        t = x / float(cw)
        pd.line([(x, 0), (x, ch)],
                fill=(int(126 - 34 * t), int(30 + 26 * t), int(104 - 18 * t)))
    lg = Image.new("RGB", (cw, ch), (0, 0, 0))
    lgd = ImageDraw.Draw(lg)
    for rr in range(340, 0, -12):
        a = int(72 * (1 - rr / 340.0) ** 2)
        lgd.ellipse([-20 - rr, -30 - rr, -20 + rr, -30 + rr],
                    fill=(a, int(a * 0.70), int(a * 0.26)))
    lg = lg.filter(ImageFilter.GaussianBlur(46))
    im.paste(ImageChops.screen(paper, lg), (x0, y0))
    d = ImageDraw.Draw(im)
    d.rectangle([x0, y0, x0 + cw, y0 + ch], outline=VIVID_GOLD, width=3)
    d.rectangle([x0 + 22, y0 + 22, x0 + cw - 22, y0 + ch - 22],
                outline=(255, 150, 190), width=1)
    name = job.get("book", "").strip().strip("《》")
    if len(name) > 8:
        brk = 4
        rows = [name[:brk], name[brk:]]
        fs = 46
    else:
        rows = [name]
        fs = 62
    for i, ln in enumerate(rows):
        f = _fit(d, ln, F_SERIF, fs, cw - 70, min_size=28)
        box = d.textbbox((0, 0), ln, font=f)
        d.text((x0 + (cw - (box[2] - box[0])) // 2 - box[0],
                y0 + 140 + i * 66), ln, font=f, fill=(255, 250, 232))
    d.line([(x0 + 92, y0 + 300), (x0 + cw - 92, y0 + 300)],
           fill=VIVID_GOLD, width=4)
    for k, ln in enumerate(["读书感悟 · 自写文案", "示意封面 · 非真实书封"]):
        f2 = _font(F_REG, 24)
        box = d.textbbox((0, 0), ln, font=f2)
        d.text((x0 + (cw - (box[2] - box[0])) // 2 - box[0],
                y0 + 400 + k * 40), ln, font=f2, fill=(240, 196, 220))
    return im


# ---------------------------------------------------------------- 高饱和艳丽底图
def _grad_lut(stops):
    """把 0..255 灰度线性映射到多段高饱和色带，返回三条 256 长度 LUT。"""
    rs, gs, bs = [], [], []
    for i in range(256):
        a, b = stops[0], stops[-1]
        for k in range(len(stops) - 1):
            if stops[k][0] <= i <= stops[k + 1][0]:
                a, b = stops[k], stops[k + 1]
                break
        t = 0.0 if b[0] == a[0] else (i - a[0]) / float(b[0] - a[0])
        rs.append(int(a[1][0] + (b[1][0] - a[1][0]) * t))
        gs.append(int(a[1][1] + (b[1][1] - a[1][1]) * t))
        bs.append(int(a[1][2] + (b[1][2] - a[1][2]) * t))
    return rs, gs, bs


VIVID_STOPS = {
    "warm": [(0, (16, 8, 54)), (52, (66, 18, 112)), (108, (158, 28, 126)),
             (164, (232, 58, 104)), (208, (255, 132, 48)),
             (240, (255, 196, 78)), (255, (255, 238, 172))],
    "cool": [(0, (8, 16, 64)), (52, (22, 56, 148)), (108, (36, 132, 214)),
             (164, (84, 206, 232)), (208, (176, 96, 232)),
             (240, (236, 132, 226)), (255, (248, 220, 246))],
}


def _vivid_shade():
    """分段线性深罩：顶部/底部与字幕区压深紫，白字清晰且无横向硬边。"""
    kp = [(0, 0.62), (320, 0.40), (430, 0.30), (820, 0.30),
          (960, 0.34), (1460, 0.34), (1620, 0.44), (1919, 0.64)]
    m = Image.new("L", (1, H))
    for y in range(H):
        v = kp[-1][1]
        for k in range(len(kp) - 1):
            if kp[k][0] <= y <= kp[k + 1][0]:
                y0, v0 = kp[k]
                y1, v1 = kp[k + 1]
                v = v0 + (v1 - v0) * ((y - y0) / float(y1 - y0))
                break
        m.putpixel((0, y), int(v * 255))
    return m.resize((W, H))


def vivid_bg(idx: int = 0, variant: int = 0, tail: bool = False) -> Image.Image:
    """高饱和艳丽版底图：自有黑白素材做渐变映射上色，纯程序化、0 积分。

    与 noir 共用构图与合规素材，但不再「去色 + 局部橙」：整幅铺靛紫→玫红→
    金橙的高饱和色带，叠青蓝/玫金双色柔光，人形放大到更占屏。
    """
    if PHOTO_SOURCE:
        return photo_bg(idx, variant, tail)
    fs = _verse_files()
    src = Image.open(fs[idx % len(fs)]).convert("RGB")
    src = src.crop((0, 0, src.width, int(src.height * 0.92)))
    if idx % 3 == 0:
        z = 1.44 + 0.04 * (variant % 2)  # 人形比 noir 更占屏
        sw, sh = src.size
        cw, ch = int(sw / z), int(sh / z)
        ox = (sw - cw) // 2
        oy = int((sh - ch) * 0.60)
        src = src.crop((ox, oy, ox + cw, oy + ch))
    elif variant % 2:
        src = ImageOps.mirror(src)
    im = _cover(src)

    g = ImageOps.grayscale(im)
    g = ImageOps.autocontrast(g, cutoff=2)
    g = ImageEnhance.Brightness(g).enhance(0.94)
    rs, gs, bs = _grad_lut(VIVID_STOPS.get(PALETTE, VIVID_STOPS["warm"]))
    im = Image.merge("RGB", (g.point(rs), g.point(gs), g.point(bs)))
    im = im.filter(ImageFilter.UnsharpMask(radius=1.1, percent=88, threshold=3))

    glow = Image.new("RGB", (W, H), (0, 0, 0))
    gd = ImageDraw.Draw(glow)
    if PALETTE == "cool":
        c1, c2 = (20, 120, 220), (190, 60, 220)
    else:
        c1, c2 = (18, 128, 214), (255, 66, 128)
    for gx, gy, col, peak in [
        (int(W * 0.20), int(H * 0.30), c1, 92),
        (int(W * 0.80), int(H * 0.68), c2, 108),
    ]:
        for rr in range(560, 0, -20):
            a = int(peak * (1 - rr / 560.0) ** 2)
            gd.ellipse([gx - rr, gy - rr, gx + rr, gy + rr],
                       fill=(int(a * col[0] / 255), int(a * col[1] / 255),
                             int(a * col[2] / 255)))
    glow = glow.filter(ImageFilter.GaussianBlur(110))
    im = ImageChops.screen(im, glow)
    im = Image.composite(Image.new("RGB", (W, H), (22, 8, 58)), im, _vivid_shade())

    if tail:
        d = ImageDraw.Draw(im)
        x0, y0, x1, y1 = 110, 1480, 970, 1640
        d.rounded_rectangle([x0, y0, x1, y1], radius=24,
                            fill=(36, 12, 74), outline=VIVID_GOLD, width=3)
        d.ellipse([x0 + 44, y0 + 52, x0 + 104, y0 + 112],
                  outline=VIVID_GOLD, width=6)
        d.line([(x0 + 98, y0 + 106), (x0 + 128, y0 + 136)],
               fill=VIVID_GOLD, width=6)
        q = "搜索 · " + SEARCH_WORD
        f = _font(F_SERIF, 46)
        box = d.textbbox((0, 0), q, font=f)
        d.text((x0 + 156 - box[0], y0 + 58 - box[1]), q, font=f,
               fill=(255, 246, 226))
        d.text((x0 + 190, y0 + 118), "把这一帧留给自己",
               font=_font(F_REG, 24), fill=(234, 196, 226))
    return im


def vivid_book(im, job):
    """艳丽版自绘示意书封：玫紫纸面 + 金橙侧光 + 亮金边框（非真实书封）。"""
    if PHOTO_SOURCE:
        return photo_book(im, job)
    cw, ch = 420, 600
    x0, y0 = (W - cw) // 2, 700
    d = ImageDraw.Draw(im)
    d.rectangle([x0 + 20, y0 + 26, x0 + cw + 20, y0 + ch + 26], fill=(12, 4, 36))
    d.rectangle([x0 + 9, y0 + 13, x0 + cw + 9, y0 + ch + 13], fill=(28, 8, 58))
    d.rectangle([x0 - 18, y0 + 6, x0, y0 + ch + 6], fill=(96, 22, 92))
    d.rectangle([x0 + cw, y0 + 6, x0 + cw + 11, y0 + ch + 6],
                fill=(255, 196, 120))
    for k in range(9):
        yy = y0 + 60 + k * 58
        d.line([(x0 + cw + 1, yy), (x0 + cw + 10, yy)],
               fill=(232, 152, 150), width=1)
    paper = Image.new("RGB", (cw, ch))
    pd = ImageDraw.Draw(paper)
    for x in range(cw):
        t = x / float(cw)
        pd.line([(x, 0), (x, ch)],
                fill=(int(126 - 34 * t), int(30 + 26 * t), int(104 - 18 * t)))
    lg = Image.new("RGB", (cw, ch), (0, 0, 0))
    lgd = ImageDraw.Draw(lg)
    for rr in range(340, 0, -12):
        a = int(72 * (1 - rr / 340.0) ** 2)
        lgd.ellipse([-20 - rr, -30 - rr, -20 + rr, -30 + rr],
                    fill=(a, int(a * 0.70), int(a * 0.26)))
    lg = lg.filter(ImageFilter.GaussianBlur(46))
    im.paste(ImageChops.screen(paper, lg), (x0, y0))
    d = ImageDraw.Draw(im)
    d.rectangle([x0, y0, x0 + cw, y0 + ch], outline=VIVID_GOLD, width=3)
    d.rectangle([x0 + 22, y0 + 22, x0 + cw - 22, y0 + ch - 22],
                outline=(255, 150, 190), width=1)
    name = job.get("book", "").strip().strip("《》")
    f = _fit(d, name, F_SERIF, 68, cw - 70, min_size=40)
    box = d.textbbox((0, 0), name, font=f)
    d.text((x0 + (cw - (box[2] - box[0])) // 2 - box[0], y0 + 150),
           name, font=f, fill=(255, 250, 232))
    d.line([(x0 + 92, y0 + 300), (x0 + cw - 92, y0 + 300)],
           fill=VIVID_GOLD, width=4)
    for k, ln in enumerate(["读书感悟 · 自写文案", "示意封面 · 非真实书封"]):
        f2 = _font(F_REG, 24)
        box = d.textbbox((0, 0), ln, font=f2)
        d.text((x0 + (cw - (box[2] - box[0])) // 2 - box[0], y0 + 400 + k * 40),
               ln, font=f2, fill=(240, 196, 220))
    return im


# ---------------------------------------------------------------- ASS 字幕
# 亮底深墨字必须 Outline=0：ASS 的 \k 逐字渐显里，未读字用
# SecondaryColour(全透明) 填充，但如果留描边，描边色仍会画出来，
# 浅色描边在亮底上就变成刺眼的「白色空心字」。去掉描边后未读字彻底
# 不可见、已读字是干净锐利的深墨色，对比度反而最高。
STYLE_HEAD = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Cn,Noto Serif SC,82,&H001E2328,&HFF000000,&H00000000,&H00000000,0,0,0,0,100,100,2,0,1,0,0,2,50,50,0,1
Style: En,Noto Sans SC,36,&H003A3228,&H003A3228,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,0,0,2,60,60,0,1
Style: Head,Noto Serif SC,62,&H001E2328,&H001E2328,&H00000000,&H00000000,0,0,0,0,100,100,2,0,1,0,0,2,50,50,0,1
Style: Author,Noto Sans SC,28,&H003A3228,&H003A3228,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,0,0,2,60,60,0,1
Style: Hook,Noto Serif SC,66,&H001E2328,&H001E2328,&H00000000,&H00000000,0,0,0,0,100,100,2,0,1,0,0,2,60,60,0,1
Style: Tail,Noto Serif SC,50,&H001E2328,&H001E2328,&H00000000,&H00000000,0,0,0,0,100,100,2,0,1,0,0,2,60,60,0,1
Style: Save,Noto Sans SC,30,&H000050B0,&H000050B0,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,0,0,2,60,60,0,1
Style: Foot,Noto Sans SC,26,&H003A3228,&H003A3228,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,0,0,2,60,60,0,1

[Events]
Format: Layer, Start, End, Style, Text
"""

# 2026-11-16 对标参考号：近纯黑底 + 白字、字更大、中英紧挨。
# Outline 仍为 0（\k 逐字渐显时描边不会随未读字透明，会留下空心字）。
STYLE_HEAD_NOIR = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Cn,Noto Serif SC,96,&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,0,0,0,0,100,100,2,0,1,0,0,2,50,50,0,1
Style: En,Noto Sans SC,38,&H00DCDCDC,&H00DCDCDC,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,0,0,2,60,60,0,1
Style: Head,Noto Serif SC,68,&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,0,0,0,0,100,100,2,0,1,0,0,2,50,50,0,1
Style: Author,Noto Sans SC,30,&H00DCDCDC,&H00DCDCDC,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,0,0,2,60,60,0,1
Style: Hook,Noto Serif SC,88,&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,0,0,0,0,100,100,2,0,1,0,0,2,60,60,0,1
Style: Big,Noto Serif SC,190,&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,0,0,0,0,100,100,6,0,1,0,0,2,50,50,0,1
Style: Tail,Noto Serif SC,56,&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,0,0,0,0,100,100,2,0,1,0,0,2,60,60,0,1
Style: Save,Noto Sans SC,32,&H001A70E0,&H001A70E0,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,0,0,2,60,60,0,1
Style: Foot,Noto Sans SC,26,&H00B8B8B8,&H00B8B8B8,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,0,0,2,60,60,0,1

[Events]
Format: Layer, Start, End, Style, Text
"""


# 2026-11-16 艳丽版：白字保持高对比，强调色改亮金/亮青/浅粉。
# ASS 颜色是 &HAABBGGRR（BGR 序），Big=亮金橙(255,186,58)、Save=亮青(80,220,255)。
# Outline 仍必须为 0：\k 逐字渐显时描边不随未读字透明，会留下空心字。
STYLE_HEAD_VIVID = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Cn,Noto Serif SC,96,&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,0,0,0,0,100,100,2,0,1,0,0,2,50,50,0,1
Style: En,Noto Sans SC,38,&H00B4E6FF,&H00B4E6FF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,0,0,2,60,60,0,1
Style: Head,Noto Serif SC,68,&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,0,0,0,0,100,100,2,0,1,0,0,2,50,50,0,1
Style: Author,Noto Sans SC,30,&H00B4E6FF,&H00B4E6FF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,0,0,2,60,60,0,1
Style: Hook,Noto Serif SC,88,&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,0,0,0,0,100,100,2,0,1,0,0,2,60,60,0,1
Style: Big,Noto Serif SC,190,&H003AB8FF,&H003AB8FF,&H00000000,&H00000000,0,0,0,0,100,100,6,0,1,0,0,2,50,50,0,1
Style: Tail,Noto Serif SC,56,&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,0,0,0,0,100,100,2,0,1,0,0,2,60,60,0,1
Style: Save,Noto Sans SC,32,&H003AB8FF,&H003AB8FF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,0,0,2,60,60,0,1
Style: Foot,Noto Sans SC,26,&H00E6CEE2,&H00E6CEE2,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,0,0,2,60,60,0,1

[Events]
Format: Layer, Start, End, Style, Text
"""


# photo_source 专用样式：Big 大字屏不走 \\k 逐字渐显，可以安全加深色描边，
# 让亮金大字压在亮窗/白墙上仍锐利；其余样式保持 Outline=0，避免空心字。
STYLE_HEAD_PHOTO = STYLE_HEAD_VIVID.replace(
    "Style: Big,Noto Serif SC,190,&H003AB8FF,&H003AB8FF,"
    "&H00000000,&H00000000,0,0,0,0,100,100,6,0,1,0,0,2,50,50,0,1",
    "Style: Big,Noto Serif SC,190,&H003AB8FF,&H003AB8FF,"
    "&H00402010,&H00000000,0,0,0,0,100,100,6,0,1,4,0,2,50,50,0,1")
assert STYLE_HEAD_PHOTO != STYLE_HEAD_VIVID, "Big 样式替换失败"


# 2026-11-17 参考片《停止内耗》声音层复刻专用：
# 逐字渐显要「未读暗灰 → 已读白」，而不是整句常白；开场大字降号，避免说教感。
STYLE_HEAD_REF = (
    STYLE_HEAD_NOIR
    .replace("Style: Cn,Noto Serif SC,96,&H00FFFFFF,&H00FFFFFF,",
             "Style: Cn,Noto Serif SC,88,&H00FFFFFF,&H00A8A8A8,")
    .replace("Style: Hook,Noto Serif SC,88,&H00FFFFFF,&H00FFFFFF,",
             "Style: Hook,Noto Serif SC,60,&H00FFFFFF,&H00FFFFFF,")
)
assert STYLE_HEAD_REF != STYLE_HEAD_NOIR, "参考片字幕样式替换失败"


_REF_PUNCT = "，。！？；：、,.!?;:…）」》】"


def split_screens(parts, text, max_chars=15, en_list=None):
    """把「连贯长句」切成参考片式的一屏一句短字幕。

    配音是一整段连贯长句（不按屏断句，避免念稿感），字幕按标点切子句后
    贪心合并成 8–17 字短屏。三条硬规矩：标点留在上一屏末尾、书名整块不
    从中间劈开、不产生 1–5 字的空屏。逐字渐显仍跟 words 时间轴严格对齐。
    """
    en_list = en_list or []
    clauses = []
    for p in parts:
        a, b = p["c0"], p["c1"]
        st, i = a, a
        while i < b:
            if text[i] in _REF_PUNCT:
                # 连续标点（如「》，」「。！」）一起归上一子句，
                # 否则下一屏会以逗号开头，非常难看。
                j = i + 1
                while j < b and text[j] in _REF_PUNCT:
                    j += 1
                if j > st:
                    clauses.append((st, j))
                st, i = j, j
            else:
                i += 1
        if st < b:
            clauses.append((st, b))

    screens = []
    cur = None
    for cs, ce in clauses:
        seg = text[cs:ce]
        # text 由 "\\n".join(段落) 拼成，段间那个换行不是标点。
        # 若把上一段的尾子句和下一段的首子句贪心合并，换行会被一起带进
        # 字幕（成片出现「事一过就该关掉。\\n可人不一样，」这种跨段屏）。
        # 因此检测到跨段就强制断屏，任何一屏都不允许包含 "\\n"。
        cross = cur is not None and "\n" in text[cur[1]:cs]
        if "《" in seg or "》" in seg:
            # 书名所在子句整块独占一屏，避免「《蛤蟆先生去看心理 / 医生》」
            if cur:
                screens.append(cur)
                cur = None
            screens.append((cs, ce))
            continue
        if cur is None:
            cur = (cs, ce)
        elif cross:
            screens.append(cur)
            cur = (cs, ce)
        elif (cur[1] - cur[0]) + (ce - cs) <= max_chars + 2:
            cur = (cur[0], ce)
        elif (cur[1] - cur[0]) >= 8:
            screens.append(cur)
            cur = (cs, ce)
        else:
            cur = (cur[0], ce)
    if cur:
        screens.append(cur)

    # 单屏过长时按字数二次切，优先把切点挪到标点之后
    out = []
    for cs, ce in screens:
        if ce - cs <= max_chars + 4:
            out.append([cs, ce])
            continue
        k = cs
        while k < ce:
            e = min(k + max_chars, ce)
            if e < ce:
                for j in range(e, k + 6, -1):
                    if text[j - 1] in _REF_PUNCT:
                        e = j
                        break
            out.append([k, e])
            k = e

    # 过短尾屏并入上一屏，杜绝「课。」「。」这种近乎空白的一屏
    merged = []
    for s in out:
        short_tail = (merged and (s[1] - s[0]) < 6
                      and (s[1] - merged[-1][0]) <= 22
                      and "\n" not in text[merged[-1][1]:s[0]])
        if short_tail:
            merged[-1][1] = s[1]
        else:
            merged.append(s)

    return [{"c0": a, "c1": b,
             "en": en_list[i] if i < len(en_list) else ""}
            for i, (a, b) in enumerate(merged)]


def build_ass_ref(job, subs, words, text, out_path, total, tail_t0):
    """参考片式 ASS：顶部常驻书名作者 / 一屏一句 / 中英双行 / 逐字渐显 / 片尾搜索条。"""
    lines = []
    t_end = ass_time(total)
    name = "《%s》" % job.get("book", "").strip().strip("《》")
    lines.append("Dialogue: 0,%s,%s,Head,{\\pos(540,220)\\an2\\fad(700,700)}%s"
                 % (ass_time(0), t_end, name))
    lines.append("Dialogue: 0,%s,%s,Author,{\\pos(540,320)\\an2\\fad(700,700)}%s"
                 % (ass_time(0), t_end, job.get("author", "")))
    lines.append("Dialogue: 0,%s,%s,Foot,{\\pos(540,1740)\\an2\\fad(700,700)}%s"
                 % (ass_time(0), t_end, "读书感悟 · 非原文摘录 · 版本以纸质书为准"))

    # 开场：介绍体不额外叠钩子大字（顶部常驻书名已是报书名），
    # 否则会和片头示意书封、首屏字幕三者挤在同一区域。
    if job.get("hook_line"):
        lines.append("Dialogue: 1,%s,%s,Hook,{\\fad(600,600)\\pos(540,620)\\an2}%s"
                     % (ass_time(0.25), ass_time(3.4), job["hook_line"]))

    punct = _REF_PUNCT
    for k, s in enumerate(subs):
        a, b = s["c0"], s["c1"]
        st = max(0.0, words[a]["start"] - 0.08)
        last = words[b - 1]["end"]
        nxt = subs[k + 1]["c0"] if k + 1 < len(subs) else None
        en = min(words[nxt]["start"] - 0.05, last + 0.20) if nxt else last + 0.28
        s_ass, e_ass = ass_time(st), ass_time(max(st + 0.3, en))
        chars = [text[i] for i in range(a, b) if text[i] != "\n"]
        seg_len = len(chars)
        # 中文恒定 2 行、最多断一次；断点必须落在「非标点」之前，
        # 否则逗号/句号会被甩到下一行开头，甚至出现「，」独占一行。
        # 做法：从对半位置起，把紧跟其后的标点划回上一行末尾。
        brk = 999
        if seg_len > 11:
            k = seg_len // 2
            while k < seg_len and chars[k] in punct:
                k += 1
            if k < seg_len - 1:
                brk = k
        body, cnt, broken = [], 0, False
        for i in range(a, b):
            ch = text[i]
            if ch == "\n":
                continue
            cs = max(1, int(round((words[i]["end"] - words[i]["start"]) * 100)))
            body.append("{\\k%d}%s" % (cs, ch))
            cnt += 1
            if not broken and cnt == brk:
                body.append("\\N")
                broken = True
        # 中文块底边 1500、英文 1620：避开片头 700–1300 的示意书封，
        # 也落在参考片字幕所在的画面下三分之一（底部压黑区，白字更清楚）。
        lines.append("Dialogue: 1,%s,%s,Cn,{\\fad(240,240)\\pos(540,1500)\\an2}%s"
                     % (s_ass, e_ass, "".join(body)))
        if s.get("en"):
            e = s["en"]
            fs = 38 if len(e) <= 46 else max(26, int(38 * 46 / len(e)))
            lines.append("Dialogue: 2,%s,%s,En,{\\fad(240,240)\\pos(540,1620)\\an2\\fs%d}%s"
                         % (s_ass, e_ass, fs, e))

    lines.append("Dialogue: 1,%s,%s,Tail,{\\fad(600,600)\\pos(540,1000)\\an2}%s"
                 % (ass_time(tail_t0), t_end, job.get("tail", "")))
    lines.append("Dialogue: 1,%s,%s,Save,{\\fad(600,600)\\pos(540,1130)\\an2}%s"
                 % (ass_time(tail_t0 + 0.55), t_end, job.get("save_line", "")))
    with open(out_path, "w", encoding="utf-8-sig") as f:
        f.write(STYLE_HEAD_REF + "\n".join(lines) + "\n")
    return out_path


def build_ass(job, parts, words, text, out_path, total, beat=None):
    ens = job.get("en", [])
    lines = []
    t_end = ass_time(total)
    noir = THEME in ("noir", "vivid")
    if PHOTO_SOURCE:
        style_head = STYLE_HEAD_PHOTO
    elif THEME == "vivid":
        style_head = STYLE_HEAD_VIVID
    else:
        style_head = STYLE_HEAD_NOIR if noir else STYLE_HEAD

    # 常驻层：顶部书名作者、底部合规声明（首尾柔和淡入淡出）
    name = "《%s》" % job.get("book", "").strip().strip("《》")
    lines.append("Dialogue: 0,%s,%s,Head,{\\pos(540,220)\\an2\\fad(700,700)}%s"
                 % (ass_time(0), t_end, name))
    lines.append("Dialogue: 0,%s,%s,Author,{\\pos(540,320)\\an2\\fad(700,700)}%s"
                 % (ass_time(0), t_end, job.get("author", "")))
    lines.append("Dialogue: 0,%s,%s,Foot,{\\pos(540,1680)\\an2\\fad(700,700)}%s"
                 % (ass_time(0), t_end, "读书感悟 · 非原文摘录 · 版本以纸质书为准"))

    # 片头钩子：两行大字，柔和进出，不切卡
    hl = (job.get("hook_line") or "").split("|")
    hook_txt = "\\N".join(x.strip() for x in hl if x.strip())
    hook_end = beat["hook_end"] if beat else 4.0
    lines.append("Dialogue: 1,%s,%s,Hook,{\\fad(650,650)\\pos(540,620)\\an2}%s"
                 % (ass_time(0.2), ass_time(hook_end), hook_txt))

    punct = "，。！？；：、,.!?;:）」》】…"
    for k, p in enumerate(parts):
        if p["kind"] in ("hook", "tail"):
            continue
        a, b = p["c0"], p["c1"]
        start = max(0.0, words[a]["start"] - 0.10)
        last = words[b - 1]["end"]
        nxt = parts[k + 1]["c0"] if k + 1 < len(parts) else None
        # beat 模式：断点大字屏与末句屏占满整段留白，不再被 last+0.24 截断
        hold = bool(beat and p.get("idx") in beat.get("hold_idx", []))
        end = ((words[nxt]["start"] - 0.06) if hold else
               min(words[nxt]["start"] - 0.10, last + 0.24)) if nxt else last + 0.30
        s_ass, e_ass = ass_time(start), ass_time(max(start + 0.3, end))

        seg_len = sum(1 for i in range(a, b) if text[i] != "\n")
        # 短句单行显示更顺；>11 字才按半分两行，避免 ASS 自动折行
        brk = seg_len // 2 if seg_len > 11 else 999
        body, count = [], 0
        for i in range(a, b):
            ch = text[i]
            if ch == "\n":
                continue
            st, en = words[i]["start"], words[i]["end"]
            cs = max(1, int(round((en - st) * 100)))
            body.append("{\\k%d}%s" % (cs, ch))
            count += 1
            if count >= brk and ch not in punct and count < seg_len - 1:
                body.append("\\N")
                count = 0
        lines.append("Dialogue: 1,%s,%s,Cn,{\\fad(300,300)\\pos(540,1060)\\an2}%s"
                     % (s_ass, e_ass, "".join(body)))

        idx = p.get("idx", 0)
        en = ens[idx - 1] if 0 < idx <= len(ens) else ""
        if en:
            fs = 36 if len(en) <= 48 else max(26, int(36 * 48 / len(en)))
            lines.append("Dialogue: 2,%s,%s,En,{\\fad(300,300)\\pos(540,1200)\\an2\\fs%d}%s"
                         % (s_ass, e_ass, fs, en))

    # 片尾：去掉白底搜索条卡，只留暖光留白 + 问句 + 可截图动作
    tail_part = parts[-1]
    t0 = tail_part["t0"]
    lines.append("Dialogue: 1,%s,%s,Tail,{\\fad(750,750)\\pos(540,1000)\\an2}%s"
                 % (ass_time(t0), t_end, job.get("tail", "")))
    lines.append("Dialogue: 1,%s,%s,Save,{\\fad(750,750)\\pos(540,1130)\\an2}%s"
                 % (ass_time(t0 + (beat["save_delay"] if beat else 0.45)),
                    t_end, job.get("save_line", "")))

    with open(out_path, "w", encoding="utf-8-sig") as f:
        if noir:
            import re as _re
            _kpat = r"\{" + _re.escape(chr(92)) + r"k\d+\}"
            _out = []
            for _ln in lines:
                _ln = (_ln.replace("pos(540,1060)", "pos(540,1240)")
                          .replace("pos(540,1200)", "pos(540,1360)")
                          .replace("pos(540,1680)", "pos(540,1740)")
                          .replace("pos(540,620)", "pos(540,520)"))
                if ",Cn,{" in _ln:
                    _txt = _re.sub(r"\{[^}]*\}", "",
                                   _ln.split(",Cn,", 1)[-1]).strip()
                    if 0 < len(_txt) <= 4:
                        # 2 字大字屏：整句淡入，不逐字渐显
                        _ln = (_ln.replace(",Cn,{", ",Big,{")
                                  .replace("pos(540,1240)", "pos(540,1120)"))
                        _ln = _re.sub(_kpat, "", _ln)
                _out.append(_ln)
            lines = _out
        f.write(style_head + "\n".join(lines) + "\n")
    return out_path


def durs_from_cuts(cuts, total, xdur=1.2):
    """按「镜头切换中点」反推每段时长，让溶解正好落在文案幕节点上。

    build_base 里第 i+1 段起点 A(i+1) = sum(d[0..i]) - (i+1)*xdur，
    溶解中心 = A(i+1) + xdur/2。令它等于 cut(i+1)，即 A(i+1) = cut - xdur/2。
    """
    a = [0.0] + [float(c) - xdur / 2.0 for c in cuts]
    n = len(cuts) + 1
    durs = [a[1] + xdur]
    for i in range(1, n - 1):
        durs.append(a[i + 1] - a[i] + xdur)
    durs.append(total - a[-1])
    if min(durs) <= xdur:
        raise ValueError("镜头段过短，无法完成 %.2fs 溶解: %s"
                         % (xdur, [round(d, 2) for d in durs]))
    return durs


# ---------------------------------------------------------------- 连续底片
def build_base(pngs, durs, badge, out_path, xdur=1.2):
    """6 段底图用长交叉溶解串成一条连续镜头；片头片尾叠 AI 标识。"""
    cmd = [ffmpeg_exe(), "-y"]
    for p, d in zip(pngs, durs):
        cmd += ["-loop", "1", "-framerate", str(FPS), "-t", "%.3f" % (d + 0.2), "-i", p]
    total = sum(durs) - xdur * (len(durs) - 1)
    cmd += ["-loop", "1", "-framerate", str(FPS), "-t", "%.3f" % total, "-i", badge]

    fc = []
    for i, d in enumerate(durs):
        fc.append("[%d:v]fps=%d,scale=%d:%d,setsar=1,format=yuv420p,"
                  "trim=duration=%.3f,setpts=PTS-STARTPTS[v%d]"
                  % (i, FPS, W, H, d, i))
    bi = len(durs)
    fc.append("[%d:v]fps=%d,format=rgba,trim=duration=%.3f,setpts=PTS-STARTPTS[bd]"
              % (bi, FPS, total))
    acc = durs[0]
    prev = "v0"
    for i in range(1, len(durs)):
        off = acc - xdur
        tag = "x%d" % i
        fc.append("[%s][v%d]xfade=transition=fade:duration=%.3f:offset=%.3f[%s]"
                  % (prev, i, xdur, off, tag))
        acc = acc + durs[i] - xdur
        prev = tag
    fc.append("[%s][bd]overlay=0:0:enable='between(t,0,%.3f)+between(t,%.3f,%.3f)',"
              "format=yuv420p[vout]"
              % (prev, durs[0], total - 4.6, total + 1))
    cmd += ["-filter_complex", ";".join(fc), "-map", "[vout]",
            "-c:v", "libx264", "-preset", "medium", "-crf", "14",
            "-pix_fmt", "yuv420p", "-r", str(FPS), "-an", out_path]
    run_cmd(cmd)
    return out_path, total


# ---------------------------------------------------------------- 亮调封面
def flow_cover(job, out_path):
    vivid = THEME == "vivid"
    noir = THEME in ("noir", "vivid")
    bgf = vivid_bg if vivid else (noir_bg if noir else sun_bg)
    bg = bgf(0, variant=0)
    im = bg.crop((0, 240, 1080, 1680)).convert("RGB")
    accent = VIVID_GOLD if vivid else ORANGE
    ink = (255, 250, 238) if vivid else ((244, 245, 246) if noir else INK)
    grey = (255, 244, 232) if vivid else ((198, 200, 202) if noir else GREY)
    d = ImageDraw.Draw(im)
    name = "《%s》" % job.get("book", "").strip().strip("《》")
    # 长书名多留左右边距，避免书名号贴边
    _center(d, 150, name, _fit(d, name, F_SERIF, 104, W - 180, 58), ink)
    _center(d, 286, job.get("author", ""), _font(F_REG, 38), grey)
    d.line([(W // 2 - 88, 366), (W // 2 + 88, 366)], fill=accent, width=3)
    hl = (job.get("hook_line") or "").split("|")
    if hl:
        _center(d, 640, hl[0].strip(), _fit(d, hl[0].strip(), F_SERIF, 92, W - 120, 54), ink)
    if len(hl) > 1:
        _center(d, 774, hl[1].strip(), _fit(d, hl[1].strip(), F_SERIF, 72, W - 120, 46), ink)
    _center(d, 906, job.get("cover_sub", ""),
            _fit(d, job.get("cover_sub", ""), F_REG, 38, W - 160, 26), accent)
    _center(d, 1050, "读书感悟 · 非原文摘录", _font(F_REG, 30), grey)
    f = _font(F_BOLD, 28)
    s = "AI 生成内容"
    box = d.textbbox((0, 0), s, font=f)
    x, y = 48, 1130
    bw, bh = box[2] - box[0] + 28, box[3] - box[1] + 16
    d.rounded_rectangle([x, y, x + bw, y + bh], radius=7, fill=(250, 250, 248))
    d.rectangle([x + 6, y + 7, x + 9, y + bh - 7], fill=ORANGE)
    d.text((x + 14, y + 8 - box[1]), s, font=f, fill=(22, 26, 32))
    im.save(out_path)
    return out_path


def run_intro(job: dict):
    """参考片《停止内耗》式「介绍体」：连贯长句配音 + 短屏逐字字幕 + 连续垫乐。

    与普通 flow 的关键差别（2026-11-17 按参考片音频实测）：
      1. 配音是一整段连贯长句，不按字幕屏断句 → 没有念稿感；
      2. 字幕另切成 8–15 字短屏，逐字渐显跟 words 对齐；
      3. 句间只留 0.35s 级短停，配乐连续铺满、无断点骤停；
      4. 人声 RMS 目标 0.20（≈-14dB），比旧片 -18.9dB 更贴耳。
    """
    global THEME, SEARCH_WORD, PALETTE, PHOTO_SOURCE
    THEME = "noir"
    PALETTE = "warm"
    SEARCH_WORD = job.get("search_word", "算了")
    PHOTO_SOURCE = False
    jid = job["id"]
    print("\n=== flow | %s | 参考片式介绍体 | %s"
          % (jid, job.get("title", "")))

    import re as _re
    narr = [s.strip() for s in job["narration"].split("\n") if s.strip()]
    parts = [{"kind": "verse", "idx": i + 1, "text": s, "data": job}
             for i, s in enumerate(narr)]
    text = "\n".join(p["text"] for p in parts)
    n_chars = len(_re.sub(r"[，。！？；：、,.!?;:…\s《》]", "", text))
    print("配音文案 %d 字 / %d 段连贯长句（不按屏断句）"
          % (n_chars, len(parts)))

    wdir = ensure_dir(os.path.join(BASE, "work", jid))
    r = ttsmod.synthesize(text, wdir,
                          voice=job.get("voice") or "zh-CN-XiaoxiaoNeural",
                          rate=job.get("rate") or "+0%",
                          pitch=job.get("pitch") or "-8Hz",
                          title="", per_line=14)
    print("配音 %.1f 秒 / %.2f 字每秒"
          % (r["duration"], n_chars / r["duration"]))
    words = json.load(open(r["words"], encoding="utf-8"))["words"]
    parts = buildmod._part_times(parts, words)

    gaps = []
    for idx, sec in job.get("gaps", []):
        p = parts[int(idx)]
        gaps.append((words[p["c1"] - 1]["end"] + 0.04, float(sec)))
    pcm, words, dur_voice = beat_audio.insert_pauses(
        r["audio"], words, gaps, wdir)
    parts = buildmod._part_times(parts, words)

    screen_chars = int(job.get("screen_chars", 15))
    subs = split_screens(parts[:-1], text, screen_chars, job.get("en", []))
    tail_t0 = parts[-1]["t0"]
    print("字幕 %d 屏（每屏一句、逐字渐显 + 中英双行）" % len(subs))

    gap_map = {int(i): float(g) for i, g in job.get("gaps", [])}
    cuts = [parts[int(i)]["t1"] + gap_map.get(int(i), 0.0) / 2.0
            for i in job.get("scenes", [])]
    levels = list(job.get("levels", []))
    voice_spans = [(p["t0"], p["t1"]) for p in parts]
    bgm, gain = beat_audio.render_bgm(
        dur_voice + 1.05, cuts, levels, voice_spans, [],
        job.get("beat_gain", 0.20))
    voice_final = os.path.join(wdir, "mix.wav")
    target_rms = float(job.get("target_rms", 0.20))
    audio_total = beat_audio.mix(pcm, bgm, gain, voice_final,
                                 target_rms=target_rms)
    print("音轨 %.1f 秒 / BGM 连续铺满 / 人声目标 RMS %.2f"
          % (audio_total, target_rms))

    xdur = 1.2
    durs = durs_from_cuts(cuts, audio_total + 0.8 + 0.15, xdur)
    n_seg = len(durs)
    print("连续底片 %d 段 / 每次溶解 %.1fs" % (n_seg, xdur))

    picdir = ensure_dir(os.path.join(wdir, "bg"))
    pngs = []
    for i in range(n_seg):
        if i == 0:
            im = noir_book(noir_bg(0, variant=0), job)
        elif i == n_seg - 1:
            im = noir_bg(2, variant=5, tail=True)
        else:
            # 参考片正文以人形占屏为主，只在段间换一两次静物意象
            im = noir_bg([0, 0, 1, 0, 2][(i - 1) % 5], variant=i)
        p = os.path.join(picdir, "s%02d.png" % i)
        im.save(p)
        pngs.append(p)
    badge = os.path.join(picdir, "badge.png")
    badge_png(badge)
    base = os.path.join(wdir, "base.mp4")
    build_base(pngs, durs, badge, base, xdur=xdur)

    ass = build_ass_ref(job, subs, words, text,
                        os.path.join(wdir, "flow.ass"),
                        audio_total + 0.8, tail_t0)
    out = os.path.join(BASE, "out", "%s.mp4" % jid)
    note = ("AIGC=1; generator=WorkBuddy/PIL+edge-tts; content_id=%s; "
            "mode=flow(intro, reference-aligned narration); "
            "ai_images=self-owned; ai_voice=1; "
            "explicit_label=起始画面与片尾显著标识; "
            "publish_note=请在平台主动声明AI生成" % jid)
    compose.finalize(base, voice_final, ass, out, bgm="", bgm_gain=0.0,
                     tail=0.8, crf=14, preset="slow",
                     metadata={"comment": note})
    cover = os.path.join(BASE, "douyin", "封面_%s_参考片介绍体_3x4.png" %
                         job.get("book", "").strip().strip("《》"))
    flow_cover(job, cover)

    meta = {
        "id": jid, "title": job.get("title", ""),
        "mode": "flow(intro, reference-aligned)", "theme": "noir",
        "video": out, "cover": cover,
        "duration": round(media_duration(out), 2),
        "voice_seconds": round(dur_voice, 2),
        "screens": len(subs), "narration_chars": n_chars,
        "bgm": "连续程序化配乐（无断点骤停），内置于 mix.wav",
        "notes": ("参考片式介绍体：连贯长句配音 + 短屏逐字渐显 + 中英双行 + "
                  "顶部常驻书名作者 + 黑白人像局部亮橙 + 片头示意书封 + 片尾自制搜索条"),
        "compliance": {
            "copy": "全片文案自写，标注「读书感悟 · 非原文摘录」，不引用任何在版文本",
            "book": "《%s》%s；%s" % (job.get("book", ""), job.get("author", ""),
                    job.get("rights_note", "")),
            "images": "自有 AI 黑白人形背影剪影，无真人正脸/真实书封/品牌；未新生成任何图片",
            "fonts": "SIL OFL 1.1 开源可商用", "bgm": "程序化合成自有音频",
            "label": "片头片尾 28px 显式 AI 标识 + 隐式元数据；发布页须手动勾选 AI 声明",
        },
    }
    json.dump(meta, open(os.path.join(wdir, "meta.json"), "w",
                         encoding="utf-8"), ensure_ascii=False, indent=1)
    print("成片 %s / %.1f 秒" % (out, meta["duration"]))
    return meta


# ---------------------------------------------------------------- 主流程
def run(job: dict):
    if job.get("intro"):
        return run_intro(job)
    global THEME, SEARCH_WORD, PALETTE, PHOTO_SOURCE
    THEME = job.get("theme", "sun")
    PALETTE = job.get("palette", "warm")
    SEARCH_WORD = job.get("search_word", "算了")
    PHOTO_SOURCE = bool(job.get("photo_source", False))
    vivid = THEME == "vivid"
    noir = THEME in ("noir", "vivid")
    jid = job["id"]
    print("\n=== flow | %s | %s" % (jid, job.get("title", "")))
    parts = [{"kind": "hook", "text": job["hook"], "data": job}]
    for i, v in enumerate(job["verses"], 1):
        parts.append({"kind": "verse", "idx": i, "text": v, "data": job})
    parts.append({"kind": "tail", "text": job["tail"], "data": job})
    text = "\n".join(p["text"] for p in parts)
    print("文案 %d 字 / %d 屏（连续镜头，无分页切卡）" % (len(text), len(parts)))

    wdir = ensure_dir(os.path.join(BASE, "work", jid))
    cfg = buildmod.load_cfg()
    r = ttsmod.synthesize(text, wdir, voice=job.get("voice") or cfg["voice"],
                          rate=job.get("rate") or cfg["rate"],
                          pitch=cfg.get("pitch", "+0Hz"), title="", per_line=14)
    print("配音 %.1f 秒" % r["duration"])
    words = json.load(open(r["words"], encoding="utf-8"))["words"]
    parts = buildmod._part_times(parts, words)
    # 2026-11-17 节奏层：旧版镜头按时间平均切、BGM 是单和弦 drone。
    # beat 模式改为「句末留白 + 分幕配乐 + 幕节点切镜」，听与看同时换挡。
    xdur = 1.2
    beat_cfg = job.get("beat")
    beat = None
    voice_final = r["audio"]
    voice_seconds = r["duration"]
    if beat_cfg:
        # 1) 在原时间轴的句末插入静音，逐字时间轴同步平移
        gaps = []
        for idx, sec in beat_cfg["gaps"]:
            p = parts[int(idx)]
            gaps.append((words[p["c1"] - 1]["end"] + 0.06, float(sec)))
        pcm, words, dur_voice = beat_audio.insert_pauses(
            r["audio"], words, gaps, wdir)
        parts = buildmod._part_times(parts, words)
        voice_seconds = dur_voice

        # 2) 幕节点取「该屏念完 + 留白的一半」，镜头与配乐共用
        gap_map = {int(i): float(g) for i, g in beat_cfg["gaps"]}
        cuts = [parts[int(i)]["t1"] + gap_map.get(int(i), 0.0) / 2.0
                for i in beat_cfg["scenes"]]
        levels = list(beat_cfg["levels"])
        voice_spans = [(p["t0"], p["t1"]) for p in parts]
        impacts = [(cuts[int(i)], kind) for i, kind in beat_cfg["impacts"]]
        bgm, gain = beat_audio.render_bgm(
            dur_voice + 1.05, cuts, levels, voice_spans, impacts,
            job.get("beat_gain", 0.13))
        voice_final = os.path.join(wdir, "mix.wav")
        audio_total = beat_audio.mix(pcm, bgm, gain, voice_final)

        total_need = audio_total + 0.8 + 0.15
        durs = durs_from_cuts(cuts, total_need, xdur)
        n_seg = len(durs)
        big_idx = int(beat_cfg.get("big_idx", 0))
        beat = {"hook_end": max(1.0, parts[1]["t0"] - 0.18),
                "hold_idx": [big_idx, len(job["verses"])],
                "save_delay": float(beat_cfg.get("save_delay", 0.90))}
        print("节奏层: %d 幕 / 句间留白 %.2fs / 断点骤停 / 音轨 %.1fs"
              % (len(levels), sum(g for _, g in gaps), audio_total))
    else:
        total_need = r["duration"] + 0.8 + 1.0
        # 6 段：片头（含书封）/ 4 段不同构图的底图 / 片尾（更亮、留白）
        n_seg = int(job.get("segments", 5 if noir else 6))
        total_durs = total_need + (n_seg - 1) * xdur
        head, tail_d = 4.8, 4.4
        mid = (total_durs - head - tail_d) / (n_seg - 2)
        durs = [head] + [mid] * (n_seg - 2) + [tail_d]
    print("连续底片 %.1f 秒 / %d 段 / 每次溶解 %.1f 秒"
          % (sum(durs) - xdur * (n_seg - 1), n_seg, xdur))

    picdir = ensure_dir(os.path.join(wdir, "bg"))
    bgf = vivid_bg if vivid else (noir_bg if noir else sun_bg)
    bookf = vivid_book if vivid else (noir_book if noir else sun_book)
    pngs = []
    for i in range(n_seg):
        if i == 0:
            im = bookf(bgf(0, variant=0), job)
        elif i == n_seg - 1:
            im = bgf(1 if noir else 2, variant=5, tail=True)
        else:
            im = bgf((i - 1) % 3, variant=i)
        p = os.path.join(picdir, "s%02d.png" % i)
        im.save(p)
        pngs.append(p)
    badge = os.path.join(picdir, "badge.png")
    badge_png(badge)

    base = os.path.join(wdir, "base.mp4")
    build_base(pngs, durs, badge, base, xdur=xdur)

    ass_total = (audio_total + 0.8) if beat else (r["duration"] + 0.8)
    ass = build_ass(job, parts, words, text, os.path.join(wdir, "flow.ass"),
                    ass_total, beat=beat)
    bgm = "" if beat else verse.ensure_bgm()
    out = os.path.join(BASE, "out", "%s.mp4" % jid)
    meta_note = ("AIGC=1; generator=WorkBuddy/PIL+edge-tts; "
                 "content_id=%s; mode=%s; "
                 "ai_images=self-owned; ai_voice=1; "
                 "explicit_label=起始画面与片尾显著标识; "
                 "publish_note=请在平台主动声明AI生成"
                 % (jid, ("flow(vivid+photo, real silhouette)" if PHOTO_SOURCE
                          else "flow-like(vivid, high-saturation)") if vivid
                    else ("flow-like(noir, reference-aligned)" if noir
                          else "flow(continuous, no page cuts)")))
    if PHOTO_SOURCE:
        meta_note = meta_note.replace(
            "ai_images=self-owned", "ai_images=0; photos=Pexels-licensed")
    compose.finalize(base, voice_final, ass, out, bgm=bgm,
                     bgm_gain=job.get("bgm_gain", 0.12), tail=0.8,
                     crf=14, preset="slow",
                     metadata={"comment": meta_note})

    cover = os.path.join(BASE, "douyin", "封面_%s_%s_3x4.png" %
                         (job.get("book", "").strip().strip("《》"),
                          ("实拍版·节奏版" if beat_cfg else "实拍版")
                          if PHOTO_SOURCE else
                          ("艳丽版" if vivid else ("对标版" if noir else "阳光版"))))
    flow_cover(job, cover)

    meta = {
        "id": jid, "title": job.get("title", ""),
        "mode": "flow-like(noir)" if noir else "flow",
        "theme": THEME,
        "video": out, "cover": cover,
        "duration": round(media_duration(out), 2),
        "voice_seconds": round(voice_seconds, 2),
        "screens": len(parts),
        "bgm": ("分幕程序化配乐 Am-F-C-G（内置于 mix.wav）" if beat
                else os.path.basename(bgm)),
        "notes": ("连续镜头：长交叉溶解；Pexels 实拍人形剪影 + 高饱和柔光层 + 留白过渡，白字亮金"
                  if PHOTO_SOURCE else
                  "连续镜头：长交叉溶解，无切卡黑帧/无页码/无搜索条 UI"),
        "compliance": {
            "copy": "全片文案自写，标注「读书感悟 · 非原文摘录」，不引用任何在版文本",
            "book": "《%s》%s；%s" % (job.get("book", ""), job.get("author", ""),
                    job.get("rights_note", "")),
            "images": ("Pexels 免费可商用实拍图（背影/剪影、无真人正脸）7 张 + "
                       "高饱和渐变柔光 3 张，无真实书封/品牌；本片未新生成任何 AI 图"
                       if PHOTO_SOURCE else
                       "3 张自有 AI 静物图，无真人正脸/真实书封/品牌；未新生成任何图片"),
            "fonts": "SIL OFL 1.1 开源可商用", "bgm": "程序化合成自有音频",
            "platform": "片尾已移除白底搜索条卡，无任何平台 UI / 他人水印",
            "aigc": "片头与片尾左下角 28px 白底黑字显著标识 + 文件元数据隐式 AIGC 字段",
            "publish": "发布时仍须使用平台提供的 AI 标识功能主动声明",
        },
    }
    json.dump(meta, open(os.path.join(wdir, "meta.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print("成片: %s (%.1f 秒)" % (out, meta["duration"]))
    print("封面: %s" % cover)
    return meta


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: python scripts/flow.py queue/flow-xxx.json")
        sys.exit(1)
    run(json.load(open(sys.argv[1], encoding="utf-8")))
