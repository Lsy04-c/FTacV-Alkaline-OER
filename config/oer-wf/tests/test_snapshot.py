"""Frozen verification runtime contract tests."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from oer_wf.models import TaskSpec
from oer_wf.snapshot import build_snapshot_dict, load_snapshot, snapshot_yaml_text


def _spec(**overrides) -> TaskSpec:
    data = {
        "task_name": "remote_gate",
        "commit": "abcdef1234567890abcdef1234567890abcdef12",
        "python": {"source": "main_repo", "path": ".venv/bin/python"},
        "worktree_root": "worktrees",
        "env": {
            "OMP_NUM_THREADS": "1",
            "OPENBLAS_NUM_THREADS": "1",
        },
        "script": "code/python/scripts/run.py",
        "output_dir": "results/remote_gate",
        "validator_config": {
            "science_gate": {
                "execution": "remote_worktree",
                "timeout_sec": 1800,
            }
        },
    }
    data.update(overrides)
    return TaskSpec.model_validate(data)


def test_snapshot_freezes_verification_runtime() -> None:
    snapshot = build_snapshot_dict(_spec(), is_smoke=False)

    assert snapshot["env"] == {
        "OMP_NUM_THREADS": "1",
        "OPENBLAS_NUM_THREADS": "1",
    }
    assert snapshot["python"] == {
        "source": "main_repo",
        "path": ".venv/bin/python",
    }
    assert snapshot["worktree_root"] == "worktrees"
    assert snapshot["commit"] == "abcdef1234567890abcdef1234567890abcdef12"


@pytest.mark.parametrize(
    "key",
    ["API_TOKEN", "PASSWORD", "CLIENT_SECRET", "PRIVATE_KEY"],
)
def test_task_spec_rejects_secret_like_environment_keys(key: str) -> None:
    with pytest.raises(ValidationError, match="secret-like"):
        _spec(env={key: "must-not-enter-snapshot"})


@pytest.mark.parametrize("execution", ["nearby", "", 7])
def test_task_spec_rejects_invalid_validator_execution(execution) -> None:
    with pytest.raises(ValidationError, match="execution"):
        _spec(
            validator_config={
                "science_gate": {
                    "execution": execution,
                    "timeout_sec": 600,
                }
            }
        )


@pytest.mark.parametrize("timeout", [0, 3601, "slow"])
def test_task_spec_rejects_invalid_validator_timeout(timeout) -> None:
    with pytest.raises(ValidationError, match="timeout_sec"):
        _spec(
            validator_config={
                "science_gate": {
                    "execution": "remote_worktree",
                    "timeout_sec": timeout,
                }
            }
        )


def test_load_snapshot_rejects_remote_runtime_without_frozen_env() -> None:
    text = snapshot_yaml_text(_spec(), is_smoke=False)
    snapshot = load_snapshot(text)
    snapshot.pop("env")

    with pytest.raises(ValueError, match="remote verification snapshot missing"):
        load_snapshot(__import__("yaml").safe_dump(snapshot))


def test_load_snapshot_rejects_invalid_remote_timeout() -> None:
    text = snapshot_yaml_text(_spec(), is_smoke=False)
    snapshot = load_snapshot(text)
    snapshot["validator_config"]["science_gate"]["timeout_sec"] = 0

    with pytest.raises(ValueError, match="timeout_sec"):
        load_snapshot(__import__("yaml").safe_dump(snapshot))
