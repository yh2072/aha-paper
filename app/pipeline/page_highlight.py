"""Reading the paper itself: each narration clause highlights the sentence in the
PDF that it is explaining.

This replaces the authored Canvas animation for chapters the storyboard could not
attach a figure to. Those animations scored 4.9/10, and the three items that sank
them -- opening, composition, phone legibility -- were all picture design, while
fidelity to the source scored 7. The model could say the right thing and not draw
it. So the drawing stops being its job: the page, the camera and the type are ours.

The model never reports a position. It is shown the paper's own sentences, already
split and already located by the PDF text layer, and it only picks an id. Geometry
comes from pypdfium2. An id that is not on the list is dropped, so a clause can end
up with no highlight but can never get a confident highlight in the wrong place.
"""
import hashlib
import json
import re

import pypdfium2 as pdfium

from .. import config, llm

VERSION = 'page-highlight-v4'
RENDER_SCALE = 2.2         # matches figures.py, ~1300px wide for an A4 page
MIN_CHARS = 40             # shorter runs are headings, axis labels, caption scraps
MAX_SENTENCES = 90         # per page
MAX_PAGES = 6              # a chapter cites up to six; cutting at four lost the
MAX_CATALOGUE = 220        # Methods page that held the sample-size sentence
# A running header carries no full stop, so the sentence split glues it to the body
# text that follows and the result spans the page. Height is what catches that, and
# it is the only geometry that means the same thing in every layout.
#
# What it replaced: a cap on the number of rects, read as "a real sentence is a few
# lines". pdfium returns one rect per text run, not per wrapped line. On a wide
# single-column arXiv paper the two coincide; in a narrow two-column journal a
# perfectly ordinary sentence comes back as 20-plus runs barely 4% of the page tall,
# and the cap threw away 90% of the paper -- every chapter then fell through to a
# schematic. MAX_RECTS now only bounds drawing cost.
MAX_RECTS = 60
MAX_HEIGHT = 0.22
# Key terms inside the chosen sentence. Three is the ceiling: past that the whole
# sentence is emphasised, which is the same as emphasising nothing.
MAX_KEYS = 3
# Ask for more than we keep. Every gate below drops something, and a clause that
# ends with no emphasis at all is a worse outcome than one of its candidates
# being thrown away -- measured on two papers, the gates reject about one key in
# seven, so three candidates would regularly leave fewer than three.
KEY_CANDIDATES = 5
MIN_KEY_CHARS = 3
MAX_KEY_CHARS = 60
# A key term is a term. Measured over 184 keys on two papers, 86% were three
# words or fewer and covered under a fifth of their sentence; the tail was not
# longer terms but *clauses* -- 'To disentangle core and readout scaling' is six
# words and 61% of the sentence it sits in. Marking that much of a sentence a
# second time is the same as marking none of it, which is what "the keywords
# aren't accurate" looks like from the outside.
MAX_KEY_WORDS = 5
MAX_KEY_SHARE = 0.34
MAX_KEY_LINES = 3

# A bracketed citation inside a key means the key spans one -- that is a clause
# being quoted, not a term.
_CITATION = re.compile(r'\[\s*\d+[\d,;\s\u2013-]*\]')
# A term does not begin with a subordinator or a pronoun. These are what the
# model reaches for when it hands back half a sentence instead of a term.
_CLAUSE_OPENERS = frozenset('''
 to why how when where which what that who whose whom if because although though
 unless while whereas since and or but so except we i they it its this these
 those there here is are was were be been being only just
'''.split())
# The real difference between a term and a clause is a finite verb, not a word
# count: 'responses of neurons to arbitrary stimuli' is six words and a perfectly
# good term, while 'a is estimated to be 1.13' is six words and a sentence. The
# word cap alone threw away the first kind along with the second.
_FINITE_VERBS = frozenset('''
 is are was were be been being am has have had do does did
 will would shall should can could may might must
'''.split())


def _norm(rect, width, height):
    """pypdfium2 gives (left, bottom, right, top) in points from the bottom-left;
    the player wants [x, y, w, h] fractions from the top-left."""
    left, bottom, right, top = rect
    return [round(left / width, 4), round(1 - top / height, 4),
            round((right - left) / width, 4), round((top - bottom) / height, 4)]


def _span(textpage, text, start=0, limit=None):
    """The character range a run of text occupies on the page, or None.

    Long queries can miss on ligatures or a column break, so fall back to shorter
    prefixes rather than losing the sentence entirely. `start` and `limit` confine
    the search to one sentence, which is what keeps a key term from being found in
    some other paragraph that happens to use the same word."""
    for length in (len(text), 160, 90, 50):
        if not min(MIN_KEY_CHARS, len(text)) <= length <= len(text):
            continue
        hit = textpage.search(text[:length], index=start,
                              match_case=False, match_whole_word=False).get_next()
        if not hit:
            continue
        index, count = hit
        if limit is not None and index + count > limit:
            continue
        return index, count
    return None


# How far apart two runs may sit and still be one stroke of the marker. A word
# space is a fraction of this; a two-column gutter is several times it, so a band
# never leaps the gutter and highlights half of the facing column.
MERGE_GAP = 0.012


def _merge(rects):
    """One continuous band per line, instead of one box per text run.

    pdfium reports a rect per run, and a line of body text is many runs — a bold
    lead-in, a code span, each stretch between them. Drawing them as they arrive
    gives a row of little blocks with gaps punched between the words, which is
    not what a marker pen does. Runs are joined while they stay on the same line
    and stay close."""
    out = []
    for x, y, w, h in rects:
        if out:
            px, py, pw, ph = out[-1]
            overlap = min(y + h, py + ph) - max(y, py)
            if overlap > min(h, ph) * .5 and -MERGE_GAP <= x - (px + pw) <= MERGE_GAP:
                top, bottom = min(y, py), max(y + h, py + ph)
                out[-1] = [min(px, x), top, max(px + pw, x + w) - min(px, x), bottom - top]
                continue
        out.append([x, y, w, h])
    return [[round(v, 4) for v in box] for box in out]


def _rects(textpage, span, width, height):
    """Boxes for a located run: one band per wrapped line, the way a marker pen
    would leave them."""
    index, count = span
    rects = [_norm(textpage.get_rect(k), width, height)
             for k in range(textpage.count_rects(index, count))]
    return _merge([r for r in rects if r[2] > 0 and r[3] > 0])


def _locate(textpage, text, width, height):
    span = _span(textpage, text)
    return _rects(textpage, span, width, height) if span else []


def sentences_on(pdf, page_no: int) -> list[dict]:
    """The paper's own sentences on one page, numbered and located."""
    page = pdf[page_no - 1]
    textpage = page.get_textpage()
    width, height = page.get_width(), page.get_height()
    flat = re.sub(r'\s+', ' ', textpage.get_text_bounded())
    out = []
    for piece in re.split(r'(?<=[.!?])\s+', flat):
        piece = piece.strip()
        if len(piece) < MIN_CHARS or not re.search(r'[a-zA-Z]{3}', piece):
            continue
        span = _span(textpage, piece)
        rects = _rects(textpage, span, width, height) if span else []
        box = bounds(rects)
        if not rects or len(rects) > MAX_RECTS or box[3] > MAX_HEIGHT:
            continue
        out.append({'id': f'p{page_no}s{len(out) + 1}', 'page': page_no,
                    'text': piece, 'rects': rects, 'span': list(span)})
        if len(out) >= MAX_SENTENCES:
            break
    return out


def bounds(rects: list[list[float]]) -> list[float] | None:
    """One box around every line of a highlight, for the camera to frame."""
    if not rects:
        return None
    x0 = min(r[0] for r in rects)
    y0 = min(r[1] for r in rects)
    x1 = max(r[0] + r[2] for r in rects)
    y1 = max(r[1] + r[3] for r in rects)
    return [round(x0, 4), round(y0, 4), round(x1 - x0, 4), round(y1 - y0, 4)]


def render_pages(pdf_path, pages, out_dir) -> dict:
    """Page images, rendered once and reused."""
    out_dir.mkdir(parents=True, exist_ok=True)
    pdf = pdfium.PdfDocument(pdf_path)
    made = {}
    for n in sorted(set(pages)):
        if not 1 <= n <= len(pdf):
            continue
        path = out_dir / f'page_{n:02d}.png'
        if not path.exists():
            pdf[n - 1].render(scale=RENDER_SCALE).to_pil().convert('RGB').save(path, optimize=True)
        made[n] = path.name
    return made


def _strip_edges(key: str) -> str:
    """Trim punctuation from the ends without unbalancing a bracket.

    A plain .strip('()[]') turns 'explained (FEVE)' into 'explained (FEVE' --
    which still locates in the text layer, and then underlines a fragment. The
    greedy strip was the bug, not the bracket: a closing bracket that has an
    opener inside the key is part of the term and stays."""
    pairs = {'(': ')', '[': ']'}
    closers = {close: open_ for open_, close in pairs.items()}
    key = key.strip(' .,;:"\'\u2019')
    while key and key[0] in pairs and key.count(key[0]) > key.count(pairs[key[0]]):
        key = key[1:].lstrip()
    while key and key[-1] in closers and key.count(key[-1]) > key.count(closers[key[-1]]):
        key = key[:-1].rstrip()
    return key.strip(' .,;:"\'\u2019')


def _whole_words(key: str, sentence: str) -> str:
    """The key as it appears in the sentence, cut back to whole words.

    The catalogue shows each sentence truncated, so a model copying from the end
    of a long line can hand back a fragment like 'up to 13% absolute accu'. It is
    verbatim and it locates, so both gates pass -- and the marker then underlines
    half of a word. Trimming to word boundaries is what the reader expects; a key
    with no whole word left is dropped."""
    lowered, folded = sentence.lower(), key.lower()
    at = lowered.find(folded)
    if at < 0:
        return ''
    start, end = at, at + len(folded)
    while start < end and start > 0 and sentence[start - 1].isalnum() and sentence[start].isalnum():
        start += 1
    while end > start and end < len(sentence) and sentence[end].isalnum() and sentence[end - 1].isalnum():
        end -= 1
    return _strip_edges(sentence[start:end])


def _term(key: str, sentence: str) -> str:
    """The candidate reduced to a term, or '' if it is not one.

    Runs after _whole_words, so `key` is already the paper's own characters. What
    is left to decide is whether those characters are a *term* or a piece of
    sentence, and the three tests are all mechanical for the same reason the
    gates above are: a rule the model is asked to follow politely is a rule that
    holds most of the time, and "most of the time" is what the reader notices."""
    # A citation hanging off either end is noise and comes off. One left in the
    # middle means the key spans a citation, and only a clause does that.
    # Substituting it out instead would make the key stop matching the page.
    key = re.sub(rf'^(?:{_CITATION.pattern})\s*', '', key)
    key = re.sub(rf'\s*(?:{_CITATION.pattern})$', '', key)
    key = _strip_edges(key)
    if _CITATION.search(key):
        return ''
    words = key.split()
    if not words or len(words) > MAX_KEY_WORDS:
        return ''
    plain = [w.lower().strip('.,;:()[]"\'') for w in words]
    if plain[0] in _CLAUSE_OPENERS:
        return ''
    if any(w in _FINITE_VERBS for w in plain):
        return ''                                  # a verb makes it a clause
    if len(key) > MAX_KEY_SHARE * max(1, len(sentence)):
        return ''                                  # most of a short sentence
    # The punctuation strip above can open a bracket it does not close:
    # '...explained (FEVE)' loses its ')' and becomes '...(FEVE', which locates
    # happily and then underlines a fragment. Same family as a key cut
    # mid-word, and the same answer -- if it does not balance, it is not a term.
    for opener, closer in ('()', '[]'):
        if key.count(opener) != key.count(closer):
            return ''
    return key


def locate_keys(pdf, sentence: dict, keys) -> list[dict]:
    """Boxes for the key terms inside one chosen sentence.

    Two gates, both mechanical. A key must be the paper's own words -- a
    case-insensitive substring of the sentence we are highlighting -- and it must
    then be found by the text layer *within that sentence's character range*. The
    range is what matters: 'reasoning' occurs a dozen times on a page, and without
    the bound the marker would land on whichever one pdfium saw first. A key that
    fails either gate is dropped, so the worst a wrong guess costs is a missing
    emphasis, never a misplaced one."""
    span = sentence.get('span')
    if not span or not isinstance(keys, list):
        return []
    page = pdf[sentence['page'] - 1]
    textpage = page.get_textpage()
    width, height = page.get_width(), page.get_height()
    start, count = span
    limit = start + count
    out, seen, taken = [], set(), []
    for key in keys:
        if not isinstance(key, str):
            continue
        key = _strip_edges(re.sub(r'\s+', ' ', key))
        if len(key) > MAX_KEY_CHARS:
            continue
        # Not in the sentence means the model wrote it rather than read it; a
        # fragment of one is trimmed back to the words it does cover.
        key = _whole_words(key, sentence['text'])
        key = _term(key, sentence['text'])
        folded = key.lower()
        if not MIN_KEY_CHARS <= len(key) or folded in seen:
            continue
        # Two keys covering the same words stack two marks on one phrase, which
        # on the page looks like a rendering fault rather than emphasis.
        at = sentence['text'].lower().find(folded)
        if any(at < b and a < at + len(folded) for a, b in taken):
            continue
        found = _span(textpage, key, start=start, limit=limit)
        if not found:
            continue
        rects = _rects(textpage, found, width, height)
        if not rects or len(rects) > MAX_KEY_LINES:
            continue
        seen.add(folded)
        taken.append((at, at + len(folded)))
        out.append({'text': key, 'rects': rects})
        if len(out) >= MAX_KEYS:
            break
    return out


PROMPT = """下面是一篇论文某几页上的句子，每句都已经由 PDF 文字层定位好，带一个编号。
再下面是这一章旁白的逐句切分。

对每一条旁白，指出它正在解释论文里的哪一句，只回那句的编号。
规则：
- 只能用下面列出的编号，不要自己造编号，不要改写句子。
- 旁白是在用中文转述论文；找语义上对应的那一句，不是字面相同的那一句。
- 过渡句、总结句、提问句如果没有对应的原文，就回 null。宁可 null，也不要硬配。
- 连续几条旁白在讲同一句原文时，可以重复给同一个编号。
- 给出编号的同时，再从那句原文里挑 1-5 个最关键的词或短语放进 keys：
  必须一字不差地照抄原文（英文就保持英文），不要翻译、不要改写、不要自己造词；
  挑术语、专有名词、数字和限定语，不要挑 the / of / and 这类词；
  **每个 key 最多 4 个英文单词，而且必须是一个"词组"，不是半句话。**
  反例（都不要）："To disentangle core and readout scaling"、
  "Why does training on clean examples improve"、"do what we mean, not what we say"
  ——这些是从句，整句已经被马克笔标出来了，再标一遍等于没标。
  正例："dissociable"、"readout scaling"、"13% absolute"、"natural movies"。
  这一条旁白在强调原句的哪一部分，就挑哪一部分，同一句不同旁白可以挑不同的词。

论文句子：
{sentences}

旁白逐句：
{clauses}

只输出 JSON：{{"picks":[{{"cue":0,"id":"p6s12","keys":["dissociable","neural signals"]}},{{"cue":1,"id":null,"keys":[]}}]}}"""


def plan(clauses: list[str], pdf_path, pages, log=print) -> list[dict | None]:
    """For each clause, the sentence of the paper it explains, or None.

    Returns one entry per clause: {'page', 'rects', 'quote'} or None."""
    pdf = pdfium.PdfDocument(pdf_path)
    catalogue = []
    for n in sorted(set(pages))[:MAX_PAGES]:
        if 1 <= n <= len(pdf):
            catalogue.extend(sentences_on(pdf, n))
    del catalogue[MAX_CATALOGUE:]
    if not catalogue:
        log('    这几页没有可用的文字层，跳过原文高亮')
        return [None] * len(clauses)
    by_id = {s['id']: s for s in catalogue}
    listing = '\n'.join(f"{s['id']}: {s['text'][:240]}" + ('…（此句被截断）' if len(s['text']) > 240 else '')
                        for s in catalogue)
    numbered = '\n'.join(f'{i}: {c}' for i, c in enumerate(clauses))
    data = llm.chat_json([{'role': 'user', 'content': PROMPT.format(
        sentences=listing, clauses=numbered)}], temperature=0.2)
    picks = data.get('picks') if isinstance(data, dict) else data
    chosen = {}
    for pick in picks or []:
        if not isinstance(pick, dict):
            continue
        index, ident = pick.get('cue'), pick.get('id')
        # An id the catalogue does not hold is a fabrication; drop it rather than
        # guessing which sentence was meant.
        if isinstance(index, int) and 0 <= index < len(clauses) and ident in by_id:
            chosen[index] = (by_id[ident], pick.get('keys'))
    hits = sum(1 for i in range(len(clauses)) if i in chosen)
    out = []
    for i in range(len(clauses)):
        if i not in chosen:
            out.append(None)
            continue
        sentence, keys = chosen[i]
        out.append({'page': sentence['page'], 'rects': sentence['rects'],
                    'quote': sentence['text'][:300],
                    'keys': locate_keys(pdf, sentence, keys)})
    marked = sum(len(h['keys']) for h in out if h)
    log(f'    原文高亮 {hits}/{len(clauses)} 句，关键词 {marked} 处（共 {len(catalogue)} 句可选）')
    return out


def identity() -> str:
    """What makes a *pick* stale: a different model, prompt, or sentence filter.

    The filter belongs here because it decides the catalogue the model chose
    from. When MAX_RECTS changed and this did not, every cached plan stayed
    valid-looking and empty, and the rebuild produced a paper with no highlights."""
    return json.dumps([VERSION, config.MODEL_TEXT,
                       MIN_CHARS, MAX_RECTS, MAX_HEIGHT, MAX_SENTENCES, MAX_PAGES],
                      ensure_ascii=False)


def geometry() -> str:
    """What makes the *boxes* stale, which is a different question.

    Which sentence a clause explains costs a request. Where that sentence sits on
    the page costs nothing. Keeping the two apart means changing how a highlight
    is drawn re-renders every project for free instead of re-billing it."""
    return json.dumps([MERGE_GAP, RENDER_SCALE, MAX_KEYS, MAX_KEY_LINES,
                       MAX_KEY_WORDS, MAX_KEY_SHARE])


def relocate(pdf_path, highlights):
    """Recompute the boxes for picks already made, without asking the model again."""
    pdf = pdfium.PdfDocument(pdf_path)
    pages, out = {}, []
    for spot in highlights:
        if not spot or not spot.get('quote'):
            out.append(None)
            continue
        number = spot['page']
        if number not in pages:
            page = pdf[number - 1]
            pages[number] = (page.get_textpage(), page.get_width(), page.get_height())
        textpage, width, height = pages[number]
        span = _span(textpage, spot['quote'])
        rects = _rects(textpage, span, width, height) if span else []
        if not rects:
            out.append(None)
            continue
        sentence = {'page': number, 'text': spot['quote'], 'span': list(span)}
        out.append({'page': number, 'rects': rects, 'quote': spot['quote'],
                    'keys': locate_keys(pdf, sentence,
                                        [k['text'] for k in (spot.get('keys') or [])])})
    return out


def prepare(scenes, project_dir, work_dir, log=print):
    """Plan the paper-reading view for every chapter that has no figure.

    Runs before narration timing because it only needs the clause split, and the
    result is cached so a re-run costs nothing."""
    from .cue_alignment import units
    pdf = project_dir / 'paper.pdf'
    if not pdf.exists():
        log('  没有 paper.pdf，跳过原文高亮')
        return
    work_dir.mkdir(parents=True, exist_ok=True)
    for index, scene in enumerate(scenes):
        if scene.get('figure_path'):
            continue
        pages = [n for n in (scene.get('source_pages') or []) if isinstance(n, int)]
        if not pages:
            continue
        clauses = units(scene['text'])
        path = work_dir / f'seg_{index:02d}.pages.json'
        key = hashlib.sha256(json.dumps([clauses, pages, identity()],
                                        ensure_ascii=False).encode()).hexdigest()
        if path.exists():
            stored = json.loads(path.read_text(encoding='utf-8'))
            if stored.get('key') == key:
                if stored.get('geom') != geometry():
                    stored = {'key': key, 'geom': geometry(), 'version': VERSION,
                              'highlights': relocate(pdf, stored.get('highlights') or [])}
                    path.write_text(json.dumps(stored, ensure_ascii=False, indent=1))
                    log(f'  章节{index + 1}：绘制参数变了，就地重算位置，没有再请求模型')
                scene['page_plan'] = str(path)
                continue
        log(f'  原文定位：章节{index + 1}，{len(clauses)}句，PDF 第{pages}页')
        try:
            highlights = plan(clauses, pdf, pages, log=log)
        except Exception as error:                       # a chapter may fall back
            log(f'    原文定位失败，改用示意图: {error}')
            continue
        # However few clauses matched, the chapter still reads the paper. There is
        # no second renderer to fall through to, and a page of the real paper with
        # one mark on it beats a picture nothing in the paper supports.
        path.write_text(json.dumps({'key': key, 'geom': geometry(), 'version': VERSION,
                                    'highlights': highlights}, ensure_ascii=False, indent=1))
        scene['page_plan'] = str(path)
