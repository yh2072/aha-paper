<div align="center">

# aha-paper

**Turn a paper into a guided read.**<br>
It narrates a PDF while marking the sentence it is explaining — on the paper itself.

[English](#english) · [中文](#中文)

</div>

---

## English

Every frame on screen is either **a figure from the paper** or **a page of the paper**. The model answers one question — *which sentence of the source is this line of narration explaining?* — and every coordinate is computed from the PDF's own text layer.

That split is the point. A wrong answer can highlight a different real sentence; it cannot invent a position. A fabricated quotation simply fails to resolve, so nothing is drawn.

### Quick start

```sh
python -m venv .venv
.venv/bin/pip install -r requirements.txt
npm ci --ignore-scripts
cp .env.example .env          # add OPENROUTER_API_KEY
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8321
```

Open <http://localhost:8321> and drop in a PDF. Keys are written only to a local `.env`; the API reports whether a provider is configured and never returns the credential itself.

**Requirements** — Python 3.11+, Node 22+, FFmpeg. Edge TTS needs no key but does need network.

### What it does

```
extract text → detect figures → write the script → storyboard
             → chapter visuals → blurb & title → collect figures → cover
```

Each stage has a completion test, so an interrupted run resumes without paying for finished work twice. A 12-page paper takes roughly **18 minutes cold**, about **12 of which is writing the script** (draft, an independent fact-and-page audit, then a length-and-structure revision). A fully cached rebuild takes about 2 seconds.

### The two kinds of frame

| | |
|---|---|
| **Figure** | A real figure from the paper. A cursor moves between its subfigures as the narration reaches them. |
| **Page** | The cited PDF page. The sentence being explained is struck through with a marker; its key terms are deepened and underlined. |

Highlights come from the character range `textpage.search()` returns, merged per line into one continuous band. A key term must clear two mechanical checks: it has to be a substring of the chosen sentence, and it has to resolve **inside that sentence's character range**. Anything else is dropped.

A chapter that matches nothing still shows the page it cites. There is no third renderer and no generated diagram.

### Length and scope

- **Length** — type any value from 3 to 30 minutes, or leave it blank for 11. The figure becomes a character budget and a chapter count at 300 characters per minute, holding chapters near 330 characters each.
- **Scope** — if the PDF carries bookmarks, its sections are listed after upload. Picking some is not a hint: **the writer is shown only those pages**, and a chapter citing anything outside them is rejected. A 152-page review can be explained one section at a time.

### Output

```
data/<id>/
├── explainer.json   chapters, per-clause timings, highlight geometry, source pages
├── narration.mp3    Edge TTS narration
├── pages/           rendered PDF pages
├── figures/         detected figures
└── aha-paper-interactive.zip
```

Unzip the bundle and open `index.html`: it plays offline, with no server and no key.

The interface is bilingual, translated at the DOM layer and keyed on the Chinese source string, so paper content and model output are never mistranslated.

### Configuration

Connect a provider once; every use shares its endpoint and credential, and each use picks its own model.

```dotenv
LANGUAGE_PROVIDER=openrouter
OPENAI_MODEL=google/gemini-3.7-flash        # script and narration; needs image input
OPENROUTER_MODEL_COVER=openai/gpt-image-2   # cover
EDGE_TTS_VOICE=zh-CN-XiaoxiaoNeural
```

See `.env.example` for every key. Models and voice are locked while a run is in flight; changing the voice or rate re-synthesises the narration.

### Development

```sh
.venv/bin/python -m unittest discover -s tests -q
```

152 tests, no network required. Several are negative controls: a fabricated quotation finds no position in a real text layer, a section id the outline does not hold is refused, and no credential appears in any API response.

A few need a sample paper under `data/` and skip without one.

### Acknowledgements

- [Twemoji](https://github.com/jdecked/twemoji) — interface icons, graphics CC-BY 4.0, see `web/emoji/LICENSE.txt`
- [Pi](https://github.com/earendil-works/pi) — provider and model catalogue, MIT, installed with the npm dependencies
- [Edge TTS](https://github.com/rany2/edge-tts) — speech synthesis

---

## 中文

屏幕上的每一帧，**要么是论文自己的插图，要么是论文自己的页面**。模型只回答一个问题——「这句旁白在讲原文的哪一句」——所有坐标都由 PDF 的文字层算出。

这个分工就是关键。答错了，最多是标到另一句真实存在的话；它造不出一个位置。编造的引文根本定位不到，于是什么也不会画。

### 快速开始

```sh
python -m venv .venv
.venv/bin/pip install -r requirements.txt
npm ci --ignore-scripts
cp .env.example .env          # 填入 OPENROUTER_API_KEY
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8321
```

打开 <http://localhost:8321> ，拖进一个 PDF。Key 只写入本机 `.env`，接口只回「是否已配置」，绝不回传凭据本身。

**运行依赖** —— Python 3.11+、Node 22+、FFmpeg。Edge TTS 不需要 Key，但需要联网。

### 它做什么

```
抽取PDF文本 → 检测论文主图 → 生成口播稿 → 生成分镜
            → 章节画面 → 摘要与标题 → 整理章节配图 → 制作封面
```

每一步都有完成判定，中断后续跑不会为已完成的工作重复付费。一篇 12 页的论文冷启动约 **18 分钟**，其中约 **12 分钟花在写口播稿**（初稿、独立核对方法与页码、按字数与结构修订）。全缓存重跑约 2 秒。

### 两种画面

| | |
|---|---|
| **主图** | 论文自己的插图。光标随旁白在子图之间移动。 |
| **原文页** | 该章引用的 PDF 页。讲到的那句打上马克笔，关键词再加重并加下划线。 |

高亮来自 `textpage.search()` 返回的字符区间，按行合并成一条连续色带。关键词要过两道机械校验：必须是所选那句话的子串，且必须能在**那句话的字符范围内**定位到。过不了就丢弃。

一句都没对上的章节，仍然显示它引用的那一页。没有第三种渲染器，也没有生成出来的示意图。

### 时长与范围

- **时长** —— 填 3 到 30 之间的任意分钟数，留空按 11 分钟。按每分钟 300 字换算成字数区间和章节数，每章稳定在 330 字左右。
- **范围** —— 论文带书签时，上传后会列出它的小节。勾选不是提示而已：**写作模型只会看到那些页**，引用范围之外的页会被直接拒绝。一篇 152 页的综述可以一节一节地讲。

### 产物

```
data/<id>/
├── explainer.json   章节、逐句时间轴、高亮坐标、来源页码
├── narration.mp3    Edge TTS 旁白
├── pages/           渲染出的论文页
├── figures/         检出的主图
└── aha-paper-interactive.zip
```

互动包解压后打开 `index.html`：离线可播，不需要服务，也不需要 Key。

界面中英双语，在 DOM 层按中文原串翻译，所以论文内容和模型输出不会被误翻。

### 配置

供应商连接一次，所有用途共用它的端点与凭据；每种用途再各自挑一个模型。

```dotenv
LANGUAGE_PROVIDER=openrouter
OPENAI_MODEL=google/gemini-3.7-flash        # 文稿与讲解，需支持图像输入
OPENROUTER_MODEL_COVER=openai/gpt-image-2   # 封面
EDGE_TTS_VOICE=zh-CN-XiaoxiaoNeural
```

完整键名见 `.env.example`。生成进行中不能改模型和音色；换音色或语速会重新合成旁白。

### 开发

```sh
.venv/bin/python -m unittest discover -s tests -q
```

152 个测试，不需要联网。其中若干条是负对照：编造的引文在真实文字层上找不到位置、目录里没有的小节编号会被拒绝、任何接口响应里都不会出现凭据。

有几条需要 `data/` 下的样本论文，缺了会自动跳过。

### 致谢

- [Twemoji](https://github.com/jdecked/twemoji) —— 界面图标，图形 CC-BY 4.0，见 `web/emoji/LICENSE.txt`
- [Pi](https://github.com/earendil-works/pi) —— 供应商与模型目录，MIT，随 npm 依赖安装
- [Edge TTS](https://github.com/rany2/edge-tts) —— 语音合成
