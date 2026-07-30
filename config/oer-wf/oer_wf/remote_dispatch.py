"""Mac-side dispatch of one validator to the frozen Legion worktree."""

from __future__ import annotations

import base64
import json
from pathlib import Path
import shlex
from typing import Any, Optional

from oer_wf import config
from oer_wf.models import CheckResult, FailType, WfResponse
from oer_wf.response import fail
from oer_wf.transport import Executor


def run_remote_validator(
    ex: Executor,
    *,
    task_name: str,
    commit_short: str,
    archive: Path,
    snapshot: dict[str, Any],
    validator: str,
    expected_files: list[str],
    validator_config: dict[str, Any],
    timeout_sec: int,
) -> tuple[Optional[WfResponse], list[CheckResult], dict[str, Any]]:
    required = ("env", "python", "worktree_root")
    missing = [name for name in required if name not in snapshot]
    if missing:
        return (
            fail(
                FailType.ENVIRONMENT,
                "remote verification runtime missing from snapshot: "
                + ", ".join(missing),
                next_action="run a new task with oer-wf 0.7.0 snapshot",
            ),
            [],
            {},
        )
    try:
        status = json.loads((archive / "STATUS.json").read_text(encoding="utf-8"))
        remote_archive = str(status["output_dir"])
        env = snapshot["env"]
        python = snapshot["python"]
        worktree_root = str(snapshot["worktree_root"])
        if not isinstance(env, dict) or not isinstance(python, dict):
            raise ValueError("env and python must be mappings")
        worktree = (
            config.WSL_MAIN_REPO
            / worktree_root
            / commit_short
            / task_name
        )
        python_root = (
            config.WSL_MAIN_REPO
            if python.get("source") == "main_repo"
            else worktree
        )
        python_path = python_root / str(python["path"])
        payload = {
            "validator": validator,
            "expected_files": expected_files,
            "validator_config": validator_config,
            "worktree": str(worktree),
            "archive": remote_archive,
            "commit": str(snapshot["commit"]),
            "commit_short": commit_short,
            "task_name": task_name,
            "timestamp": archive.name,
            "worktree_root": worktree_root,
            "env": env,
        }
        encoded = base64.urlsafe_b64encode(
            json.dumps(payload, sort_keys=True).encode("utf-8")
        ).decode("ascii")
    except (KeyError, TypeError, ValueError, OSError, json.JSONDecodeError) as exc:
        return (
            fail(
                FailType.STRUCTURE,
                f"cannot build remote verification request: {exc}",
            ),
            [],
            {},
        )

    command = (
        f"{shlex.quote(str(python_path))} -m oer_wf.remote_verify "
        f"--payload {shlex.quote(encoded)}"
    )
    result = ex.ssh_exec(command, timeout=timeout_sec)
    if not result.ok:
        return (
            fail(
                FailType.TRANSPORT,
                "remote validator transport failed: "
                + (result.stderr.strip() or f"exit {result.returncode}"),
                next_action="check SSH and retry wf verify",
            ),
            [],
            {},
        )
    try:
        lines = [line for line in result.stdout.splitlines() if line.strip()]
        remote = json.loads(lines[-1])
        if remote.get("status") not in {"pass", "fail"}:
            raise ValueError("remote status is invalid")
        remote_checks = [
            CheckResult.model_validate(item)
            for item in remote.get("checks", [])
        ]
    except (IndexError, TypeError, ValueError, json.JSONDecodeError) as exc:
        return (
            fail(
                FailType.TRANSPORT,
                f"remote validator returned invalid JSON: {exc}",
            ),
            [],
            {},
        )
    evidence_expected = {
        "validator": validator,
        "commit": str(snapshot["commit"]),
        "worktree": str(worktree),
        "archive": remote_archive,
        "env_keys": sorted(str(key) for key in env),
    }
    evidence_actual = {key: remote.get(key) for key in evidence_expected}
    if evidence_actual != evidence_expected:
        return (
            fail(
                FailType.STRUCTURE,
                "remote validator evidence mismatch: "
                f"expected={evidence_expected}, actual={evidence_actual}",
            ),
            [],
            {},
        )
    execution = {
        "validator": validator,
        "execution": "remote_worktree",
        "timeout_sec": timeout_sec,
        "commit": remote.get("commit"),
        "worktree": remote.get("worktree"),
        "archive": remote.get("archive"),
        "env_keys": remote.get("env_keys", []),
        "duration_seconds": remote.get("duration_seconds"),
    }
    if remote.get("status") == "fail" and not remote_checks:
        try:
            fail_type = FailType(str(remote.get("fail_type")))
        except ValueError:
            fail_type = FailType.STRUCTURE
        return (
            fail(fail_type, str(remote.get("message") or "remote validator failed")),
            [],
            execution,
        )
    return None, remote_checks, execution
