"""Frozen protocol for the Gate A6 fixed-budget optimizer benchmark."""

from __future__ import annotations

import hashlib
import math
from dataclasses import asdict
from statistics import median
from typing import Any, Callable, Mapping, Sequence

import numpy as np

from .inversion import (
    DEFAULT_PARAM_SPECS,
    decode_vector,
    denormalize_vector,
)
from .optimizers import run_optimizer
from .recovery import recovery_metrics, truth_library


DEVELOPMENT_OPTIMIZERS = ("tpe", "sobol_pattern", "de_fixed")
DEVELOPMENT_PAIRS = (
    ("k0_2", "k0_3"),
    ("k0_2", "G_O"),
    ("k0_3", "G_O"),
)
DEVELOPMENT_TRUTH_ID = "center"
DEVELOPMENT_NOISE = 0.0
DEVELOPMENT_SEED = 7
OPTIMIZATION_BUDGET = 100
MAX_PARAMETER_ERROR = 0.05

ObjectiveFactory = Callable[
    [Mapping[str, Any]],
    tuple[Callable[[np.ndarray], float], Callable[[], float]],
]


def _select_specs(names: Sequence[str]):
    requested = tuple(names)
    if len(requested) != len(set(requested)):
        raise ValueError("duplicate free parameter")
    by_name = {spec[0]: spec for spec in DEFAULT_PARAM_SPECS}
    try:
        return tuple(by_name[name] for name in requested)
    except KeyError as exc:
        raise ValueError(f"unknown free parameter: {exc.args[0]}") from exc


def _target_seed(truth_id: str, noise_fraction: float) -> int:
    target_key = f"{truth_id}|{noise_fraction:.12g}".encode()
    return int(hashlib.sha256(target_key).hexdigest()[:8], 16)


def build_development_jobs(
    *,
    noise_fraction: float | None = None,
) -> list[dict[str, Any]]:
    """Build the preregistered 3-pair by 3-optimizer development matrix.

    ``noise_fraction`` is accepted so callers can pass the measured-noise
    evidence uniformly across phases. The development matrix intentionally
    remains frozen at zero noise.
    """

    if noise_fraction is not None and (
        not math.isfinite(float(noise_fraction))
        or float(noise_fraction) < 0.0
    ):
        raise ValueError("noise_fraction evidence must be finite and non-negative")
    truths = {
        row["truth_id"]: row
        for row in truth_library(DEFAULT_PARAM_SPECS)
    }
    truth = truths[DEVELOPMENT_TRUTH_ID]
    jobs: list[dict[str, Any]] = []
    for pair in DEVELOPMENT_PAIRS:
        for optimizer in DEVELOPMENT_OPTIMIZERS:
            pair_id = "-".join(pair)
            jobs.append(
                {
                    "job_id": (
                        f"{pair_id}__{optimizer}__{DEVELOPMENT_TRUTH_ID}"
                        f"__noise-{DEVELOPMENT_NOISE:g}"
                        f"__seed-{DEVELOPMENT_SEED}"
                        f"__budget-{OPTIMIZATION_BUDGET}"
                    ),
                    "optimizer": optimizer,
                    "free_parameters": list(pair),
                    "truth_id": DEVELOPMENT_TRUTH_ID,
                    "truth_params": dict(truth["parameters"]),
                    "noise_fraction": DEVELOPMENT_NOISE,
                    "seed": DEVELOPMENT_SEED,
                    "target_seed": _target_seed(
                        DEVELOPMENT_TRUTH_ID,
                        DEVELOPMENT_NOISE,
                    ),
                    "budget": OPTIMIZATION_BUDGET,
                    "feature_mode": "hybrid",
                }
            )
    return jobs


def _validate_development_rows(
    rows: Sequence[Mapping[str, Any]],
) -> dict[str, list[Mapping[str, Any]]]:
    expected_jobs = build_development_jobs()
    expected = {
        (
            tuple(job["free_parameters"]),
            job["optimizer"],
            job["truth_id"],
            float(job["noise_fraction"]),
            int(job["seed"]),
            int(job["budget"]),
        )
        for job in expected_jobs
    }
    actual: set[tuple[Any, ...]] = set()
    grouped = {name: [] for name in DEVELOPMENT_OPTIMIZERS}
    for row in rows:
        key = (
            tuple(row["free_parameters"]),
            str(row["optimizer"]),
            str(row["truth_id"]),
            float(row["noise_fraction"]),
            int(row["seed"]),
            int(row.get("budget", row["optimization_calls"])),
        )
        if key in actual:
            raise ValueError(f"duplicate development job: {key}")
        actual.add(key)
        if not bool(row.get("success")):
            raise ValueError(f"development job failed: {row.get('job_id')}")
        if int(row["optimization_calls"]) != OPTIMIZATION_BUDGET:
            raise ValueError("development optimization_calls must equal 100")
        if int(row.get("n_ode_fail", 0)) != 0:
            raise ValueError("development jobs require zero ODE failures")
        if row["parameter_metrics"].get("boundary_hits"):
            raise ValueError("development jobs require zero boundary hits")
        for field in ("best_objective", "truth_objective"):
            if not math.isfinite(float(row[field])):
                raise ValueError(f"non-finite {field}")
        for name in row["free_parameters"]:
            error = float(
                row["parameter_metrics"][name]["normalized_bound_error"]
            )
            if not math.isfinite(error):
                raise ValueError("non-finite normalized parameter error")
        grouped[str(row["optimizer"])].append(row)
    if actual != expected or len(rows) != len(expected):
        raise ValueError("development rows do not match frozen 9-job matrix")
    return grouped


def select_development_candidate(
    rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Apply the frozen replacement-optimizer eligibility and ranking gate."""

    grouped = _validate_development_rows(rows)
    metrics: dict[str, dict[str, Any]] = {}
    eligible: list[str] = []
    for optimizer in DEVELOPMENT_OPTIMIZERS:
        parameter_errors = [
            float(row["parameter_metrics"][name]["normalized_bound_error"])
            for row in grouped[optimizer]
            for name in row["free_parameters"]
        ]
        regrets = [
            float(row["best_objective"]) - float(row["truth_objective"])
            for row in grouped[optimizer]
        ]
        replacement = optimizer != "tpe"
        passed = replacement and all(
            error <= MAX_PARAMETER_ERROR for error in parameter_errors
        )
        metrics[optimizer] = {
            "eligible_replacement": passed,
            "worst_parameter_error": max(parameter_errors),
            "median_parameter_error": float(median(parameter_errors)),
            "maximum_objective_regret": max(regrets),
            "study_count": len(grouped[optimizer]),
        }
        if passed:
            eligible.append(optimizer)

    preference = {"sobol_pattern": 0, "de_fixed": 1}
    ranked = sorted(
        eligible,
        key=lambda name: (
            metrics[name]["worst_parameter_error"],
            metrics[name]["median_parameter_error"],
            metrics[name]["maximum_objective_regret"],
            preference[name],
        ),
    )
    selected = ranked[0] if ranked else None
    return {
        "gate_version": 1,
        "max_parameter_error": MAX_PARAMETER_ERROR,
        "optimizer_metrics": metrics,
        "eligible_optimizers": eligible,
        "selected_optimizer": selected,
        "scientific_gate_passed": selected is not None,
        "next_action": (
            "PLAN_LOCKED_CONFIRMATION" if selected is not None else "STOP"
        ),
    }


def run_benchmark_job(
    job: Mapping[str, Any],
    *,
    objective_factory: ObjectiveFactory,
) -> dict[str, Any]:
    """Run one optimizer before invoking its isolated truth diagnostic."""

    specs = _select_specs(job["free_parameters"])
    optimization_objective, truth_diagnostic = objective_factory(job)
    result = run_optimizer(
        str(job["optimizer"]),
        optimization_objective,
        dimension=len(specs),
        budget=int(job["budget"]),
        seed=int(job["seed"]),
    )
    best_encoded = denormalize_vector(result.best_unit, specs)
    best_params = decode_vector(best_encoded, specs)
    truth_objective = float(truth_diagnostic())
    if not math.isfinite(truth_objective):
        raise FloatingPointError("non-finite truth diagnostic")
    metrics = recovery_metrics(
        truth=job["truth_params"],
        estimate=best_params,
        specs=specs,
    )
    return {
        **dict(job),
        "success": True,
        "best_unit": list(result.best_unit),
        "best_params": best_params,
        "best_objective": result.best_loss,
        "truth_objective": truth_objective,
        "objective_regret": result.best_loss - truth_objective,
        "optimization_calls": result.optimization_calls,
        "diagnostic_truth_calls": 1,
        "n_ode_fail": int(
            getattr(optimization_objective, "n_ode_fail", 0)
        ),
        "n_tafel_fail": int(
            getattr(optimization_objective, "n_tafel_fail", 0)
        ),
        "n_forward": int(
            getattr(
                optimization_objective,
                "n_forward",
                result.optimization_calls,
            )
        ),
        "parameter_metrics": metrics,
        "termination_reason": result.termination_reason,
        "evaluations": [asdict(record) for record in result.evaluations],
    }
