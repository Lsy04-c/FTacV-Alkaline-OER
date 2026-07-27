"""Deterministic objective-profile grids and discrete summaries."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

import numpy as np


COORDINATE_ATOL = 1e-12


def profile_grid(truth_coordinate: float, grid_points: int = 41) -> np.ndarray:
    """Return a sorted unit grid that includes the exact truth coordinate."""
    truth = float(truth_coordinate)
    if not np.isfinite(truth) or truth < 0.0 or truth > 1.0:
        raise ValueError("truth coordinate must be finite and within [0, 1]")
    if int(grid_points) != grid_points or grid_points < 3:
        raise ValueError("grid_points must be an integer of at least 3")
    base = np.linspace(0.0, 1.0, int(grid_points))
    matches = np.isclose(
        base,
        truth,
        rtol=0.0,
        atol=COORDINATE_ATOL,
    )
    if np.any(matches):
        base[matches] = truth
        return np.unique(base)
    return np.sort(np.concatenate((base, np.asarray([truth]))))


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
    truth_matches = np.flatnonzero(
        np.isclose(
            coordinates,
            truth,
            rtol=0.0,
            atol=COORDINATE_ATOL,
        )
    )
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


# ---------------------------------------------------------------------------
# Two-parameter (2D) profiles
# ---------------------------------------------------------------------------

def profile_grid_2d(
    x_truth: float,
    y_truth: float,
    grid_points: int = 21,
) -> np.ndarray:
    """Cartesian product of two 1D grids, each including its truth coordinate.

    Returns shape (N, 2) where N = grid_points^2 (truth unique) or
    (grid_points+1)^2 (truths inserted).
    """
    xs = profile_grid(x_truth, grid_points)
    ys = profile_grid(y_truth, grid_points)
    xv, yv = np.meshgrid(xs, ys)
    return np.column_stack((xv.ravel(), yv.ravel()))


def summarize_profile_2d(
    rows: Sequence[Mapping[str, Any]],
    *,
    x_truth: float,
    y_truth: float,
    x_param: str,
    y_param: str,
) -> dict[str, Any]:
    """Summarize a 2D objective profile.

    Returns coupling diagnostics: whether the two parameters compensate along
    a diagonal valley (coupling) vs acting independently (orthogonal to axes).
    """
    if not rows:
        raise ValueError("profile rows must not be empty")
    xs = np.asarray([float(r["x_coordinate"]) for r in rows], dtype=float)
    ys = np.asarray([float(r["y_coordinate"]) for r in rows], dtype=float)
    losses = np.asarray([float(r["total_loss"]) for r in rows], dtype=float)
    finite = np.isfinite(xs) & np.isfinite(ys) & np.isfinite(losses)

    # Truth point
    truth_mask = (
        np.isclose(xs, x_truth, atol=1e-12)
        & np.isclose(ys, y_truth, atol=1e-12)
    )
    if truth_mask.sum() != 1 or not finite[truth_mask][0]:
        raise ValueError("truth must appear exactly once with finite loss")
    truth_idx = int(np.flatnonzero(truth_mask)[0])

    finite_mask = finite
    min_loss = float(np.min(losses[finite_mask]))
    min_mask = finite_mask & np.isclose(losses, min_loss, rtol=1e-12, atol=1e-15)
    is_global_min_at_truth = bool(min_mask[truth_idx])

    # 1D marginal diagnostics
    near_truth_x = finite_mask & np.isclose(ys, y_truth, atol=1e-12)
    near_truth_y = finite_mask & np.isclose(xs, x_truth, atol=1e-12)

    def _marginal_width(mask, coords):
        valid = coords[mask]
        if valid.size < 2:
            return 0.0
        return float(np.max(valid) - np.min(valid))

    delta1_x_width = _marginal_width(
        near_truth_x & (losses <= min_loss + 1.0), xs
    )
    delta1_y_width = _marginal_width(
        near_truth_y & (losses <= min_loss + 1.0), ys
    )

    # Coupling: diagonal valley vs orthogonal
    # If parameters compensate, the minimum valley is diagonal (|x+y| ≈ const).
    # If independent, the valley aligns with axes.
    delta1_mask = finite_mask & (losses <= min_loss + 1.0)
    if delta1_mask.sum() >= 3:
        cov = np.cov(xs[delta1_mask], ys[delta1_mask])
        pearson_r = float(
            cov[0, 1] / np.sqrt(cov[0, 0] * cov[1, 1])
            if cov[0, 0] > 0 and cov[1, 1] > 0
            else 0.0
        )
    else:
        pearson_r = 0.0

    coupling_strength = abs(pearson_r)

    return {
        "x_truth": x_truth,
        "y_truth": y_truth,
        "truth_loss": float(losses[truth_idx]),
        "min_loss": min_loss,
        "is_global_min_at_truth": is_global_min_at_truth,
        "delta1_x_width": delta1_x_width,
        "delta1_y_width": delta1_y_width,
        "pearson_r_in_delta1": pearson_r,
        "coupling_strength": coupling_strength,
        "coupling_interpretation": (
            "compensating (diagonal valley)"
            if coupling_strength > 0.7
            else (
                "independent (orthogonal to axes)"
                if coupling_strength < 0.3
                else "moderate coupling"
            )
        ),
        "finite_fraction": float(np.mean(finite_mask)),
        "sampled_points": int(len(rows)),
        "x_param": x_param,
        "y_param": y_param,
        "interval_semantics": "objective diagnostic, not confidence interval",
    }
