# -*- coding: utf-8 -*-
"""生成抖音发布封面（3:4）+ 1:1 裁切预览。

用法：python scripts/cover.py queue/verse-xxx.json

日更换书时直接跑本脚本，字段全部从任务 JSON 读，不再手写死文案：
  book / author / hook_line / cover_sub / title
所有关键信息压在 1:1 安全区（y 180–1260）内，3:4 与 1:1 裁切都不丢。
"""
import io
import json
import os
import sys

from PIL import Image, ImageDraw, ImageFont

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, "scripts"))
import verse  # noqa: E402  复用同一套底图与配色

W, H = 1080, 1440
FD = os.path.join(BASE, "assets", "fonts")
WHITE, DIM, ORANGE = (242, 242, 240), (168, 174, 180), (240, 96, 14)


def _f(name, size):
    return ImageFont.truetype(os.path.join(FD, name), size)


def _fit(d, s, name, size, max_w, min_size=36):
    """长书名/长钩子自适应字号：日更换书不会撑破 3:4 与 1:1 安全区。"""
    f = _f(name, size)
    while size > min_size:
        box = d.textbbox((0, 0), s, font=f)
        if box[2] - box[0] <= max_w:
            break
        size -= 3
        f = _f(name, size)
    return f


def build(job):
    # 3:4 取自 9:16 底图中段；底图已去色 + 局部橙 + 分段压暗。
    # 2026-11-14 底图主体区提亮后，封面再叠一层轻暗罩，保证白字仍压得住画面。
    bg = verse._background(job.get("bg_offset", 0))
    im = bg.crop((0, 240, 1080, 1680)).convert("RGB")
    im = Image.blend(im, Image.new("RGB", im.size, (0, 0, 0)), 0.38)
    d = ImageDraw.Draw(im)

    def center(y, txt, font, fill):
        box = d.textbbox((0, 0), txt, font=font)
        d.text(((W - (box[2] - box[0])) / 2 - box[0], y), txt,
               font=font, fill=fill)

    f_author = _f("NotoSansSC_400Regular.ttf", 40)
    f_note = _f("NotoSansSC_400Regular.ttf", 30)
    f_ai = _f("NotoSansSC_700Bold.ttf", 28)
    serif = "NotoSerifSC_700Bold.ttf"
    sans = "NotoSansSC_400Regular.ttf"

    book_txt = "《%s》" % job["book"].strip().strip("《》")
    center(230, book_txt, _fit(d, book_txt, serif, 112, W - 120, 64), WHITE)
    center(370, job.get("author", ""), f_author, DIM)
    d.line([(W // 2 - 90, 440), (W // 2 + 90, 440)], fill=ORANGE, width=3)

    hl = (job.get("hook_line") or "").split("|")
    h1 = hl[0].strip() if hl else ""
    h2 = hl[1].strip() if len(hl) > 1 else ""
    center(750, h1, _fit(d, h1, serif, 96, W - 120, 56), WHITE)
    if h2:
        center(890, h2, _fit(d, h2, serif, 72, W - 120, 48), WHITE)
    sub = job.get("cover_sub", "")
    center(1040, sub, _fit(d, sub, sans, 38, W - 160, 26), ORANGE)
    center(1210, "读书感悟 · 非原文摘录", f_note, DIM)

    # 显著显式 AI 标识：左下角，白底黑字 + 橙竖条，字号 28px。
    # 视频里已按用户要求放到 H-140（贴最底部）；封面受 1:1 安全区下沿 1260
    # 限制，且 y=1180 会与底部声明挤在一起，故回到 1130（仍是左下角靠下位置）。
    label = "AI 生成内容"
    box = d.textbbox((0, 0), label, font=f_ai)
    bw, bh = box[2] - box[0] + 28, box[3] - box[1] + 16
    x, y = 48, 1130
    d.rounded_rectangle([x, y, x + bw, y + bh], radius=7, fill=(250, 250, 250))
    d.rectangle([x + 6, y + 7, x + 9, y + bh - 7], fill=ORANGE)
    d.text((x + 14, y + 8 - box[1]), label, font=f_ai, fill=(20, 20, 20))

    book = job["book"].strip().strip("《》")
    out_dir = os.path.join(BASE, "douyin")
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, "封面_%s_3x4.png" % book)
    im.save(out)
    prev_dir = os.path.join(BASE, "work", "_coverpreview")
    os.makedirs(prev_dir, exist_ok=True)
    im.crop((0, 180, 1080, 1260)).save(os.path.join(prev_dir, "1x1.png"))
    print("封面: %s (%s)" % (out, im.size))
    print("1:1 预览: %s" % os.path.join(prev_dir, "1x1.png"))
    return out


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(0)
    build(json.load(io.open(sys.argv[1], encoding="utf-8")))
