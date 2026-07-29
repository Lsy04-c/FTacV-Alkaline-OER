"""Pure contracts for conditional model-reachability studies."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Any, Mapping, Sequence

import numpy as np
from scipy.stats import qmc

from .inversion import ParamSpec


@dataclass(frozen=True)
class ParameterLibrary:
    unit: np.ndarray
    encoded: np.ndarray
    physical: tuple[dict[str, float], ...]
    sha256: str


@dataclass(frozen=True)
class ScoreResult:
    score: float
    passed: bool
    limiting_metrics: tuple[str, ...]


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def generate_sobol_library(
    specs: Sequence[ParamSpec],
    n_candidates: int,
    seed: int,
) -> ParameterLibrary:
    """Generate a deterministic scrambled Sobol prefix in encoded coordinates."""
    frozen_specs = tuple(
        (str(name), str(scale), float(low), float(high))
        for name, scale, low, high in specs
    )
    if not frozen_specs:
        raise ValueError("at least one parameter specification is required")
    if n_candidates <= 0 or n_candidates & (n_candidates - 1):
        raise ValueError("n_candidates must be a positive power of two")
    for name, scale, low, high in frozen_specs:
        if scale not in {"linear", "log10"}:
            raise ValueError(f"unsupported scale for {name}: {scale}")
        if not np.isfinite([low, high]).all() or low >= high:
            raise ValueError(f"invalid bounds for {name}")

    exponent = int(np.log2(n_candidates))
    unit = qmc.Sobol(
        d=len(frozen_specs),
        scramble=True,
        seed=int(seed),
    ).random_base2(exponent)
    lows = np.asarray([spec[2] for spec in frozen_specs], dtype=float)
    highs = np.asarray([spec[3] for spec in frozen_specs], dtype=float)
    encoded = lows + unit * (highs - lows)

    physical_rows: list[dict[str, float]] = []
    for row in encoded:
        physical_rows.append(
            {
                name: float(10.0**value if scale == "log10" else value)
                for value, (name, scale, _, _) in zip(row, frozen_specs)
            }
        )

    hasher = hashlib.sha256()
    hasher.update(
        _canonical_json(
            {
                "specs": frozen_specs,
                "n_candidates": int(n_candidates),
                "seed": int(seed),
            }
        )
    )
    hasher.update(np.asarray(unit, dtype="<f8").tobytes(order="C"))
    hasher.update(np.asarray(encoded, dtype="<f8").tobytes(order="C"))
    return ParameterLibrary(
        unit=np.asarray(unit, dtype=float),
        encoded=np.asarray(encoded, dtype=float),
        physical=tuple(physical_rows),
        sha256=hasher.hexdigest(),
    )


def build_fixed_stress_scenarios(
    baseline: Mapping[str, float],
) -> tuple[dict[str, Any], ...]:
    """Build the frozen sixteen one-at-a-time fixed-input perturbations."""
    required = (
        "A",
        "Cdl",
        "Ru",
        "E0_pre",
        "k0_pre",
        "gamma",
        "k0_4",
        "scaling_OOH_OH",
    )
    missing = [name for name in required if name not in baseline]
    if missing:
        raise ValueError(f"missing fixed baselines: {', '.join(missing)}")
    frozen = {name: float(baseline[name]) for name in required}
    if not np.all(np.isfinite(tuple(frozen.values()))):
        raise ValueError("fixed baselines must be finite")
    if any(
        frozen[name] <= 0
        for name in ("A", "Cdl", "Ru", "k0_pre", "gamma", "k0_4")
    ):
        raise ValueError("multiplicative fixed baselines must be positive")

    perturbations: tuple[tuple[str, str, float], ...] = (
        ("A", "x0.5", frozen["A"] * 0.5),
        ("A", "x2", frozen["A"] * 2.0),
        ("Cdl", "x0.5", frozen["Cdl"] * 0.5),
        ("Cdl", "x2", frozen["Cdl"] * 2.0),
        ("Ru", "x0.5", frozen["Ru"] * 0.5),
        ("Ru", "x2", frozen["Ru"] * 2.0),
        ("E0_pre", "minus0.05", frozen["E0_pre"] - 0.05),
        ("E0_pre", "plus0.05", frozen["E0_pre"] + 0.05),
        ("k0_pre", "x0.5", frozen["k0_pre"] * 0.5),
        ("k0_pre", "x2", frozen["k0_pre"] * 2.0),
        ("gamma", "x0.5", frozen["gamma"] * 0.5),
        ("gamma", "x2", frozen["gamma"] * 2.0),
        ("k0_4", "x0.5", frozen["k0_4"] * 0.5),
        ("k0_4", "x2", frozen["k0_4"] * 2.0),
        (
            "scaling_OOH_OH",
            "minus0.2",
            frozen["scaling_OOH_OH"] - 0.2,
        ),
        (
            "scaling_OOH_OH",
            "plus0.2",
            frozen["scaling_OOH_OH"] + 0.2,
        ),
    )
    scenarios = []
    for parameter, label, value in perturbations:
        values = dict(frozen)
        values[parameter] = float(value)
        scenarios.append(
            {
                "scenario_id": f"{parameter}:{label}",
                "parameter": parameter,
                "label": label,
                "fixed_params": values,
            }
        )
    return tuple(scenarios)


def _validated_masked_arrays(
    candidate: np.ndarray,
    target: np.ndarray,
    mask: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    candidate_array = np.asarray(candidate, dtype=float)
    target_array = np.asarray(target, dtype=float)
    mask_array = np.asarray(mask, dtype=bool)
    if (
        candidate_array.shape != target_array.shape
        or candidate_array.shape != mask_array.shape
    ):
        raise ValueError("candidate, target and mask must have identical shapes")
    if not np.any(mask_array):
        raise ValueError("at least one valid masked point is required")
    selected_candidate = candidate_array[mask_array]
    selected_target = target_array[mask_array]
    if not np.all(np.isfinite(selected_candidate)) or not np.all(
        np.isfinite(selected_target)
    ):
        raise ValueError("valid masked values must be finite")
    return selected_candidate, selected_target


def wrapped_phase_rmse(
    candidate: np.ndarray,
    target: np.ndarray,
    mask: np.ndarray,
) -> float:
    """Return wrapped candidate-minus-target phase RMSE."""
    candidate_values, target_values = _validated_masked_arrays(
        candidate,
        target,
        mask,
    )
    residual = np.angle(np.exp(1j * (candidate_values - target_values)))
    return float(np.sqrt(np.mean(residual**2)))


def masked_nrmse(
    candidate: np.ndarray,
    target: np.ndarray,
    mask: np.ndarray,
) -> float:
    """Return masked RMSE normalized by target maximum absolute magnitude."""
    candidate_values, target_values = _validated_masked_arrays(
        candidate,
        target,
        mask,
    )
    scale = max(float(np.max(np.abs(target_values))), np.finfo(float).eps)
    return float(
        np.sqrt(np.mean((candidate_values - target_values) ** 2)) / scale
    )


def score_candidate(
    metrics: Mapping[str, float],
    thresholds: Mapping[str, float],
) -> ScoreResult:
    """Score a candidate by its worst active tolerance ratio."""
    if not thresholds:
        raise ValueError("at least one threshold is required")
    ratios: dict[str, float] = {}
    for threshold_name, threshold_value_raw in thresholds.items():
        threshold_value = float(threshold_value_raw)
        if not np.isfinite(threshold_value) or threshold_value <= 0:
            raise ValueError(f"invalid threshold: {threshold_name}")
        if threshold_name.endswith("_min"):
            metric_name = threshold_name[: -len("_min")]
            if metric_name not in metrics:
                raise ValueError(f"missing metric: {metric_name}")
            metric_value = float(metrics[metric_name])
            ratio = threshold_value / metric_value if metric_value > 0 else np.inf
        else:
            metric_name = threshold_name
            if metric_name not in metrics:
                raise ValueError(f"missing metric: {metric_name}")
            metric_value = float(metrics[metric_name])
            ratio = metric_value / threshold_value
        if not np.isfinite(metric_value) or not np.isfinite(ratio):
            raise ValueError(f"metric must be finite and valid: {metric_name}")
        if metric_value < 0:
            raise ValueError(f"metric must be non-negative: {metric_name}")
        ratios[metric_name] = float(ratio)

    score = max(ratios.values())
    limiting = tuple(
        sorted(
            name
            for name, ratio in ratios.items()
            if np.isclose(ratio, score, rtol=1e-12, atol=1e-12)
        )
    )
    return ScoreResult(
        score=float(score),
        passed=bool(score <= 1.0),
        limiting_metrics=limiting,
    )


def classify_dataset(
    *,
    contract_valid: bool,
    ode_success_fraction: float,
    baseline_reached: bool,
    stress_changed: bool,
    prefix_improvement: float,
) -> str:
    """Apply the frozen V2 dataset-classification priority."""
    success_fraction = float(ode_success_fraction)
    improvement = float(prefix_improvement)
    if not np.isfinite(success_fraction) or not 0.0 <= success_fraction <= 1.0:
        raise ValueError("ode_success_fraction must be within [0, 1]")
    if not np.isfinite(improvement):
        raise ValueError("prefix_improvement must be finite")
    if not contract_valid:
        return "FAIL_CONTRACT"
    if success_fraction < 0.95:
        return "INCONCLUSIVE_NUMERICAL"
    if stress_changed:
        return "FIXED_INPUT_SENSITIVE"
    if baseline_reached:
        return "REACHED"
    if improvement > 0.10:
        return "INCONCLUSIVE_LIBRARY"
    return "NOT_REACHED_WITHIN_LIBRARY"
