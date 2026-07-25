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
        fit_harmonics=[1, 2, 3],
    )
    if not importance.get("success"):
        raise RuntimeError(str(importance.get("error")))
    features, parameters, matrix = matrix_from_importance(importance)
    correlation = sensitivity_correlation(matrix)
    labels = classify_columns(parameters, matrix, correlation)

    OUT.mkdir(parents=True, exist_ok=True)
    write_matrix(features, parameters, matrix)
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
    target = make_synthetic_target(truth, config=config, noise_fraction=0.0)
    trial_count = 2 if args.smoke else args.trials
    recovery = TPEInverter(
        config=config,
        seed=config.seed,
        initial_params=truth,
    ).run(target, n_trials=trial_count)
    payload = {
        "git_commit": git_head(),
        "command": " ".join(sys.argv),
        "seed": config.seed,
        "smoke": args.smoke,
        "n_trials": trial_count,
        "n_forward": recovery.n_forward,
        "best_value": recovery.best_value,
        "best_params": recovery.best_params,
        "truth_params": truth,
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
