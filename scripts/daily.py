# -*- coding: utf-8 -*-
"""日更自检 / 下一条变量建议。

用法：
  python scripts/daily.py --next                  # 下一条该用什么钩子/避开哪些书
  python scripts/daily.py queue/verse-xxx.json   # 出片前自检（防同质化 + 发布清单）

不做内容生成：文案仍需人工核实后填写，脚本只负责「别连着两天一样」。
"""
import glob
import io
import json
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
QUEUE = os.path.join(BASE, "queue")
HOOKS = ["反常识", "身份点名", "痛点直击", "数字冲击"]
THEMES = ["ink", "paper", "forest", "plum", "night", "dawn"]


def jobs():
    """按修改时间排序，最新的排最后——日更时不能靠文件名字母序判断新旧。"""
    out = []
    for f in glob.glob(os.path.join(QUEUE, "*.json*")):
        try:
            d = json.load(io.open(f, encoding="utf-8-sig"))
        except Exception:
            continue
        d["_file"] = os.path.basename(f)
        d["_mtime"] = os.path.getmtime(f)
        out.append(d)
    return sorted(out, key=lambda x: x["_mtime"])


def latest_verse(all_jobs, exclude=None):
    vs = [j for j in all_jobs
          if j.get("mode") == "verse" and j.get("_file") != exclude]
    return vs[-1] if vs else None


def words(job):
    return len(("\n".join([job.get("hook", "")] +
                          job.get("verses", []) +
                          [job.get("tail", "")])).replace("\n", ""))


def cover_path(job):
    book = job.get("book", "").strip().strip("《》")
    return os.path.join(BASE, "douyin", "封面_%s_3x4.png" % book)


def actual_duration(job):
    """已出片就读 meta.json 的实测时长；未出片才用字速估算。"""
    meta = os.path.join(BASE, "work", job.get("id", ""), "meta.json")
    if os.path.exists(meta):
        try:
            m = json.load(io.open(meta, encoding="utf-8"))
            if m.get("duration"):
                return m["duration"], True
        except Exception:
            pass
    # 实测：139 字长句 6 屏 → 配音 27.6 秒 ≈ 5.0 字/秒；
    # 但 143 字拆成 14 屏短句 → 配音 33.9 秒，因为每屏切分/断句都会带
    # 约 0.35–0.45 秒的停顿。旧公式按纯字速算会低估 4 秒，把 35 秒成片
    # 误判成「甜点区内」。这里按「字速 + 每屏停顿」估算，日更短句才准。
    screens = len(job.get("verses", []))
    pause = 0.38 * max(0, screens - 6) if screens > 6 else 0.0
    return words(job) / 5.0 + pause + 1.0, False


def suggest_next():
    all_jobs = jobs()
    done_books = [j.get("book", "") for j in all_jobs if j.get("book")]
    prev = latest_verse(all_jobs)
    prev_hook = (prev or {}).get("hook_type", "")
    nxt = HOOKS[(HOOKS.index(prev_hook) + 1) % 4] if prev_hook in HOOKS else HOOKS[0]
    print("=== 下一条建议 ===")
    print("[积分] 默认 0 积分：复用现有素材 / edge-tts / 程序化配乐 / Pexels 图。")
    print("        要新生成 AI 图或视频 → 先报预计消耗并等用户明确同意，再记入 douyin/积分台账.md")
    print("上一条 verse：%s（钩子：%s）" % (
        (prev or {}).get("_file", "无"), prev_hook or "未标注"))
    print("钩子类型：%s   ← 四型轮换，不要连着两天同型" % nxt)
    print("参考句式：")
    tips = {
        "反常识": "别急着放下 / 越想静下来越吵，问题不在你不够努力",
        "身份点名": "写给 30 岁还在硬撑的人 / 总在替别人圆场的人",
        "痛点直击": "你不是想太多，是没人教过你怎么放下。",
        "数字冲击": "一生被贬三次，最后一年他还在往回走。",
    }
    for k, v in tips.items():
        print("  %-6s %s%s" % (k, v, "  ← 本次" if k == nxt else ""))
    print("已做过的书（避重复）：%s" % ("、".join(dict.fromkeys(done_books)) or "无"))
    print("必须换的变量：钩子类型 / 钩子句 / 6 句文案 / 英文 / 片尾提问 / save_line / "
          "主视觉意象 / 封面副标（至少 3 项，只换书名会被判同质化）")
    print("不得改的表达方式：顶部书名作者 / 黑白+橙 / 一屏一句 / 中英双行 / "
          "逐字渐显 / 片头书封 / 片尾搜索条")
    print("文案按 日更规范.md 第十节写金句：12–15 屏短句(6–14字) / 总140–160字 / "
          "≥3 句第二人称断言 / ≥1 组跨屏拆句 / ≥1 句「不是A是B」/ 末句短到能单独截图；别复述情节")
    print("出片命令：python scripts/cover.py queue/新任务.json && "
          "python scripts/verse.py queue/新任务.json")
    print("== 平台红线：固定表达方式可以，只换书名的机械量产会被判同质化 ==")


def copy_health(j):
    """2026-11-14 金句化体检：只提示、不拦截。

    用户反馈「太呆板、没金句」后加的。根因是文案写成了剧情梗概，
    不是画质问题；这里只做文案层软提醒，版式与硬校验一律不动。
    """
    vs = j.get("verses", [])
    if not vs:
        return
    lens = [len(v) for v in vs]
    short = sum(1 for n in lens if n <= 14)
    tiny = sum(1 for n in lens if n <= 8)
    second = sum(1 for v in vs if ("你" in v or "别" in v or "不是" in v))
    third = sum(1 for v in vs if ("他" in v or "她" in v) and "你" not in v)
    print("  -- 文案体检（软提示，不拦截）：各句字数 %s" %
          "/".join(str(n) for n in lens))
    tips = []
    if short < len(vs) * 0.7:
        tips.append("短句偏少（≤14 字仅 %d/%d 句），改 12–15 屏短句并短长交替"
                    % (short, len(vs)))
    if tiny < 2:
        tips.append("缺 ≤8 字的爆点短句（当前 %d 句）" % tiny)
    if second < 3:
        tips.append("第二人称/断言仅 %d 句，观众容易变成旁听别人的故事" % second)
    if third > 1:
        tips.append("第三人称叙事 %d 句（建议 ≤1 句）" % third)
    total = len(j.get("hook", "")) + sum(lens) + len(j.get("tail", ""))
    if total < 138:
        tips.append("总字数仅 %d，配音约 %.1f 秒会掉出 28–35 秒；补 1–2 屏留白短句"
                    "（目标 140–160 字）" % (total, total / 5.0 + 1.0))
    if lens[-1] > 12:
        tips.append("末句 %d 字偏长，最后一句要短到能单独截图" % lens[-1])
    if not tips:
        print("  -- OK 金句化检查通过")
    else:
        for t in tips:
            print("  -- 建议：%s" % t)
    print("  -- 规则：douyin/日更规范.md 第十节；逐屏对照：爆款案例库.md 第十节")


def check(path):
    j = json.load(io.open(path, encoding="utf-8"))
    me = os.path.basename(path)
    prev = latest_verse(jobs(), exclude=me)
    ok = True

    def line(good, msg):
        nonlocal ok
        print("  %s %s" % ("OK " if good else "!! ", msg))
        if not good:
            ok = False

    print("=== 出片前自检：%s ===" % me)
    for key in ("book", "author", "hook", "hook_line", "hook_type", "verses",
                "en", "tail", "save_line", "title", "tags", "desc", "cover_sub"):
        if not j.get(key):
            line(False, "缺字段 %s" % key)
    line(j.get("mode") == "verse", "mode=verse（一条视频只讲一本书）")
    line(len(j.get("verses", [])) == len(j.get("en", [])),
         "中英句数一致（%d / %d）" % (len(j.get("verses", [])), len(j.get("en", []))))
    h = j.get("hook", "")
    line(14 <= len(h) <= 30, "首句 %d 字（建议 18–28 字，直接进内容）" % len(h))
    line(not h.startswith(("大家好", "今天", "今天给")), "首句不以问候/报幕开头")
    line("|" in j.get("hook_line", ""), "hook_line 用 | 分成两行钩子大字")
    line(j.get("hook_type") in HOOKS, "钩子类型 %s 在四型内" % j.get("hook_type"))

    if prev:
        line(j.get("hook_type") != prev.get("hook_type"),
             "钩子类型未与上一条「%s」重复" % prev.get("hook_type", "?"))
        line(j.get("tail") != prev.get("tail"), "片尾提问未与上一条重复")
        line(j.get("book") != prev.get("book"), "书目未与上一条重复")

    dur, real = actual_duration(j)
    line(28 <= dur <= 35,
         "%s %.1f 秒（甜点区 28–35）" % (
             "实测成片" if real else "文案 %d 字，预估" % words(j), dur))
    # 封面由 cover.py 在成片之后生成：出片前只提示，出片后才硬检查。
    # 旧版无脑要求封面存在，导致每次「出片前自检」都误报失败。
    out_mp4 = os.path.join(BASE, "out", "%s.mp4" % j.get("id", ""))
    if os.path.exists(out_mp4):
        line(os.path.exists(cover_path(j)),
             "3:4 发布封面存在：%s" % os.path.basename(cover_path(j)))
    else:
        print("  --  出片后再生成 3:4 封面：%s" %
              os.path.basename(cover_path(j)))
    copy_health(j)
    print("  -- 发布清单 --")
    print("  1. 投稿页「自主声明 / 内容由 AI 生成」勾选（硬性）")
    print("  2. 片头/片尾左下角 28px 白底黑字标识 + 元数据隐式标识（脚本已做，勿再缩字号）")
    print("  3. 正文屏无角标（法规里中间属「可以」）")
    print("  4. 标题埋书名/作者搜索词、话题 2–3 个、首评呼应 save_line")
    print("  5. 发布后 7 天不删不隐不二改（7 天长效赛马），第 1/3/7 天回填 数据记录.csv")
    print("  6. 盯收藏率（收藏/播放）：及格 3%、爆款 5%，低于 2% 难破万播放；"
          "再看 2 秒完播、搜索来源")
    print("=== %s ===" % ("全部通过" if ok else "有问题，改完再出片"))
    return 0 if ok else 1


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(0)
    if sys.argv[1] == "--next":
        suggest_next()
    else:
        sys.exit(check(sys.argv[1]))
