"""Shared contracts for experimental FTacV arrays and residuals."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path

import numpy as np


@dataclass(frozen=True)
class ExperimentalTrace:
    """A time-ordered `[potential, current, time]` experimental trace."""

    potential: np.ndarray
    current: np.ndarray
    time: np.ndarray


@dataclass(frozen=True)
class ExperimentalFileFacts:
    """Byte-level and rectangular-shape facts for one raw file."""

    sha256: str
    byte_count: int
    n_rows: int
    n_columns: int


GATE_A1_THRESHOLDS = {
    "expected_rows": 65535,
    "max_relative_jitter": 1e-3,
    "max_gap_ratio": 1.01,
    "min_points_per_cycle": 64.0,
    "min_complete_cycles": 20,
    "max_frequency_relative_error": 1e-3,
    "max_scan_rate_relative_error": 5e-4,
    "max_amplitude_relative_error": 5e-3,
}


def read_strict_experimental_trace(
    path: str | Path,
) -> tuple[ExperimentalTrace, ExperimentalFileFacts]:
    """Read exactly three numeric columns without repairing row order."""
    source = Path(path)
    raw = source.read_bytes()
    if not raw or not raw.strip():
        raise ValueError("experimental file must not be empty")

    rows = []
    for line_number, line in enumerate(
        raw.decode("utf-8").splitlines(), start=1
    ):
        fields = line.split()
        if len(fields) != 3:
            raise ValueError(
                f"line {line_number} must contain exactly three columns"
            )
        try:
            rows.append([float(field) for field in fields])
        except ValueError as exc:
            raise ValueError(
                f"line {line_number} must be numeric"
            ) from exc

    values = np.asarray(rows, dtype=float)
    if not np.all(np.isfinite(values)):
        raise ValueError("experimental values must be finite")
    if np.any(np.diff(values[:, 2]) <= 0):
        raise ValueError("time must be strictly increasing")

    trace = ExperimentalTrace(
        potential=values[:, 0].copy(),
        current=values[:, 1].copy(),
        time=values[:, 2].copy(),
    )
    facts = ExperimentalFileFacts(
        sha256=hashlib.sha256(raw).hexdigest(),
        byte_count=len(raw),
        n_rows=int(values.shape[0]),
        n_columns=int(values.shape[1]),
    )
    return trace, facts


def derive_sampling_diagnostics(
    trace: ExperimentalTrace,
) -> dict[str, float | int]:
    """Derive deterministic timing and applied-potential scan diagnostics."""
    time = np.asarray(trace.time, dtype=float)
    potential = np.asarray(trace.potential, dtype=float)
    current = np.asarray(trace.current, dtype=float)
    if (
        time.ndim != 1
        or potential.shape != time.shape
        or current.shape != time.shape
        or len(time) < 4
        or not np.all(np.isfinite(time))
        or not np.all(np.isfinite(potential))
        or not np.all(np.isfinite(current))
    ):
        raise ValueError("trace channels must be finite aligned vectors")

    dt = np.diff(time)
    if np.any(dt <= 0):
        raise ValueError("time must be strictly increasing")
    median_dt = float(np.median(dt))
    sampling_rate = 1.0 / median_dt
    relative_jitter = float(
        np.max(np.abs(dt - median_dt)) / median_dt
    )
    max_gap_ratio = float(np.max(dt) / median_dt)

    relative_time = time - time[0]
    design = np.column_stack(
        [relative_time, np.ones_like(relative_time)]
    )
    scan_rate, intercept = np.linalg.lstsq(
        design, potential, rcond=None
    )[0]
    detrended = potential - (
        float(scan_rate) * relative_time + float(intercept)
    )
    spectrum = np.abs(np.fft.rfft(detrended))
    frequencies = np.fft.rfftfreq(len(time), median_dt)
    if len(spectrum) < 2:
        raise ValueError("trace is too short for frequency estimation")
    peak_index = int(np.argmax(spectrum[1:]) + 1)
    frequency = float(frequencies[peak_index])
    if not np.isfinite(frequency) or frequency <= 0:
        raise ValueError("applied-potential frequency must be positive")

    omega_time = 2.0 * np.pi * frequency * relative_time
    joint_design = np.column_stack(
        [
            relative_time,
            np.ones_like(relative_time),
            np.sin(omega_time),
            np.cos(omega_time),
        ]
    )
    joint_coefficients = np.linalg.lstsq(
        joint_design, potential, rcond=None
    )[0]
    scan_rate = float(joint_coefficients[0])
    amplitude = float(
        np.hypot(joint_coefficients[2], joint_coefficients[3])
    )
    duration = float(time[-1] - time[0])
    cycles = duration * frequency

    return {
        "time_start": float(time[0]),
        "time_end": float(time[-1]),
        "duration_s": duration,
        "dt_min_s": float(np.min(dt)),
        "dt_median_s": median_dt,
        "dt_max_s": float(np.max(dt)),
        "sampling_rate_hz": float(sampling_rate),
        "max_relative_jitter": relative_jitter,
        "max_gap_ratio": max_gap_ratio,
        "frequency_hz": frequency,
        "scan_rate_v_s": float(scan_rate),
        "amplitude_v": amplitude,
        "points_per_cycle": float(sampling_rate / frequency),
        "complete_cycles": int(np.floor(cycles)),
        "cycle_remainder": float(cycles - np.floor(cycles)),
    }


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
