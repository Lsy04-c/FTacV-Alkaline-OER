"""wf status – combine systemd state with STATUS.json (never guess success)."""

from __future__ import annotations

import json
import re
from typing import Any, Optional

from oer_wf import config
from oer_wf.models import ComputeStatus, FailType, StatusEnum, WfResponse
from oer_wf.response import fail, ok, running, warning
from oer_wf.transport import Executor, RealExecutor
from oer_wf.utils.systemd import parse_show, show_cmd, unit_name


def _extract_output_dir_from_unit(unit_content: str) -> Optional[str]:
    """Extract output_dir from systemd unit ExecStart --output argument."""
    for line in unit_content.split("\n"):
        if line.strip().startswith("ExecStart="):
            m = re.search(r'--output[=\s]+(\S+)', line)
            if m:
                return m.group(1)
    # Fallback: parse StandardOutput log path
    for line in unit_content.split("\n"):
        if "StandardOutput" in line and "append:" in line:
            path = line.split("append:")[1].strip()
            if path.endswith("/log.txt"):
                return path[:-len("/log.txt")]
            return path
    return None


def _find_latest_output(ex: Executor, worktree: str, output_base: str) -> Optional[str]:
    """Return absolute path of latest non-smoke timestamp dir, or None."""
    # List timestamp dirs under output_base, exclude _smoke_*
    cmd = (
        f"ls -1d {worktree}/{output_base}/[0-9]* 2>/dev/null | sort | tail -1 || true"
    )
    r = ex.ssh_exec(cmd)
    if not r.ok:
        return None
    path = r.stdout.strip().splitlines()
    if not path:
        return None
    candidate = path[-1].strip()
    return candidate or None


def _read_status_json(ex: Executor, output_dir: str) -> tuple[Optional[dict[str, Any]], str]:
    """Return (parsed dict or None, raw/error detail)."""
    r = ex.ssh_exec(f"cat {output_dir}/STATUS.json 2>/dev/null || echo __MISSING__")
    if not r.ok or "__MISSING__" in r.stdout:
        return None, "STATUS.json missing"
    raw = r.stdout.strip()
    try:
        return json.loads(raw), raw
    except json.JSONDecodeError as e:
        return None, f"STATUS.json corrupt: {e}"


def run_status(
    task_id: str,
    output_dir: Optional[str] = None,
    executor: Optional[Executor] = None,
) -> WfResponse:
    """
    Query task state using systemd ∩ STATUS.json.

    Conflict rule: if the two sources disagree, report status=inconsistent
    and never claim success.
    """
    ex = executor or RealExecutor()
    unit = unit_name(task_id)

    parts = task_id.split("/", 1)
    if len(parts) != 2:
        return fail(
            FailType.STRUCTURE,
            f"invalid task_id (expected commit_short/task_name): {task_id}",
        )
    commit_short, task_name = parts
    main_repo = config.WSL_MAIN_REPO
    worktree = f"{main_repo}/worktrees/{commit_short}/{task_name}"

    # ---- systemd ----
    r_show = ex.ssh_exec(show_cmd(unit))
    sd = parse_show(unit, r_show.stdout if r_show.ok else "")

    # ---- locate output_dir from ExecStart (primary) or fallback ----
    if output_dir is None:
        r_cat = ex.ssh_exec(f"systemctl --user cat {unit} 2>/dev/null || true")
        output_dir = _extract_output_dir_from_unit(r_cat.stdout) if r_cat.ok else None
        if output_dir is None:
            output_base = f"results/{task_name}"
            output_dir = _find_latest_output(ex, worktree, output_base)

    status_data: Optional[dict[str, Any]] = None
    status_detail = "no output_dir"
    if output_dir:
        status_data, status_detail = _read_status_json(ex, output_dir)

    data: dict[str, Any] = {
        "task_id": task_id,
        "unit": unit,
        "output_dir": output_dir,
        "systemd": {
            "exists": sd.exists,
            "active": sd.active,
            "sub": sd.sub,
            "main_pid": sd.main_pid,
            "result": sd.result,
            "exec_main_status": sd.exec_main_status,
        },
        "status_file": status_data,
    }

    st = (status_data or {}).get("status") if status_data else None

    # ---- combination matrix ----
    # 1. Unit active + STATUS RUNNING → running
    if sd.is_active and st == ComputeStatus.RUNNING.value:
        return running(
            message=f"running (pid={sd.main_pid})",
            next_action=f"wf status {task_id}   # poll again later",
            data=data,
        )

    # 2. Unit active + STATUS terminal → INCONSISTENT
    if sd.is_active and st in (
        ComputeStatus.SUCCESS.value,
        ComputeStatus.FAIL_NUMERICAL.value,
        ComputeStatus.FAIL_INFRA.value,
    ):
        return WfResponse(
            status=StatusEnum.INCONSISTENT,
            fail_type=FailType.ENVIRONMENT,
            message=(
                f"inconsistent: systemd active={sd.active} but STATUS={st}. "
                "Do not treat as success."
            ),
            next_action=f"inspect journalctl --user -u {unit}; wf clean {task_id}",
            data=data,
        )

    # 3. Unit active + STATUS missing/STARTING → running (starting)
    if sd.is_active:
        return running(
            message=f"unit active, STATUS={st or 'missing'}",
            next_action=f"wf status {task_id}",
            data=data,
        )

    # 4. Unit inactive + STATUS SUCCESS → pass
    if not sd.is_active and st == ComputeStatus.SUCCESS.value:
        return ok(
            message="completed successfully",
            next_action=f"wf sync {task_id}",
            data=data,
        )

    # 5. Unit inactive + STATUS FAIL_NUMERICAL → fail numerical
    if not sd.is_active and st == ComputeStatus.FAIL_NUMERICAL.value:
        return fail(
            FailType.NUMERICAL,
            status_data.get("error_msg") or "numerical failure",
            next_action="inspect STATUS.json / logs; scientific decision required",
            data=data,
        )

    # 6. Unit inactive + STATUS FAIL_INFRA → fail infra
    if not sd.is_active and st == ComputeStatus.FAIL_INFRA.value:
        return fail(
            FailType.ENVIRONMENT,
            status_data.get("error_msg") or "infrastructure failure",
            next_action=f"wf clean {task_id} then retry",
            data=data,
        )

    # 7. Unit inactive + STATUS still RUNNING → inconsistent
    if not sd.is_active and st == ComputeStatus.RUNNING.value:
        return WfResponse(
            status=StatusEnum.INCONSISTENT,
            fail_type=FailType.ENVIRONMENT,
            message="inconsistent: systemd inactive but STATUS still RUNNING",
            next_action=f"inspect {output_dir}/STATUS.json and journalctl",
            data=data,
        )

    # 8. Unit failed (systemd) + any STATUS
    if sd.is_failed:
        if st == ComputeStatus.SUCCESS.value:
            return WfResponse(
                status=StatusEnum.INCONSISTENT,
                fail_type=FailType.ENVIRONMENT,
                message="inconsistent: systemd failed but STATUS=SUCCESS",
                next_action="manual inspection required",
                data=data,
            )
        return fail(
            FailType.ENVIRONMENT,
            f"systemd failed (result={sd.result}, STATUS={st or 'missing'})",
            next_action=f"journalctl --user -u {unit} -n 50; wf clean {task_id}",
            data=data,
        )

    # 9. No unit, no STATUS
    if not sd.exists and status_data is None:
        return fail(
            FailType.STRUCTURE,
            f"no unit and no STATUS.json for {task_id}",
            next_action=f"wf prepare <spec> && wf run <spec>",
            data=data,
        )

    # 10. STATUS missing but unit inactive with success result
    if not sd.is_active and sd.result == "success" and status_data is None:
        return warning(
            message="systemd reports success but STATUS.json missing",
            next_action="inspect output dir; do not archive without STATUS",
            data=data,
        )

    # Fallback
    return warning(
        message=f"ambiguous state: systemd={sd.active}/{sd.sub}, STATUS={st or status_detail}",
        next_action=f"manual inspection of {unit} and {output_dir}",
        data=data,
    )
