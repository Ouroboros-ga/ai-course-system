"""Resolve locally configured media executables without relying on PATH.

The desktop development host may sanitise a child process' ``PATH``.  Media
features therefore accept explicit absolute executable paths via
``FFMPEG_PATH`` and ``FFPROBE_PATH`` while retaining the usual command-name
fallback for normal deployments.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path


def resolve_media_tool(name: str) -> str:
    """Return an executable path for ``ffmpeg`` or ``ffprobe``.

    An invalid environment override is deliberately ignored so a production
    installation with the binary on ``PATH`` continues to work normally.
    """
    normalized = name.strip().lower().removesuffix(".exe")
    if normalized not in {"ffmpeg", "ffprobe"}:
        raise ValueError(f"Unsupported media tool: {name!r}")
    configured = os.environ.get(f"{normalized.upper()}_PATH", "").strip()
    if configured and Path(configured).is_file():
        return configured
    return shutil.which(normalized) or normalized


def ffmpeg_binary() -> str:
    return resolve_media_tool("ffmpeg")


def ffprobe_binary() -> str:
    return resolve_media_tool("ffprobe")


__all__ = ["ffmpeg_binary", "ffprobe_binary", "resolve_media_tool"]
