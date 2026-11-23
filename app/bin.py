"""Where the external programs are.

Three are shelled out to: ffmpeg and ffprobe do every cut, concat and
measurement, and node runs the provider CLI. Until now all 29 call sites wrote
the bare name and let PATH decide, which costs two things.

A packaged build cannot point at the copy it ships. An .app bundle carries its
own ffmpeg inside Resources precisely so the user does not have to install one,
and a bare "ffmpeg" in a list literal can never find it.

And a missing program surfaces as FileNotFoundError('ffmpeg'), raised from
whichever pipeline stage happened to run first, halfway through a run that has
already spent money on the model. Asking once, up front, is the difference
between "install ffmpeg" and a traceback out of tts.py.

Resolution order, per program:

1. an explicit override -- AHA_FFMPEG / AHA_FFPROBE / AHA_NODE
2. a bundled directory -- AHA_BIN_DIR, one variable covering all three, which is
   what a desktop build sets to its own Resources folder
3. PATH

Nothing is cached: the desktop shell sets these before starting the server, and
a cache would freeze whatever the environment looked like at import time.
"""
import os
import shutil
import sys
from pathlib import Path

#: name -> what it is for, used in the message when it cannot be found
PROGRAMS = {
    "ffmpeg": "剪辑与合成 · video assembly",
    "ffprobe": "读取时长与流信息 · media probing",
    "node": "模型供应商配置 · provider configuration",
}

_SUFFIX = ".exe" if sys.platform == "win32" else ""


def _find(name: str) -> str | None:
    override = os.getenv(f"AHA_{name.upper()}")
    if override:
        return override if Path(override).exists() else None
    bundled = os.getenv("AHA_BIN_DIR")
    if bundled:
        candidate = Path(bundled) / (name + _SUFFIX)
        if candidate.exists():
            return str(candidate)
    return shutil.which(name)


def path(name: str) -> str:
    """The program's path, or a message naming it and what it is for."""
    found = _find(name)
    if found:
        return found
    raise RuntimeError(f"找不到 {name}（{PROGRAMS.get(name, '')}）。"
                       f"请安装它，或把它放进 AHA_BIN_DIR 指向的目录。 · "
                       f"{name} not found; install it or point AHA_BIN_DIR at a copy.")


def ffmpeg() -> str:
    return path("ffmpeg")


def ffprobe() -> str:
    return path("ffprobe")


def node() -> str:
    return path("node")


def missing() -> list[str]:
    """Which programs are absent. For one check at startup, before any work."""
    return [name for name in PROGRAMS if _find(name) is None]
