/* Bilingual UI. Chinese stays the source of truth in the markup and the view
   code; this file is the only place English lives.

   Why the DOM and not templates: interface text, the paper's own words and the
   model's output all land in one tree -- a chapter title sitting next to a "next
   chapter" button -- and the backend sends stage names and error details as data
   that the view pastes straight in. Keying the dictionary on the Chinese source
   means the interface translates, the paper passes through untouched because it
   never matches a key, and studio.js / watch.js / the backend need no edits.

   Deliberately NOT translated, because they are the film and not the interface:
   narration, subtitles, chapter titles and summaries, the animation canvas
   (motion-diagrams.js also matches Chinese narration with regexes -- translating
   it would break which animation gets chosen), and the creation log. */
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
    '你的知识创作空间': 'Your space for making sense of science',
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
    '知识有出处，理解有过程。': 'Sourced knowledge. Understanding with steps.',

    /* ---- home: composer ---- */
    '讲解时长': 'Length',
    '自动': 'Auto',
    '分钟': 'min',
    '不选就是全讲。勾中的小节决定讲什么——写作时只会读到这些页，其余部分不会出现在讲解里。':
      'Pick nothing and the whole paper is explained. Whatever you tick decides the scope — the writer is shown only those pages, and nothing else reaches the explainer.',
    '全讲': 'Explain all',
    '讲解重点': 'What to focus on',
    '上传论文，或先告诉我你想重点弄懂什么……\n比如：讲清实验设计、带我读懂关键主图，并区分结论和局限。':
      'Upload a paper, or tell me what you want to understand first…\nFor example: explain the experimental design, walk me through the key figure, and separate conclusions from limits.',
    '添加论文': 'Add a paper',
    '添加论文 ↗': 'Add a paper ↗',
    '◈ 深度科普': '◈ Deep explainer',
    '16:9 互动讲解': '16:9 interactive',
    '开始创作': 'Start creating',
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
    '你的第一篇深度讲解，从这里开始。': 'Your first explainer starts here.',
    '选择一篇论文，剩下的交给 aha-paper。': 'Pick a paper; aha-paper takes it from there.',
    '没有找到这个故事。': 'No story found.',
    '作品正在酝酿中。': 'Still in the works.',
    '下一个故事，从这里开始。': 'Your next story starts here.',
    '试试论文标题或文件名中的其他关键词。': 'Try another word from the title or file name.',
    '上传一篇你想讲给世界听的论文。': 'Upload a paper you want to tell the world about.',

    /* ---- home: explore ---- */
    '创作方向': 'A direction',
    '不只看结论，': 'Don’t just read the conclusion —',
    '真正看懂一张图。': 'really see the figure.',
    '原图 · 局部放大 · 随声光标': 'Original figure · zoom · narrated cursor',
    '用这个方向创作 ↗': 'Create in this direction ↗',

    /* ---- project cards ---- */
    '未命名论文': 'Untitled paper',
    '论文讲解': 'Paper explainer',
    '等待灵感启程': 'Waiting to begin',
    '创作进行中…': 'Creating…',
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
    '先连接 OpenRouter，即可开始创作': 'Connect OpenRouter to start creating',
    '先配置 API，已选论文会保留': 'Set up the API first — your selected papers are kept',
    '已开始创作：论文 → 深度文章 → 实时动画 → 互动讲解':
      'Started: paper → article → live animation → interactive explainer',
    '已开始按需渲染 MP4；互动网页版可直接观看。':
      'Rendering MP4 on demand; the interactive version is ready to watch now.',

    /* ---- dialogs ---- */
    '论文短片': 'Paper film',
    '真实论文主图 · 光标讲解 · 自然配音': 'Real figures · narrated cursor · natural voice',
    '作品封面': 'Cover art',
    '下载封面 ↓': 'Download cover ↓',
    '创作日志': 'Creation log',
    '尚未开始生成。': 'Not started yet.',
    '让每句话，都有依据。': 'Every sentence, backed by the paper.',
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
    '原图有据，讲述有光。': 'Real figures. Clear telling.',
    '正在打开你的论文故事…': 'Opening your paper’s story…',
    '← 上一章': '← Previous',
    '下一章 →': 'Next →',
    '全屏观看': 'Fullscreen',
    '退出全屏': 'Exit fullscreen',
    '这篇论文，怎么讲？': 'How does this paper go?',
    '点击任意章节，自由跳转。': 'Click any chapter to jump.',
    '下载媒体 ↓': 'Download media ↓',
    '下载互动包 ↓': 'Download bundle ↓',
    '下载纯视频 ↓': 'Download video only ↓',
    '下载旁白 ↓': 'Download narration ↓',
    '互动包解压后打开 index.html，即可离线观看。':
      'Unzip the bundle and open index.html to watch offline.',
    '这是一份可离线使用的 aha-paper 互动作品。': 'An offline aha-paper interactive.',
    '暂时无法打开作品': 'Can’t open this work right now',
    '这个故事，还在准备中。': 'This story is still being prepared.',
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
    '小红书文案': 'Social copy',
    '批量绘图': 'Drawing illustrations',
    '光标动画': 'Cursor animation',
    '实拍素材': 'B-roll footage',
    '制作封面': 'Making the cover',
    '小红书图文版': 'Social image post',
    '公众号图文': 'Article version',
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
    '数字人已在 .env 里关闭（AVATAR_ENABLED=0）': 'Avatar is switched off in .env (AVATAR_ENABLED=0)',
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
  };

  /* Interpolated strings. A template's {} matches one run of text; the English
     side fills its {} from the matches in order. Anchored, so a placeholder can
     never swallow a neighbouring sentence of the paper. */
  const RULES = [
    ['{} · 已连接', '{} · connected'],
    ['{} 已连接', '{} connected'],
    ['{} · 来源 {}', '{} · from {}'],
    ['{} 个模型', '{} models'],
    ['{} 篇论文已进入创作队列', '{} papers queued for creation'],
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
      if (m) { let i = 0; return en.replace(/\{\}/g, () => DICT[m[++i]] ?? m[i]); }
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
