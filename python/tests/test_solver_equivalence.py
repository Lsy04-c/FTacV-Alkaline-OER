"""Tests for the C++ CN versus LSODA equivalence evidence helpers."""

import numpy as np
import pytest


def test_parameter_samples_are_deterministic_and_stay_inside_bounds():
    from scripts import validate_solver_equivalence as validation

    first = validation.sample_parameter_vectors(
        validation.DEFAULT_PARAM_SPECS,
        n_samples=6,
        seed=17,
    )
    second = validation.sample_parameter_vectors(
        validation.DEFAULT_PARAM_SPECS,
        n_samples=6,
        seed=17,
    )

    assert first == pytest.approx(second)
    assert first.shape == (6, len(validation.DEFAULT_PARAM_SPECS))
    for column, (_, _, low, high) in enumerate(validation.DEFAULT_PARAM_SPECS):
        assert np.all(first[:, column] > low)
        assert np.all(first[:, column] < high)


def test_wrapped_phase_rmse_treats_pi_boundary_as_nearby():
    from scripts import validate_solver_equivalence as validation

    first = np.array([np.pi - 0.05, -np.pi + 0.05])
    second = np.array([-np.pi + 0.05, np.pi - 0.05])

    rmse = validation.wrapped_phase_rmse(first, second)

    assert rmse == pytest.approx(0.1)


def test_normalized_rmse_uses_reference_dynamic_scale():
    from scripts import validate_solver_equivalence as validation

    reference = np.array([-2.0, 0.0, 2.0])
    candidate = reference + 0.2

    value = validation.normalized_rmse(candidate, reference)

    assert value == pytest.approx(0.1)


def test_gate_skips_unstable_relative_metrics_for_unresolved_channel():
    from scripts import validate_solver_equivalence as validation

    row = {
        "sample": 0,
        "harmonic": 7,
        "lsoda_success": True,
        "cn_success": True,
        "current_nrmse": 0.0,
        "dc_nrmse": 0.0,
        "global_resolved": False,
        "lockin_resolved": False,
        "global_amplitude_relative_error": 10.0,
        "global_phase_error_rad": 3.0,
        "lockin_amplitude_nrmse": 10.0,
        "lockin_phase_rmse_rad": 3.0,
        "peak_shift_v": 1.0,
    }

    result = validation.assess_gate([row])

    assert result["passed"] is True


def test_failure_row_uses_complete_csv_schema(monkeypatch):
    from scripts import validate_solver_equivalence as validation

    monkeypatch.setattr(validation, "_solve", lambda vector, config: (None, 0.1))

    rows = validation.compare_sample(0, np.zeros(8), 32, 8)

    assert set(rows[0]) == set(validation.CSV_FIELDS)
