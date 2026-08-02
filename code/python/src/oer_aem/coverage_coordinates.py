"""Conservation-aware coordinates for the five M0 surface coverages.

The five coverages sum to one, so only four are independent.  This module
eliminates ``theta_star`` and reconstructs it without clipping or
renormalizing the supplied coordinates.
"""

from __future__ import annotations

from typing import Any

import numpy as np


COVERAGE_TOLERANCE = 1e-8


def validate_full_coverages(
    values: Any,
    *,
    tolerance: float = COVERAGE_TOLERANCE,
) -> np.ndarray:
    """Return five finite coverages on the unit-sum physical manifold."""

    coverage = np.asarray(values, dtype=float)
    if coverage.shape != (5,):
        raise ValueError("full coverages must contain five values")
    if not np.all(np.isfinite(coverage)):
        raise ValueError("full coverages must be finite")
    if float(np.min(coverage)) < -tolerance:
        raise ValueError("full coverages contain a value below zero")
    if float(np.max(coverage)) > 1.0 + tolerance:
        raise ValueError("full coverages contain a value above one")
    coverage_sum = float(np.sum(coverage))
    if abs(coverage_sum - 1.0) > tolerance:
        raise ValueError(
            f"full coverage sum must be one; received {coverage_sum:.12g}"
        )
    return coverage.copy()


def expand_independent_coverages(
    values: Any,
    *,
    tolerance: float = COVERAGE_TOLERANCE,
) -> np.ndarray:
    """Reconstruct ``theta_star`` from the other four coverages."""

    independent = np.asarray(values, dtype=float)
    if float(np.min(independent)) < -tolerance:
        raise ValueError("independent coverages contain a value below zero")
    if float(np.max(independent)) > 1.0 + tolerance:
        raise ValueError("independent coverages contain a value above one")

    full = reconstruct_conserved_coverages(independent)
    theta_star = float(full[0])
    if theta_star < -tolerance or theta_star > 1.0 + tolerance:
        raise ValueError(
            f"reconstructed theta_star is outside [0, 1]: {theta_star:.12g}"
        )
    return validate_full_coverages(full, tolerance=tolerance)


def reconstruct_conserved_coverages(values: Any) -> np.ndarray:
    """Reconstruct unit-sum coverages for an internal solver trial point.

    Adaptive ODE solvers may evaluate finite trial points just outside the
    physical bounds.  This function preserves the conservation coordinate
    exactly but deliberately leaves physical-bound checks to accepted output
    points.
    """

    independent = np.asarray(values, dtype=float)
    if independent.shape != (4,):
        raise ValueError("independent coverages must contain four values")
    if not np.all(np.isfinite(independent)):
        raise ValueError("independent coverages must be finite")
    theta_star = 1.0 - float(np.sum(independent))
    return np.concatenate([[theta_star], independent])


def reduce_full_coverages(
    values: Any,
    *,
    tolerance: float = COVERAGE_TOLERANCE,
) -> np.ndarray:
    """Validate five coverages and remove the dependent ``theta_star``."""

    return validate_full_coverages(values, tolerance=tolerance)[1:]


def validate_reduced_trajectory(
    values: Any,
    *,
    tolerance: float = COVERAGE_TOLERANCE,
) -> np.ndarray:
    """Validate accepted reduced output points and return full states."""

    trajectory = np.asarray(values, dtype=float)
    if trajectory.ndim != 2 or trajectory.shape[1] != 5:
        raise ValueError(
            "reduced trajectory must have four coverages plus potential"
        )
    if not np.all(np.isfinite(trajectory)):
        raise ValueError("reduced trajectory must be finite")

    rows = []
    for index, state in enumerate(trajectory):
        try:
            coverage = validate_full_coverages(
                reconstruct_conserved_coverages(state[:4]),
                tolerance=tolerance,
            )
        except ValueError as exc:
            raise ValueError(f"invalid reduced output row {index}: {exc}") from exc
        rows.append(np.concatenate([coverage, [state[4]]]))
    return np.asarray(rows, dtype=float)
