"""wf sync – pull WSL results to Mac archive via rsync."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Optional

from oer_wf import config
from oer_wf.models import FailType, WfResponse
from oer_wf.utils.systemd import unit_name


def _extract_output_dir_from_execstart(ex: "Executor", task_id: str) -> Optional[str]:
    """Extract output_dir from systemd unit ExecStart --output argument."""
    unit = unit_name(task_id)
    r_cat = ex.ssh_exec(f"systemctl --user cat {unit} 2>/dev/null || true")
    if not r_cat.ok:
        return None
    for line in r_cat.stdout.split("\n"):
        if "ExecStart=" in line:
            m = re.search(r'--output[=\s]+(\S+)', line)
            if m:
                return m.group(1)
    return None
from oer_wf.response import fail, ok, warning
from oer_wf.transport import Executor, RealExecutor


def _parse_task_id(task_id: str) -> tuple[str, str]:
    parts = task_id.split("/", 1)
    if len(parts) != 2:
        raise ValueError(f"invalid task_id: {task_id}")
    return parts[0], parts[1]


def _find_remote_output(
    ex: Executor,
    worktree: str,
    output_base: str,
    timestamp: Optional[str],
) -> Optional[str]:
    if timestamp:
        # formal timestamp dir
        candidate = f"{worktree}/{output_base}/{timestamp}"
        r = ex.ssh_exec(f"test -d {candidate} && echo {candidate} || echo MISSING")
        if r.ok and "MISSING" not in r.stdout:
            return r.stdout.strip().splitlines()[-1].strip()
        return None

    # latest formal (non-smoke) dir
    cmd = f"ls -1d {worktree}/{output_base}/[0-9]* 2>/dev/null | sort | tail -1 || true"
    r = ex.ssh_exec(cmd)
    if not r.ok:
        return None
    lines = [ln.strip() for ln in r.stdout.splitlines() if ln.strip()]
    return lines[-1] if lines else None


def _archive_path(commit_short: str, task_name: str, timestamp: str) -> Path:
    return (
        config.MAC_ARCHIVE_ROOT
        / "results"
        / commit_short
        / task_name
        / timestamp
    )


def run_sync(
    task_id: str,
    *,
    timestamp: Optional[str] = None,
    output_base: Optional[str] = None,
    executor: Optional[Executor] = None,
) -> WfResponse:
    """
    rsync WSL result dir → Mac archive.

    Layout:
      <MAC_ARCHIVE_ROOT>/results/<commit_short>/<task_name>/<timestamp>/

    Never overwrites an existing local archive dir for the same timestamp
    (returns fail and asks for explicit removal).
    """
    ex = executor or RealExecutor()

    try:
        commit_short, task_name = _parse_task_id(task_id)
    except ValueError as e:
        return fail(FailType.STRUCTURE, str(e))

    main_repo = config.WSL_MAIN_REPO
    worktree = f"{main_repo}/worktrees/{commit_short}/{task_name}"

    # Resolve remote path: ExecStart gives full timestamped result dir;
    # convention-based fallback searches under <worktree>/<output_base>/
    remote: Optional[str] = None
    if output_base is None:
        extracted = _extract_output_dir_from_execstart(ex, task_id)
        if extracted:
            # extracted is the full absolute result directory — use directly
            r_exists = ex.ssh_exec(f"test -d {extracted} && echo 'yes' || echo 'no'")
            if r_exists.ok and "yes" in r_exists.stdout:
                remote = extracted

    if remote is None:
        base = output_base or f"results/{task_name}"
        remote = _find_remote_output(ex, worktree, base, timestamp)

    if not remote:
        return fail(
            FailType.TRANSPORT,
            f"no remote result dir found for {task_id}"
            + (f" timestamp={timestamp}" if timestamp else " (latest)"),
            next_action=f"wf status {task_id}  # confirm completion first",
        )

    ts = Path(remote).name
    local = _archive_path(commit_short, task_name, ts)

    if local.exists() and any(local.iterdir()):
        return fail(
            FailType.TRANSPORT,
            f"local archive already exists and is non-empty: {local}. "
            "Refusing to overwrite historical evidence.",
            next_action=f"remove or rename {local} only if intentional",
            data={"remote": remote, "local": str(local)},
        )

    local.mkdir(parents=True, exist_ok=True)

    # Ensure trailing slash semantics: copy contents into local/
    remote_src = remote.rstrip("/") + "/"
    local_dst = str(local) + "/"

    r = ex.rsync_pull(remote_src, local_dst)
    if not r.ok:
        return fail(
            FailType.TRANSPORT,
            f"rsync failed (rc={r.returncode}): {r.stderr.strip() or r.stdout.strip()}",
            next_action="check SSH/rsync; retry wf sync",
            data={"remote": remote, "local": str(local), "stderr": r.stderr},
        )

    # Count files + optional STATUS check
    files = [p for p in local.rglob("*") if p.is_file()]
    status_ok = (local / "STATUS.json").exists()
    status_val = None
    if status_ok:
        try:
            status_val = json.loads((local / "STATUS.json").read_text()).get("status")
        except Exception:
            status_val = "corrupt"

    data = {
        "task_id": task_id,
        "remote": remote,
        "local": str(local),
        "timestamp": ts,
        "file_count": len(files),
        "status": status_val,
    }

    if not status_ok:
        return warning(
            message=f"synced {len(files)} files but STATUS.json missing",
            next_action=f"wf verify {task_id}",
            data=data,
        )

    if status_val not in ("SUCCESS", None):
        return warning(
            message=f"synced {len(files)} files; STATUS={status_val}",
            next_action=f"wf verify {task_id}",
            data=data,
        )

    return ok(
        message=f"synced {len(files)} files → {local}",
        next_action=f"wf verify {task_id}",
        data=data,
    )
