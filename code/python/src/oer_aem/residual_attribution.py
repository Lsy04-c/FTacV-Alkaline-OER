"""Pure contracts for V3 residual attribution."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import numpy as np


def _finite_array(value: Any, name: str) -> np.ndarray:
    array = np.asarray(value, dtype=float)
    if not np.all(np.isfinite(array)):
        raise ValueError(f"{name} must contain only finite values")
    return array


def _unit_vector(row: Mapping[str, Any]) -> np.ndarray:
    values = np.asarray(row.get("unit_params"), dtype=float)
    if values.shape != (5,) or not np.all(np.isfinite(values)):
        raise ValueError("unit_params must contain five finite coordinates")
    if np.any(values < 0.0) or np.any(values > 1.0):
        raise ValueError("unit_params must remain inside [0, 1]")
    return values


def select_representative_candidates(
    rows: Sequence[Mapping[str, Any]],
    pool_size: int = 64,
    ensemble_size: int = 12,
) -> list[dict[str, Any]]:
    """Select the best row, then deterministic maximin-diverse rows."""
    if pool_size < 1:
        raise ValueError("pool_size must be positive")
    if ensemble_size < 1 or ensemble_size > pool_size:
        raise ValueError("ensemble_size must be in [1, pool_size]")

    successful = []
    seen_ids: set[int] = set()
    for raw in rows:
        if raw.get("success") is not True:
            continue
        candidate_id = int(raw["candidate_id"])
        if candidate_id in seen_ids:
            raise ValueError(f"duplicate candidate_id: {candidate_id}")
        seen_ids.add(candidate_id)
        score = float(raw["score"])
        if not np.isfinite(score):
            raise ValueError("candidate score must be finite")
        _unit_vector(raw)
        successful.append(dict(raw))
    successful.sort(
        key=lambda row: (float(row["score"]), int(row["candidate_id"]))
    )
    if len(successful) < pool_size:
        raise ValueError(
            f"need at least {pool_size} successful candidates; "
            f"found {len(successful)}"
        )

    pool = successful[:pool_size]
    selected = [pool[0]]
    selection_distances: list[float | None] = [None]
    remaining = pool[1:]
    while len(selected) < ensemble_size:
        ranked: list[tuple[float, float, int, dict[str, Any]]] = []
        for row in remaining:
            vector = _unit_vector(row)
            min_distance = min(
                float(np.linalg.norm(vector - _unit_vector(item)))
                for item in selected
            )
            ranked.append(
                (
                    -min_distance,
                    float(row["score"]),
                    int(row["candidate_id"]),
                    row,
                )
            )
        neg_distance, _, _, chosen = min(ranked, key=lambda item: item[:3])
        selected.append(chosen)
        selection_distances.append(-neg_distance)
        remaining.remove(chosen)

    result = []
    for rank, (row, distance) in enumerate(
        zip(selected, selection_distances, strict=True)
    ):
        item = dict(row)
        item["selection_rank"] = rank
        item["selection_min_distance"] = distance
        result.append(item)
    return result


def segment_masks(n_grid: int) -> dict[str, np.ndarray]:
    """Return the frozen low/mid/high index masks."""
    if n_grid < 3:
        raise ValueError("n_grid must be at least 3")
    low_stop = int(np.ceil(0.2 * n_grid))
    high_start = int(np.floor(0.8 * n_grid))
    index = np.arange(n_grid)
    return {
        "low": index < low_stop,
        "mid": (index >= low_stop) & (index < high_start),
        "high": index >= high_start,
    }


def _wrapped_difference(target: np.ndarray, simulated: np.ndarray) -> np.ndarray:
    return np.angle(np.exp(1j * (target - simulated)))


def signed_feature_residuals(
    target: Mapping[str, Any],
    simulated: Mapping[str, Any],
    harmonics: Sequence[int] = (1, 2, 3),
) -> dict[str, np.ndarray]:
    """Compute signed target-minus-simulation residual components."""
    target_dc = _finite_array(target["dc"], "target dc").reshape(-1)
    simulated_dc = _finite_array(simulated["dc"], "simulated dc").reshape(-1)
    if target_dc.shape != simulated_dc.shape:
        raise ValueError("DC feature shapes do not match")
    dc_scale = max(float(np.max(np.abs(target_dc))), np.finfo(float).eps)
    result: dict[str, np.ndarray] = {
        "dc": (target_dc - simulated_dc) / dc_scale,
    }

    target_complex = target["complex_harmonics"]
    simulated_complex = simulated["complex_harmonics"]
    target_global_amplitude = _finite_array(
        target_complex["amplitude"],
        "target global amplitude",
    ).reshape(-1)
    simulated_global_amplitude = _finite_array(
        simulated_complex["amplitude"],
        "simulated global amplitude",
    ).reshape(-1)
    target_global_phase = _finite_array(
        target_complex["phase"],
        "target global phase",
    ).reshape(-1)
    simulated_global_phase = _finite_array(
        simulated_complex["phase"],
        "simulated global phase",
    ).reshape(-1)

    target_lockin = target["lockin"]
    simulated_lockin = simulated["lockin"]
    target_valid = np.asarray(target_lockin["valid_mask"], dtype=bool).reshape(-1)
    simulated_valid = np.asarray(
        simulated_lockin["valid_mask"],
        dtype=bool,
    ).reshape(-1)
    common_valid = target_valid & simulated_valid
    if common_valid.shape != target_dc.shape:
        raise ValueError("lockin valid mask shape does not match DC")
    result["lockin_valid_mask"] = common_valid
    target_lockin_amplitude = np.asarray(
        target_lockin["amplitude"],
        dtype=float,
    )
    simulated_lockin_amplitude = np.asarray(
        simulated_lockin["amplitude"],
        dtype=float,
    )
    target_lockin_phase = np.asarray(target_lockin["phase"], dtype=float)
    simulated_lockin_phase = np.asarray(
        simulated_lockin["phase"],
        dtype=float,
    )

    for harmonic in harmonics:
        if harmonic < 1:
            raise ValueError("harmonics must be positive")
        index = harmonic - 1
        for array in (
            target_global_amplitude,
            simulated_global_amplitude,
            target_global_phase,
            simulated_global_phase,
        ):
            if index >= len(array):
                raise ValueError(f"missing global harmonic H{harmonic}")
        if (
            target_lockin_amplitude.ndim != 2
            or simulated_lockin_amplitude.shape
            != target_lockin_amplitude.shape
            or target_lockin_phase.shape != target_lockin_amplitude.shape
            or simulated_lockin_phase.shape != target_lockin_amplitude.shape
            or index >= target_lockin_amplitude.shape[0]
            or target_lockin_amplitude.shape[1] != len(target_dc)
        ):
            raise ValueError("lockin feature shapes do not match")
        for name, array in (
            ("target lockin amplitude", target_lockin_amplitude[index]),
            ("simulated lockin amplitude", simulated_lockin_amplitude[index]),
            ("target lockin phase", target_lockin_phase[index]),
            ("simulated lockin phase", simulated_lockin_phase[index]),
        ):
            if not np.all(np.isfinite(array[common_valid])):
                raise ValueError(f"{name} is non-finite in the valid region")

        global_scale = max(
            abs(float(target_global_amplitude[index])),
            np.finfo(float).eps,
        )
        result[f"global_amplitude_h{harmonic}"] = np.asarray(
            [
                (
                    target_global_amplitude[index]
                    - simulated_global_amplitude[index]
                )
                / global_scale
            ],
            dtype=float,
        )
        result[f"global_phase_h{harmonic}"] = _wrapped_difference(
            target_global_phase[index : index + 1],
            simulated_global_phase[index : index + 1],
        )

        amplitude_scale = max(
            float(np.max(np.abs(target_lockin_amplitude[index][common_valid])))
            if np.any(common_valid)
            else 0.0,
            np.finfo(float).eps,
        )
        amplitude_residual = np.zeros_like(target_dc)
        phase_residual = np.zeros_like(target_dc)
        amplitude_residual[common_valid] = (
            target_lockin_amplitude[index][common_valid]
            - simulated_lockin_amplitude[index][common_valid]
        ) / amplitude_scale
        phase_residual[common_valid] = _wrapped_difference(
            target_lockin_phase[index][common_valid],
            simulated_lockin_phase[index][common_valid],
        )
        result[f"lockin_amplitude_h{harmonic}"] = amplitude_residual
        result[f"lockin_phase_h{harmonic}"] = phase_residual

    return result


def classify_sign_consistency(
    values: Sequence[float],
    required: int = 9,
) -> str:
    """Classify whether at least ``required`` nonzero values share a sign."""
    array = _finite_array(values, "sign values").reshape(-1)
    if required < 1 or required > len(array):
        raise ValueError("required sign count is outside the ensemble")
    positive = int(np.count_nonzero(array > 0.0))
    negative = int(np.count_nonzero(array < 0.0))
    if max(positive, negative) >= required:
        return "ensemble sign-consistent"
    return "candidate-dependent"


def _summary_row(
    *,
    dataset_id: str,
    candidate_id: int,
    channel: str,
    segment: str,
    values: np.ndarray,
) -> dict[str, Any]:
    if values.size < 1:
        return {
            "dataset_id": dataset_id,
            "candidate_id": int(candidate_id),
            "channel": channel,
            "segment": segment,
            "n_points": 0,
            "signed_mean": None,
            "median": None,
            "rmse": None,
            "median_absolute_error": None,
            "positive_fraction": None,
        }
    if not np.all(np.isfinite(values)):
        raise ValueError(f"{channel}/{segment} has non-finite residual values")
    return {
        "dataset_id": dataset_id,
        "candidate_id": int(candidate_id),
        "channel": channel,
        "segment": segment,
        "n_points": int(values.size),
        "signed_mean": float(np.mean(values)),
        "median": float(np.median(values)),
        "rmse": float(np.sqrt(np.mean(values**2))),
        "median_absolute_error": float(np.median(np.abs(values))),
        "positive_fraction": float(np.mean(values > 0.0)),
    }


def summarize_candidate_residuals(
    residuals: Mapping[str, Any],
    *,
    dataset_id: str,
    candidate_id: int,
) -> list[dict[str, Any]]:
    """Summarize one candidate without combining amplitude and phase."""
    dc = _finite_array(residuals["dc"], "dc residual").reshape(-1)
    masks = segment_masks(len(dc))
    lockin_valid = np.asarray(
        residuals["lockin_valid_mask"],
        dtype=bool,
    ).reshape(-1)
    if lockin_valid.shape != dc.shape:
        raise ValueError("lockin valid mask shape does not match residual grid")

    rows: list[dict[str, Any]] = []
    for channel, raw in residuals.items():
        if channel == "lockin_valid_mask":
            continue
        values = _finite_array(raw, f"{channel} residual").reshape(-1)
        if channel.startswith("global_"):
            if values.shape != (1,):
                raise ValueError(f"{channel} must contain one global value")
            rows.append(
                _summary_row(
                    dataset_id=dataset_id,
                    candidate_id=candidate_id,
                    channel=channel,
                    segment="global",
                    values=values,
                )
            )
            continue
        if values.shape != dc.shape:
            raise ValueError(f"{channel} residual shape does not match grid")
        for segment, mask in masks.items():
            selected = mask
            if channel.startswith("lockin_"):
                selected = selected & lockin_valid
            rows.append(
                _summary_row(
                    dataset_id=dataset_id,
                    candidate_id=candidate_id,
                    channel=channel,
                    segment=segment,
                    values=values[selected],
                )
            )
    return rows


def summarize_ensemble(
    rows: Sequence[Mapping[str, Any]],
    *,
    nearest_candidate_id: int,
    ensemble_size: int = 12,
) -> list[dict[str, Any]]:
    """Aggregate candidate summaries by channel and potential segment."""
    grouped: dict[tuple[str, str, str], list[Mapping[str, Any]]] = {}
    for row in rows:
        key = (
            str(row["dataset_id"]),
            str(row["channel"]),
            str(row["segment"]),
        )
        grouped.setdefault(key, []).append(row)

    output: list[dict[str, Any]] = []
    for (dataset_id, channel, segment), items in sorted(grouped.items()):
        candidate_ids = [int(item["candidate_id"]) for item in items]
        if len(items) != ensemble_size or len(set(candidate_ids)) != ensemble_size:
            raise ValueError(
                f"{dataset_id}/{channel}/{segment} must contain "
                f"{ensemble_size} unique candidates"
            )
        values = np.asarray(
            [
                float(item["signed_mean"])
                for item in items
                if item["signed_mean"] is not None
            ],
            dtype=float,
        )
        if not np.all(np.isfinite(values)):
            raise ValueError("ensemble signed means must be finite")
        if values.size:
            q25, median, q75 = np.quantile(values, [0.25, 0.5, 0.75])
        else:
            q25 = median = q75 = None
        nearest_rows = [
            item
            for item in items
            if int(item["candidate_id"]) == int(nearest_candidate_id)
        ]
        if len(nearest_rows) != 1:
            raise ValueError(
                f"nearest candidate missing for {dataset_id}/{channel}/{segment}"
            )
        nearest_value = (
            float(nearest_rows[0]["signed_mean"])
            if nearest_rows[0]["signed_mean"] is not None
            else None
        )
        if values.size == 0:
            direction_class = "not-observable"
        elif ensemble_size < 9:
            direction_class = "smoke-only"
        elif values.size < 9:
            direction_class = "insufficient-valid-candidates"
        else:
            direction_class = classify_sign_consistency(values, required=9)
        output.append(
            {
                "dataset_id": dataset_id,
                "channel": channel,
                "segment": segment,
                "ensemble_size": ensemble_size,
                "valid_candidate_count": int(values.size),
                "signed_mean_median": (
                    float(median) if median is not None else None
                ),
                "signed_mean_q25": float(q25) if q25 is not None else None,
                "signed_mean_q75": float(q75) if q75 is not None else None,
                "positive_count": int(np.count_nonzero(values > 0.0)),
                "negative_count": int(np.count_nonzero(values < 0.0)),
                "direction_class": direction_class,
                "nearest_candidate_id": int(nearest_candidate_id),
                "nearest_signed_mean": nearest_value,
                "nearest_within_iqr": (
                    bool(q25 <= nearest_value <= q75)
                    if q25 is not None and nearest_value is not None
                    else None
                ),
            }
        )
    return output
