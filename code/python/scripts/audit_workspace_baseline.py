#!/usr/bin/env python3
"""Record the repository state and baseline test results without changing it."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "results" / "architecture_validation" / "baseline_manifest.json"


def project_python(root: Path, fallback: str = sys.executable) -> str:
    """Return the repository virtualenv interpreter when it exists."""
    candidate = root / ".venv" / "bin" / "python"
    return str(candidate) if candidate.is_file() else fallback


def run_git(*args: str) -> str:
    """Run a read-only Git command and return stripped stdout."""
    return subprocess.run(
        ("git", *args),
        cwd=ROOT,
        check=True,
        text=True,
        capture_output=True,
    ).stdout.strip()


def run_test(command: list[str]) -> dict[str, object]:
    """Run one baseline test command and retain concise, reproducible evidence."""
    started = time.monotonic()
    completed = subprocess.run(
        command,
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    return {
        "command": command,
        "exit_code": completed.returncode,
        "duration_seconds": round(time.monotonic() - started, 3),
        "stdout_tail": completed.stdout.splitlines()[-30:],
        "stderr_tail": completed.stderr.splitlines()[-30:],
    }


def build_manifest(run_tests: bool) -> dict[str, object]:
    manifest: dict[str, object] = {
        "head": run_git("rev-parse", "HEAD"),
        "branch": run_git("branch", "--show-current"),
        "status": run_git("status", "--short").splitlines(),
        "tracked_diff": run_git("diff", "--name-status").splitlines(),
        "untracked": run_git(
            "ls-files", "--others", "--exclude-standard"
        ).splitlines(),
    }
    if run_tests:
        python = project_python(ROOT)
        manifest["test_runs"] = [
            run_test([python, "-m", "pytest", "code/python/tests", "-q"]),
            run_test(
                [
                    python,
                    "-m",
                    "pytest",
                    "code/web/backend/test_analyze_e2e.py",
                    "-q",
                ]
            ),
        ]
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--run-tests",
        action="store_true",
        help="Run and record the baseline Python and backend tests.",
    )
    args = parser.parse_args()

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        json.dumps(build_manifest(args.run_tests), indent=2, ensure_ascii=False)
        + "\n"
    )
    print(OUT)


if __name__ == "__main__":
    main()
