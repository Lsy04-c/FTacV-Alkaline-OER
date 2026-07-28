"""Tests for the frozen Gate A6 optimizer-development protocol."""

from __future__ import annotations

from typing import Any

import json
import numpy as np
import pytest

from oer_aem.optimizer_benchmark import (
    DEVELOPMENT_OPTIMIZERS,
    build_development_jobs,
    run_benchmark_job,
    select_development_candidate,
)
from scripts import run_optimizer_benchmark as benchmark_runner


def _development_rows(
    *,
    sobol_errors: list[float],
    de_errors: list[float],
) -> list[dict[str, Any]]:
    jobs = build_development_jobs(
        noise_fraction=0.001495726085983469
    )
    error_by_optimizer = {
        "tpe": [0.10, 0.10, 0.10],
        "sobol_pattern": sobol_errors,
        "de_fixed": de_errors,
    }
    pair_index = {
        ("k0_2", "k0_3"): 0,
        ("k0_2", "G_O"): 1,
        ("k0_3", "G_O"): 2,
    }
    rows = []
    for job in jobs:
        error = error_by_optimizer[job["optimizer"]][
            pair_index[tuple(job["free_parameters"])]
        ]
        parameter_metrics = {
            name: {
                "normalized_bound_error": error,
                "boundary_hit": False,
            }
            for name in job["free_parameters"]
        }
        parameter_metrics["boundary_hits"] = []
        parameter_metrics["max_normalized_bound_error"] = error
        rows.append(
            {
                **job,
                "success": True,
                "optimization_calls": 100,
                "n_ode_fail": 0,
                "best_objective": 0.01 + error,
                "truth_objective": 0.01,
                "parameter_metrics": parameter_metrics,
            }
        )
    return rows


def test_development_matrix_is_preregistered() -> None:
    jobs = build_development_jobs(
        noise_fraction=0.001495726085983469
    )

    assert len(jobs) == 9
    assert {job["optimizer"] for job in jobs} == {
        "tpe",
        "sobol_pattern",
        "de_fixed",
    }
    assert tuple(job["optimizer"] for job in jobs[:3]) == (
        *DEVELOPMENT_OPTIMIZERS,
    )
    assert {job["truth_id"] for job in jobs} == {"center"}
    assert {job["noise_fraction"] for job in jobs} == {0.0}
    assert {job["seed"] for job in jobs} == {7}
    assert {tuple(job["free_parameters"]) for job in jobs} == {
        ("k0_2", "k0_3"),
        ("k0_2", "G_O"),
        ("k0_3", "G_O"),
    }


def test_selection_requires_all_three_pairs_to_pass() -> None:
    rows = _development_rows(
        sobol_errors=[0.01, 0.02, 0.03],
        de_errors=[0.01, 0.02, 0.06],
    )

    selection = select_development_candidate(rows)

    assert selection["selected_optimizer"] == "sobol_pattern"
    assert selection["eligible_optimizers"] == ["sobol_pattern"]


def test_no_candidate_stops_confirmation() -> None:
    rows = _development_rows(
        sobol_errors=[0.06, 0.02, 0.03],
        de_errors=[0.01, 0.07, 0.03],
    )

    selection = select_development_candidate(rows)

    assert selection["selected_optimizer"] is None
    assert selection["scientific_gate_passed"] is False
    assert selection["next_action"] == "STOP"


def test_selection_tie_prefers_sobol_pattern() -> None:
    rows = _development_rows(
        sobol_errors=[0.01, 0.02, 0.03],
        de_errors=[0.01, 0.02, 0.03],
    )

    selection = select_development_candidate(rows)

    assert selection["eligible_optimizers"] == [
        "sobol_pattern",
        "de_fixed",
    ]
    assert selection["selected_optimizer"] == "sobol_pattern"


def test_job_execution_keeps_truth_diagnostic_after_optimization() -> None:
    job = build_development_jobs(noise_fraction=0.2)[0]
    events: list[tuple[str, Any]] = []

    def objective_factory(received_job):
        assert received_job is job

        def optimization(unit) -> float:
            values = np.asarray(unit, dtype=float)
            events.append(("optimization", tuple(values)))
            return float(np.sum((values - 0.5) ** 2))

        def truth_diagnostic() -> float:
            events.append(("truth", None))
            return 0.0

        return optimization, truth_diagnostic

    row = run_benchmark_job(job, objective_factory=objective_factory)

    assert row["optimization_calls"] == 100
    assert row["diagnostic_truth_calls"] == 1
    assert len(row["evaluations"]) == 100
    assert [kind for kind, _ in events[:100]] == ["optimization"] * 100
    assert events[100:] == [("truth", None)]


def _fake_successful_row(job):
    row = _development_rows(
        sobol_errors=[0.01, 0.01, 0.01],
        de_errors=[0.02, 0.02, 0.02],
    )
    template = next(item for item in row if item["job_id"] == job["job_id"])
    return {
        **template,
        "diagnostic_truth_calls": 1,
        "evaluations": [
            {
                "index": index,
                "phase": "test",
                "unit": [0.5, 0.5],
                "loss": 0.01,
                "error": None,
            }
            for index in range(1, 101)
        ],
    }


def _read_jsonl(path):
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
    ]


def _base_args(output):
    return [
        "--phase",
        "development",
        "--backend",
        "cn",
        "--budget",
        "100",
        "--workers",
        "1",
        "--output",
        str(output),
    ]


def test_runner_writes_complete_development_artifacts(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setattr(
        benchmark_runner,
        "validate_backend",
        lambda backend: None,
    )
    monkeypatch.setattr(
        benchmark_runner,
        "run_benchmark_job",
        lambda job, **kwargs: _fake_successful_row(job),
    )
    output = tmp_path / "run"

    benchmark_runner.main(_base_args(output))

    assert {path.name for path in output.iterdir()} == {
        "benchmark_plan.json",
        "results.jsonl",
        "evaluations.jsonl",
        "summary.json",
        "selection.json",
    }
    assert len(_read_jsonl(output / "results.jsonl")) == 9
    assert len(_read_jsonl(output / "evaluations.jsonl")) == 900
    summary = json.loads((output / "summary.json").read_text())
    assert summary["optimization_calls"] == 900
    assert summary["diagnostic_truth_calls"] == 9


def test_smoke_preserves_budget_and_disables_scientific_selection(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setattr(
        benchmark_runner,
        "validate_backend",
        lambda backend: None,
    )
    monkeypatch.setattr(
        benchmark_runner,
        "run_benchmark_job",
        lambda job, **kwargs: _fake_successful_row(job),
    )
    output = tmp_path / "smoke"

    benchmark_runner.main(
        [*_base_args(output), "--smoke", "--max-jobs", "3"]
    )

    plan = json.loads((output / "benchmark_plan.json").read_text())
    selection = json.loads((output / "selection.json").read_text())
    assert plan["is_smoke"] is True
    assert {job["budget"] for job in plan["jobs"]} == {100}
    assert len(plan["jobs"]) == 3
    assert selection == {
        "scientific_gate_passed": None,
        "selected_optimizer": None,
        "next_action": "RUN_FORMAL_DEVELOPMENT",
    }


def test_resume_reuses_only_matching_job_hashes(
    monkeypatch,
    tmp_path,
) -> None:
    calls = []
    monkeypatch.setattr(
        benchmark_runner,
        "validate_backend",
        lambda backend: None,
    )

    def fake_run(job, **kwargs):
        calls.append(job["job_id"])
        return _fake_successful_row(job)

    monkeypatch.setattr(benchmark_runner, "run_benchmark_job", fake_run)
    output = tmp_path / "resume"
    benchmark_runner.main(_base_args(output))
    calls.clear()

    benchmark_runner.main([*_base_args(output), "--resume"])

    assert calls == []


def test_resume_rejects_optimizer_or_budget_drift(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setattr(
        benchmark_runner,
        "validate_backend",
        lambda backend: None,
    )
    monkeypatch.setattr(
        benchmark_runner,
        "run_benchmark_job",
        lambda job, **kwargs: _fake_successful_row(job),
    )
    output = tmp_path / "resume"
    benchmark_runner.main(_base_args(output))
    plan_path = output / "benchmark_plan.json"
    plan = json.loads(plan_path.read_text())
    plan["budget"] = 101
    plan_path.write_text(json.dumps(plan))

    with pytest.raises(ValueError, match="resume_fingerprint mismatch"):
        benchmark_runner.main([*_base_args(output), "--resume"])
