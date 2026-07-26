"""Tests for sensitivity-matrix identifiability diagnostics."""

import numpy as np

from oer_aem.identifiability import (
    classify_columns,
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
