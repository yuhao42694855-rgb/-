# 书单短视频 · 本地生产器

扣子只管生成文案，配音、逐字字幕、卡片/混剪画面、BGM 全部本地完成。
**单条成本 ≈ 扣子一次文案调用的 token（几分钱），其余全部 0 积分。**

## 快速开始

**双击 `run.bat` 就行。**

- 队列为空、还没出过片 → 自动生成一条示例，跑通全流程，成片落在 `out/`
- 队列里有任务 → 逐条处理
- 把任意 json 文件**拖到 run.bat 上** → 只处理这一条

不需要准备素材、不需要装 ffmpeg（已内置在 `vendor/`）、不需要联网调 API
（只有配音要联网，用的是免费的微软语音接口）。

## 日常流程

```
扣子跑工作流 → 复制输出 → 存成文件 → python scripts/from_coze.py 那个文件
→ 双击 run.bat → out/ 里拿成片
```

懒得存文件也可以：复制输出 → 新建 `queue/xxx.json` 粘贴保存 → 双击 `run.bat`。
要求 JSON 结构见 `COZE.md`。

## 目录

```
bookvideo/
├─ queue/          任务队列（.done 后缀 = 已处理）
├─ out/            成片
├─ work/           中间产物（配音、字幕、卡片，可随时删）
├─ assets/
│  ├─ bgm/         背景音乐（已放 kamin3，换歌就替换文件）
│  ├─ clips/       混剪素材池（放了竖屏视频就自动切混剪模式）
│  └─ fonts/
├─ config.json     音色/语速/字幕/配色
├─ COZE.md         扣子端配置与提示词
├─ run.bat         一键处理队列
└─ watch.bat       守护模式：每 60 秒扫一次队列
```

## 两种出片模式（config.json 的 mode）

| 模式 | 条件 | 画面 |
|---|---|---|
| card（默认） | assets/clips/ 为空 | 一本书一张卡 + 封面卡 + 结尾卡，缓慢推近 |
| mix | assets/clips/ 有竖屏视频 | 从素材池随机抽片段混剪 |

素材去哪找：`python scripts/fetch_stock.py "books reading" 20`
（先到 https://www.pexels.com/api/ 免费申请 key，`set PEXELS_KEY=你的key`）

## 字幕说明

字幕是**逐字卡拉OK**（读到哪亮到哪），时间戳直接来自 TTS 的字级边界，
不需要任何语音识别，精度到字。同时每条任务会生成 `work/<id>/sub.srt`，
想进剪映精修时可以直接导入。

## 常改的配置（config.json）

- `voice`：晓晓(女)/云希(男)/云健(男-激情)/晓伊(女-年轻)
- `rate`："+8%" 语速，书单号 6%~12%
- `theme`：卡片配色 ink/paper/forest/plum/night/dawn。`dawn`/`paper` 是浅底，正文与字幕会自动切成深色，不用手动调
- `brand`：卡片角落水印，留空不显示
- `bgm_gain`：BGM 音量 0.10~0.18

## 常见问题

**Q: 双击 run.bat 一闪而过**
在 bookvideo 目录开个终端跑 `python scripts/build.py`，看具体报错。

**Q: 卡片字体不对**
脚本只用 `assets/fonts/` 里的 Noto Sans SC / Noto Serif SC（SIL OFL 1.1，可商用），
不再依赖系统微软雅黑（商用需另购授权，是字体维权高发项）。换字体把 ttf 放进该目录，
改 `scripts/cards.py` 的 `F_*` 常量即可。授权凭证见 `assets/fonts/LICENSE.txt`。

**Q: 想换 BGM**
替换 `assets/bgm/` 里的音频文件即可（mp3/m4a/wav）。
`selfmade_ambient.wav` 是脚本程序化合成的纯自有音频；`kamin3.MP3` 来源不明，
不要用于公开发布的内容。

**Q: 想重新跑同一条**
把 `queue/xxx.json.done` 的 `.done` 去掉，再跑 run.bat。

## 金句卡点模式（verse）

```
python scripts/verse.py queue/verse-caigentan.json
```

对齐用户指定参考片的表达方式：顶部常驻书名作者、黑白画面＋局部亮橙、一屏一句、
中英双行、中文逐字渐显、片头立体书封、片尾搜索条卡。

**只换素材、不换表达方式**的合规替换：
- 文案全自写并标注「读书感悟 · 非原文摘录」，不引用任何在版文本；选明代古籍《菜根谭》
  （著作财产权已过保护期）仅作指示性使用
- 画面为 AI 生成的自有剪影（无真人正脸、无书封、无品牌），生成记录见
  `assets/verse/生成记录.txt`；片头封面是自绘示意封面，不复制真实书封美术设计
- 字体 SIL OFL 开源；BGM 程序化自有；不含抖音号 / 抖音码 / 官方搜索卡 UI / 他人水印
- AI 内容：起始画面显著「AI生成」标签 ＋ 全片常驻标识 ＋ 文件元数据 AIGC 隐式字段

**发布时仍须用平台提供的 AI 标识功能主动声明** —— 《人工智能生成合成内容标识办法》
（2025-09-01 施行）对用户侧的要求，文件里打标不能替代。

任务 JSON 关键字段：`book` / `author` / `subtitle` / `hook` / `verses[]` / `en[]` / `tail`；
`en[]` 与 `verses[]` 一一对应，是自写并人工校对的英文译文。

