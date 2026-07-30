"""Pure contracts for V4 computational experiment design."""

from __future__ import annotations

import numpy as np
import pytest

from oer_aem.experiment_design import (
    block_feature_vector,
    central_sensitivity,
    column_direction_cosines,
    matrix_metrics,
    rank_candidate_conditions,
    stack_observable_matrices,
)


def _feature_fixture(n_grid: int = 20) -> dict[str, object]:
    complex_values = np.asarray(
        [1 + 1j, 2 + 0.5j, 3 - 1j],
        dtype=complex,
    )
    lockin = [
        np.linspace(harmonic, harmonic + 1, n_grid)
        + 1j * np.linspace(-harmonic, harmonic, n_grid)
        for harmonic in (1, 2, 3)
    ]
    return {
        "dc": np.linspace(1.0, 2.0, n_grid),
        "complex_harmonics": {"complex": complex_values},
        "lockin": {
            "complex": lockin,
            "valid_mask": np.ones(n_grid, dtype=bool),
        },
    }


def test_block_feature_vector_has_27_rows():
    names, values, observable = block_feature_vector(_feature_fixture())

    assert len(names) == len(values) == len(observable) == 27
    assert names[:3] == ("dc:low", "dc:mid", "dc:high")
    assert all(observable)
    assert np.all(np.isfinite(values))


def test_block_feature_vector_marks_empty_lockin_segment_unobservable():
    features = _feature_fixture()
    features["lockin"]["valid_mask"][:4] = False

    names, values, observable = block_feature_vector(features)

    index = names.index("lockin_h1_real:low")
    assert observable[index] is False
    assert np.isnan(values[index])


def test_central_sensitivity_uses_parameter_span_and_baseline_scale():
    result = central_sensitivity(
        plus=np.array([3.0, 6.0]),
        minus=np.array([1.0, 2.0]),
        baseline=np.array([2.0, 4.0]),
        parameter_span=2.0,
    )

    np.testing.assert_allclose(result, [0.5, 0.5])


def test_matrix_metrics_reward_orthogonal_columns():
    orthogonal = np.eye(5)
    coupled = np.column_stack(
        [np.ones(5), np.ones(5), np.eye(5)[:, :3]]
    )

    assert matrix_metrics(orthogonal)["max_abs_correlation"] < (
        matrix_metrics(coupled)["max_abs_correlation"]
    )
    assert matrix_metrics(orthogonal)["min_singular_value"] > 0.0


def test_stack_observable_matrices_uses_only_common_rows():
    first = (
        ("a", "b", "c"),
        np.asarray([[1.0], [2.0], [3.0]]),
        np.asarray([True, True, False]),
    )
    second = (
        ("a", "b", "c"),
        np.asarray([[4.0], [5.0], [6.0]]),
        np.asarray([True, False, True]),
    )

    names, matrix = stack_observable_matrices([first, second])

    assert names == ("a",)
    np.testing.assert_allclose(matrix, [[1.0], [4.0]])


def test_rank_candidate_conditions_uses_frozen_lexicographic_order():
    rows = [
        {
            "condition_id": "high_q25_logdet",
            "all_success": True,
            "q25_logdet_gain": 2.0,
            "median_correlation_reduction": 0.1,
            "q25_min_singular_gain": 0.1,
            "positive_gain_count": 8,
            "total_points": 100,
        },
        {
            "condition_id": "lower_q25_logdet",
            "all_success": True,
            "q25_logdet_gain": 1.0,
            "median_correlation_reduction": 0.9,
            "q25_min_singular_gain": 2.0,
            "positive_gain_count": 8,
            "total_points": 50,
        },
    ]

    ranked = rank_candidate_conditions(rows, minimum_positive=6)

    assert ranked[0]["condition_id"] == "high_q25_logdet"


def test_rank_candidate_conditions_rejects_non_robust_gain():
    rows = [
        {
            "condition_id": "fragile",
            "all_success": True,
            "q25_logdet_gain": 1.0,
            "median_correlation_reduction": 0.1,
            "q25_min_singular_gain": 0.1,
            "positive_gain_count": 5,
            "total_points": 100,
        }
    ]

    ranked = rank_candidate_conditions(rows, minimum_positive=6)

    assert ranked[0]["eligible"] is False


def test_column_direction_cosines_detects_reversal():
    full = np.eye(2)
    half = np.asarray([[1.0, 0.0], [0.0, -1.0]])

    np.testing.assert_allclose(
        column_direction_cosines(full, half),
        [1.0, -1.0],
    )


def test_matrix_metrics_rejects_non_finite_values():
    with pytest.raises(ValueError, match="finite"):
        matrix_metrics(np.asarray([[np.nan]]))
