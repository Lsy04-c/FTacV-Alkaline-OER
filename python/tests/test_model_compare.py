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
