# Security Policy

## Reporting a vulnerability

Please report privately through GitHub's **Report a vulnerability** button under
this repository's *Security* tab, which opens a private advisory. Do not open a
public issue for a vulnerability.

Expect an acknowledgement within a week. If a fix lands, the advisory and the
release notes will credit you unless you prefer otherwise.

请通过本仓库 Security 标签页的 **Report a vulnerability** 私下报告，不要开公开 issue。

## What this app is

aha-paper runs locally and holds credentials for the model providers you
configure. Three things are worth knowing before you assess it.

**Credentials live in a local `.env`, mode 0600.** The settings API reports
*whether* a provider is configured and never returns the credential itself. A
report that the key is readable by a process already running as you is not a
finding; a report that it reaches the browser, a log, a crash report or an
outbound request is.

**A paper is untrusted input.** PDFs, the images extracted from them and user
drafts are reference data for the model, never instructions — every persona in
`app/lang.py` says so explicitly. If you find an input that makes the pipeline
execute, fetch or exfiltrate something on the strength of text inside a paper,
that is a finding and an important one.

**Serving it publicly is not a supported configuration.** `app/config.py`
requires `AHA_ACCESS_PASSWORD` before the app will accept non-local traffic,
because every button spends the operator's model quota. If you deploy it open to
the internet without one, the resulting bill is a configuration problem rather
than a vulnerability — but a way *around* that gate is a finding.

## Scope

In scope: credential disclosure, path traversal through a project id or an
uploaded filename, a bypass of the access gate, command injection into the
ffmpeg or Python invocations, and prompt injection that produces an action
rather than just bad narration.

Out of scope: denial of service through deliberately huge uploads on a local
instance, and anything that requires an attacker who already has your shell.

## Supported versions

The latest commit on `main`. This project does not yet maintain release
branches.
