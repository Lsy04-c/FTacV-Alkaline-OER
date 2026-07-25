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
