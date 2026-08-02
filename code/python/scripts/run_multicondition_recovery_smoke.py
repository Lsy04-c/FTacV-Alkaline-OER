#!/usr/bin/env python3
"""Joint recovery under the baseline and two V4.1-recommended protocols."""

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


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "code" / "python" / "src"))
sys.path.insert(0, str(ROOT / "code" / "python"))

from oer_aem.defaults import initialize_oer_parameters
from oer_aem.inversion import (
    InversionConfig,
    InversionObjective,
    denormalize_vector,
    make_synthetic_target,
)
from oer_aem.optimizers import run_optimizer
from oer_aem.recovery import truth_library
from scripts.run_fullspace_optimizer_smoke import (
    PARAMETER_NAMES,
    SCHEMA_PATH,
    parameter_specs_from_schema,
    summarize_recovery,
)


def build_condition_configs(backend: str) -> dict[str, InversionConfig]:
    """Return a small matched-scan version of the frozen V4.1 portfolio."""

    common = dict(
        E_start=0.924097277474612,
        E_end=1.9229037265531128,
        points_per_cycle=32,
        feature_grid_size=32,
        fit_harmonics=(1, 2, 3),
        feature_mode="hybrid",
        solver_backend=backend,
        seed=23,
    )
    return {
        "baseline_5hz_amp_016": InversionConfig(
            **common, f=5.0, dE=0.16, n_points=256
        ),
        "candidate_5hz_amp_008": InversionConfig(
            **common, f=5.0, dE=0.08, n_points=256
        ),
        "candidate_10hz_matched_scan": InversionConfig(
            **common, f=10.0, dE=0.16, n_points=512
        ),
    }


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
    parser.add_argument("--truth-id", choices=("center", "mixed_a"), required=True)
    parser.add_argument("--backend", choices=("cn", "lsoda"), default="cn")
    parser.add_argument("--candidate-source", type=Path)
    parser.add_argument("--confirm-only", action="store_true")
    args = parser.parse_args(argv)
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
    free_specs = tuple(spec for spec in all_specs if spec[0] != "k0_4")
    free_names = tuple(spec[0] for spec in free_specs)
    truth_case = next(
        row for row in truth_library(all_specs) if row["truth_id"] == args.truth_id
    )
    truth_params = dict(truth_case["parameters"])
    all_truth_unit = np.asarray(truth_case["normalized_coordinates"], dtype=float)
    truth_unit = np.asarray(
        [value for spec, value in zip(all_specs, all_truth_unit) if spec[0] != "k0_4"],
        dtype=float,
    )
    fixed_k04 = float(initialize_oer_parameters()["k0_4"])

    target_configs = {
        name: replace(config, param_specs=all_specs)
        for name, config in build_condition_configs(args.backend).items()
    }
    targets = {
        name: make_synthetic_target(
            truth_params, config=config, noise_fraction=0.0, seed=9001
        )
        for name, config in target_configs.items()
    }
    candidate_configs = {
        name: replace(
            config,
            param_specs=free_specs,
            fixed_params=(("k0_4", fixed_k04),),
        )
        for name, config in target_configs.items()
    }
    objectives = {
        name: InversionObjective(targets[name], candidate_configs[name], free_specs)
        for name in target_configs
    }

    def joint_objective(unit: np.ndarray) -> float:
        encoded = denormalize_vector(unit, free_specs)
        return float(np.mean([objective(encoded) for objective in objectives.values()]))

    started = time.perf_counter()
    if args.confirm_only:
        source = json.loads(args.candidate_source.read_text(encoding="utf-8"))
        if source.get("truth_id") != args.truth_id:
            raise ValueError("candidate source truth does not match")
        recovered = np.asarray(source["recovered_unit"], dtype=float)
        best_loss = joint_objective(recovered)
        optimization_calls = 1
        termination_reason = "candidate evaluated without reoptimization"
        source_sha256 = hashlib.sha256(args.candidate_source.read_bytes()).hexdigest()
    else:
        result = run_optimizer(
            "tpe_powell_hybrid",
            joint_objective,
            dimension=len(free_specs),
            budget=256,
            seed=23,
        )
        recovered = np.asarray(result.best_unit, dtype=float)
        best_loss = float(result.best_loss)
        optimization_calls = int(result.optimization_calls)
        termination_reason = str(result.termination_reason)
        source_sha256 = None

    summary = {
        "status": "SUCCESS",
        "study_kind": "development_v4_portfolio_joint_recovery",
        "eligible_for_formal_conclusions": False,
        "git_commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip(),
        "truth_id": args.truth_id,
        "backend": args.backend,
        "condition_ids": list(target_configs),
        "fixed_parameters": {"k0_4": fixed_k04},
        "free_parameter_names": list(free_names),
        "optimizer": "tpe_powell_hybrid",
        "budget": 256,
        "confirmation_only": bool(args.confirm_only),
        "candidate_source": None if args.candidate_source is None else str(args.candidate_source),
        "candidate_source_sha256": source_sha256,
        "best_loss": best_loss,
        "recovered_unit": recovered.tolist(),
        "recovery": summarize_recovery(
            free_names, truth_unit=truth_unit, recovered_unit=recovered
        ),
        "optimization_calls": optimization_calls,
        "termination_reason": termination_reason,
        "wall_seconds": float(time.perf_counter() - started),
        "objective_diagnostics": {
            name: {
                "n_calls": objective.n_calls,
                "n_forward": objective.n_forward,
                "n_ode_fail": objective.n_ode_fail,
                "n_feature_fail": objective.n_feature_fail,
            }
            for name, objective in objectives.items()
        },
        "prohibited_claims": [
            "six_parameters_recoverable",
            "recommended_experiments_guarantee_identifiability",
            "real_data_parameters_identifiable",
        ],
    }
    _write_json(args.output / "summary.json", summary)
    print(
        f"[joint-recovery] {args.truth_id} {args.backend} loss={best_loss:.6g} "
        f"max_error={summary['recovery']['maximum_absolute_error']:.6g}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
