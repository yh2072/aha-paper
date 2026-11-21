# aha-paper · 互动论文工作室

上传论文 PDF，自动生成可点选章节大纲、配套小游戏、代码动画、自然配音、AI 艺术封面和 3:4 MP4。
界面采用奶油纸色、印象派原野与套色印刷的美术语言。

## 启动

```sh
.venv/bin/pip install -r requirements.txt
npm ci --ignore-scripts
# 已安装 Google Chrome 时无需额外下载浏览器；否则执行：
.venv/bin/python -m playwright install chromium
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8321
```

访问 http://localhost:8321 。右上角「OpenRouter」或左侧「模型与声音」配置 Key。
Key 仅写入本机 `.env`，接口只返回是否已配置；空 Key 表示保留原值。
生成过程中不能修改模型和音色。Edge TTS 不需要单独 Key，但需要联网。

## 配置

代码模型和图片模型用同一套配置方式：**协议显式选择**，Base URL 和 Key 可留空继承语言连接。
走 Anthropic 官方 Claude API 时：

```dotenv
CODE_PROTOCOL=anthropic-messages
CODE_API_KEY=sk-ant-...
OPENROUTER_MODEL_CODE=claude-opus-5-5
```

```dotenv
OPENROUTER_API_KEY=your-key
OPENAI_BASE_URL=https://openrouter.ai/api/v1
OPENAI_MODEL=google/gemini-3.7-flash
OPENROUTER_MODEL_CODE=anthropic/claude-sonnet-4.6
OPENROUTER_MODEL_COVER=openai/gpt-image-2
EDGE_TTS_VOICE=zh-CN-XiaoxiaoNeural
EDGE_TTS_RATE=+0%
```

旧 `OPENAI_API_KEY` 仍可读取。既有 `.env` 的文稿/视觉模型配置继续生效。
代码模型必须支持 OpenRouter Chat Completions；封面模型必须支持 OpenRouter Image API。
文稿模型同时用于视觉理解，应支持图像输入。

## 一键视频流程

1. PDF 文本提取、原有 ONNX 主图识别、图注和讲图要点提取。
2. 写稿与评审迭代，生成分镜，保留原图和子图坐标。
3. **Pi 官方 SDK**（`@earendil-works/pi-agent-core` / `pi-ai`）编写 Canvas 场景，
   按 `CODE_PROTOCOL` 走 Anthropic Messages 或 OpenAI 兼容端点；凭据只经一个变量下传，
   不会借用运行环境里其他厂商的凭据。
   实际读取 `.pi/skills/xilo-opus-video/references/craft-rules.md` 与 riso 美术文档。
   采用用户选定的一键模式，直接使用印象派套色方向；不要求逐次选择三个方案。
4. 每个代码场景在空白、禁网络的浏览器中检查三帧；出现运行错误时最多修改两次。
   `data/<id>/code/` 保留 HTML 源码、指纹缓存、brief 和 QA 静帧。
5. 封面使用 **OpenRouter `/images` 专用 API** 生成完整艺术底图，再本地排标题。
   默认 GPT Image 2，不再使用旧的白底贴纸抠图封面流程。
6. **Edge TTS 整段合成每个场景**，由同一次合成返回的词边界对齐句子。
   讲图场景沿用原来的 `map_sentences_to_regions` 与 `render_guided_pointer`，
   光标按真实句子时长移动；普通场景按旁白时长逐帧渲染 Canvas。
7. 本地 FFmpeg 合成字幕、音频和进度条，输出 `slideshow.mp4`、`narration.wav`。

上传按钮会创建项目并自动排队。已有论文卡片的「一键生成视频」可接入新流程。
失败后可继续，复用已完成步骤；修改上游文稿后，需从更多工具重做分镜和下游步骤。
既有作品仍可观看和下载，旧工作流通过「更多工具」进入。
代码场景和配音缓存包含内容及模型/音色配置；换音色或语速将重新合成。

## 数据与检查

所有正式产物仍保存在原项目 `data/<id>/`。不会自动删除旧成片。
测试：`.venv/bin/python -m unittest discover -s tests -v`。
Node 22.19+、FFmpeg、Chrome/Chromium 和项目 Python 环境为运行依赖。

## 参考与许可证

- [xilo-opus-video](https://github.com/Kianzzz/xilo-opus-video)：MIT，项目内技能和代码视频工艺参考。
- [riso-windowseat](https://github.com/sevenevesai/riso-windowseat)：MIT，美术与运动参考；许可证见 `references/RISO-LICENSE`。
- [Pi](https://github.com/earendil-works/pi)：MIT，使用 npm 锁定的官方 SDK，许可证随依赖安装。
- [Edge TTS](https://github.com/rany2/edge-tts)：在线语音合成。


## 互动视频与章节游戏

作品卡片的「进入互动视频」打开 `/watch/<id>`。每个分镜成为一个 segment，
起止时间由实际渲染片段的 FFprobe 时长累计，点击大纲可随时跳转。
播放器显示当前章节与原文，保留完整 MP4 下载。

默认由 OpenRouter 根据章节旁白生成 1–2 个小游戏，支持预测选择、步骤排序、概念配对。
游戏需要附上对应旁白中真实存在的原句作为依据；内容不足时允许不生成。
章节结束可自动暂停邀请互动，也可取消自动邀请，自主点「玩一玩这一章」。
答对后收集 aha 时刻，学习进度只保存在当前浏览器。

「下载互动包」导出 ZIP，包含独立 `index.html`、播放器、MP4、封面及章节/游戏数据。
解压后直接打开 `index.html`，无需服务或 API Key，即可离线观看、跳转、玩游戏。
MP4 本身只包含线性视频；互动信息保存在网页和 `experience.json` 中。
旧作品如果仍有 `tts_work/seg_*.mp4`，可即时构建真实章节时间；缺片段时需重新生成。

首页「先玩一个小故事」提供真实渲染的互动演示，包含代码场景、真实论文图、光标讲解与 AI 生成的小环节。演示不需要调用 Key。


## 默认深度 interactive explainer

默认按深度科普文章编排，包含完整研究问题、样本与方法、对照与指标、原图与定量结果、局限、应用边界与结论。
每章附原文PDF页码与DOI。正文通常约3000–3600字，必要时保留更长的方法和证据解释，不再使用旧的娱乐化短视频写稿规则。

默认不逐帧渲染视频：仅合成旁白，浏览器根据旁白时间实时绘制Pi代码动画、论文主图、光标和逐句字幕。
小游戏直接覆盖在暂停的讲解画面上，支持全屏。章节随时跳转。
互动包包含音频、HTML/Canvas代码、原图和原论文，可离线观看，且不需要API Key。
需要MP4时，在作品卡片选择「按需导出MP4」，才启动耗时的视频渲染。

回归检查：`python -m unittest discover -s tests -q`；启动服务后运行
`python scripts/check-overlay-workflow.py` 检查桌面、手机、全屏的默认浮层工作流。
