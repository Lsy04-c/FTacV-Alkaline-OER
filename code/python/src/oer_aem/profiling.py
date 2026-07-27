"""Deterministic objective-profile grids and discrete summaries."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

import numpy as np


def profile_grid(truth_coordinate: float, grid_points: int = 41) -> np.ndarray:
    """Return a sorted unit grid that includes the exact truth coordinate."""
    truth = float(truth_coordinate)
    if not np.isfinite(truth) or truth < 0.0 or truth > 1.0:
        raise ValueError("truth coordinate must be finite and within [0, 1]")
    if int(grid_points) != grid_points or grid_points < 3:
        raise ValueError("grid_points must be an integer of at least 3")
    base = np.linspace(0.0, 1.0, int(grid_points))
    return np.unique(np.concatenate((base, np.asarray([truth]))))


def summarize_profile(
    rows: Sequence[Mapping[str, Any]],
    *,
    truth_coordinate: float,
) -> dict[str, Any]:
    """Summarize sampled profile geometry without statistical interpretation."""
    if not rows:
        raise ValueError("profile rows must not be empty")
    truth = float(truth_coordinate)
    coordinates = np.asarray(
        [float(row["normalized_coordinate"]) for row in rows],
        dtype=float,
    )
    losses = np.asarray([float(row["total_loss"]) for row in rows], dtype=float)
    ode_success = np.asarray(
        [bool(row.get("ode_success", True)) for row in rows],
        dtype=bool,
    )
    finite = np.isfinite(coordinates) & np.isfinite(losses) & ode_success
    truth_matches = np.flatnonzero(np.isclose(coordinates, truth, atol=1e-14))
    if truth_matches.size != 1:
        raise ValueError("profile must contain the truth coordinate exactly once")
    truth_index = int(truth_matches[0])
    if not finite[truth_index]:
        raise ValueError("truth loss must be finite with a successful ODE solve")

    finite_indices = np.flatnonzero(finite)
    minimum_loss = float(np.min(losses[finite]))
    minimizers = finite_indices[
        np.isclose(losses[finite], minimum_loss, rtol=1e-12, atol=1e-15)
    ]
    minimum_index = int(
        minimizers[np.argmin(np.abs(coordinates[minimizers] - truth))]
    )

    left = finite_indices[coordinates[finite_indices] < truth]
    right = finite_indices[coordinates[finite_indices] > truth]
    curvature = None
    if left.size and right.size:
        left_index = int(left[np.argmax(coordinates[left])])
        right_index = int(right[np.argmin(coordinates[right])])
        x_left, x_mid, x_right = coordinates[
            [left_index, truth_index, right_index]
        ]
        y_left, y_mid, y_right = losses[
            [left_index, truth_index, right_index]
        ]
        curvature = float(
            2.0
            * (
                (y_right - y_mid) / (x_right - x_mid)
                - (y_mid - y_left) / (x_mid - x_left)
            )
            / (x_right - x_left)
        )

    def interval_width(delta: float) -> float:
        selected = coordinates[finite & (losses <= minimum_loss + delta)]
        return float(np.max(selected) - np.min(selected))

    remote_near_minimum = bool(
        np.any(
            finite
            & (np.abs(coordinates - truth) >= 0.25)
            & (losses <= minimum_loss + 1.0)
        )
    )
    return {
        "truth_coordinate": truth,
        "truth_loss": float(losses[truth_index]),
        "truth_is_global_minimum": bool(
            np.isclose(
                losses[truth_index],
                minimum_loss,
                rtol=1e-12,
                atol=1e-15,
            )
        ),
        "minimum_coordinate": float(coordinates[minimum_index]),
        "minimum_loss": minimum_loss,
        "minimum_truth_distance": float(
            abs(coordinates[minimum_index] - truth)
        ),
        "local_curvature": curvature,
        "delta_1_width": interval_width(1.0),
        "delta_10_width": interval_width(10.0),
        "finite_fraction": float(np.mean(finite)),
        "ode_failures": int(np.sum(~ode_success)),
        "tafel_failures": int(
            sum(bool(row.get("tafel_failed", False)) for row in rows)
        ),
        "remote_delta_1_minimum": remote_near_minimum,
        "interval_semantics": "objective diagnostic, not confidence interval",
    }
