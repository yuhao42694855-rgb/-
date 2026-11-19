"""公共工具：ffmpeg 路径、时间格式、文本处理。"""
import os
import re
import subprocess
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _find_in_vendor(name: str) -> str:
    import glob
    pat = os.path.join(BASE, "vendor", "ffmpeg*", "bin", name)
    hits = sorted(glob.glob(pat))
    return hits[0] if hits else ""


def ffmpeg_exe() -> str:
    """优先用 vendor 里的完整版（带 libass），其次 imageio-ffmpeg，最后系统 PATH。"""
    p = _find_in_vendor("ffmpeg.exe") or _find_in_vendor("ffmpeg")
    if p:
        return p
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return "ffmpeg"


def ffprobe_exe() -> str:
    p = _find_in_vendor("ffprobe.exe") or _find_in_vendor("ffprobe")
    if p:
        return p
    exe = ffmpeg_exe()
    cand = exe.replace("ffmpeg", "ffprobe")
    if os.path.exists(cand):
        return cand
    return "ffprobe"


def run(cmd: list, check: bool = True) -> subprocess.CompletedProcess:
    p = subprocess.run(cmd, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if check and p.returncode != 0:
        raise RuntimeError(
            "命令失败: %s\n%s" % (" ".join(str(c) for c in cmd), p.stderr[-2000:]))
    return p


def media_duration(path: str) -> float:
    """返回秒。优先 ffprobe，失败则退回 ffmpeg 解析。"""
    p = run([ffprobe_exe(), "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nw=1:nk=1", path], check=False)
    try:
        return float(p.stdout.strip())
    except Exception:
        pass
    p = run([ffmpeg_exe(), "-i", path], check=False)
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+\.\d+)", p.stderr)
    if m:
        return int(m[1]) * 3600 + int(m[2]) * 60 + float(m[3])
    return 0.0


SENT_END = "。！？!?…；;\n"


def split_sentences(text: str):
    """按句切分，保留语气。过短的句子并入下一句，避免字幕闪跳。"""
    text = text.replace("\r", "")
    raw = re.split(r"(?<=[%s])" % re.escape(SENT_END.replace("\n", "")), text)
    if "\n" in text:
        raw = [seg for line in text.split("\n") for seg in re.split(
            r"(?<=[。！？!?…；;])", line)]
    out = []
    for s in raw:
        s = s.strip()
        if not s:
            continue
        if out and len(re.sub(r"[^\w]", "", out[-1])) < 6:
            out[-1] += s
        else:
            out.append(s)
    return out or [text.strip()]


CJK = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf0-9a-zA-Z]")


def spoken_chars(s: str) -> str:
    """取出会被朗读的字符（去掉标点空白）。"""
    return "".join(CJK.findall(s))


def wrap_text(s: str, per_line: int = 10) -> str:
    """按字数硬换行，ASS 用 \\N 连接。"""
    if len(s) <= per_line:
        return s
    lines = [s[i:i + per_line] for i in range(0, len(s), per_line)]
    if len(lines) > 2:
        lines = [lines[0], "".join(lines[1:])]
    return "\\N".join(lines)


def ass_time(sec: float) -> str:
    if sec < 0:
        sec = 0
    h = int(sec // 3600)
    m = int(sec % 3600 // 60)
    s = sec % 60
    return "%d:%02d:%05.2f" % (h, m, s)


def ensure_dir(p: str) -> str:
    os.makedirs(p, exist_ok=True)
    return p
