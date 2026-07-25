#!/usr/bin/env python3
"""Run pytest with the repository virtual environment when available."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Sequence


ROOT = Path(__file__).resolve().parents[1]


def project_python(root: Path, fallback: str = sys.executable) -> str:
    """Return the repository virtualenv interpreter when it exists."""
    candidate = root / ".venv" / "bin" / "python"
    return str(candidate) if candidate.is_file() else fallback


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
