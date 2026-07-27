"""Path resolution helpers (relative → absolute, platform suffixes)."""

from __future__ import annotations

import platform
import sys
from pathlib import Path


def platform_lib_suffix() -> str:
    """Return the shared-library suffix for the current platform."""
    system = platform.system().lower()
    if system == "linux":
        return ".so"
    if system == "darwin":
        return ".dylib"
    if system == "windows":
        return ".dll"
    # Fallback for WSL reported as Linux
    return ".so"


def resolve_artifact(basename: str) -> str:
    """Turn platform-agnostic basename into concrete filename."""
    if basename.endswith((".so", ".dylib", ".dll")):
        return basename
    return basename + platform_lib_suffix()


def timestamp_utc() -> str:
    """UTC timestamp string YYYYMMDD_HHMMSS."""
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def ensure_dir(p: Path) -> Path:
    p.mkdir(parents=True, exist_ok=True)
    return p
