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

**当前进度**（2026-11-19 10:36 复核）：

- 本地：已 `git init` 并完成 4 次提交（`0d3ce4c` → `c23feba`），63 个文本文件共 469,715 字节纳入版本管理，`out/`、`work/`、`vendor/`、`assets/` 及媒体文件由 `.gitignore` 排除。改动通过 `py_compile` 与 JSON 解析校验，工作区干净。`origin` 已配置，`git ls-remote` 匿名连通正常。
- 远程：用户已在 GitHub 网页创建空仓库。API 实测 `full_name = yuhao42694855-rgb/-`，描述「丰富视频资源和内容」，默认分支 `main`，`size = 0`（未勾 README，符合要求），`private = false`（**当前为公开仓库**）。网页填写的「第一视频库」未成为仓库名 —— GitHub 仓库名只接受字母、数字、`.`、`-`、`_`，中文会被过滤；如需改名可在网页 Settings → Repository name 修改。
- **写权限已验证通过**：连接器 `push_files` 成功创建 `refs/heads/main` 与初始提交 `c6e4017`（内容仅 `.gitignore`），返回 `push: true`。说明此前 403 只针对「创建仓库」端点，不涉及文件写入。
- **原建仓 403 的根因**（GitHub 官方 API 文档）：`POST /user/repos`（创建个人仓库）对 GitHub App 安装令牌标记为 `enabledForApps: false`，权限开多大都建不了，必须用 user-to-server OAuth 或 PAT。不要再尝试第三次。

**剩余阻塞（技术性质，非权限问题）**：

连接器是「逐文件、内容即参数」的 API：63 个文件共 469,715 字节，若逐个经手转写，Python 脚本（尤其 `flow.py` 71 KB、`verse.py` 28 KB）极易出现字节级失真，推上去的代码反而不可信；而本机没有 `gh`、没有 PAT、没有 credential helper，暂时走不了 `git push` 协议。两条收尾路径：

1. **推荐**：在 GitHub 网页生成一个仅勾选 `repo` 的 Personal Access Token，用它跑一次 `git push`（令牌只在当次命令的环境变量里使用，不写入任何文件、不回显）。这样 63 个文件与本地 4 次提交历史字节级一致、一次到位；远程已有的探针提交用 `git merge -s ours --allow-unrelated-histories` 并回，无需强推。
2. 不用令牌：把 63 个文件按原目录结构整理成一个待上传文件夹，由用户在 GitHub 网页拖拽上传，文件字节一致但只产生 1 个提交、不带本地历史。

结论未变：连接器不碰视频画面，它负责把改动变成可 diff、可回滚的版本历史。

**本次已交付成片**：`out/verse-huozhe.mp4`（《活着》35.7 秒）、`douyin/封面_活着_3x4.png`、`douyin/发布包_活着.md`。该片走 `verse.py` 自带的 `crf 12 / slow / tune stillimage` 链路，不受上文通用链路参数改动影响。
