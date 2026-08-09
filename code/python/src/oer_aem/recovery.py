"""Deterministic protocol helpers for Gate A6 synthetic recovery."""

from __future__ import annotations

import hashlib
from collections import defaultdict
from itertools import product
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

import numpy as np

from .inversion import DEFAULT_PARAM_SPECS, ParamSpec, decode_vector, encode_params


# Gate-A6 role policy.  These values are inputs or diagnostic directions in the
# current model; allowing them into a formal free vector silently changes the
# scientific question and is therefore an explicit opt-in only.
FIXED_PARAMETER_NAMES = frozenset(
    {"A", "Cdl", "Ru", "E0_pre", "k0_pre", "gamma", "k0_4", "scaling_OOH_OH"}
)
DIAGNOSTIC_ONLY_PARAMETER_NAMES = frozenset({"gamma"})
EXTERNAL_PARAMETER_NAMES = frozenset(
    {"A", "Cdl", "Ru", "E0_pre", "k0_pre", "a", "T", "beta_recon", "E_recon", "w_recon"}
)
# Keep the value on the existing DEFAULT_PARAM_SPECS log grid (coordinate
# 0.5).  This avoids a one-ulp mismatch between encoded truth and fixed input
# when an inverse-crime profile is expected to reproduce zero loss.
SYNTHETIC_GAMMA = float(10.0 ** -8.5)


@dataclass(frozen=True)
class ParameterSelection:
    """Complete, auditable fixed/free assignment for one inversion task."""

    free_specs: tuple[ParamSpec, ...]
    fixed_params: tuple[tuple[str, float], ...]
    roles: dict[str, str]
    role_override: bool = False

    def to_evidence(self) -> dict[str, Any]:
        roles = dict(sorted(self.roles.items()))
        role_groups = {
            role: [name for name, value in roles.items() if value == role]
            for role in ("free", "fixed", "diagnostic")
        }
        return {
            "selection_schema_version": 1,
            "free_parameters": [name for name, *_ in self.free_specs],
            "fixed_params": {name: value for name, value in self.fixed_params},
            "diagnostic_parameters": role_groups["diagnostic"],
            "roles": roles,
            "role_groups": role_groups,
            "role_override": self.role_override,
        }


def build_parameter_selection(
    *,
    free_names: Sequence[str],
    fixed_values: Mapping[str, float],
    diagnostic_names: Sequence[str] = (),
    specs: Sequence[ParamSpec] = DEFAULT_PARAM_SPECS,
    allow_role_override: bool = False,
) -> ParameterSelection:
    """Build a complete fixed/free assignment without hidden defaults.

    Every optimizer parameter in ``specs`` must be explicitly assigned to
    ``free_names`` or ``fixed_values`` (diagnostic names are held fixed but
    labelled separately).  A fixed-role parameter can only be reopened with
    ``allow_role_override=True``; callers should then treat the result as
    diagnostic evidence rather than formal recovery.
    """
    spec_names = tuple(name for name, *_ in specs)
    spec_set = set(spec_names)
    free = tuple(str(name).strip() for name in free_names if str(name).strip())
    diagnostic = tuple(str(name).strip() for name in diagnostic_names if str(name).strip())
    fixed = {str(name).strip(): float(value) for name, value in fixed_values.items()}
    if len(free) != len(set(free)) or len(diagnostic) != len(set(diagnostic)):
        raise ValueError("duplicate parameter assignment")
    unknown = (set(free) | set(diagnostic) | (set(fixed) - set(EXTERNAL_PARAMETER_NAMES))) - spec_set
    if unknown:
        raise ValueError("unknown parameter assignment: " + ", ".join(sorted(unknown)))
    # A diagnostic parameter is intentionally also given a fixed numerical
    # value: it is not searched, but its role must remain visible in the
    # evidence.  Only free/fixed and free/diagnostic assignments conflict.
    overlap = (set(free) & set(fixed)) | (set(diagnostic) & set(free))
    if overlap:
        raise ValueError("parameter assigned to multiple roles: " + ", ".join(sorted(overlap)))
    if set(FIXED_PARAMETER_NAMES) & set(free) and not allow_role_override:
        blocked = sorted(set(FIXED_PARAMETER_NAMES) & set(free))
        raise ValueError("fixed role cannot be reopened in formal task: " + ", ".join(blocked))
    unvalued_diagnostic = set(diagnostic) - set(fixed)
    if unvalued_diagnostic:
        raise ValueError(
            "diagnostic parameter requires an explicit fixed value: "
            + ", ".join(sorted(unvalued_diagnostic))
        )
    missing = spec_set - set(free) - set(diagnostic) - set(fixed)
    if missing:
        raise ValueError("parameter assignment is incomplete: " + ", ".join(sorted(missing)))
    for spec in specs:
        name = spec[0]
        if name in fixed:
            try:
                encode_params({name: fixed[name]}, (spec,))
            except (KeyError, ValueError) as exc:
                raise ValueError(f"fixed value for {name} is outside its declared bounds") from exc
    for name, value in fixed.items():
        if not np.isfinite(value):
            raise ValueError(f"fixed value for {name} must be finite")
    roles = {name: "free" for name in free}
    roles.update({name: "diagnostic" for name in diagnostic})
    roles.update({name: "fixed" for name in spec_names if name not in roles})
    roles.update({name: "fixed" for name in fixed if name not in roles})
    selected_specs = tuple(spec for spec in specs if spec[0] in set(free))
    ordered_fixed = tuple(
        [(name, fixed[name]) for name in spec_names if name in fixed]
        + [(name, fixed[name]) for name in sorted(set(fixed) - spec_set)]
    )
    return ParameterSelection(
        free_specs=selected_specs,
        fixed_params=ordered_fixed,
        roles=roles,
        role_override=bool(allow_role_override and set(FIXED_PARAMETER_NAMES) & set(free)),
    )


def validate_free_parameters(
    free_names: Sequence[str], *, allow_diagnostic: bool = False
) -> tuple[str, ...]:
    """Validate a formal free-parameter vector against the current role policy.

    The function is intentionally independent of a particular ``ParamSpec``
    list so it can be used by runners before constructing an objective.  A
    diagnostic run must opt in explicitly; production recovery cannot quietly
    turn a fixed/coupled quantity into a searched parameter.
    """
    names = tuple(str(name).strip() for name in free_names if str(name).strip())
    if len(names) != len(set(names)):
        raise ValueError("duplicate free parameter")
    violations = set(names) & FIXED_PARAMETER_NAMES
    if violations and not allow_diagnostic:
        raise ValueError(
            "fixed parameter(s) cannot be free in formal search: "
            + ", ".join(sorted(violations))
        )
    return names


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
        parameters = decode_vector(encoded, specs)
        # gamma is a fixed model input in the current synthetic protocol.  It
        # must not vary with the truth pattern, otherwise recovery metrics can
        # reward an accidental change of the target rather than an optimizer.
        if "gamma" in parameters:
            parameters["gamma"] = SYNTHETIC_GAMMA
        cases.append(
            {
                "truth_id": truth_id,
                "parameters": parameters,
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


def summarize_recovery(
    rows: Sequence[Mapping[str, Any]],
    *,
    parameter_names: Sequence[str],
) -> dict[str, Any]:
    """Aggregate paired seed recovery ranges without claiming confidence intervals."""
    grouped: dict[tuple[Any, ...], list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        key = (
            row["feature_mode"],
            row["truth_id"],
            float(row["noise_fraction"]),
            int(row["trials"]),
        )
        grouped[key].append(row)
    summaries = []
    for key in sorted(grouped):
        mode, truth_id, noise_fraction, trials = key
        members = grouped[key]
        parameters = {}
        for name in parameter_names:
            estimates = np.asarray(
                [float(row["best_params"][name]) for row in members],
                dtype=float,
            )
            truth = float(members[0]["truth_params"][name])
            errors = np.asarray(
                [
                    float(
                        row["parameter_metrics"][name][
                            "normalized_bound_error"
                        ]
                    )
                    for row in members
                ],
                dtype=float,
            )
            boundary_hits = [
                bool(row["parameter_metrics"][name]["boundary_hit"])
                for row in members
            ]
            seed_min = float(np.min(estimates))
            seed_max = float(np.max(estimates))
            parameters[name] = {
                "truth": truth,
                "seed_min": seed_min,
                "seed_max": seed_max,
                "truth_covered_by_seed_range": seed_min <= truth <= seed_max,
                "median_normalized_bound_error": float(np.median(errors)),
                "max_normalized_bound_error": float(np.max(errors)),
                "boundary_hit_rate": float(np.mean(boundary_hits)),
            }
        summaries.append(
            {
                "feature_mode": mode,
                "truth_id": truth_id,
                "noise_fraction": noise_fraction,
                "trials": trials,
                "seeds": sorted(int(row["seed"]) for row in members),
                "all_success": all(bool(row["success"]) for row in members),
                "parameters": parameters,
            }
        )
    return {
        "group_count": len(summaries),
        "groups": summaries,
        "interval_semantics": (
            "Seed min/max is an optimizer-stability range, not a statistical "
            "confidence interval."
        ),
    }
