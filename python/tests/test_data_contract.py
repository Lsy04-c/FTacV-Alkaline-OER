"""Contracts for experimental FTacV arrays and residual signs."""

import numpy as np
import pytest

from oer_aem.data_contract import normalize_trace, residual_exp_minus_sim


def test_normalize_trace_sorts_time_and_keeps_columns_aligned():
    rows = np.array(
        [
            [1.2, 20.0, 2.0],
            [1.0, 10.0, 0.0],
            [1.1, 15.0, 1.0],
        ]
    )

    trace = normalize_trace(rows)

    assert trace.time.tolist() == [0.0, 1.0, 2.0]
    assert trace.potential.tolist() == [1.0, 1.1, 1.2]
    assert trace.current.tolist() == [10.0, 15.0, 20.0]


def test_normalize_trace_rejects_duplicate_or_nonfinite_time():
    with pytest.raises(ValueError, match="strictly increasing"):
        normalize_trace(
            np.array([[1.0, 1.0, 0.0], [1.1, 2.0, 0.0]])
        )
    with pytest.raises(ValueError, match="finite"):
        normalize_trace(
            np.array([[1.0, np.nan, 0.0], [1.1, 2.0, 1.0]])
        )


def test_residual_sign_is_experiment_minus_simulation():
    residual = residual_exp_minus_sim(
        np.array([3.0, 5.0]),
        np.array([2.0, 7.0]),
    )

    assert residual.tolist() == [1.0, -2.0]


def test_trimmed_residual_preserves_full_grid_sign():
    from oer_aem.data_contract import residual_on_grid

    full_e = np.array([1.0, 1.1, 1.2, 1.3])
    exp = np.array([1.0, 2.0, 4.0, 8.0])
    sim = np.array([0.5, 1.5, 3.0, 7.0])
    trimmed = np.array([1.1, 1.2])

    residual = residual_on_grid(full_e, exp, full_e, sim, trimmed)

    assert np.all(residual > 0.0)
