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
  message ships without its English twin.

### Fixed
- **The cursor stood still during an English chapter.** `cue_alignment.units()`
  split on Chinese sentence punctuation only, so an English chapter came back as
  a single cursor target. It is now the narration profile's rule.
- **A Chinese preset appeared in the English interface.** The presets were
  hard-coded as `data-prompt` attributes, and the DOM translator deliberately
  never rewrites a user-authored attribute. They are served as data now.
- Every Chinese error raised in `app/` has an English twin, enforced in CI.
- A voice configured for one language is no longer used to narrate another.
