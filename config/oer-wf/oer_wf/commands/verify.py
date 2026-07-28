"""Verify Mac-archived results against their frozen task contract."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from oer_wf import config
from oer_wf.models import CheckResult, FailType, WfResponse
from oer_wf.response import fail, ok
from oer_wf.snapshot import SNAPSHOT_FILENAME, load_snapshot
from oer_wf.validators import (
    finite_check,
    manifest_hash,
    optimizer_benchmark_gate,
    provenance,
    recovery_gate,
    schema_check,
)

_VALIDATOR_MAP = {
    "schema_check": schema_check.run,
    "finite_check": finite_check.run,
    "provenance": provenance.run,
    "manifest_hash": manifest_hash.run,
    "optimizer_benchmark_gate": optimizer_benchmark_gate.run,
    "recovery_gate": recovery_gate.run,
}


def _parse_task_id(task_id: str) -> tuple[str, str]:
    parts = task_id.split("/", 1)
    if len(parts) != 2:
        raise ValueError(f"invalid task_id: {task_id}")
    return parts[0], parts[1]


def _find_local_archive(
    commit_short: str, task_name: str, timestamp: Optional[str]
) -> Optional[Path]:
    base = config.MAC_ARCHIVE_ROOT / "results" / commit_short / task_name
    if not base.is_dir():
        return None
    if timestamp:
        path = base / timestamp
        return path if path.is_dir() else None
    dirs = sorted(
        d for d in base.iterdir() if d.is_dir() and not d.name.startswith("_")
    )
    return dirs[-1] if dirs else None


def _classify_fail(failed: list[CheckResult]) -> FailType:
    if any(c.name.startswith(("scientific:", "recovery_gate")) for c in failed):
        return FailType.SCIENTIFIC
    if any(c.name.startswith(("finite:", "numerical:")) for c in failed):
        return FailType.NUMERICAL
    if any(c.name.startswith("hash:") for c in failed):
        return FailType.TRANSPORT
    return FailType.STRUCTURE


def _load_contract(
    archive: Path,
    commit_short: str,
    task_name: str,
    expected_override: Optional[list[str]],
    validators_override: Optional[list[str]],
) -> tuple[Optional[dict[str, Any]], list[str], list[str], dict[str, str], list[CheckResult]]:
    snapshot: Optional[dict[str, Any]] = None
    sources: dict[str, str] = {}
    snap_path = archive / SNAPSHOT_FILENAME
    if snap_path.is_file():
        try:
            snapshot = load_snapshot(snap_path.read_text(encoding="utf-8"))
        except Exception as exc:
            return None, [], [], sources, [
                CheckResult(
                    name="contract:snapshot",
                    passed=False,
                    detail=f"snapshot parse failed: {exc}",
                )
            ]
        if snapshot["task_name"] != task_name:
            return snapshot, [], [], sources, [
                CheckResult(
                    name="contract:task_name",
                    passed=False,
                    detail=f"{snapshot['task_name']!r} != {task_name!r}",
                )
            ]
        commit = str(snapshot["commit"])
        if commit != commit_short and commit[:7] != commit_short:
            return snapshot, [], [], sources, [
                CheckResult(
                    name="contract:commit",
                    passed=False,
                    detail=f"{commit!r} does not match {commit_short!r}",
                )
            ]

    expected = (
        list(expected_override)
        if expected_override is not None
        else list(snapshot["expected_files"]) if snapshot else []
    )
    validators = (
        list(validators_override)
        if validators_override is not None
        else list(snapshot["validators"]) if snapshot else []
    )
    if expected_override is not None:
        sources["expected_files"] = "explicit_override"
    elif snapshot:
        sources["expected_files"] = "snapshot"
    if validators_override is not None:
        sources["validators"] = "explicit_override"
    elif snapshot:
        sources["validators"] = "snapshot"

    if not expected or not validators:
        return snapshot, expected, validators, sources, [
            CheckResult(
                name="contract",
                passed=False,
                detail=(
                    "verification contract unavailable: provide both expected files "
                    "and validators, or use an archive containing task_spec.snapshot.yaml"
                ),
            )
        ]
    return snapshot, expected, validators, sources, []


def run_verify(
    task_id: str,
    *,
    timestamp: Optional[str] = None,
    expected_files: Optional[list[str]] = None,
    validators: Optional[list[str]] = None,
) -> WfResponse:
    try:
        commit_short, task_name = _parse_task_id(task_id)
    except ValueError as exc:
        return fail(FailType.STRUCTURE, str(exc))

    archive = _find_local_archive(commit_short, task_name, timestamp)
    if archive is None:
        return fail(
            FailType.TRANSPORT,
            f"no local archive for {task_id}"
            + (f" timestamp={timestamp}" if timestamp else ""),
            next_action=f"wf sync {task_id}",
        )

    snapshot, expected, vnames, sources, contract_checks = _load_contract(
        archive, commit_short, task_name, expected_files, validators
    )
    if contract_checks:
        return fail(
            FailType.STRUCTURE,
            "verify failed: " + ", ".join(c.name for c in contract_checks),
            next_action=(
                "provide --expected-file and --validator for a legacy archive, "
                "or re-run with snapshot-writing oer-wf"
            ),
            data={
                "task_id": task_id,
                "archive": str(archive),
                "timestamp": archive.name,
                "contract_sources": sources,
            },
            checks=contract_checks,
        )

    validator_config = (
        snapshot.get("validator_config") or {} if snapshot is not None else {}
    )
    checks: list[CheckResult] = []
    for name in vnames:
        fn = _VALIDATOR_MAP.get(name)
        if fn is None:
            checks.append(
                CheckResult(name=name, passed=False, detail="unknown validator")
            )
            continue
        try:
            if name in {"recovery_gate", "optimizer_benchmark_gate"}:
                checks.extend(
                    fn(
                        archive,
                        expected,
                        validator_config=validator_config.get(name) or {},
                    )
                )
            else:
                try:
                    checks.extend(fn(archive, expected))
                except TypeError:
                    checks.extend(fn(archive))  # type: ignore[call-arg]
        except Exception as exc:
            checks.append(
                CheckResult(name=name, passed=False, detail=f"validator error: {exc}")
            )

    failed = [check for check in checks if not check.passed]
    data: dict[str, Any] = {
        "task_id": task_id,
        "archive": str(archive),
        "timestamp": archive.name,
        "checks": [check.model_dump() for check in checks],
        "contract_sources": sources,
        "expected_files": expected,
        "validators": vnames,
    }
    status_path = archive / "STATUS.json"
    try:
        data["status"] = json.loads(status_path.read_text()).get("status")
    except Exception:
        data["status"] = None

    if not failed:
        return ok(
            message=f"verify passed: {archive.name}",
            next_action="wf git-check",
            data=data,
            checks=checks,
        )
    return fail(
        _classify_fail(failed),
        "verify failed: " + ", ".join(c.name for c in failed),
        next_action="inspect archive; scientific or structure decision required",
        data=data,
        checks=checks,
    )
