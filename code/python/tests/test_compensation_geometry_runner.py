"""Contracts for low-loss compensation-geometry aggregation."""

import numpy as np

from scripts.run_compensation_geometry import reconstruct_candidate


def test_reconstruct_candidate_places_profile_and_complement_by_name():
    candidate = reconstruct_candidate(
        parameter_names=("a", "b", "c"),
        profiled_parameter="b",
        profile_coordinate=0.7,
        complement_names=("a", "c"),
        complement_unit=np.array([0.2, 0.4]),
    )

    np.testing.assert_allclose(candidate, [0.2, 0.7, 0.4])
