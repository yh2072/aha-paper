'use strict';
const $=s=>document.querySelector(s);
let projects=[],settings={},view='all',uploading=false,lastSignature='',showAll=false,pendingPapers=[];
const busy=p=>['queued','running','editing'].includes(p.state);
const escapeHtml=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const file=(p,name)=>'/files/'+encodeURIComponent(p.id)+'/'+name.split('/').map(encodeURIComponent).join('/');
async function api(path,options={}){const res=await fetch(path,options);if(res.status===401){location.href='/login?next='+encodeURIComponent(location.pathname+location.search);return new Promise(()=>{})}let data;try{data=await res.json()}catch{throw Error('服务暂时不可用')}if(!res.ok)throw Error(typeof data.detail==='string'?data.detail:'请求失败，请稍后重试');return data}
const jsonOptions=(method,data)=>({method,headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});
let toastTimer;
function toast(message){$('#toast').textContent=message;$('#toast').classList.add('show');clearTimeout(toastTimer);toastTimer=setTimeout(()=>$('#toast').classList.remove('show'),4500)}
function modal(html){$('#modalBody').innerHTML=html;if(!$('#modal').open)$('#modal').showModal()}
$('#closeModal').onclick=()=>{$('#modal').close();$('#modalBody').replaceChildren()};
$('#modal').addEventListener('close',()=>$('#modalBody').replaceChildren());
function connection(){const configured=settings.configured;$('#connectionText').textContent=configured?'OpenRouter 已配置':'连接 OpenRouter';$('#connection .status-dot').style.background=configured?'#87a170':'#c4a06a'}
async function refresh(force=false){try{projects=await api('/api/projects');const signature=JSON.stringify(projects);if(force||lastSignature!==signature){lastSignature=signature;render()}$('#doneNav').textContent=projects.filter(p=>p.interactive||p.tts_output||p.output).length}catch(e){toast(e.message)}}
function render(){const query=$('#search').value.trim().toLowerCase();const visible=projects.filter(p=>(view!=='done'||p.interactive||p.tts_output||p.output)&&(!query||[p.title,p.paper_title,p.pdf_name].some(x=>String(x||'').toLowerCase().includes(query)))).sort((a,b)=>String(b.created).localeCompare(String(a.created)));
$('#allNav').textContent=projects.length;$('#projectCount').textContent=visible.length;$('#viewAll').hidden=!!query||view==='done'||visible.length<=6;$('#viewAll').textContent=showAll?'收起 ↑':'查看全部 ↗';$('#empty').hidden=visible.length>0;$('#collectionTitle').firstChild.textContent=view==='done'?'深度讲解 ':showAll?'我的论文 ':'最近项目 ';
$('#projects').innerHTML=(showAll||query||view==='done'?visible:visible.slice(0,6)).map(p=>{const title=p.title||p.paper_title||p.pdf_name?.replace(/\.pdf$/i,'')||'未命名论文';const running=busy(p),output=p.tts_output||p.output,hasExperience=!!(p.interactive||output);const cover=p.cover?`<img src="${file(p,'images/'+p.cover)}?v=${encodeURIComponent((p.title||'')+p.stage)}" alt="${escapeHtml(title)}的封面" loading="lazy">`:`<div class="project-placeholder"><span>${escapeHtml(title.slice(0,24))}</span></div>`;let progress=10;const stage=p.stage||'';if(p.script)progress=35;if(p.storyboard)progress=50;if(p.video_engine)progress=65;if(p.cover)progress=75;if(hasExperience)progress=100;
return `<article class="project" data-id="${escapeHtml(p.id)}"><div class="project-cover">${cover}<span class="project-tag">${running?'<i class="busy-dot"></i>':''}${escapeHtml(p.stage||'尚未开始')}</span></div><div class="project-body"><h3>${escapeHtml(title)}</h3><div class="project-source" title="${escapeHtml(p.pdf_name)}">${escapeHtml(p.paper_title||p.pdf_name)}</div>${p.figures?.length?`<div class="project-figures">◈ ${p.figures.length} 张真实主图 · 保留原图与光标讲解</div>`:''}${running?`<div class="project-progress"><span style="width:${progress}%"></span></div>`:''}${p.error?`<div class="project-error">${escapeHtml(p.error)}</div>`:''}<div class="project-footer">${hasExperience?`<a class="primary" href="/watch/${encodeURIComponent(p.id)}"><img class="emoji" src="/assets/emoji/25b6.svg" alt=""> 进入互动讲解</a>${output?`<button data-action="preview">仅看视频</button><a download href="${file(p,output)}">下载 MP4 ↓</a>`:'<button data-action="mp4">按需导出 MP4</button>'}<button data-action="generate" ${running?'disabled':''}>${running?'生成中…':'重新生成 ↗'}</button>`:`<button class="primary" data-action="generate" ${running?'disabled':''}>${running?'生成中…':p.state==='error'?'继续生成 ↗':'生成深度讲解 ↗'}</button>`}${p.cover?'<button data-action="cover">封面</button>':''}${p.script?'<button data-action="script">文稿</button>':''}<button data-action="log">日志</button></div></div></article>`}).join('');
if(!visible.length){$('#empty h3').textContent=query?'没有匹配的论文。':view==='done'?'还没有完成的讲解。':'还没有讲解。';$('#empty p').textContent=query?'试试论文标题或文件名中的其他关键词。':'添加一篇 PDF，它会按原文逐句讲一遍。'} }
$('#search').addEventListener('input',render);$('#refresh').onclick=()=>refresh(true);$('#emptyUpload').onclick=()=>$('#paperInput').click();
document.querySelectorAll('[data-view]').forEach(button=>button.onclick=()=>{view=button.dataset.view;showAll=true;$('#homeNav').classList.remove('active');document.querySelectorAll('[data-view]').forEach(b=>b.classList.toggle('active',b===button));render();$('#collectionTitle').scrollIntoView({behavior:'smooth',block:'center'})});
async function generate(p){if(!settings.configured){showSettings();toast('先连接 OpenRouter');return}await api('/api/generate/'+encodeURIComponent(p.id),{method:'POST'});toast('已开始：读取 PDF → 生成讲稿 → 对齐原文 → 合成讲解');await refresh(true)}
function attachments(){
$('#attachmentList').innerHTML=pendingPapers.map((f,i)=>`<div class="paper-attachment"><span><img class="emoji" src="/assets/emoji/1f4c4.svg" alt=""> ${escapeHtml(f.name)}</span><button data-remove="${i}" aria-label="移除 ${escapeHtml(f.name)}"><img class="emoji" src="/assets/emoji/2716.svg" alt=""></button></div>`).join('');$('#createExplain').disabled=uploading||!pendingPapers.length;
}
function addPapers(files){const pdfs=[...files].filter(f=>f.name.toLowerCase().endsWith('.pdf'));if(pdfs.length!==files.length)toast('请添加 PDF 文件');for(const f of pdfs)if(!pendingPapers.some(p=>p.name===f.name&&p.size===f.size))pendingPapers.push(f);attachments()}
$('#paperInput').onchange=e=>{addPapers([...e.target.files]);e.target.value=''};
$('#attachmentList').onclick=e=>{const b=e.target.closest('[data-remove]');if(b&&!uploading){pendingPapers.splice(Number(b.dataset.remove),1);attachments()}};
for(const name of ['dragenter','dragover'])$('#paperDrop').addEventListener(name,e=>{e.preventDefault();$('#paperDrop').classList.add('dragging')});
for(const name of ['dragleave','drop'])$('#paperDrop').addEventListener(name,e=>{e.preventDefault();$('#paperDrop').classList.remove('dragging');if(name==='drop'&&!uploading)addPapers([...e.dataTransfer.files])});

/* The paper decides whether this appears at all: a journal PDF has no bookmarks,
   so there is nothing to choose and the upload goes straight to work. Picking a
   section is not a hint — the writer is only shown those pages. */
async function chooseSections(project){
 let data;
 try{data=await api('/api/projects/'+encodeURIComponent(project.id)+'/outline')}catch{return []}
 const entries=(data.entries||[]).filter(e=>e.level<=1);
 if(entries.filter(e=>e.level===0).length<2)return [];
 const pages=new Set();entries.forEach(e=>{for(let n=e.page;n<=e.end_page;n++)pages.add(n)});
 const total=Math.max(...entries.map(e=>e.end_page));
 return await new Promise(resolve=>{
  modal(`<h2>${esc2(project.title||project.pdf_name||'这篇论文')}</h2>`
   +`<p>不选就是全讲。勾中的小节决定讲什么——写作时只会读到这些页，其余部分不会出现在讲解里。</p>`
   +`<div class="outline-pick">`+entries.map(e=>
     `<label class="${e.level?'sub':''}"><input type="checkbox" value="${esc2(e.id)}" data-from="${e.page}" data-to="${e.end_page}">`
     +`<span>${esc2(e.title)}</span><span class="pages">${e.end_page>e.page?`第${e.page}–${e.end_page}页`:`第${e.page}页`}</span></label>`).join('')
   +`</div><div class="dialog-actions"><span class="pick-summary" id="pickSummary"></span>`
   +`<button id="pickAll">全讲</button><button class="primary" id="pickGo">生成讲解</button></div>`);
  const boxes=()=>[...document.querySelectorAll('.outline-pick input:checked')];
  const summary=()=>{const on=boxes();
   const n=on.length?new Set(on.flatMap(b=>{const out=[];for(let i=+b.dataset.from;i<=+b.dataset.to;i++)out.push(i);return out})).size:total;
   $('#pickSummary').textContent=on.length?`已选 ${on.length} 节 · ${n} 页`:`全讲 · ${total} 页`};
  summary();
  document.querySelector('.outline-pick').onchange=summary;
  let done=false;
  const finish=ids=>{if(done)return;done=true;$('#modal').close();resolve(ids)};
  $('#pickAll').onclick=()=>finish([]);
  $('#pickGo').onclick=()=>finish(boxes().map(b=>b.value));
  $('#modal').addEventListener('close',()=>finish([]),{once:true});
 });
}
const esc2=s=>escapeHtml(String(s??''));

/* The field accepts any number so a length between the presets is one keystroke
   away; the writer's own band is 3-30 minutes, so a typed value is pulled into it
   here rather than failing the upload after the files are already sent. */
$('#targetMinutes').onchange=()=>{const el=$('#targetMinutes'),raw=el.value.trim();
 if(!raw){el.value='';return}
 const n=Math.round(Number(raw));
 el.value=String(Number.isFinite(n)?Math.max(3,Math.min(30,n)):11)};

$('#createExplain').onclick=async()=>{if(uploading||!pendingPapers.length)return;if(!settings.configured){showSettings();toast('先配置 API，已选论文会保留');return}uploading=true;attachments();$('#createExplain').innerHTML='正在提交…';try{const body=new FormData();pendingPapers.forEach(f=>body.append('files',f));const created=await api('/api/upload/papers',{method:'POST',body});const guidance=$('#creationPrompt').value.trim();const minutes=$('#targetMinutes').value?Number($('#targetMinutes').value):null;for(const p of created){if(guidance)await api('/api/projects/'+encodeURIComponent(p.id)+'/guidance',jsonOptions('PUT',{guidance}));const section_ids=await chooseSections(p);await api('/api/projects/'+encodeURIComponent(p.id)+'/plan',jsonOptions('PUT',{minutes,section_ids,lang:(window.i18n&&window.i18n.lang)||'zh'}));await generate(p)}pendingPapers=[];$('#creationPrompt').value='';toast(`${created.length} 篇论文已加入队列`)}catch(e){toast(e.message)}finally{uploading=false;attachments();$('#createExplain').innerHTML='生成讲解 <span><img class="emoji" src="/assets/emoji/2b06.svg" alt=""></span>';await refresh(true)}};
$('#viewAll').onclick=()=>{showAll=!showAll;render()};
$('#homeNav').onclick=()=>{view='all';showAll=false;document.querySelectorAll('[data-view]').forEach(b=>b.classList.remove('active'));$('#homeNav').classList.add('active');render();window.scrollTo({top:0,behavior:'smooth'})};
// ── 讲解重点预设 ──────────────────────────────────────────────────────
// Served from /api/prompts rather than written into the page. A prompt travels
// as a value, and i18n.js deliberately never rewrites a value or a
// user-authored attribute -- which is why the Chinese preset used to survive
// into the English interface.
//
// So the boundary runs through the middle of this row: #starterPrompts holds
// API data and carries data-no-i18n because it renders itself in the current
// language, while #managePrompts and the dialog below are ordinary interface
// text that i18n.js translates like everything else. One owner per string.
let promptBook={presets:[],custom:[],limits:{label:40,prompt:2000,custom:50}};
const uiLang=()=>(window.i18n&&window.i18n.lang)||'zh';
const promptById=id=>[...promptBook.presets,...promptBook.custom].find(p=>p.id===id);

function usePrompt(text){if(!text)return;$('#creationPrompt').value=text;$('#creationPrompt').focus();$('#paperDrop').scrollIntoView({behavior:'smooth',block:'center'})}

async function loadPrompts(){
 try{promptBook=await api('/api/prompts?lang='+encodeURIComponent(uiLang()))}catch(e){/* 预设拿不到不该拖垮首页 */}
 renderPrompts()}

function renderPrompts(){
 const box=$('#starterPrompts');if(!box)return;
 box.innerHTML=[...promptBook.presets,...promptBook.custom].map(p=>
  `<button data-use="${escapeHtml(p.id)}" title="${escapeHtml(p.prompt)}">${escapeHtml(p.label)} ↗</button>`).join('')}

$('#starterPrompts').addEventListener('click',event=>{
 const button=event.target.closest('button');if(!button)return;
 const found=promptById(button.dataset.use);if(found)usePrompt(found.prompt)});

// The explore card names a preset instead of carrying a copy of its text, so
// the two can never drift apart.
document.querySelectorAll('[data-prompt-id]').forEach(card=>card.onclick=()=>{
 const found=promptById(card.dataset.promptId);if(found)usePrompt(found.prompt)});

$('#managePrompts').onclick=()=>managePrompts();

function managePrompts(){
 const rows=promptBook.custom.length?promptBook.custom.map(p=>
   `<div class="prompt-row"><div><b>${escapeHtml(p.label)}</b><small>${escapeHtml(p.prompt)}</small></div><button class="small-button" data-del="${escapeHtml(p.id)}">删除</button></div>`).join('')
  :'<p class="prompt-empty">还没有保存过。</p>';
 modal(`<h2>我的讲解重点</h2><p>保存在你这台电脑上，语言就是你写时的语言。内置预设不能改。</p>
  <div class="prompt-list" id="promptList">${rows}</div>
  <label class="prompt-field"><span>名称（可留空）</span><input id="promptLabel" maxlength="${promptBook.limits.label}"></label>
  <label class="prompt-field"><span>讲解重点</span><textarea id="promptBody" maxlength="${promptBook.limits.prompt}" rows="4"></textarea></label>
  <div class="dialog-actions"><button class="small-button" id="promptFromComposer">用输入框里的内容填充</button><button class="primary" id="promptSave">保存预设</button></div>`);
 $('#promptFromComposer').onclick=()=>{$('#promptBody').value=$('#creationPrompt').value.trim()};
 $('#promptSave').onclick=async()=>{
  try{await api('/api/prompts',jsonOptions('POST',{label:$('#promptLabel').value,prompt:$('#promptBody').value}));
   await loadPrompts();toast('预设已保存');managePrompts()}catch(e){toast(e.message)}};
 $('#promptList').onclick=async event=>{
  const button=event.target.closest('[data-del]');if(!button)return;
  try{await api('/api/prompts/'+encodeURIComponent(button.dataset.del),{method:'DELETE'});
   await loadPrompts();toast('预设已删除');managePrompts()}catch(e){toast(e.message)}}}

// Presets are the one thing on this page i18n.js cannot retranslate, so they
// reload themselves when the interface language changes.
document.addEventListener('i18n:languagechange',loadPrompts);
loadPrompts();
$('#openSettingsInline').onclick=()=>showSettings();
$('#projects').addEventListener('error',event=>{const img=event.target;if(img.tagName!=='IMG')return;const card=img.closest('[data-id]'),p=projects.find(p=>p.id===card?.dataset.id);if(!p)return;const step=Number(img.dataset.fallback||0);img.dataset.fallback=step+1;if(step===0)img.src=file(p,'images/cover_art.png');else if(step===1&&p.figures?.[0]?.file)img.src=file(p,'figures/'+p.figures[0].file);else img.replaceWith(Object.assign(document.createElement('div'),{className:'project-placeholder',textContent:p.title||p.paper_title||'论文讲解'}))},true);
$('#projects').addEventListener('click',async event=>{const button=event.target.closest('[data-action]');if(!button)return;const p=projects.find(p=>p.id===button.closest('[data-id]').dataset.id);if(!p)return;try{switch(button.dataset.action){case 'generate':button.disabled=true;try{await generate(p)}finally{button.disabled=false}break;case 'mp4':await api('/api/tts_video/'+encodeURIComponent(p.id),{method:'POST'});toast('已开始按需渲染 MP4；互动网页版可直接观看。');await refresh(true);break;case 'preview':modal(`<h2>${escapeHtml(p.title||'论文短片')}</h2><video controls autoplay playsinline src="${file(p,p.tts_output||p.output)}"></video><p>论文原图 · 光标随讲解移动</p>`);break;case 'cover':modal(`<h2>作品封面</h2><img class="cover-preview" src="${file(p,'images/'+p.cover)}" alt="作品封面"><div class="dialog-actions"><a class="small-button" download href="${file(p,'images/'+p.cover)}">下载封面 ↓</a></div>`);break;case 'log':{const data=await api('/api/projects/'+encodeURIComponent(p.id)+'/log');modal(`<h2>运行日志</h2><pre class="log">${escapeHtml(data.log||'尚未开始生成。')}</pre>`);break}case 'script':modal(`<h2>讲稿</h2><textarea class="script-editor" id="scriptEditor" ${busy(p)?'readonly':''}>${escapeHtml(p.script)}</textarea><p>保存后需要重做分镜与下游环节，改动才会进到讲解里。</p><div class="dialog-actions"><button class="primary" id="saveScript" ${busy(p)?'disabled':''}>保存文稿</button></div>`);$('#saveScript').onclick=async()=>{try{await api('/api/projects/'+encodeURIComponent(p.id)+'/script',jsonOptions('PUT',{script:$('#scriptEditor').value}));toast('文稿已保存');$('#modal').close();await refresh(true)}catch(e){toast(e.message)}};break}}catch(e){toast(e.message)}});
// Pi reports where a credential came from; show that instead of a guess.
const SOURCE_LABELS={'stored credential':'已存储凭据','OAuth':'浏览器登录'};
const sourceLabel=s=>SOURCE_LABELS[s]||s||'';

async function showSettings(){try{settings=await api('/api/settings');connection();
const providers=await api('/api/providers').then(r=>r.providers.filter(p=>p.methods.some(m=>m.type==='api_key'))).catch(()=>[]);
const connected=providers.filter(p=>p.configured);
const usesOf=id=>settings.uses.filter(u=>u.provider===id).map(u=>u.label).join('、')||'未使用';
// Preselect whatever a use needs but has not got, so the form opens on the real gap.
const wanted=(settings.uses.find(u=>!u.configured)||{}).provider;
const card=(id,title,subtitle,body)=>`<section class="provider-card" data-use="${id}"><header class="provider-head"><div><h3>${title}</h3><small>${subtitle}</small></div></header><div class="provider-body">${body}</div></section>`;
modal(`<p class="eyebrow">PROVIDERS &amp; MODELS</p><h2>供应商与模型</h2><p>供应商连一次，所有用途共用它的端点和凭据。下面再给每种用途挑一个模型，协议、上下文窗口和价格都由目录决定。</p><form id="settingsForm" class="settings-form">
${card('providers','供应商','连接一次，文稿 · 动画 · 封面共用',
`<div class="conn-list">${connected.map(p=>`<div class="conn-row"><div><b>${escapeHtml(p.name)}</b><small>${escapeHtml(usesOf(p.id))} · 来源 ${escapeHtml(sourceLabel(p.source))}</small></div><button class="small-button" type="button" data-forget="${escapeHtml(p.id)}"${p.source==='stored credential'?'':' disabled title="来自环境变量，不由本应用保存"'}>断开</button></div>`).join('')||'<div class="conn-empty">还没有连接任何供应商。</div>'}</div>
<div class="field-row"><label class="field">添加供应商<select id="newProvider">${providers.map(p=>`<option value="${escapeHtml(p.id)}"${p.configured?' disabled':''}${p.id===wanted?' selected':''}>${escapeHtml(p.name)}${p.configured?' · 已连接':''}</option>`).join('')}</select></label>
<label class="field">API Key<input id="providerKey" type="password" autocomplete="new-password" placeholder="粘贴后点连接"></label></div>
<button class="small-button" id="connectProvider" type="button">连接</button>
<small>Key 只存本机，不回传浏览器。该供应商的标准环境变量（如 ANTHROPIC_API_KEY）会自动识别。</small>`)}
${card('models','用途 → 模型','每种用途各挑一个模型',
settings.uses.map(u=>`<div class="use-row" data-use="${u.use}"><b>${escapeHtml(u.label)}</b>
<select class="use-provider" data-use="${u.use}">${providers.map(p=>`<option value="${escapeHtml(p.id)}"${p.id===u.provider?' selected':''}>${escapeHtml(p.name)}${p.configured?' ✓':''}</option>`).join('')}</select>
<select class="use-model" data-use="${u.use}"><option value="${escapeHtml(u.model)}">${escapeHtml(u.model)}</option></select>
<small class="use-note" data-use="${u.use}">${u.configured?'':'该供应商未连接'}</small></div>`).join(''))}
${card('speech','旁白 · Edge TTS','逐句时间戳驱动光标与字幕',
`<div class="field-row"><label class="field">音色<select id="voice"><option value="zh-CN-XiaoxiaoNeural">晓晓 · 自然女声</option><option value="zh-CN-YunxiNeural">云希 · 清朗男声</option><option value="zh-CN-XiaoyiNeural">晓伊 · 温柔女声</option><option value="zh-CN-YunjianNeural">云健 · 稳重男声</option><option value="en-US-AriaNeural">Aria · English</option></select></label><label class="field">语速<select id="rate"><option value="-10%">舒缓 · -10%</option><option value="+0%">自然 · 默认</option><option value="+10%">轻快 · +10%</option><option value="+20%">明快 · +20%</option></select></label></div><small>Edge TTS 不需要 Key，但需要联网。</small>`)}
<div class="dialog-actions"><button class="primary" type="submit">保存设置</button><button class="small-button" id="testKey" type="button">测试连接 ↗</button></div><div id="settingsStatus" class="dialog-status" role="status"></div></form>`);
$('#voice').value=settings.voice;$('#rate').value=settings.rate;
const status=text=>{$('#settingsStatus').textContent=text};
const providerField={language:'language_provider',image:'image_provider'};
const modelField={language:'model_text',image:'model_cover'};
const payload=()=>{const body={voice:$('#voice').value,rate:$('#rate').value};
 for(const row of document.querySelectorAll('.use-provider'))body[providerField[row.dataset.use]]=row.value;
 for(const row of document.querySelectorAll('.use-model'))body[modelField[row.dataset.use]]=row.value;
 return body};
const save=async()=>{settings=await api('/api/settings',jsonOptions('PUT',payload()));connection()};
// Each use lists models from whichever provider serves it, so a provider change reloads it.
const loadModels=async use=>{const provider=$(`.use-provider[data-use=${use}]`).value;const select=$(`.use-model[data-use=${use}]`);const note=$(`.use-note[data-use=${use}]`);note.textContent='读取目录…';
 try{const result=await api(`/api/settings/models?usage=${use}&provider=${encodeURIComponent(provider)}`);const current=select.value;
  select.innerHTML=result.models.map(m=>{const price=m.cost?` · $${m.cost.input}/$${m.cost.output}`:'';const ctx=m.context_window?` · ${Math.round(m.context_window/1000)}k`:'';return `<option value="${escapeHtml(m.id)}"${m.id===current?' selected':''}>${escapeHtml(m.name)}${ctx}${price}</option>`}).join('');
  // claude-opus-5-5 and anthropic/claude-opus-5.5 are one model in two naming conventions.
  if(!result.models.some(m=>m.id===current)&&result.models.length){const flat=t=>t.replace(/[.-]/g,'').replace(/^~/,'');select.value=(result.models.find(m=>flat(m.id).endsWith(flat(current)))||result.models.find(m=>!m.id.startsWith('~'))||result.models[0]).id}
  note.textContent=`${result.models.length} 个模型`}catch(e){note.textContent=e.message}};
for(const row of document.querySelectorAll('.use-provider'))row.onchange=async()=>{status('正在切换…');try{await loadModels(row.dataset.use);await save();status(`已切到 ${row.value}`)}catch(e){status(e.message)}};
for(const row of document.querySelectorAll('.use-model'))row.onchange=async()=>{try{await save();status('已保存')}catch(e){status(e.message)}};
$('#connectProvider').onclick=async()=>{const b=$('#connectProvider');const key=$('#providerKey').value.trim();if(!key){status('请先粘贴 API Key');return}
 b.disabled=true;status('正在连接…');try{const r=await api('/api/providers/'+encodeURIComponent($('#newProvider').value)+'/login',jsonOptions('POST',{api_key:key}));$('#providerKey').value='';await showSettings();status(`${r.id} 已连接`)}catch(e){status(e.message)}finally{b.disabled=false}};
for(const button of document.querySelectorAll('[data-forget]'))button.onclick=async()=>{button.disabled=true;status('正在断开…');try{await api('/api/providers/'+encodeURIComponent(button.dataset.forget)+'/logout',{method:'POST'});await showSettings()}catch(e){status(e.message);button.disabled=false}};
$('#settingsForm').onsubmit=async event=>{event.preventDefault();const b=event.submitter;b.disabled=true;try{await save();status('设置已保存。')}catch(e){status(e.message)}finally{b.disabled=false}};
$('#testKey').onclick=async()=>{const b=$('#testKey');b.disabled=true;status('正在验证连接…');try{await save();const result=await api('/api/settings/test',{method:'POST'});status(result.message)}catch(e){status(e.message)}finally{b.disabled=false}};
settings.uses.forEach(u=>void loadModels(u.use));
}catch(e){toast(e.message)}}

$('#settingsNav').onclick=showSettings;$('#connection').onclick=showSettings;
(async()=>{try{settings=await api('/api/settings');connection()}catch(e){toast(e.message)}await refresh(true)})();setInterval(()=>{if(!document.hidden)refresh()},4000);
