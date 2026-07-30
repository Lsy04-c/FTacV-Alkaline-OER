"""Pure contracts for model-conditional FTacV experiment design."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

import numpy as np


def segment_masks(n_grid: int) -> dict[str, np.ndarray]:
    """Return deterministic low, middle and high grid segments."""
    if n_grid < 3:
        raise ValueError("feature grid must contain at least three points")
    low_end = int(np.ceil(0.2 * n_grid))
    high_start = int(np.floor(0.8 * n_grid))
    index = np.arange(n_grid)
    return {
        "low": index < low_end,
        "mid": (index >= low_end) & (index < high_start),
        "high": index >= high_start,
    }


def block_feature_vector(
    features: Mapping[str, Any],
    harmonics: Sequence[int] = (1, 2, 3),
) -> tuple[tuple[str, ...], np.ndarray, tuple[bool, ...]]:
    """Reduce DC and complex H1-H3 features to 27 equally counted blocks."""
    dc = np.asarray(features["dc"], dtype=float).reshape(-1)
    if dc.size < 3 or not np.all(np.isfinite(dc)):
        raise ValueError("DC feature must contain a finite grid")
    masks = segment_masks(dc.size)
    names: list[str] = []
    values: list[float] = []
    observable: list[bool] = []

    for segment, mask in masks.items():
        names.append(f"dc:{segment}")
        values.append(float(np.mean(dc[mask])))
        observable.append(True)

    global_values = np.asarray(
        features["complex_harmonics"]["complex"],
        dtype=complex,
    ).reshape(-1)
    lockin_values = features["lockin"]["complex"]
    valid = np.asarray(
        features["lockin"]["valid_mask"],
        dtype=bool,
    ).reshape(-1)
    if valid.shape != dc.shape:
        raise ValueError("lock-in valid mask must match the DC grid")

    for harmonic in harmonics:
        index = int(harmonic) - 1
        if index < 0 or index >= global_values.size:
            raise ValueError(f"missing global harmonic H{harmonic}")
        coefficient = global_values[index]
        for component, value in (
            ("real", coefficient.real),
            ("imag", coefficient.imag),
        ):
            names.append(f"global_h{harmonic}_{component}:global")
            values.append(float(value))
            observable.append(bool(np.isfinite(value)))

    for harmonic in harmonics:
        index = int(harmonic) - 1
        if index < 0 or index >= len(lockin_values):
            raise ValueError(f"missing lock-in harmonic H{harmonic}")
        channel = np.asarray(lockin_values[index], dtype=complex).reshape(-1)
        if channel.shape != dc.shape:
            raise ValueError("lock-in channel must match the DC grid")
        for component, component_values in (
            ("real", channel.real),
            ("imag", channel.imag),
        ):
            for segment, mask in masks.items():
                active = mask & valid & np.isfinite(component_values)
                names.append(f"lockin_h{harmonic}_{component}:{segment}")
                if np.any(active):
                    values.append(float(np.mean(component_values[active])))
                    observable.append(True)
                else:
                    values.append(float("nan"))
                    observable.append(False)

    if len(names) != 27 or len(set(names)) != len(names):
        raise ValueError("V4 block feature contract must contain 27 unique rows")
    return tuple(names), np.asarray(values, dtype=float), tuple(observable)


def central_sensitivity(
    plus: Sequence[float],
    minus: Sequence[float],
    baseline: Sequence[float],
    parameter_span: float,
) -> np.ndarray:
    """Return a signed central difference normalized by baseline magnitude."""
    plus_values = np.asarray(plus, dtype=float)
    minus_values = np.asarray(minus, dtype=float)
    baseline_values = np.asarray(baseline, dtype=float)
    if (
        plus_values.shape != minus_values.shape
        or plus_values.shape != baseline_values.shape
    ):
        raise ValueError("sensitivity vectors must have matching shapes")
    if not all(
        np.all(np.isfinite(values))
        for values in (plus_values, minus_values, baseline_values)
    ):
        raise ValueError("sensitivity vectors must be finite")
    span = float(parameter_span)
    if not np.isfinite(span) or abs(span) <= np.finfo(float).eps:
        raise ValueError("parameter span must be finite and non-zero")
    maximum = max(float(np.max(np.abs(baseline_values))), 1e-30)
    scale = np.maximum(np.abs(baseline_values), maximum * 1e-12)
    return (plus_values - minus_values) / span / scale


def matrix_metrics(
    matrix: Sequence[Sequence[float]],
    ridge: float = 1e-8,
) -> dict[str, Any]:
    """Summarize sensitivity magnitude and column coupling."""
    values = np.asarray(matrix, dtype=float)
    if values.ndim != 2 or values.shape[0] == 0 or values.shape[1] == 0:
        raise ValueError("sensitivity matrix must be non-empty and 2D")
    if not np.all(np.isfinite(values)):
        raise ValueError("sensitivity matrix must be finite")
    if not np.isfinite(ridge) or ridge <= 0.0:
        raise ValueError("ridge must be positive and finite")

    gram = values.T @ values + float(ridge) * np.eye(values.shape[1])
    sign, logdet = np.linalg.slogdet(gram)
    if sign <= 0 or not np.isfinite(logdet):
        raise ValueError("regularized sensitivity Gram matrix is invalid")
    singular = np.linalg.svd(values, compute_uv=False)
    norms = np.linalg.norm(values, axis=0)
    normalized = values / np.maximum(norms, np.finfo(float).eps)
    correlation = normalized.T @ normalized
    if correlation.shape[0] <= 1:
        max_correlation = 0.0
    else:
        off_diagonal = np.abs(
            correlation - np.diag(np.diag(correlation))
        )
        max_correlation = float(np.max(off_diagonal))
    return {
        "logdet": float(logdet),
        "min_singular_value": float(np.min(singular)),
        "max_abs_correlation": max_correlation,
        "column_norms": [float(value) for value in norms],
    }


def stack_observable_matrices(
    matrices: Sequence[
        tuple[Sequence[str], Sequence[Sequence[float]], Sequence[bool]]
    ],
) -> tuple[tuple[str, ...], np.ndarray]:
    """Stack protocols using only feature rows observable in every protocol."""
    if not matrices:
        raise ValueError("at least one protocol matrix is required")
    reference_names = tuple(str(name) for name in matrices[0][0])
    common = np.ones(len(reference_names), dtype=bool)
    prepared: list[np.ndarray] = []
    for names, matrix, observable in matrices:
        if tuple(str(name) for name in names) != reference_names:
            raise ValueError("protocol feature names do not match")
        values = np.asarray(matrix, dtype=float)
        mask = np.asarray(observable, dtype=bool)
        if values.ndim != 2 or values.shape[0] != len(reference_names):
            raise ValueError("protocol sensitivity shape mismatch")
        if mask.shape != (len(reference_names),):
            raise ValueError("protocol observable mask shape mismatch")
        common &= mask
        prepared.append(values)
    if not np.any(common):
        raise ValueError("protocols share no observable feature rows")
    stacked = np.vstack([values[common] for values in prepared])
    if not np.all(np.isfinite(stacked)):
        raise ValueError("observable sensitivity rows must be finite")
    return (
        tuple(
            name for name, keep in zip(reference_names, common) if keep
        ),
        stacked,
    )


def rank_candidate_conditions(
    rows: Sequence[Mapping[str, Any]],
    minimum_positive: int = 6,
) -> list[dict[str, Any]]:
    """Apply the frozen robust lexicographic ranking."""
    ranked: list[dict[str, Any]] = []
    for source in rows:
        row = dict(source)
        logdet_gain = row.get("q25_logdet_gain")
        row["eligible"] = bool(
            row["all_success"]
            and logdet_gain is not None
            and float(logdet_gain) > 0.0
            and int(row["positive_gain_count"]) >= int(minimum_positive)
        )
        ranked.append(row)

    def metric(row: Mapping[str, Any], name: str) -> float:
        value = row.get(name)
        return float("-inf") if value is None else float(value)

    return sorted(
        ranked,
        key=lambda row: (
            -int(bool(row["eligible"])),
            -metric(row, "q25_logdet_gain"),
            -metric(row, "median_correlation_reduction"),
            -metric(row, "q25_min_singular_gain"),
            int(row["total_points"]),
            str(row["condition_id"]),
        ),
    )


def column_direction_cosines(
    full: Sequence[Sequence[float]],
    half: Sequence[Sequence[float]],
) -> np.ndarray:
    """Compare full-step and half-step sensitivity directions by column."""
    full_values = np.asarray(full, dtype=float)
    half_values = np.asarray(half, dtype=float)
    if (
        full_values.ndim != 2
        or half_values.shape != full_values.shape
        or not np.all(np.isfinite(full_values))
        or not np.all(np.isfinite(half_values))
    ):
        raise ValueError("linearity matrices must be finite and have equal shape")
    numerator = np.sum(full_values * half_values, axis=0)
    denominator = np.linalg.norm(full_values, axis=0) * np.linalg.norm(
        half_values, axis=0
    )
    if np.any(denominator <= np.finfo(float).eps):
        raise ValueError("linearity comparison contains a zero sensitivity column")
    return numerator / denominator
