"""wf verify – run generic validators on Mac-archived results."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from oer_wf import config
from oer_wf.models import CheckResult, FailType, WfResponse
from oer_wf.response import fail, ok, warning
from oer_wf.validators import finite_check, manifest_hash, provenance, schema_check

_VALIDATOR_MAP = {
    "schema_check": schema_check.run,
    "finite_check": finite_check.run,
    "provenance": provenance.run,
    "manifest_hash": manifest_hash.run,
}

_DEFAULT_VALIDATORS = ["schema_check", "finite_check", "provenance", "manifest_hash"]
_DEFAULT_EXPECTED = ["summary.csv", "manifest.json", "STATUS.json"]


def _parse_task_id(task_id: str) -> tuple[str, str]:
    parts = task_id.split("/", 1)
    if len(parts) != 2:
        raise ValueError(f"invalid task_id: {task_id}")
    return parts[0], parts[1]


def _find_local_archive(
    commit_short: str,
    task_name: str,
    timestamp: Optional[str],
) -> Optional[Path]:
    base = config.MAC_ARCHIVE_ROOT / "results" / commit_short / task_name
    if not base.is_dir():
        return None
    if timestamp:
        p = base / timestamp
        return p if p.is_dir() else None
    # latest timestamp dir
    dirs = sorted([d for d in base.iterdir() if d.is_dir() and not d.name.startswith("_")])
    return dirs[-1] if dirs else None


def run_verify(
    task_id: str,
    *,
    timestamp: Optional[str] = None,
    expected_files: Optional[list[str]] = None,
    validators: Optional[list[str]] = None,
) -> WfResponse:
    """
    Verify locally archived results (no SSH required).

    Default: latest timestamp under
      <MAC_ARCHIVE_ROOT>/results/<commit_short>/<task_name>/
    """
    try:
        commit_short, task_name = _parse_task_id(task_id)
    except ValueError as e:
        return fail(FailType.STRUCTURE, str(e))

    archive = _find_local_archive(commit_short, task_name, timestamp)
    if archive is None:
        return fail(
            FailType.TRANSPORT,
            f"no local archive for {task_id}"
            + (f" timestamp={timestamp}" if timestamp else ""),
            next_action=f"wf sync {task_id}",
        )

    expected = expected_files or _DEFAULT_EXPECTED
    vnames = validators or _DEFAULT_VALIDATORS

    checks: list[CheckResult] = []
    for name in vnames:
        fn = _VALIDATOR_MAP.get(name)
        if fn is None:
            checks.append(CheckResult(name=name, passed=False, detail="unknown validator"))
            continue
        try:
            checks.extend(fn(archive, expected))
        except TypeError:
            # provenance/manifest_hash accept optional expected
            checks.extend(fn(archive))  # type: ignore[call-arg]
        except Exception as e:
            checks.append(CheckResult(name=name, passed=False, detail=f"validator error: {e}"))

    failed = [c for c in checks if not c.passed]
    # Soft warnings: optional hash skip messages counted as pass already

    data = {
        "task_id": task_id,
        "archive": str(archive),
        "timestamp": archive.name,
        "checks": [c.model_dump() for c in checks],
    }

    # STATUS-based fail_type
    status_val = None
    sp = archive / "STATUS.json"
    if sp.is_file():
        try:
            status_val = json.loads(sp.read_text()).get("status")
        except Exception:
            pass
    data["status"] = status_val

    if not failed:
        return ok(
            message=f"verify passed: {archive.name}",
            next_action="wf git-check",
            data=data,
            checks=checks,
        )

    # Classify
    if any(c.name.startswith("finite:") for c in failed):
        ft = FailType.NUMERICAL
    elif any(c.name.startswith("file:") for c in failed):
        ft = FailType.STRUCTURE
    elif any(c.name.startswith("hash:") for c in failed):
        ft = FailType.TRANSPORT
    else:
        ft = FailType.STRUCTURE

    return fail(
        ft,
        "verify failed: " + ", ".join(c.name for c in failed),
        next_action="inspect archive; scientific or structure decision required",
        data=data,
        checks=checks,
    )
