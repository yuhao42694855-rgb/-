"""配音 + 逐字时间轴 + 字幕(ASS/SRT)。全部本地免费，不消耗任何积分。

用法：
    from tts import synthesize
    r = synthesize("文案全文", "work/xxx")
    r["audio"], r["duration"], r["ass"], r["srt"], r["words"]
"""
import asyncio
import json
import os
import re

import edge_tts

from utils import (CJK, ass_time, ensure_dir, spoken_chars, wrap_text)

VOICE = "zh-CN-XiaoxiaoNeural"
RATE = "+8%"
PITCH = "+0Hz"

# 字幕样式
SUB_STYLE = dict(
    # Noto Sans SC：SIL OFL 开源可商用，由 compose.finalize 的 fontsdir 指向
    # assets/fonts 加载；原先的 Microsoft YaHei 商用需授权，已替换。
    font="Noto Sans SC",
    size=84,
    primary="&H00FFFFFF",      # 已读后：白
    secondary="&H0000DEFF",    # 未读：黄 (BGR)
    outline="&H00101010",
    back="&H80000000",
    outline_w=3,
    shadow=1,
    margin_v=180,
)

TITLE_STYLE = dict(size=64, primary="&H00FFFFFF", outline="&H00202020",
                   outline_w=2, margin_v=60)

# 浅底卡片（dawn / paper）专用：深墨字 + 浅色描边，避免白字糊在亮背景上
LIGHT_SUB_STYLE = dict(
    SUB_STYLE,
    primary="&H001E2228",      # 已读：深墨 (BGR)
    secondary="&H002850C8",    # 未读：赭红 (BGR)
    outline="&H00E8F4FA",      # 描边：暖白
    shadow=0,
)
LIGHT_TITLE_STYLE = dict(TITLE_STYLE, primary="&H001E2228",
                         outline="&H00E8F4FA")


# ---------- 文本切分 ----------

_BREAK = "。！？!?…；;\n"


def split_spans(text: str):
    """返回 [(start, end)] 字符区间，把无实义片段并入前一段。"""
    spans = []
    start = 0
    for i, ch in enumerate(text):
        if ch in _BREAK:
            if i + 1 > start:
                spans.append([start, i + 1])
            start = i + 1
    if start < len(text):
        spans.append([start, len(text)])

    merged = []
    for s, e in spans:
        frag = text[s:e]
        if not spoken_chars(frag):
            if merged:
                merged[-1][1] = e
            else:
                merged.append([s, e])
            continue
        if merged and len(spoken_chars(text[merged[-1][0]:merged[-1][1]])) < 5:
            merged[-1][1] = e
            continue
        merged.append([s, e])
    return [tuple(x) for x in merged]


# ---------- 时间轴对齐 ----------

def _expand_events(events):
    """把词级事件展开成字符级 (char, start, end)。"""
    flat = []
    for ev in events:
        chars = [c for c in str(ev.get("text", "")) if CJK.match(c)]
        if not chars:
            continue
        s = ev["offset"] / 1e7
        d = max(0.02, ev["duration"] / 1e7)
        step = d / len(chars)
        for k, c in enumerate(chars):
            flat.append((c, s + k * step, s + (k + 1) * step))
    return flat


def align_times(text: str, events: list):
    """用序列对齐把词级时间戳摊到每个字，未覆盖的字做线性插值。"""
    import difflib

    spoken_pos = [i for i, ch in enumerate(text) if CJK.match(ch)]
    times = [None] * len(text)
    flat = _expand_events(events)

    hit = 0
    if flat and spoken_pos:
        a = [text[i] for i in spoken_pos]
        b = [c for c, _, _ in flat]
        sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
        for tag, i1, i2, j1, j2 in sm.get_opcodes():
            if tag != "equal":
                continue
            for k in range(i2 - i1):
                times[spoken_pos[i1 + k]] = [flat[j1 + k][1], flat[j1 + k][2]]
                hit += 1

    if hit < len(spoken_pos) * 0.5:
        total = (events[-1]["offset"] + events[-1]["duration"]) / 1e7 if events else 0.0
        step = total / max(1, len(spoken_pos))
        for k, pos in enumerate(spoken_pos):
            times[pos] = [k * step, (k + 1) * step]

    known = [i for i in range(len(text)) if times[i] is not None]
    for gi in range(len(known) - 1):
        i, j = known[gi], known[gi + 1]
        if j - i <= 1:
            continue
        s, e = times[i][1], times[j][0]
        gap = max(0.0, e - s)
        n = j - i - 1
        step = gap / n
        for k in range(1, n + 1):
            times[i + k] = [s + (k - 1) * step, s + k * step]

    prev_end = 0.0
    for i in range(len(text)):
        if times[i] is None:
            times[i] = [prev_end, prev_end + 0.05]
        if times[i][0] < prev_end:
            times[i][0] = prev_end
        prev_end = times[i][1]

    # 非发音字符（标点空格）贴着前一个字
    for i in range(len(text) - 1, -1, -1):
        if CJK.match(text[i]) or times[i][1] - times[i][0] > 0.001:
            continue
        j = i + 1
        while j < len(text) and not CJK.match(text[j]) and times[j][1] - times[j][0] <= 0.001:
            j += 1
        nxt = times[j][0] if j < len(text) else times[i][0]
        k = i - 1
        while k >= 0 and not CJK.match(text[k]):
            k -= 1
        prev = times[k][1] if k >= 0 else times[i][0]
        times[i] = [prev, max(prev + 0.001, min(nxt, prev + 0.12))]

    for i in range(len(text) - 1):
        if times[i][1] > times[i + 1][0]:
            times[i][1] = max(times[i][0] + 0.001, times[i + 1][0])
    return times


# ---------- ASS 字幕 ----------

ASS_HEAD = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Sub,{font},{size},{primary},{secondary},{outline},{back},-1,0,0,0,100,100,1,0,1,{outline_w},{shadow},2,60,60,{margin_v},1
Style: Title,{tfont},{tsize},{tprimary},{tsecondary},{toutline},&H80000000,-1,0,0,0,100,100,2,0,1,{toutline_w},1,8,60,60,{tmargin_v},1

[Events]
Format: Layer, Start, End, Style, Text
"""


def build_ass(text: str, times: list, spans: list, out_path: str,
              title: str = "", per_line: int = 10, light_bg: bool = False):
    s = LIGHT_SUB_STYLE if light_bg else SUB_STYLE
    t = LIGHT_TITLE_STYLE if light_bg else TITLE_STYLE
    head = ASS_HEAD.format(
        font=s["font"], size=s["size"], primary=s["primary"],
        secondary=s["secondary"], outline=s["outline"], back=s["back"],
        outline_w=s["outline_w"], shadow=s["shadow"], margin_v=s["margin_v"],
        tfont=s["font"], tsize=t["size"], tprimary=t["primary"],
        tsecondary=s["secondary"], toutline=t["outline"],
        toutline_w=t["outline_w"], tmargin_v=t["margin_v"],
    )

    lines = []
    if title:
        lines.append("Dialogue: 1,%s,%s,Title,%s" % (
            ass_time(0.3), ass_time(max(2.0, times[-1][1] if times else 2.0)),
            title.replace("\n", "\\N")))

    for start, end in spans:
        frag = text[start:end]
        shown = frag.strip()
        if not shown:
            continue
        seg_start = times[start][0] if times[start] else 0
        seg_end = times[end - 1][1] if times[end - 1] else seg_start + 1
        body = []
        count = 0
        for i in range(start, end):
            ch = text[i]
            if ch == "\n":
                body.append("\\N")
                count = 0
                continue
            if ch in " ":
                body.append(" ")
                continue
            # 行首不落标点：宁可让上一行多一个字，也别把逗号顶到下一行开头
            if count >= per_line and ch not in "，。！？；：、,.!?;:）」》】…":
                body.append("\\N")
                count = 0
            st, en = times[i]
            cs = max(1, int(round((en - st) * 100)))
            body.append("{\\k%d}%s" % (cs, ch))
            count += 1
        txt = "".join(body)
        lines.append("Dialogue: 0,%s,%s,Sub,%s" % (
            ass_time(seg_start), ass_time(seg_end), txt))

    with open(out_path, "w", encoding="utf-8-sig") as f:
        f.write(head + "\n".join(lines) + "\n")
    return out_path


def build_srt(text: str, times: list, spans: list, out_path: str):
    def ts(x):
        return "%02d:%02d:%02d,%03d" % (
            int(x // 3600), int(x % 3600 // 60), int(x % 60), int(x % 1 * 1000))

    out = []
    n = 0
    for start, end in spans:
        frag = text[start:end].strip()
        if not frag:
            continue
        n += 1
        out.append("%d\n%s --> %s\n%s\n" % (
            n, ts(times[start][0]), ts(times[end - 1][1]), frag))
    with open(out_path, "w", encoding="utf-8-sig") as f:
        f.write("\n".join(out))
    return out_path


# ---------- 主入口 ----------

async def _synth_async(text, mp3_path, voice, rate, pitch):
    comm = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch,
                                boundary="WordBoundary")
    events = []
    with open(mp3_path, "wb") as f:
        async for chunk in comm.stream():
            if chunk["type"] == "audio":
                f.write(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                events.append({"offset": chunk["offset"],
                               "duration": chunk["duration"],
                               "text": chunk["text"]})
    return events


def synthesize(text: str, out_dir: str, voice: str = VOICE, rate: str = RATE,
               pitch: str = PITCH, title: str = "", per_line: int = 10,
               light_bg: bool = False) -> dict:
    ensure_dir(out_dir)
    text = text.strip()
    mp3 = os.path.join(out_dir, "voice.mp3")

    events = asyncio.run(_synth_async(text, mp3, voice, rate, pitch))
    if not events:
        raise RuntimeError("没有拿到时间戳，检查网络或音色名")

    times = align_times(text, events)
    spans = split_spans(text)
    ass = build_ass(text, times, spans, os.path.join(out_dir, "sub.ass"),
                    title=title, per_line=per_line, light_bg=light_bg)
    srt = build_srt(text, times, spans, os.path.join(out_dir, "sub.srt"))

    words = [{"i": i, "ch": text[i], "start": round(times[i][0], 3),
              "end": round(times[i][1], 3)} for i in range(len(text))]
    wj = os.path.join(out_dir, "words.json")
    json.dump({"text": text, "duration": round(times[-1][1], 3),
               "voice": voice, "words": words},
              open(wj, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    return {"audio": mp3, "ass": ass, "srt": srt, "words": wj,
            "duration": times[-1][1], "chars": len(text)}


if __name__ == "__main__":
    import sys
    txt = sys.argv[1] if len(sys.argv) > 1 else (
        "这本书我读了三次。第一次看懂故事，第二次看懂人性，第三次才看懂自己。"
        "如果你也正处在人生的岔路口，它值得你花一个晚上。")
    r = synthesize(txt, os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "work", "_tts_demo"))
    for k, v in r.items():
        print(k, "=", v)
