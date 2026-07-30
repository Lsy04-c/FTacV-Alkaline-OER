"""Verify Mac-archived results against their frozen task contract."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Optional

from oer_wf import config
from oer_wf import __version__
from oer_wf.models import CheckResult, FailType, WfResponse
from oer_wf.remote_dispatch import run_remote_validator
from oer_wf.response import fail, ok
from oer_wf.snapshot import SNAPSHOT_FILENAME, load_snapshot
from oer_wf.transport import Executor, RealExecutor
from oer_wf.validator_runner import run_validator
from oer_wf.verification_receipt import archive_tree_hash, write_receipt


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
    executor: Optional[Executor] = None,
) -> WfResponse:
    ex = executor or RealExecutor()
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
    try:
        archive_hash_before = archive_tree_hash(archive)
    except OSError as exc:
        return fail(
            FailType.TRANSPORT,
            f"cannot hash local archive before verification: {exc}",
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
    validator_execution: list[dict[str, Any]] = []
    for name in vnames:
        raw_config = validator_config.get(name) or {}
        execution = str(raw_config.get("execution", "local"))
        timeout_sec = int(raw_config.get("timeout_sec", 600))
        if execution == "remote_worktree":
            early, validator_checks, evidence = run_remote_validator(
                ex,
                task_name=task_name,
                commit_short=commit_short,
                archive=archive,
                snapshot=snapshot or {},
                validator=name,
                expected_files=expected,
                validator_config=raw_config,
                timeout_sec=timeout_sec,
            )
            if early is not None:
                return early
            checks.extend(validator_checks)
            validator_execution.append(evidence)
        else:
            _, _, validator_checks = run_validator(
                name,
                archive,
                expected,
                raw_config,
            )
            checks.extend(validator_checks)
            validator_execution.append(
                {"validator": name, "execution": "local"}
            )

    try:
        archive_hash_after = archive_tree_hash(archive)
    except OSError as exc:
        return fail(
            FailType.TRANSPORT,
            f"cannot hash local archive after verification: {exc}",
        )
    if archive_hash_after != archive_hash_before:
        checks.append(
            CheckResult(
                name="structure:archive_immutable",
                passed=False,
                detail="validator modified the synchronized calculation archive",
            )
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
        "validator_execution": validator_execution,
        "archive_tree_hash": archive_hash_before,
    }
    status_path = archive / "STATUS.json"
    try:
        data["status"] = json.loads(status_path.read_text()).get("status")
    except Exception:
        data["status"] = None

    if not failed:
        response = ok(
            message=f"verify passed: {archive.name}",
            next_action="wf git-check",
            data=data,
            checks=checks,
        )
    else:
        response = fail(
            _classify_fail(failed),
            "verify failed: " + ", ".join(c.name for c in failed),
            next_action="inspect archive; scientific or structure decision required",
            data=data,
            checks=checks,
        )
    try:
        snapshot_text = (archive / SNAPSHOT_FILENAME).read_bytes()
        env_bytes = json.dumps(
            (snapshot or {}).get("env", {}),
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        receipt = write_receipt(
            config.MAC_ARCHIVE_ROOT,
            task_id=task_id,
            result_timestamp=archive.name,
            payload={
                "oer_wf_version": __version__,
                "task_id": task_id,
                "commit": (snapshot or {}).get("commit"),
                "snapshot_sha256": hashlib.sha256(snapshot_text).hexdigest(),
                "archive": str(archive),
                "archive_tree_hash": archive_hash_before,
                "environment_sha256": hashlib.sha256(env_bytes).hexdigest(),
                "validator_execution": validator_execution,
                "response": response.model_dump(mode="json"),
            },
        )
    except (OSError, ValueError, TypeError) as exc:
        return fail(
            FailType.TRANSPORT,
            f"verification finished but receipt write failed: {exc}",
            data=data,
            checks=checks,
        )
    response.data["receipt"] = str(receipt)
    return response
