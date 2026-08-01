#!/usr/bin/env python3
"""Run Gate A6 paired multi-parameter synthetic recovery."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import os
import platform
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import replace
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "code" / "python" / "src"))

from oer_aem.inversion import (
    DEFAULT_PARAM_SPECS,
    InversionConfig,
    InversionObjective,
    TPEInverter,
    make_synthetic_target,
)
from oer_aem.recovery import (
    build_budget_pilot_jobs,
    build_recovery_jobs,
    recovery_metrics,
    select_trial_budget,
    summarize_recovery,
    truth_library,
)
from oer_aem.portfolio_recovery import (
    PortfolioObjective,
    build_condition_config,
    build_portfolio_jobs,
    load_pre_experiment_spec,
    target_sha256,
    validate_target_reuse,
)


FEATURE_MODES = ("legacy", "complex_snr", "lockin_only", "hybrid")
OPTIMIZER_SEEDS = (7, 17, 27)
PILOT_BUDGETS = (20, 50, 100)
WORKFLOW_OWNED_FILES = {
    "STATUS.json",
    "._status_signal",
    "stdout.log",
    "stderr.log",
    "task_spec.snapshot.yaml",
}
WORKFLOW_UNTRACKED_PATHS = {".wf_lock"}
WORKFLOW_UNTRACKED_PREFIXES = ("results/",)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", choices=("pilot", "formal"))
    parser.add_argument("--noise-fraction", type=float)
    parser.add_argument("--noise-evidence", type=Path)
    parser.add_argument("--pre-experiment-spec", type=Path)
    parser.add_argument("--portfolio-stage", choices=("S0", "S1", "S2"))
    parser.add_argument("--s1-summary", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--backend", choices=("cn", "lsoda"), default="lsoda")
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--trials", type=int)
    parser.add_argument(
        "--free-parameters",
        default=",".join(name for name, *_ in DEFAULT_PARAM_SPECS),
        help="Comma-separated subset of inversion parameters to optimize",
    )
    parser.add_argument(
        "--feature-modes",
        default=",".join(FEATURE_MODES),
        help="Comma-separated subset of feature modes to evaluate",
    )
    parser.add_argument("--smoke", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--max-jobs", "--max_jobs", type=int, default=None)
    parser.add_argument("--resume", action="store_true")
    return parser.parse_args(argv)


def select_free_specs(value: str):
    names = [name.strip() for name in value.split(",") if name.strip()]
    if len(names) != len(set(names)):
        raise ValueError("duplicate free parameter")
    known = {name for name, *_ in DEFAULT_PARAM_SPECS}
    unknown = sorted(set(names) - known)
    if unknown:
        raise ValueError(f"unknown free parameter: {', '.join(unknown)}")
    if not names:
        raise ValueError("at least one free parameter is required")
    selected = set(names)
    return tuple(spec for spec in DEFAULT_PARAM_SPECS if spec[0] in selected)


def select_feature_modes(value: str) -> tuple[str, ...]:
    modes = [mode.strip() for mode in value.split(",") if mode.strip()]
    if len(modes) != len(set(modes)):
        raise ValueError("duplicate feature mode")
    unknown = sorted(set(modes) - set(FEATURE_MODES))
    if unknown:
        raise ValueError(f"unknown feature mode: {', '.join(unknown)}")
    if not modes:
        raise ValueError("at least one feature mode is required")
    selected = set(modes)
    return tuple(mode for mode in FEATURE_MODES if mode in selected)


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
        solver_backend=args.backend,
        seed=seed,
    )


def validate_backend(backend: str) -> None:
    if backend == "cn":
        from oer_aem import cpp_bridge

        if not cpp_bridge.is_available():
            raise RuntimeError(
                "CN backend requested but unavailable; fallback is forbidden"
            )


def build_jobs(args: argparse.Namespace) -> list[dict]:
    if args.pre_experiment_spec is not None:
        if args.portfolio_stage is None:
            raise ValueError("--portfolio-stage is required with --pre-experiment-spec")
        if args.phase is not None or args.noise_fraction is not None:
            raise ValueError("legacy phase/noise override is forbidden in portfolio mode")
        if args.trials is not None:
            raise ValueError("trial override is forbidden in portfolio mode")
        if args.free_parameters != ",".join(name for name, *_ in DEFAULT_PARAM_SPECS):
            raise ValueError("free-parameter override is forbidden in portfolio mode")
        if args.feature_modes != ",".join(FEATURE_MODES):
            raise ValueError("feature-mode override is forbidden in portfolio mode")
        if args.max_jobs is not None and args.portfolio_stage != "S0":
            raise ValueError("--max-jobs is only allowed for S0")
        spec = load_pre_experiment_spec(args.pre_experiment_spec)
        eligible_pairs = None
        if args.portfolio_stage == "S2":
            if args.s1_summary is None or not args.s1_summary.is_file():
                raise ValueError("S2 requires an existing --s1-summary")
            try:
                s1_summary = json.loads(args.s1_summary.read_text(encoding="utf-8"))
                eligible_pairs = s1_summary["eligible_parameter_pairs"]
            except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
                raise ValueError("S1 summary has no valid eligible_parameter_pairs") from exc
        jobs = build_portfolio_jobs(
            spec,
            stage=args.portfolio_stage,
            backend=args.backend,
            eligible_pairs=eligible_pairs,
        )
        spec_path = args.pre_experiment_spec.resolve()
        spec_sha256 = hashlib.sha256(spec_path.read_bytes()).hexdigest()
        for job in jobs:
            job["pre_experiment_spec"] = str(spec_path)
            job["pre_experiment_spec_sha256"] = spec_sha256
        return jobs
    if args.phase is None or args.noise_fraction is None:
        raise ValueError("legacy recovery requires --phase and --noise-fraction")
    free_specs = select_free_specs(args.free_parameters)
    free_parameters = [name for name, *_ in free_specs]
    feature_modes = select_feature_modes(args.feature_modes)
    truths = truth_library(DEFAULT_PARAM_SPECS)
    if args.phase == "pilot":
        jobs = build_budget_pilot_jobs(
            modes=feature_modes,
            truths=truths,
            noise_fraction=args.noise_fraction,
            seeds=OPTIMIZER_SEEDS,
            budgets=PILOT_BUDGETS,
        )
    else:
        if args.trials is None or args.trials < 1:
            raise ValueError("formal phase requires positive --trials")
        jobs = build_recovery_jobs(
            modes=feature_modes,
            truths=truths,
            noise_fractions=(0.0, args.noise_fraction),
            seeds=OPTIMIZER_SEEDS,
            trials=args.trials,
        )
    for job in jobs:
        job["free_parameters"] = free_parameters
        job["backend"] = args.backend
    return jobs


def limit_jobs(jobs: list[dict], max_jobs: int | None) -> list[dict]:
    if max_jobs is None:
        return list(jobs)
    if max_jobs < 1:
        raise ValueError("--max-jobs must be positive")
    return list(jobs[:max_jobs])


def prepare_output_directory(output: Path, *, resume: bool = False) -> None:
    if not output.exists():
        output.mkdir(parents=True, exist_ok=True)
        return
    if not output.is_dir():
        raise FileExistsError(f"output path is not a directory: {output}")
    scientific_entries = [
        entry.name
        for entry in output.iterdir()
        if entry.name not in WORKFLOW_OWNED_FILES
        and not entry.name.startswith("STATUS.json.tmp.")
    ]
    if resume:
        allowed = {
            "job_plan.json",
            "results.jsonl",
            "summary.json",
            "pre_experiment_recovery_spec.json",
            "protocol_catalog.csv",
            "target_manifest.json",
            "portfolio_recovery.csv",
            "run_manifest.json",
        }
        unknown = [
            name
            for name in scientific_entries
            if name not in allowed
            and not name.startswith((".results.", ".job_plan.", ".summary."))
        ]
        if unknown:
            raise FileExistsError(
                "resume directory contains unknown scientific output: "
                f"{sorted(unknown)}"
            )
        present = set(scientific_entries)
        if ("results.jsonl" in present or "summary.json" in present) and (
            "job_plan.json" not in present
        ):
            raise ValueError(
                "resume requires job_plan.json when results or summary exist"
            )
        return
    if scientific_entries:
        raise FileExistsError(
            "output directory contains existing scientific output: "
            f"{sorted(scientific_entries)}"
        )


def build_recovery_problem(job: dict, *, smoke: bool):
    free_specs = select_free_specs(",".join(job["free_parameters"]))
    free_names = {name for name, *_ in free_specs}
    fixed_params = tuple(
        (name, float(value))
        for name, value in job["truth_params"].items()
        if name not in free_names
    )
    args = argparse.Namespace(
        smoke=smoke,
        noise_fraction=job["noise_fraction"],
        workers=1,
        backend=job["backend"],
    )
    config = build_config(
        args,
        feature_mode=job["feature_mode"],
        seed=job["seed"],
    )
    return replace(config, fixed_params=fixed_params), free_specs


def _canonical_json(value) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _job_input_payload(job: dict, *, smoke: bool) -> dict:
    clean_job = {key: value for key, value in job.items() if key != "job_input_hash"}
    if "portfolio_stage" in clean_job:
        spec_path = Path(clean_job["pre_experiment_spec"])
        if hashlib.sha256(spec_path.read_bytes()).hexdigest() != clean_job.get(
            "pre_experiment_spec_sha256"
        ):
            raise ValueError("pre-experiment spec hash mismatch")
        spec = load_pre_experiment_spec(spec_path)
        free_specs = select_free_specs(",".join(clean_job["free_parameters"]))
        condition_configs = {}
        for condition_id in clean_job["condition_ids"]:
            config = build_condition_config(
                spec,
                spec.conditions[condition_id],
                truth=clean_job["truth_params"],
                free_specs=free_specs,
                backend=clean_job["backend"],
                seed=clean_job["seed"],
                smoke=smoke,
            )
            condition_configs[condition_id] = {
                "n_points": config.n_points,
                "points_per_cycle": config.points_per_cycle,
                "feature_grid_size": config.feature_grid_size,
                "fit_harmonics": list(config.fit_harmonics),
                "feature_mode": config.feature_mode,
                "solver_backend": config.solver_backend,
                "fixed_params": [list(item) for item in config.fixed_params],
            }
        return {
            "job": clean_job,
            "configuration": {"conditions": condition_configs},
        }
    config, _ = build_recovery_problem(clean_job, smoke=smoke)
    return {
        "job": clean_job,
        "configuration": {
            "n_points": config.n_points,
            "points_per_cycle": config.points_per_cycle,
            "feature_grid_size": config.feature_grid_size,
            "fit_harmonics": list(config.fit_harmonics),
            "feature_mode": config.feature_mode,
            "solver_backend": config.solver_backend,
            "fixed_params": [list(item) for item in config.fixed_params],
        },
    }


def job_input_hash(job: dict, *, smoke: bool) -> str:
    payload = _job_input_payload(job, smoke=smoke)
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def build_resume_metadata(
    args: argparse.Namespace,
    jobs: list[dict],
    provenance: dict,
    noise_evidence: dict | None,
) -> dict:
    smoke_run = args.smoke or args.portfolio_stage == "S0"
    job_hashes = {
        job["job_id"]: job_input_hash(job, smoke=smoke_run) for job in jobs
    }
    fingerprint_payload = {
        "schema_version": 2,
        "source_commit": provenance["source_commit"],
        "dirty": provenance["dirty"],
        "dirty_paths": sorted(provenance.get("dirty_paths", [])),
        "phase": args.phase,
        "portfolio_stage": args.portfolio_stage,
        "pre_experiment_spec_sha256": (
            jobs[0].get("pre_experiment_spec_sha256") if jobs else None
        ),
        "smoke": smoke_run,
        "noise_fraction": args.noise_fraction,
        "noise_evidence_sha256": (
            noise_evidence.get("sha256") if noise_evidence else None
        ),
        "jobs": [
            {"job_id": job["job_id"], "job_input_hash": job_hashes[job["job_id"]]}
            for job in jobs
        ],
    }
    return {
        "resume_schema_version": 2,
        "resume_fingerprint": hashlib.sha256(
            _canonical_json(fingerprint_payload).encode("utf-8")
        ).hexdigest(),
        "job_input_hashes": job_hashes,
    }


def _atomic_write_text(path: Path, text: str, *, prefix: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        dir=path.parent, prefix=prefix, suffix=".tmp"
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        try:
            directory = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        except OSError:
            pass
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def atomic_write_json(path: Path, value: dict, *, prefix: str) -> None:
    _atomic_write_text(
        path,
        json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
        prefix=prefix,
    )


def atomic_write_checkpoint(
    path: Path, rows_by_id: dict[str, dict], planned_ids: list[str]
) -> None:
    lines = [
        json.dumps(
            rows_by_id[job_id], ensure_ascii=False, allow_nan=False
        )
        for job_id in planned_ids
        if job_id in rows_by_id
    ]
    _atomic_write_text(
        path,
        "".join(f"{line}\n" for line in lines),
        prefix=".results.",
    )


def _assert_finite(value, *, location: str) -> None:
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError(f"non-finite value at {location}")
    if isinstance(value, dict):
        for key, item in value.items():
            _assert_finite(item, location=f"{location}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _assert_finite(item, location=f"{location}[{index}]")


def load_checkpoint_rows(
    path: Path, expected_hashes: dict[str, str]
) -> dict[str, dict]:
    if not path.exists() or path.stat().st_size == 0:
        return {}
    raw = path.read_text(encoding="utf-8")
    if not raw.endswith("\n"):
        raise ValueError("results.jsonl ends with an incomplete line")
    rows: dict[str, dict] = {}
    for line_number, line in enumerate(raw.splitlines(), start=1):
        if not line.strip():
            raise ValueError(f"blank JSONL line at {line_number}")
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid JSON at line {line_number}") from exc
        if not isinstance(row, dict):
            raise ValueError(f"line {line_number} is not a JSON object")
        job_id = row.get("job_id")
        if not isinstance(job_id, str):
            raise ValueError(f"line {line_number} missing job_id")
        if job_id not in expected_hashes:
            raise ValueError(f"unknown job_id at line {line_number}: {job_id}")
        if job_id in rows:
            raise ValueError(f"duplicate job_id at line {line_number}: {job_id}")
        stored_hash = row.get("job_input_hash")
        if not isinstance(stored_hash, str):
            raise ValueError(f"line {line_number} missing job_input_hash")
        if stored_hash != expected_hashes[job_id]:
            raise ValueError(f"job_input_hash mismatch for {job_id}")
        rows[job_id] = row
    required = {
        "success",
        "best_value",
        "best_params",
        "parameter_metrics",
        "n_trials",
        "n_forward",
        "n_ode_fail",
        "n_tafel_fail",
        "runtime_seconds",
        "configuration",
    }
    for job_id, row in rows.items():
        _assert_finite(row, location=job_id)
        missing = sorted(required - row.keys())
        if missing:
            raise ValueError(f"checkpoint row {job_id} missing fields: {missing}")
    return rows


def build_inverter(job: dict, config: InversionConfig, free_specs):
    return TPEInverter(
        config=config,
        specs=free_specs,
        seed=job["seed"],
    )


def run_job(job: dict, *, smoke: bool = False) -> dict:
    if "portfolio_stage" in job:
        return run_portfolio_job(job, smoke=smoke)
    config, free_specs = build_recovery_problem(job, smoke=smoke)
    started = time.perf_counter()
    target = make_synthetic_target(
        job["truth_params"],
        config=config,
        noise_fraction=job["noise_fraction"],
        seed=job["target_seed"],
    )
    result = build_inverter(job, config, free_specs).run(
        target, n_trials=job["trials"]
    )
    metrics = recovery_metrics(
        truth=job["truth_params"],
        estimate=result.best_params,
        specs=free_specs,
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


def run_portfolio_job(job: dict, *, smoke: bool = False) -> dict:
    """Run one paired multi-condition recovery study."""
    spec_path = Path(job["pre_experiment_spec"])
    if hashlib.sha256(spec_path.read_bytes()).hexdigest() != job.get(
        "pre_experiment_spec_sha256"
    ):
        raise ValueError("pre-experiment spec hash mismatch")
    spec = load_pre_experiment_spec(spec_path)
    free_specs = select_free_specs(",".join(job["free_parameters"]))
    started = time.perf_counter()
    objectives = []
    target_records = []
    configs = {}
    identities = {
        item["condition_id"]: item for item in job["target_identities"]
    }
    for condition_id in job["condition_ids"]:
        condition = spec.conditions[condition_id]
        config = build_condition_config(
            spec,
            condition,
            truth=job["truth_params"],
            free_specs=free_specs,
            backend=job["backend"],
            seed=job["seed"],
            smoke=smoke,
        )
        identity = identities[condition_id]
        target = make_synthetic_target(
            job["truth_params"],
            config=config,
            noise_fraction=job["noise_fraction"],
            seed=identity["target_seed"],
        )
        condition_objective = InversionObjective(
            target,
            config=config,
            specs=free_specs,
        )
        target_records.append(
            {
                **identity,
                "target_sha256": target_sha256(
                    target,
                    condition_objective.channel_contract.sha256,
                ),
                "channel_contract_sha256": (
                    condition_objective.channel_contract.sha256
                ),
            }
        )
        objectives.append((condition_id, condition_objective))
        configs[condition_id] = config
    validate_target_reuse(target_records)
    portfolio_objective = PortfolioObjective(
        objectives,
        failure_penalty=max(config.feature_fail_penalty for config in configs.values()),
    )
    inverter = TPEInverter(
        config=next(iter(configs.values())),
        specs=free_specs,
        seed=job["seed"],
    )
    result = inverter.run_objective(
        portfolio_objective,
        n_trials=job["trials"],
    )
    metrics = recovery_metrics(
        truth=job["truth_params"],
        estimate=result.best_params,
        specs=free_specs,
    )
    return {
        **job,
        "success": result.success,
        "best_value": result.best_value,
        "best_params": result.best_params,
        "parameter_metrics": metrics,
        "condition_best_losses": portfolio_objective.best_condition_losses,
        "target_records": target_records,
        "n_trials": result.n_trials,
        "n_forward": result.n_forward,
        "n_ode_fail": result.n_ode_fail,
        "n_feature_fail": result.n_feature_fail,
        "n_tafel_fail": result.n_tafel_fail,
        "runtime_seconds": time.perf_counter() - started,
        "configuration": {
            "feature_mode": spec.feature_mode,
            "fit_harmonics": list(spec.fit_harmonics),
            "feature_grid_size": spec.feature_grid_size,
            "solver_backend": job["backend"],
            "conditions": {
                condition_id: {
                    "n_points": config.n_points,
                    "points_per_cycle": config.points_per_cycle,
                    "f": config.f,
                    "dE": config.dE,
                }
                for condition_id, config in configs.items()
            },
        },
    }


def _is_workflow_untracked_path(path: str) -> bool:
    return path in WORKFLOW_UNTRACKED_PATHS or path.startswith(
        WORKFLOW_UNTRACKED_PREFIXES
    )


def classify_git_status(status_porcelain_z: str) -> dict:
    """Classify NUL-delimited porcelain v1 without hiding source changes."""
    dirty_paths = []
    ignored_workflow_paths = []
    fields = status_porcelain_z.split("\0")
    index = 0
    while index < len(fields):
        entry = fields[index]
        index += 1
        if not entry:
            continue
        if len(entry) < 4 or entry[2] != " ":
            raise ValueError(f"malformed git status entry: {entry!r}")
        status = entry[:2]
        path = entry[3:]
        if "R" in status or "C" in status:
            if index >= len(fields) or not fields[index]:
                raise ValueError(f"missing source path for git status: {entry!r}")
            old_path = fields[index]
            index += 1
            dirty_paths.append(f"{old_path} -> {path}")
        elif status == "??" and _is_workflow_untracked_path(path):
            ignored_workflow_paths.append(path)
        else:
            dirty_paths.append(path)
    return {
        "dirty": bool(dirty_paths),
        "dirty_paths": dirty_paths,
        "ignored_workflow_paths": ignored_workflow_paths,
    }


def git_state_full() -> dict:
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        check=True,
        text=True,
        capture_output=True,
    ).stdout.strip()
    status = subprocess.run(
        ["git", "status", "--porcelain=v1", "-z"],
        cwd=ROOT,
        check=True,
        text=True,
        capture_output=True,
    ).stdout
    classified = classify_git_status(status)
    return {
        "source_commit": commit,
        **classified,
    }


def git_state() -> tuple[str, bool]:
    """Return the legacy provenance tuple for existing callers."""
    provenance = git_state_full()
    return (
        provenance["source_commit"],
        provenance["dirty"],
    )


def validate_noise_evidence(noise_fraction: float, path: Path | None) -> dict:
    if path is None or not path.is_file():
        raise ValueError("formal recovery requires an existing --noise-evidence JSON")
    resolved = path.resolve()
    raw = resolved.read_bytes()
    try:
        evidence = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"noise evidence is not valid JSON: {resolved}") from exc
    selected = float(evidence["selected_noise_fraction"])
    if not abs(selected - noise_fraction) <= 1e-12:
        raise ValueError(
            "noise fraction does not match evidence: "
            f"requested={noise_fraction:g}, evidence={selected:g}"
        )
    enriched = dict(evidence)
    enriched["resolved_path"] = str(resolved)
    enriched["sha256"] = hashlib.sha256(raw).hexdigest()
    return enriched


def iter_job_results(jobs: list[dict], *, workers: int, smoke: bool):
    if not jobs:
        return
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


def build_summary(
    *,
    args: argparse.Namespace,
    jobs: list[dict],
    rows: list[dict],
    provenance: dict,
    duration_seconds: float,
    resumed: bool,
    reused_jobs: int,
    executed_jobs: int,
) -> dict:
    execution_passed = len(rows) == len(jobs) and all(
        row["success"] for row in rows
    )
    portfolio_mode = args.pre_experiment_spec is not None
    summary = {
        "backend": args.backend,
        "feature_modes": (
            ["hybrid"]
            if portfolio_mode
            else list(select_feature_modes(args.feature_modes))
        ),
        "phase": args.phase,
        "portfolio_stage": args.portfolio_stage,
        "execution_passed": execution_passed,
        "scientific_gate_passed": None,
        "passed": execution_passed,
        "passed_semantics": "deprecated alias of execution_passed",
        "job_count": len(jobs),
        "completed_jobs": len(rows),
        "workers": min(args.workers, len(jobs)),
        "duration_seconds": duration_seconds,
        "n_ode_fail": sum(row["n_ode_fail"] for row in rows),
        "n_tafel_fail": sum(row["n_tafel_fail"] for row in rows),
        "source_commit": provenance["source_commit"],
        "dirty": provenance["dirty"],
        "provenance": provenance,
        "resumed": resumed,
        "reused_jobs": reused_jobs,
        "executed_jobs": executed_jobs,
        "recovery_summary": (
            {"group_count": 0, "groups": [], "scope": "structure_only"}
            if portfolio_mode and args.portfolio_stage == "S0"
            else summarize_recovery(
                rows,
                parameter_names=tuple(jobs[0]["free_parameters"])
                if jobs else (),
            )
        ),
    }
    if args.phase == "pilot":
        summary["budget_selection"] = select_trial_budget(rows)
    return summary


def _csv_text(fieldnames: list[str], records: list[dict]) -> str:
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=fieldnames, lineterminator="\n")
    writer.writeheader()
    writer.writerows(records)
    return buffer.getvalue()


def write_portfolio_evidence(
    *,
    output: Path,
    args: argparse.Namespace,
    jobs: list[dict],
    rows: list[dict],
) -> None:
    """Write deterministic portfolio evidence outside the checkpoint stream."""
    spec_path = args.pre_experiment_spec.resolve()
    spec = load_pre_experiment_spec(spec_path)
    frozen_payload = json.loads(spec_path.read_text(encoding="utf-8"))
    atomic_write_json(
        output / "pre_experiment_recovery_spec.json",
        frozen_payload,
        prefix=".pre-experiment-spec.",
    )
    catalog_records = [
        {
            "condition_id": condition.condition_id,
            "E_start": format(condition.E_start, ".17g"),
            "E_end": format(condition.E_end, ".17g"),
            "f": format(condition.f, ".17g"),
            "dE": format(condition.dE, ".17g"),
            "cycles": condition.cycles,
            "points_per_cycle": condition.points_per_cycle,
            "n_points": condition.n_points,
        }
        for condition in spec.conditions.values()
    ]
    _atomic_write_text(
        output / "protocol_catalog.csv",
        _csv_text(
            [
                "condition_id",
                "E_start",
                "E_end",
                "f",
                "dE",
                "cycles",
                "points_per_cycle",
                "n_points",
            ],
            catalog_records,
        ),
        prefix=".protocol-catalog.",
    )
    target_records = [
        {
            **record,
            "job_id": row["job_id"],
            "portfolio_id": row["portfolio_id"],
        }
        for row in rows
        for record in row["target_records"]
    ]
    unique_targets = validate_target_reuse(target_records)
    atomic_write_json(
        output / "target_manifest.json",
        {
            "schema_version": 1,
            "target_record_count": len(target_records),
            "unique_target_count": len(unique_targets),
            "reuse_conflicts": [],
            "records": target_records,
        },
        prefix=".target-manifest.",
    )
    recovery_records = [
        {
            "job_id": row["job_id"],
            "portfolio_stage": row["portfolio_stage"],
            "parameter_pair_id": row["parameter_pair_id"],
            "portfolio_id": row["portfolio_id"],
            "truth_id": row["truth_id"],
            "optimizer_seed": row["seed"],
            "success": str(bool(row["success"])).lower(),
            "max_normalized_bound_error": format(
                float(row["parameter_metrics"]["max_normalized_bound_error"]),
                ".17g",
            ),
            "classification": (
                "STRUCTURE_ONLY"
                if args.portfolio_stage == "S0"
                else "PENDING_INDEPENDENT_VALIDATION"
            ),
        }
        for row in rows
    ]
    _atomic_write_text(
        output / "portfolio_recovery.csv",
        _csv_text(
            [
                "job_id",
                "portfolio_stage",
                "parameter_pair_id",
                "portfolio_id",
                "truth_id",
                "optimizer_seed",
                "success",
                "max_normalized_bound_error",
                "classification",
            ],
            recovery_records,
        ),
        prefix=".portfolio-recovery.",
    )


def write_run_manifest(output: Path, *, source_commit: str) -> None:
    evidence_files = sorted(
        path
        for path in output.iterdir()
        if path.is_file()
        and path.name not in {"run_manifest.json", *WORKFLOW_OWNED_FILES}
        and not path.name.startswith(".")
    )
    atomic_write_json(
        output / "run_manifest.json",
        {
            "schema_version": 1,
            "source_commit": source_commit,
            "files": [
                {
                    "path": path.name,
                    "size": path.stat().st_size,
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                }
                for path in evidence_files
            ],
        },
        prefix=".run-manifest.",
    )


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    if args.resume and args.dry_run:
        raise ValueError("--resume and --dry-run cannot be combined")
    validate_backend(args.backend)
    jobs = limit_jobs(build_jobs(args), args.max_jobs)
    smoke_run = args.smoke or args.portfolio_stage == "S0"
    provenance = git_state_full()
    noise_evidence = None
    if not smoke_run and not args.dry_run:
        if args.pre_experiment_spec is not None:
            if args.portfolio_stage == "S2":
                frozen_spec = load_pre_experiment_spec(args.pre_experiment_spec)
                noise_path = ROOT / frozen_spec.noise_evidence
                noise_evidence = validate_noise_evidence(
                    float(frozen_spec.noise_fractions["S2"]), noise_path
                )
        else:
            noise_evidence = validate_noise_evidence(
                args.noise_fraction, args.noise_evidence
            )
    output = args.output.resolve()
    prepare_output_directory(output, resume=args.resume)
    provenance_record = {
        **provenance,
        "python": platform.python_version(),
        "command": [sys.executable, *sys.argv]
        if argv is None else [sys.executable, *argv],
    }
    resume_metadata = build_resume_metadata(
        args, jobs, provenance, noise_evidence
    )
    for job in jobs:
        job["job_input_hash"] = resume_metadata["job_input_hashes"][job["job_id"]]
    plan = {
        "backend": args.backend,
        "feature_modes": (
            [jobs[0]["feature_mode"]]
            if args.pre_experiment_spec is not None and jobs
            else list(select_feature_modes(args.feature_modes))
        ),
        "phase": args.phase,
        "portfolio_stage": args.portfolio_stage,
        "noise_fraction": args.noise_fraction,
        "workers": args.workers,
        "free_parameters": jobs[0]["free_parameters"] if jobs else [],
        "smoke": smoke_run,
        "job_count": len(jobs),
        "jobs": jobs,
        "noise_evidence": noise_evidence,
        "provenance": provenance_record,
        "resume_schema_version": resume_metadata["resume_schema_version"],
        "resume_fingerprint": resume_metadata["resume_fingerprint"],
    }
    plan_path = output / "job_plan.json"
    existing_plan = None
    if args.resume and plan_path.exists():
        try:
            existing_plan = json.loads(plan_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError("job_plan.json is not valid JSON") from exc
        if not isinstance(existing_plan, dict):
            raise ValueError("job_plan.json must contain a JSON object")
        if existing_plan.get("resume_schema_version") != 2:
            raise ValueError(
                "resume schema version mismatch; legacy checkpoints cannot be mixed with backend-aware evidence"
            )
        if (
            existing_plan.get("resume_fingerprint")
            != resume_metadata["resume_fingerprint"]
        ):
            raise ValueError(
                "resume_fingerprint mismatch; refuse to mix scientific evidence"
            )
    if existing_plan is None:
        atomic_write_json(plan_path, plan, prefix=".job_plan.")
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
    results_path = output / "results.jsonl"
    expected_hashes = resume_metadata["job_input_hashes"]
    rows_by_id = (
        load_checkpoint_rows(results_path, expected_hashes)
        if args.resume
        else {}
    )
    reused_jobs = len(rows_by_id)
    executed_jobs = 0
    planned_ids = [job["job_id"] for job in jobs]
    remaining = [job for job in jobs if job["job_id"] not in rows_by_id]
    for row in iter_job_results(
        remaining, workers=args.workers, smoke=smoke_run
    ):
        job_id = row.get("job_id")
        if job_id not in expected_hashes:
            raise ValueError(f"worker returned unknown job_id: {job_id!r}")
        if job_id in rows_by_id:
            raise ValueError(f"worker returned duplicate job_id: {job_id}")
        completed_row = dict(row)
        completed_row["job_input_hash"] = expected_hashes[job_id]
        _assert_finite(completed_row, location=job_id)
        rows_by_id[job_id] = completed_row
        executed_jobs += 1
        atomic_write_checkpoint(results_path, rows_by_id, planned_ids)
    rows = [rows_by_id[job_id] for job_id in planned_ids]
    if args.pre_experiment_spec is not None:
        write_portfolio_evidence(
            output=output,
            args=args,
            jobs=jobs,
            rows=rows,
        )
    summary = build_summary(
        args=args,
        jobs=jobs,
        rows=rows,
        provenance=provenance_record,
        duration_seconds=time.perf_counter() - started,
        resumed=args.resume,
        reused_jobs=reused_jobs,
        executed_jobs=executed_jobs,
    )
    atomic_write_json(output / "summary.json", summary, prefix=".summary.")
    if args.pre_experiment_spec is not None:
        write_run_manifest(output, source_commit=provenance_record["source_commit"])
    print(output)


if __name__ == "__main__":
    main()
