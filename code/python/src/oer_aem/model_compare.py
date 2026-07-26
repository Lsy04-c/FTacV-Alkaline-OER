"""Metrics and explicit acceptance gates for nested reconstruction models."""

from __future__ import annotations

import math
from typing import Any, Mapping, Sequence


def information_criteria(
    loss: float,
    n_observations: int,
    n_parameters: int,
) -> dict[str, float]:
    """Return Gaussian-residual AIC and BIC for a residual sum of squares."""
    scaled = max(float(loss) / int(n_observations), 1e-300)
    return {
        "aic": n_observations * math.log(scaled) + 2 * n_parameters,
        "bic": (
            n_observations * math.log(scaled)
            + n_parameters * math.log(n_observations)
        ),
    }


def reconstruction_gate(
    rows: Sequence[Mapping[str, Any]],
    thermo_cv_ratio: float,
    required_datasets: int = 3,
    max_cv_ratio: float = 1.15,
) -> dict[str, Any]:
    """Apply the fixed majority, harmonic, boundary, and stability gate."""
    passed = sum(
        bool(row["improved"])
        and bool(row["harmonics_not_worse"])
        and not bool(row["boundary_hit"])
        and bool(row.get("complexity_supported", True))
        for row in rows
    )
    accepted = (
        passed >= required_datasets
        and float(thermo_cv_ratio) <= max_cv_ratio
    )
    return {
        "accepted": accepted,
        "datasets_passed": passed,
        "thermo_cv_ratio": float(thermo_cv_ratio),
    }
