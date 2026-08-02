"""Tests for sensitivity-matrix identifiability diagnostics."""

import numpy as np
import pytest

from oer_aem.identifiability import (
    active_subspace_decomposition,
    classify_columns,
    coordinate_scales_from_schema,
    coupling_direction,
    decompose_importance_reports,
    estimate_diagonal_feature_stability,
    fit_compensation_geometry,
    select_candidate_dimension,
    sensitivity_correlation,
    subspace_alignment_diagnostics,
    subspace_residual_diagnostics,
    whiten_sensitivity,
)


def test_identifiability_flags_duplicate_columns_as_coupled():
    matrix = np.array(
        [
            [1.0, 1.0, 0.0],
            [2.0, 2.0, 1.0],
            [3.0, 3.0, 0.0],
        ]
    )

    correlation = sensitivity_correlation(matrix)
    result = classify_columns(
        ["a", "b", "c"],
        matrix,
        correlation,
    )

    assert result["a"] == "coupled"
    assert result["b"] == "coupled"
    assert result["c"] == "identifiable"


def test_identifiability_flags_near_zero_column_as_unresolved():
    matrix = np.column_stack(
        [np.ones(5), np.full(5, 1e-14)]
    )

    result = classify_columns(
        ["active", "silent"],
        matrix,
        sensitivity_correlation(matrix),
    )

    assert result["silent"] == "unresolved"


def test_zero_sensitivity_matrix_is_unresolved_not_nan():
    matrix = np.zeros((4, 2))

    correlation = sensitivity_correlation(matrix)
    result = classify_columns(
        ["a", "b"],
        matrix,
        correlation,
    )

    assert np.all(np.isfinite(correlation))
    assert result == {"a": "unresolved", "b": "unresolved"}


def test_opposite_columns_are_coupled_with_opposite_response():
    matrix = np.array([[1.0, -1.0], [2.0, -2.0], [3.0, -3.0]])
    correlation = sensitivity_correlation(matrix)

    labels = classify_columns(["a", "b"], matrix, correlation)
    directions = coupling_direction(["a", "b"], correlation)

    assert labels == {"a": "coupled", "b": "coupled"}
    assert directions["a"] == [
        {"peer": "b", "correlation": -1.0, "direction": "opposite_response"}
    ]


def test_nonfinite_sensitivity_matrix_is_rejected():
    matrix = np.array([[1.0, np.nan], [2.0, 3.0]])

    with np.testing.assert_raises_regex(ValueError, "finite"):
        sensitivity_correlation(matrix)


def test_whitening_uses_feature_standard_deviations():
    jacobian = np.array([[1.0, 0.0], [0.0, 2.0]])

    whitened = whiten_sensitivity(jacobian, np.array([1.0, 2.0]))

    np.testing.assert_allclose(whitened, np.eye(2), rtol=0.0, atol=0.0)


def test_whitening_uses_full_noise_covariance():
    covariance = np.array([[2.0, 0.5], [0.5, 1.0]])
    jacobian = np.array([[1.0, 2.0], [3.0, 4.0]])

    whitened = whiten_sensitivity(jacobian, covariance)

    np.testing.assert_allclose(
        whitened.T @ whitened,
        jacobian.T @ np.linalg.solve(covariance, jacobian),
        rtol=1e-12,
        atol=1e-12,
    )


def test_active_subspace_finds_shared_compensation_direction():
    jacobian = np.array([[1.0, 1.0], [2.0, 2.0]])

    result = active_subspace_decomposition(
        [jacobian],
        [np.ones(2)],
    )

    np.testing.assert_allclose(result.eigenvalues, [10.0, 0.0], atol=1e-12)
    np.testing.assert_allclose(
        result.directions[:, 0],
        np.array([1.0, 1.0]) / np.sqrt(2.0),
        atol=1e-12,
    )
    assert not hasattr(result, "effective_dimension")


def test_anchor_weights_change_gramian_without_hard_parameter_groups():
    first = np.array([[1.0, 0.0]])
    second = np.array([[0.0, 1.0]])

    result = active_subspace_decomposition(
        [first, second],
        [np.ones(1), np.ones(1)],
        anchor_weights=[3.0, 1.0],
    )

    np.testing.assert_allclose(
        result.gramian,
        np.diag([0.75, 0.25]),
        rtol=0.0,
        atol=0.0,
    )
    np.testing.assert_allclose(result.eigenvalues, [0.75, 0.25])


def test_whitening_rejects_nonpositive_noise_model():
    jacobian = np.eye(2)

    with np.testing.assert_raises_regex(ValueError, "positive"):
        whiten_sensitivity(jacobian, np.array([1.0, 0.0]))
    with np.testing.assert_raises_regex(ValueError, "positive definite"):
        whiten_sensitivity(jacobian, np.array([[1.0, 2.0], [2.0, 1.0]]))


def test_importance_reports_feed_multi_anchor_decomposition():
    def report(changes):
        return {
            "metadata": {"param_order": ["a", "b"]},
            "parameter_importance": [{"name": "a"}, {"name": "b"}],
            "signed_feature_sensitivity_matrix": [
                {"feature": "H1", "changes": changes},
            ],
        }

    features, parameters, result = decompose_importance_reports(
        [report({"a": 1.0, "b": 0.0}), report({"a": 0.0, "b": 1.0})],
        [np.ones(1), np.ones(1)],
        column_scales_to_unit_coordinates={"a": 2.0, "b": 3.0},
    )

    assert features == ["H1"]
    assert parameters == ["a", "b"]
    np.testing.assert_allclose(result.gramian, np.diag([2.0, 4.5]))


def test_importance_report_feature_drift_is_rejected():
    first = {
        "metadata": {"param_order": ["a"]},
        "parameter_importance": [{"name": "a"}],
        "signed_feature_sensitivity_matrix": [
            {"feature": "H1", "changes": {"a": 1.0}}
        ],
    }
    second = {
        **first,
        "signed_feature_sensitivity_matrix": [
            {"feature": "H2", "changes": {"a": 1.0}}
        ],
    }

    with np.testing.assert_raises_regex(ValueError, "feature contract"):
        decompose_importance_reports(
            [first, second],
            [np.ones(1), np.ones(1)],
            column_scales_to_unit_coordinates={"a": 1.0},
        )


def test_importance_reports_require_complete_unit_coordinate_scales():
    report = {
        "metadata": {"param_order": ["a", "b"]},
        "parameter_importance": [{"name": "a"}, {"name": "b"}],
        "signed_feature_sensitivity_matrix": [
            {"feature": "H1", "changes": {"a": 1.0, "b": 1.0}}
        ],
    }

    with np.testing.assert_raises_regex(ValueError, "coordinate scales"):
        decompose_importance_reports(
            [report],
            [np.ones(1)],
            column_scales_to_unit_coordinates={"a": 1.0},
        )


def test_schema_bounds_generate_unit_coordinate_column_scales():
    schema = {
        "parameters": {
            "rate": {"transform": "log10", "bounds": [1e-3, 1e3]},
            "energy": {"transform": "linear", "bounds": [0.5, 2.0]},
        }
    }

    scales = coordinate_scales_from_schema(schema, ["rate", "energy"])

    assert scales == {"rate": 6.0, "energy": 1.5}


def test_schema_scale_generation_rejects_unresolved_bounds():
    schema = {
        "parameters": {
            "GammaA": {
                "transform": "log10",
                "bounds": None,
                "bounds_status": "unresolved",
            }
        }
    }

    with np.testing.assert_raises_regex(ValueError, "GammaA.*bounds"):
        coordinate_scales_from_schema(schema, ["GammaA"])


def test_subspace_residuals_measure_discarded_whitened_sensitivity():
    jacobian = np.diag([10.0, 1.0])

    rows = subspace_residual_diagnostics(
        [jacobian],
        [np.ones(2)],
        np.eye(2),
        candidate_dimensions=[1, 2],
    )

    assert rows[0]["dimension"] == 1
    assert rows[0]["worst_relative_frobenius"] == pytest.approx(
        1.0 / np.sqrt(101.0)
    )
    assert rows[0]["worst_discarded_singular_value"] == pytest.approx(1.0)
    assert rows[1]["dimension"] == 2
    assert rows[1]["worst_relative_frobenius"] == pytest.approx(0.0)


def test_subspace_residuals_reject_nonorthogonal_directions():
    with pytest.raises(ValueError, match="orthonormal"):
        subspace_residual_diagnostics(
            [np.eye(2)],
            [np.ones(2)],
            np.ones((2, 2)),
        )


def test_quantization_stability_uses_uniform_noise_with_frozen_seeds():
    current = np.array([-2.0, 1.0, 0.5])
    seeds = [11, 13, 17, 19]

    result = estimate_diagonal_feature_stability(
        current,
        feature_extractor=lambda values: np.asarray(values[:2], dtype=float),
        noise_fraction=0.01,
        seeds=seeds,
    )

    expected = []
    half_width = np.sqrt(3.0) * 0.01 * 2.0
    for seed in seeds:
        rng = np.random.default_rng(seed)
        expected.append(
            (current + rng.uniform(-half_width, half_width, current.shape))[:2]
        )
    np.testing.assert_allclose(
        result.standard_deviations,
        np.std(np.asarray(expected), axis=0, ddof=1),
    )
    assert result.distribution == "uniform_quantization_error"
    assert result.seeds == tuple(seeds)
    assert result.current_sigma == pytest.approx(0.02)


def test_quantization_stability_rejects_unresolved_zero_variance_feature():
    with pytest.raises(ValueError, match="zero stability variance"):
        estimate_diagonal_feature_stability(
            np.array([1.0, 2.0, 3.0]),
            feature_extractor=lambda _values: np.array([1.0]),
            noise_fraction=0.01,
            seeds=[1, 2, 3],
        )


def test_candidate_dimension_is_selected_only_from_frozen_selection_threshold():
    rows = [
        {"dimension": 1, "worst_discarded_singular_value": 1.4},
        {"dimension": 2, "worst_discarded_singular_value": 0.8},
        {"dimension": 3, "worst_discarded_singular_value": 0.0},
    ]

    result = select_candidate_dimension(
        rows,
        parameter_count=3,
        maximum_whitened_operator_norm=1.0,
    )

    assert result == {
        "status": "candidate_selected_from_selection",
        "candidate_dimension": 2,
        "maximum_whitened_operator_norm": 1.0,
        "reduction_achieved": True,
    }


def test_candidate_dimension_reports_full_space_when_no_reduction_passes():
    rows = [
        {"dimension": 1, "worst_discarded_singular_value": 2.0},
        {"dimension": 2, "worst_discarded_singular_value": 0.0},
    ]

    result = select_candidate_dimension(rows, parameter_count=2)

    assert result["candidate_dimension"] == 2
    assert result["status"] == "full_space_required_by_selection"
    assert result["reduction_achieved"] is False


def test_subspace_alignment_distinguishes_stable_and_rotated_local_directions():
    diagnostics = subspace_alignment_diagnostics(
        [np.diag([2.0, 1.0]), np.diag([1.0, 2.0])],
        [np.ones(2), np.ones(2)],
        np.eye(2),
    )

    assert diagnostics[0][0]["dimension"] == 1
    assert diagnostics[0][0]["maximum_principal_angle_degrees"] == pytest.approx(0.0)
    assert diagnostics[1][0]["maximum_principal_angle_degrees"] == pytest.approx(90.0)
    assert diagnostics[0][1]["maximum_principal_angle_degrees"] == pytest.approx(0.0)
    assert diagnostics[1][1]["maximum_principal_angle_degrees"] == pytest.approx(0.0)


def test_subspace_alignment_rejects_nonorthogonal_reference():
    with pytest.raises(ValueError, match="orthonormal"):
        subspace_alignment_diagnostics(
            [np.eye(2)],
            [np.ones(2)],
            np.ones((2, 2)),
        )


def test_compensation_geometry_returns_invariant_orthogonal_to_motion():
    displacements = np.array([[1.0, 1.0], [2.0, 2.0], [-1.0, -1.0]])

    result = fit_compensation_geometry(displacements)

    invariant = np.asarray(result["directions"], dtype=float)[:, -1]
    np.testing.assert_allclose(displacements @ invariant, 0.0, atol=1e-12)
    np.testing.assert_allclose(result["singular_values"][1], 0.0, atol=1e-12)
    assert invariant[np.argmax(np.abs(invariant))] > 0.0
