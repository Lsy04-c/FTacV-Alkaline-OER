"""Shared contracts for experimental FTacV arrays and residuals."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class ExperimentalTrace:
    """A time-ordered `[potential, current, time]` experimental trace."""

    potential: np.ndarray
    current: np.ndarray
    time: np.ndarray


def normalize_by_max_abs(values: np.ndarray) -> np.ndarray:
    """Normalize one channel by its finite maximum absolute magnitude."""
    array = np.asarray(values, dtype=float)
    scale = float(np.max(np.abs(array))) if array.size else 0.0
    if not np.isfinite(scale) or scale <= 1e-30:
        scale = 1e-30
    return array / scale


def normalize_trace(rows: np.ndarray) -> ExperimentalTrace:
    """Validate, sort by time, and shift the first time point to zero."""
    values = np.asarray(rows, dtype=float)
    if values.ndim != 2 or values.shape[1] < 3:
        raise ValueError(
            "experimental rows must have potential, current, time columns"
        )
    values = values[:, :3]
    if not np.all(np.isfinite(values)):
        raise ValueError("experimental rows must be finite")

    order = np.argsort(values[:, 2], kind="stable")
    ordered = values[order]
    time = ordered[:, 2]
    if np.any(np.diff(time) <= 0):
        raise ValueError("time must be strictly increasing")

    return ExperimentalTrace(
        potential=ordered[:, 0],
        current=ordered[:, 1],
        time=time - time[0],
    )


def residual_exp_minus_sim(
    experiment: np.ndarray,
    simulation: np.ndarray,
) -> np.ndarray:
    """Return the project-wide residual convention: experiment - simulation."""
    experiment = np.asarray(experiment, dtype=float)
    simulation = np.asarray(simulation, dtype=float)
    if experiment.shape != simulation.shape:
        raise ValueError(
            "experiment and simulation must have identical shapes"
        )
    return experiment - simulation


def residual_on_grid(
    exp_e: np.ndarray,
    exp_i: np.ndarray,
    sim_e: np.ndarray,
    sim_i: np.ndarray,
    common_e: np.ndarray,
) -> np.ndarray:
    """Interpolate experiment and simulation before applying the residual sign."""
    common_e = np.asarray(common_e, dtype=float)
    exp_interp = np.interp(
        common_e,
        np.asarray(exp_e, dtype=float),
        np.asarray(exp_i, dtype=float),
    )
    sim_interp = np.interp(
        common_e,
        np.asarray(sim_e, dtype=float),
        np.asarray(sim_i, dtype=float),
    )
    return residual_exp_minus_sim(exp_interp, sim_interp)
