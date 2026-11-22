"""FastAPI 入口：REST API + 静态 GUI。启动: uvicorn app.main:app --port 8321"""
import hmac
from pathlib import Path

from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import access, config, jobs, pi_models, studio_settings
from .pipeline import deep_script, outline
from fastapi import Request
from fastapi.responses import JSONResponse

app = FastAPI(title="aha-paper")
WEB_DIR = Path(__file__).resolve().parent.parent / "web"
app.mount("/assets", StaticFiles(directory=WEB_DIR), name="assets")


@app.middleware("http")
async def local_origin_guard(request: Request, call_next):
    if request.method in ("POST","PUT","DELETE","PATCH"):
        origin=request.headers.get("origin")
        if request.headers.get("sec-fetch-site") == "cross-site" or (origin and origin != str(request.base_url).rstrip("/")):
            return JSONResponse({"detail":"仅允许工作室页面发起操作"},status_code=403)
    return await call_next(request)


# 注册顺序＝生效顺序的反面：Starlette 把最后注册的中间件放在最外层，
# 所以这道门先跑，没带口令的请求根本到不了上面的同源检查和任何路由。
# 挂载的静态目录（/assets、/files）同样被它包住——只拦 /api 等于把
# 整个 data/ 目录（论文原文、成片）敞开给所有人。
@app.middleware("http")
async def access_gate(request: Request, call_next):
    denied = access.check(request)
    return denied if denied is not None else await call_next(request)


app.mount("/files", StaticFiles(directory=config.DATA_DIR), name="files")

# 启动那一刻的代码新旧程度。之后磁盘上的代码被改过，进程里跑的仍是旧的——
# 这会让人以为"改了没用"，其实是没加载。记下来供前端提示。
_CODE_DIR = Path(__file__).resolve().parent


def _code_mtime() -> float:
    """.env 也要算进来：换 TTS 音色、换数字人源都只改 .env，
    但它同样是启动时读进进程的，不重启照样不生效（踩过：换了数字人源，
    进程里还是旧的，推理缓存直接命中旧结果）。"""
    files = list(_CODE_DIR.rglob("*.py")) + [config.ROOT / ".env"]
    return max((p.stat().st_mtime for p in files if p.exists()), default=0.0)


_BOOT_CODE_MTIME = _code_mtime()


@app.get("/api/ping")
def ping():
    """存活探针，不设门。编排平台的健康检查要是被口令拦住，容器会被判定
    不健康然后无限重启——它服务得好好的。这里只回 ok，别的什么都不说；
    /api/health 带着构建新旧和任务数，那是给运营者看的，照常要口令。"""
    return {"ok": True}


@app.get("/api/health")
def health():
    """code_stale=True 表示磁盘上的代码比服务启动时新，需要重启才能生效。"""
    now = _code_mtime()
    return {"code_stale": now > _BOOT_CODE_MTIME + 1,
            "busy": jobs.busy_count(),
            }


@app.get("/login")
def login_page(request: Request, next: str = "/"):
    if not access.enabled():
        return RedirectResponse("/", status_code=303)
    if access.valid(request.cookies.get(access.COOKIE, "")):
        return RedirectResponse(access.safe_next(next), status_code=303)
    return access.page(request, access.safe_next(next))


@app.post("/api/login")
async def login(request: Request):
    """原生表单提交：不依赖 JS，也不依赖 /assets（那是被门拦着的）。"""
    form = await request.form()
    nxt = access.safe_next(str(form.get("next") or "/"))
    if not access.enabled():
        return RedirectResponse(nxt, status_code=303)
    if access.locked(request):
        return access.page(request, nxt, "尝试过多，请稍后再试 · too many attempts", 429)
    if not hmac.compare_digest(str(form.get("password") or ""), config.ACCESS_PASSWORD):
        access.note_failure(request)
        return access.page(request, nxt, "口令不对 · wrong password", 401)
    access.forget(request)
    response = RedirectResponse(nxt, status_code=303)
    access.grant(response, request)
    return response


@app.post("/api/logout")
def logout():
    response = JSONResponse({"ok": True})
    access.revoke(response)
    return response


@app.get("/")
def index():
    # 禁缓存：界面改动后刷新就能看到，不用手动清缓存
    return FileResponse(WEB_DIR / "index.html",
                        headers={"Cache-Control": "no-store, must-revalidate"})


@app.get("/api/projects")
def projects():
    return jobs.list_projects()


@app.get("/api/projects/{pid}/log")
def project_log(pid: str):
    log = config.DATA_DIR / pid / "log.txt"
    return {"log": log.read_text() if log.exists() else ""}


@app.post("/api/upload/papers")
async def upload_papers(files: list[UploadFile]):
    created = []
    for f in files:
        if not (f.filename or "").lower().endswith(".pdf"):
            continue
        created.append(jobs.create_project(f.filename, await f.read()))
    if not created:
        raise HTTPException(400, "没有收到 PDF 文件")
    return created


@app.post("/api/run/{pid}")
def run_generation(pid: str):
    jobs.start_generation(pid)
    return {"ok": True}


@app.get("/api/stages")
def stages():
    """环节清单（供前端渲染重试下拉框）。"""
    return [{"key": k, "name": n} for k, n, *_ in jobs.STAGES]


@app.post("/api/retry/{pid}/{step}")
def retry_step(pid: str, step: str):
    """只重做指定环节，其余一律不动。"""
    if step not in jobs.STAGE_NAMES:
        raise HTTPException(400, f"未知环节: {step}")
    jobs.start_generation(pid, only=[step])
    return {"ok": True, "step": jobs.STAGE_NAMES[step]}


@app.post("/api/run_all")
def run_all():
    started = []
    for meta in jobs.list_projects():
        if meta.get("state") in ("idle", "error") and not meta.get("script"):
            jobs.start_generation(meta["id"])
            started.append(meta["id"])
    return {"started": started}


class GenerationGuidance(BaseModel):
    guidance: str


class ExplainerPlan(BaseModel):
    minutes: int | None = None
    section_ids: list[str] | None = None


@app.get("/api/projects/{pid}/outline")
def paper_outline(pid: str):
    """The paper's own bookmarks, so the user can pick what gets explained.

    An empty list is the normal answer for a journal PDF with no bookmarks; the
    caller then offers no picker and the whole paper is explained."""
    proj = jobs.Project(pid)
    pdf = proj.dir / "paper.pdf"
    if not proj.meta_path.exists() or not pdf.exists():
        raise HTTPException(404)
    entries = outline.extract(pdf)
    saved = proj.load()
    return {"entries": entries,
            "section_ids": saved.get("section_ids") or [],
            "minutes": saved.get("target_minutes"),
            "default_minutes": deep_script.DEFAULT_MINUTES,
            "min_minutes": deep_script.MIN_MINUTES,
            "max_minutes": deep_script.MAX_MINUTES}


@app.put("/api/projects/{pid}/plan")
def edit_plan(pid: str, body: ExplainerPlan):
    """How long the explainer runs, and which sections it covers."""
    proj = jobs.Project(pid)
    if not proj.meta_path.exists():
        raise HTTPException(404)
    if proj.load().get("state") in ("queued", "running", "editing"):
        raise HTTPException(409, "创作进行中，请完成后再改时长或章节")
    minutes = body.minutes
    if minutes is not None and not deep_script.MIN_MINUTES <= minutes <= deep_script.MAX_MINUTES:
        raise HTTPException(400, f"时长请在 {deep_script.MIN_MINUTES}–{deep_script.MAX_MINUTES} 分钟之间")
    ids = body.section_ids or []
    if ids:
        # An id the paper's own outline does not hold cannot be turned into pages,
        # so it is refused here rather than silently explaining the whole paper.
        known = {item["id"] for item in outline.extract(proj.dir / "paper.pdf")}
        unknown = [i for i in ids if i not in known]
        if unknown:
            raise HTTPException(400, f"这篇论文没有这些小节: {'、'.join(unknown[:3])}")
    proj.save(target_minutes=minutes, section_ids=ids)
    return {"ok": True, "minutes": minutes, "sections": len(ids),
            "budget": deep_script.budget(minutes)}


@app.put("/api/projects/{pid}/guidance")
def edit_guidance(pid: str, body: GenerationGuidance):
    proj = jobs.Project(pid)
    if not proj.meta_path.exists():
        raise HTTPException(404)
    if proj.load().get("state") in ("queued", "running", "editing"):
        raise HTTPException(409, "创作进行中，请完成后修改讲解重点")
    if len(body.guidance) > 2000:
        raise HTTPException(400, "讲解重点请控制在2000字以内")
    proj.save(generation_guidance=body.guidance.strip())
    return {"ok": True}


class ScriptEdit(BaseModel):
    script: str


@app.put("/api/projects/{pid}/script")
def edit_script(pid: str, body: ScriptEdit):
    proj = jobs.Project(pid)
    if not proj.meta_path.exists():
        raise HTTPException(404)
    proj.save(script=body.script)
    return {"ok": True}


@app.post("/api/upload/video/{pid}")
async def upload_video(pid: str, file: UploadFile):
    proj = jobs.Project(pid)
    if not proj.meta_path.exists():
        raise HTTPException(404)
    jobs.attach_video(pid, file.filename or "video.mp4", await file.read())
    jobs.start_edit(pid)
    return {"ok": True}


@app.post("/api/upload/videos")
async def upload_videos_batch(files: list[UploadFile]):
    """批量上传口播视频：按文件名自动匹配论文项目，匹配上即自动开剪。"""
    results = []
    for f in files:
        pid = jobs.match_video_to_project(f.filename or "")
        if pid:
            jobs.attach_video(pid, f.filename or "video.mp4", await f.read())
            jobs.start_edit(pid)
        results.append({"file": f.filename, "matched": pid})
    return results


class TitlePick(BaseModel):
    title: str


@app.put("/api/projects/{pid}/title")
def pick_title(pid: str, body: TitlePick):
    if not jobs.Project(pid).meta_path.exists():
        raise HTTPException(404)
    jobs.set_title(pid, body.title)
    return {"ok": True}


class IntroEdit(BaseModel):
    intro: str


@app.put("/api/projects/{pid}/intro")
def edit_intro(pid: str, body: IntroEdit):
    if not jobs.Project(pid).meta_path.exists():
        raise HTTPException(404)
    jobs.Project(pid).save(intro=body.intro)
    return {"ok": True}


@app.post("/api/pick_folder")
def pick_folder():
    """弹出 macOS 原生文件夹选择框，返回所选路径。"""
    import subprocess  # noqa: PLC0415
    script = ('tell application "System Events" to activate\n'
              'POSIX path of (choose folder with prompt "选择导出文件夹")')
    try:
        r = subprocess.run(["osascript", "-e", script],
                           capture_output=True, text=True, timeout=180)
    except subprocess.TimeoutExpired:
        raise HTTPException(408, "选择超时") from None
    path = r.stdout.strip()
    if r.returncode != 0 or not path:
        raise HTTPException(400, "已取消选择")
    return {"path": path}


class ExportReq(BaseModel):
    ids: list[str]
    dest: str
    include: list[str] | None = None  # slideshow/final/cover/narration/copy


@app.post("/api/export")
def export(body: ExportReq):
    if not body.ids:
        raise HTTPException(400, "没有选择项目")
    return jobs.export_projects(body.ids, body.dest or "~/Desktop/paper2video导出",
                                include=body.include)


@app.post("/api/tts_video/{pid}")
def tts_video(pid: str):
    meta = jobs.Project(pid).load()
    if not meta.get("storyboard"):
        raise HTTPException(400, "请先生成文稿和配图")
    jobs.start_tts_video(pid)
    return {"ok": True}


@app.post("/api/tts_video_all")
def tts_video_all():
    started = []
    for meta in jobs.list_projects():
        if meta.get("storyboard") and not meta.get("tts_output") \
                and meta.get("state") not in ("running", "editing", "queued"):
            jobs.start_tts_video(meta["id"])
            started.append(meta["id"])
    return {"started": started}


@app.post("/api/edit/{pid}")
def rerun_edit(pid: str):
    meta = jobs.Project(pid).load()
    if not meta.get("video"):
        raise HTTPException(400, "该项目还没有上传口播视频")
    jobs.start_edit(pid)
    return {"ok": True}


class StudioSettings(BaseModel):
    base_url: str | None = None
    image_protocol: str | None = None
    language_provider: str | None = None
    image_provider: str | None = None
    model_text: str | None = None
    model_cover: str | None = None
    voice: str | None = None
    rate: str | None = None


@app.get("/api/settings")
def settings():
    return studio_settings.public_settings()


@app.put("/api/settings")
def update_settings(body: StudioSettings):
    if jobs.busy_count():
        raise HTTPException(409,"有任务运行中，完成后再修改设置")
    try:
        return studio_settings.save_settings(body.model_dump(exclude_none=True))
    except ValueError as error:
        raise HTTPException(400,str(error)) from error


@app.post("/api/settings/test")
def test_settings():
    try:
        return studio_settings.check_connection()
    except ValueError as error:
        raise HTTPException(400,str(error)) from error


@app.post("/api/generate/{pid}")
def generate_video(pid: str):
    try:
        jobs.start_full_video(pid)
    except ValueError as error:
        raise HTTPException(400,str(error)) from error
    return {"ok":True}


@app.get("/watch/{pid}")
def watch(pid: str):
    try:
        project=jobs.Project(pid)
    except ValueError as error:
        raise HTTPException(404,"项目不存在") from error
    if not project.meta_path.exists():raise HTTPException(404,"项目不存在")
    return FileResponse(WEB_DIR/"watch.html",headers={"Cache-Control":"no-store"})


@app.get("/api/projects/{pid}/experience")
def experience(pid: str):
    from .pipeline import interactive
    try:
        project=jobs.Project(pid)
        manifest=interactive.build_manifest(project.dir,project.load())
    except ValueError as error:
        raise HTTPException(404,"项目不存在") from error
    if not manifest:raise HTTPException(409,"此作品尚未生成分章节视频，请返回工作室重新生成")
    return manifest


@app.get("/api/projects/{pid}/interactive.zip")
def interactive_bundle(pid: str):
    from .pipeline import interactive
    try:
        project=jobs.Project(pid)
        if jobs._pending(pid):raise HTTPException(409,"视频生成中，完成后再导出")
        path=interactive.export_bundle(project.dir,project.load())
    except ValueError as error:
        raise HTTPException(400,str(error)) from error
    return FileResponse(path,media_type="application/zip",filename="aha-paper-interactive.zip")


@app.get("/api/settings/models")
def setting_models(usage: str = "language", provider: str | None = None):
    if usage not in ("language","image","code"):raise HTTPException(400,"未知模型用途")
    try:return studio_settings.model_catalog(usage,provider)
    except (ValueError, pi_models.ProviderError) as error:raise HTTPException(400,str(error)) from error


class ProviderKey(BaseModel):
    api_key: str


@app.get("/api/providers")
def list_providers():
    """Every provider Pi knows, with its connection state and credential source."""
    try:return {"providers":pi_models.providers()}
    except pi_models.ProviderError as error:raise HTTPException(503,str(error)) from error


@app.post("/api/providers/{provider}/login")
def connect_provider(provider: str, body: ProviderKey):
    """Store a provider credential. The key goes to Pi's store and is never echoed back."""
    if jobs.busy_count():raise HTTPException(409,"有任务运行中，完成后再修改设置")
    try:return pi_models.login(provider,body.api_key)
    except pi_models.ProviderError as error:raise HTTPException(400,str(error)) from error


@app.post("/api/providers/{provider}/logout")
def disconnect_provider(provider: str):
    if jobs.busy_count():raise HTTPException(409,"有任务运行中，完成后再修改设置")
    try:return pi_models.logout(provider)
    except pi_models.ProviderError as error:raise HTTPException(400,str(error)) from error
