"""Unit tests for wf doctor."""

from __future__ import annotations

from datetime import datetime, timezone

from oer_wf.commands.doctor import run_doctor
from oer_wf.models import StatusEnum
from oer_wf.transport import MockExecutor


def test_doctor_all_pass(mock_ex: MockExecutor) -> None:
    # Match local UTC so clock-skew check passes
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    mock_ex.when_ssh("whoami").returns(0, "lsy\nLinux\n5.15.0\n")
    mock_ex.when_ssh("date -u").returns(0, now + "\n")
    mock_ex.when_ssh("test -d").returns(0, "yes\n")
    mock_ex.when_ssh("git rev-parse").returns(0, "3f9aad1\n")
    mock_ex.when_ssh("test -x").returns(0, "Python 3.11.7\n")
    mock_ex.when_ssh("command -v rsync").returns(
        0, "/usr/bin/rsync\nrsync  version 3.2.7\n"
    )
    mock_ex.when_ssh("command -v systemctl").returns(0, "running\n")

    resp = run_doctor(executor=mock_ex)
    assert resp.status in (StatusEnum.PASS, StatusEnum.WARNING)
    assert resp.next_action.startswith("wf prepare")
    assert any(c.name == "ssh_wsl" and c.passed for c in resp.checks)


def test_doctor_ssh_fail(mock_ex: MockExecutor) -> None:
    mock_ex.when_ssh("whoami").returns(1, "", "Connection refused")
    resp = run_doctor(executor=mock_ex)
    assert resp.status == StatusEnum.FAIL
    assert resp.fail_type.value == "environment"
