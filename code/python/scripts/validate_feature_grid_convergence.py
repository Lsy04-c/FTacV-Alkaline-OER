#!/usr/bin/env python3
"""Gate A5: fixed-parameter-library feature-grid convergence."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import platform
import shlex
import subprocess
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Sequence

import numpy as np
from scipy.stats import spearmanr

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "code" / "python" / "src"))
sys.path.insert(0, str(ROOT / "code" / "python" / "scripts"))

from compare_feature_objectives import TRUTH  # noqa: E402
from oer_aem.inversion import (  # noqa: E402
    DEFAULT_PARAM_SPECS,
    InversionConfig,
    InversionObjective,
    extract_features,
    forward_current,
    make_synthetic_target,
)

MODES = ("legacy", "complex_snr", "lockin_only", "hybrid")
GRID_SIZES = (64, 128, 256, None)
N_CANDIDATES = 8
LIBRARY_SEED = 23
RELATIVE_MEDIAN_LIMIT = 0.01
RELATIVE_MAX_LIMIT = 0.05
SPEARMAN_LIMIT = 0.99

COMPONENT_KEYS = (
    "dc",
    "common_harmonics",
    "dataset_specific_harmonics",
    "phase",
    "lockin_common_amplitude",
    "lockin_dataset_specific_amplitude",
    "lockin_common_phase",
    "lockin_dataset_specific_phase",
    "physical",
)


def sample_parameter_library(
    specs: Sequence[tuple[str, str, float, float]],
    n_candidates: int,
    seed: int,
) -> np.ndarray:
    """Return deterministic stratified encoded vectors inside 10%–90% bounds."""
    if n_candidates < 2:
        raise ValueError("n_candidates must be at least 2")
    rng = np.random.default_rng(seed)
    unit = np.empty((n_candidates, len(specs)), dtype=float)
    for column in range(len(specs)):
        strata = (np.arange(n_candidates) + rng.random(n_candidates)) / n_candidates
        unit[:, column] = strata[rng.permutation(n_candidates)]
    unit = 0.10 + 0.80 * unit
    lows = np.asarray([spec[2] for spec in specs], dtype=float)
    highs = np.asarray([spec[3] for spec in specs], dtype=float)
    return lows + unit * (highs - lows)


def stable_relative_error(
    value: float,
    reference: float,
    *,
    scale_floor: float = 1e-12,
) -> float:
    """Return a finite relative error with an explicit near-zero scale floor."""
    return abs(float(value) - float(reference)) / max(abs(float(reference)), scale_floor)


def assess_grid_gate(summaries: Sequence[dict[str, object]]) -> dict[str, object]:
    """Apply preregistered convergence limits to 128- and 256-grid summaries."""
    failures: list[str] = []
    for row in summaries:
        if str(row["grid"]) not in {"128", "256"}:
            continue
        prefix = f"{row['mode']} grid={row['grid']}"
        if not bool(row["all_success"]):
            failures.append(f"{prefix} one or more ODE evaluations failed")
        if not bool(row["all_finite"]):
            failures.append(f"{prefix} one or more metrics are non-finite")
        for metric in (
            "total_loss_relative_error_median",
            "common_dc_rmse_relative_error_median",
            "common_h1_h3_rmse_relative_error_median",
        ):
            value = float(row[metric])
            if not np.isfinite(value) or value > RELATIVE_MEDIAN_LIMIT:
                failures.append(
                    f"{prefix} {metric}={value:.6g}>{RELATIVE_MEDIAN_LIMIT:.6g}"
                )
        for metric in (
            "total_loss_relative_error_max",
            "common_dc_rmse_relative_error_max",
            "common_h1_h3_rmse_relative_error_max",
        ):
            value = float(row[metric])
            if not np.isfinite(value) or value > RELATIVE_MAX_LIMIT:
                failures.append(
                    f"{prefix} {metric}={value:.6g}>{RELATIVE_MAX_LIMIT:.6g}"
                )
        rank = float(row["total_loss_spearman"])
        if not np.isfinite(rank) or rank < SPEARMAN_LIMIT:
            failures.append(
                f"{prefix} total_loss_spearman={rank:.6g}<{SPEARMAN_LIMIT:.6g}"
            )
    return {
        "passed": not failures,
        "n_failures": len(failures),
        "failures": failures,
    }


def _config(mode: str, grid: int | None) -> InversionConfig:
    return InversionConfig(
        E_start=0.924,
        E_end=1.923,
        f=5.0,
        dE=0.16,
        n_points=256 * 32,
        points_per_cycle=32,
        feature_grid_size=grid,
        fit_harmonics=(1, 2, 3, 4, 5, 6, 7),
        feature_mode=mode,
        solver_backend="lsoda",
    )


def _candidate_hash(vector: np.ndarray) -> str:
    return hashlib.sha256(np.asarray(vector, dtype="<f8").tobytes()).hexdigest()


def _evaluate_task(task: tuple[str, int | None, int, list[float]]) -> dict[str, object]:
    mode, grid, candidate_index, vector_values = task
    vector = np.asarray(vector_values, dtype=float)
    config = _config(mode, grid)
    started = time.perf_counter()
    target = make_synthetic_target(TRUTH, config=config, noise_fraction=0.0)
    candidate_current = forward_current(vector, config, DEFAULT_PARAM_SPECS)
    if candidate_current is None:
        return {
            "mode": mode,
            "grid": "full" if grid is None else str(grid),
            "resolved_grid_size": config.resolved_feature_grid_size,
            "candidate": candidate_index,
            "candidate_hash": _candidate_hash(vector),
            "ode_success": False,
            "total_loss": float("nan"),
            **{f"loss_{key}": float("nan") for key in COMPONENT_KEYS},
            "common_dc_rmse": float("nan"),
            "common_h1_h3_rmse": float("nan"),
            "runtime_s": time.perf_counter() - started,
        }
    candidate_features = extract_features(candidate_current, config)
    objective = InversionObjective(target, config=config)
    total_loss = objective(vector)
    dc_rmse = float(
        np.sqrt(
            np.mean(
                (
                    np.asarray(candidate_features["dc"])
                    - np.asarray(target["dc"])
                )
                ** 2
            )
        )
    )
    harmonic_residuals = np.concatenate(
        [
            np.asarray(candidate_features["harm"][index])
            - np.asarray(target["harm"][index])
            for index in range(3)
        ]
    )
    h1_h3_rmse = float(np.sqrt(np.mean(harmonic_residuals**2)))
    return {
        "mode": mode,
        "grid": "full" if grid is None else str(grid),
        "resolved_grid_size": config.resolved_feature_grid_size,
        "candidate": candidate_index,
        "candidate_hash": _candidate_hash(vector),
        "ode_success": True,
        "total_loss": total_loss,
        **{
            f"loss_{key}": float(objective.last_components[key])
            for key in COMPONENT_KEYS
        },
        "common_dc_rmse": dc_rmse,
        "common_h1_h3_rmse": h1_h3_rmse,
        "runtime_s": time.perf_counter() - started,
    }


def summarize_grid_rows(rows: Sequence[dict[str, object]]) -> list[dict[str, object]]:
    """Compare each finite grid with matching full-grid candidates."""
    indexed = {
        (str(row["mode"]), str(row["grid"]), int(row["candidate"])): row
        for row in rows
    }
    summaries: list[dict[str, object]] = []
    for mode in MODES:
        reference = [indexed[(mode, "full", candidate)] for candidate in range(N_CANDIDATES)]
        reference_losses = np.asarray([float(row["total_loss"]) for row in reference])
        for grid in ("64", "128", "256"):
            candidate_rows = [indexed[(mode, grid, candidate)] for candidate in range(N_CANDIDATES)]
            error_sets: dict[str, list[float]] = {
                "total_loss": [],
                "common_dc_rmse": [],
                "common_h1_h3_rmse": [],
            }
            for candidate_row, reference_row in zip(candidate_rows, reference):
                for metric in error_sets:
                    error_sets[metric].append(
                        stable_relative_error(
                            float(candidate_row[metric]),
                            float(reference_row[metric]),
                        )
                    )
            losses = np.asarray([float(row["total_loss"]) for row in candidate_rows])
            rank = float(spearmanr(losses, reference_losses).statistic)
            finite_values = [
                float(row[key])
                for row in candidate_rows
                for key in (
                    "total_loss",
                    "common_dc_rmse",
                    "common_h1_h3_rmse",
                    *(f"loss_{component}" for component in COMPONENT_KEYS),
                )
            ]
            summary: dict[str, object] = {
                "mode": mode,
                "grid": grid,
                "all_success": all(bool(row["ode_success"]) for row in candidate_rows),
                "all_finite": all(np.isfinite(value) for value in finite_values),
                "total_loss_spearman": rank,
            }
            for metric, errors in error_sets.items():
                summary[f"{metric}_relative_error_median"] = float(np.median(errors))
                summary[f"{metric}_relative_error_max"] = float(np.max(errors))
            summaries.append(summary)
    return summaries


def _collect_provenance() -> dict[str, object]:
    commit = subprocess.run(
        ["git", "-C", str(ROOT), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    thread_names = (
        "OMP_NUM_THREADS",
        "OPENBLAS_NUM_THREADS",
        "MKL_NUM_THREADS",
        "NUMEXPR_NUM_THREADS",
    )
    return {
        "source_commit": commit,
        "started_at_cst": datetime.now(
            timezone(timedelta(hours=8))
        ).strftime("%Y-%m-%dT%H:%M:%S%z"),
        "command": shlex.join([sys.executable, *sys.argv]),
        "thread_limits": {name: os.environ.get(name, "unset") for name in thread_names},
        "environment": {
            "python": platform.python_version(),
            "numpy": np.__version__,
            "scipy": __import__("scipy").__version__,
        },
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=ROOT / "results" / "formal" / "feature_grid_convergence" / "gate-a5-grid",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    if args.workers < 1:
        raise ValueError("workers must be positive")
    provenance = _collect_provenance()
    library = sample_parameter_library(
        DEFAULT_PARAM_SPECS,
        n_candidates=N_CANDIDATES,
        seed=LIBRARY_SEED,
    )
    tasks = [
        (mode, grid, candidate, library[candidate].tolist())
        for mode in MODES
        for grid in GRID_SIZES
        for candidate in range(N_CANDIDATES)
    ]
    worker_count = min(args.workers, len(tasks), os.cpu_count() or 1)
    if worker_count == 1:
        rows = [_evaluate_task(task) for task in tasks]
    else:
        with ProcessPoolExecutor(max_workers=worker_count) as executor:
            rows = list(executor.map(_evaluate_task, tasks))
    rows.sort(key=lambda row: (str(row["mode"]), str(row["grid"]), int(row["candidate"])))
    summaries = summarize_grid_rows(rows)
    gate = assess_grid_gate(summaries)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = args.output_dir / "feature_grid_convergence.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    summary = {
        **gate,
        "n_rows": len(rows),
        "workers": worker_count,
        "modes": list(MODES),
        "grids": ["64", "128", "256", "full"],
        "n_candidates": N_CANDIDATES,
        "library_seed": LIBRARY_SEED,
        "library_sha256": hashlib.sha256(
            np.asarray(library, dtype="<f8").tobytes()
        ).hexdigest(),
        "thresholds": {
            "relative_error_median": RELATIVE_MEDIAN_LIMIT,
            "relative_error_max": RELATIVE_MAX_LIMIT,
            "total_loss_spearman": SPEARMAN_LIMIT,
        },
        "grid_summaries": summaries,
        "provenance": provenance,
        "csv": str(csv_path),
    }
    summary_path = args.output_dir / "feature_grid_convergence_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(
        f"FEATURE_GRID_CONVERGENCE passed={gate['passed']} rows={len(rows)} "
        f"failures={gate['n_failures']} workers={worker_count}"
    )
    return 0 if gate["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
