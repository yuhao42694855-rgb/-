"""素材混剪 + 字幕烧录 + 音轨混合。全部本地完成，零积分。

流程：
    1. 从素材池按目标时长随机取片段
    2. 每段统一成 1080x1920 / 30fps（带缓存，同一素材只转一次）
    3. concat 拼成底片
    4. 叠字幕、贴配音、压 BGM
"""
import hashlib
import json
import os
import random
import shutil

from utils import ensure_dir, ffmpeg_exe, media_duration, run

W, H, FPS = 1080, 1920, 30
VIDEO_EXT = (".mp4", ".mov", ".m4v", ".avi", ".mkv", ".webm")


def scan_clips(folder: str):
    out = []
    if not os.path.isdir(folder):
        return out
    for f in sorted(os.listdir(folder)):
        if f.lower().endswith(VIDEO_EXT):
            p = os.path.join(folder, f)
            if os.path.getsize(p) > 50 * 1024:
                out.append(p)
    return out


def _cache_key(src: str, w: int, h: int) -> str:
    st = os.stat(src)
    raw = "%s|%d|%d|%d|%d" % (os.path.abspath(src), st.st_size,
                              int(st.st_mtime), w, h)
    return hashlib.md5(raw.encode()).hexdigest()[:16]


def normalize_clip(src: str, cache_dir: str, w=W, h=H) -> str:
    """统一分辨率/帧率/像素格式，去掉原声。结果缓存复用。"""
    ensure_dir(cache_dir)
    dst = os.path.join(cache_dir, _cache_key(src, w, h) + ".mp4")
    if os.path.exists(dst) and os.path.getsize(dst) > 1024:
        return dst
    vf = ("scale=%d:%d:force_original_aspect_ratio=increase,"
          "crop=%d:%d,setsar=1,fps=%d,format=yuv420p" % (w, h, w, h, FPS))
    run([ffmpeg_exe(), "-y", "-i", src, "-an", "-vf", vf,
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
         "-g", str(FPS * 2), dst])
    return dst


def pick_segments(clips, total: float, cache_dir, seed=None,
                  min_len=3.0, max_len=6.5):
    """随机抽片段直到够时长，素材不够就洗牌后再来一轮。"""
    rng = random.Random(seed)
    picked, acc = [], 0.0
    pool = clips[:]
    rng.shuffle(pool)
    idx = 0
    while acc < total + 0.5:
        if idx >= len(pool):
            rng.shuffle(pool)
            idx = 0
            if not pool:
                break
        src = pool[idx]
        idx += 1
        dur = media_duration(src)
        if dur < 1.0:
            continue
        want = min(dur, rng.uniform(min_len, max_len))
        start = 0.0
        if dur > want + 0.2:
            start = rng.uniform(0, dur - want - 0.1)
        norm = normalize_clip(src, cache_dir)
        picked.append({"path": norm, "start": round(start, 3),
                       "dur": round(want, 3), "src": os.path.basename(src)})
        acc += want
    return picked, acc


def build_base(segments, out_path: str, cache_dir: str):
    """把片段拼成一条底片。"""
    ensure_dir(os.path.dirname(out_path))
    parts = []
    for i, s in enumerate(segments):
        part = os.path.join(cache_dir, "part_%03d.mp4" % i)
        run([ffmpeg_exe(), "-y", "-ss", str(s["start"]), "-t", str(s["dur"]),
             "-i", s["path"], "-an", "-c:v", "libx264", "-preset", "veryfast",
             "-crf", "22", "-g", str(FPS * 2), "-pix_fmt", "yuv420p", part])
        parts.append(part)

    lst = os.path.join(cache_dir, "concat.txt")
    with open(lst, "w", encoding="utf-8") as f:
        for p in parts:
            f.write("file '%s'\n" % p.replace("\\", "/"))
    run([ffmpeg_exe(), "-y", "-f", "concat", "-safe", "0", "-i", lst,
         "-c", "copy", out_path])
    return out_path


ASS_FILTER = "ass"


def image_segment(png: str, dur: float, out_path: str, w=W, h=H,
                  zoom_from: float = 1.0, zoom_to: float = 1.05,
                  pan: str = "center", crf: int = 21,
                  preset: str = "veryfast") -> float:
    """静态图 → 带运镜的竖屏片段。pan: center / lr / rl（横移方向）。"""
    frames = max(2, int(round(dur * FPS)))
    dur = frames / FPS
    # verse 模式（motion=False）走「静态直出」：原实现会把 1080x1920 的卡片
    # 先 scale 到 2160x3840，再由 zoompan 缩回 1080x1920，等于把烘焙在图里的
    # 标题/英文/书封重采样两次，是「字发虚」的首要原因。静态卡不做任何缩放。
    still = abs(zoom_to - zoom_from) < 1e-6 and pan == "center"
    if still:
        vf = ("scale=%d:%d:force_original_aspect_ratio=increase,crop=%d:%d,"
              "setsar=1,format=yuv420p" % (w, h, w, h))
        cmd = [ffmpeg_exe(), "-y", "-loop", "1", "-framerate", str(FPS),
               "-i", png, "-vf", vf, "-frames:v", str(frames)]
    else:
        dz = zoom_to - zoom_from
        if pan == "lr":
            xexpr = "(iw-iw/zoom)*(on/%d)" % frames
        elif pan == "rl":
            xexpr = "(iw-iw/zoom)*(1-on/%d)" % frames
        else:
            xexpr = "iw/2-(iw/zoom/2)"
        # 卡间硬切：不加 fade。原先的淡出到黑 + 淡入会在切点留一帧纯黑，
        # 与爆款手册「卡间硬切不做花哨转场」相悖。
        vf = (
            "scale=%d:%d:force_original_aspect_ratio=increase,crop=%d:%d,"
            "zoompan=z='%.4f+%.4f*on/%d':x='%s':y='ih/2-(ih/zoom/2)'"
            ":d=%d:s=%dx%d:fps=%d,format=yuv420p"
            % (w * 2, h * 2, w * 2, h * 2, zoom_from, dz, frames, xexpr,
               frames, w, h, FPS)
        )
        cmd = [ffmpeg_exe(), "-y", "-i", png, "-vf", vf,
               "-frames:v", str(frames)]
    cmd += ["-c:v", "libx264", "-preset", preset, "-crf", str(crf),
            "-g", str(FPS * 2), "-pix_fmt", "yuv420p", "-r", str(FPS),
            "-an", out_path]
    run(cmd)
    return dur


def build_from_cards(pics, parts, out_path: str, cache_dir: str,
                     motion: bool = True, crf: int = 21,
                     preset: str = "veryfast"):
    """每段一张卡，按语音时间点精确切分，拼成底片。
    motion=False 用于 verse 模式（字烘焙在图里，运镜缩放会把字重采样糊掉）。"""
    ensure_dir(cache_dir)
    ensure_dir(os.path.dirname(out_path))
    segs, parts_out = [], []
    done = 0.0
    for i, (png, p) in enumerate(zip(pics, parts)):
        want_end = max(p["t1"], done + 0.8)
        dur = want_end - done
        seg = os.path.join(cache_dir, "card_%03d.mp4" % i)
        # 交替运镜：奇数张推近+右移，偶数张拉远+左移，避免观感单调
        if motion:
            z0, z1, pan = ((1.0, 1.07, "lr") if i % 2 == 0
                          else (1.07, 1.0, "rl"))
        else:
            z0, z1, pan = 1.0, 1.0, "center"
        actual = image_segment(png, dur, seg, zoom_from=z0, zoom_to=z1,
                               pan=pan, crf=crf, preset=preset)
        done += actual
        parts_out.append(seg)
        segs.append(seg)

    lst = os.path.join(cache_dir, "concat.txt")
    with open(lst, "w", encoding="utf-8") as f:
        for p in segs:
            f.write("file '%s'\n" % p.replace("\\", "/"))
    run([ffmpeg_exe(), "-y", "-f", "concat", "-safe", "0", "-i", lst,
         "-c", "copy", out_path])
    return out_path


def has_ass_support() -> bool:
    p = run([ffmpeg_exe(), "-hide_banner", "-filters"], check=False)
    txt = (p.stdout or "") + (p.stderr or "")
    return " ass " in txt or " subtitles " in txt


def finalize(base: str, voice: str, ass: str, out_path: str,
             bgm: str = "", bgm_gain: float = 0.15, tail: float = 0.6,
             fonts_dir_rel: str = "../../assets/fonts",
             metadata: dict = None, crf: int = 18,
             preset: str = "medium", tune: str = ""):
    """贴字幕 + 混音，输出成片。

    fonts_dir_rel：相对工作目录的开源字体目录，让 libass 加载 SIL OFL 字体，
    避免渲染时回退到系统自带的微软雅黑等需商用授权的字体。
    metadata：写进文件元数据的隐式 AIGC 标识（《AI生成合成内容标识办法》）。
    两项均有默认值，旧任务调用方式不变。
    """
    ensure_dir(os.path.dirname(out_path))
    vdur = media_duration(voice)
    total = vdur + tail

    work = os.path.dirname(base)
    ass_rel = os.path.basename(ass)
    local_ass = os.path.join(work, ass_rel)
    if os.path.abspath(ass) != os.path.abspath(local_ass):
        shutil.copy(ass, local_ass)

    cmd = [ffmpeg_exe(), "-y", "-i", base, "-i", voice]
    fc = []
    fc.append("[1:a]volume=1.0,adelay=0|0,apad[va]")
    audio_label = "[va]"

    if bgm and os.path.exists(bgm):
        cmd += ["-i", bgm]
        fc.append("[2:a]volume=%.3f,atrim=0:%.3f,asetpts=PTS-STARTPTS,"
                  "afade=t=in:st=0:d=0.8,afade=t=out:st=%.3f:d=1.2[bg]"
                  % (bgm_gain, total, max(0.0, total - 1.2)))
        fc.append("[va][bg]amix=inputs=2:duration=first:normalize=0[aout]")
        audio_label = "[aout]"

    if has_ass_support():
        ass_filter = "ass=%s" % ass_rel
        if fonts_dir_rel:
            ass_filter += ":fontsdir=%s" % fonts_dir_rel
        fc.append("[0:v]%s[vout]" % ass_filter)
    else:
        fc.append("[0:v]null[vout]")

    cmd += ["-filter_complex", ";".join(fc),
            "-map", "[vout]", "-map", audio_label,
            "-t", "%.3f" % total,
            "-c:v", "libx264", "-preset", preset, "-crf", str(crf),
            "-pix_fmt", "yuv420p", "-r", str(FPS),
            "-c:a", "aac", "-b:a", "192k", "-ar", "44100",
            "-movflags", "+faststart"]
    if tune:
        cmd += ["-tune", tune]
    if metadata:
        for k, v in metadata.items():
            cmd += ["-metadata", "%s=%s" % (k, v)]
    cmd += [out_path]

    cwd = os.getcwd()
    os.chdir(work)
    try:
        run(cmd)
    finally:
        os.chdir(cwd)
    return out_path
