"""Tests for the Gate A6 objective-profile runner."""

import importlib
import importlib.util
import json

import pytest


EXPECTED_PARAMETERS = ("k0_1", "k0_2", "k0_3", "G_OH", "G_O")
EXPECTED_MODES = ("legacy", "complex_snr", "lockin_only", "hybrid")


def _runner():
    assert importlib.util.find_spec("scripts.run_objective_profiles") is not None
    return importlib.import_module("scripts.run_objective_profiles")


def test_default_formal_plan_uses_frozen_profile_contract(tmp_path):
    runner = _runner()
    args = runner.parse_args(["--output", str(tmp_path / "profiles")])

    tasks = runner.build_profile_tasks(args)
    config = runner.build_config(args, feature_mode="hybrid")

    assert config.n_points == 8192
    assert config.points_per_cycle == 32
    assert config.feature_grid_size == 128
    assert config.solver_backend == "lsoda"
    assert config.feature_mode == "hybrid"
    assert len(tasks) == 20
    assert {task["parameter"] for task in tasks} == set(EXPECTED_PARAMETERS)
    assert {task["feature_mode"] for task in tasks} == set(EXPECTED_MODES)
    assert {task["truth_id"] for task in tasks} == {"mixed_b"}
    assert {task["grid_points"] for task in tasks} == {41}
    assert {task["noise_fraction"] for task in tasks} == {0.0}


def test_profile_problem_varies_one_parameter_and_fixes_truth_complement(tmp_path):
    runner = _runner()
    args = runner.parse_args(
        ["--output", str(tmp_path / "profiles"), "--smoke"]
    )
    task = next(
        task
        for task in runner.build_profile_tasks(args)
        if task["parameter"] == "k0_3" and task["feature_mode"] == "legacy"
    )

    config, spec, grid = runner.build_profile_problem(task, smoke=True)

    assert spec[0] == "k0_3"
    assert dict(config.fixed_params) == {
        name: value
        for name, value in task["truth_params"].items()
        if name != "k0_3"
    }
    assert grid[0] == pytest.approx(0.0)
    assert grid[-1] == pytest.approx(1.0)
    assert sum(value == pytest.approx(task["truth_coordinate"]) for value in grid) == 1


def test_smoke_profile_executes_truth_and_records_components(tmp_path):
    runner = _runner()
    args = runner.parse_args(
        [
            "--output",
            str(tmp_path / "profiles"),
            "--grid-points",
            "3",
            "--smoke",
            "--max-profiles",
            "1",
        ]
    )
    task = runner.build_profile_tasks(args)[0]

    result = runner.run_profile(task, smoke=True)

    assert result["summary"]["truth_is_global_minimum"] is True
    assert result["summary"]["truth_loss"] == pytest.approx(0.0, abs=1e-12)
    assert len(result["rows"]) == 4
    assert sum(row["is_truth"] for row in result["rows"]) == 1
    assert set(runner.COMPONENT_KEYS) <= set(result["rows"][0])


def test_smoke_main_writes_hashed_profile_outputs(tmp_path):
    runner = _runner()
    output = tmp_path / "profiles"

    runner.main(
        [
            "--output",
            str(output),
            "--grid-points",
            "3",
            "--workers",
            "1",
            "--smoke",
            "--max-profiles",
            "1",
        ]
    )

    manifest = json.loads((output / "run_manifest.json").read_text())
    summary = json.loads((output / "profile_summary.json").read_text())
    assert (output / "profile_rows.csv").is_file()
    assert manifest["configuration"]["solver_backend"] == "lsoda"
    assert manifest["configuration"]["noise_fraction"] == 0.0
    assert set(manifest["sha256"]) == {
        "profile_rows.csv",
        "profile_summary.json",
    }
    assert summary["completed_profiles"] == 1
    assert summary["expected_profiles"] == 1
    assert summary["configuration"] == {
        "n_points": 256,
        "points_per_cycle": 32,
        "feature_grid_size": 128,
        "fit_harmonics": [1, 2, 3],
        "feature_modes": list(EXPECTED_MODES),
        "profile_parameters": list(EXPECTED_PARAMETERS),
        "truth_id": "mixed_b",
        "grid_points": 3,
        "solver_backend": "lsoda",
        "noise_fraction": 0.0,
        "workers": 1,
        "smoke": True,
    }
