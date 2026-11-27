/* Bilingual UI. Chinese stays the source of truth in the markup and the view
   code; this file is the only place English lives.

   Why the DOM and not templates: interface text, the paper's own words and the
   model's output all land in one tree -- a chapter title sitting next to a "next
   chapter" button -- and the backend sends stage names and error details as data
   that the view pastes straight in. Keying the dictionary on the Chinese source
   means the interface translates, the paper passes through untouched because it
   never matches a key, and studio.js / watch.js / the backend need no edits.

   Deliberately NOT translated, because they are the film and not the interface:
   narration, subtitles, chapter titles and summaries, and the animation canvas
   (motion-diagrams.js also matches Chinese narration with regexes -- translating
   it would break which animation gets chosen).

   The run log used to be on that list, on the grounds that a <pre> holds data.
   It does not: the pipeline writes those lines for a person to read while they
   wait. They are translated, but not by the observer -- <pre> stays in SKIP,
   and studio.js calls t() on each line after splitting off the [HH:MM:SS] stamp
   and the indentation, so what the dictionary is asked about is the message. */
(function () {
  const STORE = 'ahaLang';
  const HAN = /[㐀-䶿一-鿿]/;

  /* Exact text, matched after trimming. Whitespace around the match is kept, so
     'depth explainer ' with its trailing space still lines up with its counter. */
  const DICT = {
    /* ---- shell / navigation ---- */
    'aha-paper · 带你读一遍论文': 'aha-paper · a guided read of the paper',
    '论文→爆款视频 流水线': 'Paper → video pipeline',
    '首页': 'Home',
    '我的论文': 'My papers',
    '深度讲解': 'Explainers',
    '模型与声音': 'Models & voice',
    '本': 'L',
    '本地工作区': 'Local workspace',
    '文件保存在你的电脑': 'Files stay on your computer',
    '逐句对照论文': 'Read against the source',
    '读取配置中': 'Loading settings',
    '关闭': 'Close',

    /* ---- home: the pitch ---- */
    '像有人': 'Like someone ',
    '带着你读论文。': 'reading the paper with you.',
    '从一篇论文，': 'From one paper,',
    '到真正的理解。': 'to real understanding.',
    '读懂 · 看见 · 亲手发现': 'Read · See · Discover',
    '讲到哪一句，就在论文原文上标出哪一句；讲到哪张图，光标就移到图上。':
      'Whatever sentence it explains gets marked on the paper itself; whatever figure it reads, the cursor moves onto.',
    '每一句讲解，都指向论文里的一句原文。': 'Every sentence of narration points at a sentence of the paper.',

    /* ---- home: composer ---- */
    '讲解时长': 'Length',
    '自动': 'Auto',
    '分钟': 'min',
    '这篇论文': 'This paper',
    '不选就是全讲。勾中的小节决定讲什么——写作时只会读到这些页，其余部分不会出现在讲解里。':
      'Pick nothing and the whole paper is explained. Whatever you tick decides the scope — the writer is shown only those pages, and nothing else reaches the explainer.',
    '全讲': 'Explain all',
    '讲解重点': 'What to focus on',
    '上传论文，或先告诉我你想重点弄懂什么……\n比如：讲清实验设计、带我读懂关键主图，并区分结论和局限。':
      'Upload a paper, or tell me what you want to understand first…\nFor example: explain the experimental design, walk me through the key figure, and separate conclusions from limits.',
    '添加论文': 'Add a paper',
    '添加论文 ↗': 'Add a paper ↗',
    '◈ 逐句讲解': '◈ Sentence by sentence',
    '16:9 可交互': '16:9 interactive',
    '生成讲解': 'Generate',
    '支持 PDF · 可批量添加 · 保留论文原图和数据出处':
      'PDF · add several at once · original figures and sources kept',
    '配置 API ↗': 'Set up API ↗',
    '研究问题与实验设计 ↗': 'Question & experimental design ↗',
    '带我读懂论文主图 ↗': 'Walk me through the key figure ↗',
    '方法、结果与局限 ↗': 'Method, results & limits ↗',

    /* ---- home: library ---- */
    '最近项目': 'Recent projects',
    '搜索论文或讲解…': 'Search papers or explainers…',
    '搜索作品': 'Search work',
    '查看全部 ↗': 'See all ↗',
    '收起 ↑': 'Collapse ↑',
    '还没有讲解。': 'No explainers yet.',
    '添加一篇 PDF，它会按原文逐句讲一遍。': 'Add a PDF and it reads through it, sentence by sentence.',
    '没有匹配的论文。': 'No matching papers.',
    '还没有完成的讲解。': 'No finished explainers yet.',
    '还没有讲解。': 'No explainers yet.',
    '试试论文标题或文件名中的其他关键词。': 'Try another word from the title or file name.',
    '添加一篇 PDF，它会按原文逐句讲一遍。': 'Add a PDF and it reads through it, sentence by sentence.',

    /* ---- home: explore ---- */
    '讲解方式': 'Approach',
    '带读主图，': 'Walk through the figure, ',
    '而不是只念结论。': 'not just read out the conclusion.',
    '论文原图 · 局部放大 · 随讲解移动的光标': 'The figure from the paper · zoom · a cursor that follows the narration',
    '用这个方式生成 ↗': 'Use this approach ↗',

    /* ---- project cards ---- */
    '未命名论文': 'Untitled paper',
    '论文讲解': 'Paper explainer',
    '尚未开始': 'Not started',
    '生成中…': 'Generating…',
    '生成深度讲解 ↗': 'Create explainer ↗',
    '继续生成 ↗': 'Resume ↗',
    '重新生成 ↗': 'Regenerate ↗',
    '进入互动讲解': 'Open explainer',
    '封面': 'Cover',
    '文稿': 'Script',
    '日志': 'Log',
    '仅看视频': 'Video only',
    '按需导出 MP4': 'Export MP4',
    '下载 MP4 ↓': 'Download MP4 ↓',
    '请添加 PDF 文件': 'Please add PDF files',
    '正在提交…': 'Submitting…',
    '先连接 OpenRouter': 'Connect OpenRouter first',
    '先连接供应商': 'Connect a provider first',
    '连接供应商': 'Connect a provider',
    '先配置 API，已选论文会保留': 'Set up the API first — your selected papers are kept',
    '已开始：读取 PDF → 生成讲稿 → 对齐原文 → 合成讲解': 'Started: read the PDF → write the narration → align it to the text → assemble',
    '已开始按需渲染 MP4；互动网页版可直接观看。':
      'Rendering MP4 on demand; the interactive version is ready to watch now.',

    /* ---- dialogs ---- */
    '论文短片': 'Paper film',
    '论文原图 · 光标随讲解移动': 'Figures from the paper · a cursor that follows the narration',
    '作品封面': 'Cover art',
    '下载封面 ↓': 'Download cover ↓',
    '运行日志': 'Run log',
    '尚未开始生成。': 'Not started yet.',
    '讲稿': 'Narration',
    '保存后需要重做分镜与下游环节，改动才会进到讲解里。':
      'After saving, the storyboard and the steps after it must be redone before the change reaches the explainer.',
    '保存文稿': 'Save script',
    '文稿已保存': 'Script saved',

    /* ---- settings: providers & models ---- */
    '供应商与模型': 'Providers & models',
    '供应商': 'Providers',
    '供应商连一次，所有用途共用它的端点和凭据。下面再给每种用途挑一个模型，协议、上下文窗口和价格都由目录决定。':
      'Connect a provider once and every use shares its endpoint and credentials. Then pick a model per use — protocol, context window and price come from the catalog.',
    '连接一次，文稿 · 动画 · 封面共用': 'Connect once; shared by script, animation and cover',
    '还没有连接任何供应商。': 'No providers connected yet.',
    '添加供应商': 'Add provider',
    '连接': 'Connect',
    '断开': 'Disconnect',
    '粘贴后点连接': 'Paste, then connect',
    'Key 只存本机，不回传浏览器。该供应商的标准环境变量（如 ANTHROPIC_API_KEY）会自动识别。':
      'Keys are stored on this machine only and never sent back to the browser. The provider’s standard environment variables (such as ANTHROPIC_API_KEY) are picked up automatically.',
    '请先粘贴 API Key': 'Paste an API key first',
    '正在连接…': 'Connecting…',
    '正在断开…': 'Disconnecting…',
    '正在验证连接…': 'Verifying…',
    '正在切换…': 'Switching…',
    '用途 → 模型': 'Use → model',
    '每种用途各挑一个模型': 'One model per use',
    '该供应商未连接': 'Provider not connected',
    '读取目录…': 'Loading catalog…',
    '已保存': 'Saved',
    '设置已保存。': 'Settings saved.',
    '保存设置': 'Save settings',
    '测试连接 ↗': 'Test connection ↗',
    '已存储凭据': 'stored credential',
    '浏览器登录': 'browser sign-in',
    '未使用': 'unused',
    '已连接': 'connected',
    '来自环境变量，不由本应用保存': 'From an environment variable; not stored by this app',
    'OpenRouter 已配置': 'OpenRouter connected',
    '连接 OpenRouter': 'Connect OpenRouter',
    '服务暂时不可用': 'Service temporarily unavailable',
    '请求失败，请稍后重试': 'Request failed — please try again',

    /* ---- settings: narration ---- */
    '旁白 · Edge TTS': 'Narration · Edge TTS',
    '旁白 · 语音': 'Narration · Voice',
    '语音供应商': 'Speech provider',
    '模型': 'Model',
    '音色 ID': 'Voice ID',
    '试听 ▶': 'Preview ▶',
    '正在合成试听…': 'Synthesizing a preview…',
    '正在播放试听': 'Playing the preview',
    '需要 Key': 'Needs a key',
    '复用已合成的配音': 'Reusing the cached narration',
    '复用「供应商」里的 OpenAI 连接；逐句合成，光标按句移动。': 'Uses your OpenAI connection above; synthesized per sentence, so the cursor moves per sentence.',
    '复用「供应商」里的 Google 连接；逐句合成，光标按句移动。': 'Uses your Google connection above; synthesized per sentence, so the cursor moves per sentence.',
    '复用「供应商」里的 MiniMax 连接；中文音色丰富，逐句合成。': 'Uses your MiniMax connection above; rich Chinese voices, synthesized per sentence.',
    '需要 ElevenLabs 自己的 Key；返回逐字时间戳，可整段合成。也可填克隆音色 ID。': 'Needs its own ElevenLabs key; returns character timestamps, so it narrates in one take. Cloned voice IDs work too.',
    '少女': 'Young woman', '御姐': 'Mature woman', '成熟女性': 'Grown woman',
    '青涩青年': 'Young man', '精英青年': 'Professional man',
    '女性主持人': 'Female presenter', '男性主持人': 'Male presenter',
    '有声书女声': 'Audiobook · female', '有声书男声': 'Audiobook · male',
    '请选择列表中的语音供应商': 'Pick a speech provider from the list',
    '音色 ID 无效，请从列表中选择': 'Invalid voice ID — pick one from the list',
    '语音模型 ID 格式无效': 'Invalid speech model ID',
    '该语音供应商使用「供应商」里的连接，不单独保存 Key': 'This speech provider uses the connection under Providers; it does not store a key of its own',
    'API Key 格式无效': 'Invalid API key format',
    '逐句时间戳驱动光标与字幕': 'Per-sentence timestamps drive the cursor and subtitles',
    '音色': 'Voice',
    '语速': 'Rate',
    '晓晓 · 自然女声': 'Xiaoxiao · natural female',
    '云希 · 清朗男声': 'Yunxi · clear male',
    '晓伊 · 温柔女声': 'Xiaoyi · gentle female',
    '云健 · 稳重男声': 'Yunjian · steady male',
    '自然 · 默认': 'Natural · default',
    '舒缓 · -10%': 'Slower · -10%',
    '轻快 · +10%': 'Brisker · +10%',
    '明快 · +20%': 'Lively · +20%',
    'Edge TTS 不需要 Key，但需要联网。': 'Edge TTS needs no key, but it does need internet.',
    '文稿与讲解': 'Script & explainer',
    '封面配图': 'Cover art',

    /* ---- player chrome ---- */
    '← 回到工作室': '← Back to studio',
    '回到工作室 →': 'Back to studio →',
    '实时科学动画': 'Live science animation',
    '论文主图与讲解光标': 'Paper figure with narration cursor',
    '查看全图': 'See whole figure',
    '跟随讲解': 'Follow narration',
    '讲到哪句，标哪句': 'Marked where it is explained',
    '正在打开…': 'Opening…',
    '← 上一章': '← Previous',
    '下一章 →': 'Next →',
    '全屏观看': 'Fullscreen',
    '退出全屏': 'Exit fullscreen',
    '讲解章节': 'Chapters',
    '点击任意章节，自由跳转。': 'Click any chapter to jump.',
    '下载媒体 ↓': 'Download media ↓',
    '下载互动包 ↓': 'Download bundle ↓',
    '下载纯视频 ↓': 'Download video only ↓',
    '下载旁白 ↓': 'Download narration ↓',
    '互动包解压后打开 index.html，即可离线观看。':
      'Unzip the bundle and open index.html to watch offline.',
    '这是一份可离线使用的 aha-paper 互动作品。': 'An offline aha-paper interactive.',
    '暂时无法打开作品': 'Can’t open this work right now',
    '这份讲解还在生成中。': 'This explainer is still being generated.',
    '视频尚未生成章节': 'No chapters generated yet',
    '◈ 真实论文主图 · 光标随讲解移动': '◈ Real paper figure · cursor follows the narration',
    '▤ 论文原文 · 讲到哪句高亮哪句': '▤ The paper itself · the sentence being explained is lit',

    /* ---- backend stage names (arrive as data, land as card text) ---- */
    '待生成': 'Not started',
    '待上传口播视频': 'Waiting for a talking-head video',
    '排队中': 'Queued',
    '已中断': 'Interrupted',
    '任务没跑完就中断了（被杀/重启），可重新触发':
      'The job was interrupted before finishing (killed or restarted) — you can run it again',
    '抽取PDF文本': 'Extracting PDF text',
    '检测论文主图': 'Finding the key figures',
    '生成口播稿': 'Writing the narration',
    '生成分镜': 'Building the storyboard',
    '章节画面': 'Chapter visuals',
    '摘要与标题': 'Blurb and title',
    '整理章节配图': 'Collecting chapter figures',
    '光标动画': 'Cursor animation',
    '制作封面': 'Making the cover',
    '文稿与场景准备完成': 'Script and scenes ready',
    '生成阶段全部完成 ✓': 'All generation steps done ✓',
    '重试完成 ✓': 'Retry finished ✓',
    '语音对齐': 'Aligning the audio',
    'ffmpeg 剪辑合成': 'ffmpeg is cutting the video',
    '成片完成 ✓': 'Video finished ✓',
    '剪辑完成 ✓': 'Cut finished ✓',
    '剪辑排队中': 'Cut queued',
    '实时互动讲解：配音与同步': 'Interactive explainer: voicing and syncing',
    '深度互动讲解完成 ✓': 'Interactive explainer finished ✓',
    '深度互动讲解排队中': 'Interactive explainer queued',
    'TTS 配音+渲染': 'TTS voicing and rendering',
    '叠加进度条': 'Adding the progress bar',
    'TTS 成片完成 ✓': 'TTS video finished ✓',
    '互动视频完成 ✓': 'Interactive video finished ✓',
    'aha-paper 分章节视频完成 ✓': 'aha-paper chaptered video finished ✓',
    '数字人推理中（分段）': 'Avatar inference running (in segments)',
    '数字人角标合成': 'Compositing the avatar badge',
    '数字人圆形角标已合成 ✓': 'Round avatar badge composited ✓',
    '分段数字人角标完成 ✓': 'Segmented avatar badge finished ✓',
    'TTS 成片完成（含数字人）✓': 'TTS video finished (with avatar) ✓',
    'TTS 成片完成（数字人失败）': 'TTS video finished (avatar failed)',
    '搜集实拍素材': 'Collecting B-roll',
    '实拍素材失败': 'B-roll failed',
    'MP4 导出排队中': 'MP4 export queued',

    /* ---- backend errors (arrive as detail, land in the toast) ---- */
    '项目不存在': 'Project not found',
    'PDF 无法抽取文本（可能是纯扫描件，需要 OCR）':
      'No text could be extracted from the PDF (it may be a scan and need OCR)',
    '⚠ PDF 无法抽取文本（可能是纯扫描件，需要 OCR）':
      '⚠ No text could be extracted from the PDF (it may be a scan and need OCR)',
    '项目 ID 无效': 'Invalid project id',
    '没有收到 PDF 文件': 'No PDF received',
    '仅允许工作室页面发起操作': 'Only the studio page may start this',
    '创作进行中，请完成后修改讲解重点': 'Creation is running — change the focus after it finishes',
    '讲解重点请控制在2000字以内': 'Keep the focus under 2000 characters',
    '请先生成文稿和配图': 'Generate the script and illustrations first',
    '请先生成文稿': 'Generate the script first',
    '请先生成 TTS 成片': 'Generate the TTS video first',
    '实拍素材不可用（缺 youtube-know 项目或 yt-dlp）':
      'B-roll unavailable (youtube-know project or yt-dlp missing)',
    'MuseTalk 未就绪（缺模型或 avatar 源视频）': 'MuseTalk not ready (model or avatar source video missing)',
    '该项目还没有上传口播视频': 'No talking-head video uploaded for this project',
    '有任务运行中，完成后再修改设置': 'A job is running — change settings after it finishes',
    '此作品尚未生成分章节视频，请返回工作室重新生成':
      'This work has no chaptered video yet — go back to the studio and generate it again',
    '视频生成中，完成后再导出': 'Video is rendering — export it after it finishes',
    '未知模型用途': 'Unknown model use',
    '选择超时': 'Selection timed out',
    '已取消选择': 'Selection cancelled',
    '没有选择项目': 'No project selected',
    '设置值不能为空或包含换行': 'A setting cannot be empty or contain a line break',
    '请选择明确的图片 API 协议': 'Choose an explicit image API protocol',
    '供应商 ID 无效，请从列表中选择': 'Invalid provider id — pick one from the list',
    '模型 ID 格式无效': 'Invalid model id format',
    '请选择列表中的 Edge TTS 音色': 'Pick an Edge TTS voice from the list',
    '语速范围为 -50% 到 +50%': 'Rate must be between -50% and +50%',
    '请先填写并保存语言 API Key': 'Enter and save the language API key first',
    '该兼容端点不提供模型目录；可手动配置模型，尚未验证推理权限。':
      'This compatible endpoint serves no model catalog; you can set a model by hand, but inference access is unverified.',
    '语言连接已就绪，文稿与封面使用此账户额度。':
      'Language connection ready — script and cover draw on this account’s credit.',
    'Base URL 需为不含凭据、查询或片段的 HTTP(S) API 根地址':
      'The base URL must be an HTTP(S) API root with no credentials, query or fragment',
    '来自 Pi 内置目录，含协议、上下文窗口与价格；列出不代表 Key 有该模型权限。':
      'From Pi’s built-in catalog, with protocol, context window and price. Being listed does not mean your key may use it.',
    '此端点不提供模型目录；可手动填写服务支持的准确模型 ID。':
      'This endpoint serves no catalog; type the exact model id the service supports.',
    '服务未返回兼容的模型目录；请手动填写模型 ID':
      'The service returned no compatible catalog — type the model id by hand',
    '只读取目录，不生成内容；模型是否有权限以实际请求为准。':
      'This only reads the catalog and generates nothing; a real request decides whether the model is permitted.',

    /* ---- the batch pipeline page, moved out of this app to tools/advanced.html.
       Kept because several of these strings are also backend stage names and
       errors that still reach this UI through the toast. ---- */
    '🍳 论文 → 爆款科普视频 流水线': '🍳 Paper → explainer video pipeline',
    '批量上传论文 PDF → 自动迭代生成口播稿 + 日式手绘配图 + 爆款封面 → 上传口播视频自动剪辑':
      'Bulk-upload paper PDFs → iterate a narration script + hand-drawn illustrations + a cover → upload a talking-head video and it cuts itself',
    '📄 批量上传论文 PDF': '📄 Bulk-upload paper PDFs',
    '🚀 一键生成全部文稿+配图': '🚀 Generate every script + illustration',
    '🎙 全部生成TTS图文成片（免录口播）': '🎙 Render all as TTS videos (no recording)',
    '🎬 批量上传口播视频（按文件名自动配对）':
      '🎬 Bulk-upload talking-head videos (paired by file name)',
    '↻ 刷新': '↻ Refresh',
    '📂 选择导出文件夹…': '📂 Choose export folder…',
    '~/Desktop/paper2video导出': '~/Desktop/paper2video-export',
    '📦 导出选中项目（成片+封面+文案）': '📦 Export selected (video + cover + copy)',
    '全选/全不选': 'Select all / none',
    '隐藏已出片': 'Hide finished',
    '🙈 隐藏选中': '🙈 Hide selected',
    '选中': 'Select',
    '待生成项目': 'Not started',
    '🔁 重试': '🔁 Retry',
    '只重做这一步': 'Redo this step only',
    '📝 看/改文稿': '📝 View / edit script',
    '📋 标题/简介': '📋 Title / blurb',
    '📰 生成公众号文': '📰 Generate article',
    '📰 公众号docx': '📰 Article .docx',
    '🧑 手动传数字人': '🧑 Upload avatar manually',
    '🤖 数字人推理': '🤖 Avatar inference',
    '🤖 重跑数字人推理': '🤖 Re-run avatar inference',
    '数字人推理': 'Avatar inference',
    '重跑': 'Re-run',
    '重做': 'Redo',
    '重搜': 'search again',
    '🎞 实拍素材': '🎞 B-roll footage',
    '🎞 加实拍素材': '🎞 Add B-roll',
    '加实拍素材': 'Add B-roll',
    '↻ 重新搜一批': '↻ Search another batch',
    '还没有实拍素材': 'No B-roll yet',
    '▶️ 预览成片': '▶️ Preview video',
    '📋 发布物料': '📋 Publishing kit',
    '⬇ 口播成片': '⬇ Talking-head video',
    '原视频↗': 'Original ↗',
    '上传口播视频': 'Upload talking-head video',
    '重新剪辑口播': 'Re-cut talking head',
    '🎙 TTS图文成片': '🎙 TTS video',
    '🎙 重做TTS图文成片': '🎙 Redo TTS video',
    '↻ 重新生成': '↻ Regenerate',
    '生成文稿+配图': 'Generate script + illustrations',
    '补齐未完成环节': 'Finish the missing steps',
    '生成简介+候选标题': 'Generate blurb + title ideas',
    '保存简介': 'Save blurb',
    '复制简介': 'Copy blurb',
    '保存修改': 'Save changes',
    '运行日志': 'Run log',
    '小红书简介（可改）：': 'Blurb (editable):',
    '勾选标题（封面大字会自动重排）：': 'Pick a title (the cover headline re-flows):',
    '改完保存后，用你最终的这版文稿去录口播（逐字念），对齐才会准。':
      'Save your edits, then record the narration from this final script word for word — that is what makes the alignment accurate.',
    '还没有项目，先上传论文 PDF 吧 ☝️': 'No projects yet — upload a paper PDF first ☝️',
    '先勾选要隐藏的项目': 'Tick the projects you want to hide first',
    '先勾选要导出的项目': 'Tick the projects you want to export first',
    '没有待处理的项目': 'Nothing waiting to be processed',
    '没有待生成的项目': 'Nothing waiting to be generated',
    '已开始搜集 YouTube 实拍素材，完成后会自动重渲成片':
      'Started collecting YouTube B-roll; the video re-renders when it is done',
    '公众号图文已生成': 'Article generated',
    '数字人推理已排队（约10分钟，看卡片状态）':
      'Avatar inference queued (about 10 minutes — watch the card)',
    '数字人角标已合成进成片': 'Avatar badge composited into the video',
    '已复制': 'Copied',
    '未配对(请在卡片里单独上传):': 'Not paired (upload them on the card):',
    '（空）': '(empty)',
    '⚠️ 代码已更新但服务还在跑旧版本，改动尚未生效。现在没有任务在跑，可以安全重启服务。':
      '⚠️ The code changed but the server is still running the old build, so your edits are not live. Nothing is running, so it is safe to restart.',
    '（未生成，点上方按钮生成）': '(not generated — use the button above)',
    '全部': 'All',
    'TTS片': 'TTS cut',
    '口播片': 'Talking head',
    '配图': 'Illustrations',

    /* ---- backend errors, second pass ----
       Raised in Python and surfaced through toast() or a project card, so they
       are ordinary text nodes by the time the observer sees them. Interpolated
       ones live in RULES instead; the split is only about which mechanism can
       match, not about where the message came from. */
    '缺少深度大纲，请先重做「生成口播稿」': 'No chapter outline yet — redo “Write the narration” first',
    '没有这条预设': 'No such preset',
    '创作进行中，请完成后再改时长或章节': 'Creation in progress — change the duration or sections once it finishes',
    '未配置支持的图片 API 协议': 'No supported image API protocol is configured',
    '图片 API 未返回封面图片': 'The image API returned no cover image',
    '图片 API 未返回 base64 或下载 URL': 'The image API returned neither base64 data nor a download URL',
    '有讲解片段无法对应到实际词时间戳': 'A narration segment could not be matched to the real word timestamps',
    '旁白子句时间边界重复或倒序': 'Narration clause timings are duplicated or out of order',
    '深度文稿响应必须是结构化对象': 'The narration response must be a structured object',
    '章节不能缺少正文': 'A chapter cannot be missing its body text',
    '每章必须包含真实有效的 PDF 来源页码': 'Every chapter must cite real, valid PDF source pages',
    '章节引用了不存在的论文主图': 'A chapter cites a figure that does not exist',
    '深度讲解必须覆盖至少3张关键真实主图': 'An explainer must cover at least 3 of the paper’s real figures',
    '尚未生成深度章节': 'No chapters have been generated yet',
    '无法从视频抽帧': 'Could not extract a frame from the video',
    '互动讲解尚未生成完成': 'The interactive explainer is not finished yet',
    'Edge TTS 没有返回可对齐的词时间戳，请重试配音': 'Edge TTS returned no alignable word timestamps — try the narration again',
    'Edge TTS 时间戳不完整，无法精确驱动光标': 'Edge TTS timestamps are incomplete, so the cursor cannot be driven precisely',
    '配音文本不能为空': 'The narration text cannot be empty',
    '请先写下讲解重点，再保存为预设': 'Write the focus first, then save it as a preset',
    '内容包含无法保存的字符': 'The content contains characters that cannot be saved',
    '这条讲解重点已经保存过了': 'That focus is already saved',
    '内置预设不能改，可另存为自己的预设': 'A built-in preset cannot be edited — save your own copy instead',
    '内置预设不能删除': 'A built-in preset cannot be deleted',

    /* ---- focus presets: the dialog around them ----
       The presets themselves are served already in the right language and sit
       behind data-no-i18n. Everything here is the chrome around them, which is
       ordinary interface text and belongs to this module. */
    '＋ 我的预设': '+ My presets',
    '我的讲解重点': 'My focus presets',
    '保存在你这台电脑上，语言就是你写时的语言。内置预设不能改。':
      'Saved on this computer, in the language you wrote them. Built-in presets cannot be changed.',
    '还没有保存过。': 'Nothing saved yet.',
    '名称（可留空）': 'Name (optional)',
    '讲解重点': 'Focus',
    '用输入框里的内容填充': 'Fill from the composer',
    '保存预设': 'Save preset',
    '预设已保存': 'Preset saved',
    '预设已删除': 'Preset deleted',

    /* ---- the run log ----
       Written to log.txt in Chinese by the pipeline, and rendered by studio.js
       through t() a line at a time, with the [HH:MM:SS] stamp split off first.
       So the key here is the trimmed message: no stamp, no leading indent. */
    '深度科普：独立核对方法、数据、主图与来源页码':
      'Deep explainer: independently checking method, data, figures and source pages',
    '复用 Edge TTS 配音': 'Reusing the cached Edge TTS narration',
    '（复用缓存配音）': '(reusing cached narration)',
    '视觉兜底：这篇确实没有可讲的主图': 'Visual fallback: this paper really has no figure worth explaining',
    '这几页没有可用的文字层，跳过原文高亮':
      'These pages have no usable text layer; skipping source highlighting',
    '没有 paper.pdf，跳过原文高亮': 'No paper.pdf, so source highlighting is skipped',
    '（已在队列中，忽略重复触发）': '(already queued — ignoring the repeat)',
    '使用 faster-whisper 做词级对齐…': 'Aligning word by word with faster-whisper…',
    '合成数字人圆形角标…': 'Compositing the circular avatar badge…',
    '叠加顶部进度条…': 'Overlaying the progress bar…',

    /* ---- the run log: the dialog around it ---- */
    '尚未开始生成。': 'Nothing has been generated yet.',
    '实时跟踪中': 'Live',

    /* ---- script length and the audit switch ---- */
    '深度科普：跳过独立核对（可在设置里打开）':
      'Deep explainer: skipping the independent check (switch it on in settings)',
    '文稿质量 · 速度': 'Script quality · speed',
    '多一道独立核对，还是快一点出结果': 'One more independent check, or a faster result',
    '独立核对这一轮': 'The independent check',
    '写完后再对着原文和真图核一遍数值、图号和来源页码。实测约多花 2 分钟，是整条流水线最慢的一步。关掉时写作人格里的准确性约束仍然生效。':
      'After the draft, check the numbers, figure labels and source pages once more against the paper and the real figures. Measured at about 2 extra minutes — the slowest step in the pipeline. With it off, the accuracy constraints in the writing persona still apply.',

    /* ---- the 3:4 card deck ---- */
    '图文卡片 ↓': 'Card deck ↓',
    '生成进行中，完成后再导出图文卡片': 'Creation in progress — export the cards once it finishes',
    '还没有生成互动讲解，无法导出图文卡片': 'No interactive explainer yet, so there are no cards to export',
    '讲解里没有章节，无法导出图文卡片': 'The explainer has no chapters, so there are no cards to export',
  };

  /* Interpolated strings. A template's {} matches one run of text; the English
     side fills its {} from the matches in order. Anchored, so a placeholder can
     never swallow a neighbouring sentence of the paper. */
  const RULES = [
    ['{} · 已连接', '{} · connected'],
    ['{} 已连接', '{} connected'],
    ['{} · 来源 {}', '{} · from {}'],
    ['{} 个模型', '{} models'],
    ['{} 篇论文已加入队列', '{} papers queued for creation'],
    ['已切到 {}', 'Switched to {}'],
    ['◈ {} 张真实主图 · 保留原图与光标讲解', '◈ {} real figures · originals kept, narrated cursor'],
    ['{}的封面', 'Cover of {}'],
    ['移除 {}', 'Remove {}'],
    /* The two-page rule goes first: a single {} matches a run of any length, so
       '第{}页' would swallow '2–11' whole and the range form would never be tried. */
    ['第{}–{}页', 'pp. {}–{}'],
    ['第{}页', 'p. {}'],
    ['全讲 · {} 页', 'All of it · {} pages'],
    ['已选 {} 节 · {} 页', '{} sections · {} pages'],
    /* stages and errors from the backend */
    ['已中断（{}）', 'Interrupted ({})'],
    ['排队中（前面 {} 篇在跑，共 2 个工位）', 'Queued ({} running ahead; 2 slots)'],
    ['出错: {}', 'Error: {}'],
    ['剪辑出错: {}', 'Cut error: {}'],
    ['TTS 成片出错: {}', 'TTS video error: {}'],
    ['实拍素材 {} 段 ✓', '{} B-roll clips ✓'],
    ['实拍素材完成：{} 段', 'B-roll done: {} clips'],
    ['实拍素材失败: {}', 'B-roll failed: {}'],
    ['PDF 抽取 {} 字', 'Extracted {} characters from the PDF'],
    ['文稿核对完成，{} 字', 'Script checked — {} characters'],
    ['重试完成：{} ✓', 'Retry finished: {} ✓'],
    ['请先在设置中连接供应商 {}', 'Connect provider {} in settings first'],
    ['无法读取供应商状态：{}', 'Could not read provider status: {}'],
    ['需先在上方连接 {}', 'Connect {} above first'],
    ['请先在设置中连接语音供应商 {}', 'Connect speech provider {} in settings first'],
    ['语音供应商 {} 未连接：请先在设置中连接 {}', 'Speech provider {} is not connected — connect {} in settings first'],
    ['{} 语音合成失败（HTTP {}）：{}', '{} speech synthesis failed (HTTP {}): {}'],
    ['{} 语音合成失败：{}', '{} speech synthesis failed: {}'],
    ['{} 网络错误：{}', '{} network error: {}'],
    ['{} 没有返回音频：{}', '{} returned no audio: {}'],
    ['{} 没有返回时间戳：{}', '{} returned no timestamps: {}'],
    ['{} 没有返回可对齐的词时间戳，请重试配音', '{} returned no alignable word timestamps — try the narration again'],
    ['{} 时间戳不完整，无法精确驱动光标', '{} timestamps are incomplete, so the cursor cannot be driven precisely'],
    ['{} 逐句合成 {} 句', '{}: synthesized {} sentences one by one'],
    ['语音音频转换失败: {}', 'Speech audio conversion failed: {}'],
    ['语音列表读取失败：{}', 'Could not load the speech providers: {}'],
    ['{} 验证失败：{}', '{} check failed: {}'],
    ['语言连接已就绪：{} · {}', 'Language connection ready: {} · {}'],
    ['未知环节: {}', 'Unknown step: {}'],
    ['{} 的模型目录里没有 {}', '{}’s catalog has no {}'],
    ['语言 API 验证失败（HTTP {}），请检查 Key 和额度',
      'Language API check failed (HTTP {}) — check the key and your credit'],
    ['读取模型失败（HTTP {}），请检查端点和凭据',
      'Could not load models (HTTP {}) — check the endpoint and credentials'],
    ['供应商 {} 未连接，请在「供应商与模型」中连接',
      'Animation provider {} is not connected — connect it under Providers & models'],
    /* more tools */
    ['👁 显示全部（已隐藏 {}）', '👁 Show all ({} hidden)'],
    ['全部 {} 个项目都被隐藏了，点「显示全部」找回',
      'All {} projects are hidden — click “Show all” to bring them back'],
    ['🎞 实拍×{} 重搜', '🎞 B-roll ×{} · search again'],
    ['🎞 看素材({})', '🎞 B-roll ({})'],
    ['实拍×{} 重搜', 'B-roll ×{} · search again'],
    ['场景 {} ｜ 搜索词：{}', 'Scene {} | query: {}'],
    ['来源：{}《{}》', 'Source: {} — “{}”'],
    ['迭代评审：{} ｜ {} 字 ≈ {} 分钟', 'Review: {} | {} chars ≈ {} min'],
    ['第{}轮 平均{}分', 'Round {} · avg {}'],
    ['{} ｜ 📊 主图×{}', '{} | 📊 figures ×{}'],
    ['已开始 {} 个 TTS 成片', 'Started {} TTS videos'],
    ['已开始生成 {} 篇', 'Started generating {}'],
    ['只重做「{}」这一个环节？\n其它环节的成果不会动。',
      'Redo only the “{}” step?\nNothing produced by the other steps is touched.'],
    ['无法启动：{}', 'Could not start: {}'],
    ['生成失败：{}', 'Generation failed: {}'],
    ['导出完成 → {}', 'Export finished → {}'],
    ['✓ {} → {} 个文件', '✓ {} → {} files'],
    ['✗ {}: {}', '✗ {}: {}'],
    ['当前有 {} 个任务在跑，等跑完再重启服务。',
      '{} job(s) are running — restart once they finish.'],
    ['⚠️ 代码已更新但服务还在跑旧版本，改动尚未生效。当前有 {} 个任务在跑，等跑完再重启服务。',
      '⚠️ The code changed but the server is still running the old build, so your edits are not live. {} job(s) are running — restart once they finish.'],
    /* ---- backend errors, interpolated ----
       Anchored at both ends, which is what keeps '第{}页' above from swallowing
       '第5页不在选定的章节范围内' here. */
    ['找不到 {}（{}）。', 'Cannot find {} ({}).'],
    ['供应商 {} 未连接：{}', 'Provider {} is not connected: {}'],
    ['模型 {} 请求重试 {} 次仍失败：{}', 'Model {} still failed after {} retries: {}'],
    ['模型 {} 请求失败：{}', 'Model {} request failed: {}'],
    ['模型 {} 是异步批处理版本，不能用于当前 Chat Completions / Pi 工作流。请在模型与声音中改用 {}。',
      'Model {} is an async batch variant and cannot serve this Chat Completions / Pi workflow. Switch to {} under Models & voice.'],
    ['时长请在 {}–{} 分钟之间', 'Duration must be between {} and {} minutes'],
    ['不支持的讲解语言: {}', 'Unsupported narration language: {}'],
    ['这篇论文没有这些小节: {}', 'This paper has no such sections: {}'],
    ['光标动画编码失败: {}', 'Cursor animation encoding failed: {}'],
    ['旁白词时间戳覆盖不足：{}', 'Narration word-timestamp coverage is too low: {}'],
    ['深度内容需要{}–{}章，当前{}章', 'An explainer needs {}–{} chapters; this one has {}'],
    ['第{}页不在选定的章节范围内，只能引用所选小节的页码',
      'Page {} is outside the selected sections; only pages from those sections may be cited'],
    ['深度正文需{}–{}字（约{}分钟），当前{}字',
      'The narration needs {}–{} characters (about {} minutes); this one has {}'],
    ['数字人合成失败: {}', 'Avatar compositing failed: {}'],
    ['进度条合成失败: {}', 'Progress-bar compositing failed: {}'],
    ['分段数字人合成失败: {}', 'Per-segment avatar compositing failed: {}'],
    ['ffmpeg 失败: {}', 'ffmpeg failed: {}'],
    ['拼接失败: {}', 'Concatenation failed: {}'],
    ['ffmpeg 分段失败: {}', 'ffmpeg segment step failed: {}'],
    ['ffmpeg 拼接失败: {}', 'ffmpeg concatenation failed: {}'],
    ['章节{}的论文页渲染失败', 'Rendering the paper pages for chapter {} failed'],
    ['章节{}既没有主图，也没有可读的论文 PDF',
      'Chapter {} has neither a figure nor a readable paper PDF'],
    ['旁白拼接失败: {}', 'Narration concatenation failed: {}'],
    ['Edge TTS 音频转换失败: {}', 'Edge TTS audio conversion failed: {}'],
    ['讲解重点请控制在{}字以内', 'Keep the focus under {} characters'],
    ['自定义预设最多{}条，请先删掉一些', 'At most {} custom presets — delete some first'],
    /* ---- the run log, interpolated ---- */
    ['主图提取失败（继续无图流程）: {}', 'Figure extraction failed (continuing without figures): {}'],
    ['{} 定位到相关子图 {}', '{} located the relevant subpanel {}'],
    ['跳过「{}」（已有产出）', 'Skipping “{}” — already produced'],
    ['「{}」失败: {}', '“{}” failed: {}'],
    ['⚠ 重试了上游环节，这些下游产物可能已对不上，需要时请单独重试：{}',
      '⚠ An upstream step was redone, so these downstream results may no longer match; retry them individually if needed: {}'],
    ['讲图时段隐藏人像: {}', 'Avatar hidden while a figure is being explained: {}'],
    ['whisper 对齐失败，退回比例对齐: {}',
      'Whisper alignment failed; falling back to proportional alignment: {}'],
    ['比例对齐：说话区间 {}s ~ {}s / 总长 {}s',
      'Proportional alignment: speech from {}s to {}s of {}s total'],
    ['跟随式光标动画 {}（{}帧）✓', 'Following cursor animation {} ({} frames) ✓'],
    ['光标动画 {} ✓', 'Cursor animation {} ✓'],
    ['AI Image 封面 · {}', 'AI image cover · {}'],
    ['只讲选定的 {} 个小节：{} 页，{} 张主图',
      'Explaining only the {} selected sections: {} pages, {} figures'],
    ['深度科普：规划约{}字、{}–{}章（口播约{}分钟）',
      'Deep explainer: planning about {} characters in {}–{} chapters (about {} minutes spoken)'],
    ['深度文稿结构修正: {}', 'Narration structure corrected: {}'],
    ['深度核对: {}', 'Accuracy check: {}'],
    ['深度正文完成：{}字，{}章，来源页码已附',
      'Narration complete: {} characters, {} chapters, source pages attached'],
    ['分段合成数字人角标（{} 段出镜）…', 'Compositing the avatar badge per segment ({} on camera)…'],
    ['合成：开头 {}s 全屏人像 → {} 段素材在框内 + 圆形人像压顶…',
      'Compositing: {}s full-screen presenter, then {} clips in frame with the circular avatar on top…'],
    ['实时章节 {}/{}：配音与同步，不渲染视频帧',
      'Live chapter {}/{}: narration and sync, no video frames rendered'],
    ['实时互动讲解完成：{}章，{}分钟；无需渲染MP4',
      'Interactive explainer finished: {} chapters, {} minutes — no MP4 needed'],
    ['ONNX 检出主图 {} 张', 'ONNX detected {} figures'],
    ['视觉兜底：选页失败（{}），按无图流程继续',
      'Visual fallback: page selection failed ({}); continuing without figures'],
    ['视觉兜底：第 {} 页可能有主图，逐页定位…',
      'Visual fallback: page {} may hold a figure; locating page by page…'],
    ['第{}页定位失败: {}', 'Locating page {} failed: {}'],
    ['视觉兜底：补到 {} 张主图', 'Visual fallback: recovered {} figures'],
    ['pdfium 标题搜索失败: {}', 'pdfium title search failed: {}'],
    ['标题截图 {}x{} ✓', 'Title screenshot {}x{} ✓'],
    ['标题截图失败: {}', 'Title screenshot failed: {}'],
    ['选帧失败用中间帧: {}', 'Frame selection failed; using the middle frame: {}'],
    ['头像选帧 t={}s ✓', 'Avatar frame chosen at t={}s ✓'],
    ['图注生成失败 {}: {}', 'Caption generation failed for {}: {}'],
    ['剔除非插图（标题横幅/页眉等）：{}', 'Dropped non-figures (title banners, headers): {}'],
    ['逐句区域映射失败: {}', 'Per-sentence region mapping failed: {}'],
    ['原文高亮 {}/{} 句，关键词 {} 处（共 {} 句可选）',
      'Source highlighting: {}/{} sentences, {} keyword hits ({} sentences available)'],
    ['章节{}：绘制参数变了，就地重算位置，没有再请求模型',
      'Chapter {}: drawing parameters changed, so positions were recomputed locally without calling the model'],
    ['原文定位：章节{}，{}句，PDF 第{}页', 'Source located: chapter {}, {} sentences, PDF page {}'],
    ['原文定位失败，改用示意图: {}', 'Source location failed; using a schematic instead: {}'],
    ['TTS 配音 {}/{}…', 'TTS narration {}/{}…'],
    ['步骤 {}/{}', 'Step {} of {}'],
    ['已运行 {}', 'Running for {}'],
    ['深度正文需至少{}字（约{}分钟），当前{}字',
      'The narration needs at least {} characters (about {} minutes); this one has {}'],
    ['深度正文{}字远超{}字的目标，疑似失控，请重试',
      'The narration ran to {} characters against a {} target — that looks like a lost brief; please retry'],
    ['讲解会比要求的长：{}字 ≈ {}分钟（目标{}分钟）',
      'The explainer will run longer than asked: {} characters ≈ {} minutes (target {} minutes)'],
    ['章节{}：原文高亮{}条对不上{}句讲解，这一章只显示页面',
      'Chapter {}: {} source highlights do not line up with {} narration cues, so this chapter just shows the page'],
    ['口令至少 {} 位', 'The passphrase needs at least {} characters'],
    ['图文卡片 {}/{}：封面', 'Card {} of {}: the cover'],
    ['图文卡片 {}/{}：第{}章', 'Card {} of {}: chapter {}'],
    ['图文讲解卡片完成：{} 张 3:4 图片', 'Card deck finished: {} images at 3:4'],
    ['标题截图跳过: {}', 'Title screenshot skipped: {}'],
  ];

  const escape = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  /* A placeholder spans a line break only when the template itself does. Without
     that, '导出完成 → {}' would swallow the per-file lines after it and they would
     never reach the line-by-line pass in t(). */
  const compiled = RULES.map(([zh, en]) => ({
    re: new RegExp('^' + zh.split('{}').map(escape)
      .join(zh.includes('\n') ? '([\\s\\S]+?)' : '([^\\n]+?)') + '$'),
    en,
  }));

  function lookup(text) {
    if (DICT[text] !== undefined) return DICT[text];
    if (!HAN.test(text)) return undefined;        // already English, or pure symbols
    for (const { re, en } of compiled) {
      const m = text.match(re);
      // A placeholder usually holds a number or a file name, which passes through
      // untouched -- but it can hold a stage name the dictionary already knows,
      // as in 只重做「生成分镜」.
      // A placeholder holds a number or a file name most of the time, and those
      // pass through untouched. But it can also hold a whole message: the log
      // line '深度文稿结构修正: {}' carries a validation error that is itself a
      // translatable template. So the fill is the full lookup, recursively,
      // not just a dictionary hit -- otherwise the outer half of the sentence
      // turns English and the inner half stays Chinese.
      if (m) {
        let i = 0;
        return en.replace(/\{\}/g, () => {
          const value = m[++i];
          // Guard the degenerate template '{}', whose capture is the whole
          // input and would recurse forever.
          return (value === text ? undefined : lookup(value)) ?? value;
        });
      }
    }
    return undefined;
  }

  /* Their CONTENT is not interface: the script in a textarea, the creation log in
     a <pre>, the animation canvas. Their own attributes still are -- a textarea's
     placeholder and a canvas's aria-label are written by this app, not by the
     paper -- so these are skipped for text and kept for attributes.
     Everything else is filtered by the dictionary itself: the paper's own words
     never match a key. */
  const SKIP = new Set(['SCRIPT', 'STYLE', 'TEXTAREA', 'CANVAS', 'PRE', 'CODE', 'IFRAME']);
  const SKIP_SELECTOR = 'script,style,textarea,canvas,pre,code,iframe';
  const ATTRS = ['placeholder', 'title', 'aria-label', 'alt'];   // never value or data-prompt

  /* Remembers both sides: the Chinese a node held and the English we put there.
     Keeping the English lets us tell "the app just wrote new Chinese here" from
     "this is still our own output", which is what makes a re-render land correctly
     and what stops the observer from reacting to its own writes. */
  const mark = new WeakMap();        // text node -> {zh, en}
  const markAttr = new WeakMap();    // element -> {attr: {zh, en}}
  let lang = 'zh';

  function applyText(node) {
    const current = node.nodeValue;
    const seen = mark.get(node);
    // If the value is no longer the English we wrote, the view replaced it.
    const source = seen && current === seen.en ? seen.zh : current;
    if (lang === 'zh') {
      if (seen && current === seen.en) { mark.delete(node); node.nodeValue = seen.zh; }
      return;
    }
    // Keep surrounding whitespace: markup indentation, and the trailing space that
    // separates a heading from its counter, both matter.
    const m = source.match(/^(\s*)([\s\S]*?)(\s*)$/);
    const hit = m[2] && lookup(m[2]);
    if (hit === undefined || hit === false) { mark.delete(node); return; }
    const next = m[1] + hit + m[3];
    if (next === current) return;    // already right; assigning again would re-fire
    mark.set(node, { zh: source, en: next });
    node.nodeValue = next;
  }

  function applyAttrs(el) {
    for (const name of ATTRS) {
      if (!el.hasAttribute(name)) continue;
      const current = el.getAttribute(name);
      const saved = markAttr.get(el) || {};
      const seen = saved[name];
      const source = seen && current === seen.en ? seen.zh : current;
      if (lang === 'zh') {
        if (seen && current === seen.en) { delete saved[name]; el.setAttribute(name, seen.zh); }
        continue;
      }
      const hit = lookup(source.trim());
      if (hit === undefined) { delete saved[name]; continue; }
      if (hit === current) continue;
      saved[name] = { zh: source, en: hit };
      markAttr.set(el, saved);
      el.setAttribute(name, hit);
    }
  }

  function walk(root) {
    if (root.nodeType === Node.TEXT_NODE) { applyText(root); return; }
    if (root.nodeType !== Node.ELEMENT_NODE && root.nodeType !== Node.DOCUMENT_FRAGMENT_NODE) return;
    if (root.nodeType === Node.ELEMENT_NODE) {
      if (root.hasAttribute('data-no-i18n')) return;
      applyAttrs(root);
      if (SKIP.has(root.tagName)) return;      // its attributes done, its text is content
    }
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT | NodeFilter.SHOW_ELEMENT, {
      acceptNode: (n) => (n.nodeType === Node.ELEMENT_NODE
        ? (SKIP.has(n.tagName) || n.hasAttribute('data-no-i18n')
          ? NodeFilter.FILTER_REJECT : NodeFilter.FILTER_ACCEPT)
        : NodeFilter.FILTER_ACCEPT),
    });
    for (let n = walker.nextNode(); n; n = walker.nextNode()) {
      if (n.nodeType === Node.TEXT_NODE) applyText(n);
      else applyAttrs(n);
    }
    // The walker rejects the content-bearing tags outright, so reach their
    // attributes separately or the composer's placeholder stays Chinese.
    if (root.querySelectorAll) {
      for (const el of root.querySelectorAll(SKIP_SELECTOR)) {
        if (!el.closest('[data-no-i18n]')) applyAttrs(el);
      }
    }
  }

  const zhTitle = document.title;
  function setLang(next, persist = true) {
    lang = next === 'en' ? 'en' : 'zh';
    if (persist) { try { localStorage.setItem(STORE, lang); } catch (e) { /* private mode */ } }
    document.documentElement.lang = lang === 'en' ? 'en' : 'zh-CN';
    document.title = lang === 'en' ? (lookup(zhTitle) ?? zhTitle) : zhTitle;
    walk(document.body);
    const button = document.querySelector('.lang-toggle');
    if (button) {
      button.textContent = lang === 'en' ? '中文' : 'EN';
      button.setAttribute('aria-label', lang === 'en' ? 'Switch to Chinese' : '切换到英文');
      button.setAttribute('data-no-i18n', '');
    }
    /* Content this module cannot translate -- anything that travels as a value
       rather than as a text node, like the focus presets -- is rendered by its
       own owner in the current language. That owner needs to know when the
       language changed, and walk() cannot tell it: the whole point is that
       walk() never touches those strings. */
    document.dispatchEvent(new CustomEvent('i18n:languagechange', { detail: { lang } }));
  }

  /* characterData matters as much as childList: studio.js updates a heading with
     `$('#collectionTitle').firstChild.textContent = ...`, which writes to the text
     node itself and never touches its parent's children. Translating is idempotent
     (applyText assigns nothing when the value is already right), so watching our
     own writes settles instead of looping. Attributes stay unobserved -- the view
     only ever sets them through innerHTML, which childList already covers. */
  const observer = new MutationObserver((records) => {
    if (lang === 'zh') return;
    for (const record of records) {
      if (record.type === 'characterData') applyText(record.target);
      else for (const node of record.addedNodes) walk(node);
    }
  });

  function toggle() {
    const button = document.createElement('button');
    button.className = 'lang-toggle';
    button.type = 'button';
    button.setAttribute('data-no-i18n', '');
    button.onclick = () => setLang(lang === 'en' ? 'zh' : 'en');
    const style = document.createElement('style');
    style.textContent = '.lang-toggle{font:inherit;font-size:13px;line-height:1;padding:7px 12px;'
      + 'border:1px solid currentColor;border-radius:999px;background:transparent;color:inherit;'
      + 'opacity:.72;cursor:pointer;letter-spacing:.04em}'
      + '.lang-toggle:hover{opacity:1}'
      + '.lang-toggle.floating{position:fixed;top:14px;right:16px;z-index:9999;'
      + 'background:#fffdf8;color:#3d2f26;box-shadow:0 2px 10px rgba(80,60,40,.18)}';
    document.head.appendChild(style);
    const slot = document.querySelector('[data-lang-slot]');
    if (slot) slot.appendChild(button);
    else { button.classList.add('floating'); document.body.appendChild(button); }
    return button;
  }

  function start() {
    toggle();
    let saved = null;
    try { saved = localStorage.getItem(STORE); } catch (e) { /* private mode */ }
    setLang(saved === 'en' ? 'en' : 'zh', false);
    observer.observe(document.body, { childList: true, subtree: true, characterData: true });
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start);
  else start();

  /* For text that never reaches the DOM: alert(), confirm(). */
  function t(s) {
    if (lang !== 'en') return s;
    const whole = lookup(s);
    if (whole !== undefined) return whole;
    // alert() text is often one summary line plus a line per file; each line is
    // a unit the dictionary can know, even when the whole string is not.
    if (!s.includes('\n')) return s;
    return s.split('\n').map((line) => lookup(line.trim()) ?? line).join('\n');
  }

  window.i18n = { t, setLang, get lang() { return lang; } };
})();
