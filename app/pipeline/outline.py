"""The paper's own table of contents, so a long paper can be explained in parts.

A 150-page roadmap and a 12-page report are not the same job. Without this the
whole PDF goes to the writer, gets truncated at an arbitrary character count, and
whatever survived decides what the explainer is about.

The entries come from the PDF's own bookmarks -- nothing here is a heading the
model guessed. Each one carries the page range it covers, and that range is what
makes a selection enforceable: the writer is handed only those pages, and a
chapter citing a page outside them is rejected rather than talked out of.
"""
import re

import pypdfium2 as pdfium

# Fewer than three top-level entries is a cover page and an appendix marker, not
# a table of contents worth choosing from.
MIN_SECTIONS = 3
MAX_ENTRIES = 160
MAX_DEPTH = 3
MAX_TITLE = 90


def _clean(title: str) -> str:
    return re.sub(r'\s+', ' ', str(title or '')).strip()[:MAX_TITLE]


def extract(pdf_path) -> list[dict]:
    """Outline entries, each with the page span it covers.

    Returns [] for a paper with no bookmarks, which is most journal PDFs; the
    caller then explains the whole thing as before."""
    try:
        pdf = pdfium.PdfDocument(pdf_path)
    except Exception:
        return []
    pages = len(pdf)
    raw = []
    for bookmark in pdf.get_toc(max_depth=MAX_DEPTH):
        level = getattr(bookmark, 'level', 0)
        title = _clean(bookmark.get_title())
        dest = bookmark.get_dest()
        index = dest.get_index() if dest else None
        if not title or index is None or not 0 <= index < pages:
            continue
        raw.append({'level': int(level), 'title': title, 'page': index + 1})
        if len(raw) >= MAX_ENTRIES:
            break
    if sum(1 for item in raw if item['level'] == 0) < MIN_SECTIONS:
        return []
    # A section runs until the next entry at the same or a shallower level. Its
    # own subsections sit inside that span, so picking a parent picks its children.
    for position, item in enumerate(raw):
        end = pages
        for later in raw[position + 1:]:
            if later['level'] <= item['level']:
                end = max(item['page'], later['page'] - 1)
                break
        item['end_page'] = end
        item['id'] = f's{position + 1}'
    return raw


def pages_for(entries: list[dict], ids) -> set[int]:
    """Every page the chosen sections cover."""
    wanted = {str(i) for i in (ids or [])}
    out = set()
    for item in entries:
        if item['id'] in wanted:
            out.update(range(item['page'], item['end_page'] + 1))
    return out


def chosen(entries: list[dict], ids) -> list[dict]:
    wanted = {str(i) for i in (ids or [])}
    return [item for item in entries if item['id'] in wanted]


def describe(entries: list[dict]) -> str:
    """The selection as the writer sees it: titles and the pages they live on."""
    return '\n'.join(
        f"{'  ' * item['level']}· {item['title']}（PDF 第{item['page']}"
        + (f"–{item['end_page']}页）" if item['end_page'] > item['page'] else '页）')
        for item in entries)
