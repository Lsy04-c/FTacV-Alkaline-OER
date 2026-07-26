"""Deterministic protocol helpers for Gate A6 synthetic recovery."""

from __future__ import annotations

import hashlib
from itertools import product
from typing import Any, Mapping, Sequence

import numpy as np

from .inversion import ParamSpec, decode_vector, encode_params


def noise_fraction_evidence(current: Sequence[float]) -> dict[str, float | str]:
    """Return a time-domain noise estimate and its derivation metadata."""
    values = np.asarray(current, dtype=float).reshape(-1)
    if values.size < 3 or not np.all(np.isfinite(values)):
        raise ValueError("current must contain at least three finite values")
    differences = np.diff(values)
    centered = differences - np.median(differences)
    sigma_difference = 1.4826 * float(np.median(np.abs(centered)))
    sigma_current = sigma_difference / np.sqrt(2.0)
    peak = float(np.max(np.abs(values)))
    if peak <= np.finfo(float).eps:
        raise ValueError("current peak must be non-zero")
    quantization_step = 0.0
    method = "first_difference_mad"
    if sigma_current <= np.finfo(float).eps:
        nonzero_steps = np.abs(differences[np.abs(differences) > 0.0])
        if nonzero_steps.size == 0:
            raise ValueError("current contains no measurable variation")
        quantization_step = float(np.min(nonzero_steps))
        sigma_current = quantization_step / np.sqrt(12.0)
        method = "quantization_floor"
    return {
        "noise_fraction": sigma_current / peak,
        "method": method,
        "zero_difference_fraction": float(np.mean(differences == 0.0)),
        "quantization_step": quantization_step,
        "peak_absolute_current": peak,
    }


def estimate_white_noise_fraction(current: Sequence[float]) -> float:
    """Estimate time-domain noise relative to peak absolute current."""
    return float(noise_fraction_evidence(current)["noise_fraction"])


def truth_library(specs: Sequence[ParamSpec]) -> list[dict[str, Any]]:
    """Return three distinct truth cases strictly inside optimizer bounds."""
    patterns = {
        "center": (0.50,),
        "mixed_a": (0.25, 0.70, 0.40, 0.60, 0.35, 0.65, 0.45, 0.55),
        "mixed_b": (0.70, 0.30, 0.65, 0.35, 0.60, 0.40, 0.70, 0.30),
    }
    cases = []
    for truth_id, pattern in patterns.items():
        unit = np.asarray(
            [pattern[index % len(pattern)] for index in range(len(specs))],
            dtype=float,
        )
        encoded = np.asarray(
            [
                low + value * (high - low)
                for value, (_, _, low, high) in zip(unit, specs)
            ],
            dtype=float,
        )
        cases.append(
            {
                "truth_id": truth_id,
                "parameters": decode_vector(encoded, specs),
                "normalized_coordinates": unit.tolist(),
            }
        )
    return cases


def recovery_metrics(
    *,
    truth: Mapping[str, float],
    estimate: Mapping[str, float],
    specs: Sequence[ParamSpec],
    boundary_fraction: float = 0.01,
) -> dict[str, Any]:
    """Measure recovery in optimizer coordinates and report boundary hits."""
    truth_encoded = encode_params(truth, specs)
    estimate_encoded = encode_params(estimate, specs)
    rows: dict[str, Any] = {}
    boundary_hits = []
    for truth_value, estimate_value, (name, kind, low, high) in zip(
        truth_encoded, estimate_encoded, specs
    ):
        width = float(high - low)
        distance = abs(float(estimate_value - truth_value))
        edge_distance = min(
            float(estimate_value - low),
            float(high - estimate_value),
        )
        if edge_distance / width <= boundary_fraction:
            boundary_hits.append(name)
        rows[name] = {
            "encoding": kind,
            "truth": float(truth[name]),
            "estimate": float(estimate[name]),
            "encoded_absolute_error": distance,
            "normalized_bound_error": distance / width,
            "boundary_hit": name in boundary_hits,
        }
    rows["boundary_hits"] = boundary_hits
    rows["max_normalized_bound_error"] = max(
        rows[name]["normalized_bound_error"] for name, *_ in specs
    )
    return rows


def build_recovery_jobs(
    *,
    modes: Sequence[str],
    truths: Sequence[Mapping[str, Any]],
    noise_fractions: Sequence[float],
    seeds: Sequence[int],
    trials: int,
) -> list[dict[str, Any]]:
    """Build a fully paired deterministic recovery job matrix."""
    if trials < 1:
        raise ValueError("trials must be positive")
    jobs = []
    for mode, truth, noise_fraction, seed in product(
        modes, truths, noise_fractions, seeds
    ):
        if float(noise_fraction) < 0:
            raise ValueError("noise fractions must be non-negative")
        truth_id = str(truth["truth_id"])
        target_key = f"{truth_id}|{float(noise_fraction):.12g}".encode()
        target_seed = int(hashlib.sha256(target_key).hexdigest()[:8], 16)
        jobs.append(
            {
                "job_id": (
                    f"{mode}__{truth_id}__noise-{float(noise_fraction):g}"
                    f"__seed-{int(seed)}__trials-{int(trials)}"
                ),
                "feature_mode": str(mode),
                "truth_id": truth_id,
                "truth_params": dict(truth["parameters"]),
                "noise_fraction": float(noise_fraction),
                "seed": int(seed),
                "target_seed": target_seed,
                "trials": int(trials),
            }
        )
    return jobs


def build_budget_pilot_jobs(
    *,
    modes: Sequence[str],
    truths: Sequence[Mapping[str, Any]],
    noise_fraction: float,
    seeds: Sequence[int],
    budgets: Sequence[int],
) -> list[dict[str, Any]]:
    """Build the 20/50/100-trial pilot on one difficult interior truth."""
    difficult = [truth for truth in truths if truth["truth_id"] == "mixed_b"]
    if len(difficult) != 1:
        raise ValueError("truth library must contain exactly one mixed_b case")
    jobs = []
    for budget in budgets:
        jobs.extend(
            build_recovery_jobs(
                modes=modes,
                truths=difficult,
                noise_fractions=(noise_fraction,),
                seeds=seeds,
                trials=int(budget),
            )
        )
    return jobs


def select_trial_budget(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Select the smallest pilot budget stable against the largest budget."""
    thresholds = {
        "median_paired_error_delta_max": 0.02,
        "p90_paired_error_delta_max": 0.05,
        "boundary_set_agreement_min": 0.8,
    }
    budgets = sorted({int(row["trials"]) for row in rows})
    if len(budgets) < 2:
        raise ValueError("budget selection requires at least two trial budgets")
    reference_budget = budgets[-1]

    def pair_key(row: Mapping[str, Any]) -> tuple[Any, ...]:
        return (
            row["feature_mode"],
            row["truth_id"],
            float(row["noise_fraction"]),
            int(row["seed"]),
        )

    by_budget = {
        budget: {
            pair_key(row): row
            for row in rows
            if int(row["trials"]) == budget
        }
        for budget in budgets
    }
    reference = by_budget[reference_budget]
    summaries: dict[str, Any] = {}
    for budget in budgets:
        candidate = by_budget[budget]
        common = sorted(set(reference) & set(candidate))
        deltas = []
        boundary_matches = []
        success = len(common) == len(reference) and bool(common)
        for key in common:
            left = candidate[key]
            right = reference[key]
            success = success and bool(left["success"]) and bool(right["success"])
            deltas.append(
                abs(
                    float(
                        left["parameter_metrics"]["max_normalized_bound_error"]
                    )
                    - float(
                        right["parameter_metrics"]["max_normalized_bound_error"]
                    )
                )
            )
            boundary_matches.append(
                set(left["parameter_metrics"]["boundary_hits"])
                == set(right["parameter_metrics"]["boundary_hits"])
            )
        median_delta = float(np.median(deltas)) if deltas else float("inf")
        p90_delta = float(np.quantile(deltas, 0.9)) if deltas else float("inf")
        boundary_agreement = (
            float(np.mean(boundary_matches)) if boundary_matches else 0.0
        )
        passed = (
            success
            and median_delta
            <= thresholds["median_paired_error_delta_max"]
            and p90_delta <= thresholds["p90_paired_error_delta_max"]
            and boundary_agreement
            >= thresholds["boundary_set_agreement_min"]
        )
        if budget == reference_budget:
            passed = success
        summaries[str(budget)] = {
            "passed": bool(passed),
            "paired_cases": len(common),
            "median_paired_error_delta": median_delta,
            "p90_paired_error_delta": p90_delta,
            "boundary_set_agreement": boundary_agreement,
        }
    selected = next(
        (
            budget
            for budget in budgets
            if summaries[str(budget)]["passed"]
        ),
        reference_budget,
    )
    return {
        "selected_trials": selected,
        "reference_trials": reference_budget,
        "thresholds": thresholds,
        "budgets": summaries,
    }
