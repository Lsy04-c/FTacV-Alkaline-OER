"""Unit tests for wf git-check."""

from __future__ import annotations

from oer_wf.commands.git_check import run_git_check, _is_excluded
from oer_wf.models import StatusEnum
from oer_wf.transport import MockExecutor


def test_excluded_patterns() -> None:
    assert _is_excluded("worktrees/abc/t/.wf_lock")
    assert _is_excluded("results/x/_smoke_20260727_120000/summary.csv")
    assert _is_excluded("results/x/20260727_120000/out.csv")
    assert not _is_excluded("scripts/run_solver_equiv.py")
    assert not _is_excluded("configs/solver_equiv.yaml")


def test_git_check_clean(mock_ex: MockExecutor) -> None:
    mock_ex.when_ssh("git rev-parse").returns(0, "main\n3f9aad1\n")
    mock_ex.when_ssh("git diff").returns(0, "")
    mock_ex.when_ssh("pytest").returns(0, "5 passed in 0.1s\n")

    resp = run_git_check(run_tests=True, executor=mock_ex)
    assert resp.status == StatusEnum.PASS
    assert resp.data["branch"] == "main"
    assert resp.data["head"] == "3f9aad1"
    assert resp.data["staged_files"] == []


def test_git_check_with_changes(mock_ex: MockExecutor) -> None:
    porcelain = (
        "main\n"
        "3f9aad1\n"
        " M scripts/run.py\n"
        "?? configs/new.yaml\n"
        "?? worktrees/abc/t/.wf_lock\n"
        " M results/x/20260727_120000/summary.csv\n"
    )
    mock_ex.when_ssh("git rev-parse").returns(0, porcelain)
    mock_ex.when_ssh("git diff").returns(0, " scripts/run.py | 2 +-\n 1 file changed\n")
    mock_ex.when_ssh("pytest").returns(0, "3 passed in 0.2s\n")

    resp = run_git_check(run_tests=True, executor=mock_ex)
    assert resp.status == StatusEnum.PASS
    assert "scripts/run.py" in resp.data["unstaged_files"]
    assert "configs/new.yaml" in resp.data["untracked_files"]
    assert any(".wf_lock" in p for p in resp.data["excluded_files"])
    assert "commit_message_draft" in resp.data
    assert "人工确认" in resp.next_action or "commit" in resp.next_action.lower()


def test_git_check_pytest_fail(mock_ex: MockExecutor) -> None:
    mock_ex.when_ssh("git rev-parse").returns(0, "main\nabc1234\n M foo.py\n")
    mock_ex.when_ssh("git diff").returns(0, "")
    mock_ex.when_ssh("pytest").returns(1, "1 failed, 2 passed in 0.3s\n")

    resp = run_git_check(run_tests=True, executor=mock_ex)
    assert resp.status == StatusEnum.FAIL
    assert "pytest" in resp.message.lower() or "test" in resp.next_action.lower()
