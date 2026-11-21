# aha-paper

把一篇论文 PDF 变成一段带讲解的阅读。讲到哪一句，就在论文原文上标出哪一句；讲到哪张图，光标就移到图上。

屏幕上的每一张画面，**要么是论文自己的插图，要么是论文自己的页面**。模型只回答一个问题——「这句旁白在讲原文的哪一句」——所有坐标都由 PDF 的文字层算出。所以一次误判最多是标错一句真实存在的话，不可能标到一个不存在的位置。

## 跑起来

```sh
python -m venv .venv
.venv/bin/pip install -r requirements.txt
npm ci --ignore-scripts
cp .env.example .env     # 填入 OPENROUTER_API_KEY
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8321
```

打开 http://localhost:8321 ，拖进一个 PDF。Key 只写本机 `.env`，接口只回「是否已配置」，不回传任何凭据。

运行依赖：Python 3.11+、Node 22+、FFmpeg。Edge TTS 不要 Key，但要联网。

## 它做什么

上传后按顺序跑这几步，每步都有「已完成」判定，中断可续跑，不会重花已经花过的钱：

```
抽取PDF文本 → 检测论文主图 → 生成口播稿 → 生成分镜 → 章节画面 → 小红书文案 → 批量绘图 → 制作封面
```

一篇 12 页左右的论文冷启动约 18 分钟，**其中约 12 分钟花在写口播稿**（写初稿、独立核对方法与页码、按字数结构修订三轮）。画面、配音和封面加起来只占几分钟。全缓存重跑约 2 秒。

## 画面只有两种

| | |
|---|---|
| **真实主图** | 论文自己的插图，光标随讲解在子图之间移动 |
| **论文原文** | 该章引用的 PDF 页面，讲到的那句打上马克笔，关键词再加重并加下划线 |

高亮位置来自 `textpage.search()` 返回的字符区间，再按行合并成连续色带。关键词要过两道机械校验：必须是所选那句话的子串（证明是抄的不是编的），且必须能在**那句话的字符范围内**被文字层找到——否则丢弃。编造的引文搜不到，也就没有位置可标。

一句都没对上的章节，显示该章引用的原页。没有第三种画面，没有凭空生成的示意图或动画。

## 时长与范围

- **时长**：输入框里填 3–30 分钟，留空按 11 分钟。按 300 字/分钟换算成字数区间与章节数，每章稳定在 330 字左右。
- **讲哪部分**：论文带书签时，上传后会列出小节让你勾选。选中的小节不只是写进提示词——**写作模型只会收到那些页**，引用范围外的页会被校验打回。一篇 152 页的综述可以只讲其中一节。

## 产物

```
data/<id>/
├── explainer.json      章节、逐句时间轴、高亮坐标、来源页码
├── narration.mp3       Edge TTS 合成的旁白
├── pages/              渲染出的论文页
├── figures/            检出的真实主图
└── aha-paper-interactive.zip
```

互动包解压后直接打开 `index.html`：离线可看，不需要服务也不需要 Key。

界面中英双语，在 DOM 层按中文原串翻译，所以论文内容和模型输出不会被误翻。

## 配置

供应商连一次，所有用途共用它的端点和凭据；每种用途再各挑一个模型。默认：

```dotenv
LANGUAGE_PROVIDER=openrouter
OPENAI_MODEL=google/gemini-3.7-flash      # 文稿与讲解，需支持图像输入
OPENROUTER_MODEL_COVER=openai/gpt-image-2 # 封面
EDGE_TTS_VOICE=zh-CN-XiaoxiaoNeural
```

完整键名见 `.env.example`。生成过程中不能改模型和音色；换音色或语速会重新合成配音。

## 测试

```sh
.venv/bin/python -m unittest discover -s tests -q
```

152 个测试，不需要联网。其中若干条是负对照：编造的引文在真实 PDF 的文字层上找不到位置、目录里没有的小节编号会被拒绝、凭据不会出现在任何接口响应里。

有几条需要 `data/` 下的样本论文，缺了会自动跳过。

## 许可证

- [riso-windowseat](https://github.com/sevenevesai/riso-windowseat)：MIT，`web/riso-kit.js` 的美术参考，见 `references/RISO-LICENSE`。
- [Twemoji](https://github.com/jdecked/twemoji)：图形 CC-BY 4.0，界面图标，见 `web/emoji/LICENSE.txt`。
- [Pi](https://github.com/earendil-works/pi)：MIT，供应商与模型目录，随 npm 依赖安装。
- [Edge TTS](https://github.com/rany2/edge-tts)：在线语音合成。
