"""Parameter identifiability diagnostics from feature sensitivities."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping, Sequence

import numpy as np


@dataclass(frozen=True)
class ActiveSubspaceResult:
    """Noise-whitened multi-anchor sensitivity decomposition.

    No effective dimension is selected here.  That decision belongs to a
    separate held-out recovery gate, not to the eigenvalue spectrum alone.
    """

    gramian: np.ndarray
    eigenvalues: np.ndarray
    directions: np.ndarray
    column_norms: np.ndarray
    whitened_jacobians: tuple[np.ndarray, ...]


@dataclass(frozen=True)
class FeatureStabilityResult:
    """Diagonal feature stability from a frozen time-domain noise model."""

    standard_deviations: np.ndarray
    distribution: str
    seeds: tuple[int, ...]
    current_sigma: float


def estimate_diagonal_feature_stability(
    current,
    *,
    feature_extractor: Callable[[np.ndarray], np.ndarray],
    noise_fraction: float,
    seeds: Sequence[int],
) -> FeatureStabilityResult:
    """Propagate a quantization-resolution noise floor through features.

    ``noise_fraction`` is the time-domain standard deviation divided by peak
    absolute current.  A uniform error with the same standard deviation is
    used because the available evidence is a quantization floor, not a
    repeatability distribution.
    """

    values = np.asarray(current, dtype=float).reshape(-1)
    if values.size < 2 or not np.all(np.isfinite(values)):
        raise ValueError("current must contain at least two finite values")
    fraction = float(noise_fraction)
    if not np.isfinite(fraction) or fraction <= 0.0:
        raise ValueError("noise_fraction must be finite and positive")
    frozen_seeds = tuple(int(seed) for seed in seeds)
    if len(frozen_seeds) < 2 or len(set(frozen_seeds)) != len(frozen_seeds):
        raise ValueError("at least two unique noise seeds are required")

    baseline = np.asarray(feature_extractor(values), dtype=float).reshape(-1)
    if baseline.size == 0 or not np.all(np.isfinite(baseline)):
        raise ValueError("feature extractor must return finite features")
    current_sigma = fraction * float(np.max(np.abs(values)))
    if current_sigma <= 0.0:
        raise ValueError("current peak must be positive")
    half_width = np.sqrt(3.0) * current_sigma
    samples = []
    for seed in frozen_seeds:
        rng = np.random.default_rng(seed)
        noisy = values + rng.uniform(-half_width, half_width, values.shape)
        extracted = np.asarray(feature_extractor(noisy), dtype=float).reshape(-1)
        if extracted.shape != baseline.shape or not np.all(np.isfinite(extracted)):
            raise ValueError("feature contract drift during noise propagation")
        samples.append(extracted)
    standard_deviations = np.std(np.asarray(samples), axis=0, ddof=1)
    if not np.all(np.isfinite(standard_deviations)):
        raise ValueError("feature stability must be finite")
    if np.any(standard_deviations <= 0.0):
        indices = np.flatnonzero(standard_deviations <= 0.0).tolist()
        raise ValueError(f"zero stability variance for feature rows {indices}")
    return FeatureStabilityResult(
        standard_deviations=standard_deviations,
        distribution="uniform_quantization_error",
        seeds=frozen_seeds,
        current_sigma=float(current_sigma),
    )


def select_candidate_dimension(
    selection_rows: Sequence[Mapping[str, object]],
    *,
    parameter_count: int,
    maximum_whitened_operator_norm: float = 1.0,
) -> dict[str, object]:
    """Select the smallest dimension passing a frozen selection-only gate."""

    count = int(parameter_count)
    threshold = float(maximum_whitened_operator_norm)
    if count < 1:
        raise ValueError("parameter_count must be positive")
    if not np.isfinite(threshold) or threshold <= 0.0:
        raise ValueError("selection threshold must be finite and positive")
    indexed: dict[int, float] = {}
    for row in selection_rows:
        dimension = int(row["dimension"])
        value = float(row["worst_discarded_singular_value"])
        if dimension in indexed or dimension < 1 or dimension > count:
            raise ValueError("selection dimensions must be unique and in range")
        if not np.isfinite(value) or value < 0.0:
            raise ValueError("selection operator norms must be finite and non-negative")
        indexed[dimension] = value
    if set(indexed) != set(range(1, count + 1)):
        raise ValueError("selection rows must cover every candidate dimension")
    candidate = next(
        dimension
        for dimension in range(1, count + 1)
        if indexed[dimension] <= threshold
    )
    reduced = candidate < count
    return {
        "status": (
            "candidate_selected_from_selection"
            if reduced
            else "full_space_required_by_selection"
        ),
        "candidate_dimension": candidate,
        "maximum_whitened_operator_norm": threshold,
        "reduction_achieved": reduced,
    }


def coordinate_scales_from_schema(
    schema: Mapping[str, object],
    parameter_names: Sequence[str],
) -> dict[str, float]:
    """Return derivatives ``d(parameter coordinate)/d(unit coordinate)``."""

    parameters = schema.get("parameters")
    if not isinstance(parameters, Mapping):
        raise ValueError("parameter schema must contain a parameters mapping")
    scales: dict[str, float] = {}
    for name in parameter_names:
        entry = parameters.get(name)
        if not isinstance(entry, Mapping):
            raise ValueError(f"parameter {name} is missing from schema")
        bounds = entry.get("bounds")
        if not isinstance(bounds, Sequence) or isinstance(bounds, (str, bytes)):
            raise ValueError(f"parameter {name} bounds are unresolved")
        if len(bounds) != 2:
            raise ValueError(f"parameter {name} bounds must contain two values")
        lower, upper = (float(bounds[0]), float(bounds[1]))
        if not np.isfinite(lower) or not np.isfinite(upper) or lower >= upper:
            raise ValueError(f"parameter {name} bounds are invalid")
        transform = str(entry.get("transform"))
        if transform == "linear":
            scale = upper - lower
        elif transform == "log10":
            if lower <= 0.0:
                raise ValueError(f"parameter {name} log10 bounds must be positive")
            scale = np.log10(upper) - np.log10(lower)
        else:
            raise ValueError(f"parameter {name} transform is unsupported")
        scales[str(name)] = float(scale)
    return scales


def whiten_sensitivity(jacobian, noise_model) -> np.ndarray:
    """Left-whiten one feature-by-parameter Jacobian."""

    values = np.asarray(jacobian, dtype=float)
    noise = np.asarray(noise_model, dtype=float)
    if values.ndim != 2 or not np.all(np.isfinite(values)):
        raise ValueError("jacobian must be a finite two-dimensional matrix")
    feature_count = values.shape[0]

    if noise.ndim == 1:
        if noise.shape != (feature_count,):
            raise ValueError("noise standard deviations must match features")
        if not np.all(np.isfinite(noise)) or np.any(noise <= 0.0):
            raise ValueError("noise standard deviations must be positive")
        return values / noise[:, None]

    if noise.ndim == 2:
        if noise.shape != (feature_count, feature_count):
            raise ValueError("noise covariance must match feature dimensions")
        if not np.all(np.isfinite(noise)):
            raise ValueError("noise covariance must be finite")
        if not np.allclose(noise, noise.T, rtol=0.0, atol=1e-12):
            raise ValueError("noise covariance must be symmetric")
        try:
            factor = np.linalg.cholesky(noise)
        except np.linalg.LinAlgError as exc:
            raise ValueError(
                "noise covariance must be positive definite"
            ) from exc
        return np.linalg.solve(factor, values)

    raise ValueError("noise model must be standard deviations or covariance")


def _stable_direction_signs(directions: np.ndarray) -> np.ndarray:
    stable = np.asarray(directions, dtype=float).copy()
    for column in range(stable.shape[1]):
        pivot = int(np.argmax(np.abs(stable[:, column])))
        if stable[pivot, column] < 0.0:
            stable[:, column] *= -1.0
    return stable


def active_subspace_decomposition(
    jacobians: Sequence[np.ndarray],
    noise_models: Sequence[np.ndarray],
    *,
    anchor_weights: Sequence[float] | None = None,
) -> ActiveSubspaceResult:
    """Decompose a weighted sum of whitened sensitivity Gramians."""

    if not jacobians or len(jacobians) != len(noise_models):
        raise ValueError("jacobians and noise models must have equal nonzero length")
    whitened = tuple(
        whiten_sensitivity(jacobian, noise)
        for jacobian, noise in zip(jacobians, noise_models)
    )
    parameter_count = whitened[0].shape[1]
    if any(item.shape[1] != parameter_count for item in whitened):
        raise ValueError("all jacobians must use the same parameter columns")

    if anchor_weights is None:
        weights = np.ones(len(whitened), dtype=float)
    else:
        weights = np.asarray(anchor_weights, dtype=float)
        if weights.shape != (len(whitened),):
            raise ValueError("anchor weights must match jacobians")
    if not np.all(np.isfinite(weights)) or np.any(weights <= 0.0):
        raise ValueError("anchor weights must be finite and positive")
    weights /= float(np.sum(weights))

    gramian = np.zeros((parameter_count, parameter_count), dtype=float)
    for weight, matrix in zip(weights, whitened):
        gramian += float(weight) * (matrix.T @ matrix)
    gramian = 0.5 * (gramian + gramian.T)

    eigenvalues, directions = np.linalg.eigh(gramian)
    order = np.argsort(eigenvalues)[::-1]
    eigenvalues = eigenvalues[order]
    numerical_floor = np.finfo(float).eps * max(
        1.0,
        float(np.max(np.abs(eigenvalues))),
    )
    eigenvalues[np.abs(eigenvalues) <= numerical_floor] = 0.0
    directions = _stable_direction_signs(directions[:, order])
    return ActiveSubspaceResult(
        gramian=gramian,
        eigenvalues=eigenvalues,
        directions=directions,
        column_norms=np.sqrt(np.maximum(np.diag(gramian), 0.0)),
        whitened_jacobians=whitened,
    )


def subspace_residual_diagnostics(
    jacobians: Sequence[np.ndarray],
    noise_models: Sequence[np.ndarray],
    directions: np.ndarray,
    *,
    candidate_dimensions: Sequence[int] | None = None,
) -> list[dict[str, float | int]]:
    """Measure selection-anchor sensitivity left outside candidate spaces."""

    whitened = tuple(
        whiten_sensitivity(jacobian, noise)
        for jacobian, noise in zip(jacobians, noise_models)
    )
    if not whitened or len(whitened) != len(jacobians):
        raise ValueError("jacobians and noise models must have equal nonzero length")
    basis = np.asarray(directions, dtype=float)
    parameter_count = whitened[0].shape[1]
    if basis.shape != (parameter_count, parameter_count):
        raise ValueError("directions must be a square parameter basis")
    if not np.all(np.isfinite(basis)) or not np.allclose(
        basis.T @ basis,
        np.eye(parameter_count),
        rtol=0.0,
        atol=1e-10,
    ):
        raise ValueError("directions must be finite and orthonormal")
    if any(matrix.shape[1] != parameter_count for matrix in whitened):
        raise ValueError("jacobian parameter columns must match directions")

    dimensions = list(
        candidate_dimensions or range(1, parameter_count + 1)
    )
    if (
        not dimensions
        or len(dimensions) != len(set(dimensions))
        or any(value < 1 or value > parameter_count for value in dimensions)
    ):
        raise ValueError("candidate dimensions must be unique and in range")

    rows: list[dict[str, float | int]] = []
    identity = np.eye(parameter_count)
    for dimension in dimensions:
        active = basis[:, :dimension]
        inactive_projector = identity - active @ active.T
        relative = []
        singular = []
        for matrix in whitened:
            residual = matrix @ inactive_projector
            scale = max(float(np.linalg.norm(matrix, ord="fro")), np.finfo(float).eps)
            relative.append(float(np.linalg.norm(residual, ord="fro")) / scale)
            values = np.linalg.svd(residual, compute_uv=False)
            singular.append(float(values[0]) if values.size else 0.0)
        rows.append(
            {
                "dimension": int(dimension),
                "worst_relative_frobenius": float(max(relative)),
                "mean_relative_frobenius": float(np.mean(relative)),
                "worst_discarded_singular_value": float(max(singular)),
            }
        )
    return rows


def subspace_alignment_diagnostics(
    jacobians: Sequence[np.ndarray],
    noise_models: Sequence[np.ndarray],
    reference_directions: np.ndarray,
) -> list[list[dict[str, float | int]]]:
    """Compare each local right-singular subspace with a frozen reference."""

    if not jacobians or len(jacobians) != len(noise_models):
        raise ValueError("jacobians and noise models must have equal nonzero length")
    whitened = [
        whiten_sensitivity(jacobian, noise)
        for jacobian, noise in zip(jacobians, noise_models)
    ]
    reference = np.asarray(reference_directions, dtype=float)
    parameter_count = whitened[0].shape[1]
    if reference.shape != (parameter_count, parameter_count):
        raise ValueError("reference directions must be a square parameter basis")
    if not np.all(np.isfinite(reference)) or not np.allclose(
        reference.T @ reference,
        np.eye(parameter_count),
        rtol=0.0,
        atol=1e-10,
    ):
        raise ValueError("reference directions must be finite and orthonormal")
    if any(matrix.shape[1] != parameter_count for matrix in whitened):
        raise ValueError("jacobian parameter columns must match reference directions")

    diagnostics = []
    for matrix in whitened:
        _, singular_values, right_transpose = np.linalg.svd(
            matrix,
            full_matrices=True,
        )
        local = right_transpose.T
        rows = []
        for dimension in range(1, parameter_count + 1):
            reference_basis = reference[:, :dimension]
            local_basis = local[:, :dimension]
            cosines = np.linalg.svd(
                reference_basis.T @ local_basis,
                compute_uv=False,
            )
            cosines = np.clip(cosines, 0.0, 1.0)
            maximum_angle = float(
                np.degrees(np.arccos(float(np.min(cosines))))
            )
            projector_distance = float(
                np.linalg.norm(
                    reference_basis @ reference_basis.T
                    - local_basis @ local_basis.T,
                    ord="fro",
                )
            )
            rows.append(
                {
                    "dimension": dimension,
                    "maximum_principal_angle_degrees": maximum_angle,
                    "projector_frobenius": projector_distance,
                    "local_retained_singular_value": (
                        float(singular_values[dimension - 1])
                        if dimension <= singular_values.size
                        else 0.0
                    ),
                }
            )
        diagnostics.append(rows)
    return diagnostics


def sensitivity_correlation(matrix) -> np.ndarray:
    """Return cosine similarity between sensitivity-matrix columns."""
    values = np.asarray(matrix, dtype=float)
    if values.ndim != 2:
        raise ValueError("sensitivity matrix must be two-dimensional")
    if not np.all(np.isfinite(values)):
        raise ValueError("sensitivity matrix must contain only finite values")
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
    rows = list(
        result.get("signed_feature_sensitivity_matrix")
        or result.get("feature_sensitivity_matrix", [])
    )
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


def decompose_importance_reports(
    reports: Sequence[Mapping[str, object]],
    noise_models: Sequence[np.ndarray],
    *,
    column_scales_to_unit_coordinates: Mapping[str, float],
    anchor_weights: Sequence[float] | None = None,
) -> tuple[list[str], list[str], ActiveSubspaceResult]:
    """Build one active-subspace decomposition from frozen importance reports."""

    if not reports:
        raise ValueError("at least one importance report is required")
    converted = [matrix_from_importance(report) for report in reports]
    feature_names, parameter_names, _ = converted[0]
    for current_features, current_parameters, _ in converted[1:]:
        if current_features != feature_names:
            raise ValueError("importance report feature contract drift")
        if current_parameters != parameter_names:
            raise ValueError("importance report parameter contract drift")
    if set(column_scales_to_unit_coordinates) != set(parameter_names):
        raise ValueError(
            "coordinate scales must match every importance parameter"
        )
    scales = np.asarray(
        [column_scales_to_unit_coordinates[name] for name in parameter_names],
        dtype=float,
    )
    if not np.all(np.isfinite(scales)) or np.any(scales <= 0.0):
        raise ValueError("coordinate scales must be finite and positive")
    result = active_subspace_decomposition(
        [matrix * scales[None, :] for _, _, matrix in converted],
        noise_models,
        anchor_weights=anchor_weights,
    )
    return feature_names, parameter_names, result


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
                    "direction": "same_response" if r > 0 else "opposite_response",
                })
        result[str(name)] = peers
    return result


def fit_compensation_geometry(displacements: np.ndarray) -> dict[str, Any]:
    """Decompose observed low-loss parameter motion into motion/invariant axes."""

    values = np.asarray(displacements, dtype=float)
    if values.ndim != 2 or values.shape[0] < 1 or values.shape[1] < 1:
        raise ValueError("displacements must be a non-empty two-dimensional matrix")
    if not np.all(np.isfinite(values)):
        raise ValueError("displacements must be finite")
    _, singular_values, right_transpose = np.linalg.svd(
        values,
        full_matrices=True,
    )
    directions = right_transpose.T
    for column in range(directions.shape[1]):
        pivot = int(np.argmax(np.abs(directions[:, column])))
        if directions[pivot, column] < 0.0:
            directions[:, column] *= -1.0
    padded = np.zeros(values.shape[1], dtype=float)
    padded[: singular_values.size] = singular_values
    return {
        "singular_values": padded.tolist(),
        "directions": directions.tolist(),
        "sample_count": int(values.shape[0]),
        "parameter_count": int(values.shape[1]),
    }
