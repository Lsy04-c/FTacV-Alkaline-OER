"""Contracts for the V4 experiment-design runner."""

from __future__ import annotations

from collections import Counter
import json
from pathlib import Path

import numpy as np
import pytest

import scripts.run_v4_experiment_design as runner
from scripts.run_v4_experiment_design import (
    _resume_expected_jobs,
    build_condition_catalog,
    build_linearity_jobs,
    build_recommendation,
    build_primary_jobs,
    build_sensitivity_evidence,
    compute_portfolio_gains,
    condition_to_config,
    load_inputs,
    load_completed_jobs,
    load_spec,
    linearity_preserves_recommendation_order,
    run_one_forward,
    select_parameter_points,
)

ROOT = Path(__file__).resolve().parents[3]
SPEC = ROOT / "config" / "experiment-design" / "v4-computational-design.json"

PARAMETER_SPECS = [
    ["k0_1", "log10", -3.0, 5.0],
    ["k0_2", "log10", -3.0, 5.0],
    ["k0_3", "log10", -3.0, 5.0],
    ["G_OH", "linear", 0.8, 1.8],
    ["G_O", "linear", 2.2, 3.4],
]
PERTURBATIONS = {
    "k0_1": 0.25,
    "k0_2": 0.25,
    "k0_3": 0.25,
    "G_OH": 0.05,
    "G_O": 0.05,
}


def _v3_rows() -> list[dict[str, object]]:
    rows = []
    for dataset_index, dataset_id in enumerate(("FT2", "FT3", "FT4", "FT8")):
        for rank in range(3):
            encoded = [
                -2.0 + 0.1 * dataset_index,
                1.0 + 0.1 * rank,
                0.5,
                1.0,
                2.8,
            ]
            rows.append(
                {
                    "dataset_id": dataset_id,
                    "candidate_id": dataset_index * 10 + rank,
                    "selection_rank": rank,
                    "encoded_params": encoded,
                    "physical_params": {
                        "k0_1": 10 ** encoded[0],
                        "k0_2": 10 ** encoded[1],
                        "k0_3": 10 ** encoded[2],
                        "G_OH": encoded[3],
                        "G_O": encoded[4],
                    },
                    "job_input_hash": f"v3-{dataset_id}-{rank}",
                    "success": True,
                }
            )
    return rows


def _conditions() -> list[dict[str, object]]:
    rows = []
    for index in range(9):
        rows.append(
            {
                "condition_id": f"c{index}",
                "condition_role": "existing" if index < 4 else "candidate",
                "E_start": 0.9,
                "E_end": 1.9,
                "frequency_hz": 5.0,
                "amplitude_v": 0.16,
                "cycles": 32 + index,
                "points_per_cycle": 128,
            }
        )
    return rows


def test_parameter_points_are_v3_ranks_zero_and_one():
    points = select_parameter_points(_v3_rows(), selection_ranks=(0, 1))

    assert len(points) == 8
    assert Counter(row["selection_rank"] for row in points) == {0: 4, 1: 4}
    assert Counter(row["dataset_id"] for row in points) == {
        "FT2": 2,
        "FT3": 2,
        "FT4": 2,
        "FT8": 2,
    }


def test_build_primary_jobs_has_792_deterministic_jobs():
    jobs = build_primary_jobs(
        select_parameter_points(_v3_rows(), selection_ranks=(0, 1)),
        _conditions(),
        parameter_specs=PARAMETER_SPECS,
        perturbations=PERTURBATIONS,
        task_spec_hash="task-hash",
    )

    assert len(jobs) == 8 * 9 * 11
    assert len({row["job_id"] for row in jobs}) == len(jobs)
    assert Counter(row["perturbation_direction"] for row in jobs) == {
        "baseline": 8 * 9,
        "plus": 8 * 9 * 5,
        "minus": 8 * 9 * 5,
    }
    assert {row["condition_role"] for row in jobs} == {
        "existing",
        "candidate",
    }


def test_log_perturbation_changes_encoded_coordinate_by_frozen_step():
    jobs = build_primary_jobs(
        select_parameter_points(_v3_rows(), selection_ranks=(0, 1))[:1],
        _conditions()[:1],
        parameter_specs=PARAMETER_SPECS,
        perturbations=PERTURBATIONS,
        task_spec_hash="task-hash",
    )
    baseline = next(row for row in jobs if row["perturbation_direction"] == "baseline")
    plus = next(
        row
        for row in jobs
        if row["perturbation_parameter"] == "k0_1"
        and row["perturbation_direction"] == "plus"
    )

    assert plus["encoded_params"][0] == pytest.approx(
        baseline["encoded_params"][0] + 0.25
    )


def test_load_completed_jobs_rejects_changed_job_hash(tmp_path):
    jobs = build_primary_jobs(
        select_parameter_points(_v3_rows(), selection_ranks=(0, 1))[:1],
        _conditions()[:1],
        parameter_specs=PARAMETER_SPECS,
        perturbations=PERTURBATIONS,
        task_spec_hash="task-hash",
    )
    (tmp_path / "forward_results.jsonl").write_text(
        json.dumps(
            {
                "job_id": jobs[0]["job_id"],
                "job_input_hash": "wrong",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="job hash"):
        load_completed_jobs(tmp_path, jobs)


def test_load_completed_jobs_rejects_duplicate_job(tmp_path):
    jobs = build_primary_jobs(
        select_parameter_points(_v3_rows(), selection_ranks=(0, 1))[:1],
        _conditions()[:1],
        parameter_specs=PARAMETER_SPECS,
        perturbations=PERTURBATIONS,
        task_spec_hash="task-hash",
    )
    row = {
        "job_id": jobs[0]["job_id"],
        "job_input_hash": jobs[0]["job_input_hash"],
    }
    (tmp_path / "forward_results.jsonl").write_text(
        json.dumps(row) + "\n" + json.dumps(row) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="duplicate"):
        load_completed_jobs(tmp_path, jobs)


def test_frozen_spec_loads_hashed_v2_v3_inputs():
    spec = load_spec(SPEC)
    inputs = load_inputs(ROOT, spec)

    assert len(inputs["parameter_points"]) == 8
    assert inputs["parameter_specs"] == PARAMETER_SPECS
    assert inputs["fixed_baseline"]["gamma"] == 3e-9


def test_condition_catalog_derives_points_duration_and_scan_rate():
    spec = load_spec(SPEC)
    conditions = build_condition_catalog(spec, smoke=False)
    condition = next(
        row
        for row in conditions
        if row["condition_id"] == "candidate_1hz_matched_scan"
    )

    assert condition["n_points"] == 52 * 128
    assert condition["duration_s"] == pytest.approx(52.0)
    assert condition["scan_rate_v_s"] == pytest.approx(
        (condition["E_end"] - condition["E_start"]) / 52.0
    )


def test_condition_to_config_freezes_hybrid_lsoda_contract():
    spec = load_spec(SPEC)
    condition = build_condition_catalog(spec, smoke=True)[0]

    config = condition_to_config(condition, spec, fixed_baseline={"A": 1.0})

    assert config.solver_backend == "lsoda"
    assert config.feature_mode == "hybrid"
    assert config.fit_harmonics == (1, 2, 3)
    assert config.fixed_params == (("A", 1.0),)


def _forward_rows_for_one_matrix() -> list[dict[str, object]]:
    names = [f"feature-{index}" for index in range(27)]
    baseline = np.linspace(1.0, 2.0, 27)
    rows = [
        {
            "dataset_id": "FT2",
            "candidate_id": 1,
            "selection_rank": 0,
            "condition_id": "existing_ft3",
            "condition_role": "existing",
            "perturbation_parameter": None,
            "perturbation_direction": "baseline",
            "encoded_params": [0.0] * 5,
            "feature_names": names,
            "feature_values": baseline.tolist(),
            "observable": [True] * 27,
            "success": True,
        }
    ]
    for parameter_index, parameter in enumerate(PERTURBATIONS):
        for direction, sign in (("plus", 1.0), ("minus", -1.0)):
            values = baseline.copy()
            values[parameter_index] += sign * PERTURBATIONS[parameter]
            encoded = [0.0] * 5
            encoded[parameter_index] = sign * PERTURBATIONS[parameter]
            rows.append(
                {
                    **rows[0],
                    "perturbation_parameter": parameter,
                    "perturbation_direction": direction,
                    "encoded_params": encoded,
                    "feature_values": values.tolist(),
                }
            )
    return rows


def test_build_sensitivity_evidence_produces_27_by_5_matrix():
    evidence = build_sensitivity_evidence(
        _forward_rows_for_one_matrix(),
        parameter_specs=PARAMETER_SPECS,
        ridge=1e-8,
    )

    assert len(evidence) == 1
    assert np.asarray(evidence[0]["matrix"]).shape == (27, 5)
    assert len(evidence[0]["column_norms"]) == 5
    assert evidence[0]["success"] is True


def test_run_one_forward_returns_real_27_block_vector():
    spec = load_spec(SPEC)
    inputs = load_inputs(ROOT, spec)
    point = {
        "dataset_id": "FT2",
        "candidate_id": 999,
        "selection_rank": 0,
        "job_input_hash": "fixture",
        "encoded_params": [3.0, 3.0, 1.0, 1.1, 2.7],
    }
    condition = {
        "condition_id": "fixture",
        "condition_role": "candidate",
        "E_start": 0.9,
        "E_end": 1.2,
        "frequency_hz": 5.0,
        "amplitude_v": 0.08,
        "cycles": 8,
        "points_per_cycle": 32,
        "n_points": 256,
        "duration_s": 1.6,
        "scan_rate_v_s": 0.1875,
    }
    job = build_primary_jobs(
        [point],
        [condition],
        parameter_specs=PARAMETER_SPECS,
        perturbations=PERTURBATIONS,
        task_spec_hash="task-hash",
    )[0]

    result = run_one_forward(
        {
            "job": job,
            "spec": {**spec, "feature_grid_size": 32},
            "parameter_specs": PARAMETER_SPECS,
            "fixed_baseline": inputs["fixed_baseline"],
        }
    )

    assert result["success"] is True
    assert len(result["feature_names"]) == 27
    assert len(result["feature_values"]) == 27
    assert result["solver_backend_used"] in {"LSODA", "BDF"}


def _portfolio_fixture() -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    conditions = [
        {
            "condition_id": f"existing-{index}",
            "condition_role": "existing",
            "n_points": 100,
        }
        for index in range(4)
    ] + [
        {
            "condition_id": "candidate-good",
            "condition_role": "candidate",
            "n_points": 200,
        },
        {
            "condition_id": "candidate-weak",
            "condition_role": "candidate",
            "n_points": 50,
        },
    ]
    rows = []
    for dataset_index, dataset_id in enumerate(("FT2", "FT3", "FT4", "FT8")):
        for rank in (0, 1):
            for condition in conditions:
                scale = (
                    1.0
                    if condition["condition_id"] == "candidate-good"
                    else 0.05
                )
                rows.append(
                    {
                        "dataset_id": dataset_id,
                        "candidate_id": dataset_index * 10 + rank,
                        "selection_rank": rank,
                        "condition_id": condition["condition_id"],
                        "condition_role": condition["condition_role"],
                        "success": True,
                        "feature_names": [f"f{i}" for i in range(5)],
                        "matrix": (np.eye(5) * scale).tolist(),
                    }
                )
    return rows, conditions


def test_compute_portfolio_gains_aggregates_eight_parameter_points():
    rows, conditions = _portfolio_fixture()
    detail, aggregate = compute_portfolio_gains(
        rows,
        conditions,
        ridge=1e-8,
        minimum_positive=6,
    )

    assert len(detail) == 8 * 2
    assert {row["condition_id"] for row in aggregate} == {
        "candidate-good",
        "candidate-weak",
    }
    good = next(
        row for row in aggregate if row["condition_id"] == "candidate-good"
    )
    assert good["positive_gain_count"] == 8
    assert good["eligible"] is True


def test_failed_portfolio_uses_json_safe_missing_metrics():
    rows, conditions = _portfolio_fixture()
    for row in rows:
        if row["condition_id"] == "candidate-good":
            row["success"] = False

    _, aggregate = compute_portfolio_gains(
        rows,
        conditions,
        ridge=1e-8,
        minimum_positive=6,
    )

    failed = next(
        row for row in aggregate if row["condition_id"] == "candidate-good"
    )
    assert failed["q25_logdet_gain"] is None
    assert failed["median_correlation_reduction"] is None
    assert failed["q25_min_singular_gain"] is None
    json.dumps(aggregate, allow_nan=False)


def test_build_recommendation_selects_two_conditions_in_order():
    rows, conditions = _portfolio_fixture()

    result = build_recommendation(
        rows,
        conditions,
        ridge=1e-8,
        minimum_positive=6,
    )

    assert result["status"] == "RECOMMEND_TWO"
    assert result["selected"][0] == "candidate-good"
    assert result["selected"][1] == "candidate-weak"


def test_build_recommendation_labels_numerical_failure():
    rows, conditions = _portfolio_fixture()
    rows[0]["success"] = False

    result = build_recommendation(
        rows,
        conditions,
        ridge=1e-8,
        minimum_positive=6,
    )

    assert result["status"] == "FAIL_NUMERICAL"
    assert result["selected"] == []


def test_half_step_ranking_detects_reversed_selected_order():
    rows, conditions = _portfolio_fixture()
    rank_zero = [
        row for row in rows if int(row["selection_rank"]) == 0
    ]
    half_rows = []
    for row in rank_zero:
        if row["condition_id"] not in {"candidate-good", "candidate-weak"}:
            continue
        scale = 0.01 if row["condition_id"] == "candidate-good" else 2.0
        half_rows.append(
            {
                **row,
                "matrix": (np.eye(5) * scale).tolist(),
            }
        )

    preserved = linearity_preserves_recommendation_order(
        rank_zero,
        half_rows,
        conditions,
        selected=("candidate-good", "candidate-weak"),
        ridge=1e-8,
    )

    assert preserved is False


def test_build_linearity_jobs_has_80_half_step_jobs():
    points = select_parameter_points(_v3_rows(), selection_ranks=(0, 1))
    rank_zero = [row for row in points if row["selection_rank"] == 0]
    conditions = _conditions()[4:6]

    jobs = build_linearity_jobs(
        rank_zero,
        conditions,
        parameter_specs=PARAMETER_SPECS,
        perturbations=PERTURBATIONS,
        task_spec_hash="task-hash",
    )

    assert len(jobs) == 4 * 2 * 5 * 2
    assert all(row["job_kind"] == "linearity_half_step" for row in jobs)
    plus = next(
        row
        for row in jobs
        if row["perturbation_parameter"] == "k0_1"
        and row["perturbation_direction"] == "plus"
    )
    point = next(
        row
        for row in rank_zero
        if row["dataset_id"] == plus["dataset_id"]
    )
    assert plus["encoded_params"][0] == pytest.approx(
        point["encoded_params"][0] + 0.125
    )


def test_resume_initial_plan_accepts_only_hash_valid_candidate_half_steps():
    points = select_parameter_points(_v3_rows(), selection_ranks=(0, 1))
    conditions = _conditions()
    primary = build_primary_jobs(
        points,
        conditions,
        parameter_specs=PARAMETER_SPECS,
        perturbations=PERTURBATIONS,
        task_spec_hash="task-hash",
    )

    expected = _resume_expected_jobs(
        primary,
        points,
        conditions,
        parameter_specs=PARAMETER_SPECS,
        perturbations=PERTURBATIONS,
        task_spec_hash="task-hash",
    )

    assert len(expected) == 792 + 4 * 5 * 5 * 2
    assert len({row["job_id"] for row in expected}) == len(expected)


def test_load_inputs_rejects_parameter_bound_drift(monkeypatch):
    spec = load_spec(SPEC)
    changed = json.loads(json.dumps(spec))
    changed["parameter_specs"][0][2] = -2.5

    with pytest.raises(ValueError, match="parameter specs"):
        load_inputs(ROOT, changed)


def test_main_calls_zero_argument_git_provenance(monkeypatch, tmp_path):
    monkeypatch.setattr(
        runner,
        "_git_provenance",
        lambda: {
            "source_commit": "fixture",
            "dirty": True,
            "dirty_paths": ["fixture"],
            "ignored_workflow_paths": [],
            "dirty_content_sha256": "hash",
        },
    )

    def stop_after_provenance(*args, **kwargs):
        raise RuntimeError("after-provenance")

    monkeypatch.setattr(runner, "_prepare_output", stop_after_provenance)

    with pytest.raises(RuntimeError, match="after-provenance"):
        runner.main(
            [
                "--task-spec",
                str(SPEC),
                "--output",
                str(tmp_path),
                "--smoke",
            ]
        )
