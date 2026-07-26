#!/usr/bin/env python3
"""Generate sensitivity, identifiability, and synthetic-recovery evidence."""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.metadata
import json
import platform
import subprocess
import sys
import time
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "code" / "python" / "src"))

from oer_aem.defaults import initialize_oer_parameters
from oer_aem.identifiability import (
    classify_columns,
    matrix_from_importance,
    sensitivity_correlation,
)
from oer_aem.importance import (
    DEFAULT_PHYSICAL_BOUNDS,
    PERTURBATION_RULES,
    analyze_parameter_importance,
)
from oer_aem.inversion import (
    InversionConfig,
    TPEInverter,
    make_synthetic_target,
)


FEATURE_MODES = ("legacy", "complex_snr", "lockin_only", "hybrid")


def git_head() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        check=True,
        text=True,
        capture_output=True,
    ).stdout.strip()


def git_dirty() -> bool:
    return bool(
        subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=ROOT,
            check=True,
            text=True,
            capture_output=True,
        ).stdout.strip()
    )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_run_manifest(
    *,
    output: Path,
    args: argparse.Namespace,
    config: InversionConfig,
    source_commit: str,
    dirty: bool,
    command: list[str],
    baseline_params: dict[str, float],
) -> dict[str, object]:
    artifacts = sorted(
        path for path in output.iterdir()
        if path.is_file() and path.name != "run_manifest.json"
    )
    versions = {}
    for package in ("numpy", "scipy", "optuna"):
        try:
            versions[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            versions[package] = None
    return {
        "source_commit": source_commit,
        "dirty": dirty,
        "command": command,
        "configuration": {
            "n_points": config.n_points,
            "points_per_cycle": config.points_per_cycle,
            "feature_grid_size": config.feature_grid_size,
            "fit_harmonics": list(config.fit_harmonics),
            "feature_mode": config.feature_mode,
            "solver_backend": config.solver_backend,
            "seed": config.seed,
            "noise_fraction": args.noise_fraction,
            "trials": 2 if args.smoke else args.trials,
            "smoke": args.smoke,
        },
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            **versions,
        },
        "baseline_parameters": baseline_params,
        "perturbation_rules": {
            name: [rule, delta]
            for name, (rule, delta) in PERTURBATION_RULES.items()
        },
        "physical_bounds": {
            name: [lower, upper]
            for name, (lower, upper) in DEFAULT_PHYSICAL_BOUNDS.items()
        },
        "input_sha256": {},
        "sha256": {path.name: sha256_file(path) for path in artifacts},
    }


def write_matrix(
    output: Path,
    features: list[str],
    parameters: list[str],
    matrix: np.ndarray,
) -> None:
    with (output / "sensitivity_matrix.csv").open("w", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(["feature", *parameters])
        for feature, row in zip(features, matrix):
            writer.writerow([feature, *map(float, row)])


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--smoke", action="store_true")
    parser.add_argument("--trials", type=int, default=10)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--feature-mode", choices=FEATURE_MODES, default="legacy")
    parser.add_argument("--feature-grid-size", type=int, default=128)
    parser.add_argument("--solver-backend", choices=("lsoda",), default="lsoda")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--noise-fraction", type=float, default=0.0)
    return parser.parse_args(argv)


def build_config(args: argparse.Namespace) -> InversionConfig:
    if args.feature_grid_size < 1:
        raise ValueError("feature grid size must be positive")
    if args.trials < 1:
        raise ValueError("trials must be positive")
    if args.noise_fraction < 0:
        raise ValueError("noise fraction must be non-negative")
    return InversionConfig(
        n_points=256 if args.smoke else 2048,
        points_per_cycle=32 if args.smoke else 128,
        feature_grid_size=args.feature_grid_size,
        fit_harmonics=(1, 2, 3),
        feature_mode=args.feature_mode,
        solver_backend=args.solver_backend,
        seed=args.seed,
    )


def prepare_output_directory(output: Path) -> None:
    if output.exists() and any(output.iterdir()):
        raise FileExistsError(f"output directory is not empty: {output}")
    output.mkdir(parents=True, exist_ok=True)


def validate_source_state(args: argparse.Namespace, *, dirty: bool) -> None:
    if dirty and not args.smoke:
        raise RuntimeError("formal evidence requires a clean Git worktree")


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    config = build_config(args)
    source_dirty = git_dirty()
    validate_source_state(args, dirty=source_dirty)
    output = args.output.resolve()
    prepare_output_directory(output)
    params = initialize_oer_parameters()
    params.update(
        {
            "E_start": config.E_start,
            "E_end": config.E_end,
            "f": config.f,
            "dE": config.dE,
            "n_points": config.n_points,
            "points_per_cycle": config.points_per_cycle,
            "total_time": config.total_time,
            "v": config.scan_rate,
            "omega": 2 * np.pi * config.f,
            "t_span": config.t_span,
            "gamma": 3e-9,
            "beta_recon": 0.0,
        }
    )

    started = time.monotonic()
    importance = analyze_parameter_importance(
        params,
        config=config,
        exp_harmonic_quality={
            "fit_harmonics": [1, 2, 3],
            "channels": [
                {"harmonic": h, "relative_rms": 1.0} for h in range(1, 4)
            ],
        },
        fit_harmonics=[1, 2, 3],
    )
    if not importance.get("success"):
        raise RuntimeError(str(importance.get("error")))
    features, parameters, matrix = matrix_from_importance(importance)
    correlation = sensitivity_correlation(matrix)
    labels = classify_columns(parameters, matrix, correlation)

    write_matrix(output, features, parameters, matrix)

    # Signed sensitivity table (Phase 3)
    from oer_aem.identifiability import signed_sensitivity_table, coupling_direction
    signed_rows = signed_sensitivity_table(features, parameters, matrix)
    with (output / "signed_sensitivity.csv").open("w", newline="") as handle:
        w = csv.DictWriter(handle, fieldnames=list(signed_rows[0]), lineterminator="\n")
        w.writeheader(); w.writerows(signed_rows)

    # Coupling direction table
    coupling = coupling_direction(parameters, correlation)
    with (output / "coupling_direction.csv").open("w", newline="") as handle:
        w = csv.writer(handle, lineterminator="\n")
        w.writerow(["parameter", "peer", "correlation", "direction"])
        for param, peers in coupling.items():
            for p in peers:
                w.writerow([param, p["peer"], p["correlation"], p["direction"]])

    with (output / "parameter_classification.csv").open(
        "w", newline=""
    ) as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(
            ["parameter", "classification", "sensitivity_norm", "max_correlation"]
        )
        norms = np.linalg.norm(matrix, axis=0)
        for index, parameter in enumerate(parameters):
            peers = np.delete(np.abs(correlation[index]), index)
            writer.writerow(
                [
                    parameter,
                    labels[parameter],
                    float(norms[index]),
                    float(np.max(peers)) if peers.size else 0.0,
                ]
            )

    truth = {
        "k0_1": 100.0,
        "k0_2": 50.0,
        "k0_3": 20.0,
        "k0_4": 80.0,
        "G_OH": 1.23,
        "G_O": 2.80,
        "scaling_OOH_OH": 3.2,
        "gamma": 1e-9,
    }
    recovery_spec = (("k0_1", "log10", 1.0, 3.0),)
    recovery_config = InversionConfig(
        n_points=config.n_points,
        points_per_cycle=config.points_per_cycle,
        feature_grid_size=config.feature_grid_size,
        fit_harmonics=(1, 2, 3),
        feature_mode=config.feature_mode,
        solver_backend=config.solver_backend,
        fixed_params=tuple(
            sorted((name, value) for name, value in truth.items() if name != "k0_1")
        ),
        param_specs=recovery_spec,
        seed=config.seed,
    )
    target = make_synthetic_target(
        truth, config=recovery_config, noise_fraction=args.noise_fraction
    )
    trial_count = 2 if args.smoke else args.trials
    initial = dict(truth)
    initial["k0_1"] = truth["k0_1"] / 10.0
    recovery = TPEInverter(
        config=recovery_config,
        specs=recovery_spec,
        seed=config.seed,
        initial_params=initial,
    ).run(target, n_trials=trial_count)
    relative_recovery_error = abs(
        recovery.best_params["k0_1"] - truth["k0_1"]
    ) / truth["k0_1"]
    payload = {
        "git_commit": git_head(),
        "command": " ".join(sys.argv),
        "configuration": {
            "n_points": config.n_points,
            "points_per_cycle": config.points_per_cycle,
            "feature_grid_size": config.feature_grid_size,
            "fit_harmonics": list(config.fit_harmonics),
            "feature_mode": config.feature_mode,
            "solver_backend": config.solver_backend,
            "noise_fraction": args.noise_fraction,
            "parameter_specs": [list(spec) for spec in recovery_spec],
            "fixed_params": dict(recovery_config.fixed_params),
        },
        "seed": config.seed,
        "smoke": args.smoke,
        "n_trials": trial_count,
        "n_forward": recovery.n_forward,
        "best_value": recovery.best_value,
        "best_params": recovery.best_params,
        "truth_params": truth,
        "designed_identifiable_parameters": ["k0_1"],
        "initial_params": initial,
        "relative_recovery_error": relative_recovery_error,
        "recovery_tolerance": 0.25,
        "recovered": relative_recovery_error <= 0.25,
        "classifications": labels,
        "importance_forward_runs": importance["metadata"]["n_forward_runs"],
        "duration_seconds": round(time.monotonic() - started, 3),
    }
    (output / "synthetic_recovery.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    )
    manifest = build_run_manifest(
        output=output,
        args=args,
        config=config,
        source_commit=git_head(),
        dirty=source_dirty,
        command=[sys.executable, *sys.argv] if argv is None else [sys.executable, *argv],
        baseline_params={
            name: float(params[name])
            for name in PERTURBATION_RULES
            if name in params
        },
    )
    (output / "run_manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n"
    )
    print(output)


if __name__ == "__main__":
    main()
