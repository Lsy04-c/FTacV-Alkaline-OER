"""Unit tests for wf run."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from oer_wf.commands.run import run_run
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
        "smoke": {"enabled": True, "overrides": {"n_samples": 2}},
    }
    p = tmp_path / "spec.yaml"
    p.write_text(yaml.dump(data), encoding="utf-8")
    return p


def test_run_requires_lock(mock_ex: MockExecutor, sample_spec: Path) -> None:
    mock_ex.when_ssh(".wf_lock").returns(0, "MISSING\n")
    resp = run_run(sample_spec, executor=mock_ex, skip_smoke=True)
    assert resp.status == StatusEnum.FAIL
    assert "prepare" in resp.next_action


def test_run_requires_smoke(mock_ex: MockExecutor, sample_spec: Path) -> None:
    mock_ex.when_ssh(".wf_lock").returns(
        0,
        '{"task_id":"3f9aad1/solver_equiv_01","task_name":"solver_equiv_01",'
        '"spec_hash":"sha256:x","commit":"3f9aad1","created_at":"t","worktree_path":"/w"}\n',
    )
    mock_ex.when_ssh("_smoke_").returns(0, "DONE\n")  # no OK:
    resp = run_run(sample_spec, executor=mock_ex, skip_smoke=False)
    assert resp.status == StatusEnum.FAIL
    assert "smoke" in resp.next_action.lower() or "smoke" in resp.message.lower()


def test_run_rejects_active_unit(mock_ex: MockExecutor, sample_spec: Path) -> None:
    mock_ex.when_ssh(".wf_lock").returns(
        0,
        '{"task_id":"3f9aad1/solver_equiv_01","task_name":"solver_equiv_01",'
        '"spec_hash":"sha256:x","commit":"3f9aad1","created_at":"t","worktree_path":"/w"}\n',
    )
    mock_ex.when_ssh("systemctl").returns(
        0,
        "LoadState=loaded\nActiveState=active\nSubState=running\nMainPID=42\n"
        "Result=success\nExecMainStatus=0\n",
    )
    resp = run_run(sample_spec, executor=mock_ex, skip_smoke=True)
    assert resp.status == StatusEnum.RUNNING
    assert "already active" in resp.message


def test_run_rejects_inactive_without_force(
    mock_ex: MockExecutor, sample_spec: Path
) -> None:
    mock_ex.when_ssh(".wf_lock").returns(
        0,
        '{"task_id":"3f9aad1/solver_equiv_01","task_name":"solver_equiv_01",'
        '"spec_hash":"sha256:x","commit":"3f9aad1","created_at":"t","worktree_path":"/w"}\n',
    )
    mock_ex.when_ssh("systemctl").returns(
        0,
        "LoadState=loaded\nActiveState=failed\nSubState=failed\nMainPID=0\n"
        "Result=exit-code\nExecMainStatus=1\n",
    )
    resp = run_run(sample_spec, force=False, executor=mock_ex, skip_smoke=True)
    assert resp.status == StatusEnum.FAIL
    assert "--force" in resp.next_action or "clean" in resp.next_action


def test_run_starts_with_force(mock_ex: MockExecutor, sample_spec: Path) -> None:
    mock_ex.when_ssh(".wf_lock").returns(
        0,
        '{"task_id":"3f9aad1/solver_equiv_01","task_name":"solver_equiv_01",'
        '"spec_hash":"sha256:x","commit":"3f9aad1","created_at":"t","worktree_path":"/w"}\n',
    )
    mock_ex.when_ssh("systemctl --user show").returns(
        0,
        "LoadState=loaded\nActiveState=inactive\nSubState=dead\nMainPID=0\n"
        "Result=success\nExecMainStatus=0\n",
    )
    mock_ex.when_ssh("test -d").returns(0, "yes\n")
    mock_ex.when_ssh("mkdir -p").returns(0, "OK\n")
    mock_ex.when_ssh("base64").returns(0, "OK\n")
    mock_ex.when_ssh("daemon-reload").returns(0, "OK\n")
    mock_ex.when_ssh("systemctl --user start").returns(0, "STARTED\n")

    resp = run_run(sample_spec, force=True, executor=mock_ex, skip_smoke=True)
    assert resp.status == StatusEnum.PASS
    assert resp.data.get("force") is True
    assert "output_dir" in resp.data
    assert resp.data.get("wrapped") is True


def test_run_rejects_resume_for_task_without_support(
    mock_ex: MockExecutor, sample_spec: Path
) -> None:
    resp = run_run(
        sample_spec,
        resume_timestamp="20260729_010203",
        executor=mock_ex,
        skip_smoke=True,
    )

    assert resp.status == StatusEnum.FAIL
    assert "resume" in resp.message.lower()


def test_run_resume_reuses_exact_timestamp_directory(
    mock_ex: MockExecutor, sample_spec: Path
) -> None:
    data = yaml.safe_load(sample_spec.read_text())
    data["supports_resume"] = True
    sample_spec.write_text(yaml.safe_dump(data))
    mock_ex.when_ssh(".wf_lock").returns(
        0,
        '{"task_id":"3f9aad1/solver_equiv_01","task_name":"solver_equiv_01",'
        '"spec_hash":"sha256:x","commit":"3f9aad1","created_at":"t","worktree_path":"/w"}\n',
    )
    mock_ex.when_ssh("systemctl --user show").returns(
        0,
        "LoadState=loaded\nActiveState=failed\nSubState=failed\nMainPID=0\n"
        "Result=exit-code\nExecMainStatus=1\n",
    )
    mock_ex.when_ssh("&& echo yes || echo no").returns(0, "yes\n")
    mock_ex.when_ssh("job_plan.json").returns(0, "OK\n")
    mock_ex.when_ssh("base64").returns(0, "OK\n")
    mock_ex.when_ssh("daemon-reload").returns(0, "OK\n")
    mock_ex.when_ssh("systemctl --user start").returns(0, "STARTED\n")

    resp = run_run(
        sample_spec,
        resume_timestamp="20260729_010203",
        executor=mock_ex,
        skip_smoke=True,
    )

    assert resp.status == StatusEnum.PASS
    assert resp.data["resumed"] is True
    assert resp.data["output_rel"].endswith("20260729_010203")
    assert "--resume" in resp.data["command"]


def test_run_rejects_resume_with_force_or_invalid_timestamp(
    mock_ex: MockExecutor, sample_spec: Path
) -> None:
    data = yaml.safe_load(sample_spec.read_text())
    data["supports_resume"] = True
    sample_spec.write_text(yaml.safe_dump(data))

    with_force = run_run(
        sample_spec,
        force=True,
        resume_timestamp="20260729_010203",
        executor=mock_ex,
        skip_smoke=True,
    )
    invalid = run_run(
        sample_spec,
        resume_timestamp="../old",
        executor=mock_ex,
        skip_smoke=True,
    )

    assert with_force.status == StatusEnum.FAIL
    assert invalid.status == StatusEnum.FAIL
