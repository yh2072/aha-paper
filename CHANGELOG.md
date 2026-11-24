# Changelog

Notable changes. The format follows [Keep a Changelog](https://keepachangelog.com/),
and this project will use [Semantic Versioning](https://semver.org/) from its
first tagged release.

## [Unreleased]

### Added
- **Narration in English.** The language of the explainer is now a property of
  the project (`lang` in its metadata) rather than an assumption of the
  pipeline. Choosing English gives an English writing persona, an English voice,
  an English character budget and English sentence boundaries. The interface
  language sets it when a project is created.
- `app/lang.py`: one profile per narration language, holding everything that
  changes with it. Adding a third language means adding a profile.
- **Focus presets**, served from `/api/prompts` in the interface's language,
  with eight professional readings of a paper — study design, figures,
  statistics and effect sizes, reproducibility, contribution, a reviewer's read,
  and transfer to practice.
- **Custom focus presets.** Save what you wrote in the composer, in whatever
  language you wrote it, kept in `prompts.json` beside your other local state.
- `LICENSE` (Apache-2.0), `NOTICE`, `CONTRIBUTING.md`, `SECURITY.md`,
  `fonts/OFL.txt`, and a CI workflow running the suite on macOS and Linux.
- `scripts/check_translations.py`, which fails the build when a Chinese error
  message or log line ships without its English twin.
- **The run log follows the interface language**, and tails itself while a
  project is running: the current step, how long it has been going, a progress
  bar and a live indicator, with the scroll position kept if you have scrolled
  up to read something.

### Changed
- **A painterly skin** (`web/paint.css`), loaded after `refine.css`: warm paper
  ground, a violet-black ink, the sky/butter/pink/lavender/matcha/tangerine
  palette, one reused hand-cut border radius, and torn-paper edges from an SVG
  displacement filter. Headings are Fraunces with its SOFT and WONK axes; the
  wordmark is Pinyon Script; body text is Nunito. The structure underneath is
  untouched — same single-column library, same dense rows, same small card type
  — because the surface changed, not the job.
  - The three faces load from Google Fonts. The studio previously made no
    external request at all; it now makes one per page load, and falls back to
    the system serif and sans when offline.
  - The exported offline bundle strips those links and ships `paint.css`, so it
    still opens from disk with no network, as the README promises.
- **The narration's length ceiling is advisory.** Under the floor a summary is
  passing as a deep explainer, which is fatal. Over the ceiling the explainer
  merely runs longer than asked — a preference that was costing a full
  regeneration of the whole article, and sometimes failing outright. It is now
  accepted, flagged, and its real length reported; only a runaway draft (twice
  the target) is refused.
- **The independent accuracy check is off by default**, switchable under
  *Models & voice* or with `AHA_SCRIPT_AUDIT=1`. It rewrites the whole article
  to re-check numbers, figure labels and source pages, and was measured at 145s
  of a 285s script stage. With it off the script stage makes one model call
  instead of two.
- A structure repair no longer re-uploads the paper's figures. It is an
  arithmetic problem, and re-sending six base64 images to settle one paid the
  slowest part of the request twice.

### Fixed
- **The paper highlighted sentences the voice was not explaining.**
  `page_highlight.prepare` cut the narration with the Chinese rule whatever its
  language, producing 2–4 clauses for an English chapter the player drove from
  7–8 cues. Highlights are matched to cues by position, so every one of them
  landed on the wrong line — silently. A mismatched count is now refused rather
  than padded, and an AST test fails the build if any caller omits the language.
- **The English length instruction contradicted itself.** 4–6 chapters of
  "125–198 words" reaches 1188 words while the total ceiling said 937, so a
  writer honouring the per-chapter figure overshot the one actually checked —
  observed three times in a row. It is one derived number now.
- **The cursor stood still during an English chapter.** `cue_alignment.units()`
  split on Chinese sentence punctuation only, so an English chapter came back as
  a single cursor target. It is now the narration profile's rule.
- **A Chinese preset appeared in the English interface.** The presets were
  hard-coded as `data-prompt` attributes, and the DOM translator deliberately
  never rewrites a user-authored attribute. They are served as data now.
- Every Chinese error and log line in `app/` has an English twin, enforced in CI.
- A translated placeholder now fills recursively, so a log line carrying a
  validation error no longer comes back half English and half Chinese.
- A voice configured for one language is no longer used to narrate another.
