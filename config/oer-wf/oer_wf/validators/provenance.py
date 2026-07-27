"""Check STATUS.json / manifest provenance fields."""

from __future__ import annotations

import json
from pathlib import Path

from oer_wf.models import CheckResult


def run(archive_dir: Path, expected_files: list[str] | None = None) -> list[CheckResult]:
    checks: list[CheckResult] = []
    status_path = archive_dir / "STATUS.json"
    if not status_path.is_file():
        checks.append(CheckResult(name="provenance:STATUS", passed=False, detail="STATUS.json missing"))
        return checks

    try:
        data = json.loads(status_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        checks.append(CheckResult(name="provenance:STATUS", passed=False, detail=f"corrupt: {e}"))
        return checks

    required = ["status", "commit", "task_id", "started_at"]
    missing = [k for k in required if not data.get(k)]
    if missing:
        checks.append(
            CheckResult(name="provenance:STATUS", passed=False, detail=f"missing fields: {missing}")
        )
    else:
        checks.append(
            CheckResult(
                name="provenance:STATUS",
                passed=True,
                detail=f"status={data.get('status')} commit={data.get('commit')}",
            )
        )

    manifest = archive_dir / "manifest.json"
    if manifest.is_file():
        try:
            m = json.loads(manifest.read_text(encoding="utf-8"))
            has_commit = bool(m.get("commit") or m.get("git_commit") or m.get("sha"))
            checks.append(
                CheckResult(
                    name="provenance:manifest",
                    passed=has_commit,
                    detail="commit present" if has_commit else "no commit field",
                )
            )
        except json.JSONDecodeError as e:
            checks.append(CheckResult(name="provenance:manifest", passed=False, detail=f"corrupt: {e}"))

    return checks
