"""Tests for the minimal M0/M1 reconstruction acceptance gate."""

from oer_aem.model_compare import information_criteria, reconstruction_gate


def test_information_criteria_penalize_extra_parameters():
    m0 = information_criteria(
        loss=100.0,
        n_observations=200,
        n_parameters=8,
    )
    m1 = information_criteria(
        loss=99.9,
        n_observations=200,
        n_parameters=9,
    )

    assert m1["bic"] > m0["bic"]


def test_reconstruction_gate_requires_three_datasets_and_stable_thermodynamics():
    rows = [
        {
            "improved": True,
            "harmonics_not_worse": True,
            "boundary_hit": False,
        }
        for _ in range(3)
    ] + [
        {
            "improved": False,
            "harmonics_not_worse": True,
            "boundary_hit": False,
        }
    ]

    assert reconstruction_gate(rows, thermo_cv_ratio=1.05)["accepted"] is True
    assert reconstruction_gate(rows, thermo_cv_ratio=1.30)["accepted"] is False


def test_reconstruction_gate_requires_complexity_support_when_reported():
    rows = [
        {
            "improved": True,
            "harmonics_not_worse": True,
            "boundary_hit": False,
            "complexity_supported": True,
        }
        for _ in range(3)
    ]
    rows[0]["complexity_supported"] = False

    assert reconstruction_gate(
        rows,
        thermo_cv_ratio=1.0,
        required_datasets=3,
    )["accepted"] is False


def test_script_gate_requires_paired_seed_majority():
    from scripts.compare_reconstruction_model import (
        MODELS,
        SEEDS,
        _apply_gate,
    )
    from scripts.compare_feature_objectives import DATASETS

    rows = []
    for dataset in DATASETS:
        for model in MODELS:
            for seed in SEEDS:
                m1_wins = model == "M1" and seed == SEEDS[-1]
                rows.append(
                    {
                        "dataset": dataset,
                        "model": model,
                        "seed": seed,
                        "high_potential_rmse": 0.5 if m1_wins else 1.0,
                        "high_potential_shape_rmse": 0.5 if m1_wins else 1.0,
                        "h1_h3_loss": 0.5 if m1_wins else 1.0,
                        "bic": 0.5 if m1_wins else 1.0,
                        "beta_boundary_hit": False,
                        "G_OH": 1.0,
                        "G_O": 2.0,
                        "scaling_OOH_OH": 3.0,
                    }
                )

    gate = _apply_gate(rows)

    assert gate["datasets_passed"] == 0
    assert gate["accepted"] is False
