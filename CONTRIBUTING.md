# Contributing to aha-paper

Thanks for looking. This file is short on purpose: it covers the few rules that
are load-bearing in this codebase and would be expensive to rediscover.

感谢参与。这份文件只写真正要紧的几条约束——其余的照着周围代码写就行。

## Getting set up

```sh
python -m venv .venv
.venv/bin/pip install -r requirements.txt
npm ci --ignore-scripts
cp .env.example .env          # add OPENROUTER_API_KEY
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8321
```

```sh
.venv/bin/python -m unittest discover -s tests -q
```

The suite is stdlib `unittest` — there is no pytest, and adding one would mean
pinning a test runner the project does not otherwise need. Nothing in it reaches
a model provider, so it runs offline and on a fork without a credential.

```sh
python3 scripts/check_translations.py
```

Both commands run in CI on every pull request.

## The three rules that matter

### 1. Nothing on screen may be invented

Every frame is either a figure from the paper or a page of the paper. The model
answers one question — *which sentence of the source is this narration
explaining?* — and every coordinate is derived from the PDF's own text layer.

That split is the product. A wrong answer highlights a different real sentence;
it cannot invent a position, and a fabricated quotation simply fails to resolve,
so nothing is drawn. A change that lets the model supply a coordinate, a page
number or a figure directly removes the only guarantee this app makes. If you
need one, derive it.

### 2. A cut of the narration must be lossless

`''.join(split(text)) == text`, for every splitter in `app/lang.py`.

The narration is sent to the synthesiser as one joined string, and the word
timestamps that come back are what the cursor is driven from. A split that
swallows the space between two sentences feeds the synthesiser text the writer
never wrote, and every timestamp after it moves. The audio still plays and still
sounds correct; only the cursor is wrong. You cannot catch this by listening to
it, which is why it is pinned by assertion in `tests/test_narration_lang.py`.

### 3. The interface is bilingual by contract

A user-facing string exists in Chinese and English or it does not ship.

- **Interface text** is translated by `web/i18n.js`, which looks up the Chinese
  source — there are no keys. Add the English to `DICT` for an exact string, or
  to `RULES` as a `{}`-templated pair when a value is interpolated.
- **Content that travels as a value** — the focus presets, for one — cannot be
  translated that way, because the translator deliberately never rewrites a
  value or a user-authored attribute. That content is served already in the
  right language from the backend, and its container carries `data-no-i18n` to
  say who owns it. One owner per string.
- **Narration** is not interface. It is the product, and everything that changes
  with its language lives in `app/lang.py`: the writer's persona, the characters
  per minute, the voice, the sentence boundaries, the cursor boundaries and the
  wording of a quantity. Adding a third language should mean adding a profile
  and touching nothing else. If it doesn't, that's the bug.

`scripts/check_translations.py` enforces the first point for raised errors. The
other two are on you and on review.

## Style

Match the file you are in. The Python is deliberately dense in the pipeline and
spacious in `app/jobs.py`; neither is an accident, and a reformatting pass that
touches lines unrelated to your change makes the diff unreviewable.

Comments explain *why*, especially where the obvious implementation is wrong —
those comments are usually a bug someone already paid for. Please don't delete
one without understanding what it is protecting.

## Pull requests

- One concern per PR.
- Say what you verified, and how. "Tests pass" is weaker than "added a case that
  fails without the fix".
- If you changed something user-facing, say what it looks like in both
  languages.
- New dependencies need a reason in the PR description. This app bundles its own
  Python and ffmpeg for the desktop build, so every addition has a size cost.

## Licence

By contributing you agree that your contribution is licensed under the Apache
License 2.0, the same as the project. If you add third-party material, add its
attribution to `NOTICE` in the same PR.
