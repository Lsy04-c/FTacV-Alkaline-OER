"""wf prepare – create or reuse a commit-specific worktree with lock."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import base64

import yaml

from oer_wf import config
from oer_wf.lock import check_lock, spec_hash, write_lock
from oer_wf.models import FailType, LockInfo, TaskSpec, WfResponse
from oer_wf.response import fail, ok
from oer_wf.transport import Executor, RealExecutor


def load_spec(spec_path: str | Path) -> TaskSpec:
    path = Path(spec_path)
    if not path.exists():
        raise FileNotFoundError(f"task_spec not found: {path}")
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return TaskSpec.model_validate(raw)


def run_prepare(
    spec_path: str | Path,
    executor: Optional[Executor] = None,
) -> WfResponse:
    """
    Create (or reuse) a commit-specific worktree and write .wf_lock.

    Rules:
      - worktree missing          → create + lock
      - worktree exists, hash ok  → reuse
      - worktree exists, hash bad → fail (require clean)
    """
    ex = executor or RealExecutor()

    try:
        spec = load_spec(spec_path)
    except Exception as e:
        return fail(
            FailType.STRUCTURE,
            f"invalid task_spec: {e}",
            next_action="fix the YAML schema",
        )

    main_repo = config.WSL_MAIN_REPO
    wt = spec.worktree_path(main_repo)
    expected_hash = spec_hash(spec)

    # ---- remote: does the worktree directory already exist? ----
    r_exists = ex.ssh_exec(f"test -d {wt} && echo yes || echo no")
    if not r_exists.ok:
        return fail(
            FailType.TRANSPORT,
            f"cannot probe worktree path: {r_exists.stderr}",
            next_action="check SSH connectivity (wf doctor)",
        )

    exists = "yes" in r_exists.stdout

    if exists:
        # Read remote lock
        r_lock = ex.ssh_exec(f"cat {wt}/.wf_lock 2>/dev/null || echo ''")
        if r_lock.ok and r_lock.stdout.strip():
            try:
                existing = LockInfo.model_validate_json(r_lock.stdout.strip())
            except Exception:
                return fail(
                    FailType.STRUCTURE,
                    f"corrupt .wf_lock in {wt}",
                    next_action=f"wf clean --force {spec.task_id}",
                )
            if existing.spec_hash == expected_hash and existing.task_id == spec.task_id:
                return ok(
                    message=f"worktree already prepared (reuse): {wt}",
                    next_action=f"wf smoke {spec_path}",
                    data={
                        "task_id": spec.task_id,
                        "worktree": str(wt),
                        "action": "reuse",
                        "spec_hash": expected_hash,
                    },
                )
            return fail(
                FailType.STRUCTURE,
                f"worktree exists but spec_hash mismatch "
                f"(existing={existing.spec_hash[:16]}…, expected={expected_hash[:16]}…)",
                next_action=f"wf clean --force {spec.task_id}",
                data={
                    "task_id": spec.task_id,
                    "worktree": str(wt),
                    "existing_hash": existing.spec_hash,
                    "expected_hash": expected_hash,
                },
            )
        # Directory exists but no lock → treat as conflict
        return fail(
            FailType.STRUCTURE,
            f"worktree directory exists without .wf_lock: {wt}",
            next_action=f"wf clean --force {spec.task_id}",
        )

    # ---- create worktree ----
    # Ensure the commit is available
    r_fetch = ex.ssh_exec(
        f"cd {main_repo} && git fetch --all --quiet 2>/dev/null; "
        f"git rev-parse --verify {spec.commit}^{{commit}} >/dev/null 2>&1 && echo ok || echo missing"
    )
    if not r_fetch.ok or "missing" in r_fetch.stdout:
        return fail(
            FailType.ENVIRONMENT,
            f"commit {spec.commit} not found in {main_repo}",
            next_action="git push the commit first, then re-run prepare",
        )

    # Create parent dirs and worktree
    parent = wt.parent
    r_mk = ex.ssh_exec(
        f"mkdir -p {parent} && "
        f"cd {main_repo} && "
        f"git worktree add --detach {wt} {spec.commit}"
    )
    if not r_mk.ok:
        return fail(
            FailType.ENVIRONMENT,
            f"git worktree add failed: {r_mk.stderr.strip() or r_mk.stdout.strip()}",
            next_action="inspect git worktree list / disk space",
            data={"stderr": r_mk.stderr},
        )

    # Write lock file on remote
    lock = LockInfo.create(
        task_id=spec.task_id,
        task_name=spec.task_name,
        spec_hash=expected_hash,
        commit=spec.commit,
        worktree_path=wt,
    )
    lock_json = lock.model_dump_json()
    # base64-encode to bypass PowerShell/shell double-quote stripping
    encoded = base64.b64encode(lock_json.encode()).decode()
    r_lock_w = ex.ssh_exec(f"echo {encoded} | base64 -d > {wt}/.wf_lock")
    if not r_lock_w.ok:
        # Best-effort cleanup
        ex.ssh_exec(f"cd {main_repo} && git worktree remove --force {wt} 2>/dev/null || rm -rf {wt}")
        return fail(
            FailType.TRANSPORT,
            f"failed to write .wf_lock: {r_lock_w.stderr}",
            next_action="retry prepare",
        )

    return ok(
        message=f"worktree prepared: {wt}",
        next_action=f"wf smoke {spec_path}",
        data={
            "task_id": spec.task_id,
            "worktree": str(wt),
            "action": "create",
            "spec_hash": expected_hash,
            "commit": spec.commit_short,
        },
    )
