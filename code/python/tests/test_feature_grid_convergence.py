"""Tests for the fixed-library Gate A5 grid-convergence helpers."""

import numpy as np


def test_parameter_library_is_deterministic_and_stays_in_inner_bounds():
    from scripts import validate_feature_grid_convergence as validation

    first = validation.sample_parameter_library(
        validation.DEFAULT_PARAM_SPECS,
        n_candidates=8,
        seed=23,
    )
    second = validation.sample_parameter_library(
        validation.DEFAULT_PARAM_SPECS,
        n_candidates=8,
        seed=23,
    )

    assert np.array_equal(first, second)
    assert first.shape == (8, len(validation.DEFAULT_PARAM_SPECS))
    for index, (_, _, low, high) in enumerate(validation.DEFAULT_PARAM_SPECS):
        width = high - low
        assert np.all(first[:, index] > low + 0.10 * width)
        assert np.all(first[:, index] < high - 0.10 * width)


def test_stable_relative_error_remains_finite_for_zero_reference():
    from scripts import validate_feature_grid_convergence as validation

    assert validation.stable_relative_error(0.0, 0.0) == 0.0
    assert validation.stable_relative_error(1e-13, 0.0) == 0.1
    assert np.isfinite(validation.stable_relative_error(1.0, 0.0))


def test_grid_gate_rejects_excess_max_error_or_rank_drift():
    from scripts import validate_feature_grid_convergence as validation

    passing = {
        "mode": "legacy",
        "grid": "128",
        "total_loss_relative_error_median": 0.005,
        "total_loss_relative_error_max": 0.04,
        "common_dc_rmse_relative_error_median": 0.005,
        "common_dc_rmse_relative_error_max": 0.04,
        "common_h1_h3_rmse_relative_error_median": 0.005,
        "common_h1_h3_rmse_relative_error_max": 0.04,
        "total_loss_spearman": 1.0,
        "all_success": True,
        "all_finite": True,
    }

    max_error_failure = validation.assess_grid_gate(
        [{**passing, "total_loss_relative_error_max": 0.051}]
    )
    rank_failure = validation.assess_grid_gate(
        [{**passing, "total_loss_spearman": 0.98}]
    )
    passed = validation.assess_grid_gate([passing])

    assert max_error_failure["passed"] is False
    assert "total_loss_relative_error_max" in max_error_failure["failures"][0]
    assert rank_failure["passed"] is False
    assert "total_loss_spearman" in rank_failure["failures"][0]
    assert passed["passed"] is True


def test_grid_summary_matches_candidates_to_full_reference():
    from scripts import validate_feature_grid_convergence as validation

    rows = []
    for mode in validation.MODES:
        for grid in ("64", "128", "256", "full"):
            factor = (
                1.0
                if grid == "full"
                else {"64": 1.02, "128": 1.001, "256": 1.0005}[grid]
            )
            for candidate in range(validation.N_CANDIDATES):
                value = float(candidate + 1)
                row = {
                    "mode": mode,
                    "grid": grid,
                    "candidate": candidate,
                    "ode_success": True,
                    "total_loss": value * factor,
                    "common_dc_rmse": value * factor,
                    "common_h1_h3_rmse": value * factor,
                }
                row.update(
                    {
                        f"loss_{key}": value * factor
                        for key in validation.COMPONENT_KEYS
                    }
                )
                rows.append(row)

    summaries = validation.summarize_grid_rows(rows)
    gate = validation.assess_grid_gate(summaries)
    grid_128 = [row for row in summaries if row["grid"] == "128"]

    assert len(summaries) == 12
    assert all(
        row["total_loss_relative_error_max"] < 0.002 for row in grid_128
    )
    assert all(row["total_loss_spearman"] == 1.0 for row in grid_128)
    assert gate["passed"] is True
