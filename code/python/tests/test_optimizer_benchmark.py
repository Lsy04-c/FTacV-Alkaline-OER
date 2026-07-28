"""Tests for the frozen Gate A6 optimizer-development protocol."""

from __future__ import annotations

from typing import Any

import numpy as np

from oer_aem.optimizer_benchmark import (
    DEVELOPMENT_OPTIMIZERS,
    build_development_jobs,
    run_benchmark_job,
    select_development_candidate,
)


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
