"""Contracts for exact-truth local identifiability diagnostics."""

import numpy as np

from scripts.run_truth_identifiability_smoke import (
    parameter_unit_coordinate,
    propagation_coordinates,
    parse_args,
    profile_coordinates,
)


def test_profile_coordinates_are_unique_bounded_and_include_truth():
    coordinates = profile_coordinates(0.05)

    np.testing.assert_allclose(coordinates, [0.0, 0.05, 0.1, 0.15])
    assert all(0.0 <= value <= 1.0 for value in coordinates)


def test_truth_identifiability_runner_requires_output(tmp_path):
    args = parse_args(["--output", str(tmp_path / "truth-rank")])

    assert args.output == tmp_path / "truth-rank"


def test_propagation_coordinates_cover_bounds_truth_and_default():
    coordinates = propagation_coordinates(0.6, 0.8371, grid_size=5)

    np.testing.assert_allclose(coordinates, [0.0, 0.25, 0.5, 0.6, 0.75, 0.8371, 1.0])


def test_model_default_coordinate_is_computed_from_unmodified_default():
    spec = ("k0_4", "log10", -3.0, 6.0)

    coordinate = parameter_unit_coordinate(5000.0, spec)

    np.testing.assert_allclose(coordinate, (np.log10(5000.0) + 3.0) / 9.0)
    assert not np.isclose(coordinate, 0.6)
