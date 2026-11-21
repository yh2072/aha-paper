"""项目存储 + 后台任务编排。每篇论文 = data/ 下一个目录，meta.json 记录全部状态。"""
import functools
import copy
import json
import re
import subprocess
import threading
import time
import unicodedata
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import config
from . import llm
from . import pi_models
from .pipeline import art_cover, interactive, deep_script, explainer, page_highlight
from .pipeline import (align, anim, broll, carousel, copywriter, cover, edit, figures, musetalk, pdf_extract, slideshow, wechat)

# 数字人推理专属单工位队列：天然串行防内存爆，且不占用渲染工位（否则等锁的
# 数字人任务会堵死 _EXECUTOR，批量出片时渲染全部停摆——踩过的坑）
_MUSETALK_EXEC = ThreadPoolExecutor(max_workers=1)

_EXECUTOR = ThreadPoolExecutor(max_workers=2)  # 同时跑 2 篇，避免打爆 API 限速
_LOCK = threading.Lock()

# 真正在工作线程里跑着的项目 pid。
# meta.json 里的 state 只是"上一次写进去的话"，任务被杀、服务重启、或者有人绕过
# 任务流程直接调渲染函数，它都会永久停在中间态，前端于是一直转圈。
# 有了这张表，"在跑"才有进程内的事实依据。
# 计数而不是集合：同一篇可能同时有"排队中"和"在跑"两笔，先完成的那笔
# 不能把另一笔的号也销掉。
_ACTIVE: dict[str, int] = {}
_BUSY_STATES = ("queued", "running", "editing")


def busy_count() -> int:
    """当前在册的任务数（含排队）。重启前用它确认不会打断谁。"""
    with _LOCK:
        return sum(_ACTIVE.values())


def _pending(pid: str) -> bool:
    with _LOCK:
        return _ACTIVE.get(pid, 0) > 0


def _submit(executor, fn, pid: str, *args):
    """派发任务并当场登记。

    登记必须发生在 submit 这一刻，不能等工作线程真正进函数才登记——
    工位只有 2 个，排在后面的任务可能等很久，这段时间它在 meta 里是"排队中"，
    如果此时登记表里没有它，列表接口就会把正常排队误判成"已中断"。
    """
    with _LOCK:
        _ACTIVE[pid] = _ACTIVE.get(pid, 0) + 1
    try:
        return executor.submit(fn, pid, *args)
    except Exception:
        with _LOCK:                       # 派发失败要销号，否则永远显示在跑
            _ACTIVE[pid] = max(_ACTIVE.get(pid, 1) - 1, 0)
        raise


def _tracked(fn):
    """任务出口销号。登记在 _submit 里做，这里只负责减。"""
    @functools.wraps(fn)
    def wrap(pid, *a, **kw):
        try:
            return fn(pid, *a, **kw)
        finally:
            with _LOCK:
                n = _ACTIVE.get(pid, 0) - 1
                if n > 0:
                    _ACTIVE[pid] = n
                else:
                    _ACTIVE.pop(pid, None)
    return wrap


def _slugify(name: str) -> str:
    name = unicodedata.normalize("NFKC", Path(name).stem)
    name = re.sub(r"[^\w一-鿿-]+", "_", name).strip("_")[:60]
    return name or uuid.uuid4().hex[:8]


class Project:
    def __init__(self, pid: str):
        if not re.fullmatch(r"[\w-]{1,100}", pid):
            raise ValueError("项目 ID 无效")
        self.pid = pid
        self.dir = config.DATA_DIR / pid

    @property
    def meta_path(self) -> Path:
        return self.dir / "meta.json"

    def load(self) -> dict:
        if self.meta_path.exists():
            return json.loads(self.meta_path.read_text())
        return {}

    def save(self, **updates):
        with _LOCK:
            meta = self.load()
            meta.update(updates)
            temporary=self.meta_path.with_suffix(".tmp")
            temporary.write_text(json.dumps(meta, ensure_ascii=False, indent=1))
            temporary.replace(self.meta_path)
        return meta

    def log(self, msg: str):
        line = f"[{time.strftime('%H:%M:%S')}] {msg}"
        with _LOCK:
            with open(self.dir / "log.txt", "a") as f:
                f.write(line + "\n")


def create_project(pdf_name: str, pdf_bytes: bytes) -> dict:
    pid = _slugify(pdf_name)
    if (config.DATA_DIR / pid).exists():
        pid = f"{pid}_{uuid.uuid4().hex[:4]}"
    proj = Project(pid)
    proj.dir.mkdir(parents=True)
    (proj.dir / "paper.pdf").write_bytes(pdf_bytes)
    return proj.save(id=pid, pdf_name=pdf_name, state="idle", stage="待生成",
                     created=time.strftime("%Y-%m-%d %H:%M"))


def list_projects() -> list[dict]:
    """列表时用进程内的事实核对 meta.json，不让幽灵状态一直转圈。

    只改返回给前端的副本，不回写磁盘：任务真跑起来时它自己会写状态，
    这样不管中断多少次，显示的永远是当下真实情况。
    """
    with _LOCK:
        active = set(_ACTIVE)
    running = sum(1 for d in config.DATA_DIR.iterdir()
                  if d.name in active and (d / "meta.json").exists()
                  and Project(d.name).load().get("state") == "running")
    out = []
    for d in sorted(config.DATA_DIR.iterdir()):
        if not (d / "meta.json").exists():
            continue
        m = Project(d.name).load()
        if m.get("state") in _BUSY_STATES:
            if d.name not in active:
                was = m.get("stage", "")
                m["state"] = "error"
                m["stage"] = f"已中断（{was}）" if was else "已中断"
                m["error"] = m.get("error") or "任务没跑完就中断了（被杀/重启），可重新触发"
            elif m.get("state") == "queued":
                # 在队列里、还没轮到。说清楚它在等什么，别让人以为卡死了
                m["stage"] = f"排队中（前面 {running} 篇在跑，共 2 个工位）"
        out.append(m)
    return out


# ── 阶段一 + 二：文稿 → 分镜 → 配图 → 封面 ─────────────────────────
#
# 拆成可单独重试的环节。两条规矩：
#   1. 默认永不重做已有产出——点"生成"只补没做完的部分，不会把稿子覆盖掉
#   2. 每个环节都能单独重试，重试时才强制重做那一个环节
# ctx 在环节之间传中间结果；被跳过的环节从 meta 里把结果读回来。

def _figures_desc(figs: list[dict]) -> str:
    return "\n".join(
        f"   - {f['file']}（第{f['page']}页）: {f.get('caption', '')}\n" +
        "".join(f"     · {p}\n" for p in f.get("walkthrough", []))
        for f in figs)


def _st_text(proj: "Project", ctx: dict):
    """抽 PDF 文本 + 认出论文标题和期刊。"""
    ctx["text"] = pdf_extract.extract_text(proj.dir / "paper.pdf")
    proj.log(f"PDF 抽取 {len(ctx['text'])} 字")
    info = llm.chat_json([{"role": "user", "content":
        "从下面的论文文本开头提取信息，只输出 JSON：\n"
        '{"title": "论文原标题", "journal": "期刊/会议通用全名，不要缩写'
        '（如 Nature Human Behaviour、Science Advances、NeurIPS；识别不出给空字符串）"}'
        "\n\n" + ctx["text"][:2500]}], temperature=0.1)
    ctx["paper_title"] = str(info.get("title", "")).strip()
    proj.save(paper_title=ctx["paper_title"],
              journal=str(info.get("journal", "")).strip()[:40])


def _st_figures(proj: "Project", ctx: dict):
    figs = []
    if figures.available():
        try:
            figs = figures.extract_main_figures(
                proj.dir / "paper.pdf", proj.dir / "figures", log=proj.log)
            figs = figures.caption_figures(figs, proj.dir / "figures", log=proj.log)
        except Exception as e:  # noqa: BLE001 - 主图提取失败不阻塞主流程
            proj.log(f"主图提取失败（继续无图流程）: {e}")
            figs = []
    ctx["figs"] = figs
    proj.save(figures=figs)


def _st_script(proj: "Project", ctx: dict):
    m=proj.load()
    board=deep_script.generate(proj.dir/"paper.pdf",ctx["figs"],proj.dir/"figures",
            log=proj.log,guidance=m.get("generation_guidance",""),
        minutes=m.get("target_minutes"),section_ids=m.get("section_ids"))
    script="\n\n".join(sc["text"] for sc in board["scenes"])
    ctx["script"]=script
    proj.save(script=script,deep_outline=board,script_profile=deep_script.PROFILE,
              accuracy_review=board["corrections"],doi=board.get("doi",""),
              storyboard=None,images=[],video_engine=None,cover_engine=None)


def _st_storyboard(proj: "Project", ctx: dict):
    m=proj.load()
    if not m.get("deep_outline"):
        raise ValueError("缺少深度大纲，请先重做「生成口播稿」")
    board=copy.deepcopy(m["deep_outline"])
    for sc in board["scenes"]:          # 分镜选中的真实主图 → 该场景配图
        fig = sc.get("figure")
        if fig and (proj.dir / "figures" / fig).exists():
            fp = proj.dir / "figures" / fig
            sc["figure_path"] = str(fp)
            # 有子图时定位最相关的一块，之后画可爱光标做 signalling
            sc["highlight"] = figures.locate_subfigure(fp, sc["text"])
            if sc["highlight"]:
                proj.log(f"  {fig} 定位到相关子图 {sc['highlight']}")
    ctx["board"] = board
    proj.save(storyboard=board, title=board.get("title", proj.pid),
              subtitle=board.get("subtitle", ""))


def _st_copy(proj: "Project", ctx: dict):
    if proj.load().get("script_profile") == deep_script.PROFILE:
        board=ctx["board"]
        proj.save(intro=board.get("subtitle","")+"\n"+ctx["script"][:280],
                  title_options=[board["title"]])
        return
    social = copywriter.generate_social_copy(ctx["script"], ctx.get("paper_title", ""))
    titles = social["title_options"]
    board_title = (ctx["board"] or {}).get("title")
    if board_title and board_title not in titles:
        titles = [board_title[:15]] + titles[:2]
    for t, lv in zip(titles, social.get("title_levers", []) or [""] * 3):
        proj.log(f"  候选标题[{lv or '?'}] {t}")
    proj.save(intro=social["intro"], title_options=titles,
              title_levers=social.get("title_levers", []))


def _st_code(proj: "Project", ctx: dict):
    """Chapters with a figure keep it. The rest read the paper itself: the PDF's own
    text layer gives the highlight geometry, so nothing on screen is a drawing the
    model invented. There is no second renderer behind this one."""
    page_highlight.prepare(ctx['board']['scenes'],proj.dir,proj.dir/'explainer_work',log=proj.log)
    proj.save(storyboard=ctx["board"], video_engine=page_highlight.VERSION)


def _st_images(proj: "Project", ctx: dict):
    if proj.load().get("engine") == "pi-canvas":
        (proj.dir / "images").mkdir(exist_ok=True)
        imgs=[]
        for i,sc in enumerate(ctx["board"]["scenes"]):
            if sc.get("figure_path"):
                name=f"scene_{i:02d}.png"
                (proj.dir / "images" / name).write_bytes(Path(sc["figure_path"]).read_bytes())
                imgs.append(name)
            else:
                imgs.append("")
        proj.save(images=imgs)


def _st_broll(proj: "Project", ctx: dict):
    if not broll.available():
        proj.log("  未配置实拍素材来源，跳过")
        return
    board = ctx["board"]
    plans = broll.plan(board["scenes"], log=proj.log)
    est = [max(len(sc["text"]) * 0.21, 8) for sc in board["scenes"]]
    credits = broll.collect(board["scenes"], plans, proj.dir / "broll",
                            durations=est, log=proj.log)
    for c in credits:
        board["scenes"][c["scene"] - 1]["broll_credit"] = c["author"]
    proj.save(storyboard=board, broll_credits=credits)


def _st_cover(proj: "Project", ctx: dict):
    if proj.load().get("engine") == "pi-canvas":
        name=art_cover.generate(proj.load(),proj.dir / "images",log=proj.log)
        proj.save(cover=name,cover_engine="ai-image")


def _st_carousel(proj: "Project", ctx: dict):
    files = carousel.build(proj.dir, proj.load(), log=proj.log)
    proj.save(carousel=files)


def _st_wechat(proj: "Project", ctx: dict):
    wechat.build_article(proj.dir, proj.load(), log=proj.log)
    proj.save(wechat="wechat.docx")


def _code_done(proj: "Project", m: dict) -> bool:
    """Whether every chapter already has the visual it is supposed to have.

    A file existing is not enough. A Canvas page left on disk by the engine this
    mode used to ship is not what it ships now, so it must not count as finished
    work — otherwise the project reports 完成 while its chapters are static."""
    scenes = (m.get("storyboard") or {}).get("scenes") or []
    if not m.get("storyboard"):
        return False
    for sc in scenes:
        if sc.get("figure_path"):
            continue                        # 真实主图 + 光标讲解，不需要另画
        if sc.get("page_plan") and Path(sc["page_plan"]).exists():
            continue
        return False
    return True


# key, 中文名, 执行函数, 已完成判定, 失败是否中断后续
STAGES = [
    ("text",       "抽取PDF文本",   _st_text,       lambda p, m: bool(m.get("paper_title")), True),
    ("figures",    "检测论文主图",  _st_figures,    lambda p, m: m.get("figures") is not None, False),
    ("script",     "生成口播稿",    _st_script,     lambda p, m: bool(m.get("script")) and (m.get("engine") != "pi-canvas" or m.get("script_profile") == deep_script.PROFILE), True),
    ("storyboard", "生成分镜",      _st_storyboard, lambda p, m: bool(m.get("storyboard")), True),
    ("code",       "章节画面",      _st_code,     _code_done, True),
    ("copy",       "小红书文案",    _st_copy,       lambda p, m: bool(m.get("intro")), False),
    ("images",     "批量绘图",      _st_images,     lambda p, m: bool(m.get("images")), False),
    ("broll",      "实拍素材",      _st_broll,
     lambda p, m: any(sc.get("broll_path")
                      for sc in (m.get("storyboard") or {}).get("scenes") or []), False),
    ("cover",      "制作封面",      _st_cover,      lambda p, m: (p.dir / "images" / "cover.png").exists() and (m.get("engine") != "pi-canvas" or m.get("cover_engine") == "ai-image"), False),
    ("carousel",   "小红书图文版",  _st_carousel,
     lambda p, m: bool(m.get("carousel")), False),
    ("wechat",     "公众号图文",    _st_wechat,     lambda p, m: (p.dir / "wechat.docx").exists(), False),
]
STAGE_NAMES = {k: n for k, n, *_ in STAGES}
# 下游依赖：重试上游后，这些环节的产物就对不上了，只提示不自动重做（重做要花钱）
_DOWNSTREAM = {
    "figures": ["script", "storyboard", "cover"],
    "script": ["storyboard", "copy", "images", "broll", "cover", "wechat"],
    "storyboard": ["code", "copy", "images", "broll", "cover"],
}


@_tracked
def _run_generation(pid: str, only: list[str] | None = None):
    """only=None：补齐没做完的环节（绝不重做已有产出）；only=[key]：强制重做这些环节。"""
    proj = Project(pid)
    ctx: dict = {}
    try:
        proj.save(state="running", error="")
        m = proj.load()
        for key, name, fn, done, fatal in STAGES:
            if m.get("engine") == "pi-canvas" and key in ("broll","carousel","wechat"):
                continue
            if m.get("engine") != "pi-canvas" and key == "code":
                continue
            forced = only is not None and key in only
            if only is not None and not forced:
                continue
            if not forced and done(proj, m):
                proj.log(f"  跳过「{name}」（已有产出）")
                continue
            # 本环节要跑，先把上游结果准备好（跳过的环节从 meta 读回来）
            _load_ctx(proj, ctx, key)
            proj.save(stage=name)
            try:
                fn(proj, ctx)
            except Exception as e:  # noqa: BLE001
                proj.log(f"「{name}」失败: {e}")
                if fatal or (m.get("engine") == "pi-canvas" and key == "cover"):
                    raise
            m = proj.load()
        if only:
            stale = sorted({d for k in only for d in _DOWNSTREAM.get(k, [])})
            if stale:
                proj.log("  ⚠ 重试了上游环节，这些下游产物可能已对不上，"
                         f"需要时请单独重试：{'、'.join(STAGE_NAMES[s] for s in stale)}")
            proj.save(state="ready", stage=f"重试完成：{'、'.join(STAGE_NAMES[k] for k in only)} ✓")
            proj.log("重试完成 ✓")
        else:
            proj.save(state="ready", stage="文稿与场景准备完成")
            proj.log("生成阶段全部完成 ✓")
    except Exception as e:  # noqa: BLE001
        proj.log(f"出错: {e}")
        proj.save(state="error", error=str(e))


def _load_ctx(proj: "Project", ctx: dict, upto: str):
    """把被跳过环节的产物从 meta 读回 ctx，供后面的环节使用。"""
    m = proj.load()
    if "text" not in ctx:
        ctx["text"] = pdf_extract.extract_text(proj.dir / "paper.pdf")  # 本地，不花钱
        ctx["paper_title"] = m.get("paper_title", "")
    ctx.setdefault("figs", m.get("figures") or [])
    ctx.setdefault("script", m.get("script") or "")
    ctx.setdefault("board", m.get("storyboard") or {})


def start_generation(pid: str, only: list[str] | None = None) -> None:
    # 工位只有 2 个，排队时卡片看着像没反应，用户会反复点。不拦的话同一篇会被
    # 跑好几遍，每遍都真金白银调一次 LLM。
    if _pending(pid):
        Project(pid).log("  （已在队列中，忽略重复触发）")
        return
    Project(pid).save(state="queued", stage="排队中")
    _submit(_EXECUTOR, _run_generation, pid, only)


# ── 阶段三：视频对齐 + 自动剪辑 ────────────────────────────────────

def attach_video(pid: str, filename: str, data: bytes) -> dict:
    proj = Project(pid)
    ext = Path(filename).suffix or ".mp4"
    video_path = proj.dir / f"video{ext}"
    video_path.write_bytes(data)
    return proj.save(video=video_path.name, video_name=filename)


@_tracked
def _run_edit(pid: str):
    proj = Project(pid)
    meta = proj.load()
    try:
        proj.save(state="editing", stage="语音对齐", error="")
        video = proj.dir / meta["video"]
        scenes = meta["storyboard"]["scenes"]
        spans = align.align_scenes(video, scenes, log=proj.log)
        proj.save(spans=spans, stage="ffmpeg 剪辑合成")
        # 每个场景的画面：实拍素材 > 讲图光标动画 > 手绘图
        images = []
        for i, n in enumerate(meta.get("images", [])):
            sc = scenes[i] if i < len(scenes) else {}
            bp = Path(sc["broll_path"]) if sc.get("broll_path") else None
            if bp and bp.exists():
                images.append(bp)
                continue
            a = proj.dir / "images" / f"anim_{i:02d}.mp4"
            images.append(a if a.exists() else (proj.dir / "images" / n if n else None))
        edit.render_video(video, images, spans, proj.dir / "final.mp4", log=proj.log)
        proj.save(output="final.mp4", state="done", stage="成片完成 ✓")
        proj.log("剪辑完成 ✓")
    except Exception as e:  # noqa: BLE001
        proj.log(f"剪辑出错: {e}")
        proj.save(state="error", error=str(e))


def start_edit(pid: str) -> None:
    Project(pid).save(state="queued", stage="剪辑排队中")
    _submit(_EXECUTOR, _run_edit, pid)


@_tracked
def _run_tts_video(pid: str, force_video: bool = False):
    proj = Project(pid)
    meta = proj.load()
    try:
        if meta.get("engine") == "pi-canvas" and not force_video:
            proj.save(state="editing",stage="实时互动讲解：配音与同步",error="")
            manifest=explainer.build(proj.dir,meta,log=proj.log,
                                     progress=lambda stage:proj.save(stage=stage))
            proj.save(state="done",stage="深度互动讲解完成 ✓",experience_mode="explainer",
                      interactive="experience.json",audio_output="narration.mp3",
                      segment_count=len(manifest["segments"]),duration=manifest["duration"])
            return
        proj.save(state="editing", stage="TTS 配音+渲染", error="")
        scenes = meta["storyboard"]["scenes"]
        images = [proj.dir / "images" / n if n else None for n in meta.get("images", [])]
        slideshow.render_slideshow(scenes, images, proj.dir / "tts_work",
                                   proj.dir / "slideshow.mp4", log=proj.log,
                                   anim_dir=proj.dir / "images")
        proj.save(stage="叠加进度条")
        tmp_bar = proj.dir / "slideshow_bar.mp4"
        edit.add_progress_bar(proj.dir / "slideshow.mp4", tmp_bar, log=proj.log)
        tmp_bar.replace(proj.dir / "slideshow.mp4")
        # 导出纯配音（驱动数字人克隆工具用）
        subprocess.run(["ffmpeg", "-y", "-i", str(proj.dir / "slideshow.mp4"),
                        "-vn", "-acodec", "pcm_s16le",
                        str(proj.dir / "narration.wav")], capture_output=True)
        proj.save(tts_output="slideshow.mp4",
                  state="done",
                  stage="TTS 成片完成 ✓")
        manifest=interactive.write_manifest(proj.dir,proj.load())
        if manifest:
            proj.save(interactive="experience.json",segment_count=len(manifest["segments"]),
                      stage="互动视频完成 ✓")
        proj.log("aha-paper 分章节视频完成 ✓")
        # 手动上传的数字人（HeyGen 等）优先，其次才是本机 MuseTalk 推理
        if _avatar_path(proj):
            _apply_avatar(proj)
        elif musetalk.available():
            _submit(_MUSETALK_EXEC, _run_musetalk, pid)
    except Exception as e:  # noqa: BLE001
        proj.log(f"TTS 成片出错: {e}")
        proj.save(state="error", error=str(e))


def _avatar_path(proj: Project) -> Path | None:
    for ext in (".mp4", ".mov", ".webm", ".m4v"):
        p = proj.dir / f"avatar{ext}"
        if p.exists():
            return p
    return None


def _figure_scene_spans(proj: Project, meta: dict) -> list:
    """讲图场景的时间段（气泡在这些时段隐藏，让位给 figure）。"""
    scenes = (meta.get("storyboard") or {}).get("scenes", [])
    spans, t = [], 0.0
    for i, sc in enumerate(scenes):
        seg = proj.dir / "tts_work" / f"seg_{i:02d}.mp4"
        if not seg.exists():
            return []
        out = subprocess.run(["ffprobe", "-v", "quiet", "-show_entries",
                              "format=duration", "-of", "csv=p=0", str(seg)],
                             capture_output=True, text=True)
        dur = float(out.stdout.strip() or 0)
        if sc.get("figure_path"):
            spans.append((t, t + dur))
        t += dur
    return spans


def _apply_avatar(proj: Project):
    """有数字人口播视频时，圆形角标合成进成片（讲图场景自动隐身）。"""
    avatar = _avatar_path(proj)
    video = proj.dir / "slideshow.mp4"
    if not avatar or not video.exists():
        return
    meta = proj.load()
    spans = _figure_scene_spans(proj, meta)
    if spans:
        proj.log(f"  讲图时段隐藏人像: {[(round(s), round(e)) for s, e in spans]}")
    tmp = proj.dir / "slideshow_avatar.mp4"
    edit.add_avatar_bubble(video, avatar, tmp, hide_spans=spans, log=proj.log)
    tmp.replace(video)
    proj.log("数字人圆形角标已合成 ✓")


@_tracked
def _run_musetalk(pid: str):
    """分段 MuseTalk 推理 + 圆形角标合成（讲图时段无人像）。"""
    proj = Project(pid)
    meta = proj.load()
    try:
        proj.save(stage="数字人推理中（分段）")
        clip, segments = musetalk.generate(
            proj.dir, meta["storyboard"]["scenes"], log=proj.log)
        proj.save(stage="数字人角标合成")
        tmp = proj.dir / "slideshow_avatar.mp4"
        edit.add_avatar_bubbles_segmented(
            proj.dir / "slideshow.mp4", clip, segments, tmp, log=proj.log)
        tmp.replace(proj.dir / "slideshow.mp4")
        # 抽帧进封面
        try:  # 视觉模型选"睁眼上镜"的一帧做封面头像（每篇各不相同）
            figures.pick_avatar_face(clip, proj.dir / "images" / "avatar_face.png",
                                     log=proj.log)
        except Exception as e:  # noqa: BLE001
            proj.log(f"  选帧失败: {e}")
        if meta.get("title"):
            set_title(pid, meta["title"])
        proj.save(avatar="musetalk", stage="TTS 成片完成（含数字人）✓")
        proj.log("分段数字人角标完成 ✓")
    except Exception as e:  # noqa: BLE001 - 数字人失败不影响成片本身
        proj.log(f"数字人环节失败（成片仍可用）: {e}")
        proj.save(stage="TTS 成片完成（数字人失败）")


@_tracked
def _run_broll(pid: str, rerender: bool = True):
    """给已有项目补搜实拍素材，完成后可自动重渲成片。"""
    proj = Project(pid)
    meta = proj.load()
    board = meta.get("storyboard") or {}
    scenes = board.get("scenes") or []
    try:
        proj.save(stage="搜集实拍素材")
        plans = broll.plan(scenes, log=proj.log)
        est = [max(len(sc["text"]) * 0.21, 8) for sc in scenes]
        credits = broll.collect(scenes, plans, proj.dir / "broll",
                                durations=est, log=proj.log)
        for c in credits:
            scenes[c["scene"] - 1]["broll_credit"] = c["author"]
        board["scenes"] = scenes
        proj.save(storyboard=board, broll_credits=credits,
                  stage=f"实拍素材 {len(credits)} 段 ✓")
        proj.log(f"实拍素材完成：{len(credits)} 段")
        if rerender:  # 按项目类型重渲：口播项目走剪辑，TTS 项目走图文成片
            if meta.get("video"):
                _submit(_EXECUTOR, _run_edit, pid)
            elif meta.get("tts_output"):
                _submit(_EXECUTOR, _run_tts_video, pid)
    except Exception as e:  # noqa: BLE001
        proj.log(f"实拍素材失败: {e}")
        proj.save(stage="实拍素材失败")


def start_broll(pid: str, rerender: bool = True) -> None:
    _submit(_EXECUTOR, _run_broll, pid, rerender)


def start_musetalk(pid: str) -> None:
    _submit(_MUSETALK_EXEC, _run_musetalk, pid)


def attach_avatar(pid: str, filename: str, data: bytes) -> dict:
    proj = Project(pid)
    for ext in (".mp4", ".mov", ".webm", ".m4v"):  # 清掉旧的
        (proj.dir / f"avatar{ext}").unlink(missing_ok=True)
    ext = Path(filename).suffix.lower() or ".mp4"
    (proj.dir / f"avatar{ext}").write_bytes(data)
    meta = proj.save(avatar=f"avatar{ext}")
    # 抽一帧做封面的圆形头像角标，并重排封面
    try:
        figures.pick_avatar_face(proj.dir / f"avatar{ext}",
                                 proj.dir / "images" / "avatar_face.png",
                                 log=proj.log)
    except Exception as e:  # noqa: BLE001
        proj.log(f"  选帧失败: {e}")
    if meta.get("title"):
        set_title(pid, meta["title"])
    if (proj.dir / "slideshow.mp4").exists():  # 已有成片 → 立即合成
        _apply_avatar(proj)
    return meta


def start_tts_video(pid: str) -> None:
    Project(pid).save(state="queued", stage="MP4 导出排队中")
    _submit(_EXECUTOR, _run_tts_video, pid, True)


def _main_figure_path(proj: Project, meta: dict) -> Path | None:
    """封面用的代表性主图：优先第一个讲图场景用的图，其次置信度最高的检出图。"""
    for sc in (meta.get("storyboard") or {}).get("scenes", []):
        f = sc.get("figure")
        if f and (proj.dir / "figures" / f).exists():
            return proj.dir / "figures" / f
    for f in sorted(meta.get("figures") or [], key=lambda x: -x.get("conf", 0)):
        if (proj.dir / "figures" / f["file"]).exists():
            return proj.dir / "figures" / f["file"]
    return None


def sanitize_filename(name: str) -> str:
    name = re.sub(r'[\\/:*?"<>|\n\r]+', "", str(name)).strip().strip(".")
    return name[:40] or "未命名"


def set_title(pid: str, title: str) -> dict:
    """换选中的标题，并用已有底图免费重排封面。"""
    proj = Project(pid)
    meta = proj.save(title=title.strip()[:20])
    art = proj.dir / "images" / "cover_art.png"
    if art.exists() and meta.get("cover_engine") == "ai-image":
        art_cover.compose(art,meta,proj.dir / "images" / "cover.png")
        return meta
    if art.exists():
        snip = proj.dir / "images" / "title_snippet.png"
        face = proj.dir / "images" / "avatar_face.png"
        cover.compose_cover(art, meta["title"], meta.get("subtitle", ""),
                            proj.dir / "images" / "cover.png",
                            title_snippet=snip if snip.exists() else None,
                            journal=meta.get("journal") or None,
                            main_figure=_main_figure_path(proj, meta),
                            avatar_face=face if face.exists() else None)
    return meta


def regen_copy(pid: str) -> dict:
    proj = Project(pid)
    meta = proj.load()
    social = copywriter.generate_social_copy(meta["script"],
                                             meta.get("paper_title", ""))
    titles = social["title_options"]
    if meta.get("title") and meta["title"] not in titles:
        titles = [meta["title"][:15]] + titles[:2]
    return proj.save(intro=social["intro"], title_options=titles)


EXPORT_KINDS = {  # kind → (源文件, 导出名模板)
    "slideshow": ("slideshow.mp4", "{name}.mp4"),
    "final": ("final.mp4", "{name}_口播版.mp4"),
    "cover": ("images/cover.png", "{name}_封面.png"),
    "narration": ("narration.wav", "{name}_配音.wav"),
    "wechat": ("wechat.docx", "{name}_公众号.docx"),
}


def export_projects(pids: list[str], dest: str,
                    include: list[str] | None = None) -> list[dict]:
    """批量导出：按 include 筛选内容类型，文件名与标题一致。"""
    import shutil  # noqa: PLC0415
    include = include or [*EXPORT_KINDS, "copy"]
    dest_dir = Path(dest).expanduser()
    dest_dir.mkdir(parents=True, exist_ok=True)
    results = []
    for pid in pids:
        proj = Project(pid)
        meta = proj.load()
        if not meta:
            results.append({"id": pid, "error": "项目不存在"})
            continue
        name = sanitize_filename(meta.get("title") or pid)
        written = []
        for kind, (src, tmpl) in EXPORT_KINDS.items():
            if kind in include and (proj.dir / src).exists():
                dst = tmpl.format(name=name)
                shutil.copy(proj.dir / src, dest_dir / dst)
                written.append(dst)
        if "copy" in include and (meta.get("intro") or meta.get("title")):
            # 不再附素材出处：Pexels 允许商用且不要求署名，发布文案里不需要。
            # 出处仍留在 meta 的 broll_credits 里备查。
            txt = (f"【标题】{meta.get('title', '')}\n\n"
                   f"【简介】\n{meta.get('intro', '（未生成）')}\n\n"
                   f"【候选标题】\n" +
                   "\n".join(f"- {t}" for t in meta.get("title_options", [])) +
                   f"\n\n【论文】{meta.get('paper_title', '')}\n")
            (dest_dir / f"{name}_文案.txt").write_text(txt)
            written.append(f"{name}_文案.txt")
        results.append({"id": pid, "files": written})
    return results


def match_video_to_project(filename: str) -> str | None:
    """按文件名与论文名/标题的相似度自动配对批量上传的视频。"""
    from difflib import SequenceMatcher  # noqa: PLC0415
    stem = _slugify(filename).lower()
    best, best_score = None, 0.35
    for meta in list_projects():
        for cand in (meta["id"], meta.get("title", ""), _slugify(meta.get("pdf_name", ""))):
            score = SequenceMatcher(None, stem, str(cand).lower()).ratio()
            if score > best_score:
                best, best_score = meta["id"], score
    return best


@_tracked
def _run_full_video(pid: str):
    _run_generation.__wrapped__(pid)
    if Project(pid).load().get("state") == "error":
        return
    _run_tts_video.__wrapped__(pid)


def start_full_video(pid: str):
    proj=Project(pid)
    if not proj.meta_path.exists():
        raise ValueError("项目不存在")
    # Gate on the connection, not on an env var: a provider connected through the
    # settings page stores its credential in Pi, leaving config.API_KEY empty.
    language = config.use_provider("language")
    try:
        connected = pi_models.check(language).get("configured")
    except pi_models.ProviderError as error:
        raise ValueError(f"无法读取供应商状态：{error}") from error
    if not connected:
        raise ValueError(f"请先在设置中连接供应商 {language}")
    if _pending(pid):
        return
    # New pipeline can resume prior projects; original outputs are kept until replacement succeeds.
    proj.save(engine="pi-canvas",state="queued",stage="深度互动讲解排队中")
    _submit(_EXECUTOR,_run_full_video,pid)
