"""Check numeric CSV columns for NaN / Inf."""

from __future__ import annotations

import math
import re
from pathlib import Path

from oer_wf.models import CheckResult

_NON_FINITE = re.compile(r"\b(?:nan|inf|-inf)\b", re.IGNORECASE)


def run(archive_dir: Path, expected_files: list[str]) -> list[CheckResult]:
    checks: list[CheckResult] = []
    csvs = [n for n in expected_files if n.endswith(".csv")]
    if not csvs:
        csvs = [p.name for p in archive_dir.glob("*.csv")]

    for name in csvs:
        p = archive_dir / name
        if not p.is_file():
            continue
        text = p.read_text(encoding="utf-8", errors="replace")
        if _NON_FINITE.search(text):
            checks.append(
                CheckResult(name=f"finite:{name}", passed=False, detail="found NaN/Inf token")
            )
        else:
            # also scan float-able cells lightly
            bad = 0
            for i, line in enumerate(text.splitlines()[1:], start=2):
                for cell in line.split(","):
                    cell = cell.strip().strip('"')
                    if not cell:
                        continue
                    try:
                        v = float(cell)
                        if not math.isfinite(v):
                            bad += 1
                    except ValueError:
                        pass
                if bad > 0:
                    break
            if bad:
                checks.append(
                    CheckResult(name=f"finite:{name}", passed=False, detail=f"non-finite near line {i}")
                )
            else:
                checks.append(CheckResult(name=f"finite:{name}", passed=True, detail="ok"))
    return checks
