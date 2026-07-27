"""Tests for universal STATUS wrapper."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from oer_wf.models import ComputeStatus
from oer_wf.runtime.wrapper import run_wrapped, write_status
from oer_wf.models import StatusFile


def test_write_status_atomic(tmp_path: Path) -> None:
    p = tmp_path / "STATUS.json"
    st = StatusFile(status=ComputeStatus.RUNNING, pid=1, task_id="a/b", commit="abc")
    write_status(p, st)
    assert p.exists()
    data = json.loads(p.read_text())
    assert data["status"] == "RUNNING"
    # no leftover tmp
    assert list(tmp_path.glob("*.tmp.*")) == []


def test_run_wrapped_success(tmp_path: Path) -> None:
    status = tmp_path / "STATUS.json"
    out = tmp_path / "out"
    out.mkdir()
    # Use a trivial command that exits 0
    code = run_wrapped(
        [sys.executable, "-c", "print('ok')"],
        status_file=status,
        task_id="3f9aad1/test",
        commit="3f9aad1",
        output_dir=str(out),
    )
    assert code == 0
    data = json.loads(status.read_text())
    assert data["status"] == "SUCCESS"
    assert data["exit_code"] == 0
    assert data["finished_at"] is not None
    assert data["pid"] is not None


def test_run_wrapped_infra_fail(tmp_path: Path) -> None:
    status = tmp_path / "STATUS.json"
    out = tmp_path / "out"
    out.mkdir()
    code = run_wrapped(
        [sys.executable, "-c", "import sys; sys.exit(1)"],
        status_file=status,
        task_id="3f9aad1/test",
        commit="3f9aad1",
        output_dir=str(out),
    )
    assert code == 1
    data = json.loads(status.read_text())
    assert data["status"] == "FAIL_INFRA"
    assert data["exit_code"] == 1


def test_run_wrapped_numerical_exit_code(tmp_path: Path) -> None:
    status = tmp_path / "STATUS.json"
    out = tmp_path / "out"
    out.mkdir()
    code = run_wrapped(
        [sys.executable, "-c", "import sys; sys.exit(2)"],  # EXIT_NUMERICAL
        status_file=status,
        task_id="3f9aad1/test",
        commit="3f9aad1",
        output_dir=str(out),
    )
    assert code == 2
    data = json.loads(status.read_text())
    assert data["status"] == "FAIL_NUMERICAL"
