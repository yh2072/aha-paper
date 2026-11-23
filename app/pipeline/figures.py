"""用 models/main-figure-best.onnx（YOLOv8, 单类 main-figure）从论文 PDF 里抠出主图。"""
import base64
from io import BytesIO
from pathlib import Path

import numpy as np
import pypdfium2 as pdfium
from PIL import Image

from .. import config, llm
from ..bin import ffmpeg as ffmpeg_bin, ffprobe as ffprobe_bin

MODEL_PATH = config.ROOT / "models" / "main-figure-best.onnx"
IMGSZ = 640
CONF_TH = 0.35
IOU_TH = 0.5
MAX_PAGES = 12          # 论文正文主图基本都在前面
MIN_AREA_FRAC = 0.04    # 过滤小碎图（占页面面积比）
MAX_FIGS = 6

_session = None


def available() -> bool:
    return MODEL_PATH.exists()


def _get_session():
    global _session
    if _session is None:
        import onnxruntime as ort  # noqa: PLC0415
        _session = ort.InferenceSession(str(MODEL_PATH),
                                        providers=["CPUExecutionProvider"])
    return _session


def _letterbox(img: Image.Image) -> tuple[np.ndarray, float, tuple[int, int]]:
    w, h = img.size
    r = min(IMGSZ / w, IMGSZ / h)
    nw, nh = round(w * r), round(h * r)
    pad_x, pad_y = (IMGSZ - nw) // 2, (IMGSZ - nh) // 2
    canvas = Image.new("RGB", (IMGSZ, IMGSZ), (114, 114, 114))
    canvas.paste(img.resize((nw, nh)), (pad_x, pad_y))
    arr = np.asarray(canvas, dtype=np.float32).transpose(2, 0, 1)[None] / 255.0
    return arr, r, (pad_x, pad_y)


def _nms(boxes: np.ndarray, scores: np.ndarray) -> list[int]:
    order = scores.argsort()[::-1]
    keep = []
    while order.size:
        i = order[0]
        keep.append(int(i))
        if order.size == 1:
            break
        rest = boxes[order[1:]]
        xx1 = np.maximum(boxes[i, 0], rest[:, 0])
        yy1 = np.maximum(boxes[i, 1], rest[:, 1])
        xx2 = np.minimum(boxes[i, 2], rest[:, 2])
        yy2 = np.minimum(boxes[i, 3], rest[:, 3])
        inter = np.clip(xx2 - xx1, 0, None) * np.clip(yy2 - yy1, 0, None)
        area_i = (boxes[i, 2] - boxes[i, 0]) * (boxes[i, 3] - boxes[i, 1])
        area_r = (rest[:, 2] - rest[:, 0]) * (rest[:, 3] - rest[:, 1])
        iou = inter / (area_i + area_r - inter + 1e-9)
        order = order[1:][iou < IOU_TH]
    return keep


def _detect(page_img: Image.Image) -> list[tuple[float, float, float, float, float]]:
    """返回原图坐标系下的 (x1, y1, x2, y2, conf)。"""
    inp, r, (px, py) = _letterbox(page_img)
    (out,) = _get_session().run(None, {"images": inp})  # [1, 5, 8400]
    pred = out[0].T                                     # [8400, 5] = cx,cy,w,h,conf
    pred = pred[pred[:, 4] >= CONF_TH]
    if not len(pred):
        return []
    cx, cy, w, h = pred[:, 0], pred[:, 1], pred[:, 2], pred[:, 3]
    boxes = np.stack([cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2], axis=1)
    keep = _nms(boxes, pred[:, 4])
    W, H = page_img.size
    results = []
    for i in keep:
        x1 = max((boxes[i, 0] - px) / r, 0)
        y1 = max((boxes[i, 1] - py) / r, 0)
        x2 = min((boxes[i, 2] - px) / r, W)
        y2 = min((boxes[i, 3] - py) / r, H)
        if (x2 - x1) * (y2 - y1) >= MIN_AREA_FRAC * W * H:
            results.append((x1, y1, x2, y2, float(pred[i, 4])))
    return results


def extract_main_figures(pdf_path: Path, out_dir: Path, log=print) -> list[dict]:
    """抠出主图存盘，返回 [{"file", "page", "conf"}]，按 (页码, 纵向位置) 排序。"""
    out_dir.mkdir(parents=True, exist_ok=True)
    doc = pdfium.PdfDocument(str(pdf_path))
    found = []
    for pno in range(min(len(doc), MAX_PAGES)):
        page_img = doc[pno].render(scale=2.2).to_pil().convert("RGB")
        for (x1, y1, x2, y2, conf) in _detect(page_img):
            found.append((pno, y1, conf, page_img.crop(
                (max(x1 - 8, 0), max(y1 - 8, 0),
                 min(x2 + 8, page_img.width), min(y2 + 8, page_img.height)))))
    found.sort(key=lambda t: (t[0], t[1]))
    figs = []
    for i, (pno, _, conf, crop) in enumerate(found[:MAX_FIGS]):
        name = f"fig_{i + 1:02d}.png"
        crop.save(out_dir / name)
        figs.append({"file": name, "page": pno + 1, "conf": round(conf, 2)})
    log(f"  ONNX 检出主图 {len(figs)} 张")

    # 检出太少时启用视觉兜底。讲图是这条视频的核心卖点，宁可多花几次调用，
    # 也不要因为版式不合检测器胃口就整篇没图可讲。
    if len(figs) < MIN_FIGS:
        pages_taken = {f["page"] for f in figs}
        extra = [f for f in _vision_find_figures(doc, out_dir, len(figs), log=log)
                 if f["page"] not in pages_taken]      # 同一页不重复抠
        figs = (figs + extra)[:MAX_FIGS]
        figs.sort(key=lambda f: f["page"])
    doc.close()
    return figs


MIN_FIGS = 2          # 少于这个数就启用视觉兜底
VISION_MAX_PAGES = 4  # 兜底最多细看几页，控制花销


def _contact_sheet(pages: list[Image.Image], cols: int = 4,
                   cell: int = 300) -> Image.Image:
    """把多页缩略图拼成一张联系表，页码烙在左上角。

    为什么拼版：逐页问视觉模型要花 N 次调用，拼成一张只花 1 次就能问出
    "哪几页有主图"，再对少数命中页单独要坐标。
    """
    from PIL import ImageDraw  # noqa: PLC0415
    rows = (len(pages) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * cell, rows * cell), (255, 255, 255))
    d = ImageDraw.Draw(sheet)
    for i, p in enumerate(pages):
        t = p.copy()
        t.thumbnail((cell - 8, cell - 8), Image.LANCZOS)
        x, y = (i % cols) * cell, (i // cols) * cell
        sheet.paste(t, (x + 4, y + 4))
        d.rectangle([x, y, x + cell - 1, y + cell - 1], outline=(200, 200, 200))
        d.rectangle([x + 2, y + 2, x + 34, y + 22], fill=(255, 80, 80))
        d.text((x + 8, y + 6), f"P{i + 1}", fill=(255, 255, 255))
    return sheet


def _vision_find_figures(doc, out_dir: Path, start_idx: int,
                         log=print) -> list[dict]:
    """ONNX 认不出版式时的兜底：让视觉模型指认主图所在页并给出位置。

    检测器是拿 Nature/Science 版式训的，换成综述或老论文就抓瞎。这里不依赖
    版式，靠"看得懂图"来找，代价是每篇多几次视觉调用。
    """
    n = min(len(doc), MAX_PAGES)
    pages = [doc[i].render(scale=2.2).to_pil().convert("RGB") for i in range(n)]
    sheet = _contact_sheet(pages)
    b64 = base64.b64encode(_png_bytes(sheet, max_side=1600)).decode()
    try:
        ans = llm.chat_json([{"role": "user", "content": [
            {"type": "text", "text":
             "这是一篇论文所有页面的缩略图拼版，每格左上角红标是页码。\n"
             "找出哪些页含有【正文主图】——就是带数据的图表、示意图、"
             "实验结果图（有坐标轴的曲线图、柱状图、脑图、流程示意图都算）。\n"
             "不要选：纯文字页、参考文献页、只有表格的页、期刊页眉页脚装饰、"
             "作者照片。\n"
             f'按重要性排序，最多给 {VISION_MAX_PAGES} 页。'
             '只输出 JSON：{"pages": [页码, ...]}'},
            {"type": "image_url",
             "image_url": {"url": f"data:image/png;base64,{b64}"}},
        ]}], temperature=0.1)
        cand = [int(p) for p in ans.get("pages", []) if 1 <= int(p) <= n]
    except Exception as e:  # noqa: BLE001 - 兜底失败就维持无图流程
        log(f"  视觉兜底：选页失败（{e}），按无图流程继续")
        return []
    if not cand:
        log("  视觉兜底：这篇确实没有可讲的主图")
        return []
    log(f"  视觉兜底：第 {cand} 页可能有主图，逐页定位…")

    figs = []
    for pno in cand[:VISION_MAX_PAGES]:
        page = pages[pno - 1]
        pb64 = base64.b64encode(_png_bytes(page, max_side=1600)).decode()
        try:
            ans = llm.chat_json([{"role": "user", "content": [
                {"type": "text", "text":
                 "这是论文的一页。框出页面上【最主要的那张插图】的位置，"
                 "只框图本身连同它的图注，不要框正文段落。\n"
                 '只输出 JSON：{"bbox": [x, y, w, h]}，'
                 "为归一化坐标（0~1，x/y 是左上角）。这页没有插图就给 null。"},
                {"type": "image_url",
                 "image_url": {"url": f"data:image/png;base64,{pb64}"}},
            ]}], temperature=0.1)
            bb = ans.get("bbox")
            if not bb:
                continue
            x, y, w, h = (float(v) for v in bb)
            # 视觉模型给的框通常偏松，先按比例裁再 _trim_white 收边
            if not (0 <= x < 1 and 0 <= y < 1 and 0.1 < w <= 1 and 0.05 < h <= 1):
                continue
            W, H = page.size
            crop = page.crop((int(x * W), int(y * H),
                              int(min(x + w, 1) * W), int(min(y + h, 1) * H)))
            crop = _trim_white(crop)
            if crop.width < 200 or crop.height < 120:   # 太小的多半框歪了
                continue
            name = f"fig_{start_idx + len(figs) + 1:02d}.png"
            crop.save(out_dir / name)
            figs.append({"file": name, "page": pno, "conf": 0.0, "via": "vision"})
        except Exception as e:  # noqa: BLE001 - 单页失败跳过，不毁整篇
            log(f"    第{pno}页定位失败: {e}")
    log(f"  视觉兜底：补到 {len(figs)} 张主图")
    return figs


def extract_title_snippet(pdf_path: Path, out_path: Path, paper_title: str,
                          log=print) -> Path | None:
    """从论文第一页截取真实标题区域的截图（程序合成用）。

    首选 pdfium 文本搜索精确定位标题字符的包围盒；搜不到再让视觉模型给 bbox。
    """
    doc = pdfium.PdfDocument(str(pdf_path))
    try:
        page = doc[0]
        scale = 2.4
        page_img = page.render(scale=scale).to_pil().convert("RGB")
        pw, ph = page.get_size()

        rects = []
        try:
            tp = page.get_textpage()
            words = paper_title.split()
            for needle in {" ".join(words[:6]), " ".join(words[-6:])}:
                if len(needle) < 8:
                    continue
                found = tp.search(needle, match_case=False).get_next()
                if found:
                    idx, cnt = found
                    for i in range(tp.count_rects(idx, cnt)):
                        rects.append(tp.get_rect(i))
        except Exception as e:  # noqa: BLE001
            log(f"  pdfium 标题搜索失败: {e}")

        if rects:
            x1 = min(r[0] for r in rects) * scale
            x2 = max(r[2] for r in rects) * scale
            # PDF 坐标原点在左下 → 转成图像坐标
            y1 = min(ph - r[3] for r in rects) * scale
            y2 = max(ph - r[1] for r in rects) * scale
        else:
            b64 = base64.b64encode(_png_bytes(page_img, max_side=1600)).decode()
            ans = llm.chat_json([{"role": "user", "content": [
                {"type": "text", "text":
                 f"定位这页论文里标题《{paper_title[:120]}》文字块的位置，"
                 '只输出 JSON：{"bbox": [x, y, w, h]}（0~1 归一化，x/y 为左上角）'},
                {"type": "image_url",
                 "image_url": {"url": f"data:image/png;base64,{b64}"}},
            ]}], temperature=0.1)
            x, y, w, h = (float(v) for v in ans["bbox"])
            x1, y1 = x * page_img.width, y * page_img.height
            x2, y2 = x1 + w * page_img.width, y1 + h * page_img.height

        pad = 14
        W_img, H_img = page_img.size
        if y1 < H_img * 0.35:
            # 标题在页面上部 → 从页首整宽截到标题底部，把期刊名/刊头一起带上
            crop = page_img.crop((int(W_img * 0.025), 2,
                                  int(W_img * 0.975), int(min(y2 + pad, H_img))))
            crop = _trim_white(crop)
        else:
            crop = page_img.crop((max(x1 - pad, 0), max(y1 - pad, 0),
                                  min(x2 + pad, W_img), min(y2 + pad, H_img)))
        if crop.width < 80 or crop.height < 16:
            return None
        out_path.parent.mkdir(parents=True, exist_ok=True)
        crop.save(out_path)
        log(f"  标题截图 {crop.width}x{crop.height} ✓")
        return out_path
    except Exception as e:  # noqa: BLE001
        log(f"  标题截图失败: {e}")
        return None
    finally:
        doc.close()


def _trim_white(img: Image.Image, thresh: int = 244, pad: int = 12) -> Image.Image:
    """裁掉四周的空白边（保留 pad 像素呼吸感）。"""
    arr = np.asarray(img.convert("L"))
    ink = np.argwhere(arr < thresh)
    if not len(ink):
        return img
    y1, x1 = ink.min(axis=0)
    y2, x2 = ink.max(axis=0)
    return img.crop((max(int(x1) - pad, 0), max(int(y1) - pad, 0),
                     min(int(x2) + pad, img.width), min(int(y2) + pad, img.height)))


def _png_bytes(img: Image.Image, max_side: int = 1600) -> bytes:
    im = img.copy()
    im.thumbnail((max_side, max_side))
    bio = BytesIO()
    im.save(bio, "PNG")
    return bio.getvalue()


def pick_avatar_face(video: Path, out_png: Path, log=print) -> Path:
    """从口播视频采样 9 帧，视觉模型选最上镜的一帧（睁眼、表情自然）做圆头像。"""
    import subprocess  # noqa: PLC0415
    import tempfile  # noqa: PLC0415
    dur = float(subprocess.run(
        [ffprobe_bin(), "-v", "quiet", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(video)], capture_output=True, text=True).stdout or 10)
    times = [0.5 + (dur - 1.0) * k / 8 for k in range(9)]
    with tempfile.TemporaryDirectory() as td:
        cells = []
        for k, t in enumerate(times):
            f = Path(td) / f"c{k}.png"
            subprocess.run([ffmpeg_bin(), "-y", "-ss", f"{t:.2f}", "-i", str(video),
                            "-frames:v", "1", "-vf", "scale=300:-2", str(f)],
                           capture_output=True)
            if f.exists():
                cells.append((k, t, f))
        if not cells:
            raise RuntimeError("无法从视频抽帧")
        cw, ch = 300, Image.open(cells[0][2]).height
        sheet = Image.new("RGB", (cw * 3, ch * 3), (0, 0, 0))
        from PIL import ImageDraw as _ID, ImageFont as _IF  # noqa: PLC0415
        font = _IF.load_default(size=40)
        for k, _, f in cells:
            im = Image.open(f)
            x, y = (k % 3) * cw, (k // 3) * ch
            sheet.paste(im, (x, y))
            _ID.Draw(sheet).text((x + 10, y + 8), str(k + 1), font=font,
                                 fill=(255, 80, 80))
        bio = BytesIO()
        sheet.save(bio, "JPEG", quality=85)
        pick = 4  # 兜底：中间帧
        try:
            ans = llm.chat_json([{"role": "user", "content": [
                {"type": "text", "text":
                 "九宫格是同一人的视频帧（左上1号→右下9号）。选一格做头像："
                 "眼睛完全睁开、表情自然好看、最好带笑意、脸不糊。"
                 '只输出 JSON：{"pick": 数字1-9}'},
                {"type": "image_url", "image_url": {
                    "url": "data:image/jpeg;base64,"
                           + base64.b64encode(bio.getvalue()).decode()}},
            ]}], temperature=0.1)
            p = int(ans.get("pick", 5)) - 1
            if 0 <= p < len(cells):
                pick = p
        except Exception as e:  # noqa: BLE001
            log(f"  选帧失败用中间帧: {e}")
        t_best = cells[min(pick, len(cells) - 1)][1]
    subprocess.run([ffmpeg_bin(), "-y", "-ss", f"{t_best:.2f}", "-i", str(video),
                    "-frames:v", "1", str(out_png)], capture_output=True)
    log(f"  头像选帧 t={t_best:.1f}s ✓")
    return out_png


def locate_subfigure(fig_path: Path, scene_text: str) -> list[float] | None:
    """若真实图含多个子图，返回与口播最相关子图的归一化 bbox [x, y, w, h]；否则 None。"""
    b64 = base64.b64encode(fig_path.read_bytes()).decode()
    try:
        ans = llm.chat_json([{"role": "user", "content": [
            {"type": "text", "text":
             "这是论文插图，旁边是一段口播文稿。判断：\n"
             "1. 该图是否由多个子图/面板组成（如 a/b/c 面板、多条曲线子图）\n"
             "2. 若是，哪个子图与口播内容最相关\n"
             '只输出 JSON：{"has_subfigures": true/false, '
             '"bbox": [x, y, w, h]}\n'
             "bbox 是该子图在整图中的归一化位置（0~1，x/y 为左上角），"
             "没有子图时 bbox 给 null。\n\n口播文稿：" + scene_text},
            {"type": "image_url",
             "image_url": {"url": f"data:image/png;base64,{b64}"}},
        ]}], temperature=0.1)
        if ans.get("has_subfigures") and ans.get("bbox"):
            x, y, w, h = (float(v) for v in ans["bbox"])
            if 0 <= x < 1 and 0 <= y < 1 and 0.05 < w <= 1 and 0.05 < h <= 1:
                return [x, y, min(w, 1 - x), min(h, 1 - y)]
    except Exception:  # noqa: BLE001 - 标注失败就不标，不阻塞
        pass
    return None


def _emoji_font(size_candidates=(160, 137, 96, 64)):
    from PIL import ImageFont  # noqa: PLC0415
    for size in size_candidates:
        try:
            return ImageFont.truetype("/System/Library/Fonts/Apple Color Emoji.ttc",
                                      size=size)
        except Exception:  # noqa: BLE001
            continue
    return None


def emoji_layer(emoji: str, target_w: int) -> Image.Image | None:
    """把 emoji 渲染成裁边的透明图层并缩放到 target_w 宽；失败返回 None。"""
    from PIL import ImageDraw as _ID  # noqa: PLC0415
    font = _emoji_font()
    if font is None:
        return None
    try:
        layer = Image.new("RGBA", (font.size * 2, font.size * 2), (0, 0, 0, 0))
        _ID.Draw(layer).text((font.size // 4, font.size // 4), emoji,
                             font=font, embedded_color=True)
        layer = layer.crop(layer.getbbox())
        return layer.resize((target_w, int(target_w * layer.height / layer.width)))
    except Exception:  # noqa: BLE001
        return None


def annotate_figure(src: Path, dst: Path, bbox: list[float]) -> Path:
    """在真实图上给相关子图画高亮圆角框 + 可爱手指光标（signalling）。"""
    from PIL import ImageDraw  # noqa: PLC0415
    img = Image.open(src).convert("RGB")
    W, H = img.size
    x1, y1 = int(bbox[0] * W), int(bbox[1] * H)
    x2, y2 = int((bbox[0] + bbox[2]) * W), int((bbox[1] + bbox[3]) * H)
    draw = ImageDraw.Draw(img)
    lw = max(4, W // 220)
    draw.rounded_rectangle([x1, y1, x2, y2], radius=lw * 3,
                           outline=(214, 108, 90), width=lw)

    font = _emoji_font()
    if font is not None:
        # 子图偏右 → 👉 放左侧；偏左 → 👇 放上方；按图宽自适应大小
        emoji = "👉" if bbox[0] > 0.18 else "👇"
        try:
            layer = Image.new("RGBA", (font.size * 2, font.size * 2), (0, 0, 0, 0))
            ImageDraw.Draw(layer).text((font.size // 4, font.size // 4), emoji,
                                       font=font, embedded_color=True)
            layer = layer.crop(layer.getbbox())
            size = max(48, min(W // 7, 150))
            layer = layer.resize((size, int(size * layer.height / layer.width)))
            if emoji == "👉":
                ex, ey = x1 - int(size * 1.02), (y1 + y2) // 2 - layer.height // 2
            else:
                ex, ey = (x1 + x2) // 2 - size // 2, y1 - int(layer.height * 1.05)
            ex = max(min(ex, W - size), 0)
            ey = max(min(ey, H - layer.height), 0)
            img.paste(layer, (ex, ey), layer)
        except Exception:  # noqa: BLE001
            font = None
    if font is None:  # 兜底：画一个奶油色描边的橙红箭头
        cx, cy = x1 - max(W // 14, 40), (y1 + y2) // 2
        s = max(W // 20, 28)
        pts = [(cx - s, cy - s // 2), (cx, cy - s // 2), (cx, cy - s),
               (cx + s, cy), (cx, cy + s), (cx, cy + s // 2), (cx - s, cy + s // 2)]
        draw.polygon(pts, fill=(214, 108, 90), outline=(250, 244, 230), width=3)
    img.save(dst)
    return dst


def caption_figures(figs: list[dict], fig_dir: Path, log=print) -> list[dict]:
    """视觉模型给每张主图产出：一句图注 + 讲解要点（供写手把图讲透）。"""
    for fig in figs:
        try:
            b64 = base64.b64encode(
                _png_bytes(Image.open(fig_dir / fig["file"]), 1400)).decode()
            ans = llm.chat_json([{"role": "user", "content": [
                {"type": "text", "text":
                 "这是从论文里抠出来的一块图。请仔细读图后输出 JSON：\n"
                 '{"is_figure": true/false,\n'
                 ' "caption": "一句话说明这张图画的是什么(30字内)",\n'
                 ' "walkthrough": ["讲解要点1", "要点2", "要点3"]}\n'
                 "is_figure：它是不是【正文数据插图】（有坐标轴的曲线图、柱状图、\n"
                 "示意图、脑图、实验流程图）。如果只是论文标题横幅、期刊刊头、\n"
                 "作者信息、页眉页脚、参考文献块、纯文字段落，给 false。\n"
                 "walkthrough 是给科普口播写手的讲图素材（3~5条，大白话）：\n"
                 "- 每个 panel/子图各画什么、坐标轴是什么\n"
                 "- 观众应该看哪个曲线/颜色/对比，看到什么趋势\n"
                 "- 这张图最想证明的结论是什么"},
                {"type": "image_url",
                 "image_url": {"url": f"data:image/png;base64,{b64}"}},
            ]}], temperature=0.2)
            fig["caption"] = ans.get("caption", "").strip()
            fig["walkthrough"] = ans.get("walkthrough", [])
            fig["is_figure"] = bool(ans.get("is_figure", True))
        except Exception as e:  # noqa: BLE001
            log(f"  图注生成失败 {fig['file']}: {e}")
            fig["caption"] = f"论文第{fig['page']}页主图"
            fig["walkthrough"] = []
            fig["is_figure"] = True        # 判不出来时保留，不误杀
    # 检测器会把期刊刊头、标题横幅当成主图抠出来（它们确实"像一张图"）。
    # 视觉模型已经能认出来，这里据此剔除，否则讲图段会对着一张标题横幅讲。
    kept = [f for f in figs if f.get("is_figure", True)]
    if len(kept) < len(figs):
        drop = [f["file"] for f in figs if not f.get("is_figure", True)]
        log(f"  剔除非插图（标题横幅/页眉等）：{', '.join(drop)}")
    return kept


def map_sentences_to_regions(fig_path: Path, sentences: list[str],
                             log=print) -> list[list[float] | None]:
    """把逐句口播映射到图中被讲到的区域 bbox（说哪块指哪块）；讲不到具体区域给 null。"""
    try:
        b64 = base64.b64encode(
            _png_bytes(Image.open(fig_path), 1400)).decode()
        numbered = "\n".join(f"{i + 1}. {s}" for i, s in enumerate(sentences))
        ans = llm.chat_json([{"role": "user", "content": [
            {"type": "text", "text":
             "这是论文插图。下面是讲解这张图的口播，一行一句。"
             "为每句话给出它正在讲的图中区域 bbox（0~1 归一化 [x,y,w,h]，x/y 左上角）；"
             "该句没讲到具体区域就给 null。\n"
             f'只输出 JSON：{{"regions": [bbox或null, ...]}}，长度必须等于 {len(sentences)}。\n\n'
             + numbered},
            {"type": "image_url",
             "image_url": {"url": f"data:image/png;base64,{b64}"}},
        ]}], temperature=0.1)
        regions = ans.get("regions", [])
        out = []
        for r in (regions + [None] * len(sentences))[:len(sentences)]:
            try:
                x, y, w, h = (float(v) for v in r)
                ok = 0 <= x < 1 and 0 <= y < 1 and 0.03 < w <= 1 and 0.03 < h <= 1
                out.append([x, y, min(w, 1 - x), min(h, 1 - y)] if ok else None)
            except Exception:  # noqa: BLE001
                out.append(None)
        return out
    except Exception as e:  # noqa: BLE001
        log(f"  逐句区域映射失败: {e}")
        return [None] * len(sentences)
