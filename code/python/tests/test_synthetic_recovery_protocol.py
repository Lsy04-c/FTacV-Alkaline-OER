"""Tests for the Gate A6 multi-parameter recovery protocol."""

import numpy as np
import pytest

from oer_aem.inversion import DEFAULT_PARAM_SPECS, encode_params
from oer_aem.recovery import (
    build_recovery_jobs,
    estimate_white_noise_fraction,
    noise_fraction_evidence,
    recovery_metrics,
    truth_library,
)


def test_truth_library_has_three_distinct_interior_cases():
    truths = truth_library(DEFAULT_PARAM_SPECS)

    assert [case["truth_id"] for case in truths] == [
        "center",
        "mixed_a",
        "mixed_b",
    ]
    encoded = np.vstack(
        [encode_params(case["parameters"], DEFAULT_PARAM_SPECS) for case in truths]
    )
    lows = np.array([spec[2] for spec in DEFAULT_PARAM_SPECS])
    highs = np.array([spec[3] for spec in DEFAULT_PARAM_SPECS])
    assert np.all(encoded > lows)
    assert np.all(encoded < highs)
    assert len({tuple(row) for row in encoded}) == 3


def test_recovery_metrics_use_encoded_error_and_boundary_hits():
    specs = (
        ("rate", "log10", 0.0, 4.0),
        ("energy", "linear", 1.0, 3.0),
    )
    metrics = recovery_metrics(
        truth={"rate": 100.0, "energy": 2.0},
        estimate={"rate": 1000.0, "energy": 2.2},
        specs=specs,
    )

    assert metrics["rate"]["encoded_absolute_error"] == 1.0
    assert metrics["rate"]["normalized_bound_error"] == 0.25
    assert metrics["energy"]["encoded_absolute_error"] == pytest.approx(0.2)
    assert metrics["boundary_hits"] == []


def test_job_builder_pairs_modes_truths_noise_and_seeds():
    jobs = build_recovery_jobs(
        modes=("legacy", "hybrid"),
        truths=truth_library(DEFAULT_PARAM_SPECS)[:2],
        noise_fractions=(0.0, 0.001),
        seeds=(7, 17),
        trials=50,
    )

    assert len(jobs) == 2 * 2 * 2 * 2
    assert {job["trials"] for job in jobs} == {50}
    assert len({job["job_id"] for job in jobs}) == len(jobs)


def test_noise_fraction_estimator_recovers_added_white_noise():
    rng = np.random.default_rng(11)
    time = np.linspace(0.0, 20.0, 20_000, endpoint=False)
    smooth_signal = np.sin(2.0 * np.pi * time)
    noisy_signal = smooth_signal + rng.normal(0.0, 0.01, size=time.size)

    estimate = estimate_white_noise_fraction(noisy_signal)

    assert estimate == pytest.approx(0.01 / np.max(np.abs(noisy_signal)), rel=0.15)


def test_noise_fraction_estimator_falls_back_to_quantization_floor():
    smooth = np.sin(np.linspace(0.0, 4.0 * np.pi, 20_000))
    quantized = np.round(smooth / 0.01) * 0.01

    estimate = estimate_white_noise_fraction(quantized)

    expected_floor = 0.01 / np.sqrt(12.0) / np.max(np.abs(quantized))
    assert estimate == pytest.approx(expected_floor, rel=0.05)
    evidence = noise_fraction_evidence(quantized)
    assert evidence["method"] == "quantization_floor"
    assert evidence["zero_difference_fraction"] > 0.5
    assert evidence["quantization_step"] == pytest.approx(0.01)
