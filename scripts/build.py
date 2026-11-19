"""主流程：队列里的 JSON → 成片 mp4。

两种出片模式，自动选择：
  · 卡片模式（默认）：一本书一张卡，无需任何素材，开箱即用
  · 混剪模式：assets/clips/ 里有素材时，自动改用素材混剪

用法：
    python build.py                # 处理 queue/ 下所有任务
    python build.py xxx.json       # 只跑指定任务
    python build.py --make-demo    # 生成一个示例任务
"""
import glob
import json
import os
import re
import sys
import time

import cards
import compose
import tts as ttsmod
from utils import ensure_dir, media_duration

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CFG_PATH = os.path.join(BASE, "config.json")

DEFAULT_CFG = {
    "voice": "zh-CN-XiaoxiaoNeural",
    "rate": "+8%",
    "pitch": "+0Hz",
    "sub_per_line": 9,
    "bgm_gain": 0.15,
    "clip_min": 3.0,
    "clip_max": 6.5,
    "mode": "auto",
    "theme": "ink",
    "brand": "书单推荐",
}

HOOK_TPL = "{hook}"
ITEM_TPL = "第{n}本，《{name}》。{line}"
TAIL_TPL = "{tail}"


def load_cfg():
    cfg = dict(DEFAULT_CFG)
    if os.path.exists(CFG_PATH):
        cfg.update(json.load(open(CFG_PATH, encoding="utf-8")))
    return cfg


def assemble_parts(job: dict):
    """切成若干段，每段对应一个画面单元。有 script 也按行切。"""
    parts = []
    if job.get("script"):
        for i, line in enumerate(
                [x.strip() for x in job["script"].split("\n") if x.strip()]):
            parts.append({"kind": "line", "idx": i, "text": line,
                          "data": {"line": line}})
        return parts

    if job.get("quotes"):
        # 单本书模式：封面(钩子) → 每句金句一张卡 → 结尾
        if job.get("hook"):
            parts.append({"kind": "hook", "text": HOOK_TPL.format(hook=job["hook"]),
                          "data": job})
        quotes = [str(q).strip() for q in job["quotes"] if str(q).strip()]
        for i, q in enumerate(quotes, 1):
            parts.append({"kind": "quote", "idx": i, "text": q, "data": job})
        # 立意卡：故事讲完必须给一句观点，否则视频只有信息没有寓意
        insight = (job.get("insight") or "").strip()
        if insight:
            parts.append({"kind": "insight", "text": insight, "data": job})
        if job.get("tail"):
            parts.append({"kind": "tail", "text": TAIL_TPL.format(tail=job["tail"]),
                          "data": job})
        return parts

    if job.get("hook"):
        parts.append({"kind": "hook", "text": HOOK_TPL.format(hook=job["hook"]),
                      "data": job})
    for i, it in enumerate(job.get("items") or [], 1):
        parts.append({"kind": "item", "idx": i, "data": it,
                      "text": ITEM_TPL.format(
                          n=i, name=it.get("name", ""),
                          line=it.get("line") or it.get("quote", ""))})
    if job.get("tail"):
        parts.append({"kind": "tail", "text": TAIL_TPL.format(tail=job["tail"]),
                      "data": job})
    return parts


def estimate_seconds(text: str) -> float:
    return len(re.sub(r"[^\w]", "", text)) / 4.6


def _part_times(parts, words):
    """把每段文字映射到秒区间。"""
    off = 0
    for p in parts:
        p["c0"] = off
        p["c1"] = off + len(p["text"])
        off = p["c1"] + 1
    n = len(words)
    for p in parts:
        a = min(p["c0"], n - 1)
        b = min(max(p["c1"] - 1, a), n - 1)
        p["t0"] = max(0.0, words[a]["start"] - 0.12)
        p["t1"] = words[b]["end"] + 0.18
    parts[0]["t0"] = 0.0
    for i in range(len(parts) - 1):
        parts[i]["t1"] = max(parts[i]["t0"] + 0.4,
                             min(parts[i]["t1"], parts[i + 1]["t0"]))
    if parts:
        parts[-1]["t1"] = max(parts[-1]["t0"] + 0.6, parts[-1]["t1"])
    return parts


def _make_pictures(parts, job, cfg, wdir):
    """为每段生成一张画面。"""
    theme = job.get("theme") or cfg.get("theme", "ink")
    brand = cfg.get("brand", "")
    total_books = len([p for p in parts if p["kind"] == "item"])
    total_quotes = len([p for p in parts if p["kind"] == "quote"])
    out = []
    cache = ensure_dir(os.path.join(wdir, "cards"))
    for i, p in enumerate(parts):
        png = os.path.join(cache, "p%02d.png" % i)
        if p["kind"] == "item":
            d = p["data"]
            cards.make_card(d, p["idx"], max(total_books, p["idx"]), png,
                            theme=theme, brand=brand)
        elif p["kind"] == "quote":
            cards.make_quote_card(p["data"], p["idx"], total_quotes, p["text"],
                                  png, theme=theme, brand=brand,
                                  label=job.get("card_label", "金句"))
        elif p["kind"] == "insight":
            cards.make_insight_card(p["data"], p["text"], png,
                                    theme=theme, brand=brand,
                                    label=job.get("insight_label", "读完之后"))
        elif p["kind"] == "hook":
            cards.make_cover(job.get("on_screen_title") or job.get("title", ""),
                             job.get("cover_text", ""), png, theme=theme)
        elif p["kind"] == "tail":
            # 单本书问"哪一句"，多本书问"哪一本"，跟随 tail 的第一个问句
            big = (job.get("tail") or "").split("？")[0].strip() or "你最喜欢哪一本"
            cards.make_cover(big + "？", "", png, theme=theme)
        else:
            cards.make_cover(p["text"][:12], "", png, theme=theme)
        out.append(png)
    return out


def run_job(job: dict, cfg: dict) -> dict:
    jid = job.get("id") or time.strftime("%Y%m%d-%H%M%S")
    theme = job.get("theme") or cfg.get("theme", "ink")
    print("\n=== %s | %s" % (jid, job.get("title", "")))

    parts = assemble_parts(job)
    if not parts:
        raise ValueError("任务 %s 没有文案" % jid)
    text = "\n".join(p["text"] for p in parts)

    est = estimate_seconds(text)
    print("文案 %d 字 / %d 段，预估 %.0f 秒" % (len(text), len(parts), est))
    if est > 100:
        print("！偏长，建议压到 90 秒内")

    wdir = ensure_dir(os.path.join(BASE, "work", jid))
    r = ttsmod.synthesize(
        text, wdir, voice=job.get("voice") or cfg["voice"],
        rate=job.get("rate") or cfg["rate"], pitch=cfg.get("pitch", "+0Hz"),
        title=job.get("on_screen_title", ""), per_line=cfg.get("sub_per_line", 9),
        light_bg=cards.is_light(theme))
    print("配音 %.1f 秒" % r["duration"])

    words = json.load(open(r["words"], encoding="utf-8"))["words"]
    parts = _part_times(parts, words)
    for p in parts:
        print("  %-5s %5.1f - %5.1f  %s" % (
            p["kind"], p["t0"], p["t1"], p["text"][:22]))

    clips = compose.scan_clips(os.path.join(BASE, "assets", "clips"))
    mode = cfg.get("mode", "auto")
    if mode == "auto":
        mode = "mix" if clips else "card"
    print("出片模式: %s（素材池 %d 条）" % (mode, len(clips)))

    cache = ensure_dir(os.path.join(BASE, "work", "_clipcache"))
    if mode == "mix" and clips:
        segs, acc = compose.pick_segments(
            clips, r["duration"], cache, seed=jid,
            min_len=cfg["clip_min"], max_len=cfg["clip_max"])
        print("选用 %d 个片段，共 %.1f 秒" % (len(segs), acc))
        base = os.path.join(wdir, "base.mp4")
        compose.build_base(segs, base, cache)
        clips_used = [s["src"] for s in segs]
    else:
        pics = _make_pictures(parts, job, cfg, wdir)
        base = os.path.join(wdir, "base.mp4")
        compose.build_from_cards(pics, parts, base, cache)
        clips_used = [os.path.basename(x) for x in pics]

    bgm = job.get("bgm") or _default_bgm()
    out = os.path.join(BASE, "out", "%s.mp4" % jid)
    compose.finalize(base, r["audio"], r["ass"], out,
                     bgm=bgm, bgm_gain=cfg.get("bgm_gain", 0.15),
                     crf=cfg.get("crf", 18), preset=cfg.get("preset", "medium"))

    meta = {
        "id": jid, "title": job.get("title", ""), "tags": job.get("tags", []),
        "desc": job.get("desc", ""), "video": out, "mode": mode,
        "duration": round(media_duration(out), 2),
        "voice_seconds": round(r["duration"], 2),
        "assets_used": clips_used, "srt": r["srt"],
    }
    json.dump(meta, open(os.path.join(wdir, "meta.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print("成片: %s (%.1f 秒)" % (out, meta["duration"]))
    return meta


def _default_bgm():
    d = os.path.join(BASE, "assets", "bgm")
    if not os.path.isdir(d):
        return ""
    for f in sorted(os.listdir(d)):
        if f.lower().endswith((".mp3", ".m4a", ".wav")):
            return os.path.join(d, f)
    return ""


def make_demo():
    job = {
        "id": "demo-" + time.strftime("%m%d%H%M"),
        "title": "30岁前读到这5本书，少走十年弯路",
        "on_screen_title": "30岁前必读的5本书",
        "cover_text": "少走十年弯路",
        "hook": "如果30岁前只能读五本书，我会选这几本。",
        "items": [
            {"name": "活着", "author": "余华",
             "line": "它告诉你，人是为了活着本身而活着。"},
            {"name": "被讨厌的勇气", "author": "岸见一郎",
             "line": "所有的烦恼都来自人际关系，而自由就是被别人讨厌。"},
            {"name": "人类简史", "author": "尤瓦尔·赫拉利",
             "line": "我们能统治地球，是因为我们会讲虚构的故事。"},
            {"name": "月亮与六便士", "author": "毛姆",
             "line": "满地都是六便士，他却抬头看见了月亮。"},
            {"name": "非暴力沟通", "author": "马歇尔·卢森堡",
             "line": "大多数争吵不是不爱了，而是不会说话。"},
        ],
        "tail": "哪一本戳中了你？评论区告诉我。",
        "tags": ["#书单", "#读书", "#好书推荐"],
        "desc": "五本改变过我的书。",
    }
    p = os.path.join(BASE, "queue", job["id"] + ".json")
    json.dump(job, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("已生成示例任务:", p)
    return p


def main():
    args = sys.argv[1:]
    if "--make-demo" in args:
        p = make_demo()
        cfg = load_cfg()
        run_job(json.load(open(p, encoding="utf-8")), cfg)
        os.replace(p, p + ".done")
        return
    cfg = load_cfg()

    if args:
        files = args
    else:
        files = sorted(glob.glob(os.path.join(BASE, "queue", "*.json")))

    if not files:
        out_dir = os.path.join(BASE, "out")
        have_out = bool(glob.glob(os.path.join(out_dir, "*.mp4")))
        if have_out:
            print("队列是空的。")
            print("把扣子生成的 JSON 存成 queue/xxx.json，或者直接把 json 文件拖到 run.bat 上。")
            return
        print("队列是空的，先自动生成一条示例把流程跑通……\n")
        files = [make_demo()]

    done, fail = [], []
    explicit = set(os.path.abspath(x) for x in args)
    for f in files:
        try:
            job = json.load(open(f, encoding="utf-8"))
            meta = run_job(job, cfg)
            done.append(meta["video"])
            if f.endswith(".json") and os.path.dirname(os.path.abspath(f)) == \
                    os.path.join(BASE, "queue") and \
                    os.path.abspath(f) not in explicit:
                os.replace(f, f + ".done")
        except Exception as e:
            print("失败 %s: %s" % (os.path.basename(f), e))
            fail.append((f, str(e)))

    print("\n完成 %d 条，失败 %d 条" % (len(done), len(fail)))
    for d in done:
        print("  ", d)
    for f, e in fail:
        print("  FAIL", os.path.basename(f), e)
    if done:
        print("\n成片在 out/ 目录，双击就能播放。")


if __name__ == "__main__":
    main()
