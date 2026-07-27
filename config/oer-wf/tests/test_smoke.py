"""Unit tests for wf smoke."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from oer_wf.commands.smoke import run_smoke, _check_forbidden_overrides
from oer_wf.models import StatusEnum
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
        "smoke": {
            "enabled": True,
            "overrides": {"n_samples": 2, "max_steps": 50},
            "expected_files": ["summary.csv", "manifest.json"],
        },
    }
    p = tmp_path / "spec.yaml"
    p.write_text(yaml.dump(data), encoding="utf-8")
    return p


def test_forbidden_overrides() -> None:
    assert _check_forbidden_overrides({"n_samples": 2}) == []
    bad = _check_forbidden_overrides({"solver": "x", "n_samples": 1})
    assert any("solver" in b for b in bad)


def test_smoke_rejects_scientific_override(
    mock_ex: MockExecutor, tmp_path: Path
) -> None:
    data = {
        "task_name": "solver_equiv_01",
        "commit": "3f9aad1abcdef",
        "script": "scripts/run.py",
        "args": [],
        "workers": 1,
        "output_dir": "results/x",
        "smoke": {
            "enabled": True,
            "overrides": {"solver": "lsoda"},
            "expected_files": ["summary.csv"],
        },
    }
    p = tmp_path / "bad.yaml"
    p.write_text(yaml.dump(data), encoding="utf-8")
    resp = run_smoke(p, executor=mock_ex, timeout_sec=1)
    assert resp.status == StatusEnum.FAIL
    assert resp.fail_type.value == "scientific"


def test_smoke_requires_lock(mock_ex: MockExecutor, sample_spec: Path) -> None:
    mock_ex.when_ssh(".wf_lock").returns(0, "MISSING\n")
    resp = run_smoke(sample_spec, executor=mock_ex, timeout_sec=1)
    assert resp.status == StatusEnum.FAIL
    assert "prepare" in resp.next_action


def test_smoke_success_path(mock_ex: MockExecutor, sample_spec: Path) -> None:
    mock_ex.when_ssh(".wf_lock").returns(
        0,
        '{"task_id":"3f9aad1/solver_equiv_01","task_name":"solver_equiv_01",'
        '"spec_hash":"sha256:x","commit":"3f9aad1","created_at":"t","worktree_path":"/w"}\n',
    )
    mock_ex.when_ssh("systemctl --user show").returns(
        0,
        "LoadState=not-found\nActiveState=inactive\nSubState=dead\nMainPID=0\n"
        "Result=\nExecMainStatus=0\n",
    )
    mock_ex.when_ssh("mkdir -p").returns(0, "OK\n")
    mock_ex.when_ssh("base64").returns(0, "OK\n")
    mock_ex.when_ssh("daemon-reload").returns(0, "OK\n")
    mock_ex.when_ssh("systemctl --user start").returns(0, "RC:0\n")
    # Register broad matchers carefully: test -f before cat, so paths that
    # contain STATUS.json do not get the JSON body as the test -f result.
    mock_ex.when_ssh("test -f").returns(0, "yes\n")
    mock_ex.when_ssh("head -1").returns(0, "col_a,col_b\n")

    status_body = json.dumps(
        {
            "status": "SUCCESS",
            "exit_code": 0,
            "pid": 1,
            "started_at": "2026-07-27T09:00:00Z",
            "finished_at": "2026-07-27T09:00:01Z",
            "commit": "3f9aad1",
            "task_id": "3f9aad1/solver_equiv_01",
            "command": [],
            "output_dir": "/out",
            "error_msg": None,
            "extra": {},
        }
    )
    mock_ex.when_ssh("cat ").returns(0, status_body + "\n")

    resp = run_smoke(sample_spec, executor=mock_ex, timeout_sec=5, poll_interval=0.01)
    assert resp.status in (StatusEnum.PASS, StatusEnum.WARNING)
    assert "run" in resp.next_action
    assert resp.data.get("overrides", {}).get("n_samples") == 2
