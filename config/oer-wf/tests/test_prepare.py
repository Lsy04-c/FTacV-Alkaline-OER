"""Unit tests for wf prepare."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from oer_wf.commands.prepare import run_prepare
from oer_wf.models import StatusEnum, TaskSpec
from oer_wf.transport import MockExecutor


@pytest.fixture
def sample_spec(tmp_path: Path) -> Path:
    data = {
        "task_name": "solver_equiv_01",
        "commit": "3f9aad1abcdef",
        "description": "test",
        "python": {"source": "main_repo", "path": ".venv/bin/python"},
        "script": "scripts/run.py",
        "args": ["--config", "cfg.yaml"],
        "workers": 2,
        "output_dir": "results/solver_equiv_01",
    }
    p = tmp_path / "spec.yaml"
    p.write_text(yaml.dump(data), encoding="utf-8")
    return p


def test_prepare_create(mock_ex: MockExecutor, sample_spec: Path) -> None:
    # worktree does not exist
    mock_ex.when_ssh("test -d").returns(0, "no\n")
    # commit exists
    mock_ex.when_ssh("git rev-parse").returns(0, "ok\n")
    # worktree add succeeds
    mock_ex.when_ssh("git worktree add").returns(0, "")
    # lock write succeeds
    mock_ex.when_ssh("base64").returns(0, "")

    resp = run_prepare(sample_spec, executor=mock_ex)
    assert resp.status == StatusEnum.PASS
    assert resp.data.get("action") == "create"
    assert "3f9aad1/solver_equiv_01" in resp.data.get("task_id", "")


def test_prepare_conflict(mock_ex: MockExecutor, sample_spec: Path) -> None:
    mock_ex.when_ssh("test -d").returns(0, "yes\n")
    # existing lock with different hash
    lock_json = (
        '{"task_id":"3f9aad1/solver_equiv_01","task_name":"solver_equiv_01",'
        '"spec_hash":"sha256:deadbeef","commit":"3f9aad1abcdef",'
        '"created_at":"2026-07-27T00:00:00Z","worktree_path":"/tmp/wt"}'
    )
    mock_ex.when_ssh("cat ").returns(0, lock_json + "\n")

    resp = run_prepare(sample_spec, executor=mock_ex)
    assert resp.status == StatusEnum.FAIL
    assert "spec_hash mismatch" in resp.message
    assert "wf clean --force" in resp.next_action
