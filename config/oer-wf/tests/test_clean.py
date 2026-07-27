"""Unit tests for wf clean."""

from __future__ import annotations

from oer_wf.commands.clean import run_clean
from oer_wf.models import StatusEnum
from oer_wf.transport import MockExecutor


def test_clean_soft(mock_ex: MockExecutor) -> None:
    mock_ex.when_ssh("systemctl").returns(0, "done\n")
    mock_ex.when_ssh("rm -f").returns(0, "done\n")
    mock_ex.when_ssh("test -d").returns(0, "yes\n")
    mock_ex.when_ssh("rm -f ").returns(0, "done\n")  # soft clean

    resp = run_clean("3f9aad1/solver_equiv_01", force=False, executor=mock_ex)
    assert resp.status == StatusEnum.PASS
    assert resp.data.get("force") is False


def test_clean_force(mock_ex: MockExecutor) -> None:
    mock_ex.when_ssh("systemctl").returns(0, "done\n")
    mock_ex.when_ssh("rm -f").returns(0, "done\n")
    mock_ex.when_ssh("test -d").returns(0, "yes\n")
    mock_ex.when_ssh("git worktree remove").returns(0, "done\n")
    resp = run_clean("3f9aad1/solver_equiv_01", force=True, executor=mock_ex)
    assert resp.status == StatusEnum.PASS
    assert resp.data.get("force") is True
    assert any("worktree removed" in a for a in resp.data.get("actions", []))


def test_clean_force_keep_results(mock_ex: MockExecutor) -> None:
    """--force --keep-results: copy results to _wf_preserved_results/ first."""
    mock_ex.when_ssh("systemctl").returns(0, "done\n")
    mock_ex.when_ssh("rm -f").returns(0, "done\n")
    mock_ex.when_ssh("test -d").returns(0, "yes\n")
    mock_ex.when_ssh("cp -a").returns(0, "done\n")  # copy succeeds
    mock_ex.when_ssh("diff -rq").returns(0, "")       # verification passes
    mock_ex.when_ssh("git worktree remove").returns(0, "done\n")
    resp = run_clean("3f9aad1/solver_equiv_01", force=True, keep_results=True, executor=mock_ex)
    assert resp.status == StatusEnum.PASS
    assert resp.data.get("keep_results") is True
    assert any("preserved" in a for a in resp.data.get("actions", []))


def test_clean_force_keep_results_copy_fails(mock_ex: MockExecutor) -> None:
    """--force --keep-results: copy failure must refuse deletion."""
    mock_ex.when_ssh("systemctl").returns(0, "done\n")
    mock_ex.when_ssh("rm -f").returns(0, "done\n")
    mock_ex.when_ssh("test -d").returns(0, "yes\n")
    mock_ex.when_ssh("cp -a").returns(1, "cp: cannot stat...\n")  # copy FAILS
    resp = run_clean("3f9aad1/solver_equiv_01", force=True, keep_results=True, executor=mock_ex)
    assert resp.status == StatusEnum.FAIL
    assert "refusing" in resp.message.lower() or "preserv" in resp.message.lower()


def test_clean_invalid_task_id(mock_ex: MockExecutor) -> None:
    """Invalid task_id format should fail immediately."""
    resp = run_clean("bad-format", force=False, executor=mock_ex)
    assert resp.status == StatusEnum.FAIL


def test_clean_nonexistent_worktree(mock_ex: MockExecutor) -> None:
    """Cleaning a non-existent worktree should return OK (idempotent)."""
    mock_ex.when_ssh("systemctl").returns(0, "done\n")
    mock_ex.when_ssh("rm -f").returns(0, "done\n")
    mock_ex.when_ssh("test -d").returns(0, "no\n")
    resp = run_clean("3f9aad1/solver_equiv_01", force=False, executor=mock_ex)
    assert resp.status == StatusEnum.PASS
