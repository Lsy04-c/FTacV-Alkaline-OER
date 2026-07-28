"""Tests for the frozen Gate A6 optimizer-development protocol."""

from __future__ import annotations

from typing import Any

import json
import numpy as np
import pytest
from pathlib import Path

from oer_aem.optimizer_benchmark import (
    CONFIRMATION_NOISES,
    CONFIRMATION_SEEDS,
    CONFIRMATION_TRUTHS,
    DEVELOPMENT_OPTIMIZERS,
    build_confirmation_jobs,
    build_development_jobs,
    run_benchmark_job,
    select_development_candidate,
    summarize_confirmation_gate,
)
from scripts import run_optimizer_benchmark as benchmark_runner


ROOT = Path(__file__).resolve().parents[3]


def test_development_evidence_is_frozen_from_accepted_archive() -> None:
    path = (
        ROOT
        / "results"
        / "formal"
        / "identifiability"
        / "gate-a6-optimizer-development"
        / "development_evidence.json"
    )
    evidence = json.loads(path.read_text(encoding="utf-8"))

    assert evidence["selected_optimizer"] == "sobol_pattern"
    assert evidence["source_commit"] == (
        "a5b93f55e540682cc8cddb1fabbe63a7e0e92326"
    )
    assert evidence["source_results_sha256"] == (
        "e93ccab24c4a91d9d4d9a2b8e014826b6b1a07b7d0891c6e7dd944b78e17b432"
    )
    assert len(evidence["development_rows"]) == 3
    assert {
        row["optimization_calls"]
        for row in evidence["development_rows"]
    } == {100}
    assert {
        tuple(row["free_parameters"])
        for row in evidence["development_rows"]
    } == {
        ("k0_2", "k0_3"),
        ("k0_2", "G_O"),
        ("k0_3", "G_O"),
    }


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


def _confirmation_row(job, *, signed_error: float = 0.01):
    error = abs(signed_error)
    parameter_metrics = {
        name: {
            "truth": 1.0,
            "estimate": 1.0 + signed_error,
            "normalized_bound_error": error,
            "boundary_hit": False,
        }
        for name in job["free_parameters"]
    }
    parameter_metrics["boundary_hits"] = []
    parameter_metrics["max_normalized_bound_error"] = error
    return {
        **job,
        "success": True,
        "optimization_calls": 100,
        "diagnostic_truth_calls": 1,
        "truth_diagnostic_sequence": 101,
        "n_ode_fail": 0,
        "n_tafel_fail": 0,
        "best_objective": error,
        "truth_objective": 0.0,
        "parameter_metrics": parameter_metrics,
    }


def test_confirmation_matrix_is_locked_and_excludes_development() -> None:
    jobs = build_confirmation_jobs(
        noise_fraction=0.001495726085983469
    )

    assert len(jobs) == 51
    assert {job["optimizer"] for job in jobs} == {"sobol_pattern"}
    assert {job["budget"] for job in jobs} == {100}
    assert {
        tuple(job["free_parameters"]) for job in jobs
    } == {
        ("k0_2", "k0_3"),
        ("k0_2", "G_O"),
        ("k0_3", "G_O"),
    }
    assert {
        (
            job["truth_id"],
            job["noise_fraction"],
            job["seed"],
        )
        for job in jobs
    } == (
        {
            (truth, noise, seed)
            for truth in CONFIRMATION_TRUTHS
            for noise in CONFIRMATION_NOISES
            for seed in CONFIRMATION_SEEDS
        }
        - {("center", 0.0, 7)}
    )
    assert not any(
        job["truth_id"] == "center"
        and job["noise_fraction"] == 0.0
        and job["seed"] == 7
        for job in jobs
    )


def test_confirmation_gate_applies_v2_per_pair() -> None:
    confirmation = [
        _confirmation_row(job)
        for job in build_confirmation_jobs(
            noise_fraction=0.001495726085983469
        )
    ]
    development_jobs = [
        job
        for job in build_development_jobs()
        if job["optimizer"] == "sobol_pattern"
    ]
    development = [
        _confirmation_row(job) for job in development_jobs
    ]
    failing_pair = ("k0_3", "G_O")
    for row in confirmation:
        if (
            tuple(row["free_parameters"]) == failing_pair
            and row["truth_id"] == "mixed_b"
            and row["noise_fraction"] == CONFIRMATION_NOISES[1]
            and row["seed"] == 27
        ):
            for name in row["free_parameters"]:
                row["parameter_metrics"][name].update(
                    {
                        "estimate": 1.050001,
                        "normalized_bound_error": 0.050001,
                    }
                )
            row["parameter_metrics"][
                "max_normalized_bound_error"
            ] = 0.050001

    gate = summarize_confirmation_gate(development, confirmation)

    assert gate["pair_results"]["k0_2,k0_3"]["passed"] is True
    assert gate["pair_results"]["k0_2,G_O"]["passed"] is True
    assert gate["pair_results"]["k0_3,G_O"]["passed"] is False
    assert gate["eligible_pairs"] == [
        ["k0_2", "k0_3"],
        ["k0_2", "G_O"],
    ]
    assert gate["scientific_gate_passed"] is True


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


def _fake_confirmation_row(job):
    row = _confirmation_row(job)
    return {
        **row,
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


def _confirmation_args(output, evidence):
    return [
        "--phase",
        "confirmation",
        "--backend",
        "cn",
        "--budget",
        "100",
        "--development-evidence",
        str(evidence),
        "--noise-evidence",
        str(
            ROOT
            / "results"
            / "formal"
            / "identifiability"
            / "gate-a6-d9299f8"
            / "noise_evidence.json"
        ),
        "--workers",
        "1",
        "--output",
        str(output),
    ]


def test_confirmation_runner_writes_51_jobs_and_5100_calls(
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
        lambda job, **kwargs: _fake_confirmation_row(job),
    )
    evidence = (
        ROOT
        / "results"
        / "formal"
        / "identifiability"
        / "gate-a6-optimizer-development"
        / "development_evidence.json"
    )
    output = tmp_path / "confirmation"

    benchmark_runner.main(_confirmation_args(output, evidence))

    results = _read_jsonl(output / "results.jsonl")
    evaluations = _read_jsonl(output / "evaluations.jsonl")
    plan = json.loads((output / "benchmark_plan.json").read_text())
    assert len(results) == 51
    assert len(evaluations) == 5100
    assert {row["optimizer"] for row in results} == {"sobol_pattern"}
    assert plan["development_evidence"]["sha256"]
    assert (output / "confirmation_gate.json").is_file()
    assert not (output / "selection.json").exists()


def test_confirmation_runner_smoke_covers_all_parameter_pairs(
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
        lambda job, **kwargs: _fake_confirmation_row(job),
    )
    evidence = (
        ROOT
        / "results"
        / "formal"
        / "identifiability"
        / "gate-a6-optimizer-development"
        / "development_evidence.json"
    )
    output = tmp_path / "confirmation-smoke"

    benchmark_runner.main(
        [
            *_confirmation_args(output, evidence),
            "--smoke",
            "--max-jobs",
            "3",
        ]
    )

    plan = json.loads((output / "benchmark_plan.json").read_text())
    gate = json.loads((output / "confirmation_gate.json").read_text())
    assert {
        tuple(job["free_parameters"]) for job in plan["jobs"]
    } == {
        ("k0_2", "k0_3"),
        ("k0_2", "G_O"),
        ("k0_3", "G_O"),
    }
    assert {job["budget"] for job in plan["jobs"]} == {100}
    assert gate == {
        "scientific_gate_passed": None,
        "eligible_pairs": [],
        "next_action": "RUN_FORMAL_CONFIRMATION",
    }


def test_confirmation_runner_resume_rejects_changed_development_evidence(
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
        lambda job, **kwargs: _fake_confirmation_row(job),
    )
    source = (
        ROOT
        / "results"
        / "formal"
        / "identifiability"
        / "gate-a6-optimizer-development"
        / "development_evidence.json"
    )
    evidence = tmp_path / "development_evidence.json"
    evidence.write_bytes(source.read_bytes())
    output = tmp_path / "confirmation-resume"
    args = _confirmation_args(output, evidence)
    before = evidence.read_bytes()
    benchmark_runner.main(args)
    assert evidence.read_bytes() == before
    payload = json.loads(evidence.read_text())
    payload["source_commit"] = "changed"
    evidence.write_text(json.dumps(payload))

    with pytest.raises(
        ValueError,
        match="development evidence|resume_fingerprint",
    ):
        benchmark_runner.main([*args, "--resume"])


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
