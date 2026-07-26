#!/usr/bin/env python3
"""Run Gate A6 paired multi-parameter synthetic recovery."""

from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "code" / "python" / "src"))

from oer_aem.inversion import (
    DEFAULT_PARAM_SPECS,
    InversionConfig,
    TPEInverter,
    make_synthetic_target,
)
from oer_aem.recovery import (
    build_budget_pilot_jobs,
    build_recovery_jobs,
    recovery_metrics,
    truth_library,
)


FEATURE_MODES = ("legacy", "complex_snr", "lockin_only", "hybrid")
OPTIMIZER_SEEDS = (7, 17, 27)
PILOT_BUDGETS = (20, 50, 100)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", choices=("pilot", "formal"), required=True)
    parser.add_argument("--noise-fraction", type=float, required=True)
    parser.add_argument("--noise-evidence", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--trials", type=int)
    parser.add_argument("--smoke", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--max-jobs", type=int)
    return parser.parse_args(argv)


def build_config(
    args: argparse.Namespace,
    *,
    feature_mode: str,
    seed: int,
) -> InversionConfig:
    if args.noise_fraction < 0:
        raise ValueError("noise fraction must be non-negative")
    if args.workers < 1:
        raise ValueError("workers must be positive")
    return InversionConfig(
        n_points=256 if args.smoke else 8192,
        points_per_cycle=32,
        feature_grid_size=128,
        fit_harmonics=(1, 2, 3),
        feature_mode=feature_mode,
        solver_backend="lsoda",
        seed=seed,
    )


def build_jobs(args: argparse.Namespace) -> list[dict]:
    truths = truth_library(DEFAULT_PARAM_SPECS)
    if args.phase == "pilot":
        return build_budget_pilot_jobs(
            modes=FEATURE_MODES,
            truths=truths,
            noise_fraction=args.noise_fraction,
            seeds=OPTIMIZER_SEEDS,
            budgets=PILOT_BUDGETS,
        )
    if args.trials is None or args.trials < 1:
        raise ValueError("formal phase requires positive --trials")
    return build_recovery_jobs(
        modes=FEATURE_MODES,
        truths=truths,
        noise_fractions=(0.0, args.noise_fraction),
        seeds=OPTIMIZER_SEEDS,
        trials=args.trials,
    )


def run_job(job: dict, *, smoke: bool = False) -> dict:
    args = argparse.Namespace(
        smoke=smoke,
        noise_fraction=job["noise_fraction"],
        workers=1,
    )
    config = build_config(
        args,
        feature_mode=job["feature_mode"],
        seed=job["seed"],
    )
    started = time.perf_counter()
    target = make_synthetic_target(
        job["truth_params"],
        config=config,
        noise_fraction=job["noise_fraction"],
        seed=job["target_seed"],
    )
    result = TPEInverter(
        config=config,
        specs=DEFAULT_PARAM_SPECS,
        seed=job["seed"],
    ).run(target, n_trials=job["trials"])
    metrics = recovery_metrics(
        truth=job["truth_params"],
        estimate=result.best_params,
        specs=DEFAULT_PARAM_SPECS,
    )
    return {
        **job,
        "success": result.success,
        "best_value": result.best_value,
        "best_params": result.best_params,
        "parameter_metrics": metrics,
        "n_trials": result.n_trials,
        "n_forward": result.n_forward,
        "n_ode_fail": result.n_ode_fail,
        "n_tafel_fail": result.n_tafel_fail,
        "runtime_seconds": time.perf_counter() - started,
        "configuration": {
            "n_points": config.n_points,
            "points_per_cycle": config.points_per_cycle,
            "feature_grid_size": config.feature_grid_size,
            "solver_backend": config.solver_backend,
        },
    }


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


def validate_noise_evidence(noise_fraction: float, path: Path | None) -> dict:
    if path is None or not path.is_file():
        raise ValueError("formal recovery requires an existing --noise-evidence JSON")
    evidence = json.loads(path.read_text())
    selected = float(evidence["selected_noise_fraction"])
    if not abs(selected - noise_fraction) <= 1e-12:
        raise ValueError(
            "noise fraction does not match evidence: "
            f"requested={noise_fraction:g}, evidence={selected:g}"
        )
    return evidence


def iter_job_results(jobs: list[dict], *, workers: int, smoke: bool):
    if workers == 1:
        for job in jobs:
            yield run_job(job, smoke=smoke)
        return
    with ProcessPoolExecutor(max_workers=min(workers, len(jobs))) as executor:
        futures = {
            executor.submit(run_job, job, smoke=smoke): job["job_id"]
            for job in jobs
        }
        for future in as_completed(futures):
            yield future.result()


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    jobs = build_jobs(args)
    if args.max_jobs is not None:
        if not args.smoke or args.max_jobs < 1:
            raise ValueError("--max-jobs is only allowed as a positive smoke limit")
        jobs = jobs[: args.max_jobs]
    source_commit, dirty = git_state()
    if dirty and not args.smoke and not args.dry_run:
        raise RuntimeError("formal recovery requires a clean Git worktree")
    noise_evidence = None
    if not args.smoke and not args.dry_run:
        noise_evidence = validate_noise_evidence(
            args.noise_fraction, args.noise_evidence
        )
    output = args.output.resolve()
    if output.exists() and any(output.iterdir()):
        raise FileExistsError(f"output directory is not empty: {output}")
    output.mkdir(parents=True, exist_ok=True)
    plan = {
        "phase": args.phase,
        "noise_fraction": args.noise_fraction,
        "workers": args.workers,
        "smoke": args.smoke,
        "job_count": len(jobs),
        "jobs": jobs,
        "noise_evidence": noise_evidence,
        "provenance": {
            "source_commit": source_commit,
            "dirty": dirty,
            "python": platform.python_version(),
            "command": [sys.executable, *sys.argv]
            if argv is None else [sys.executable, *argv],
        },
    }
    (output / "job_plan.json").write_text(
        json.dumps(plan, indent=2, ensure_ascii=False) + "\n"
    )
    if args.dry_run:
        print(output)
        return
    for variable in (
        "OMP_NUM_THREADS",
        "OPENBLAS_NUM_THREADS",
        "MKL_NUM_THREADS",
        "NUMEXPR_NUM_THREADS",
    ):
        os.environ[variable] = "1"
    started = time.perf_counter()
    rows = []
    results_path = output / "results.jsonl"
    with results_path.open("w") as handle:
        for row in iter_job_results(jobs, workers=args.workers, smoke=args.smoke):
            rows.append(row)
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
            handle.flush()
    summary = {
        "phase": args.phase,
        "passed": all(row["success"] for row in rows),
        "job_count": len(jobs),
        "completed_jobs": len(rows),
        "workers": min(args.workers, len(jobs)),
        "duration_seconds": time.perf_counter() - started,
        "n_ode_fail": sum(row["n_ode_fail"] for row in rows),
        "n_tafel_fail": sum(row["n_tafel_fail"] for row in rows),
        "source_commit": source_commit,
        "dirty": dirty,
    }
    (output / "summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n"
    )
    print(output)


if __name__ == "__main__":
    main()
