"""Tests for the four-coordinate representation of five coverages."""

import sys
from pathlib import Path

import numpy as np
import pytest


SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

from oer_aem.coverage_coordinates import (
    expand_independent_coverages,
    reconstruct_conserved_coverages,
    reduce_full_coverages,
    validate_reduced_trajectory,
)


def test_four_coordinates_reconstruct_unit_sum_full_coverages():
    reduced = np.array([0.25, 0.20, 0.18, 0.22])

    full = expand_independent_coverages(reduced)

    np.testing.assert_allclose(
        full,
        np.array([0.15, 0.25, 0.20, 0.18, 0.22]),
        rtol=0.0,
        atol=1e-15,
    )
    np.testing.assert_allclose(
        reduce_full_coverages(full), reduced, rtol=0.0, atol=0.0
    )


def test_invalid_reconstructed_eliminated_coverage_is_rejected():
    with pytest.raises(ValueError, match="theta_star"):
        expand_independent_coverages(np.array([0.4, 0.3, 0.2, 0.2]))


@pytest.mark.parametrize(
    "values",
    [
        np.array([0.2, 0.2, 0.2]),
        np.array([0.2, 0.2, 0.2, np.nan]),
        np.array([0.2, -0.1, 0.2, 0.2]),
    ],
)
def test_independent_coverages_require_four_finite_physical_values(values):
    with pytest.raises(ValueError):
        expand_independent_coverages(values)


def test_reduction_rejects_off_manifold_full_coverages():
    with pytest.raises(ValueError, match="sum"):
        reduce_full_coverages(np.array([0.3, 0.3, 0.3, 0.3, 0.3]))


def test_conservation_reconstruction_does_not_clip_internal_trial_point():
    trial = np.array([-9.26e-8, 0.0, 0.0, 0.0])

    full = reconstruct_conserved_coverages(trial)

    assert full[0] == pytest.approx(1.0 + 9.26e-8)
    assert full[1] == pytest.approx(-9.26e-8)
    assert np.sum(full) == pytest.approx(1.0, abs=1e-15)


def test_output_trajectory_validation_rejects_same_trial_point():
    trajectory = np.array([[-9.26e-8, 0.0, 0.0, 0.0, 1.45]])

    with pytest.raises(ValueError, match="output row 0"):
        validate_reduced_trajectory(trajectory)
