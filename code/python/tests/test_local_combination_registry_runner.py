"""Contracts for the auditable local-combination registry."""

import numpy as np

from scripts.run_local_combination_registry import (
    direction_angle_degrees,
    evaluate_context,
    physical_goh_logk01_coefficient,
)


def _summary(k01=-0.5141514767, goh=0.8576396278, selection=0.0039):
    return {
        "status": "SUCCESS",
        "parameter_names": [
            "k0_1", "k0_2", "k0_3", "G_OH", "G_O", "scaling_OOH_OH"
        ],
        "direction_validation": [
            {
                "direction": 6,
                "training_singular_value": 0.0012,
                "selection_maximum_absolute_motion": selection,
                "loadings": {
                    "k0_1": k01,
                    "k0_2": 0.0,
                    "k0_3": 0.0,
                    "G_OH": goh,
                    "G_O": 0.0,
                    "scaling_OOH_OH": 0.0,
                },
            }
        ],
    }


def _schema():
    return {
        "parameters": {
            "k0_1": {"transform": "log10", "bounds": [1e-3, 1e6]},
            "G_OH": {"transform": "linear", "bounds": [0.5, 2.2]},
        }
    }


def test_physical_coefficient_is_reconstructed_from_schema_bounds():
    coefficient = physical_goh_logk01_coefficient(_summary(), _schema())

    np.testing.assert_allclose(coefficient, 0.1132381224, rtol=1e-8)


def test_direction_angle_is_invariant_to_svd_sign():
    left = _summary()
    right = _summary(k01=0.5141514767, goh=-0.8576396278)

    assert direction_angle_degrees(left, right) == 0.0


def test_context_requires_pair_dominance_and_selection_stability():
    accepted = evaluate_context(_summary(), _schema())
    rejected = evaluate_context(_summary(selection=0.03), _schema())

    assert accepted["local_geometry_gate"] is True
    assert accepted["goh_k01_loading_square_sum"] >= 0.95
    assert rejected["local_geometry_gate"] is False
