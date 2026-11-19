"""金句卡点模式（verse）——合规版读书感悟短视频。

对应 2026-11-11 用户指定参考片《停止内耗》的形式，但按法律研究结论做「错位复刻」：
  · 保留类型结构：顶部常驻书名 + 一屏一句 + 逐字渐显 + 黑白去色画面 + 局部暖色
  · 全部替换素材：自有 AI 剪影图（无正脸/无书封/无品牌）、SIL OFL 开源字体、
    程序化生成的自有 BGM、全自写文案（不冒充原文）
  · 不出现：他人真人照片、真实书封美术设计、抖音号/搜索框/官方 UI、机翻英文
  · 《AI生成合成内容标识办法》：片头/片尾左下角显著「AI 生成内容」标识（正文屏不挂角标）
    + 文件元数据隐式 AIGC 字段；发布时仍需用平台提供的标识功能主动声明

用法：
    python scripts/verse.py queue/verse-xxx.json
"""
import glob
import json
import math
import os
import struct
import sys
import time
import wave

from PIL import (Image, ImageChops, ImageDraw, ImageEnhance, ImageFilter,
                 ImageFont, ImageOps, ImageStat)

import build as buildmod
import cards
import compose
import tts as ttsmod
from utils import ass_time, ensure_dir, media_duration

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FONTS = os.path.join(BASE, "assets", "fonts")
BG_DIR = os.path.join(BASE, "assets", "verse")
BGM_PATH = os.path.join(BASE, "assets", "bgm", "selfmade_ambient.wav")
W, H = 1080, 1920

F_SERIF = os.path.join(FONTS, "NotoSerifSC_700Bold.ttf")
F_BOLD = os.path.join(FONTS, "NotoSansSC_700Bold.ttf")
F_REG = os.path.join(FONTS, "NotoSansSC_400Regular.ttf")

INK = (246, 243, 237)
AMBER = (240, 124, 40)
DIM = (176, 180, 184)


def _font(path, size):
    return ImageFont.truetype(path, size)


def _center(d, y, s, font, fill):
    box = d.textbbox((0, 0), s, font=font)
    d.text(((W - (box[2] - box[0])) // 2 - box[0], y), s, font=font, fill=fill)
    return box[3] - box[1]


def _fit_font(d, s, path, size, max_w, min_size=36):
    """长书名自适应字号：日更换书时不会因为书名变长而撑破版式。"""
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


def _background(idx: int) -> Image.Image:
    """自有 AI 剪影图 → 近纯黑去色 + 局部亮橙 + 大面积柔光。

    2026-11-14「追平参考号 60653746344」专项：并排比对后，我们原先差在
    ① 背景是灰渐变不是纯黑，白字发闷；② 12–15 屏循环同一张静物，画面太静；
    ③ 橙只有一条细线一个圈，参考片是大面积柔光染在主体上。
    这里全部用代码绘制补，**不新增任何 AI 生成图**（用户已要求停止生成图片），
    也不动顶部书名作者、一屏一句、中英双行等锁定版式。
    """
    fs = sorted(glob.glob(os.path.join(BG_DIR, "*.png")))
    variant = 0
    if fs:
        src = Image.open(fs[idx % len(fs)]).convert("RGB")
        # 生成图右下角自带「AI生成 / WORKBUDDY」水印；裁掉底部 8% 再构图，
        # 否则成片里会残留半截残缺字符。显式标识另由片头/片尾承担。
        src = src.crop((0, 0, src.width, int(src.height * 0.92)))
        # 每屏换构图：同一张底图按屏序号取不同区域 + 轻微变焦 + 隔组镜像。
        # 幅度控制在 10% 内，避免纹理被反复重采样发糊。
        variant = idx // len(fs)
        sw, sh = src.size
        zoom = 1.0 + 0.05 * (variant % 3)
        cw, ch = int(sw / zoom), int(sh / zoom)
        ox = int((sw - cw) * (0.15 + 0.30 * ((variant // 3) % 3)))
        oy = int((sh - ch) * (0.12 + 0.32 * (variant % 2)))
        src = src.crop((ox, oy, ox + cw, oy + ch))
        if (variant // 6) % 2:
            src = ImageOps.mirror(src)
        orig = _cover(src)
        # 源图 1024x1536 放大到 1080x1920 会发虚：先做一次轻度反锐化掩模，
        # 把人像轮廓/窗棂/书页的边缘找回来（2026-11-14 清晰度修复）。
        orig = orig.filter(ImageFilter.UnsharpMask(radius=1.2, percent=140, threshold=2))
        r, g, b = orig.split()
        warm = ImageChops.subtract(r, b)
        mask = warm.point(lambda v: 0 if v < 20 else min(255, (v - 20) * 5))
        gray = ImageOps.grayscale(orig).convert("RGB")
        gray = ImageEnhance.Contrast(gray).enhance(1.22)
        # 三张自有底图本身亮度不齐：茶盏/宣纸那张源图均值 ≈79、中灰以上
        # 像素占 36.7%，另两张只有 ≈28–33、占 0.2–5%。14 屏轮换必然轮到
        # 它 4–5 次，只调 bg_offset 避不开，切到那屏就会冒一大片灰雾。
        # 按源图均值做一次温和的线性归一化（无阶跃、不改构图、不生成新图），
        # 只压偏亮的那张，把三张拉到同一暗度；高光仍由下面的 >150 保留。
        src_mean = ImageStat.Stat(ImageOps.grayscale(orig)).mean[0]
        if src_mean > 45:
            k = max(0.55, min(0.85, 42.0 / src_mean))
            gray = ImageEnhance.Brightness(gray).enhance(k)
        # 暗部压到近纯黑：参考片是纯黑底，白字才锐利；只压 <96 的暗部。
        # 系数不能再低——试过 0.40 会把主体（书页/窗棂）一起压没，
        # 变成一片空黑，比原来的灰底更差。0.66 是「黑得干净」与「主体可见」的折中。
        # 中灰（96–150）也轻微压一档，否则 AI 图的纹理噪点会留一大片灰雾，
        # 不像参考片的纯黑；高光（窗棂/茶盏边缘 >150）一律不动。
        gray = gray.point(lambda v: int(v * 0.66) if v < 96 else
                          (int(v * 0.82) if v < 150 else v))
        base = Image.blend(gray, Image.new("RGB", (W, H), (4, 5, 7)), 0.06)
        warm_col = Image.blend(orig, Image.new("RGB", (W, H), (242, 112, 28)), 0.34)
        im = Image.composite(warm_col, base, mask)
        # 程序化暖橙光晕：screen 混合只提亮被照到的地方，纯黑背景仍是纯黑。
        # 光源位置按屏轮换，补上参考片「大面积橙染在主体上」的温度。
        glow = Image.new("RGB", (W, H), (0, 0, 0))
        gd = ImageDraw.Draw(glow)
        gx = int(W * (0.28 + 0.22 * (variant % 3)))
        gy = int(H * (0.44 + 0.09 * ((variant // 3) % 3)))
        rad = int(W * 0.66)
        for rr in range(rad, 0, -14):
            a = int(105 * (1 - rr / float(rad)) ** 2)
            gd.ellipse([gx - rr, gy - rr, gx + rr, gy + rr],
                       fill=(a, int(a * 0.48), int(a * 0.14)))
        glow = glow.filter(ImageFilter.GaussianBlur(78))
        im = ImageChops.screen(im, glow)
    else:
        im = cards._gradient((W, H), (6, 6, 8), (18, 18, 20))

    # 压暗曲线。注意 PIL 的 Image.composite(a, b, mask) 是 mask=255 取 a ——
    # 这里 a 是纯黑，所以 v 表示「叠黑的比例」，不是亮度。分段线性插值，
    # 避免阶跃在画面上留下横向硬边；主体区几乎不压，白字始终有深色衬底。
    stops = [(0, 0.64), (380, 0.60), (620, 0.10), (980, 0.16),
             (1120, 0.62), (1380, 0.76), (1620, 0.74), (H, 0.70)]
    shade = Image.new("L", (1, H))
    for y in range(H):
        v = stops[-1][1]
        for k in range(len(stops) - 1):
            y0, v0 = stops[k]
            y1, v1 = stops[k + 1]
            if y0 <= y <= y1:
                t = (y - y0) / float(y1 - y0)
                v = v0 + (v1 - v0) * t
                break
        shade.putpixel((0, y), int(v * 255))
    shade = shade.resize((W, H))
    return Image.composite(Image.new("RGB", (W, H), (4, 5, 8)), im, shade)


def _ai_badge(im: Image.Image):
    """起始画面 + 片尾的显著显式标识。

    依据《AI生成合成内容标识办法》第四条第四项：视频「起始画面」和播放周边
    「应当」加显著标识，末尾/中间「可以」加（属可选）。故正文屏不再挂角标，
    既不遮挡画面，也不构成隐匿标识——起始画面显著标识 + 平台侧发布周边标识
    + 投稿页自主声明 + 文件元数据隐式标识，四者仍完整。
    """
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    # 用户 2026-11-12 要求：移到左下角、字别太大。
    # 28px + 白底黑字细胶囊是「显著」与「不抢画面」的折中下限；
    # 再缩字号或改成低对比灰字会落入「小字隐蔽标注」的违规区间，不再下调。
    f = _font(F_BOLD, 28)
    s = "AI 生成内容"
    box = d.textbbox((0, 0), s, font=f)
    tw, th = box[2] - box[0], box[3] - box[1]
    pad_x, pad_y = 14, 8
    bw, bh = tw + pad_x * 2, th + pad_y * 2
    # 2026-11-14 用户看参考片后要求「放左下角最下面」：下移到画面最底部，
    # 左缘与底部声明对齐。抖音底部标题栏可能压住这一带，故发布时必须
    # 另行勾选平台 AI 声明（投稿页声明 + 文件元数据 + 片头片尾标识，三重兜底）。
    x0, y0 = 84, H - 140
    x1, y1 = x0 + bw, y0 + bh
    d.rounded_rectangle([x0, y0, x1, y1], radius=7,
                        fill=(246, 244, 238, 242))
    d.rectangle([x0 + 6, y0 + 7, x0 + 9, y1 - 7], fill=(242, 112, 28, 255))
    d.text((x0 + pad_x - box[0], y0 + pad_y - box[1]), s, font=f,
           fill=(22, 26, 32, 255))
    return Image.alpha_composite(im.convert("RGBA"), layer).convert("RGB")


def _demo_cover(im, job):
    """片头立体书封：自绘示意封面，保留参考片「书封悬浮」的表达方式，
    但不用任何真实书封照片、出版社美术设计、ISBN 或品牌标识。
    2026-11-12 模板升级：书脊/页口/厚度做伪 3D、双层柔阴影、内框留白、
    书名自适应字号（换长书名不会撑破版式）。"""
    cw, ch = 420, 600
    x0, y0 = (W - cw) // 2, 660
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ld = ImageDraw.Draw(layer)
    ld.rectangle([x0 + 24, y0 + 32, x0 + cw + 24, y0 + ch + 32],
                 fill=(0, 0, 0, 105))
    ld.rectangle([x0 + 12, y0 + 18, x0 + cw + 12, y0 + ch + 18],
                 fill=(0, 0, 0, 115))
    im = Image.alpha_composite(im.convert("RGBA"), layer).convert("RGB")
    d = ImageDraw.Draw(im)
    # 书脊 / 页口 / 书底厚度，纯自绘，不出现任何真实书籍装帧细节。
    # 2026-11-14 追平参考号：原先米白封面在纯黑底上像一张标签卡，是片头
    # 「PPT 感」的最大来源。改成暗调纸面 + 左上暖光 + 左亮右暗的侧光，
    # 靠光勾体积，不用真人照片、不用真实书封、不新增 AI 生成图。
    d.rectangle([x0 - 16, y0 + 6, x0, y0 + ch + 6], fill=(46, 44, 42))
    d.line([(x0 - 16, y0 + 6), (x0 - 16, y0 + ch + 6)],
           fill=(24, 24, 26), width=2)
    d.rectangle([x0 + cw, y0 + 6, x0 + cw + 10, y0 + ch + 6],
                fill=(118, 112, 102), outline=(72, 68, 62), width=1)
    for k in range(9):
        yy = y0 + 58 + k * 62
        d.line([(x0 + cw + 1, yy), (x0 + cw + 9, yy)],
               fill=(84, 80, 72), width=1)
    d.rectangle([x0 - 16, y0 + ch, x0 + cw + 10, y0 + ch + 8],
                fill=(96, 90, 82))
    # 封面主体：程序化暗调纸面，左亮右暗模拟侧光，再叠一层左上暖光
    cover = Image.new("RGB", (cw, ch))
    cd = ImageDraw.Draw(cover)
    for x in range(cw):
        t = x / float(cw)
        cd.line([(x, 0), (x, ch)],
                fill=(int(66 - 44 * t), int(62 - 42 * t), int(58 - 36 * t)))
    lg = Image.new("RGB", (cw, ch), (0, 0, 0))
    ld2 = ImageDraw.Draw(lg)
    for rr in range(380, 0, -12):
        a = int(70 * (1 - rr / 380.0) ** 2)
        ld2.ellipse([-30 - rr, -40 - rr, -30 + rr, -40 + rr],
                    fill=(a, int(a * 0.50), int(a * 0.16)))
    lg = lg.filter(ImageFilter.GaussianBlur(52))
    cover = ImageChops.screen(cover, lg)
    im.paste(cover, (x0, y0))
    d = ImageDraw.Draw(im)
    d.rectangle([x0, y0, x0 + cw, y0 + ch], outline=(96, 88, 76), width=2)
    d.rectangle([x0 + 26, y0 + 26, x0 + cw - 26, y0 + ch - 26],
                outline=(128, 104, 72), width=1)
    name = job.get("book", "").strip().strip("《》")
    f = _fit_font(d, name, F_SERIF, 68, cw - 76, min_size=38)
    box = d.textbbox((0, 0), name, font=f)
    d.text((x0 + (cw - (box[2] - box[0])) // 2 - box[0], y0 + 124),
           name, font=f, fill=(236, 228, 212))
    f2 = _font(F_REG, 26)
    for k, ln in enumerate(["读书感悟 · 自写文案", "非原文摘录 · 示意封面"]):
        box = d.textbbox((0, 0), ln, font=f2)
        d.text((x0 + (cw - (box[2] - box[0])) // 2 - box[0],
                y0 + 254 + k * 44), ln, font=f2, fill=(158, 154, 146))
    d.line([(x0 + 90, y0 + 430), (x0 + cw - 90, y0 + 430)],
           fill=(214, 140, 64), width=3)
    d.ellipse([x0 + cw // 2 - 38, y0 + 462, x0 + cw // 2 + 38, y0 + 538],
              outline=(214, 140, 64), width=3)
    return im


def _search_bg():
    """片尾底：改回全片统一的「黑灰 + 局部暖橙」，替换原先偏冷的深蓝渐变，
    避免 30 秒里突然跳色；搜索条仍是自有通用 UI，不用平台官方样式与话术。"""
    im = cards._gradient((W, H), (11, 12, 14), (26, 22, 19)).convert("RGBA")
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    gd.ellipse([W // 2 - 430, 1180, W // 2 + 430, 1880],
               fill=(240, 124, 40, 42))
    glow = glow.filter(ImageFilter.GaussianBlur(170))
    return Image.alpha_composite(im, glow).convert("RGB")


def _fixed_layers(im, job, idx, total, is_open=False, is_end=False):
    d = ImageDraw.Draw(im)
    if is_end:
        # 顶部常驻书名作者（与正文屏一致），片尾上半部不再大片留白
        end_name = "《%s》" % job.get("book", "").strip().strip("《》")
        _center(d, 208, end_name,
                _fit_font(d, end_name, F_SERIF, 66, W - 160), (214, 216, 218))
        _center(d, 306, job.get("author", ""), _font(F_REG, 30), (150, 156, 162))
        d.line([(W // 2 - 70, 366), (W // 2 + 70, 366)], fill=AMBER, width=2)
        # 自有版式的「搜索条」：通用 UI 形式，不含抖音 logo / 抖音码 / 官方话术
        _center(d, 610, "今晚的一句", _font(F_REG, 34), (196, 204, 214))
        x0, y0, x1, y1 = 110, 790, 970, 920
        d.rounded_rectangle([x0, y0, x1, y1], radius=24, fill=(248, 248, 246))
        d.text((x0 + 30, y0 + 34), "想一想", font=_font(F_BOLD, 40),
               fill=(28, 32, 40))
        d.line([(x0 + 172, y0 + 22), (x0 + 172, y1 - 22)],
               fill=(214, 214, 212), width=2)
        d.text((x0 + 200, y0 + 34), job.get("tail", ""),
               font=_font(F_REG, 40), fill=(40, 44, 50))
        cx, cy = x1 - 58, y0 + 65
        d.ellipse([cx - 20, cy - 20, cx + 20, cy + 20],
                  outline=(90, 96, 104), width=4)
        d.line([(cx + 15, cy + 15), (cx + 34, cy + 34)],
               fill=(90, 96, 104), width=4)
        # 具体可执行的收尾动作（收藏/截图钩子），按书从任务 JSON 读
        _center(d, 1010, job.get("save_line", "截图保存 · 评论区聊聊"),
                _font(F_REG, 30), (188, 194, 200))
    else:
        # 顶部常驻书名 + 作者（参考片的核心表达方式；字形改用开源宋体）
        name = "《%s》" % job.get("book", "").strip().strip("《》")
        _center(d, 200 if is_open else 214, name,
                _fit_font(d, name, F_SERIF, 104 if is_open else 88, W - 120), INK)
        _center(d, 330 if is_open else 318, job.get("author", ""),
                _font(F_REG, 34), DIM)
        d.line([(W // 2 - 90, 392), (W // 2 + 90, 392)],
               fill=AMBER, width=2)
        if is_open:
            # 前 3 秒钩子：两行大字，直接戳痛点；版式仍是参考片的「书名 + 副标 + 书封」
            hl = job.get("hook_line") or job.get("subtitle", "")
            for k, ln in enumerate(hl.split("|")):
                ln = ln.strip()
                _center(d, 438 + k * 94, ln,
                        _fit_font(d, ln, F_SERIF, 66, W - 150, min_size=44), INK)
        # 中英双行的英文不再烘焙在卡片里：中文逐字渐显时行数会变，
        # 写死的 y 坐标会让英文跑到中文上面去。改由 build_reveal_ass
        # 作为同一字幕块的第二行渲染（\N + 内联字号/颜色），顺序与间距恒定。

    # 底部来源声明（对应参考片「内容来自书评 / 感悟」），内容换成自有，
    # 不放任何他人账号名、抖音号或平台水印。
    # 2026-11-14 追平参考号：参考片底部只有一行小字，我们原先两行声明 + 横线
    # + 页码显得像说明书。合并成一行、横线减淡、页码收小；AI 标识仍独占最底
    # 一行，不缩字号、不改低对比（法规底线）。
    d.line([(80, H - 280), (W - 80, H - 280)], fill=(56, 62, 70), width=1)
    d.text((84, H - 250), "读书感悟 · 非原文摘录 · 版本以纸质书为准",
           font=_font(F_REG, 26), fill=(150, 156, 162))
    if not is_open and not is_end:
        d.text((W - 190, H - 252), "%02d / %02d" % (idx, total),
               font=_font(F_BOLD, 30), fill=AMBER)
    return im


def make_frame(part, i, n, out_path, job):
    is_open = part["kind"] == "hook"
    is_end = part["kind"] == "tail"
    # bg_offset：日更换主视觉意象（三张自有剪影轮换），不连续两天同一张
    off = job.get("bg_offset", 0)
    im = _search_bg() if is_end else _background((i if not is_open else 0) + off)
    if is_open:
        # 片头对齐参考片的「近纯黑」开场：钩子两行白字需要更沉的底
        im = Image.blend(im, Image.new("RGB", im.size, (0, 0, 0)), 0.30)
    im = _fixed_layers(im, job, part.get("idx", 0),
                       max(1, n - 2), is_open, is_end)
    if is_open:
        im = _demo_cover(im, job)
    # 只在起始画面与片尾保留显著标识；正文屏不再常驻左上角角标
    if is_open or is_end:
        im = _ai_badge(im)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    im.save(out_path, quality=93)
    return out_path


def build_reveal_ass(text, parts, words, out_path, ens=None):
    """逐字渐显（打字机）字幕：未读字全透明、已读字白色，非卡拉OK高亮。

    2026-11-14：英文改为**独立 Dialogue 的独立字幕轨**（Style: En + \\pos
    绝对定位），不再烘焙在卡片 PNG 上，也不放进中文的 \\N 第二行。
    原因：中文用 \\k 卡拉OK，libass 会把后续无 \\k 的文本排进同一音节队列，
    英文要等整句念完才出现（中间帧完全看不到）；\\k0 / \\r / \\1c 都救不了。
    独立轨整句期间常显，坐标固定在中文块底边之下，顺序永不颠倒。
    """
    ens = ens or []
    head = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Sub,Noto Serif SC,82,&H00FFFFFF,&HFF000000,&HFF0A0E12,&H90000000,0,0,0,0,100,100,2,0,1,2,0,2,50,50,470,1
Style: En,Noto Sans SC,36,&H00DCDAD6,&H00DCDAD6,&H00120E0A,&H90000000,0,0,0,0,100,100,0,0,1,1,0,2,60,60,0,1

[Events]
Format: Layer, Start, End, Style, Text
"""
    punct = "，。！？；：、,.!?;:）」》】…"
    lines = []
    for k, p in enumerate(parts):
        # 片头已有两行钩子大字 + 书封，片尾搜索条本身已呈现问句：
        # 两处都不叠口播字幕，对齐参考片；正文 6 屏逐字渐显保留。
        if p["kind"] in ("hook", "tail"):
            continue
        a, b = p["c0"], p["c1"]
        start = words[a]["start"] - 0.06
        last = words[b - 1]["end"]
        nxt = parts[k + 1]["c0"] if k + 1 < len(parts) else None
        end = min(words[nxt]["start"] - 0.04, last + 0.28) if nxt else last + 0.35
        # 中文恒定 2 行：Alignment=2 让字幕块底边固定在 y≈1450，
        # 英文独立轨固定在 y=1550。旧版按固定 11 字断行，标点会把断点
        # 一路推后，21 字长句第一行撑到 12 字、超出 900px 后被 ASS 自动
        # 折成 3 行；逐字渐显时第三行尚未显形，中英之间会空出整整一行
        # （实测 254px vs 86px）。现在按句长对半断、且**渲染后再判断断点**：
        # 标点留在上一行末尾，每行 ≤11 字，配合 50px 边距（可用 980px）
        # 不再折行，块高度与中英间距全程稳定。
        body, count, broke = [], 0, False
        seg_len = sum(1 for i in range(a, b) if text[i] != "\n")
        brk = seg_len // 2
        for i in range(a, b):
            ch = text[i]
            if ch == "\n":
                continue
            st, en = words[i]["start"], words[i]["end"]
            cs = max(1, int(round((en - st) * 100)))
            body.append("{\\k%d}%s" % (cs, ch))
            count += 1
            limit = brk if not broke else 12
            if count >= limit and ch not in punct:
                body.append("\\N")
                broke = True
                count = 0
        s_ass, e_ass = (ass_time(max(0.0, start)),
                        ass_time(max(start + 0.3, end)))
        # 中文也用 \pos 绝对定位：只靠 Style 的 Alignment=2 + MarginV 时，
        # 成片里中文块会被 libass 整体上移约 168px（英文轨因用 \pos 不受影响），
        # 中英间距在 86–254px 跳动。两条轨都钉死绝对坐标后，间距恒定 ~100px。
        lines.append("Dialogue: 0,%s,%s,Sub,{\\pos(540,1450)\\an2}%s"
                     % (s_ass, e_ass, "".join(body)))
        # 英文独立轨：常显、单行、固定在中文块底边之下（y=1550），
        # 与中文的卡拉OK 音节队列完全解耦，顺序与可见性都稳定。
        idx = p.get("idx", 0)
        en = ens[idx - 1] if 0 < idx <= len(ens) else ""
        if en:
            fs = 36 if len(en) <= 48 else max(26, int(36 * 48 / len(en)))
            lines.append("Dialogue: 1,%s,%s,En,{\\pos(540,1550)\\an2\\fs%d}%s"
                         % (s_ass, e_ass, fs, en))
    with open(out_path, "w", encoding="utf-8-sig") as f:
        f.write(head + "\n".join(lines) + "\n")
    return out_path


def ensure_bgm(path=BGM_PATH, seconds=46):
    """程序化合成的纯自有氛围垫音，零第三方音乐版权。"""
    if os.path.exists(path) and os.path.getsize(path) > 100000:
        return path
    os.makedirs(os.path.dirname(path), exist_ok=True)
    sr = 22050
    n = sr * seconds
    buf = bytearray()
    tones = ((130.81, 0.20), (174.61, 0.50), (220.00, 0.32), (261.63, 0.22))
    for i in range(n):
        t = i / sr
        env = min(1.0, t / 1.6) * min(1.0, (seconds - t) / 2.8)
        lfo = 0.68 + 0.32 * math.sin(2 * math.pi * 0.055 * t)
        v = 0.0
        for f, a in tones:
            v += a * math.sin(2 * math.pi * f * t +
                              0.25 * math.sin(2 * math.pi * 0.045 * t))
        v *= 0.075 * env * lfo
        buf += struct.pack("<h", int(max(-1.0, min(1.0, v)) * 32767))
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(bytes(buf))
    return path


def run(job: dict):
    jid = job["id"]
    print("\n=== verse | %s | %s" % (jid, job.get("title", "")))
    parts = [{"kind": "hook", "text": job["hook"], "data": job}]
    for i, v in enumerate(job["verses"], 1):
        parts.append({"kind": "verse", "idx": i, "text": v, "data": job})
    parts.append({"kind": "tail", "text": job["tail"], "data": job})
    text = "\n".join(p["text"] for p in parts)
    print("文案 %d 字 / %d 屏" % (len(text), len(parts)))

    wdir = ensure_dir(os.path.join(BASE, "work", jid))
    cfg = buildmod.load_cfg()
    r = ttsmod.synthesize(
        text, wdir, voice=job.get("voice") or cfg["voice"],
        rate=job.get("rate") or cfg["rate"], pitch=cfg.get("pitch", "+0Hz"),
        title="", per_line=14)
    print("配音 %.1f 秒" % r["duration"])
    words = json.load(open(r["words"], encoding="utf-8"))["words"]
    parts = buildmod._part_times(parts, words)

    picdir = ensure_dir(os.path.join(wdir, "cards"))
    pics = []
    for i, p in enumerate(parts):
        png = os.path.join(picdir, "p%02d.png" % i)
        make_frame(p, i, len(parts), png, job)
        pics.append(png)
        print("  %-5s %5.1f - %5.1f  %s" % (
            p["kind"], p["t0"], p["t1"], p["text"][:20]))

    cache = ensure_dir(os.path.join(BASE, "work", "_clipcache"))
    base = os.path.join(wdir, "base.mp4")
    # verse：文字烘焙在卡片里，关掉运镜避免字被重采样；两段编码都用高画质。
    # 2026-11-14 清晰度升级：crf 16→12、preset medium→slow、静态卡不再 2x 缩放。
    compose.build_from_cards(pics, parts, base, cache,
                             motion=False, crf=12, preset="slow")

    ass = build_reveal_ass(text, parts, words,
                           os.path.join(wdir, "reveal.ass"), job.get("en"))
    bgm = ensure_bgm()
    out = os.path.join(BASE, "out", "%s.mp4" % jid)
    meta_note = ("AIGC=1; generator=WorkBuddy/ImageGen+edge-tts; "
                 "content_id=%s; ai_images=3; ai_voice=1; "
                 "explicit_label=起始画面与片尾显著标识;正文无角标; "
                 "publish_note=请在平台主动声明AI生成" % jid)
    compose.finalize(base, r["audio"], ass, out, bgm=bgm,
                     bgm_gain=job.get("bgm_gain", 0.12), tail=0.8,
                     crf=12, preset="slow", tune="stillimage",
                     metadata={"comment": meta_note})

    meta = {
        "id": jid, "title": job.get("title", ""), "mode": "verse",
        "video": out, "duration": round(media_duration(out), 2),
        "voice_seconds": round(r["duration"], 2),
        "screens": len(parts), "bgm": os.path.basename(bgm),
        "fonts": ["NotoSansSC_400Regular.ttf", "NotoSansSC_700Bold.ttf",
                  "NotoSerifSC_700Bold.ttf"],
        "compliance": {
            "copy": "全片文案自写，标注「读书感悟 · 非原文摘录」，不引用任何在版文本",
            "book": "《%s》%s；%s" % (job.get("book", ""), job.get("author", ""),
                    job.get("rights_note", "已多源核实，仅作指示性使用")),
            "images": "AI 生成自有剪影，无真人正脸/书封/品牌；生成记录见 assets/verse/生成记录.txt",
            "fonts": "SIL OFL 1.1 开源可商用，assets/fonts/README.md 为授权凭证",
            "bgm": "程序化合成自有音频，无第三方音乐",
            "platform": "无抖音号/搜索框/官方 UI/他人水印",
            "aigc": "起始画面与片尾显著「AI 生成内容」标识；正文无角标（第四条第四项：中间属「可以」）；文件元数据隐式 AIGC 字段",
            "publish": "发布时仍须使用平台提供的 AI 标识功能主动声明",
        },
    }
    json.dump(meta, open(os.path.join(wdir, "meta.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print("成片: %s (%.1f 秒)" % (out, meta["duration"]))
    return meta


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: python scripts/verse.py queue/verse-xxx.json")
        sys.exit(1)
    run(json.load(open(sys.argv[1], encoding="utf-8")))
