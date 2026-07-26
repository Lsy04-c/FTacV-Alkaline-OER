"""Tests for the Gate A6 multi-parameter recovery protocol."""

import numpy as np
import pytest

from oer_aem.inversion import DEFAULT_PARAM_SPECS, encode_params
from oer_aem.recovery import (
    build_budget_pilot_jobs,
    build_recovery_jobs,
    estimate_white_noise_fraction,
    noise_fraction_evidence,
    recovery_metrics,
    select_trial_budget,
    summarize_recovery,
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
    paired_target_seeds = {}
    for job in jobs:
        key = (job["truth_id"], job["noise_fraction"])
        paired_target_seeds.setdefault(key, set()).add(job["target_seed"])
    assert all(len(seeds) == 1 for seeds in paired_target_seeds.values())


def test_budget_pilot_uses_all_modes_one_hard_case_and_three_budgets():
    jobs = build_budget_pilot_jobs(
        modes=("legacy", "complex_snr", "lockin_only", "hybrid"),
        truths=truth_library(DEFAULT_PARAM_SPECS),
        noise_fraction=0.0015,
        seeds=(7, 17, 27),
        budgets=(20, 50, 100),
    )

    assert len(jobs) == 4 * 3 * 3
    assert {job["truth_id"] for job in jobs} == {"mixed_b"}
    assert {job["noise_fraction"] for job in jobs} == {0.0015}
    assert {job["trials"] for job in jobs} == {20, 50, 100}


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


def test_budget_selection_rejects_unstable_20_and_accepts_50():
    rows = []
    for mode in ("legacy", "hybrid"):
        for seed in (7, 17, 27):
            reference = 0.10 + 0.001 * seed
            for trials, error, boundaries in (
                (20, reference + 0.10, ["k0_1"]),
                (50, reference + 0.01, []),
                (100, reference, []),
            ):
                rows.append(
                    {
                        "feature_mode": mode,
                        "truth_id": "mixed_b",
                        "noise_fraction": 0.0015,
                        "seed": seed,
                        "trials": trials,
                        "success": True,
                        "parameter_metrics": {
                            "max_normalized_bound_error": error,
                            "boundary_hits": boundaries,
                        },
                    }
                )

    selection = select_trial_budget(rows)

    assert selection["selected_trials"] == 50
    assert selection["budgets"]["20"]["passed"] is False
    assert selection["budgets"]["50"]["passed"] is True
    assert selection["thresholds"] == {
        "median_paired_error_delta_max": 0.02,
        "p90_paired_error_delta_max": 0.05,
        "boundary_set_agreement_min": 0.8,
    }


def test_recovery_summary_reports_seed_range_coverage():
    rows = []
    for seed, estimate in ((7, 8.0), (17, 10.0), (27, 12.0)):
        rows.append(
            {
                "feature_mode": "legacy",
                "truth_id": "center",
                "truth_params": {"rate": 10.0},
                "noise_fraction": 0.0,
                "seed": seed,
                "trials": 50,
                "success": True,
                "best_params": {"rate": estimate},
                "parameter_metrics": {
                    "rate": {
                        "normalized_bound_error": abs(estimate - 10.0) / 100.0,
                        "boundary_hit": False,
                    },
                    "boundary_hits": [],
                    "max_normalized_bound_error": abs(estimate - 10.0) / 100.0,
                },
            }
        )

    summary = summarize_recovery(rows, parameter_names=("rate",))
    parameter = summary["groups"][0]["parameters"]["rate"]

    assert parameter["seed_min"] == 8.0
    assert parameter["seed_max"] == 12.0
    assert parameter["truth_covered_by_seed_range"] is True
    assert parameter["boundary_hit_rate"] == 0.0
