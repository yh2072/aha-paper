# Reference · 参考

[← README](../README.md) · [← 中文说明](../README.zh.md)

How a frame is drawn, what the run produces, and every knob worth turning.

---

## English

## The two kinds of frame

| | |
|---|---|
| **Figure** | A real figure from the paper. A cursor moves between its subfigures as the narration reaches them. |
| **Page** | The cited PDF page. The sentence being explained is struck through with a marker; its key terms are deepened and underlined. |

Highlights come from the character range `textpage.search()` returns, merged per line into one continuous band. A key term must clear two mechanical checks: it has to be a substring of the chosen sentence, and it has to resolve **inside that sentence's character range**. Anything else is dropped.

A chapter that matches nothing still shows the page it cites. There is no third renderer and no generated diagram.

## Length and scope

- **Length** — type any value from 3 to 30 minutes, or leave it blank for 11. The figure becomes a character budget and a chapter count at the narration language's own rate: 300 characters a minute for Chinese and about 900 for English, holding a chapter near a minute either way. See `app/lang.py`.
- **Scope** — if the PDF carries bookmarks, its sections are listed after upload. Picking some is not a hint: **the writer is shown only those pages**, and a chapter citing anything outside them is rejected. A 152-page review can be explained one section at a time.

## Output

```
data/<id>/
├── explainer.json   chapters, per-clause timings, highlight geometry, source pages
├── narration.mp3    narration (Edge TTS by default)
├── pages/           rendered PDF pages
├── figures/         detected figures
└── aha-paper-interactive.zip
```

Unzip the bundle and open `index.html`: it plays offline, with no server and no key.

The interface is bilingual, translated at the DOM layer and keyed on the Chinese source string, so paper content and model output are never mistranslated.

## Configuration

Connect a provider once; every use shares its endpoint and credential, and each use picks its own model.

```dotenv
AHA_ACCESS_PASSWORD=                        # blank: no gate, for local use
LANGUAGE_PROVIDER=openrouter
OPENAI_MODEL=google/gemini-3.7-flash        # script and narration; needs image input
OPENROUTER_MODEL_COVER=openai/gpt-image-2   # cover
TTS_PROVIDER=edge                           # edge | openai | google | elevenlabs | minimax
EDGE_TTS_VOICE=zh-CN-XiaoxiaoNeural          # a voice for another language hands over
AHA_SCRIPT_AUDIT=0                          # 1: re-check the draft against the paper (~2 min more)
```

Speech providers that return word timestamps (Edge, ElevenLabs) narrate a chapter in one take and the cursor moves clause by clause. The others (OpenAI, Gemini, MiniMax) are synthesized one sentence at a time and each clip's real length is that sentence's duration, so the cursor moves sentence by sentence — never by an estimate. OpenAI, Gemini and MiniMax reuse the provider connection made under Providers; ElevenLabs takes its own key.

The narration's language is a property of each project, chosen when it is created and stored in its metadata; it decides the writer's persona, the pace, the voice and where a sentence ends.

See `.env.example` for every key. Models and voice are locked while a run is in flight; changing the voice or rate re-synthesises the narration.

## Development

```sh
.venv/bin/python -m unittest discover -s tests -q
```

290 tests, no network required. Several are negative controls: a fabricated quotation finds no position in a real text layer, a section id the outline does not hold is refused, and no credential appears in any API response.

A few need a sample paper under `data/` and skip without one.

---

## 中文

## 两种画面

| | |
|---|---|
| **主图** | 论文自己的插图。光标随旁白在子图之间移动。 |
| **原文页** | 该章引用的 PDF 页。讲到的那句打上马克笔，关键词再加重并加下划线。 |

高亮来自 `textpage.search()` 返回的字符区间，按行合并成一条连续色带。关键词要过两道机械校验：必须是所选那句话的子串，且必须能在**那句话的字符范围内**定位到。过不了就丢弃。

一句都没对上的章节，仍然显示它引用的那一页。没有第三种渲染器，也没有生成出来的示意图。

## 时长与范围

- **时长** —— 填 3 到 30 之间的任意分钟数，留空按 11 分钟。按讲解语言的语速换算成字数区间和章节数：中文每分钟 300 字、每章约 330 字，英文每分钟约 900 字符、每章约 165 词。见 `app/lang.py`。
- **范围** —— 论文带书签时，上传后会列出它的小节。勾选不是提示而已：**写作模型只会看到那些页**，引用范围之外的页会被直接拒绝。一篇 152 页的综述可以一节一节地讲。

## 产物

```
data/<id>/
├── explainer.json   章节、逐句时间轴、高亮坐标、来源页码
├── narration.mp3    旁白（默认 Edge TTS）
├── pages/           渲染出的论文页
├── figures/         检出的主图
└── aha-paper-interactive.zip
```

互动包解压后打开 `index.html`：离线可播，不需要服务，也不需要 Key。

界面中英双语，在 DOM 层按中文原串翻译，所以论文内容和模型输出不会被误翻。

## 配置

供应商连接一次，所有用途共用它的端点与凭据；每种用途再各自挑一个模型。

```dotenv
AHA_ACCESS_PASSWORD=                        # 留空＝不设门，本机跑用这个
LANGUAGE_PROVIDER=openrouter
OPENAI_MODEL=google/gemini-3.7-flash        # 文稿与讲解，需支持图像输入
OPENROUTER_MODEL_COVER=openai/gpt-image-2   # 封面
TTS_PROVIDER=edge                           # edge | openai | google | elevenlabs | minimax
EDGE_TTS_VOICE=zh-CN-XiaoxiaoNeural          # a voice for another language hands over
AHA_SCRIPT_AUDIT=0                          # 1: re-check the draft against the paper (~2 min more)
```

返回词时间戳的语音供应商（Edge、ElevenLabs）整章一次合成，光标按子句移动；其余（OpenAI、Gemini、MiniMax）逐句合成，每段音频的真实长度就是这句的时长，光标按句移动——从不估算。OpenAI、Gemini、MiniMax 复用「供应商」里的连接；ElevenLabs 需要单独的 Key。

讲解语言是每篇项目自己的属性，新建时决定并记在元数据里；它决定写作人格、语速、音色和断句规则。

完整键名见 `.env.example`。生成进行中不能改模型和音色；换音色或语速会重新合成旁白。

## 开发

```sh
.venv/bin/python -m unittest discover -s tests -q
```

152 个测试，不需要联网。其中若干条是负对照：编造的引文在真实文字层上找不到位置、目录里没有的小节编号会被拒绝、任何接口响应里都不会出现凭据。

有几条需要 `data/` 下的样本论文，缺了会自动跳过。
