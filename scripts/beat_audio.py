# -*- coding: utf-8 -*-
"""beat 模式：给 flow 片补一层真正有起伏的音频与句读节奏。

2026-11-17 用户反馈「音频还是结构还是差点」。诊断：
  · 旧 BGM 是 verse.ensure_bgm() 的 46 秒单和弦正弦垫音，没有和声进行、
    没有节拍、没有情绪线，整片一个调子；
  · 配音是整段一次合成，句间只有 TTS 自带停顿，重点句前后没有留白；
  · 镜头 7 段按时间平均切，跟文案节点无关，所以「听」和「看」都不成段落。

本模块做三件事，且完全不改动 verse / 旧 flow 分支：
  1. insert_pauses()：在指定句末插入静音，并同步平移逐字时间轴 words；
  2. render_bgm()：按幕生成和弦进行（Am-F-C-G）+ 分幕音量包络 +
     断点骤停 + 心跳低频 + 两处重音落点 + 人声 duck；
  3. mix()：人声电平归一 + 混音 + 软限幅，输出 44.1k 单声道 wav。

纯标准库（无 numpy），程序化合成，零第三方音乐版权、零积分。
"""
from __future__ import annotations

import array
import json
import math
import os
import subprocess
import wave

from utils import ffmpeg_exe

SR = 44100
TN = 4096                      # 正弦查表长度（避免每帧多次 math.sin）
SIN = [math.sin(2.0 * math.pi * i / TN) for i in range(TN)]
MASK = TN - 1

# A 小调四和弦循环：Am - F - C - G，情绪偏内省但不悲
CHORDS = (
    (220.00, 261.63, 329.63),   # Am
    (174.61, 220.00, 261.63),   # F
    (261.63, 329.63, 392.00),   # C
    (196.00, 246.94, 293.66),   # G
)
CHORD_SEC = 2.45


def _decode(mp3: str, pcm_path: str) -> array.array:
    """edge-tts 的 mp3 解成 44.1k 单声道 s16le PCM。"""
    subprocess.run([ffmpeg_exe(), "-y", "-v", "error", "-i", mp3,
                    "-ac", "1", "-ar", str(SR), "-f", "s16le", pcm_path],
                   check=True)
    a = array.array("h")
    with open(pcm_path, "rb") as f:
        a.frombytes(f.read())
    if len(a) == 0:
        raise RuntimeError("配音解码为空: " + mp3)
    return a


def insert_pauses(voice_mp3: str, words: list, gaps: list, wdir: str):
    """在指定原时间轴位置插入静音，并把 words 同步平移。

    gaps: [(cut_time, seconds), ...]，cut_time 用「上一屏最后一个字的 end」。
    返回 (新 PCM, 新 words, 新时长)。
    """
    os.makedirs(wdir, exist_ok=True)
    pcm = _decode(voice_mp3, os.path.join(wdir, "_voice.pcm"))
    cuts = sorted((float(c), float(g)) for c, g in gaps if g > 0)
    segs, shifts, prev, acc = [], [], 0, 0.0
    for cut, gap in cuts:
        i = max(prev, min(len(pcm), int(round(cut * SR))))
        segs.append(pcm[prev:i])
        segs.append(array.array("h", [0]) * int(round(gap * SR)))
        prev = i
        acc += gap
        shifts.append((cut, acc))
    segs.append(pcm[prev:])
    out = array.array("h")
    for s in segs:
        out.extend(s)

    new_words = []
    for w in words:
        d = 0.0
        for cut, a in shifts:
            if w["start"] >= cut - 1e-6:
                d = a
        new_words.append({"i": w["i"], "ch": w["ch"],
                          "start": round(w["start"] + d, 3),
                          "end": round(w["end"] + d, 3)})
    return out, new_words, len(out) / float(SR)


def _tone(buf: array.array, start: float, dur: float, freq: float,
          amp: float, tau: float = 1.10, attack: float = 0.018,
          detune: float = 0.0):
    """把一个带自然衰减的音符叠进浮点缓冲；查表法，纯 Python 也够快。"""
    i0 = int(start * SR)
    if i0 >= len(buf) or amp <= 0.0:
        return
    n = min(int(dur * SR), len(buf) - i0)
    if n <= 0:
        return
    step = TN * freq / SR
    step2 = TN * freq * (1.0 + detune) / SR
    ph = ph2 = 0.0
    a_atk = max(1, int(attack * SR))
    decay = 1.0 / (tau * SR)
    for k in range(n):
        v = SIN[int(ph) & MASK]
        ph += step
        if detune:
            v += 0.55 * SIN[int(ph2) & MASK]
            ph2 += step2
        env = (k / a_atk if k < a_atk else 1.0) * math.exp(-k * decay)
        buf[i0 + k] += amp * v * env


def _seg_level(t: float, cuts: list, levels: list) -> float:
    """取 t 所在幕的目标音量（不含过渡），供心跳/亮层判断用。"""
    seg = 0
    for i, c in enumerate(cuts):
        if t >= c:
            seg = i + 1
    return levels[min(seg, len(levels) - 1)]


def render_bgm(dur: float, cuts: list, levels: list, voice_spans: list,
               impacts: list, bgm_gain: float = 0.20):
    """生成分幕 BGM 浮点缓冲（未混人声）。

    cuts/levels：镜头与配乐共用同一组幕节点，听与看同时换挡。
    事件振幅统一固定，幕音量在逐样本包络里施加，避免跨幕和弦把断点带响。
    impacts：[(t, kind)] 单独走不受幕包络的通道，断点处才听得见闷响。
    """
    n = int(dur * SR)
    buf = array.array("f", [0.0]) * n
    imp = array.array("f", [0.0]) * n

    # 和弦进行：每个和弦三个音 + 一个低八度 bass；幕 4 之后加高八度亮层
    bright_from = cuts[3] if len(cuts) > 3 else dur
    for ci in range(int(math.ceil(dur / CHORD_SEC)) + 1):
        t0 = ci * CHORD_SEC
        ch = CHORDS[ci % len(CHORDS)]
        for j, f in enumerate(ch):
            _tone(buf, t0 + j * 0.085, CHORD_SEC * 1.18, f,
                  0.30, tau=1.25, detune=0.0016)
            # 持续 pad：让句间留白里也有可听的和声底，而不是只剩拨弦尾巴。
            # 断点幕的逐样本包络会把它一起砸到 0.04，骤停才听得出来。
            _tone(buf, t0, CHORD_SEC * 1.26, f,
                  0.085, tau=6.0, attack=0.35, detune=0.0008)
            if t0 >= bright_from:
                _tone(buf, t0 + 0.10 + j * 0.06, CHORD_SEC * 0.85, f * 2,
                      0.075, tau=0.85)
        _tone(buf, t0, CHORD_SEC * 1.30, ch[0] / 2.0, 0.26, tau=1.55)

    # 心跳低频：只在推进幕（level >= 0.80）出现，每 0.82 秒一记
    for i in range(int(dur / 0.82) + 1):
        t = i * 0.82
        if _seg_level(t, cuts, levels) >= 0.80:
            _tone(buf, t, 0.14, 56.0, 0.30, tau=0.055, attack=0.004)
            _tone(buf, t + 0.19, 0.10, 48.0, 0.16, tau=0.045,
                  attack=0.004)

    # 重音落点：断点一记闷响，收束一枚亮音（不受幕包络衰减）
    for t, kind in impacts:
        if kind == "low":
            _tone(imp, t, 0.34, 62.0, 0.62, tau=0.10, attack=0.003)
            _tone(imp, t, 0.22, 93.0, 0.20, tau=0.075, attack=0.003)
        else:
            _tone(imp, t, 0.90, 880.0, 0.30, tau=0.32, attack=0.006)
            _tone(imp, t + 0.06, 0.80, 1318.5, 0.14, tau=0.28,
                  attack=0.006)

    # 人声 duck 掩码：0.10s 盒式平滑，避免咔哒
    voice = bytearray(n)
    for a, b in voice_spans:
        i0, i1 = max(0, int(a * SR)), min(n, int(b * SR))
        for i in range(i0, i1):
            voice[i] = 1
    win = int(0.10 * SR)
    pref = [0] * (n + 1)
    for i in range(n):
        pref[i + 1] = pref[i] + voice[i]

    # 分幕包络：断点幕 40ms 骤停，其余 0.28s 柔和推进；末尾 1.35s 淡出
    bounds = [0.0] + [float(c) for c in cuts] + [dur]
    fade_n = max(1, int(1.35 * SR))
    for si in range(len(bounds) - 1):
        a, b = bounds[si], bounds[si + 1]
        cur = levels[min(si, len(levels) - 1)]
        prv = levels[min(si - 1, len(levels) - 1)] if si > 0 else cur
        ramp = 0.04 if cur < 0.1 else 0.28
        i0, i1 = max(0, int(a * SR)), min(n, int(b * SR))
        for i in range(i0, i1):
            t = i / float(SR)
            lvl = (prv + (cur - prv) * min(1.0, (t - a) / ramp)
                   if t < a + ramp else cur)
            lo, hi = max(0, i - win), min(n, i + win)
            vd = (pref[hi] - pref[lo]) / float(max(1, hi - lo))
            duck = 1.0 - 0.46 * vd
            fade = (max(0.0, (dur - t) * SR / fade_n)
                    if dur - t < 1.35 else 1.0)
            buf[i] = buf[i] * lvl * duck * fade + imp[i] * 0.90 * fade
    return buf, bgm_gain


def mix(voice_pcm: array.array, bgm: array.array, bgm_gain: float,
        out_wav: str, tail_sec: float = 1.05,
        target_rms: float = 0.115) -> float:
    """人声 RMS 归一 + BGM 混音 + tanh 软限幅，写出 wav，返回总时长。

    target_rms 默认 0.115（旧节奏版，mean ≈ -18.9dB）保持不变；
    参考片式「介绍体」传 0.20 左右（mean ≈ -14dB），人声更贴耳。
    """
    n = len(voice_pcm)
    rms = math.sqrt(sum(float(v) * v for v in voice_pcm) / max(1, n)) / 32768.0
    vg = min(3.2, max(0.85, target_rms / max(0.001, rms)))
    total_n = n + int(tail_sec * SR)
    out = array.array("h", [0]) * total_n
    for i in range(total_n):
        v = (voice_pcm[i] / 32768.0 * vg) if i < n else 0.0
        b = bgm[i] * bgm_gain if i < len(bgm) else 0.0
        y = math.tanh((v + b) * 1.12) * 0.92
        out[i] = int(max(-32768, min(32767, y * 32767)))
    with wave.open(out_wav, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(out.tobytes())
    return total_n / float(SR)


def build(voice_mp3: str, words: list, gaps: list, cuts: list,
          levels: list, voice_spans: list, impacts: list,
          wdir: str, bgm_gain: float = 0.20):
    """一次性完成：插停顿 → 平移 words → 生成配乐 → 混音。

    cuts/levels/voice_spans/impacts 都是「新时间轴」（含插停顿）上的秒。
    返回 (mix.wav 路径, 新 words, 人声时长, 音频总时长)。
    """
    os.makedirs(wdir, exist_ok=True)
    pcm, new_words, dur_voice = insert_pauses(voice_mp3, words, gaps, wdir)
    bgm, gain = render_bgm(dur_voice + 1.05, cuts, levels,
                           voice_spans, impacts, bgm_gain)
    wav = os.path.join(wdir, "mix.wav")
    total = mix(pcm, bgm, gain, wav)
    json.dump({"words": new_words, "voice_duration": dur_voice,
               "mix_duration": total, "cuts": cuts, "levels": levels},
              open(os.path.join(wdir, "beat.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    return wav, new_words, dur_voice, total
