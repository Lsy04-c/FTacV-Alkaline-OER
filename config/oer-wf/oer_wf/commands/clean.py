"""wf clean – reset intermediate state for a task_id."""

from __future__ import annotations

from typing import Optional

from oer_wf import config
from oer_wf.models import FailType, WfResponse
from oer_wf.response import fail, ok
from oer_wf.transport import Executor, RealExecutor
from oer_wf.utils.systemd import unit_name


def run_clean(
    task_id: str,
    force: bool = False,
    keep_results: bool = False,
    executor: Optional[Executor] = None,
) -> WfResponse:
    """
    Clean intermediate state for task_id.

    Default (no --force):
      - stop & reset systemd unit (formal + smoke)
      - remove unit files
      - remove .wf_lock and _smoke_* temps inside worktree
      - keep worktree source tree and result directories

    --force:
      - remove worktree source, but results handling depends on --keep-results

    --keep-results:
      - NEVER delete result directories
      - with --force: move/preserve results outside worktree before removing
        the worktree, or refuse force-delete if preservation fails
    """
    ex = executor or RealExecutor()
    main_repo = config.WSL_MAIN_REPO
    unit = unit_name(task_id)
    unit_smoke = unit.removesuffix(".service") + "-smoke.service"

    actions: list[str] = []

    # 1. Stop / reset both formal and smoke units
    r_stop = ex.ssh_exec(
        f"systemctl --user stop {unit} {unit_smoke} 2>/dev/null; "
        f"systemctl --user reset-failed {unit} {unit_smoke} 2>/dev/null; "
        f"systemctl stop {unit} {unit_smoke} 2>/dev/null; "
        f"systemctl reset-failed {unit} {unit_smoke} 2>/dev/null; "
        f"echo done"
    )
    actions.append(f"systemd stop/reset: {unit}, {unit_smoke}")

    # 2. Remove unit files
    r_rm_unit = ex.ssh_exec(
        f"rm -f ~/.config/systemd/user/{unit} ~/.config/systemd/user/{unit_smoke} "
        f"/etc/systemd/system/{unit} /etc/systemd/system/{unit_smoke} 2>/dev/null; "
        f"systemctl --user daemon-reload 2>/dev/null; "
        f"systemctl daemon-reload 2>/dev/null; "
        f"echo done"
    )
    actions.append("unit files removed (if existed)")

    parts = task_id.split("/", 1)
    if len(parts) != 2:
        return fail(
            FailType.STRUCTURE,
            f"invalid task_id format (expected commit_short/task_name): {task_id}",
            next_action="provide a valid task_id",
        )
    commit_short, task_name = parts
    wt = main_repo / "worktrees" / commit_short / task_name
    results_dir = f"{wt}/results"

    r_exists = ex.ssh_exec(f"test -d {wt} && echo yes || echo no")
    if not r_exists.ok or "yes" not in r_exists.stdout:
        return ok(
            message=f"nothing to clean (worktree absent): {wt}",
            next_action="wf prepare <task_spec.yaml>",
            data={"task_id": task_id, "actions": actions},
        )

    if force and keep_results:
        # Preserve results outside worktree, then remove the rest of the worktree.
        # Staging location: <main_repo>/_wf_preserved_results/<task_id>/
        preserve_root = f"{main_repo}/_wf_preserved_results/{commit_short}/{task_name}"
        r_preserve = ex.ssh_exec(
            f"if test -d {results_dir}; then "
            f"  mkdir -p {preserve_root} && "
            f"  cp -a {results_dir}/. {preserve_root}/ && "
            f"  echo PRESERVED; "
            f"else "
            f"  echo NO_RESULTS; "
            f"fi"
        )
        if not r_preserve.ok:
            return fail(
                FailType.TRANSPORT,
                f"--keep-results requested but failed to preserve results: "
                f"{r_preserve.stderr.strip() or r_preserve.stdout.strip()}",
                next_action="manual copy of results, then retry clean --force",
                data={"stderr": r_preserve.stderr, "results_dir": results_dir},
            )
        if "PRESERVED" in r_preserve.stdout:
            actions.append(f"results preserved to {preserve_root}")
        else:
            actions.append("no results dir to preserve")

        # Remove worktree but NOT by rm -rf blindly on results still inside:
        # after copy, safe to remove whole worktree
        r_rm = ex.ssh_exec(
            f"cd {main_repo} && "
            f"git worktree remove --force {wt} 2>/dev/null || rm -rf {wt}"
        )
        if not r_rm.ok:
            return fail(
                FailType.ENVIRONMENT,
                f"failed to remove worktree after preserving results: {r_rm.stderr.strip()}",
                next_action=f"results should be at {preserve_root}; inspect manually",
                data={"stderr": r_rm.stderr, "preserved": preserve_root},
            )
        actions.append(f"worktree removed: {wt}")
        actions.append("results preserved (--keep-results)")

    elif force and not keep_results:
        # Explicit destructive path – results go with worktree
        r_rm = ex.ssh_exec(
            f"cd {main_repo} && "
            f"git worktree remove --force {wt} 2>/dev/null || rm -rf {wt}"
        )
        if not r_rm.ok:
            return fail(
                FailType.ENVIRONMENT,
                f"failed to remove worktree: {r_rm.stderr.strip()}",
                next_action="manual inspection required",
                data={"stderr": r_rm.stderr},
            )
        actions.append(f"worktree removed (including results): {wt}")

    else:
        # Soft clean: only lock + smoke temps; never touch formal results
        r_soft = ex.ssh_exec(
            f"rm -f {wt}/.wf_lock && "
            f"rm -rf {wt}/results/*/_smoke_* 2>/dev/null; "
            f"echo done"
        )
        actions.append("removed .wf_lock and _smoke_* temps")
        if keep_results:
            actions.append("results preserved (--keep-results, soft clean)")

    return ok(
        message=f"cleaned task {task_id}"
        + (" (force)" if force else "")
        + (" (keep-results)" if keep_results else ""),
        next_action="wf prepare <task_spec.yaml>",
        data={
            "task_id": task_id,
            "force": force,
            "keep_results": keep_results,
            "actions": actions,
            "worktree": str(wt),
        },
    )
