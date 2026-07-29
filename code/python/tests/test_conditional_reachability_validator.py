from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "code" / "python" / "scripts"))


def test_validator_recomputes_worst_component_scores():
    from validate_conditional_reachability import recompute_scores

    result = recompute_scores(
        metrics={
            "dc_nrmse": 0.05,
            "global_amplitude_h1": 0.11,
            "global_phase_h1": 0.02,
            "lockin_valid_fraction": 0.75,
            "lockin_amplitude_h1": 0.01,
            "lockin_phase_h1": 0.02,
            "lockin_peak_shift_h1": 0.0,
        },
        active_harmonics=(1,),
        thresholds={
            "dc_nrmse": 0.1,
            "global_amplitude_relative_error": 0.1,
            "global_phase_error_rad": 0.1,
            "lockin_amplitude_nrmse": 0.1,
            "lockin_phase_rmse_rad": 0.1,
            "lockin_peak_shift_v": 0.025,
            "lockin_valid_fraction_min": 0.5,
        },
    )

    assert result["global_score"] == pytest.approx(1.1)
    assert result["lockin_score"] == pytest.approx(2 / 3)
    assert result["score"] == pytest.approx(1.1)
    assert result["passed"] is False


def test_validator_source_is_independent_of_runner_and_reachability_module():
    source = (
        ROOT
        / "code"
        / "python"
        / "scripts"
        / "validate_conditional_reachability.py"
    ).read_text(encoding="utf-8")

    assert "import run_conditional_reachability" not in source
    assert "from oer_aem.reachability" not in source


@pytest.mark.parametrize(
    ("mutation", "match"),
    [
        ({"steady_state_rhs_norm": 2e-8}, "RHS"),
        ({"steady_state_elapsed_s": 60.0}, "endpoint"),
        (
            {
                "steady_state_attempts": [
                    {
                        "elapsed_s": 5.0,
                        "rhs_norm": 1e-4,
                        "success": True,
                        "message": "stage",
                        "nfev": 10,
                    }
                ]
            },
            "final attempt",
        ),
    ],
)
def test_validator_rejects_tampered_steady_state_provenance(
    mutation,
    match,
):
    from validate_conditional_reachability import (
        validate_steady_state_provenance,
    )

    row = {
        "success": True,
        "steady_state_elapsed_s": 50.0,
        "steady_state_rhs_norm": 2e-10,
        "steady_state_attempts": [
            {
                "elapsed_s": 5.0,
                "rhs_norm": 1e-4,
                "success": True,
                "message": "stage",
                "nfev": 10,
            },
            {
                "elapsed_s": 50.0,
                "rhs_norm": 2e-10,
                "success": True,
                "message": "stage",
                "nfev": 12,
            },
        ],
    }
    row.update(mutation)

    with pytest.raises(ValueError, match=match):
        validate_steady_state_provenance(row)


def test_validator_reconstructs_ranked_stress_job_set_and_hashes():
    from validate_conditional_reachability import expected_stress_jobs

    spec = {
        "top_stress_candidates": 2,
        "fixed_stress_scenarios": [
            {"scenario_id": "A:x0.5", "parameter": "A", "value": 0.5},
            {"scenario_id": "A:x2", "parameter": "A", "value": 2.0},
        ],
    }
    base_rows = [
        {
            "dataset_id": "FT2",
            "candidate_id": 0,
            "success": True,
            "score": 0.8,
            "encoded_params": [0.0],
            "physical_params": {"k0_1": 1.0},
            "task_spec_hash": "a" * 64,
            "parameter_library_hash": "b" * 64,
            "dataset_sha256": "c" * 64,
        },
        {
            "dataset_id": "FT2",
            "candidate_id": 1,
            "success": True,
            "score": 0.2,
            "encoded_params": [1.0],
            "physical_params": {"k0_1": 10.0},
            "task_spec_hash": "a" * 64,
            "parameter_library_hash": "b" * 64,
            "dataset_sha256": "c" * 64,
        },
        {
            "dataset_id": "FT2",
            "candidate_id": 2,
            "success": True,
            "score": 1.2,
            "encoded_params": [2.0],
            "physical_params": {"k0_1": 100.0},
            "task_spec_hash": "a" * 64,
            "parameter_library_hash": "b" * 64,
            "dataset_sha256": "c" * 64,
        },
    ]

    jobs = expected_stress_jobs(spec, base_rows)

    assert len(jobs) == 4
    assert [job["candidate_id"] for job in jobs] == [1, 1, 0, 0]
    assert all(len(job["job_input_hash"]) == 64 for job in jobs)
    assert len({job["job_id"] for job in jobs}) == 4


def test_rerun_metric_comparison_rejects_component_drift():
    from validate_conditional_reachability import compare_rerun_metrics

    compare_rerun_metrics(
        {"dc_nrmse": 0.1, "global_phase_h1": 0.2},
        {"dc_nrmse": 0.1 + 5e-10, "global_phase_h1": 0.2},
    )
    with pytest.raises(ValueError, match="dc_nrmse"):
        compare_rerun_metrics(
            {"dc_nrmse": 0.1},
            {"dc_nrmse": 0.10001},
        )
