#!/usr/bin/env python3
"""Independently validate a V4 experiment-design archive."""

from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
import subprocess
import sys
from typing import Any, Mapping, Sequence

import numpy as np


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "code" / "python"))
sys.path.insert(0, str(ROOT / "code" / "python" / "src"))

from scripts.run_v4_experiment_design import (
    RUNNER_FILES,
    _canonical_json,
    _linearity_evidence,
    _read_json,
    _read_jsonl,
    _sha256_file,
    _sha256_json,
    build_condition_catalog,
    build_linearity_jobs,
    build_primary_jobs,
    build_recommendation,
    build_sensitivity_evidence,
    linearity_preserves_recommendation_order,
    load_inputs,
    load_spec,
    run_one_forward,
)


class NumericalValidationError(ValueError):
    """A structurally valid archive contains failed or non-finite science."""


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _assert_close(actual: Any, expected: Any, name: str) -> None:
    if expected is None:
        if actual not in (None, ""):
            raise ValueError(f"{name} mismatch")
    elif isinstance(expected, bool):
        normalized = actual
        if isinstance(actual, str):
            normalized = actual.lower() == "true"
        if normalized is not expected:
            raise ValueError(f"{name} mismatch")
    elif isinstance(expected, (int, float)) and not isinstance(expected, bool):
        value = float(actual)
        if not math.isfinite(value) or not math.isclose(
            value,
            float(expected),
            rel_tol=1e-12,
            abs_tol=1e-12,
        ):
            raise ValueError(f"{name} mismatch")
    elif str(actual) != str(expected):
        raise ValueError(f"{name} mismatch")


def _compare_csv_rows(
    actual: Sequence[Mapping[str, Any]],
    expected: Sequence[Mapping[str, Any]],
    *,
    fieldnames: Sequence[str],
    label: str,
) -> None:
    if len(actual) != len(expected):
        raise ValueError(f"{label} row count mismatch")
    for index, (left, right) in enumerate(zip(actual, expected, strict=True)):
        if set(left) != set(fieldnames):
            raise ValueError(f"{label} schema mismatch")
        for name in fieldnames:
            _assert_close(
                left.get(name),
                right.get(name),
                f"{label}[{index}].{name}",
            )


def _validate_forward_row(
    row: Mapping[str, Any],
    job: Mapping[str, Any],
) -> None:
    if row.get("job_id") != job["job_id"]:
        raise ValueError("forward job order or membership mismatch")
    if row.get("job_input_hash") != job["job_input_hash"]:
        raise ValueError(f"forward job hash mismatch: {job['job_id']}")
    if row.get("success") is not True:
        raise NumericalValidationError(
            f"forward job failed: {job['job_id']}"
        )
    if row.get("solver_backend_used") not in {"LSODA", "BDF"}:
        raise NumericalValidationError(
            f"invalid solver backend: {job['job_id']}"
        )
    names = [str(value) for value in row.get("feature_names", [])]
    values = row.get("feature_values", [])
    observable = row.get("observable", [])
    if (
        len(names) != 27
        or len(set(names)) != 27
        or len(values) != 27
        or len(observable) != 27
    ):
        raise ValueError(f"invalid feature contract: {job['job_id']}")
    for value, is_observable in zip(values, observable, strict=True):
        if not isinstance(is_observable, bool):
            raise ValueError(f"invalid observable mask: {job['job_id']}")
        if is_observable:
            if value is None or not math.isfinite(float(value)):
                raise NumericalValidationError(
                    f"non-finite observable feature: {job['job_id']}"
                )
        elif value is not None:
            raise ValueError(
                f"unobservable feature must be null: {job['job_id']}"
            )


def _expected_gain_rows(
    recommendation: Mapping[str, Any],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for stage in recommendation["stages"]:
        rows.extend(
            {"stage": int(stage["stage"]), **dict(row)}
            for row in stage["ranking"]
        )
    return rows


def _validate_manifest(
    archive: Path,
    manifest: Mapping[str, Any],
    *,
    spec: Mapping[str, Any],
    frozen: Mapping[str, Any],
    inputs: Mapping[str, Any],
    primary_count: int,
    linearity_count: int,
    success_count: int,
) -> None:
    if manifest.get("schema_version") != 1:
        raise ValueError("manifest schema mismatch")
    if manifest.get("analysis_id") != spec["analysis_id"]:
        raise ValueError("manifest analysis mismatch")
    if manifest.get("run_mode") != frozen["run_mode"]:
        raise ValueError("manifest run mode mismatch")
    if manifest.get("task_spec_hash") != _sha256_json(spec):
        raise ValueError("manifest task spec hash mismatch")
    if manifest.get("source_state") != frozen["source_state"]:
        raise ValueError("manifest source state mismatch")
    if manifest.get("input_hashes") != inputs["input_hashes"]:
        raise ValueError("manifest input hashes mismatch")
    expected_counts = {
        "primary_job_count": primary_count,
        "linearity_job_count": linearity_count,
        "job_count": primary_count + linearity_count,
        "success_count": success_count,
    }
    for name, expected in expected_counts.items():
        if int(manifest.get(name, -1)) != expected:
            raise ValueError(f"manifest {name} mismatch")
    expected_names = RUNNER_FILES - {"run_manifest.json"}
    hashes = manifest.get("artifact_sha256")
    if not isinstance(hashes, dict) or set(hashes) != expected_names:
        raise ValueError("manifest artifact set mismatch")
    for name in sorted(expected_names):
        if hashes[name] != _sha256_file(archive / name):
            raise ValueError(f"artifact hash mismatch: {name}")


def _rerun_selected(
    spec: Mapping[str, Any],
    inputs: Mapping[str, Any],
    jobs: Sequence[Mapping[str, Any]],
    archived_rows: Sequence[Mapping[str, Any]],
    selected: Sequence[str],
) -> list[dict[str, Any]]:
    if len(selected) != 2:
        raise NumericalValidationError(
            "formal selected rerun requires two recommended protocols"
        )
    archived = {str(row["job_id"]): row for row in archived_rows}
    selected_ids = {str(value) for value in selected}
    rerun_jobs = [
        job
        for job in jobs
        if int(job["selection_rank"]) == 0
        and job["condition_id"] in selected_ids
        and job["perturbation_direction"] == "baseline"
    ]
    if len(rerun_jobs) != 8:
        raise ValueError("formal selected rerun must contain eight baselines")
    evidence: list[dict[str, Any]] = []
    for job in rerun_jobs:
        result = run_one_forward(
            {
                "job": job,
                "spec": spec,
                "parameter_specs": inputs["parameter_specs"],
                "fixed_baseline": inputs["fixed_baseline"],
            }
        )
        if result.get("success") is not True:
            raise NumericalValidationError(
                f"selected rerun failed: {job['job_id']}"
            )
        original = archived[str(job["job_id"])]
        if (
            result["feature_names"] != original["feature_names"]
            or result["observable"] != original["observable"]
        ):
            raise NumericalValidationError(
                f"selected rerun feature contract mismatch: {job['job_id']}"
            )
        observable = np.asarray(result["observable"], dtype=bool)
        rerun_values = np.asarray(
            [0.0 if value is None else value for value in result["feature_values"]],
            dtype=float,
        )
        archived_values = np.asarray(
            [0.0 if value is None else value for value in original["feature_values"]],
            dtype=float,
        )
        if not np.allclose(
            rerun_values[observable],
            archived_values[observable],
            rtol=1e-8,
            atol=1e-10,
        ):
            raise NumericalValidationError(
                f"selected rerun value mismatch: {job['job_id']}"
            )
        evidence.append(
            {
                "job_id": str(job["job_id"]),
                "dataset_id": str(job["dataset_id"]),
                "condition_id": str(job["condition_id"]),
                "solver_backend_used": str(result["solver_backend_used"]),
            }
        )
    return evidence


def _selected_rerun_required(
    recommendation_status: str,
    selected: Sequence[str],
) -> bool:
    """Require reruns only when the frozen ranking produced two protocols."""
    selected_count = len(selected)
    if recommendation_status in {
        "RECOMMEND_TWO",
        "LOCAL_LINEARITY_UNSTABLE",
    }:
        if selected_count != 2:
            raise ValueError(
                "two-protocol recommendation must contain two selections"
            )
        return True
    if recommendation_status == "NO_ROBUST_RECOMMENDATION":
        if selected_count != 0:
            raise ValueError(
                "no-recommendation status must not contain selections"
            )
        return False
    raise NumericalValidationError(
        f"cannot rerun selected protocols for status: {recommendation_status}"
    )


def validate_archive(
    root: str | Path,
    spec_path: str | Path,
    archive: str | Path,
    *,
    rerun_selected: bool = False,
) -> dict[str, Any]:
    """Rebuild V4 jobs, matrices, ranking, linearity and provenance read-only."""
    root = Path(root).resolve()
    archive = Path(archive).resolve()
    errors: list[str] = []
    rerun_evidence: list[dict[str, Any]] = []
    run_mode: str | None = None
    primary_count = 0
    linearity_count = 0
    matrix_count = 0
    recommendation_status: str | None = None
    try:
        missing = sorted(
            name for name in RUNNER_FILES if not (archive / name).is_file()
        )
        if missing:
            raise ValueError(f"missing files: {', '.join(missing)}")
        spec = load_spec(spec_path)
        frozen = _read_json(archive / "v4_task_spec.json")
        for name, value in spec.items():
            if frozen.get(name) != value:
                raise ValueError(f"frozen V4 spec mismatch at {name}")
        run_mode = str(frozen.get("run_mode"))
        if run_mode not in {"smoke", "formal"}:
            raise ValueError("invalid V4 run mode")
        if run_mode == "formal":
            if frozen["source_state"].get("dirty") is not False:
                raise ValueError("formal V4 source state is dirty")
            commit = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=root,
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
            if commit != frozen["source_state"].get("source_commit"):
                raise ValueError("validator commit does not match V4 archive")

        inputs = load_inputs(root, spec)
        conditions = build_condition_catalog(spec, smoke=run_mode == "smoke")
        points = list(inputs["parameter_points"])
        if run_mode == "smoke":
            points = [
                row
                for row in points
                if row["dataset_id"] == spec["smoke"]["dataset_id"]
                and int(row["selection_rank"])
                == int(spec["smoke"]["selection_rank"])
            ]
        task_hash = _sha256_json(spec)
        primary_jobs = build_primary_jobs(
            points,
            conditions,
            parameter_specs=inputs["parameter_specs"],
            perturbations=spec["perturbations"],
            task_spec_hash=task_hash,
        )
        primary_count = len(primary_jobs)
        expected_primary = 22 if run_mode == "smoke" else 792
        if primary_count != expected_primary:
            raise ValueError("primary job count mismatch")

        catalog_fields = (
            "condition_id",
            "condition_role",
            "E_start",
            "E_end",
            "frequency_hz",
            "amplitude_v",
            "cycles",
            "points_per_cycle",
            "n_points",
            "duration_s",
            "scan_rate_v_s",
        )
        _compare_csv_rows(
            _read_csv(archive / "condition_catalog.csv"),
            conditions,
            fieldnames=catalog_fields,
            label="condition catalog",
        )

        forward_rows = _read_jsonl(archive / "forward_results.jsonl")
        plan = _read_json(archive / "job_plan.json")
        if plan.get("task_spec_hash") != task_hash:
            raise ValueError("job plan task hash mismatch")
        archived_jobs = plan.get("jobs")
        if not isinstance(archived_jobs, list):
            raise ValueError("job plan jobs must be a list")
        if archived_jobs[:primary_count] != primary_jobs:
            raise ValueError("primary job plan mismatch")
        if len(forward_rows) != len(archived_jobs):
            raise ValueError("forward result count mismatch")
        for row, job in zip(forward_rows, archived_jobs, strict=True):
            _validate_forward_row(row, job)

        primary_rows = forward_rows[:primary_count]
        sensitivity = build_sensitivity_evidence(
            primary_rows,
            parameter_specs=inputs["parameter_specs"],
            ridge=float(spec["ridge"]),
        )
        matrix_count = len(sensitivity)
        expected_matrices = 2 if run_mode == "smoke" else 72
        if matrix_count != expected_matrices:
            raise ValueError("sensitivity matrix count mismatch")
        if any(row.get("success") is not True for row in sensitivity):
            raise NumericalValidationError("sensitivity reconstruction failed")
        archived_sensitivity = _read_jsonl(
            archive / "sensitivity_matrices.jsonl"
        )
        if _canonical_json(archived_sensitivity) != _canonical_json(sensitivity):
            raise ValueError("sensitivity matrix reconstruction mismatch")

        recommendation = build_recommendation(
            sensitivity,
            conditions,
            ridge=float(spec["ridge"]),
            minimum_positive=int(spec["minimum_positive_points"]),
        )
        linearity_jobs: list[dict[str, Any]] = []
        linearity_rows: list[dict[str, Any]] = []
        if (
            run_mode == "formal"
            and recommendation["status"] == "RECOMMEND_TWO"
        ):
            selected_conditions = [
                row
                for row in conditions
                if row["condition_id"] in recommendation["selected"]
            ]
            rank_zero = [
                row for row in points if int(row["selection_rank"]) == 0
            ]
            linearity_jobs = build_linearity_jobs(
                rank_zero,
                selected_conditions,
                parameter_specs=inputs["parameter_specs"],
                perturbations=spec["perturbations"],
                task_spec_hash=task_hash,
            )
            baseline_rows = [
                row
                for row in primary_rows
                if int(row["selection_rank"]) == 0
                and row["condition_id"] in recommendation["selected"]
                and row["perturbation_direction"] == "baseline"
            ]
            half_rows = forward_rows[primary_count:]
            half_sensitivity = build_sensitivity_evidence(
                [*baseline_rows, *half_rows],
                parameter_specs=inputs["parameter_specs"],
                ridge=float(spec["ridge"]),
            )
            if any(row.get("success") is not True for row in half_sensitivity):
                raise NumericalValidationError(
                    "half-step sensitivity reconstruction failed"
                )
            linearity_rows = _linearity_evidence(
                sensitivity,
                half_sensitivity,
                threshold=float(spec["linearity_cosine_min"]),
            )
            order_preserved = linearity_preserves_recommendation_order(
                sensitivity,
                half_sensitivity,
                conditions,
                selected=recommendation["selected"],
                ridge=float(spec["ridge"]),
            )
            recommendation["linearity_order_preserved"] = order_preserved
            if (
                not all(row["stable"] for row in linearity_rows)
                or not order_preserved
            ):
                recommendation["status"] = "LOCAL_LINEARITY_UNSTABLE"

        linearity_count = len(linearity_jobs)
        expected_jobs = [*primary_jobs, *linearity_jobs]
        if archived_jobs != expected_jobs:
            raise ValueError("complete job plan mismatch")
        if int(plan.get("primary_job_count", -1)) != primary_count:
            raise ValueError("job plan primary count mismatch")
        if int(plan.get("linearity_job_count", -1)) != linearity_count:
            raise ValueError("job plan linearity count mismatch")

        gain_fields = (
            "stage",
            "rank",
            "condition_id",
            "eligible",
            "all_success",
            "parameter_point_count",
            "successful_point_count",
            "q25_logdet_gain",
            "median_correlation_reduction",
            "q25_min_singular_gain",
            "positive_gain_count",
            "total_points",
        )
        _compare_csv_rows(
            _read_csv(archive / "portfolio_gain.csv"),
            _expected_gain_rows(recommendation),
            fieldnames=gain_fields,
            label="portfolio gain",
        )
        linearity_fields = (
            "dataset_id",
            "candidate_id",
            "condition_id",
            "parameter",
            "direction_cosine",
            "stable",
        )
        _compare_csv_rows(
            _read_csv(archive / "linearity_check.csv"),
            linearity_rows,
            fieldnames=linearity_fields,
            label="linearity check",
        )

        archived_recommendation = _read_json(
            archive / "recommendation.json"
        )
        expected_recommendation = {
            **recommendation,
            "analysis_id": spec["analysis_id"],
            "run_mode": run_mode,
            "job_count": len(expected_jobs),
            "successful_job_count": len(forward_rows),
            "deferred_experimental_inputs": list(
                spec["deferred_experimental_inputs"]
            ),
        }
        duration = archived_recommendation.get("duration_seconds")
        if duration is None or not math.isfinite(float(duration)):
            raise ValueError("recommendation duration is invalid")
        actual_core = {
            key: value
            for key, value in archived_recommendation.items()
            if key != "duration_seconds"
        }
        if _canonical_json(actual_core) != _canonical_json(
            expected_recommendation
        ):
            raise ValueError("recommendation reconstruction mismatch")
        recommendation_status = str(archived_recommendation["status"])

        manifest = _read_json(archive / "run_manifest.json")
        _validate_manifest(
            archive,
            manifest,
            spec=spec,
            frozen=frozen,
            inputs=inputs,
            primary_count=primary_count,
            linearity_count=linearity_count,
            success_count=len(forward_rows),
        )
        if rerun_selected:
            if run_mode != "formal":
                raise ValueError("selected rerun is formal-only")
            if _selected_rerun_required(
                recommendation["status"],
                recommendation["selected"],
            ):
                rerun_evidence = _rerun_selected(
                    spec,
                    inputs,
                    primary_jobs,
                    primary_rows,
                    recommendation["selected"],
                )
    except NumericalValidationError as exc:
        errors.append(str(exc))
        gate = "FAIL_NUMERICAL"
    except Exception as exc:
        errors.append(f"{type(exc).__name__}: {exc}")
        gate = "FAIL_STRUCTURE"
    else:
        gate = "PASS"
    return {
        "gate": gate,
        "run_mode": run_mode,
        "primary_job_count": primary_count,
        "linearity_job_count": linearity_count,
        "sensitivity_matrix_count": matrix_count,
        "recommendation_status": recommendation_status,
        "rerun_evidence": rerun_evidence,
        "errors": errors,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--task-spec", type=Path, required=True)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--rerun-selected", action="store_true")
    parser.add_argument("--acceptance-output", type=Path)
    args = parser.parse_args(argv)
    result = validate_archive(
        args.root,
        args.task_spec,
        args.archive,
        rerun_selected=args.rerun_selected,
    )
    content = json.dumps(result, indent=2, allow_nan=False) + "\n"
    if args.acceptance_output is not None:
        args.acceptance_output.parent.mkdir(parents=True, exist_ok=True)
        args.acceptance_output.write_text(content, encoding="utf-8")
    print(content, end="")
    return 0 if result["gate"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
