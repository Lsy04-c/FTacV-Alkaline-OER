"""StatusContext: file-signal-based STATUS.json writer for cross-process reliability.

Problem: mark_fail_numerical() called in a child process modifies only the
child's Python memory; the parent's atexit handler cannot see the change.

Solution: Write a signal file (._status_signal) that both parent and child
processes can read/write. The atexit handler reads the signal file to
determine the final status.
"""

from __future__ import annotations

import atexit
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


class StatusContext:
    """STATUS.json writer using file signals for cross-process communication.

    Signal file:  <output_dir>/._status_signal
    Status file:  <output_dir>/STATUS.json

    Usage:
        with StatusContext(output_dir, spec_hash="abc123") as ctx:
            result = solver.solve(params)
            ctx.set_success(extra={"converged": True})

            # Inside a child process (e.g. multiprocessing):
            ctx.mark_fail_numerical("LSODA too many steps")
    """

    SIGNAL_FILE = "._status_signal"
    STATUS_FILE = "STATUS.json"

    def __init__(
        self,
        output_dir: str | Path,
        spec_hash: Optional[str] = None,
        task_id: Optional[str] = None,
        commit: Optional[str] = None,
    ):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.signal_path = self.output_dir / self.SIGNAL_FILE
        self.status_path = self.output_dir / self.STATUS_FILE
        self.spec_hash = spec_hash
        self.task_id = task_id
        self.commit = commit
        self._finalized = False
        self._write_signal("FAIL_INFRA", "process started, not yet finalized")
        atexit.register(self._finalize)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_success(self, extra: Optional[dict[str, Any]] = None) -> None:
        """Mark the computation as successful."""
        self._write_signal("SUCCESS", "", extra)
        self._finalized = True

    def mark_fail_numerical(
        self,
        error_msg: str = "",
        extra: Optional[dict[str, Any]] = None,
    ) -> None:
        """Mark as numerical failure. Safe to call from child processes."""
        self._write_signal("FAIL_NUMERICAL", error_msg, extra)
        self._finalized = True

    def mark_fail_infra(
        self,
        error_msg: str = "",
        extra: Optional[dict[str, Any]] = None,
    ) -> None:
        """Mark as infrastructure failure. Safe to call from child processes."""
        self._write_signal("FAIL_INFRA", error_msg, extra)
        self._finalized = True

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _write_signal(
        self,
        status: str,
        error_msg: str = "",
        extra: Optional[dict[str, Any]] = None,
    ) -> None:
        """Write signal file — safe for child processes."""
        data = {
            "status": status,
            "exit_code": 0,
            "pid": os.getpid(),
            "error_msg": error_msg,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "spec_hash": self.spec_hash,
            "task_id": self.task_id,
            "commit": self.commit,
            "extra": extra or {},
        }
        self.signal_path.write_text(json.dumps(data, indent=2))

    def _finalize(self) -> None:
        """atexit handler: read signal file, write final STATUS.json."""
        signal: Optional[dict[str, Any]] = None
        if self.signal_path.exists():
            try:
                signal = json.loads(self.signal_path.read_text())
            except json.JSONDecodeError:
                pass

        if signal is None and not self._finalized:
            signal = {
                "status": "FAIL_INFRA",
                "exit_code": -1,
                "pid": os.getpid(),
                "error_msg": "process exited without explicit success/fail signal",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "spec_hash": self.spec_hash,
                "task_id": self.task_id,
                "commit": self.commit,
                "extra": {},
            }

        if signal:
            self.status_path.write_text(json.dumps(signal, indent=2))

    def __enter__(self) -> "StatusContext":
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: object,
    ) -> bool:
        if exc_type is not None:
            if issubclass(exc_type, SystemExit):
                self._write_signal(
                    "FAIL_INFRA", f"SystemExit: {exc_val}"
                )
            else:
                self._write_signal(
                    "FAIL_NUMERICAL",
                    f"uncaught {exc_type.__name__}: {exc_val}",
                )
        self._finalize()
        return False  # propagate exception
