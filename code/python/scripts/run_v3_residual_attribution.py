#!/usr/bin/env python3
"""Run the frozen V3 ensemble residual-attribution study."""

from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
import csv
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import time
from typing import Any, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "code" / "python"))
sys.path.insert(0, str(ROOT / "code" / "python" / "src"))

import numpy as np
from scipy.stats import spearmanr

from oer_aem.inversion import extract_features, params_from_vector
from oer_aem.physics import DynamicSolverError, OERPhysics
from oer_aem.residual_attribution import (
    select_representative_candidates,
    signed_feature_residuals,
    summarize_candidate_residuals,
    summarize_ensemble,
)
from scripts.run_conditional_reachability import (
    _attempt_rows,
    _git_provenance,
    _serialize,
    build_targets,
)


RUNNER_FILES = {
    "v3_task_spec.json",
    "selection.json",
    "residual_curves.jsonl",
    "residual_matrix.csv",
    "parameter_associations.csv",
    "stress_directions.csv",
    "attribution_evidence.csv",
    "summary.json",
    "run_manifest.json",
}
WORKFLOW_FILES = {
    "STATUS.json",
    "task_spec.snapshot.yaml",
    "._status_signal",
}


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _sha256_json(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def _sha256_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(block)
    return hasher.hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path.name} must contain a JSON object")
    return value


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    raw = path.read_text(encoding="utf-8")
    if raw and not raw.endswith("\n"):
        raise ValueError(f"{path.name} ends with an incomplete JSON line")
    rows = []
    for line_number, line in enumerate(raw.splitlines(), start=1):
        if not line:
            raise ValueError(f"{path.name} contains a blank JSON line")
        value = json.loads(line)
        if not isinstance(value, dict):
            raise ValueError(f"{path.name} line {line_number} is not an object")
        rows.append(value)
    return rows


def load_spec(path: str | Path) -> dict[str, Any]:
    """Load the frozen V3 configuration."""
    spec = _read_json(Path(path))
    if spec.get("schema_version") != 1:
        raise ValueError("unsupported V3 schema_version")
    if spec.get("analysis_id") != "v3-residual-attribution":
        raise ValueError("unexpected V3 analysis_id")
    if spec.get("solver_backend") != "lsoda":
        raise ValueError("V3 formal backend must be lsoda")
    if spec.get("feature_mode") != "hybrid":
        raise ValueError("V3 feature mode must be hybrid")
    if spec.get("datasets") != ["FT2", "FT3", "FT4", "FT8"]:
        raise ValueError("V3 datasets must be FT2, FT3, FT4 and FT8")
    if int(spec.get("ensemble_size", 0)) != 12:
        raise ValueError("V3 formal ensemble_size must be 12")
    return spec


def load_v2_inputs(
    root: str | Path,
    spec: Mapping[str, Any],
) -> dict[str, Any]:
    """Load and hash-check the frozen V2 evidence."""
    project = Path(root)
    archive = project / str(spec["v2_archive"])
    expected_hashes = dict(spec["v2_input_sha256"])
    for name, expected in expected_hashes.items():
        path = archive / name
        if not path.is_file():
            raise ValueError(f"missing V2 input: {name}")
        actual = _sha256_file(path)
        if actual != expected:
            raise ValueError(f"V2 input hash mismatch: {name}")

    v2_spec = _read_json(archive / "task_spec.json")
    parameter_names = [
        str(item[0]) for item in v2_spec["diagnostic_parameter_specs"]
    ]
    units: dict[int, list[float]] = {}
    with (archive / "parameter_library.csv").open(
        encoding="utf-8",
        newline="",
    ) as handle:
        for row in csv.DictReader(handle):
            candidate_id = int(row["candidate_id"])
            units[candidate_id] = [
                float(row[f"unit_{name}"]) for name in parameter_names
            ]
    base_rows = _read_jsonl(archive / "base_results.jsonl")
    for row in base_rows:
        candidate_id = int(row["candidate_id"])
        if candidate_id not in units:
            raise ValueError(f"missing unit coordinates for {candidate_id}")
        row["unit_params"] = list(units[candidate_id])

    return {
        "archive": archive,
        "v2_spec": v2_spec,
        "parameter_names": parameter_names,
        "parameter_units": units,
        "targets": _read_json(archive / "targets.json"),
        "base_rows": base_rows,
        "stress_rows": _read_jsonl(archive / "stress_results.jsonl"),
        "summary": _read_json(archive / "summary.json"),
        "run_manifest": _read_json(archive / "run_manifest.json"),
        "input_hashes": expected_hashes,
    }


def build_job_plan(
    inputs: Mapping[str, Any],
    spec: Mapping[str, Any],
    *,
    smoke: bool,
) -> tuple[list[dict[str, Any]], dict[str, list[dict[str, Any]]]]:
    """Build the deterministic four-dataset representative ensemble."""
    pool_size = int(spec["pool_size"])
    ensemble_size = (
        int(spec["smoke_ensemble_size"])
        if smoke
        else int(spec["ensemble_size"])
    )
    task_hash = _sha256_json(spec)
    jobs: list[dict[str, Any]] = []
    selection: dict[str, list[dict[str, Any]]] = {}
    for dataset_id in spec["datasets"]:
        dataset_rows = [
            row
            for row in inputs["base_rows"]
            if row["dataset_id"] == dataset_id
        ]
        selected = select_representative_candidates(
            dataset_rows,
            pool_size=pool_size,
            ensemble_size=max(ensemble_size, 1),
        )[:ensemble_size]
        selection[dataset_id] = [
            {
                "candidate_id": int(row["candidate_id"]),
                "score": float(row["score"]),
                "unit_params": list(row["unit_params"]),
                "selection_rank": int(row["selection_rank"]),
                "selection_min_distance": row["selection_min_distance"],
            }
            for row in selected
        ]
        for row in selected:
            payload = {
                "job_id": (
                    f"v3:{dataset_id}:{int(row['candidate_id']):06d}"
                ),
                "dataset_id": dataset_id,
                "candidate_id": int(row["candidate_id"]),
                "encoded_params": list(row["encoded_params"]),
                "physical_params": dict(row["physical_params"]),
                "unit_params": list(row["unit_params"]),
                "selection_rank": int(row["selection_rank"]),
                "selection_min_distance": row["selection_min_distance"],
                "v2_job_input_hash": str(row["job_input_hash"]),
                "v3_task_spec_hash": task_hash,
            }
            jobs.append(
                {**payload, "job_input_hash": _sha256_json(payload)}
            )
    return jobs, selection


def load_completed_jobs(
    output_dir: str | Path,
    expected_jobs: Sequence[Mapping[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Load exact completed rows for resume."""
    path = Path(output_dir) / "residual_curves.jsonl"
    if not path.exists():
        return {}
    expected = {
        str(row["job_id"]): str(row["job_input_hash"])
        for row in expected_jobs
    }
    completed: dict[str, dict[str, Any]] = {}
    for row in _read_jsonl(path):
        job_id = str(row.get("job_id", ""))
        if job_id not in expected:
            raise ValueError(f"unknown job_id in resume data: {job_id!r}")
        if job_id in completed:
            raise ValueError(f"duplicate job_id in resume data: {job_id}")
        if row.get("job_input_hash") != expected[job_id]:
            raise ValueError(f"job hash mismatch for {job_id}")
        completed[job_id] = row
    return completed


def run_one_job(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Run one representative candidate and preserve signed residual curves."""
    job = dict(payload["job"])
    config = payload["config"]
    target = payload["target"]
    harmonics = tuple(int(value) for value in payload["harmonics"])
    started = time.perf_counter()
    try:
        params = params_from_vector(
            job["encoded_params"],
            config,
            config.param_specs,
        )
        solution = OERPhysics.solve_ode_system_detailed(params)
        features = extract_features(solution.i_total, config)
        residuals = signed_feature_residuals(
            target,
            features,
            harmonics=harmonics,
        )
        candidate_summary = summarize_candidate_residuals(
            residuals,
            dataset_id=str(job["dataset_id"]),
            candidate_id=int(job["candidate_id"]),
        )
        return {
            **job,
            "success": True,
            "failure_kind": None,
            "failure_message": None,
            "solver_backend_used": solution.backend_used,
            "solver_fallback_used": bool(solution.fallback_used),
            "solver_attempts": _attempt_rows(solution.attempts),
            "steady_state_elapsed_s": solution.steady_state_elapsed_s,
            "steady_state_rhs_norm": solution.steady_state_rhs_norm,
            "steady_state_attempts": _attempt_rows(
                solution.steady_state_attempts
            ),
            "runtime_seconds": time.perf_counter() - started,
            "e_grid": np.asarray(target["e_grid"], dtype=float),
            "residuals": residuals,
            "candidate_summary": candidate_summary,
        }
    except DynamicSolverError as exc:
        failure_kind = "ODE"
        solver_attempts = _attempt_rows(exc.attempts)
        steady_state_attempts = _attempt_rows(exc.steady_state_attempts)
        steady_state_elapsed = exc.steady_state_elapsed_s
        steady_state_rhs = exc.steady_state_rhs_norm
        message = str(exc)
    except Exception as exc:  # noqa: BLE001
        failure_kind = "FEATURE_OR_CONTRACT"
        solver_attempts = []
        steady_state_attempts = []
        steady_state_elapsed = None
        steady_state_rhs = None
        message = f"{type(exc).__name__}: {exc}"
    return {
        **job,
        "success": False,
        "failure_kind": failure_kind,
        "failure_message": message,
        "solver_backend_used": None,
        "solver_fallback_used": None,
        "solver_attempts": solver_attempts,
        "steady_state_elapsed_s": steady_state_elapsed,
        "steady_state_rhs_norm": steady_state_rhs,
        "steady_state_attempts": steady_state_attempts,
        "runtime_seconds": time.perf_counter() - started,
        "e_grid": None,
        "residuals": None,
        "candidate_summary": [],
    }


def _iter_job_results(
    payloads: Sequence[Mapping[str, Any]],
    *,
    workers: int,
):
    if workers <= 1:
        for payload in payloads:
            yield run_one_job(payload)
        return
    with ProcessPoolExecutor(
        max_workers=min(int(workers), len(payloads))
    ) as executor:
        futures = {
            executor.submit(run_one_job, payload): payload["job"]["job_id"]
            for payload in payloads
        }
        for future in as_completed(futures):
            yield future.result()


def _atomic_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def _atomic_json(path: Path, value: Any) -> None:
    _atomic_text(
        path,
        json.dumps(
            _serialize(value),
            indent=2,
            ensure_ascii=False,
            allow_nan=False,
        )
        + "\n",
    )


def _atomic_jsonl(
    path: Path,
    rows_by_id: Mapping[str, Mapping[str, Any]],
    planned_ids: Sequence[str],
) -> None:
    text = "".join(
        json.dumps(
            _serialize(rows_by_id[job_id]),
            ensure_ascii=False,
            allow_nan=False,
        )
        + "\n"
        for job_id in planned_ids
        if job_id in rows_by_id
    )
    _atomic_text(path, text)


def _atomic_csv(
    path: Path,
    rows: Sequence[Mapping[str, Any]],
    fieldnames: Sequence[str],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    try:
        with os.fdopen(
            descriptor,
            "w",
            encoding="utf-8",
            newline="",
        ) as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=list(fieldnames),
                extrasaction="raise",
                lineterminator="\n",
            )
            writer.writeheader()
            writer.writerows(rows)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def _parameter_associations(
    inputs: Mapping[str, Any],
    datasets: Sequence[str],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    parameter_names = list(inputs["parameter_names"])
    for dataset_id in datasets:
        successful = [
            row
            for row in inputs["base_rows"]
            if row["dataset_id"] == dataset_id
            and row.get("success") is True
        ]
        metric_names = sorted(successful[0]["metrics"]) + ["score"]
        for parameter_index, parameter in enumerate(parameter_names):
            x = np.asarray(
                [row["unit_params"][parameter_index] for row in successful],
                dtype=float,
            )
            for metric in metric_names:
                y = np.asarray(
                    [
                        row["score"]
                        if metric == "score"
                        else row["metrics"][metric]
                        for row in successful
                    ],
                    dtype=float,
                )
                if np.ptp(x) == 0.0 or np.ptp(y) == 0.0:
                    rho, pvalue = 0.0, 1.0
                else:
                    rho, pvalue = spearmanr(x, y)
                rows.append(
                    {
                        "dataset_id": dataset_id,
                        "parameter": parameter,
                        "metric": metric,
                        "n": len(successful),
                        "spearman_rho": (
                            float(rho) if np.isfinite(rho) else 0.0
                        ),
                        "pvalue": (
                            float(pvalue) if np.isfinite(pvalue) else 1.0
                        ),
                        "interpretation": "association_not_causation",
                    }
                )
    return rows


def _stress_directions(
    inputs: Mapping[str, Any],
    datasets: Sequence[str],
) -> list[dict[str, Any]]:
    base_index = {
        (str(row["dataset_id"]), int(row["candidate_id"])): row
        for row in inputs["base_rows"]
        if row.get("success") is True
    }
    grouped: dict[
        tuple[str, str, str, str],
        list[float],
    ] = {}
    for row in inputs["stress_rows"]:
        if row.get("success") is not True:
            continue
        dataset_id = str(row["dataset_id"])
        if dataset_id not in datasets:
            continue
        anchor = base_index.get(
            (dataset_id, int(row["candidate_id"]))
        )
        if anchor is None:
            raise ValueError("stress row has no successful base anchor")
        metrics = sorted(row["metrics"])
        for metric in metrics + ["score"]:
            stressed = (
                float(row["score"])
                if metric == "score"
                else float(row["metrics"][metric])
            )
            baseline = (
                float(anchor["score"])
                if metric == "score"
                else float(anchor["metrics"][metric])
            )
            key = (
                dataset_id,
                str(row["stress_scenario_id"]),
                str(row["stress_parameter"]),
                metric,
            )
            grouped.setdefault(key, []).append(stressed - baseline)

    output = []
    for (dataset_id, scenario, parameter, metric), deltas in sorted(
        grouped.items()
    ):
        values = np.asarray(deltas, dtype=float)
        positive = int(np.count_nonzero(values > 0.0))
        negative = int(np.count_nonzero(values < 0.0))
        stable = max(positive, negative) >= 6
        output.append(
            {
                "dataset_id": dataset_id,
                "scenario_id": scenario,
                "parameter": parameter,
                "metric": metric,
                "n_anchors": len(values),
                "median_delta": float(np.median(values)),
                "positive_count": positive,
                "negative_count": negative,
                "direction_stable": stable,
                "effect": (
                    "lower_error"
                    if stable and float(np.median(values)) < 0.0
                    else "higher_error"
                    if stable and float(np.median(values)) > 0.0
                    else "unstable"
                ),
            }
        )
    return output


def _attribution_evidence(
    matrix_rows: Sequence[Mapping[str, Any]],
    stress_rows: Sequence[Mapping[str, Any]],
    datasets: Sequence[str],
) -> list[dict[str, Any]]:
    output = []
    for dataset_id in datasets:
        dataset_matrix = [
            row for row in matrix_rows if row["dataset_id"] == dataset_id
        ]
        consistent = [
            row
            for row in dataset_matrix
            if row["direction_class"] == "ensemble sign-consistent"
        ]
        dependent = [
            row
            for row in dataset_matrix
            if row["direction_class"] == "candidate-dependent"
        ]
        low_dc = [
            row
            for row in consistent
            if row["channel"] == "dc" and row["segment"] == "low"
        ]
        lowering = [
            row
            for row in stress_rows
            if row["dataset_id"] == dataset_id
            and row["metric"] == "score"
            and row["effect"] == "lower_error"
        ]
        records = [
            (
                "model_item",
                (
                    f"{len(consistent)} channel-segments retain one residual "
                    "direction across at least 9/12 candidates"
                ),
                "fixed-input compensation or unresolved experimental processing",
                "alternative physical model not yet compared",
                "conditional",
            ),
            (
                "background_item",
                (
                    "low-potential DC residual is ensemble-consistent"
                    if low_dc
                    else "low-potential DC residual is candidate-dependent"
                ),
                "kinetic onset or current normalization",
                "background and preprocessing records deferred",
                "diagnostic",
            ),
            (
                "metadata_item",
                "experimental preprocessing and independent constraints deferred",
                "none evaluated in V3",
                "requires restored experimental records",
                "deferred",
            ),
            (
                "parameter_compensation",
                (
                    f"{len(lowering)} stable fixed-parameter directions lower "
                    "the aggregate score"
                ),
                "correlated parameters may produce the same direction",
                "stress rows are local paired diagnostics",
                "conditional",
            ),
            (
                "unexplained",
                (
                    f"{len(dependent)} channel-segments remain "
                    "candidate-dependent"
                ),
                "denser sampling or a different model may change the pattern",
                "no causal assignment from residuals alone",
                "unresolved",
            ),
        ]
        for category, finding, alternative, condition, level in records:
            output.append(
                {
                    "dataset_id": dataset_id,
                    "category": category,
                    "finding": finding,
                    "supporting_evidence": (
                        "V2 scalar rows plus V3 12-candidate ensemble"
                    ),
                    "alternative_explanation": alternative,
                    "unverified_condition": condition,
                    "evidence_level": level,
                }
            )
    return output


def _prepare_output(output: Path, *, resume: bool) -> None:
    output.mkdir(parents=True, exist_ok=True)
    unknown = sorted(
        path.name
        for path in output.iterdir()
        if path.name not in RUNNER_FILES | WORKFLOW_FILES
    )
    if unknown:
        raise ValueError(f"unknown output files: {', '.join(unknown)}")
    scientific = [
        path.name for path in output.iterdir() if path.name in RUNNER_FILES
    ]
    if scientific and not resume:
        raise ValueError("scientific output exists; use --resume")


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task-spec", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--smoke", action="store_true")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """Execute or resume the frozen V3 job plan."""
    args = _parse_args(argv)
    if args.workers < 1:
        raise ValueError("workers must be positive")
    spec = load_spec(args.task_spec)
    inputs = load_v2_inputs(ROOT, spec)
    jobs, selection = build_job_plan(inputs, spec, smoke=args.smoke)
    _prepare_output(args.output, resume=args.resume)
    provenance = _git_provenance()
    if not args.smoke:
        if provenance["dirty"]:
            raise ValueError("formal V3 requires a clean worktree")

    started = time.perf_counter()
    run_spec = {
        **spec,
        "run_mode": "smoke" if args.smoke else "formal",
        "source_state": provenance,
    }
    _atomic_json(
        args.output / "v3_task_spec.json",
        run_spec,
    )
    _atomic_json(args.output / "selection.json", selection)

    targets, configs, _ = build_targets(inputs["v2_spec"])
    completed = load_completed_jobs(args.output, jobs)
    reused_jobs = len(completed)
    payloads = [
        {
            "job": job,
            "config": configs[str(job["dataset_id"])],
            "target": targets[str(job["dataset_id"])],
            "harmonics": spec["fit_harmonics"],
        }
        for job in jobs
        if job["job_id"] not in completed
    ]
    planned_ids = [str(job["job_id"]) for job in jobs]
    executed_jobs = 0
    for row in _iter_job_results(payloads, workers=args.workers):
        job_id = str(row["job_id"])
        if job_id in completed or job_id not in planned_ids:
            raise ValueError(f"worker returned invalid job_id: {job_id}")
        completed[job_id] = row
        executed_jobs += 1
        _atomic_jsonl(
            args.output / "residual_curves.jsonl",
            completed,
            planned_ids,
        )

    ordered = [completed[job_id] for job_id in planned_ids]
    failed = [row for row in ordered if row.get("success") is not True]
    matrix_rows: list[dict[str, Any]] = []
    associations: list[dict[str, Any]] = []
    stress_directions: list[dict[str, Any]] = []
    evidence: list[dict[str, Any]] = []
    if not failed:
        candidate_rows = [
            summary
            for row in ordered
            for summary in row["candidate_summary"]
        ]
        ensemble_size = (
            int(spec["smoke_ensemble_size"])
            if args.smoke
            else int(spec["ensemble_size"])
        )
        for dataset_id in spec["datasets"]:
            nearest_id = int(selection[dataset_id][0]["candidate_id"])
            matrix_rows.extend(
                summarize_ensemble(
                    [
                        row
                        for row in candidate_rows
                        if row["dataset_id"] == dataset_id
                    ],
                    nearest_candidate_id=nearest_id,
                    ensemble_size=ensemble_size,
                )
            )
        associations = _parameter_associations(inputs, spec["datasets"])
        stress_directions = _stress_directions(inputs, spec["datasets"])
        evidence = _attribution_evidence(
            matrix_rows,
            stress_directions,
            spec["datasets"],
        )
        _atomic_csv(
            args.output / "residual_matrix.csv",
            matrix_rows,
            [
                "dataset_id",
                "channel",
                "segment",
                "ensemble_size",
                "valid_candidate_count",
                "signed_mean_median",
                "signed_mean_q25",
                "signed_mean_q75",
                "positive_count",
                "negative_count",
                "direction_class",
                "nearest_candidate_id",
                "nearest_signed_mean",
                "nearest_within_iqr",
            ],
        )
        _atomic_csv(
            args.output / "parameter_associations.csv",
            associations,
            [
                "dataset_id",
                "parameter",
                "metric",
                "n",
                "spearman_rho",
                "pvalue",
                "interpretation",
            ],
        )
        _atomic_csv(
            args.output / "stress_directions.csv",
            stress_directions,
            [
                "dataset_id",
                "scenario_id",
                "parameter",
                "metric",
                "n_anchors",
                "median_delta",
                "positive_count",
                "negative_count",
                "direction_stable",
                "effect",
            ],
        )
        _atomic_csv(
            args.output / "attribution_evidence.csv",
            evidence,
            [
                "dataset_id",
                "category",
                "finding",
                "supporting_evidence",
                "alternative_explanation",
                "unverified_condition",
                "evidence_level",
            ],
        )

    dataset_summary = {}
    for dataset_id in spec["datasets"]:
        dataset_jobs = [
            row for row in ordered if row["dataset_id"] == dataset_id
        ]
        dataset_matrix = [
            row for row in matrix_rows if row["dataset_id"] == dataset_id
        ]
        dataset_summary[dataset_id] = {
            "job_count": len(dataset_jobs),
            "success_count": sum(
                row.get("success") is True for row in dataset_jobs
            ),
            "candidate_ids": [
                int(row["candidate_id"]) for row in dataset_jobs
            ],
            "fallback_count": sum(
                row.get("solver_fallback_used") is True
                for row in dataset_jobs
            ),
            "sign_consistent_channel_segments": sum(
                row["direction_class"] == "ensemble sign-consistent"
                for row in dataset_matrix
            ),
            "candidate_dependent_channel_segments": sum(
                row["direction_class"] == "candidate-dependent"
                for row in dataset_matrix
            ),
        }
    summary = {
        "schema_version": 1,
        "analysis_id": spec["analysis_id"],
        "run_mode": run_spec["run_mode"],
        "structure_complete": not failed,
        "scientific_parameter_estimation_enabled": False,
        "datasets": dataset_summary,
        "job_count": len(jobs),
        "success_count": len(jobs) - len(failed),
        "failed_job_ids": [str(row["job_id"]) for row in failed],
        "workers": int(args.workers),
        "duration_seconds": time.perf_counter() - started,
        "reused_jobs": reused_jobs,
        "executed_jobs": executed_jobs,
    }
    _atomic_json(args.output / "summary.json", summary)

    artifact_names = sorted(
        name
        for name in RUNNER_FILES
        if name != "run_manifest.json"
        and (args.output / name).is_file()
    )
    manifest = {
        "schema_version": 1,
        "analysis_id": spec["analysis_id"],
        "run_mode": run_spec["run_mode"],
        "v3_task_spec_hash": _sha256_json(spec),
        "v2_input_sha256": dict(inputs["input_hashes"]),
        "provenance": provenance,
        "job_count": len(jobs),
        "artifact_sha256": {
            name: _sha256_file(args.output / name)
            for name in artifact_names
        },
    }
    _atomic_json(args.output / "run_manifest.json", manifest)
    return 0 if not failed else 2


if __name__ == "__main__":
    raise SystemExit(main())
