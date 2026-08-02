#!/usr/bin/env python3
"""Diagnose exact-truth local rank and conditional objective slices."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from dataclasses import replace
from pathlib import Path
from typing import Sequence

import numpy as np


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "code" / "python" / "src"))
sys.path.insert(0, str(ROOT / "code" / "python"))

from oer_aem.defaults import initialize_oer_parameters
from oer_aem.importance import analyze_parameter_importance
from oer_aem.inversion import (
    InversionConfig,
    InversionObjective,
    denormalize_vector,
    encode_params,
    forward_current,
    make_synthetic_target,
    normalize_vector,
)
from oer_aem.recovery import truth_library
from scripts.run_effective_dimension_smoke import (
    NOISE_SEED_POOL,
    decompose_training_reports,
    estimate_anchor_stability_scales,
    load_noise_evidence,
    structurally_observed_feature_names,
)
from scripts.run_fullspace_optimizer_smoke import (
    PARAMETER_NAMES,
    SCHEMA_PATH,
    parameter_specs_from_schema,
)


NOISE_EVIDENCE_PATH = (
    ROOT / "results/formal/identifiability/gate-a6-d9299f8/noise_evidence.json"
)
TRUTH_ID = "mixed_a"
TARGET_SEED = 9001
PROFILE_OFFSETS = (-0.1, -0.05, 0.0, 0.05, 0.1)


def profile_coordinates(
    truth_coordinate: float,
    offsets: Sequence[float] = PROFILE_OFFSETS,
) -> list[float]:
    """Return a unique bounded local slice containing the exact truth."""

    truth = float(truth_coordinate)
    if not np.isfinite(truth) or truth < 0.0 or truth > 1.0:
        raise ValueError("truth coordinate must be finite and in [0,1]")
    coordinates = {
        float(np.round(np.clip(truth + float(offset), 0.0, 1.0), 15))
        for offset in offsets
    }
    coordinates.add(float(np.round(truth, 15)))
    return sorted(coordinates)


def propagation_coordinates(
    truth_coordinate: float,
    default_coordinate: float,
    *,
    grid_size: int = 21,
) -> list[float]:
    """Cover the full bound range while retaining truth and model default."""

    if grid_size < 2:
        raise ValueError("grid_size must be at least two")
    special = (float(truth_coordinate), float(default_coordinate))
    if any(not np.isfinite(value) or value < 0.0 or value > 1.0 for value in special):
        raise ValueError("truth and default coordinates must be in [0,1]")
    values = {
        float(np.round(value, 15))
        for value in np.linspace(0.0, 1.0, grid_size)
    }
    values.update(float(np.round(value, 15)) for value in special)
    return sorted(values)


def parameter_unit_coordinate(
    physical_value: float,
    spec: tuple[str, str, float, float],
) -> float:
    """Encode one physical parameter value into its schema unit coordinate."""

    return float(
        normalize_vector(
            encode_params({spec[0]: float(physical_value)}, (spec,)),
            (spec,),
        )[0]
    )


def _write_json(path: Path, payload: object) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git_commit() -> str:
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
    ).strip()


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    if args.output.exists() and any(args.output.iterdir()):
        raise RuntimeError(f"output directory is not empty: {args.output}")
    args.output.mkdir(parents=True, exist_ok=True)

    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    specs = parameter_specs_from_schema(schema, PARAMETER_NAMES)
    config = InversionConfig(
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
        seed=23,
        param_specs=specs,
    )
    cases = {row["truth_id"]: row for row in truth_library(specs)}
    truth_case = cases[TRUTH_ID]
    truth_params = dict(truth_case["parameters"])
    truth_unit = np.asarray(truth_case["normalized_coordinates"], dtype=float)

    model_defaults = initialize_oer_parameters()
    base = dict(model_defaults)
    base.update(truth_params)
    report = analyze_parameter_importance(
        base,
        config,
        fit_harmonics=[1, 2, 3],
        parameter_names=PARAMETER_NAMES,
    )
    if report.get("success") is False:
        raise RuntimeError(f"truth importance failed: {report.get('error')}")
    record = {
        "anchor_id": "truth-mixed-a",
        "split": "train",
        "unit_coordinates": truth_unit.tolist(),
        "parameters": truth_params,
        "report": report,
    }
    preliminary = decompose_training_reports([record], schema)
    observed_names, structurally_excluded = structurally_observed_feature_names(
        config,
        preliminary["feature_names"],
    )
    proxy = decompose_training_reports(
        [record],
        schema,
        observed_feature_names=observed_names,
    )
    noise_evidence = load_noise_evidence(NOISE_EVIDENCE_PATH)
    stability_scales, stability_audit = estimate_anchor_stability_scales(
        [record],
        schema,
        parameter_names=PARAMETER_NAMES,
        feature_names=proxy["feature_names"],
        config=config,
        noise_fraction=float(noise_evidence["selected_noise_fraction"]),
        noise_seeds=NOISE_SEED_POOL,
    )
    decomposition = decompose_training_reports(
        [record],
        schema,
        stability_scales=stability_scales,
        observed_feature_names=observed_names,
    )
    local = decomposition["subspace_alignment"]["training"]["per_anchor"][0]
    local_singular_values = [float(value) for value in local["local_singular_values"]]
    local_rank = sum(value > 1.0 for value in local_singular_values)

    target = make_synthetic_target(
        truth_params,
        config=config,
        noise_fraction=0.0,
        seed=TARGET_SEED,
    )
    profiles = []
    target_current = np.asarray(target["current"], dtype=float)
    for index, spec in enumerate(specs):
        name = spec[0]
        fixed_params = tuple(
            (other_name, float(value))
            for other_name, value in truth_params.items()
            if other_name != name
        )
        profile_config = replace(
            config,
            fixed_params=fixed_params,
            param_specs=(spec,),
        )
        objective = InversionObjective(target, profile_config, (spec,))
        default_coordinate = parameter_unit_coordinate(
            float(model_defaults[name]),
            spec,
        )
        coordinates = (
            propagation_coordinates(
                float(truth_unit[index]),
                default_coordinate,
            )
            if name == "k0_4"
            else profile_coordinates(float(truth_unit[index]))
        )
        rows = []
        for coordinate in coordinates:
            encoded = denormalize_vector([coordinate], (spec,))
            loss = float(objective(encoded))
            current = forward_current(encoded, profile_config, (spec,))
            if current is None:
                maximum_current_difference = float("inf")
                rms_current_difference = float("inf")
            else:
                current_difference = np.asarray(current, dtype=float) - target_current
                maximum_current_difference = float(
                    np.max(np.abs(current_difference))
                )
                rms_current_difference = float(
                    np.sqrt(np.mean(current_difference**2))
                )
            rows.append(
                {
                    "unit_coordinate": coordinate,
                    "offset_from_truth": float(coordinate - truth_unit[index]),
                    "is_truth": bool(
                        np.isclose(coordinate, truth_unit[index], rtol=0.0, atol=1e-14)
                    ),
                    "is_model_default": bool(
                        np.isclose(coordinate, default_coordinate, rtol=0.0, atol=1e-14)
                    ),
                    "loss": loss,
                    "maximum_absolute_current_difference_A": maximum_current_difference,
                    "rms_current_difference_A": rms_current_difference,
                    "passes_fixed_input_current_gate": bool(
                        maximum_current_difference <= 1e-8
                    ),
                    "ode_failed": bool(objective.n_ode_fail > 0 and loss >= config.ode_penalty),
                }
            )
        profiles.append(
            {
                "parameter": name,
                "truth_unit_coordinate": float(truth_unit[index]),
                "model_default_unit_coordinate": default_coordinate,
                "complement": "fixed_to_truth_diagnostic_not_profile_likelihood",
                "rows": rows,
            }
        )

    report_path = args.output / "importance_report.json"
    _write_json(report_path, report)
    summary = {
        "status": "SUCCESS",
        "study_kind": "development_truth_local_identifiability",
        "eligible_for_formal_conclusions": False,
        "git_commit": _git_commit(),
        "dirty_worktree_expected": True,
        "schema_path": str(SCHEMA_PATH.relative_to(ROOT)),
        "schema_sha256": _sha256(SCHEMA_PATH),
        "truth_id": TRUTH_ID,
        "truth_unit": truth_unit.tolist(),
        "truth_parameters": truth_params,
        "parameter_names": list(PARAMETER_NAMES),
        "noise_evidence": noise_evidence,
        "feature_stability": stability_audit,
        "feature_count": decomposition["feature_count"],
        "structurally_excluded_feature_rows": structurally_excluded,
        "local_singular_values": local_singular_values,
        "local_effective_rank_at_one_sigma": local_rank,
        "local_directions": local["local_directions"],
        "conditional_objective_slices": profiles,
        "artifacts": {
            "importance_report": {
                "path": str(report_path),
                "sha256": _sha256(report_path),
            }
        },
        "prohibited_claims": [
            "conditional_slice_is_profile_likelihood",
            "local_rank_proves_global_identifiability",
            "seven_parameters_recoverable",
        ],
    }
    _write_json(args.output / "summary.json", summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
