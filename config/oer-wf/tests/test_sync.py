"""Unit tests for wf sync."""

from __future__ import annotations

from pathlib import Path

from oer_wf.commands.sync import run_sync
from oer_wf.models import StatusEnum
from oer_wf.transport import MockExecutor
import oer_wf.config as cfg


def test_sync_no_remote(mock_ex: MockExecutor, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(cfg, "MAC_ARCHIVE_ROOT", tmp_path / "archive")
    mock_ex.when_ssh("ls -1d").returns(0, "\n")
    resp = run_sync("3f9aad1/solver_equiv_01", executor=mock_ex)
    assert resp.status == StatusEnum.FAIL
    assert resp.fail_type.value == "transport"


def test_sync_success(mock_ex: MockExecutor, tmp_path: Path, monkeypatch) -> None:
    archive = tmp_path / "archive"
    monkeypatch.setattr(cfg, "MAC_ARCHIVE_ROOT", archive)
    remote = "/home/lsy/OER-FTAcV/worktrees/3f9aad1/solver_equiv_01/results/solver_equiv_01/20260727_120000"
    mock_ex.when_ssh("ls -1d").returns(0, remote + "\n")

    def _rsync(remote_path, local_path, timeout=None):
        # simulate rsync by writing files into local_path
        dest = Path(local_path)
        dest.mkdir(parents=True, exist_ok=True)
        (dest / "STATUS.json").write_text(
            '{"status":"SUCCESS","commit":"3f9aad1","task_id":"3f9aad1/solver_equiv_01","started_at":"t"}'
        )
        (dest / "summary.csv").write_text("a,b\n1,2\n")
        from oer_wf.transport import ExecResult

        return ExecResult(returncode=0, stdout="ok", cmd="rsync")

    mock_ex.rsync_pull = _rsync  # type: ignore

    resp = run_sync("3f9aad1/solver_equiv_01", executor=mock_ex)
    assert resp.status == StatusEnum.PASS
    assert resp.data["file_count"] >= 2
    assert "verify" in resp.next_action
