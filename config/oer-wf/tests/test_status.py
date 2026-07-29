"""Unit tests for wf status combination matrix."""

from __future__ import annotations

import json

from oer_wf.commands.status import run_status
from oer_wf.models import StatusEnum
from oer_wf.transport import MockExecutor


TASK = "3f9aad1/solver_equiv_01"


def _status_json(status: str, **extra) -> str:
    body = {
        "status": status,
        "exit_code": 0 if status == "SUCCESS" else 1,
        "pid": 99,
        "started_at": "2026-07-27T09:00:00Z",
        "finished_at": "2026-07-27T09:01:00Z" if status != "RUNNING" else None,
        "commit": "3f9aad1",
        "task_id": TASK,
        "command": ["python", "x.py"],
        "output_dir": "/out",
        "error_msg": extra.get("error_msg"),
        "extra": {},
    }
    return json.dumps(body)


def test_status_running(mock_ex: MockExecutor) -> None:
    mock_ex.when_ssh("systemctl").returns(
        0,
        "LoadState=loaded\nActiveState=active\nSubState=running\nMainPID=42\n"
        "Result=\nExecMainStatus=0\n",
    )
    mock_ex.when_ssh("ls -1d").returns(0, "/home/lsy/OER-FTAcV/worktrees/3f9aad1/solver_equiv_01/results/solver_equiv_01/20260727_090000\n")
    mock_ex.when_ssh("cat ").returns(0, _status_json("RUNNING") + "\n")

    resp = run_status(TASK, executor=mock_ex)
    assert resp.status == StatusEnum.RUNNING


def test_status_oneshot_activating_is_running(mock_ex: MockExecutor) -> None:
    mock_ex.when_ssh("systemctl").returns(
        0,
        "LoadState=loaded\nActiveState=activating\nSubState=start\nMainPID=42\n"
        "Result=success\nExecMainStatus=0\n",
    )
    mock_ex.when_ssh("ls -1d").returns(
        0,
        "/home/lsy/OER-FTAcV/worktrees/3f9aad1/solver_equiv_01/"
        "results/solver_equiv_01/20260727_090000\n",
    )
    mock_ex.when_ssh("cat ").returns(0, _status_json("RUNNING") + "\n")

    resp = run_status(TASK, executor=mock_ex)

    assert resp.status == StatusEnum.RUNNING
    assert "running" in resp.message.lower()


def test_status_success(mock_ex: MockExecutor) -> None:
    mock_ex.when_ssh("systemctl").returns(
        0,
        "LoadState=loaded\nActiveState=inactive\nSubState=dead\nMainPID=0\n"
        "Result=success\nExecMainStatus=0\n",
    )
    mock_ex.when_ssh("ls -1d").returns(
        0,
        "/home/lsy/OER-FTAcV/worktrees/3f9aad1/solver_equiv_01/results/solver_equiv_01/20260727_090000\n",
    )
    mock_ex.when_ssh("cat ").returns(0, _status_json("SUCCESS") + "\n")

    resp = run_status(TASK, executor=mock_ex)
    assert resp.status == StatusEnum.PASS
    assert "sync" in resp.next_action


def test_status_inconsistent_active_but_success(mock_ex: MockExecutor) -> None:
    mock_ex.when_ssh("systemctl").returns(
        0,
        "LoadState=loaded\nActiveState=active\nSubState=running\nMainPID=42\n"
        "Result=\nExecMainStatus=0\n",
    )
    mock_ex.when_ssh("ls -1d").returns(
        0,
        "/home/lsy/OER-FTAcV/worktrees/3f9aad1/solver_equiv_01/results/solver_equiv_01/20260727_090000\n",
    )
    mock_ex.when_ssh("cat ").returns(0, _status_json("SUCCESS") + "\n")

    resp = run_status(TASK, executor=mock_ex)
    assert resp.status == StatusEnum.INCONSISTENT
    assert "inconsistent" in resp.message.lower()


def test_status_numerical_fail(mock_ex: MockExecutor) -> None:
    mock_ex.when_ssh("systemctl").returns(
        0,
        "LoadState=loaded\nActiveState=inactive\nSubState=dead\nMainPID=0\n"
        "Result=exit-code\nExecMainStatus=2\n",
    )
    mock_ex.when_ssh("ls -1d").returns(
        0,
        "/home/lsy/OER-FTAcV/worktrees/3f9aad1/solver_equiv_01/results/solver_equiv_01/20260727_090000\n",
    )
    mock_ex.when_ssh("cat ").returns(
        0, _status_json("FAIL_NUMERICAL", error_msg="LSODA failed") + "\n"
    )

    resp = run_status(TASK, executor=mock_ex)
    assert resp.status == StatusEnum.FAIL
    assert resp.fail_type.value == "numerical"
