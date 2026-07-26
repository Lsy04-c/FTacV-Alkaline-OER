"""Tests for sensitivity-matrix identifiability diagnostics."""

import numpy as np

from oer_aem.identifiability import (
    classify_columns,
    coupling_direction,
    sensitivity_correlation,
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
