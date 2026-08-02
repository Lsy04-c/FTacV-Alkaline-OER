#!/usr/bin/env python3
"""Profile one learned parameter combination while reoptimizing its complement."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
from dataclasses import replace
from pathlib import Path
from typing import Sequence

import numpy as np
from scipy.optimize import minimize


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "code" / "python" / "src"))
sys.path.insert(0, str(ROOT / "code" / "python"))

from oer_aem.defaults import initialize_oer_parameters
from oer_aem.inversion import (
    InversionConfig,
    InversionObjective,
    denormalize_vector,
    make_synthetic_target,
    normalize_vector,
)
from oer_aem.recovery import truth_library
from oer_aem.optimizers import run_optimizer
from scripts.run_fullspace_optimizer_smoke import (
    PARAMETER_NAMES as ALL_PARAMETER_NAMES,
    SCHEMA_PATH,
    parameter_specs_from_schema,
)


FREE_PARAMETER_NAMES = (
    "k0_1",
    "k0_2",
    "k0_3",
    "G_OH",
    "G_O",
    "scaling_OOH_OH",
)
PROFILE_OFFSETS = (-0.1, -0.05, 0.0, 0.05, 0.1)


def reconstruct_with_fixed_combination(
    *,
    complement_unit: np.ndarray,
    direction: np.ndarray,
    target_coordinate: float,
    pivot_index: int,
) -> np.ndarray:
    """Solve the pivot coordinate so the full vector has the requested projection."""

    vector = np.asarray(direction, dtype=float).reshape(-1)
    complement = np.asarray(complement_unit, dtype=float).reshape(-1)
    if vector.size < 2 or complement.shape != (vector.size - 1,):
        raise ValueError("combination direction and complement dimensions do not match")
    if pivot_index < 0 or pivot_index >= vector.size:
        raise ValueError("pivot index is out of range")
    pivot_loading = float(vector[pivot_index])
    if abs(pivot_loading) <= np.finfo(float).eps:
        raise ValueError("pivot loading must be non-zero")
    full = np.empty(vector.size, dtype=float)
    mask = np.arange(vector.size) != pivot_index
    full[mask] = complement
    full[pivot_index] = (
        float(target_coordinate) - float(vector[mask] @ complement)
    ) / pivot_loading
    return full


def _write_json(path: Path, payload: object) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--geometry", required=True, type=Path)
    parser.add_argument("--direction", type=int, default=6)
    parser.add_argument("--backend", choices=("cn", "lsoda"), default="cn")
    parser.add_argument("--budget", type=int, default=192)
    parser.add_argument(
        "--search",
        choices=("powell", "tpe_powell_hybrid"),
        default="powell",
    )
    parser.add_argument("--candidate-source", type=Path)
    parser.add_argument("--confirm-only", action="store_true")
    parser.add_argument(
        "--truth-id",
        choices=("center", "mixed_a", "mixed_b"),
        default="mixed_a",
    )
    args = parser.parse_args(argv)
    if args.budget < 1:
        parser.error("--budget must be positive")
    if args.confirm_only and args.candidate_source is None:
        parser.error("--confirm-only requires --candidate-source")
    return args


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    if args.output.exists() and any(args.output.iterdir()):
        raise RuntimeError(f"output directory is not empty: {args.output}")
    args.output.mkdir(parents=True, exist_ok=True)

    geometry = json.loads(args.geometry.read_text(encoding="utf-8"))
    if tuple(geometry["parameter_names"]) != FREE_PARAMETER_NAMES:
        raise ValueError("geometry parameter contract does not match")
    directions = np.asarray(geometry["training_geometry"]["directions"], dtype=float)
    direction_index = int(args.direction) - 1
    if direction_index < 0 or direction_index >= directions.shape[1]:
        raise ValueError("direction index is out of range")
    direction = directions[:, direction_index]
    pivot_index = int(np.argmax(np.abs(direction)))
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    all_specs = parameter_specs_from_schema(schema, ALL_PARAMETER_NAMES)
    free_specs = tuple(spec for spec in all_specs if spec[0] != "k0_4")
    truth_case = next(
        row for row in truth_library(all_specs) if row["truth_id"] == args.truth_id
    )
    truth_params = dict(truth_case["parameters"])
    truth_all = np.asarray(truth_case["normalized_coordinates"], dtype=float)
    truth_free = np.asarray(
        [value for spec, value in zip(all_specs, truth_all) if spec[0] != "k0_4"],
        dtype=float,
    )
    truth_coordinate = float(direction @ truth_free)
    fixed_k04 = float(initialize_oer_parameters()["k0_4"])
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
        solver_backend=args.backend,
        seed=23,
        param_specs=all_specs,
    )
    target = make_synthetic_target(
        truth_params,
        config=target_config,
        noise_fraction=0.0,
        seed=9001,
    )
    config = replace(
        target_config,
        param_specs=free_specs,
        fixed_params=(("k0_4", fixed_k04),),
    )
    pivot_mask = np.arange(len(FREE_PARAMETER_NAMES)) != pivot_index
    complement_truth = truth_free[pivot_mask]

    source_rows = None
    source_sha256 = None
    if args.candidate_source is not None:
        source = json.loads(args.candidate_source.read_text(encoding="utf-8"))
        if source.get("direction") != int(args.direction):
            raise ValueError("candidate source direction does not match")
        if source.get("truth_id") != args.truth_id:
            raise ValueError("candidate source truth does not match")
        source_rows = {
            float(row["combination_coordinate"]): np.asarray(
                row["recovered_unit"], dtype=float
            )
            for row in source["rows"]
        }
        source_sha256 = hashlib.sha256(args.candidate_source.read_bytes()).hexdigest()
    coordinates = (
        sorted(source_rows)
        if source_rows is not None
        else [truth_coordinate + offset for offset in PROFILE_OFFSETS]
    )

    rows = []
    for coordinate in coordinates:
        objective = InversionObjective(target, config, free_specs)
        attempted_calls = 0

        def unit_objective(complement: np.ndarray) -> float:
            nonlocal attempted_calls
            attempted_calls += 1
            full = reconstruct_with_fixed_combination(
                complement_unit=complement,
                direction=direction,
                target_coordinate=coordinate,
                pivot_index=pivot_index,
            )
            if np.any(full < 0.0) or np.any(full > 1.0):
                return 1e9
            return float(objective(denormalize_vector(full, free_specs)))

        started = time.perf_counter()
        if args.confirm_only:
            recovered = source_rows[float(coordinate)]
            value = float(objective(denormalize_vector(recovered, free_specs)))
            attempted_calls = 1
            optimizer_success = True
            optimizer_message = "candidate evaluated without reoptimization"
        else:
            if args.search == "tpe_powell_hybrid":
                result = run_optimizer(
                    "tpe_powell_hybrid",
                    unit_objective,
                    dimension=complement_truth.size,
                    budget=args.budget,
                    seed=23,
                )
                optimizer_success = bool(np.isfinite(result.best_loss))
                optimizer_message = str(result.termination_reason)
            else:
                result = minimize(
                    unit_objective,
                    complement_truth,
                    method="Powell",
                    bounds=[(0.0, 1.0)] * complement_truth.size,
                    options={
                        "maxfev": args.budget,
                        "xtol": 1e-4,
                        "ftol": 1e-6,
                        "disp": False,
                    },
                )
                optimizer_success = bool(result.success)
                optimizer_message = str(result.message)
            if objective.best_x is None:
                raise RuntimeError("combination profile produced no valid forward solve")
            recovered = normalize_vector(objective.best_x, free_specs)
            value = float(objective.best_value)
        rows.append(
            {
                "combination_coordinate": float(coordinate),
                "offset_from_truth": float(coordinate - truth_coordinate),
                "minimum_loss": value,
                "recovered_unit": recovered.tolist(),
                "realized_combination_coordinate": float(direction @ recovered),
                "attempted_calls": int(attempted_calls),
                "valid_objective_calls": int(objective.n_calls),
                "ode_failures": int(objective.n_ode_fail),
                "wall_seconds": float(time.perf_counter() - started),
                "optimizer_success": optimizer_success,
                "optimizer_message": optimizer_message,
            }
        )
        print(
            f"[combination-profile] {args.backend} d{args.direction} "
            f"offset={coordinate-truth_coordinate:+.3f} loss={value:.6g}",
            flush=True,
        )

    summary = {
        "status": "SUCCESS",
        "study_kind": "development_combination_reoptimized_profile",
        "eligible_for_formal_conclusions": False,
        "git_commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip(),
        "backend": args.backend,
        "truth_id": args.truth_id,
        "direction": int(args.direction),
        "direction_loadings": {
            name: float(value) for name, value in zip(FREE_PARAMETER_NAMES, direction)
        },
        "pivot_parameter": FREE_PARAMETER_NAMES[pivot_index],
        "truth_combination_coordinate": truth_coordinate,
        "fixed_parameters": {"k0_4": fixed_k04},
        "per_coordinate_budget": int(args.budget),
        "search": args.search,
        "confirmation_only": bool(args.confirm_only),
        "candidate_source": None if args.candidate_source is None else str(args.candidate_source),
        "candidate_source_sha256": source_sha256,
        "geometry_path": str(args.geometry),
        "geometry_sha256": hashlib.sha256(args.geometry.read_bytes()).hexdigest(),
        "rows": rows,
        "prohibited_claims": [
            "confidence_interval",
            "combination_globally_identifiable",
            "real_data_combination_recoverable",
        ],
    }
    _write_json(args.output / "summary.json", summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
