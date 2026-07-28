"""Contracts for experimental FTacV arrays and residual signs."""

import numpy as np
import pytest

from oer_aem.data_contract import (
    ExperimentalTrace,
    derive_sampling_diagnostics,
    normalize_trace,
    read_strict_experimental_trace,
    residual_exp_minus_sim,
)


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


def test_normalized_channels_are_scale_invariant():
    from oer_aem.data_contract import normalize_by_max_abs

    experiment = normalize_by_max_abs(np.array([1.0, 2.0, 4.0]))
    simulation = normalize_by_max_abs(np.array([10.0, 20.0, 40.0]))

    assert residual_exp_minus_sim(experiment, simulation) == pytest.approx(
        np.zeros(3)
    )


def test_strict_trace_preserves_original_rows(tmp_path):
    path = tmp_path / "trace.txt"
    path.write_text("1.0 2.0 0.0\n1.1 3.0 0.5\n")

    trace, facts = read_strict_experimental_trace(path)

    assert trace.potential.tolist() == [1.0, 1.1]
    assert trace.current.tolist() == [2.0, 3.0]
    assert trace.time.tolist() == [0.0, 0.5]
    assert facts.n_rows == 2
    assert facts.n_columns == 3
    assert facts.byte_count == path.stat().st_size


@pytest.mark.parametrize(
    ("content", "match"),
    [
        ("1 2\n", "exactly three"),
        ("1 2 3 4\n", "exactly three"),
        ("potential current time\n1 2 0\n", "numeric"),
        ("1 nan 0\n", "finite"),
        ("1 2 0\n2 3 0\n", "strictly increasing"),
        ("1 2 1\n2 3 0\n", "strictly increasing"),
        ("\n", "must not be empty"),
    ],
)
def test_strict_trace_rejects_invalid_raw_structure(
    tmp_path, content, match
):
    path = tmp_path / "trace.txt"
    path.write_text(content)

    with pytest.raises(ValueError, match=match):
        read_strict_experimental_trace(path)


def test_sampling_diagnostics_recover_known_signal():
    fs = 1280.0
    time = np.arange(0.0, 20.0, 1.0 / fs)
    potential = (
        1.0
        + 0.01 * time
        + 0.16 * np.sin(2.0 * np.pi * 5.0 * time)
    )
    trace = ExperimentalTrace(
        potential=potential,
        current=np.zeros_like(time),
        time=time + 7.0,
    )

    result = derive_sampling_diagnostics(trace)

    assert result["sampling_rate_hz"] == pytest.approx(fs, rel=1e-12)
    assert result["frequency_hz"] == pytest.approx(5.0, rel=1e-6)
    assert result["scan_rate_v_s"] == pytest.approx(0.01, rel=1e-6)
    assert result["amplitude_v"] == pytest.approx(0.16, rel=1e-6)
    assert result["points_per_cycle"] == pytest.approx(256.0, rel=1e-6)
    assert result["complete_cycles"] == 99


def test_sampling_diagnostics_expose_gap_and_jitter():
    time = np.arange(0.0, 4.0, 0.001)
    time = np.delete(time, 2000)
    potential = (
        1.0
        + 0.01 * time
        + 0.16 * np.sin(2.0 * np.pi * 5.0 * time)
    )
    trace = ExperimentalTrace(
        potential=potential,
        current=np.zeros_like(time),
        time=time,
    )

    result = derive_sampling_diagnostics(trace)

    assert result["max_gap_ratio"] == pytest.approx(2.0)
    assert result["max_relative_jitter"] == pytest.approx(1.0)
