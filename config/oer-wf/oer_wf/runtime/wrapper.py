"""Universal task wrapper.

Wraps any compute script so STATUS.json is always written atomically,
without requiring each scientific script to implement try/finally.

Usage (inside the launched process, typically via `python -m oer_wf.runtime.wrapper`):

    python -m oer_wf.runtime.wrapper \\
        --status-file /path/to/STATUS.json \\
        --task-id 3f9aad1/solver_equiv_01 \\
        --commit 3f9aad1 \\
        --output-dir /path/to/out \\
        -- /path/to/python /path/to/script.py --config cfg.yaml --output ... --workers 4

Or import and call `run_wrapped(argv, ...)` from a systemd ExecStart helper.
"""

from __future__ import annotations

import argparse
import atexit
import json
import os
import signal
import sys
import traceback
from pathlib import Path
from typing import Any, Optional

from oer_wf.models import EXIT_NUMERICAL, ComputeStatus, StatusFile

# ---------------------------------------------------------------------------
# Module-level state for atexit / signal handlers
# ---------------------------------------------------------------------------

_status_path: Optional[Path] = None
_status: Optional[StatusFile] = None
_finalized: bool = False


def _utc_now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def write_status(path: Path, status: StatusFile) -> None:
    """Atomic write: tmp → fsync → replace."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    data = status.model_dump_json(indent=2) + "\n"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def mark_fail_numerical(msg: str, extra: Optional[dict[str, Any]] = None) -> None:
    """
    Callable from inside a compute script to declare numerical failure.

    Example:
        from oer_wf.runtime.wrapper import mark_fail_numerical
        mark_fail_numerical("LSODA failed with too many steps")
        sys.exit(2)
    """
    global _status
    if _status is None:
        return
    _status.status = ComputeStatus.FAIL_NUMERICAL
    _status.error_msg = msg
    if extra:
        _status.extra.update(extra)
    if _status_path:
        write_status(_status_path, _status)


def _finalize(exit_code: int, error_msg: Optional[str] = None) -> None:
    """Idempotent final status write.

    Priority (highest first):
      1. Child-process signal file (._status_signal) — cross-process reliable
      2. In-process _status.status if already FAIL_NUMERICAL
      3. Exit code 0 → SUCCESS, 2 → FAIL_NUMERICAL, else FAIL_INFRA
    """
    global _finalized, _status
    if _finalized or _status is None or _status_path is None:
        return
    _finalized = True

    signal_path = _status_path.parent / "._status_signal"

    # 1. Check file signal (child-process safe)
    signal_status: Optional[str] = None
    if signal_path.exists():
        try:
            signal_data = json.loads(signal_path.read_text())
            signal_status = signal_data.get("status")
            if signal_data.get("error_msg") and not error_msg:
                error_msg = signal_data["error_msg"]
        except (json.JSONDecodeError, OSError, KeyError):
            pass

    if signal_status == "SUCCESS":
        final = ComputeStatus.SUCCESS
    elif signal_status in ("FAIL_NUMERICAL", "fail_numerical"):
        final = ComputeStatus.FAIL_NUMERICAL
    elif signal_status in ("FAIL_INFRA", "fail_infra"):
        final = ComputeStatus.FAIL_INFRA
    # 2. Respect in-process numerical mark
    elif _status.status == ComputeStatus.FAIL_NUMERICAL:
        final = ComputeStatus.FAIL_NUMERICAL
    elif exit_code == 0:
        final = ComputeStatus.SUCCESS
    elif exit_code == EXIT_NUMERICAL:
        final = ComputeStatus.FAIL_NUMERICAL
    else:
        final = ComputeStatus.FAIL_INFRA

    _status.status = final
    _status.exit_code = exit_code
    _status.finished_at = _utc_now()
    if error_msg and not _status.error_msg:
        _status.error_msg = error_msg
    write_status(_status_path, _status)


def _atexit_handler() -> None:
    # If we reach atexit without explicit finalize, treat as infra fail
    # unless already finalized (normal path calls _finalize before exit).
    if not _finalized:
        code = 1
        try:
            # sys.exc_info is empty in atexit; use last exit code if available
            code = getattr(sys, "last_exc", None) and 1 or (
                0 if _status and _status.status == ComputeStatus.RUNNING else 1
            )
        except Exception:
            code = 1
        # Prefer non-zero if still RUNNING (abnormal termination)
        if _status and _status.status in (
            ComputeStatus.STARTING,
            ComputeStatus.RUNNING,
        ):
            code = code or 1
        _finalize(code, error_msg="process exited without explicit finalize")


def _signal_handler(signum: int, frame: Any) -> None:
    name = signal.Signals(signum).name if hasattr(signal, "Signals") else str(signum)
    _finalize(128 + signum, error_msg=f"terminated by signal {name}")
    # Re-raise default behaviour
    signal.signal(signum, signal.SIG_DFL)
    os.kill(os.getpid(), signum)


def run_wrapped(
    argv: list[str],
    *,
    status_file: Path,
    task_id: str,
    commit: str,
    output_dir: str,
    env: Optional[dict[str, str]] = None,
) -> int:
    """
    Write STARTING → RUNNING, exec the user command via subprocess semantics
    (we import-run if possible is complex; use subprocess for isolation).

    Actually for STATUS fidelity we stay in-process only for the wrapper
    bookkeeping and use subprocess to launch the real script so signals
    and exit codes are clean.
    """
    import subprocess

    global _status_path, _status, _finalized
    _status_path = Path(status_file)
    _finalized = False

    _status = StatusFile(
        status=ComputeStatus.STARTING,
        pid=os.getpid(),
        started_at=_utc_now(),
        commit=commit,
        task_id=task_id,
        spec_hash=os.environ.get("OER_WF_SPEC_HASH"),
        command=argv,
        output_dir=output_dir,
    )
    write_status(_status_path, _status)

    # Register hooks before launching child
    atexit.register(_atexit_handler)
    for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        try:
            signal.signal(sig, _signal_handler)
        except (ValueError, OSError):
            pass

    _status.status = ComputeStatus.RUNNING
    write_status(_status_path, _status)

    child_env = os.environ.copy()
    if env:
        child_env.update(env)
    # Expose status path so scripts can call mark_fail_numerical
    child_env["OER_WF_STATUS_FILE"] = str(_status_path)

    try:
        proc = subprocess.run(argv, env=child_env)
        code = proc.returncode
        _finalize(code)
        return code
    except Exception as e:
        _finalize(1, error_msg=f"{type(e).__name__}: {e}\n{traceback.format_exc()}")
        return 1


# ---------------------------------------------------------------------------
# CLI entry: python -m oer_wf.runtime.wrapper
# ---------------------------------------------------------------------------

def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="oer-wf universal task wrapper")
    parser.add_argument("--status-file", required=True, type=Path)
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument(
        "command",
        nargs=argparse.REMAINDER,
        help="User command after --",
    )
    args = parser.parse_args(argv)

    cmd = args.command
    if cmd and cmd[0] == "--":
        cmd = cmd[1:]
    if not cmd:
        print("wrapper: no command provided after --", file=sys.stderr)
        return 1

    return run_wrapped(
        cmd,
        status_file=args.status_file,
        task_id=args.task_id,
        commit=args.commit,
        output_dir=args.output_dir,
    )


if __name__ == "__main__":
    sys.exit(main())
