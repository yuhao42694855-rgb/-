# 出片质量优化记录 · 2026-11-19

## 一、体检基线（ffprobe 实测）

| 成片 | 分辨率 | 帧率 | 视频编码 | 视频码率 | 音频 | 时长 | 体积 |
|---|---|---|---|---|---|---|---|
| `out/ref-zebra.mp4`（11-17 最新） | 1080×1920 | 30 | H.264 | 2.22 Mbps | AAC 183 kbps | 56.2s | 16.9 MB |
| `out/交付_自控力_阳光版/…34秒.mp4`（11-14 交付） | 1080×1920 | 30 | H.264 | 3.16 Mbps | AAC 143 kbps | 34.0s | 14.1 MB |
| `out/demo-11021436.mp4`（11-02 示例书单片） | — | — | H.264 | — | — | — | 3.9 MB |

满屏细线条文字 + 逐字卡拉OK 字幕属于「高细节、低运动」画面，2~3 Mbps 在平台二次压缩后字幕边缘容易糊、暗场容易起色带。源片应留足余量。

### A/B 实测（同一段 5 秒画面，严格对齐参考片）

| 参数 | PSNR（越高越保真） | 体积 |
|---|---|---|
| 旧：`crf 21 / veryfast` | 51.20 dB | 282 KB |
| 新：`crf 18 / medium` | **55.67 dB** | 436 KB |

保真度提升 **4.47 dB**，代价是体积增加约 54%、编码变慢。对以文字为主的画面，这个交换是划算的；平台还会再压一次，源片留余量更重要。

## 二、定位到的根因

`scripts/compose.py` 的通用出片链路（card / mix 模式）用的是：

- `normalize_clip()`：`-crf 22 -preset veryfast`（混剪素材预处理，先损一次）
- `finalize()`：默认 `crf=21, preset=veryfast`（成片再损一次）

而后续新增的高级模式早已升级：

- `scripts/flow.py`：`crf 14 / slow`
- `scripts/verse.py`：`crf 12 / slow`（注释里还留着 11-14 的「清晰度升级」记录）

也就是说，**老链路的画质短板是编码参数，不是素材或算法**。

## 三、本次改动（可一键回退）

| 文件 | 改动 |
|---|---|
| `config.json` | 新增 `crf: 18`、`preset: "medium"` 两个可配置项，并在 `_notes` 写明含义与回退方法 |
| `scripts/build.py` | `finalize()` 调用改为从 `config.json` 读取 `crf` / `preset` |
| `scripts/compose.py` | `normalize_clip()` 的 crf 22 → 18；`finalize()` 默认值 crf 21 → 18、veryfast → medium |

回退方式：把 `config.json` 的 `crf` 改回 `21`、`preset` 改回 `veryfast` 即可，无需改代码。

代价：`medium` 比 `veryfast` 编码慢（约 2~4 倍），成片体积会上升，换取文字边缘与暗场更干净。音频保持 `AAC 192k / 44.1kHz`、`-movflags +faststart` 不变。

## 四、尚未执行 / 待确认

1. **目标视频待指认**：本次需求里提到的「活着」，在本项目中只作为示例书单《30岁前必读的5本书》的第一本（余华《活着》）出现，没有一条独立的《活着》成片。候选为 `out/demo-11021436.mp4`、`out/20261103-105044.mp4`、`out/20261103-110403.mp4`。确认后再用新参数重渲染。
2. **节奏与卡点**：可改项在 `config.json` 的 `rate` / `clip_min` / `clip_max`，以及 `compose.py` 的 `tail`、`flow.py` 的镜头时长。涉及风格判断，等确认方向再动。
3. **字幕与配色排版**：可改项在 `config.json` 的 `sub_per_line`（每行字数）、`theme`（ink/paper/forest/plum/night/dawn）、`brand`，以及 `cards.py` 的字体常量与逐字高亮样式。

## 五、关于 GitHub 连接器

连接器本身**不渲染视频、不改画面**，它管的是代码仓库。所以「通过 GitHub 优化视频」的正确路径是：

改生成脚本 → 用 GitHub 把这次改动版本化（可 diff、可回滚、可复现）→ 本地重渲染出新成片。

本次改动即按此路径提交，仓库里记录的是「让视频变好」的那次代码变更，而不是视频文件本身。

**当前进度与阻塞**（2026-11-19 10:2x 复核）：

- 本地：已 `git init` 并完成多次提交，全部文本文件（含 `queue/verse-huozhe.json`、`douyin/发布包_活着.md`）纳入版本管理，`out/`、`work/`、`vendor/`、`assets/` 及媒体文件由 `.gitignore` 排除。改动通过 `py_compile` 与 JSON 解析校验。工作区干净，随时可推送。
- 远程：**两次**尝试创建私有仓库均返回 `403 Resource not accessible by integration`；同一时刻 `get_me` 与公开仓库搜索均正常、`public_repos` 仍为 0。判定为 GitHub App 安装权限（integration）只放开读，缺少 Administration / Contents 写权限 —— 不是连接掉线，也不是本地可绕过。
- 打通方式二选一：
  1. GitHub → Settings → Applications → 对应 App → Configure，放开 **Administration: write** 与 **Contents: write** 后让我重试；
  2. 在 GitHub 网页手动建空仓库，或用本地 git + Personal Access Token 直接推送：`git remote add origin https://github.com/<you>/<repo>.git && git push -u origin HEAD`（令牌只在命令行临时使用，不要写进任何文件）。
- 结论未变：连接器不碰视频画面，它负责把改动变成可 diff、可回滚的版本历史。

**本次已交付成片**：`out/verse-huozhe.mp4`（《活着》35.7 秒）、`douyin/封面_活着_3x4.png`、`douyin/发布包_活着.md`。该片走 `verse.py` 自带的 `crf 12 / slow / tune stillimage` 链路，不受上文通用链路参数改动影响。
