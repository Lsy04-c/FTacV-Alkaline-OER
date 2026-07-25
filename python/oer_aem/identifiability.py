"""Parameter identifiability diagnostics from feature sensitivities."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

import numpy as np


def sensitivity_correlation(matrix) -> np.ndarray:
    """Return cosine similarity between sensitivity-matrix columns."""
    values = np.asarray(matrix, dtype=float)
    if values.ndim != 2:
        raise ValueError("sensitivity matrix must be two-dimensional")
    norms = np.linalg.norm(values, axis=0)
    normalized = values / np.maximum(norms, np.finfo(float).eps)
    return normalized.T @ normalized


def classify_columns(
    names: Sequence[str],
    matrix,
    correlation,
    norm_floor_ratio: float = 1e-8,
    corr_limit: float = 0.98,
) -> dict[str, str]:
    """Classify columns as identifiable, coupled, or unresolved."""
    values = np.asarray(matrix, dtype=float)
    correlations = np.asarray(correlation, dtype=float)
    if values.ndim != 2 or values.shape[1] != len(names):
        raise ValueError("parameter names must match sensitivity columns")
    if correlations.shape != (len(names), len(names)):
        raise ValueError("correlation matrix shape does not match parameters")

    norms = np.linalg.norm(values, axis=0)
    floor = max(float(np.max(norms)) * norm_floor_ratio, 1e-12)
    labels: dict[str, str] = {}
    for index, name in enumerate(names):
        peers = np.delete(np.abs(correlations[index]), index)
        if norms[index] <= floor:
            labels[name] = "unresolved"
        elif peers.size and float(np.max(peers)) >= corr_limit:
            labels[name] = "coupled"
        else:
            labels[name] = "identifiable"
    return labels


def matrix_from_importance(
    result: Mapping[str, object],
) -> tuple[list[str], list[str], np.ndarray]:
    """Convert an importance report into feature names, parameters, and matrix."""
    rows = list(result.get("feature_sensitivity_matrix", []))
    parameters = list(
        result.get("metadata", {}).get("param_order", [])
    )
    available = {
        item["name"]
        for item in result.get("parameter_importance", [])
    }
    parameters = [name for name in parameters if name in available]
    features = [str(row["feature"]) for row in rows]
    matrix = np.asarray(
        [
            [
                float(row.get("changes", {}).get(parameter, 0.0))
                for parameter in parameters
            ]
            for row in rows
        ],
        dtype=float,
    )
    return features, parameters, matrix


def signed_sensitivity_table(
    feature_names: Sequence[str],
    param_names: Sequence[str],
    matrix: np.ndarray,
) -> list[dict[str, Any]]:
    """Return signed sensitivity rows for every (feature, parameter) pair.

    Each row records the raw signed sensitivity from central differences.
    """
    values = np.asarray(matrix, dtype=float)
    if values.ndim != 2:
        raise ValueError("sensitivity matrix must be two-dimensional")
    if values.shape[0] != len(feature_names):
        raise ValueError("feature count mismatch")
    if values.shape[1] != len(param_names):
        raise ValueError("parameter count mismatch")

    rows: list[dict[str, Any]] = []
    for fi, fname in enumerate(feature_names):
        for pi, pname in enumerate(param_names):
            raw = float(values[fi, pi])
            rows.append({
                "feature": str(fname),
                "parameter": str(pname),
                "sensitivity": raw,
                "abs_sensitivity": abs(raw),
                "direction": "positive" if raw > 0 else ("negative" if raw < 0 else "zero"),
            })
    return rows


def coupling_direction(
    names: Sequence[str],
    correlation: np.ndarray,
    corr_limit: float = 0.98,
) -> dict[str, list[dict[str, Any]]]:
    """For each coupled parameter, list peers and coupling sign.

    Positive correlation = same direction (compensation risk).
    Negative correlation = opposite direction (distinguishable).
    """
    corr = np.asarray(correlation, dtype=float)
    n = len(names)
    if corr.shape != (n, n):
        raise ValueError("correlation shape mismatch")

    result: dict[str, list[dict[str, Any]]] = {}
    for i, name in enumerate(names):
        peers: list[dict[str, Any]] = []
        for j in range(n):
            if i == j:
                continue
            r = float(corr[i, j])
            if abs(r) >= corr_limit:
                peers.append({
                    "peer": str(names[j]),
                    "correlation": r,
                    "direction": "compensating" if r > 0 else "distinguishable",
                })
        result[str(name)] = peers
    return result
