"""Extract usable text from an academic PDF."""
from pathlib import Path

from pypdf import PdfReader

MAX_CHARS = 60_000  # 论文正文足够了，防止超长 PDF 撑爆上下文


def extract_text(pdf_path: str | Path) -> str:
    reader = PdfReader(str(pdf_path))
    pages = []
    for page in reader.pages:
        try:
            pages.append(page.extract_text() or "")
        except Exception:  # noqa: BLE001 - 个别损坏页直接跳过
            continue
    text = "\n".join(pages).strip()
    if not text:
        raise RuntimeError("PDF 无法抽取文本（可能是纯扫描件，需要 OCR）")
    return text[:MAX_CHARS]
