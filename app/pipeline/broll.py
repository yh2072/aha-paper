"""YouTube 实拍素材（B-roll）：给合适的场景配真实视频画面，替代部分 AI 插画。

- 搜索走 ahafrog-youtube-know 项目的 youtubei.js（无需 API key）
- 片段用 yt-dlp 只下所需的几十秒，静音使用（配音是我们自己的）
- 画面上角标注来源频道，credits 汇总进导出文案，便于注明出处
"""
import json
import os
import subprocess
from pathlib import Path

from .. import config, llm

YT_PROJECT = Path(os.getenv(
    "YT_PROJECT", "/Users/yuqihang/dev/ahafrog-youtube-know"))
YTDLP = YT_PROJECT / ".venv" / "bin" / "yt-dlp"
CLIP_LEAD = 0.25       # 从视频 25% 处开始取，避开片头
MIN_SRC_SEC = 45       # 太短的源视频不用
MAX_SRC_SEC = 1800

_PLAN_PROMPT = """下面是一条科普视频的分镜（每段是一个场景）。有些场景用**真实拍摄画面**
比手绘插画更有说服力（实验室、大脑扫描、动物实验、城市生活、人在做某件事……），
有些场景更适合保留可爱手绘（抽象比喻、拟人化概念）。

对每个场景判断，并给出 JSON：
{{"plans": [{{"index": 场景序号从0开始, "use_broll": true/false,
             "queries": ["镜头1的英文搜索词", "镜头2", "镜头3"]}}]}}

queries 是这个场景的**分镜头清单**：一个场景要 4~6 个**互不相同**的画面轮流出现
（成片是 2 秒一换的快切节奏，镜头越多越不容易重复）。
几个镜头要从不同角度呈现同一件事，例如"人被 AI 影响创造力"可以是：
person typing laptop late night / hands writing notebook closeup /
coffee cup desk workspace / people working open office

规则：
- 只给最多 {max_broll} 个场景用实拍，挑画面感最强、最能"眼见为实"的
- query 必须是**找画面**的简短搜索词（2~5 个词），描述看得见的东西，不是论文术语。
  主力素材源是空镜素材库，所以用日常可拍的具体画面
  （好例子：brain scan machine / person studying at night / laboratory microscope /
   city crowd walking；坏例子：cortical hierarchy gradient、白质纤维束）
- 避免会搜到"真人对镜头讲解"的词（explained / lecture / how it works / tutorial）
- 抽象比喻场景一律 use_broll=false（手绘更好）
- plans 长度必须等于场景数 {n}

分镜：
{scenes}"""


def available() -> bool:
    return (YT_PROJECT / "scripts" / "yt_search.mjs").exists() and YTDLP.exists()


def plan(scenes: list[dict], max_broll: int = 5, log=print) -> list[dict]:
    """决定哪些场景用实拍素材 + 搜索词。"""
    desc = "\n".join(
        f"{i}. {sc['text'][:70]}" for i, sc in enumerate(scenes)
        if not sc.get("figure_path"))  # 讲图场景不动
    try:
        ans = llm.chat_json([{"role": "user", "content": _PLAN_PROMPT.format(
            scenes=desc, n=len(scenes), max_broll=max_broll)}], temperature=0.3)
        plans = []
        for p in ans.get("plans", []):
            qs = [q for q in (p.get("queries") or
                              ([p["query"]] if p.get("query") else [])) if q]
            if p.get("use_broll") and qs:
                plans.append({"index": p.get("index"), "queries": qs[:6],
                              "query": qs[0]})
        # 讲图场景强制排除，且不超过上限
        fig_idx = {i for i, sc in enumerate(scenes) if sc.get("figure_path")}
        plans = [p for p in plans if int(p.get("index", -1)) not in fig_idx][:max_broll]
        log(f"  B-roll 计划 {len(plans)} 个场景: "
            + ", ".join(f"#{p['index']+1} {p['query'][:28]}" for p in plans))
        return plans
    except Exception as e:  # noqa: BLE001
        log(f"  B-roll 规划失败: {e}")
        return []


def _search(query: str, limit: int = 6) -> list[dict]:
    out = subprocess.run(["node", "scripts/yt_search.mjs", query, str(limit)],
                         cwd=YT_PROJECT, capture_output=True, text=True, timeout=180)
    try:
        return json.loads(out.stdout or "[]")
    except json.JSONDecodeError:
        return []


_OFFSETS = (0.35, 0.55, 0.20)   # 依次尝试的取材位置（避开片头/片尾）
ACCEPT = 7                      # 视觉评分达标线
PEXELS_KEY = os.getenv("pexel_api_key") or os.getenv("PEXELS_API_KEY", "")


def _pexels_search(query: str, limit: int = 8) -> list[dict]:
    """Pexels 空镜库：免费可商用、无水印、无人声，天生就是素材。"""
    if not PEXELS_KEY:
        return []
    import httpx  # noqa: PLC0415
    try:
        r = httpx.get("https://api.pexels.com/videos/search",
                      headers={"Authorization": PEXELS_KEY},
                      params={"query": query, "per_page": limit,
                              "orientation": "landscape", "size": "medium"},
                      timeout=60)
        r.raise_for_status()
        out = []
        for v in r.json().get("videos", []):
            files = [f for f in v.get("video_files", [])
                     if f.get("file_type") == "video/mp4" and (f.get("width") or 0) >= 640]
            if not files:
                continue
            # 取接近 1280 宽的那档，画质够用又不至于太大
            best = min(files, key=lambda f: abs((f.get("width") or 0) - 1280))
            out.append({"link": best["link"], "durationSec": v.get("duration", 0),
                        "author": (v.get("user") or {}).get("name", "Pexels"),
                        "title": f"Pexels #{v.get('id')}", "url": v.get("url", "")})
        return out
    except Exception:  # noqa: BLE001
        return []


def _pexels_grab(cand: dict, start: float, dur: float, out_mp4: Path) -> bool:
    import httpx  # noqa: PLC0415
    tmp = out_mp4.with_suffix(".src.mp4")
    try:
        with httpx.stream("GET", cand["link"], timeout=180,
                          follow_redirects=True) as r:
            r.raise_for_status()
            with open(tmp, "wb") as f:
                for chunk in r.iter_bytes(1 << 16):
                    f.write(chunk)
        proc = subprocess.run(
            ["ffmpeg", "-y", "-ss", f"{start:.2f}", "-i", str(tmp),
             "-t", f"{dur:.2f}", "-an", "-c:v", "h264_videotoolbox", "-b:v", "8M", "-pix_fmt", "yuv420p", str(out_mp4)], capture_output=True, timeout=300)
        return proc.returncode == 0 and out_mp4.exists() \
            and out_mp4.stat().st_size > 40_000
    except Exception:  # noqa: BLE001
        return False
    finally:
        tmp.unlink(missing_ok=True)


def _grab(vid: str, start: float, dur: float, out_mp4: Path) -> bool:
    proc = subprocess.run(
        [str(YTDLP), "-q", "--no-warnings",
         "-f", "bv*[height<=720][ext=mp4]/bv*[height<=720]/b[height<=720]",
         "--download-sections", f"*{start:.0f}-{start + dur:.0f}",
         "--force-keyframes-at-cuts", "-o", str(out_mp4),
         f"https://www.youtube.com/watch?v={vid}"],
        capture_output=True, text=True, timeout=600)
    return proc.returncode == 0 and out_mp4.exists() and out_mp4.stat().st_size > 50_000


def _score_clip(clip: Path, want: str, log=print) -> tuple[int, str]:
    """抽 3 帧拼图让视觉模型打分：画面是否好看、切题、没有说话人头/字幕/水印。"""
    import base64  # noqa: PLC0415
    from io import BytesIO  # noqa: PLC0415

    from PIL import Image  # noqa: PLC0415
    dur = float(subprocess.run(
        ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(clip)], capture_output=True, text=True).stdout or 6)
    tiles = []
    for t in (dur * 0.15, dur * 0.5, dur * 0.85):
        p = clip.with_suffix(f".f{int(t * 10)}.jpg")
        subprocess.run(["ffmpeg", "-y", "-ss", f"{t:.2f}", "-i", str(clip),
                        "-frames:v", "1", "-vf", "scale=420:-2", str(p)],
                       capture_output=True)
        if p.exists():
            tiles.append(p)
    if not tiles:
        return 0, "抽帧失败"
    ims = [Image.open(p) for p in tiles]
    sheet = Image.new("RGB", (sum(i.width for i in ims), max(i.height for i in ims)))
    x = 0
    for i in ims:
        sheet.paste(i, (x, 0))
        x += i.width
    bio = BytesIO()
    sheet.save(bio, "JPEG", quality=82)
    for p in tiles:
        p.unlink(missing_ok=True)
    try:
        ans = llm.chat_json([{"role": "user", "content": [
            {"type": "text", "text":
             f"这是一段候选视频素材的三帧。它要用作科普视频的画面素材，主题：{want}\n"
             "按 0-10 打分并说明。以下情况直接给 0-3 分：\n"
             "- 画面主体是人在对着镜头说话（talking head）\n"
             "- 满屏文字、PPT 讲义、大段英文标注\n"
             "- 有赞助商水印/广告/频道 logo 占画面\n"
             "- 内容与主题无关\n"
             "8-10 分：画面干净有视觉冲击、和主题直接相关、像纪录片/实拍/精美动画。\n"
             '只输出 JSON：{"score": 数字, "why": "十几个字的理由"}'},
            {"type": "image_url", "image_url": {
                "url": "data:image/jpeg;base64," + base64.b64encode(bio.getvalue()).decode()}},
        ]}], temperature=0.1)
        return int(ans.get("score", 0)), str(ans.get("why", ""))[:30]
    except Exception as e:  # noqa: BLE001
        log(f"    评分失败: {str(e)[:50]}")
        return 0, "评分失败"


def fetch_clip(query: str, want_sec: float, out_mp4: Path, log=print,
               want_desc: str = "") -> dict | None:
    """搜索 → 下载候选片段 → 视觉模型打分 → 取最好的一段（不达标就换视频/换位置）。"""
    want = want_desc or query
    best = None  # (score, credit)
    tmp = out_mp4.with_suffix(".cand.mp4")

    # ① 首选 Pexels 空镜库：免费可商用、无水印、无口播人头
    for c in _pexels_search(query, 8)[:5]:
        dur = float(c.get("durationSec") or 0)
        start = 0.5 if dur < want_sec + 3 else min(dur * 0.25, 4)
        tmp.unlink(missing_ok=True)
        if not _pexels_grab(c, start, want_sec + 2, tmp):
            continue
        score, why = _score_clip(tmp, want, log=log)
        log(f"    Pexels {str(c['author'])[:14]} → {score}分 {why}")
        if best is None or score > best[0]:
            tmp.replace(out_mp4)
            best = (score, {"title": c["title"], "author": f"Pexels · {c['author']}",
                            "url": c["url"], "query": query, "score": score})
        if score >= ACCEPT:
            log(f"  B-roll ✓ {best[1]['author']}")
            tmp.unlink(missing_ok=True)
            return best[1]

    # ② 退回 YouTube（同样要过视觉验证）
    for v in _search(query, 6)[:5]:
        dur = float(v.get("durationSec") or 0)
        if not (MIN_SRC_SEC <= dur <= MAX_SRC_SEC):
            continue
        vid = v.get("id")
        for frac in _OFFSETS[:2]:  # 每个视频最多试两个位置
            start = max(dur * frac, 5)
            if start + want_sec + 2 > dur - 2:
                continue
            tmp.unlink(missing_ok=True)
            if not _grab(vid, start, want_sec + 2, tmp):
                break  # 这个视频下不动，换下一个
            score, why = _score_clip(tmp, want, log=log)
            log(f"    候选 {str(v.get('author'))[:14]} @{frac:.0%} → {score}分 {why}")
            if best is None or score > best[0]:
                tmp.replace(out_mp4)
                best = (score, {"title": v.get("title", ""),
                                "author": v.get("author", ""),
                                "url": f"https://youtu.be/{vid}", "query": query,
                                "score": score})
            if score >= ACCEPT:
                log(f"  B-roll ✓ {best[1]['author']} · {str(best[1]['title'])[:30]}")
                tmp.unlink(missing_ok=True)
                return best[1]
    tmp.unlink(missing_ok=True)
    if best and best[0] >= 5:  # 没有满分候选，用矮子里的高个
        log(f"  B-roll ~ 勉强可用({best[0]}分) {best[1]['author']}")
        return best[1]
    out_mp4.unlink(missing_ok=True)
    log(f"  B-roll ✗ 没有够格的素材，保留手绘: {query}")
    return None


SHOT_SEC = 2.0          # 每个镜头出镜时长（快切节奏）
NORM_W, NORM_H = 1080, 900


def _normalize(src: Path, start: float, dur: float, out: Path) -> bool:
    """统一成同参数片段，便于拼接：裁到 1080x900、30fps、无音轨。"""
    proc = subprocess.run(
        ["ffmpeg", "-y", "-ss", f"{start:.2f}", "-i", str(src), "-t", f"{dur:.2f}",
         "-vf", f"scale={NORM_W}:{NORM_H}:force_original_aspect_ratio=increase,"
                f"crop={NORM_W}:{NORM_H},fps=30",
         "-an", "-c:v", "h264_videotoolbox", "-b:v", "8M", "-pix_fmt", "yuv420p", str(out)], capture_output=True)
    return proc.returncode == 0 and out.exists() and out.stat().st_size > 20_000


def _assemble(clips: list[Path], total: float, out: Path, work: Path,
              log=print) -> bool:
    """多个镜头轮流出镜拼成整段：每 SHOT_SEC 秒换一个画面，重复时换起始点。"""
    pieces, t, k = [], 0.0, 0
    while t < total - 0.3 and k < 40:
        src = clips[k % len(clips)]
        d = float(subprocess.run(
            ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
             "-of", "csv=p=0", str(src)], capture_output=True, text=True).stdout or 8)
        take = min(SHOT_SEC, total - t)
        loop = k // len(clips)                    # 第几轮用到这条素材
        start = min(loop * SHOT_SEC, max(d - take - 0.2, 0))
        p = work / f"shot_{k:02d}.mp4"
        if _normalize(src, start, take, p):
            pieces.append(p)
            t += take
        k += 1
    if not pieces:
        return False
    lst = work / "shots.txt"
    lst.write_text("".join(f"file '{p.resolve()}'\n" for p in pieces))
    ok = subprocess.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0",
                         "-i", str(lst), "-c", "copy", str(out)],
                        capture_output=True).returncode == 0
    for p in pieces:
        p.unlink(missing_ok=True)
    log(f"    拼接 {len(pieces)} 个镜头 → {total:.0f}s")
    return ok


def collect(scenes: list[dict], plans: list[dict], out_dir: Path,
            durations: list[float] | None = None, log=print) -> list[dict]:
    """每个场景抓多个镜头并轮流出镜，写回 scene['broll_path']；返回 credits。"""
    out_dir.mkdir(parents=True, exist_ok=True)
    work = out_dir / "_shots"
    work.mkdir(exist_ok=True)
    credits = []
    for p in plans:
        i = int(p["index"])
        if not (0 <= i < len(scenes)):
            continue
        want = durations[i] if durations and i < len(durations) else 14.0
        # 2 秒一换 → 需要更多不同镜头；上限受搜索词条数限制
        n_shots = max(1, min(int(want / SHOT_SEC) or 1, len(p["queries"])))
        clips, got = [], []
        for q in p["queries"][:n_shots]:
            cand = work / f"raw_{i:02d}_{len(clips)}.mp4"
            c = fetch_clip(q, min(SHOT_SEC + 3, want), cand, log=log,
                           want_desc=scenes[i]["text"][:90])
            if c:
                clips.append(cand)
                got.append(c)
        if not clips:
            continue
        dst = out_dir / f"broll_{i:02d}.mp4"
        if len(clips) == 1 and want <= SHOT_SEC * 1.5:
            clips[0].replace(dst)
        elif not _assemble(clips, want, dst, work, log=log):
            clips[0].replace(dst)
        scenes[i]["broll_path"] = str(dst)
        for c in got:
            c["scene"] = i + 1
            credits.append(c)
        log(f"  场景 {i + 1}：{len(clips)} 个镜头覆盖 {want:.0f}s")
    for f in work.glob("raw_*.mp4"):
        f.unlink(missing_ok=True)
    return credits
