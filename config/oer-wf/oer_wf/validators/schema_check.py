"""Check expected files exist and CSV has a header."""

from __future__ import annotations

from pathlib import Path

from oer_wf.models import CheckResult


def run(archive_dir: Path, expected_files: list[str]) -> list[CheckResult]:
    checks: list[CheckResult] = []
    for name in expected_files:
        p = archive_dir / name
        if p.is_file():
            checks.append(CheckResult(name=f"file:{name}", passed=True, detail="present"))
        else:
            checks.append(CheckResult(name=f"file:{name}", passed=False, detail="missing"))

    for name in expected_files:
        if name.endswith(".csv"):
            p = archive_dir / name
            if p.is_file():
                try:
                    header = p.read_text(encoding="utf-8", errors="replace").splitlines()[0]
                    checks.append(
                        CheckResult(name=f"csv_header:{name}", passed=bool(header.strip()), detail=header[:80])
                    )
                except Exception as e:
                    checks.append(CheckResult(name=f"csv_header:{name}", passed=False, detail=str(e)))
    return checks
