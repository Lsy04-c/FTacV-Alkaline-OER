#!/usr/bin/env python3
"""Run deterministic Gate A6 one-parameter objective profiles."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import platform
import subprocess
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import replace
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "code" / "python" / "src"))

from oer_aem.inversion import (
    DEFAULT_PARAM_SPECS,
    InversionConfig,
    InversionObjective,
    denormalize_vector,
    encode_params,
    make_synthetic_target,
    normalize_vector,
)
from oer_aem.profiling import profile_grid, summarize_profile
from oer_aem.recovery import truth_library


FEATURE_MODES = ("legacy", "complex_snr", "lockin_only", "hybrid")
PROFILE_PARAMETERS = ("k0_1", "k0_2", "k0_3", "G_OH", "G_O")
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


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--grid-points", type=int, default=41)
    parser.add_argument("--smoke", action="store_true")
    parser.add_argument("--max-profiles", type=int)
    return parser.parse_args(argv)


def build_config(
    args: argparse.Namespace,
    *,
    feature_mode: str,
) -> InversionConfig:
    if args.workers < 1:
        raise ValueError("workers must be positive")
    return InversionConfig(
        n_points=256 if args.smoke else 8192,
        points_per_cycle=32,
        feature_grid_size=128,
        fit_harmonics=(1, 2, 3),
        feature_mode=feature_mode,
        solver_backend="lsoda",
        seed=42,
    )


def build_profile_tasks(args: argparse.Namespace) -> list[dict]:
    if args.grid_points < 3:
        raise ValueError("grid points must be at least 3")
    truth = next(
        case
        for case in truth_library(DEFAULT_PARAM_SPECS)
        if case["truth_id"] == "mixed_b"
    )
    encoded = encode_params(truth["parameters"], DEFAULT_PARAM_SPECS)
    normalized = normalize_vector(encoded, DEFAULT_PARAM_SPECS)
    truth_coordinates = {
        name: float(value)
        for (name, *_), value in zip(DEFAULT_PARAM_SPECS, normalized)
    }
    tasks = [
        {
            "profile_id": f"{mode}__{parameter}",
            "feature_mode": mode,
            "parameter": parameter,
            "truth_id": truth["truth_id"],
            "truth_params": dict(truth["parameters"]),
            "truth_coordinate": truth_coordinates[parameter],
            "grid_points": int(args.grid_points),
            "noise_fraction": 0.0,
        }
        for mode in FEATURE_MODES
        for parameter in PROFILE_PARAMETERS
    ]
    if args.max_profiles is not None:
        if not args.smoke or args.max_profiles < 1:
            raise ValueError(
                "--max-profiles is only allowed as a positive smoke limit"
            )
        tasks = tasks[: args.max_profiles]
    return tasks


def build_profile_problem(task: dict, *, smoke: bool):
    spec = next(
        spec for spec in DEFAULT_PARAM_SPECS if spec[0] == task["parameter"]
    )
    fixed_params = tuple(
        (name, float(value))
        for name, value in task["truth_params"].items()
        if name != task["parameter"]
    )
    args = argparse.Namespace(smoke=smoke, workers=1)
    config = replace(
        build_config(args, feature_mode=task["feature_mode"]),
        fixed_params=fixed_params,
    )
    grid = profile_grid(
        task["truth_coordinate"],
        grid_points=task["grid_points"],
    )
    return config, spec, grid


def run_profile(task: dict, *, smoke: bool = False) -> dict:
    """Evaluate one mode-parameter profile with the complement fixed to truth."""
    config, spec, grid = build_profile_problem(task, smoke=smoke)
    target = make_synthetic_target(
        task["truth_params"],
        config=config,
        noise_fraction=0.0,
    )
    objective = InversionObjective(target, config=config, specs=(spec,))
    rows = []
    for coordinate in grid:
        started = time.perf_counter()
        before_ode = objective.n_ode_fail
        before_tafel = objective.n_tafel_fail
        encoded = denormalize_vector([coordinate], (spec,))
        total_loss = float(objective(encoded))
        ode_success = objective.n_ode_fail == before_ode
        tafel_failed = objective.n_tafel_fail > before_tafel
        row = {
            "profile_id": task["profile_id"],
            "feature_mode": task["feature_mode"],
            "parameter": task["parameter"],
            "truth_id": task["truth_id"],
            "normalized_coordinate": float(coordinate),
            "truth_coordinate": float(task["truth_coordinate"]),
            "is_truth": bool(
                np.isclose(
                    coordinate,
                    task["truth_coordinate"],
                    atol=1e-14,
                )
            ),
            "physical_value": float(
                10.0 ** encoded[0]
                if spec[1] == "log10"
                else encoded[0]
            ),
            "total_loss": total_loss,
            "ode_success": ode_success,
            "tafel_failed": tafel_failed,
            "runtime_seconds": time.perf_counter() - started,
        }
        row.update(
            {
                key: float(objective.last_components[key])
                for key in COMPONENT_KEYS
            }
        )
        rows.append(row)
    summary = summarize_profile(
        rows,
        truth_coordinate=task["truth_coordinate"],
    )
    summary.update(
        {
            "profile_id": task["profile_id"],
            "feature_mode": task["feature_mode"],
            "parameter": task["parameter"],
            "truth_id": task["truth_id"],
            "sampled_points": len(rows),
        }
    )
    return {"task": task, "rows": rows, "summary": summary}


def git_state() -> tuple[str, bool]:
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        check=True,
        text=True,
        capture_output=True,
    ).stdout.strip()
    dirty = bool(
        subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=ROOT,
            check=True,
            text=True,
            capture_output=True,
        ).stdout.strip()
    )
    return commit, dirty


def iter_profile_results(
    tasks: list[dict],
    *,
    workers: int,
    smoke: bool,
):
    if workers == 1:
        for task in tasks:
            yield run_profile(task, smoke=smoke)
        return
    with ProcessPoolExecutor(max_workers=min(workers, len(tasks))) as executor:
        futures = {
            executor.submit(run_profile, task, smoke=smoke): task["profile_id"]
            for task in tasks
        }
        for future in as_completed(futures):
            yield future.result()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    tasks = build_profile_tasks(args)
    source_commit, dirty = git_state()
    if dirty and not args.smoke:
        raise RuntimeError("formal profiles require a clean Git worktree")
    output = args.output.resolve()
    if output.exists() and any(output.iterdir()):
        raise FileExistsError(f"output directory is not empty: {output}")
    output.mkdir(parents=True, exist_ok=True)
    for variable in (
        "OMP_NUM_THREADS",
        "OPENBLAS_NUM_THREADS",
        "MKL_NUM_THREADS",
        "NUMEXPR_NUM_THREADS",
    ):
        os.environ[variable] = "1"

    started = time.perf_counter()
    results = list(
        iter_profile_results(
            tasks,
            workers=args.workers,
            smoke=args.smoke,
        )
    )
    results.sort(key=lambda result: result["task"]["profile_id"])
    all_rows = [row for result in results for row in result["rows"]]
    rows_path = output / "profile_rows.csv"
    with rows_path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(all_rows[0]))
        writer.writeheader()
        writer.writerows(all_rows)

    summaries = [result["summary"] for result in results]
    expected_rows = sum(
        len(
            profile_grid(
                task["truth_coordinate"],
                grid_points=task["grid_points"],
            )
        )
        for task in tasks
    )
    configuration = {
        "n_points": 256 if args.smoke else 8192,
        "points_per_cycle": 32,
        "feature_grid_size": 128,
        "fit_harmonics": [1, 2, 3],
        "feature_modes": list(FEATURE_MODES),
        "profile_parameters": list(PROFILE_PARAMETERS),
        "truth_id": "mixed_b",
        "grid_points": args.grid_points,
        "solver_backend": "lsoda",
        "noise_fraction": 0.0,
        "workers": min(args.workers, len(tasks)),
        "smoke": args.smoke,
    }
    summary = {
        "infrastructure_passed": bool(
            len(results) == len(tasks)
            and len(all_rows) == expected_rows
            and all(
                result["summary"]["truth_loss"] is not None
                and np.isfinite(result["summary"]["truth_loss"])
                for result in results
            )
        ),
        "expected_profiles": len(tasks),
        "completed_profiles": len(results),
        "expected_rows": expected_rows,
        "completed_rows": len(all_rows),
        "duration_seconds": time.perf_counter() - started,
        "source_commit": source_commit,
        "dirty": dirty,
        "configuration": configuration,
        "profiles": summaries,
        "decision": (
            "diagnostic_only; inspect preregistered profile gates before "
            "two-parameter profiling"
        ),
    }
    summary_path = output / "profile_summary.json"
    summary_path.write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n"
    )

    import optuna
    import scipy

    manifest = {
        "source_commit": source_commit,
        "dirty": dirty,
        "command": (
            [sys.executable, *sys.argv]
            if argv is None
            else [sys.executable, *argv]
        ),
        "configuration": configuration,
        "tasks": tasks,
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "numpy": np.__version__,
            "scipy": scipy.__version__,
            "optuna": optuna.__version__,
        },
        "sha256": {
            rows_path.name: _sha256(rows_path),
            summary_path.name: _sha256(summary_path),
        },
    }
    (output / "run_manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n"
    )
    if not summary["infrastructure_passed"]:
        raise RuntimeError("profile infrastructure validation failed")
    print(output)


if __name__ == "__main__":
    main()
