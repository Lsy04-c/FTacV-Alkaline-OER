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
        args=["--config", "cfg.yaml"],
        workers=4,
        output_dir="results/solver_equiv_01",
        smoke={"enabled": True, "overrides": {"n_samples": 2, "max_steps": 50}},
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
    assert "--n_samples" in plan.argv
    assert "2" in plan.argv
    assert "--max_steps" in plan.argv
    assert plan.argv[-4] == "--output"
    assert plan.argv[-2] == "--workers"
