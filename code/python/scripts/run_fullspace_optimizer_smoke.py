#!/usr/bin/env python3
"""Compare fixed-budget optimizers on one seven-parameter LSODA recovery smoke."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
from dataclasses import replace
from pathlib import Path
from typing import Mapping, Sequence

import numpy as np


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "code" / "python" / "src"))

from oer_aem.inversion import (
    InversionConfig,
    InversionObjective,
    decode_vector,
    denormalize_vector,
    make_synthetic_target,
)
from oer_aem.defaults import initialize_oer_parameters
from oer_aem.optimizers import run_optimizer
from oer_aem.recovery import truth_library


SCHEMA_PATH = (
    ROOT / "config" / "parameter-schemas" / "m0-total-current-effective-v1.json"
)
PARAMETER_NAMES = (
    "k0_1",
    "k0_2",
    "k0_3",
    "k0_4",
    "G_OH",
    "G_O",
    "scaling_OOH_OH",
)
OPTIMIZERS = (
    "tpe",
    "sobol_multibasin_pattern",
    "sobol_multibasin_hybrid",
)
BUDGET = 256
OPTIMIZER_SEED = 23
TARGET_SEED = 9001
TRUTH_ID = "mixed_a"
VALIDATION_RTOL = 1e-8


def parameter_specs_from_schema(
    schema: Mapping[str, object],
    parameter_names: Sequence[str],
) -> tuple[tuple[str, str, float, float], ...]:
    """Build inversion encoding specs from physical schema bounds."""

    parameters = schema.get("parameters")
    if not isinstance(parameters, Mapping):
        raise ValueError("parameter schema must contain parameters")
    specs = []
    for raw_name in parameter_names:
        name = str(raw_name)
        entry = parameters.get(name)
        if not isinstance(entry, Mapping):
            raise ValueError(f"parameter {name} is missing from schema")
        bounds = entry.get("bounds")
        if not isinstance(bounds, Sequence) or len(bounds) != 2:
            raise ValueError(f"parameter {name} bounds are unresolved")
        lower, upper = float(bounds[0]), float(bounds[1])
        if not np.isfinite(lower) or not np.isfinite(upper) or lower >= upper:
            raise ValueError(f"parameter {name} bounds are invalid")
        transform = str(entry.get("transform"))
        if transform == "log10":
            if lower <= 0.0:
                raise ValueError(f"parameter {name} log10 bounds must be positive")
            lower, upper = float(np.log10(lower)), float(np.log10(upper))
        elif transform != "linear":
            raise ValueError(f"parameter {name} transform is unsupported")
        specs.append((name, transform, lower, upper))
    return tuple(specs)


def summarize_recovery(
    parameter_names: Sequence[str],
    *,
    truth_unit: np.ndarray,
    recovered_unit: np.ndarray,
) -> dict[str, object]:
    """Summarize recovery in the common dimensionless unit cube."""

    names = [str(name) for name in parameter_names]
    truth = np.asarray(truth_unit, dtype=float).reshape(-1)
    recovered = np.asarray(recovered_unit, dtype=float).reshape(-1)
    if truth.shape != recovered.shape or truth.shape != (len(names),):
        raise ValueError("recovery vectors must match parameter names")
    if not np.all(np.isfinite(truth)) or not np.all(np.isfinite(recovered)):
        raise ValueError("recovery vectors must be finite")
    signed = recovered - truth
    absolute = np.abs(signed)
    rounded_signed = [float(np.round(value, 15)) for value in signed]
    rounded_absolute = [float(np.round(value, 15)) for value in absolute]
    return {
        "truth_unit": truth.tolist(),
        "recovered_unit": recovered.tolist(),
        "signed_errors": dict(zip(names, rounded_signed)),
        "absolute_errors": dict(zip(names, rounded_absolute)),
        "maximum_absolute_error": float(np.round(np.max(absolute), 15)),
        "median_absolute_error": float(np.round(np.median(absolute), 15)),
        "boundary_hit": bool(np.any((recovered <= 0.0) | (recovered >= 1.0))),
    }


def reduce_parameter_problem(
    specs: Sequence[tuple[str, str, float, float]],
    *,
    truth_unit: np.ndarray,
    fixed_defaults: Mapping[str, float],
) -> tuple[
    tuple[tuple[str, str, float, float], ...],
    np.ndarray,
    tuple[tuple[str, float], ...],
]:
    """Remove fixed inputs while retaining truth coordinates only for free parameters."""

    truth = np.asarray(truth_unit, dtype=float).reshape(-1)
    if truth.shape != (len(specs),):
        raise ValueError("truth coordinates must match parameter specs")
    names = tuple(spec[0] for spec in specs)
    unknown = sorted(set(fixed_defaults) - set(names))
    if unknown:
        raise ValueError(f"fixed parameters are not in specs: {unknown}")

    free_specs = tuple(spec for spec in specs if spec[0] not in fixed_defaults)
    free_truth = np.asarray(
        [value for spec, value in zip(specs, truth) if spec[0] not in fixed_defaults],
        dtype=float,
    )
    fixed = tuple(
        (name, float(fixed_defaults[name]))
        for name in names
        if name in fixed_defaults
    )
    return free_specs, free_truth, fixed


def assess_fixed_input_equivalence(
    *,
    target_current: np.ndarray,
    candidate_current: np.ndarray,
    truth_objective: float,
    current_tolerance_A: float = 1e-8,
    objective_tolerance: float = 1e-6,
) -> dict[str, object]:
    """Apply the pre-registered gate before optimizing a reduced problem."""

    target = np.asarray(target_current, dtype=float).reshape(-1)
    candidate = np.asarray(candidate_current, dtype=float).reshape(-1)
    if target.shape != candidate.shape or not np.all(np.isfinite(candidate)):
        raise ValueError("candidate current must be finite and match target current")
    maximum_difference = float(np.max(np.abs(candidate - target)))
    objective = float(truth_objective)
    passed = (
        np.isfinite(objective)
        and maximum_difference <= current_tolerance_A
        and objective <= objective_tolerance
    )
    return {
        "status": "PASS" if passed else "FAIL",
        "maximum_absolute_current_difference_A": maximum_difference,
        "current_tolerance_A": float(current_tolerance_A),
        "truth_objective": objective,
        "objective_tolerance": float(objective_tolerance),
    }


def validation_fixed_params(
    fixed: Sequence[tuple[str, float]],
    *,
    rtol: float,
) -> tuple[tuple[str, float], ...]:
    """Add a diagnostic solver tolerance without changing scientific inputs."""

    if any(name == "dynamic_rtol" for name, _ in fixed):
        raise ValueError("dynamic_rtol is reserved for validation")
    return tuple(fixed) + (("dynamic_rtol", float(rtol)),)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, payload: object) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _git_commit() -> str:
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
    ).strip()


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--optimizer", action="append")
    parser.add_argument("--fix-default", action="append", default=[])
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    if args.output.exists() and any(args.output.iterdir()):
        raise RuntimeError(f"output directory is not empty: {args.output}")
    args.output.mkdir(parents=True, exist_ok=True)

    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    all_specs = parameter_specs_from_schema(schema, PARAMETER_NAMES)
    target_config = InversionConfig(
        E_start=0.924097277474612,
        E_end=1.9229037265531128,
        f=5.0,
        dE=0.16,
        n_points=256,
        points_per_cycle=32,
        feature_grid_size=32,
        fit_harmonics=(1, 2, 3),
        feature_mode="hybrid",
        solver_backend="lsoda",
        seed=OPTIMIZER_SEED,
        param_specs=all_specs,
    )
    cases = {row["truth_id"]: row for row in truth_library(all_specs)}
    truth_case = cases[TRUTH_ID]
    truth_params = truth_case["parameters"]
    all_truth_unit = np.asarray(truth_case["normalized_coordinates"], dtype=float)
    target = make_synthetic_target(
        truth_params,
        config=target_config,
        noise_fraction=0.0,
        seed=TARGET_SEED,
    )

    defaults = initialize_oer_parameters()
    fixed_defaults = {}
    for name in args.fix_default:
        if name not in defaults:
            raise ValueError(f"fixed parameter has no model default: {name}")
        fixed_defaults[name] = float(defaults[name])
    specs, truth_unit, fixed = reduce_parameter_problem(
        all_specs,
        truth_unit=all_truth_unit,
        fixed_defaults=fixed_defaults,
    )
    if not specs:
        raise ValueError("at least one free parameter is required")
    config = InversionConfig(
        E_start=target_config.E_start,
        E_end=target_config.E_end,
        f=target_config.f,
        dE=target_config.dE,
        n_points=target_config.n_points,
        points_per_cycle=target_config.points_per_cycle,
        feature_grid_size=target_config.feature_grid_size,
        fit_harmonics=target_config.fit_harmonics,
        feature_mode=target_config.feature_mode,
        solver_backend=target_config.solver_backend,
        seed=target_config.seed,
        param_specs=specs,
        fixed_params=fixed,
    )
    free_truth_params = {
        name: float(truth_params[name]) for name, *_ in specs
    }
    validation_target_config = replace(
        target_config,
        fixed_params=validation_fixed_params((), rtol=VALIDATION_RTOL),
    )
    validation_config = replace(
        config,
        fixed_params=validation_fixed_params(fixed, rtol=VALIDATION_RTOL),
    )
    validation_target = make_synthetic_target(
        truth_params,
        config=validation_target_config,
        noise_fraction=0.0,
        seed=TARGET_SEED,
    )
    candidate_target = make_synthetic_target(
        free_truth_params,
        config=validation_config,
        noise_fraction=0.0,
        seed=TARGET_SEED,
    )
    gate_objective = InversionObjective(
        validation_target,
        validation_config,
        specs,
    )
    truth_encoded = denormalize_vector(truth_unit, specs)
    gate = assess_fixed_input_equivalence(
        target_current=np.asarray(validation_target["current"], dtype=float),
        candidate_current=np.asarray(candidate_target["current"], dtype=float),
        truth_objective=gate_objective(truth_encoded),
    )
    if gate["status"] != "PASS":
        _write_json(
            args.output / "summary.json",
            {
                "status": "FAIL_NUMERICAL",
                "failure_stage": "fixed_input_equivalence_gate",
                "eligible_for_formal_conclusions": False,
                "git_commit": _git_commit(),
                "schema_path": str(SCHEMA_PATH.relative_to(ROOT)),
                "schema_sha256": _sha256(SCHEMA_PATH),
                "all_parameter_names": list(PARAMETER_NAMES),
                "free_parameter_names": [name for name, *_ in specs],
                "fixed_parameters": dict(fixed),
                "validation_rtol": VALIDATION_RTOL,
                "fixed_input_equivalence_gate": gate,
            },
        )
        return 2

    requested_optimizers = tuple(args.optimizer or OPTIMIZERS)
    if len(requested_optimizers) != len(set(requested_optimizers)):
        raise ValueError("optimizer names must be unique")
    rows = []
    for optimizer_name in requested_optimizers:
        objective = InversionObjective(target, config, specs)

        def unit_objective(unit) -> float:
            encoded = denormalize_vector(unit, specs)
            return objective(encoded)

        started = time.perf_counter()
        result = run_optimizer(
            optimizer_name,
            unit_objective,
            dimension=len(specs),
            budget=BUDGET,
            seed=OPTIMIZER_SEED,
        )
        wall_seconds = time.perf_counter() - started
        recovered_unit = np.asarray(result.best_unit, dtype=float)
        recovered_encoded = denormalize_vector(recovered_unit, specs)
        rows.append(
            {
                "optimizer": optimizer_name,
                "budget": BUDGET,
                "optimizer_seed": OPTIMIZER_SEED,
                "best_loss": result.best_loss,
                "wall_seconds": wall_seconds,
                "optimization_calls": result.optimization_calls,
                "objective_diagnostics": {
                    "n_calls": objective.n_calls,
                    "n_forward": objective.n_forward,
                    "n_ode_fail": objective.n_ode_fail,
                    "n_feature_fail": objective.n_feature_fail,
                    "n_tafel_fail": objective.n_tafel_fail,
                },
                "recovered_parameters": decode_vector(recovered_encoded, specs),
                "recovery": summarize_recovery(
                    [name for name, *_ in specs],
                    truth_unit=truth_unit,
                    recovered_unit=recovered_unit,
                ),
                "termination_reason": result.termination_reason,
                "evaluations": [
                    {
                        "index": item.index,
                        "phase": item.phase,
                        "unit": list(item.unit),
                        "loss": item.loss,
                        "error": item.error,
                    }
                    for item in result.evaluations
                ],
            }
        )
        print(
            f"[fullspace-smoke] {optimizer_name} "
            f"loss={result.best_loss:.6g} "
            f"max_error={rows[-1]['recovery']['maximum_absolute_error']:.6g} "
            f"wall={wall_seconds:.3f}s",
            flush=True,
        )

    target_current = np.asarray(target["current"], dtype=float)
    summary = {
        "status": "SUCCESS",
        "study_kind": "development_smoke",
        "eligible_for_formal_conclusions": False,
        "scientific_selection_status": "not_run_single_truth_single_seed",
        "git_commit": _git_commit(),
        "dirty_worktree_expected": True,
        "schema_path": str(SCHEMA_PATH.relative_to(ROOT)),
        "schema_sha256": _sha256(SCHEMA_PATH),
        "all_parameter_names": list(PARAMETER_NAMES),
        "free_parameter_names": [name for name, *_ in specs],
        "fixed_parameters": dict(fixed),
        "validation_rtol": VALIDATION_RTOL,
        "fixed_input_equivalence_gate": gate,
        "truth_id": TRUTH_ID,
        "all_truth_unit": all_truth_unit.tolist(),
        "free_truth_unit": truth_unit.tolist(),
        "truth_parameters": truth_params,
        "target_seed": TARGET_SEED,
        "target_noise_fraction": 0.0,
        "target_current_sha256": hashlib.sha256(target_current.tobytes()).hexdigest(),
        "config": {
            "E_start": config.E_start,
            "E_end": config.E_end,
            "f": config.f,
            "dE": config.dE,
            "n_points": config.n_points,
            "points_per_cycle": config.points_per_cycle,
            "feature_grid_size": config.feature_grid_size,
            "fit_harmonics": list(config.fit_harmonics),
            "feature_mode": config.feature_mode,
            "solver_backend": config.solver_backend,
        },
        "requested_optimizers": list(requested_optimizers),
        "rows": rows,
        "prohibited_claims": [
            "optimizer_default_selected",
            "seven_parameters_recoverable",
            "real_data_parameters_identifiable",
        ],
    }
    _write_json(args.output / "summary.json", summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
