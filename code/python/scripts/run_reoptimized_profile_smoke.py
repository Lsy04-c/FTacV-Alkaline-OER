#!/usr/bin/env python3
"""Profile one parameter while reoptimizing the remaining free complement."""

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
    decode_vector,
    denormalize_vector,
    make_synthetic_target,
    normalize_vector,
)
from oer_aem.recovery import truth_library
from scripts.run_fullspace_optimizer_smoke import (
    PARAMETER_NAMES,
    SCHEMA_PATH,
    parameter_specs_from_schema,
)
from scripts.run_truth_identifiability_smoke import profile_coordinates


PROFILE_BUDGET = 48


def protocol_config(
    protocol: str,
    backend: str,
    *,
    transfer_coefficient: float = 0.5,
    temperature: float = 298.15,
) -> InversionConfig:
    """Return one small matched-scan protocol for scaling validation."""

    variants = {
        "baseline": (5.0, 0.16, 256),
        "lowamp": (5.0, 0.08, 256),
        "highfreq_matched": (10.0, 0.16, 512),
    }
    if protocol not in variants:
        raise ValueError(f"unknown protocol: {protocol}")
    frequency, amplitude, n_points = variants[protocol]
    return InversionConfig(
        E_start=0.924097277474612,
        E_end=1.9229037265531128,
        f=frequency,
        dE=amplitude,
        n_points=n_points,
        points_per_cycle=32,
        feature_grid_size=32,
        fit_harmonics=(1, 2, 3),
        feature_mode="hybrid",
        solver_backend=backend,
        seed=23,
        fixed_params=(
            ("a", float(transfer_coefficient)),
            ("T", float(temperature)),
        ),
    )


def encoded_best_to_unit(
    encoded: np.ndarray,
    specs: Sequence[tuple[str, str, float, float]],
) -> np.ndarray:
    """Convert the objective's best encoded vector to unit coordinates."""

    return normalize_vector(np.asarray(encoded, dtype=float), specs)


def split_profile_problem(
    specs: Sequence[tuple[str, str, float, float]],
    *,
    truth_unit: np.ndarray,
    profiled_name: str,
    fixed_names: set[str],
) -> tuple[tuple[tuple[str, str, float, float], ...], np.ndarray]:
    """Return complement specs and their truth initialization coordinates."""

    truth = np.asarray(truth_unit, dtype=float).reshape(-1)
    if truth.shape != (len(specs),):
        raise ValueError("truth coordinates must match specs")
    excluded = set(fixed_names) | {str(profiled_name)}
    complement = tuple(spec for spec in specs if spec[0] not in excluded)
    coordinates = np.asarray(
        [value for spec, value in zip(specs, truth) if spec[0] not in excluded],
        dtype=float,
    )
    if not any(spec[0] == profiled_name for spec in specs):
        raise ValueError(f"profiled parameter is not in specs: {profiled_name}")
    return complement, coordinates


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
    parser.add_argument("--parameter", default="G_OH")
    parser.add_argument("--backend", choices=("cn", "lsoda"), default="cn")
    parser.add_argument("--budget", type=int, default=PROFILE_BUDGET)
    parser.add_argument("--candidate-source", type=Path)
    parser.add_argument("--confirm-only", action="store_true")
    parser.add_argument(
        "--truth-id",
        choices=("center", "mixed_a", "mixed_b"),
        default="mixed_a",
    )
    parser.add_argument(
        "--protocol",
        choices=("baseline", "lowamp", "highfreq_matched"),
        default="baseline",
    )
    parser.add_argument("--transfer-coefficient", type=float, default=0.5)
    parser.add_argument("--temperature", type=float, default=298.15)
    parser.add_argument(
        "--fixed-k04-source",
        choices=("model_default", "truth"),
        default="model_default",
    )
    args = parser.parse_args(argv)
    if args.budget < 1:
        parser.error("--budget must be positive")
    if not 0.0 < args.transfer_coefficient < 1.0:
        parser.error("--transfer-coefficient must be between zero and one")
    if args.temperature <= 0.0:
        parser.error("--temperature must be positive")
    if args.confirm_only and args.candidate_source is None:
        parser.error("--confirm-only requires --candidate-source")
    return args


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    if args.output.exists() and any(args.output.iterdir()):
        raise RuntimeError(f"output directory is not empty: {args.output}")
    args.output.mkdir(parents=True, exist_ok=True)

    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    all_specs = parameter_specs_from_schema(schema, PARAMETER_NAMES)
    truth_case = next(
        row for row in truth_library(all_specs) if row["truth_id"] == args.truth_id
    )
    truth_params = dict(truth_case["parameters"])
    truth_params.update({"a": args.transfer_coefficient, "T": args.temperature})
    truth_unit = np.asarray(truth_case["normalized_coordinates"], dtype=float)
    fixed_k04 = (
        float(truth_params["k0_4"])
        if args.fixed_k04_source == "truth"
        else float(initialize_oer_parameters()["k0_4"])
    )
    complement_specs, complement_truth = split_profile_problem(
        all_specs,
        truth_unit=truth_unit,
        profiled_name=args.parameter,
        fixed_names={"k0_4"},
    )
    profile_index = next(
        index for index, spec in enumerate(all_specs) if spec[0] == args.parameter
    )
    profile_spec = all_specs[profile_index]
    target_config = replace(
        protocol_config(
            args.protocol,
            args.backend,
            transfer_coefficient=args.transfer_coefficient,
            temperature=args.temperature,
        ),
        param_specs=all_specs,
    )
    target = make_synthetic_target(
        truth_params,
        config=target_config,
        noise_fraction=0.0,
        seed=9001,
    )

    candidate_rows = None
    candidate_source_sha256 = None
    if args.candidate_source is not None:
        source = json.loads(args.candidate_source.read_text(encoding="utf-8"))
        if source.get("profiled_parameter") != args.parameter:
            raise ValueError("candidate source profiled parameter does not match")
        if source.get("truth_id") != args.truth_id:
            raise ValueError("candidate source truth does not match")
        if source.get("protocol") != args.protocol:
            raise ValueError("candidate source protocol does not match")
        source_conditions = source.get(
            "physical_conditions",
            {"transfer_coefficient": 0.5, "temperature_K": 298.15},
        )
        expected_conditions = {
            "transfer_coefficient": args.transfer_coefficient,
            "temperature_K": args.temperature,
        }
        if source_conditions != expected_conditions:
            raise ValueError("candidate source physical conditions do not match")
        if source.get("fixed_k04_source", "model_default") != args.fixed_k04_source:
            raise ValueError("candidate source k0_4 source does not match")
        if source.get("complement_parameter_names") != [
            name for name, *_ in complement_specs
        ]:
            raise ValueError("candidate source complement does not match")
        candidate_rows = {
            float(row["profile_coordinate"]): np.asarray(
                row["complement_recovered_unit"], dtype=float
            )
            for row in source["rows"]
        }
        candidate_source_sha256 = hashlib.sha256(
            args.candidate_source.read_bytes()
        ).hexdigest()
    coordinates = (
        sorted(candidate_rows)
        if candidate_rows is not None
        else profile_coordinates(float(truth_unit[profile_index]))
    )

    rows = []
    for coordinate in coordinates:
        encoded_profile = denormalize_vector([coordinate], (profile_spec,))
        profile_value = decode_vector(encoded_profile, (profile_spec,))[args.parameter]
        config = replace(
            target_config,
            param_specs=complement_specs,
            fixed_params=(
                ("k0_4", fixed_k04),
                ("a", args.transfer_coefficient),
                ("T", args.temperature),
                (args.parameter, profile_value),
            ),
        )
        objective = InversionObjective(target, config, complement_specs)

        def unit_objective(unit: np.ndarray) -> float:
            return float(objective(denormalize_vector(unit, complement_specs)))

        started = time.perf_counter()
        initial = (
            candidate_rows[float(coordinate)]
            if candidate_rows is not None
            else complement_truth
        )
        if args.confirm_only:
            unit_objective(initial)
            optimizer_success = True
            optimizer_message = "candidate evaluated without reoptimization"
        else:
            result = minimize(
                unit_objective,
                initial,
                method="Powell",
                bounds=[(0.0, 1.0)] * len(complement_specs),
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
            raise RuntimeError("profile optimizer did not evaluate the objective")
        recovered = encoded_best_to_unit(objective.best_x, complement_specs)
        rows.append(
            {
                "profile_coordinate": float(coordinate),
                "offset_from_truth": float(coordinate - truth_unit[profile_index]),
                "profile_physical_value": float(profile_value),
                "minimum_loss": float(objective.best_value),
                "complement_calls": int(objective.n_calls),
                "complement_recovered_unit": recovered.tolist(),
                "complement_truth_unit": complement_truth.tolist(),
                "complement_maximum_truth_error": float(
                    np.max(np.abs(recovered - complement_truth))
                ),
                "ode_failures": int(objective.n_ode_fail),
                "feature_failures": int(objective.n_feature_fail),
                "wall_seconds": float(time.perf_counter() - started),
                "optimizer_success": optimizer_success,
                "optimizer_message": optimizer_message,
            }
        )
        print(
            f"[reoptimized-profile] {args.backend} {args.parameter} "
            f"z={coordinate:.3f} loss={float(objective.best_value):.6g}",
            flush=True,
        )

    summary = {
        "status": "SUCCESS",
        "study_kind": "development_complement_reoptimized_profile",
        "eligible_for_formal_conclusions": False,
        "git_commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip(),
        "schema_path": str(SCHEMA_PATH.relative_to(ROOT)),
        "schema_sha256": hashlib.sha256(SCHEMA_PATH.read_bytes()).hexdigest(),
        "truth_id": args.truth_id,
        "protocol": args.protocol,
        "backend": args.backend,
        "physical_conditions": {
            "transfer_coefficient": args.transfer_coefficient,
            "temperature_K": args.temperature,
        },
        "fixed_k04_source": args.fixed_k04_source,
        "profiled_parameter": args.parameter,
        "profile_truth_coordinate": float(truth_unit[profile_index]),
        "fixed_parameters": {"k0_4": fixed_k04},
        "complement_parameter_names": [name for name, *_ in complement_specs],
        "complement_initialization": "synthetic_truth_optimistic_identifiability_diagnostic",
        "per_coordinate_budget": int(args.budget),
        "confirmation_only": bool(args.confirm_only),
        "candidate_source": (
            None if args.candidate_source is None else str(args.candidate_source)
        ),
        "candidate_source_sha256": candidate_source_sha256,
        "rows": rows,
        "prohibited_claims": [
            "confidence_interval",
            "global_profile_minimum_proven",
            "real_data_parameter_identifiable",
        ],
    }
    _write_json(args.output / "summary.json", summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
