"""Shared validator dispatch tests."""

from __future__ import annotations

from pathlib import Path

from oer_wf.models import CheckResult
import oer_wf.validator_runner as runner


def test_runtime_config_is_removed_before_validator_call(
    tmp_path: Path,
    monkeypatch,
) -> None:
    seen = {}

    def probe(archive, expected, *, validator_config):
        seen["archive"] = archive
        seen["expected"] = expected
        seen["config"] = validator_config
        return [CheckResult(name="probe", passed=True)]

    monkeypatch.setitem(runner.VALIDATOR_MAP, "probe", probe)

    execution, timeout, checks = runner.run_validator(
        "probe",
        tmp_path,
        ["STATUS.json"],
        {
            "execution": "remote_worktree",
            "timeout_sec": 321,
            "threshold": 0.5,
        },
    )

    assert execution == "remote_worktree"
    assert timeout == 321
    assert seen["config"] == {"threshold": 0.5}
    assert checks == [CheckResult(name="probe", passed=True)]


def test_unknown_validator_returns_structure_check(tmp_path: Path) -> None:
    execution, timeout, checks = runner.run_validator(
        "missing",
        tmp_path,
        [],
        {},
    )

    assert execution == "local"
    assert timeout == 600
    assert len(checks) == 1
    assert checks[0].name == "structure:missing"
    assert checks[0].passed is False
