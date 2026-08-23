#!/usr/bin/env python3
"""Run pytest with the repository virtual environment when available."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Sequence


ROOT = Path(__file__).resolve().parents[1]


def project_python(root: Path, fallback: str = sys.executable) -> str:
    """Return the repository virtualenv interpreter when it exists.

    向上逐级查找 `.venv/bin/python`：git worktree 里没有自己的 `.venv`，
    它在主检出中，可能高出好几级目录。只在仓库根查会静默退回系统解释器，
    从而用错依赖（本项目 worktree 下曾因此让 pre-commit 跑到没装 pytest
    的 miniconda 上）。同类问题见 docs/项目纠错.md §21。
    """
    for directory in [root, *root.parents]:
        candidate = directory / ".venv" / "bin" / "python"
        if candidate.is_file():
            return str(candidate)
    return fallback


def pytest_command(interpreter: str, args: Sequence[str]) -> list[str]:
    """Build a pytest module command for the selected interpreter."""
    return [interpreter, "-m", "pytest", *args]


def main() -> int:
    args = sys.argv[1:] or ["python/tests", "-q"]
    return subprocess.run(
        pytest_command(project_python(ROOT), args),
        cwd=ROOT,
        check=False,
    ).returncode


if __name__ == "__main__":
    raise SystemExit(main())
