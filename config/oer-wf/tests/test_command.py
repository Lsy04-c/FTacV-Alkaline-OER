"""Tests for shared command construction."""

from __future__ import annotations

from pathlib import Path

import pytest

from oer_wf.models import TaskSpec
from oer_wf.runtime.command import build_command, make_output_dir


@pytest.fixture
def spec() -> TaskSpec:
    return TaskSpec(
        task_name="solver_equiv_01",
        commit="3f9aad1abcdef",
        script="scripts/run.py",
        args=["--config", "cfg.yaml", "--trials", "100"],
        workers=4,
        output_dir="results/solver_equiv_01",
        smoke={
            "enabled": True,
            "args": ["--smoke"],
            "overrides": {
                "trials": 5,
                "max_jobs": 1,
                "verbose": True,
                "disabled": False,
                "unset": None,
            },
        },
    )


def test_make_output_dir_formal(tmp_path: Path) -> None:
    out = make_output_dir(tmp_path, "results/x", is_smoke=False, timestamp="20260727_120000")
    assert out.name == "20260727_120000"
    assert out.parent.name == "x"
    assert out.is_dir()


def test_make_output_dir_smoke(tmp_path: Path) -> None:
    out = make_output_dir(tmp_path, "results/x", is_smoke=True, timestamp="20260727_120000")
    assert out.name == "_smoke_20260727_120000"
    assert out.is_dir()


def test_build_command_injects_output_workers(spec: TaskSpec, tmp_path: Path) -> None:
    main = tmp_path / "main"
    wt = tmp_path / "wt"
    main.mkdir()
    wt.mkdir()
    (wt / "scripts").mkdir()
    (wt / "scripts" / "run.py").write_text("# noop\n")
    # fake venv python
    venv = main / ".venv" / "bin"
    venv.mkdir(parents=True)
    (venv / "python").write_text("#!/bin/true\n")

    out = make_output_dir(wt, spec.output_dir, timestamp="20260727_120000")
    plan = build_command(spec, main_repo=main, worktree=wt, output_dir=out, is_smoke=False)

    assert plan.argv[-4:] == ["--output", str(out), "--workers", "4"]
    assert "--config" in plan.argv
    assert plan.is_smoke is False
    assert plan.task_id == "3f9aad1/solver_equiv_01"


def test_build_command_smoke_overrides(spec: TaskSpec, tmp_path: Path) -> None:
    main = tmp_path / "main"
    wt = tmp_path / "wt"
    main.mkdir()
    wt.mkdir()
    (wt / "scripts").mkdir()
    (wt / "scripts" / "run.py").write_text("# noop\n")
    venv = main / ".venv" / "bin"
    venv.mkdir(parents=True)
    (venv / "python").write_text("#!/bin/true\n")

    out = make_output_dir(wt, spec.output_dir, is_smoke=True, timestamp="20260727_120000")
    plan = build_command(spec, main_repo=main, worktree=wt, output_dir=out, is_smoke=True)

    assert plan.is_smoke is True
    assert "--smoke" in plan.argv
    trial_indexes = [i for i, value in enumerate(plan.argv) if value == "--trials"]
    assert [plan.argv[i + 1] for i in trial_indexes] == ["100", "5"]
    assert plan.argv[plan.argv.index("--max_jobs") + 1] == "1"
    assert "--verbose" in plan.argv
    assert "True" not in plan.argv
    assert "--disabled" not in plan.argv
    assert "--unset" not in plan.argv
    assert plan.argv[-4] == "--output"
    assert plan.argv[-2] == "--workers"


def test_build_command_formal_keeps_formal_budget(spec: TaskSpec, tmp_path: Path) -> None:
    main = tmp_path / "main"
    wt = tmp_path / "wt"
    main.mkdir()
    wt.mkdir()
    out = make_output_dir(wt, spec.output_dir, timestamp="20260727_120000")

    plan = build_command(spec, main_repo=main, worktree=wt, output_dir=out)

    assert "--smoke" not in plan.argv
    assert plan.argv[plan.argv.index("--trials") + 1] == "100"
    assert "--max_jobs" not in plan.argv
