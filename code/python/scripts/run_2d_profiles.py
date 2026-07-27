#!/usr/bin/env python3
"""Run deterministic Gate A6 two-parameter objective profiles.

Only hybrid and lockin_only modes for the 4 remaining candidate parameters
(k0_2, k0_3, G_OH, G_O) = 6 parameter pairs × 2 modes = 12 profiles.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
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
from oer_aem.profiling import profile_grid_2d, summarize_profile_2d
from oer_aem.recovery import truth_library

FEATURE_MODES_2D = ("lockin_only", "hybrid")
PROFILE_PARAMETERS_2D = ("k0_2", "k0_3", "G_OH", "G_O")
COMPONENT_KEYS = (
    "dc", "common_harmonics", "dataset_specific_harmonics",
    "phase", "lockin_common_amplitude", "lockin_dataset_specific_amplitude",
    "lockin_common_phase", "lockin_dataset_specific_phase", "physical",
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--workers", type=int, default=8)
    p.add_argument("--grid-points", "--grid_points", type=int, default=41)
    p.add_argument("--smoke", action="store_true")
    p.add_argument("--max-profiles", "--max_profiles", type=int, default=None)
    return p.parse_args(argv)


def build_config(args: argparse.Namespace, *, feature_mode: str) -> InversionConfig:
    return InversionConfig(
        n_points=256 if args.smoke else 8192,
        points_per_cycle=32,
        feature_grid_size=128,
        fit_harmonics=(1, 2, 3),
        feature_mode=feature_mode,
        solver_backend="lsoda",
        seed=42,
    )


def build_2d_tasks(args: argparse.Namespace) -> list[dict]:
    if args.grid_points < 3:
        raise ValueError("grid points must be at least 3")
    truth = next(
        case for case in truth_library(DEFAULT_PARAM_SPECS)
        if case["truth_id"] == "mixed_b"
    )
    encoded = encode_params(truth["parameters"], DEFAULT_PARAM_SPECS)
    normalized = normalize_vector(encoded, DEFAULT_PARAM_SPECS)
    truth_coords = {
        name: float(val)
        for (name, *_), val in zip(DEFAULT_PARAM_SPECS, normalized)
    }

    # All unique pairs of PROFILE_PARAMETERS_2D
    params = list(PROFILE_PARAMETERS_2D)
    pairs = [(params[i], params[j]) for i in range(len(params)) for j in range(i + 1, len(params))]

    tasks = []
    for mode in FEATURE_MODES_2D:
        for x_param, y_param in pairs:
            tasks.append({
                "profile_id": f"{mode}__{x_param}__{y_param}",
                "feature_mode": mode,
                "x_param": x_param,
                "y_param": y_param,
                "truth_id": truth["truth_id"],
                "truth_params": dict(truth["parameters"]),
                "x_truth": truth_coords[x_param],
                "y_truth": truth_coords[y_param],
                "grid_points": int(args.grid_points),
            })
    if args.max_profiles is not None:
        tasks = tasks[:args.max_profiles]
    return tasks


def run_2d_profile(task: dict, *, smoke: bool = False) -> dict:
    """Evaluate one mode × parameter-pair profile with all other params fixed to truth."""
    x_spec = next(s for s in DEFAULT_PARAM_SPECS if s[0] == task["x_param"])
    y_spec = next(s for s in DEFAULT_PARAM_SPECS if s[0] == task["y_param"])

    fixed = tuple(
        (name, float(val))
        for name, val in task["truth_params"].items()
        if name not in (task["x_param"], task["y_param"])
    )
    config = replace(
        build_config(argparse.Namespace(smoke=smoke, workers=1),
                     feature_mode=task["feature_mode"]),
        fixed_params=fixed,
    )
    grid = profile_grid_2d(
        task["x_truth"], task["y_truth"],
        grid_points=task["grid_points"],
    )
    target = make_synthetic_target(task["truth_params"], config=config, noise_fraction=0.0)
    objective = InversionObjective(target, config=config, specs=(x_spec, y_spec))

    rows = []
    for xc, yc in grid:
        started = time.perf_counter()
        before_ode = objective.n_ode_fail
        before_tafel = objective.n_tafel_fail
        dx = denormalize_vector([xc], (x_spec,))
        dy = denormalize_vector([yc], (y_spec,))
        total_loss = float(objective(np.concatenate([dx, dy])))
        row = {
            "profile_id": task["profile_id"],
            "feature_mode": task["feature_mode"],
            "x_param": task["x_param"],
            "y_param": task["y_param"],
            "x_coordinate": float(xc),
            "y_coordinate": float(yc),
            "x_truth": task["x_truth"],
            "y_truth": task["y_truth"],
            "is_truth": bool(np.isclose(xc, task["x_truth"], atol=1e-14) and
                             np.isclose(yc, task["y_truth"], atol=1e-14)),
            "physical_x": float(10.0 ** dx[0] if x_spec[1] == "log10" else dx[0]),
            "physical_y": float(10.0 ** dy[0] if y_spec[1] == "log10" else dy[0]),
            "total_loss": total_loss,
            "ode_success": objective.n_ode_fail == before_ode,
            "tafel_failed": objective.n_tafel_fail > before_tafel,
            "runtime_seconds": time.perf_counter() - started,
        }
        row.update({key: float(objective.last_components[key]) for key in COMPONENT_KEYS})
        rows.append(row)

    summary = summarize_profile_2d(
        rows, x_truth=task["x_truth"], y_truth=task["y_truth"],
        x_param=task["x_param"], y_param=task["y_param"],
    )
    summary.update({
        "profile_id": task["profile_id"],
        "feature_mode": task["feature_mode"],
        "truth_id": task["truth_id"],
    })
    return {"task": task, "rows": rows, "summary": summary}


def git_state() -> tuple[str, bool]:
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, check=True,
        text=True, capture_output=True,
    ).stdout.strip()
    dirty = bool(subprocess.run(
        ["git", "status", "--porcelain"], cwd=ROOT, check=True,
        text=True, capture_output=True,
    ).stdout.strip())
    return commit, dirty


def iter_results(tasks, *, workers, smoke):
    if workers == 1:
        for task in tasks:
            yield run_2d_profile(task, smoke=smoke)
        return
    with ProcessPoolExecutor(max_workers=min(workers, len(tasks))) as executor:
        futures = {
            executor.submit(run_2d_profile, task, smoke=smoke): task["profile_id"]
            for task in tasks
        }
        for future in as_completed(futures):
            yield future.result()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    tasks = build_2d_tasks(args)
    commit, dirty = git_state()
    if dirty and not args.smoke:
        raise RuntimeError("formal 2D profiles require a clean Git worktree")
    output = args.output.resolve()
    if output.exists() and any(output.iterdir()):
        raise FileExistsError(f"output directory is not empty: {output}")
    output.mkdir(parents=True, exist_ok=True)

    for v in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS",
              "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
        os.environ[v] = "1"

    started = time.perf_counter()
    results = list(iter_results(tasks, workers=args.workers, smoke=args.smoke))
    results.sort(key=lambda r: r["task"]["profile_id"])

    all_rows = [row for r in results for row in r["rows"]]

    # Write rows
    rows_path = output / "profile_2d_rows.csv"
    with rows_path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(all_rows[0]))
        w.writeheader()
        w.writerows(all_rows)

    # Write summaries
    summaries = [r["summary"] for r in results]
    with (output / "profile_2d_summary.json").open("w") as f:
        json.dump(summaries, f, indent=2)

    # Manifest
    manifest = {
        "commit": commit,
        "dirty": dirty,
        "smoke": args.smoke,
        "workers": args.workers,
        "grid_points": args.grid_points,
        "n_tasks": len(tasks),
        "n_rows": len(all_rows),
        "runtime_seconds": time.perf_counter() - started,
        "files": {
            "profile_2d_rows.csv": {"bytes": rows_path.stat().st_size,
                                     "sha256": _sha256(rows_path)},
        },
    }
    with (output / "run_manifest.json").open("w") as f:
        json.dump(manifest, f, indent=2)

    print(f"{len(tasks)} profiles × ~{args.grid_points}² grid points → {len(all_rows)} rows")
    print(f"output: {output}")


if __name__ == "__main__":
    main()
