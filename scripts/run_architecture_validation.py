#!/usr/bin/env python3
"""Generate sensitivity, identifiability, and synthetic-recovery evidence."""

from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
import time
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))

from oer_aem.defaults import initialize_oer_parameters
from oer_aem.identifiability import (
    classify_columns,
    matrix_from_importance,
    sensitivity_correlation,
)
from oer_aem.importance import analyze_parameter_importance
from oer_aem.inversion import (
    InversionConfig,
    TPEInverter,
    make_synthetic_target,
)


OUT = ROOT / "results" / "architecture_validation"


def git_head() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        check=True,
        text=True,
        capture_output=True,
    ).stdout.strip()


def write_matrix(
    features: list[str],
    parameters: list[str],
    matrix: np.ndarray,
) -> None:
    with (OUT / "sensitivity_matrix.csv").open("w", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(["feature", *parameters])
        for feature, row in zip(features, matrix):
            writer.writerow([feature, *map(float, row)])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--smoke", action="store_true")
    parser.add_argument("--trials", type=int, default=10)
    args = parser.parse_args()

    config = InversionConfig(
        n_points=256 if args.smoke else 2048,
        points_per_cycle=32 if args.smoke else 128,
        feature_grid_size=32 if args.smoke else 200,
        fit_harmonics=(1, 2, 3),
        seed=42,
    )
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

    OUT.mkdir(parents=True, exist_ok=True)
    write_matrix(features, parameters, matrix)

    # Signed sensitivity table (Phase 3)
    from oer_aem.identifiability import signed_sensitivity_table, coupling_direction
    signed_rows = signed_sensitivity_table(features, parameters, matrix)
    with (OUT / "signed_sensitivity.csv").open("w", newline="") as handle:
        w = csv.DictWriter(handle, fieldnames=list(signed_rows[0]), lineterminator="\n")
        w.writeheader(); w.writerows(signed_rows)

    # Coupling direction table
    coupling = coupling_direction(parameters, correlation)
    with (OUT / "coupling_direction.csv").open("w", newline="") as handle:
        w = csv.writer(handle, lineterminator="\n")
        w.writerow(["parameter", "peer", "correlation", "direction"])
        for param, peers in coupling.items():
            for p in peers:
                w.writerow([param, p["peer"], p["correlation"], p["direction"]])

    with (OUT / "parameter_classification.csv").open(
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
        fixed_params=tuple(
            sorted((name, value) for name, value in truth.items() if name != "k0_1")
        ),
        param_specs=recovery_spec,
        seed=config.seed,
    )
    target = make_synthetic_target(
        truth, config=recovery_config, noise_fraction=0.0
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
    (OUT / "synthetic_recovery.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    )
    print(OUT)


if __name__ == "__main__":
    main()
