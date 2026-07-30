#!/usr/bin/env python3
"""Run the frozen V4 model-conditional experiment-design study."""

from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
import csv
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import time
from typing import Any, Mapping, Sequence

import numpy as np


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "code" / "python"))
sys.path.insert(0, str(ROOT / "code" / "python" / "src"))

from oer_aem.experiment_design import (
    block_feature_vector,
    central_sensitivity,
    column_direction_cosines,
    matrix_metrics,
    rank_candidate_conditions,
)
from oer_aem.inversion import InversionConfig, extract_features, params_from_vector
from oer_aem.physics import DynamicSolverError, OERPhysics
from scripts.run_conditional_reachability import _attempt_rows, _git_provenance


RUNNER_FILES = {
    "v4_task_spec.json",
    "condition_catalog.csv",
    "job_plan.json",
    "forward_results.jsonl",
    "sensitivity_matrices.jsonl",
    "portfolio_gain.csv",
    "linearity_check.csv",
    "recommendation.json",
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
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(raw.splitlines(), start=1):
        if not line:
            raise ValueError(f"{path.name} contains a blank JSON line")
        value = json.loads(line)
        if not isinstance(value, dict):
            raise ValueError(
                f"{path.name} line {line_number} is not an object"
            )
        rows.append(value)
    return rows


def _atomic_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _atomic_json(path: Path, value: Any) -> None:
    _atomic_text(
        path,
        json.dumps(value, indent=2, allow_nan=False) + "\n",
    )


def _atomic_jsonl(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    _atomic_text(
        path,
        "".join(
            json.dumps(dict(row), allow_nan=False) + "\n"
            for row in rows
        ),
    )


def _atomic_csv(
    path: Path,
    rows: Sequence[Mapping[str, Any]],
    *,
    fieldnames: Sequence[str],
) -> None:
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    try:
        with os.fdopen(
            descriptor,
            "w",
            encoding="utf-8",
            newline="",
        ) as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            for row in rows:
                writer.writerow(
                    {name: row.get(name) for name in fieldnames}
                )
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def select_parameter_points(
    v3_rows: Sequence[Mapping[str, Any]],
    *,
    selection_ranks: Sequence[int] = (0, 1),
) -> list[dict[str, Any]]:
    """Select exactly two successful V3 points per dataset by frozen rank."""
    wanted = tuple(int(value) for value in selection_ranks)
    selected = [
        dict(row)
        for row in v3_rows
        if row.get("success") is True
        and int(row.get("selection_rank", -1)) in wanted
    ]
    selected.sort(
        key=lambda row: (
            str(row["dataset_id"]),
            int(row["selection_rank"]),
            int(row["candidate_id"]),
        )
    )
    datasets = ("FT2", "FT3", "FT4", "FT8")
    for dataset_id in datasets:
        rows = [
            row for row in selected if row["dataset_id"] == dataset_id
        ]
        if [int(row["selection_rank"]) for row in rows] != list(wanted):
            raise ValueError(
                f"missing V3 selection ranks for {dataset_id}: {wanted}"
            )
    if len(selected) != len(datasets) * len(wanted):
        raise ValueError("unexpected V4 parameter-point count")
    return selected


def load_spec(path: str | Path) -> dict[str, Any]:
    """Load and validate the frozen V4 configuration."""
    spec = _read_json(Path(path))
    if spec.get("schema_version") != 1:
        raise ValueError("unsupported V4 schema_version")
    if spec.get("analysis_id") != "v4-computational-experiment-design":
        raise ValueError("unexpected V4 analysis_id")
    if spec.get("solver_backend") != "lsoda":
        raise ValueError("V4 formal backend must be lsoda")
    if spec.get("feature_mode") != "hybrid":
        raise ValueError("V4 feature mode must be hybrid")
    if spec.get("datasets") != ["FT2", "FT3", "FT4", "FT8"]:
        raise ValueError("V4 datasets must be FT2, FT3, FT4 and FT8")
    if spec.get("selection_ranks") != [0, 1]:
        raise ValueError("V4 must use selection ranks 0 and 1")
    if spec.get("diagnostic_parameters") != [
        "k0_1",
        "k0_2",
        "k0_3",
        "G_OH",
        "G_O",
    ]:
        raise ValueError("unexpected V4 diagnostic parameter order")
    return spec


def load_inputs(
    root: str | Path,
    spec: Mapping[str, Any],
) -> dict[str, Any]:
    """Load hash-bound V2/V3 evidence and parameter-role constraints."""
    project = Path(root)
    v2_archive = project / str(spec["v2_archive"])
    v3_archive = project / str(spec["v3_archive"])
    for name, expected in dict(spec["v2_input_sha256"]).items():
        if _sha256_file(v2_archive / name) != expected:
            raise ValueError(f"V2 input hash mismatch: {name}")
    for name, expected in dict(spec["v3_input_sha256"]).items():
        if _sha256_file(v3_archive / name) != expected:
            raise ValueError(f"V3 input hash mismatch: {name}")
    role_path = project / str(spec["parameter_role_registry"])
    if _sha256_file(role_path) != spec["parameter_role_sha256"]:
        raise ValueError("parameter-role registry hash mismatch")

    v2_spec = _read_json(v2_archive / "task_spec.json")
    parameter_specs = [
        list(row) for row in v2_spec["diagnostic_parameter_specs"]
    ]
    if parameter_specs != [
        list(row) for row in spec["parameter_specs"]
    ]:
        raise ValueError("V2 and V4 parameter specs do not match")
    if [str(row[0]) for row in parameter_specs] != list(
        spec["diagnostic_parameters"]
    ):
        raise ValueError("V2 parameter order does not match V4")
    roles = _read_json(role_path)
    by_name = {
        str(row["name"]): row for row in roles["parameters"]
    }
    for name in spec["diagnostic_parameters"]:
        row = by_name.get(name)
        if (
            row is None
            or row.get("role") != "diagnostic_only"
            or "experimental_design" not in row.get("allowed_use", [])
        ):
            raise ValueError(f"parameter is not eligible for V4 design: {name}")

    v3_rows = _read_jsonl(v3_archive / "residual_curves.jsonl")
    points = select_parameter_points(
        v3_rows,
        selection_ranks=spec["selection_ranks"],
    )
    return {
        "v2_archive": v2_archive,
        "v3_archive": v3_archive,
        "parameter_specs": parameter_specs,
        "fixed_baseline": dict(v2_spec["fixed_baseline"]),
        "parameter_points": points,
        "input_hashes": {
            "v2": dict(spec["v2_input_sha256"]),
            "v3": dict(spec["v3_input_sha256"]),
            "parameter_roles": str(spec["parameter_role_sha256"]),
        },
    }


def build_condition_catalog(
    spec: Mapping[str, Any],
    *,
    smoke: bool,
) -> list[dict[str, Any]]:
    """Enrich frozen protocol rows with their exact numerical acquisition grid."""
    points_per_cycle = int(spec["points_per_cycle"])
    source = [
        *spec["existing_conditions"],
        *spec["candidate_conditions"],
    ]
    if smoke:
        allowed = set(spec["smoke"]["condition_ids"])
        source = [row for row in source if row["condition_id"] in allowed]
        points_per_cycle = int(spec["smoke"]["points_per_cycle"])
    result: list[dict[str, Any]] = []
    for raw in source:
        row = dict(raw)
        cycles = (
            int(spec["smoke"]["cycles"])
            if smoke
            else int(row["cycles"])
        )
        row["cycles"] = cycles
        frequency = float(row["frequency_hz"])
        if cycles <= 0 or frequency <= 0.0:
            raise ValueError("condition cycles and frequency must be positive")
        duration = cycles / frequency
        row.update(
            {
                "points_per_cycle": points_per_cycle,
                "n_points": cycles * points_per_cycle,
                "duration_s": duration,
                "scan_rate_v_s": (
                    float(row["E_end"]) - float(row["E_start"])
                )
                / duration,
            }
        )
        result.append(row)
    if len({row["condition_id"] for row in result}) != len(result):
        raise ValueError("condition IDs must be unique")
    return result


def condition_to_config(
    condition: Mapping[str, Any],
    spec: Mapping[str, Any],
    *,
    fixed_baseline: Mapping[str, float],
) -> InversionConfig:
    """Convert one catalog row to the exact forward-model contract."""
    fixed = tuple(
        sorted(
            (str(name), float(value))
            for name, value in fixed_baseline.items()
        )
    )
    return InversionConfig(
        E_start=float(condition["E_start"]),
        E_end=float(condition["E_end"]),
        f=float(condition["frequency_hz"]),
        dE=float(condition["amplitude_v"]),
        n_points=int(condition["n_points"]),
        points_per_cycle=int(condition["points_per_cycle"]),
        feature_grid_size=int(spec["feature_grid_size"]),
        fixed_params=fixed,
        param_specs=tuple(tuple(row) for row in spec["parameter_specs"]),
        fit_harmonics=tuple(int(value) for value in spec["fit_harmonics"]),
        feature_mode=str(spec["feature_mode"]),
        solver_backend=str(spec["solver_backend"]),
    )


def _perturbed_vector(
    encoded: Sequence[float],
    *,
    parameter_specs: Sequence[Sequence[Any]],
    parameter: str,
    direction: str,
    step: float,
) -> list[float]:
    values = [float(value) for value in encoded]
    index_by_name = {
        str(row[0]): index for index, row in enumerate(parameter_specs)
    }
    if parameter not in index_by_name:
        raise ValueError(f"unknown perturbation parameter: {parameter}")
    index = index_by_name[parameter]
    lower = float(parameter_specs[index][2])
    upper = float(parameter_specs[index][3])
    sign = 1.0 if direction == "plus" else -1.0
    values[index] = min(
        upper,
        max(lower, values[index] + sign * float(step)),
    )
    return values


def build_primary_jobs(
    parameter_points: Sequence[Mapping[str, Any]],
    conditions: Sequence[Mapping[str, Any]],
    *,
    parameter_specs: Sequence[Sequence[Any]],
    perturbations: Mapping[str, float],
    task_spec_hash: str,
) -> list[dict[str, Any]]:
    """Build baseline and full-step plus/minus jobs in deterministic order."""
    parameter_order = [str(row[0]) for row in parameter_specs]
    if set(parameter_order) != set(perturbations):
        raise ValueError("perturbations must match diagnostic parameter specs")
    jobs: list[dict[str, Any]] = []
    for point in parameter_points:
        for condition in conditions:
            variants: list[tuple[str | None, str, float]] = [
                (None, "baseline", 0.0)
            ]
            variants.extend(
                (parameter, direction, float(perturbations[parameter]))
                for parameter in parameter_order
                for direction in ("plus", "minus")
            )
            for parameter, direction, step in variants:
                encoded = [float(value) for value in point["encoded_params"]]
                if parameter is not None:
                    encoded = _perturbed_vector(
                        encoded,
                        parameter_specs=parameter_specs,
                        parameter=parameter,
                        direction=direction,
                        step=step,
                    )
                perturbation_id = (
                    "baseline"
                    if parameter is None
                    else f"{parameter}:{direction}"
                )
                payload = {
                    "job_id": (
                        f"v4:{point['dataset_id']}:"
                        f"{int(point['candidate_id']):06d}:"
                        f"{condition['condition_id']}:{perturbation_id}"
                    ),
                    "dataset_id": str(point["dataset_id"]),
                    "candidate_id": int(point["candidate_id"]),
                    "selection_rank": int(point["selection_rank"]),
                    "v3_job_input_hash": str(point["job_input_hash"]),
                    "condition_id": str(condition["condition_id"]),
                    "condition_role": str(condition["condition_role"]),
                    "condition": dict(condition),
                    "perturbation_parameter": parameter,
                    "perturbation_direction": direction,
                    "perturbation_step": float(step),
                    "encoded_params": encoded,
                    "task_spec_hash": str(task_spec_hash),
                }
                jobs.append(
                    {**payload, "job_input_hash": _sha256_json(payload)}
                )
    if len({row["job_id"] for row in jobs}) != len(jobs):
        raise ValueError("V4 job plan contains duplicate IDs")
    return jobs


def build_linearity_jobs(
    parameter_points: Sequence[Mapping[str, Any]],
    conditions: Sequence[Mapping[str, Any]],
    *,
    parameter_specs: Sequence[Sequence[Any]],
    perturbations: Mapping[str, float],
    task_spec_hash: str,
) -> list[dict[str, Any]]:
    """Build half-step plus/minus jobs for selected protocols and rank-0 points."""
    parameter_order = [str(row[0]) for row in parameter_specs]
    jobs: list[dict[str, Any]] = []
    for point in parameter_points:
        if int(point["selection_rank"]) != 0:
            raise ValueError("linearity jobs require rank-0 parameter points")
        for condition in conditions:
            for parameter in parameter_order:
                half_step = 0.5 * float(perturbations[parameter])
                for direction in ("plus", "minus"):
                    encoded = _perturbed_vector(
                        point["encoded_params"],
                        parameter_specs=parameter_specs,
                        parameter=parameter,
                        direction=direction,
                        step=half_step,
                    )
                    payload = {
                        "job_id": (
                            f"v4half:{point['dataset_id']}:"
                            f"{int(point['candidate_id']):06d}:"
                            f"{condition['condition_id']}:"
                            f"{parameter}:{direction}"
                        ),
                        "job_kind": "linearity_half_step",
                        "dataset_id": str(point["dataset_id"]),
                        "candidate_id": int(point["candidate_id"]),
                        "selection_rank": 0,
                        "v3_job_input_hash": str(point["job_input_hash"]),
                        "condition_id": str(condition["condition_id"]),
                        "condition_role": str(condition["condition_role"]),
                        "condition": dict(condition),
                        "perturbation_parameter": parameter,
                        "perturbation_direction": direction,
                        "perturbation_step": half_step,
                        "encoded_params": encoded,
                        "task_spec_hash": str(task_spec_hash),
                    }
                    jobs.append(
                        {**payload, "job_input_hash": _sha256_json(payload)}
                    )
    if len({row["job_id"] for row in jobs}) != len(jobs):
        raise ValueError("V4 linearity plan contains duplicate IDs")
    return jobs


def load_completed_jobs(
    output_dir: str | Path,
    expected_jobs: Sequence[Mapping[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Load only complete rows whose IDs and hashes match the frozen plan."""
    path = Path(output_dir) / "forward_results.jsonl"
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


def run_one_forward(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Run one V4 forward job and return its block feature vector."""
    job = dict(payload["job"])
    spec = dict(payload["spec"])
    started = time.perf_counter()
    try:
        config = condition_to_config(
            job["condition"],
            spec,
            fixed_baseline=payload["fixed_baseline"],
        )
        parameter_specs = tuple(
            tuple(row) for row in payload["parameter_specs"]
        )
        params = params_from_vector(
            job["encoded_params"],
            config,
            parameter_specs,
        )
        solution = OERPhysics.solve_ode_system_detailed(params)
        features = extract_features(solution.i_total, config)
        names, values, observable = block_feature_vector(
            features,
            harmonics=tuple(int(value) for value in spec["fit_harmonics"]),
        )
        encoded_values = [
            float(value) if is_observable else None
            for value, is_observable in zip(values, observable)
        ]
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
            "feature_names": list(names),
            "feature_values": encoded_values,
            "observable": list(observable),
            "runtime_seconds": time.perf_counter() - started,
        }
    except DynamicSolverError as exc:
        attempts = _attempt_rows(exc.attempts)
        return {
            **job,
            "success": False,
            "failure_kind": "ODE",
            "failure_message": str(exc),
            "solver_backend_used": attempts[-1]["backend"] if attempts else None,
            "solver_fallback_used": len(attempts) > 1,
            "solver_attempts": attempts,
            "steady_state_elapsed_s": None,
            "steady_state_rhs_norm": None,
            "steady_state_attempts": [],
            "feature_names": [],
            "feature_values": [],
            "observable": [],
            "runtime_seconds": time.perf_counter() - started,
        }
    except Exception as exc:
        return {
            **job,
            "success": False,
            "failure_kind": "INFRA",
            "failure_message": f"{type(exc).__name__}: {exc}",
            "solver_backend_used": None,
            "solver_fallback_used": False,
            "solver_attempts": [],
            "steady_state_elapsed_s": None,
            "steady_state_rhs_norm": None,
            "steady_state_attempts": [],
            "feature_names": [],
            "feature_values": [],
            "observable": [],
            "runtime_seconds": time.perf_counter() - started,
        }


def build_sensitivity_evidence(
    forward_rows: Sequence[Mapping[str, Any]],
    *,
    parameter_specs: Sequence[Sequence[Any]],
    ridge: float,
) -> list[dict[str, Any]]:
    """Build one signed sensitivity matrix per point and protocol."""
    parameter_order = [str(row[0]) for row in parameter_specs]
    parameter_index = {
        name: index for index, name in enumerate(parameter_order)
    }
    grouped: dict[tuple[str, int, str], list[Mapping[str, Any]]] = {}
    for row in forward_rows:
        key = (
            str(row["dataset_id"]),
            int(row["candidate_id"]),
            str(row["condition_id"]),
        )
        grouped.setdefault(key, []).append(row)

    evidence: list[dict[str, Any]] = []
    for key in sorted(grouped):
        rows = grouped[key]
        baseline_rows = [
            row
            for row in rows
            if row["perturbation_direction"] == "baseline"
        ]
        if len(baseline_rows) != 1:
            raise ValueError(f"expected one baseline row for {key}")
        baseline = baseline_rows[0]
        feature_names = tuple(
            str(value) for value in baseline["feature_names"]
        )
        if len(feature_names) != len(set(feature_names)):
            raise ValueError("forward row contains duplicate feature names")
        common = np.asarray(baseline["observable"], dtype=bool)
        for row in rows:
            if tuple(str(value) for value in row["feature_names"]) != feature_names:
                raise ValueError("forward feature names do not match")
            common &= np.asarray(row["observable"], dtype=bool)
        success = (
            len(rows) == 1 + 2 * len(parameter_order)
            and all(row.get("success") is True for row in rows)
            and bool(np.any(common))
        )
        if not success:
            evidence.append(
                {
                    "dataset_id": key[0],
                    "candidate_id": key[1],
                    "selection_rank": int(baseline["selection_rank"]),
                    "condition_id": key[2],
                    "condition_role": str(baseline["condition_role"]),
                    "success": False,
                    "feature_names": [],
                    "observable": common.tolist(),
                    "matrix": [],
                    "logdet": None,
                    "min_singular_value": None,
                    "max_abs_correlation": None,
                    "column_norms": [],
                }
            )
            continue

        baseline_values = np.asarray(
            baseline["feature_values"], dtype=float
        )[common]
        columns: list[np.ndarray] = []
        for parameter in parameter_order:
            plus = next(
                row
                for row in rows
                if row["perturbation_parameter"] == parameter
                and row["perturbation_direction"] == "plus"
            )
            minus = next(
                row
                for row in rows
                if row["perturbation_parameter"] == parameter
                and row["perturbation_direction"] == "minus"
            )
            index = parameter_index[parameter]
            span = (
                float(plus["encoded_params"][index])
                - float(minus["encoded_params"][index])
            )
            columns.append(
                central_sensitivity(
                    np.asarray(plus["feature_values"], dtype=float)[common],
                    np.asarray(minus["feature_values"], dtype=float)[common],
                    baseline_values,
                    span,
                )
            )
        matrix = np.column_stack(columns)
        metrics = matrix_metrics(matrix, ridge=float(ridge))
        evidence.append(
            {
                "dataset_id": key[0],
                "candidate_id": key[1],
                "selection_rank": int(baseline["selection_rank"]),
                "condition_id": key[2],
                "condition_role": str(baseline["condition_role"]),
                "success": True,
                "feature_names": [
                    name
                    for name, is_observable in zip(feature_names, common)
                    if is_observable
                ],
                "observable": common.tolist(),
                "matrix": matrix.tolist(),
                **metrics,
            }
        )
    return evidence


def _stack_named_matrices(
    rows: Sequence[Mapping[str, Any]],
) -> np.ndarray:
    if not rows or any(row.get("success") is not True for row in rows):
        raise ValueError("portfolio contains an unsuccessful sensitivity matrix")
    common = set(str(name) for name in rows[0]["feature_names"])
    for row in rows[1:]:
        common &= {str(name) for name in row["feature_names"]}
    ordered = [
        str(name) for name in rows[0]["feature_names"] if str(name) in common
    ]
    if not ordered:
        raise ValueError("portfolio matrices share no feature rows")
    stacked: list[np.ndarray] = []
    for row in rows:
        names = [str(name) for name in row["feature_names"]]
        index = {name: position for position, name in enumerate(names)}
        matrix = np.asarray(row["matrix"], dtype=float)
        stacked.append(matrix[[index[name] for name in ordered]])
    return np.vstack(stacked)


def compute_portfolio_gains(
    sensitivity_rows: Sequence[Mapping[str, Any]],
    condition_catalog: Sequence[Mapping[str, Any]],
    *,
    ridge: float,
    minimum_positive: int,
    added_existing: Sequence[str] = (),
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Compare each remaining candidate with the current protocol portfolio."""
    added = {str(value) for value in added_existing}
    existing_ids = {
        str(row["condition_id"])
        for row in condition_catalog
        if row["condition_role"] == "existing"
    } | added
    candidate_ids = [
        str(row["condition_id"])
        for row in condition_catalog
        if row["condition_role"] == "candidate"
        and str(row["condition_id"]) not in added
    ]
    points = sorted(
        {
            (
                str(row["dataset_id"]),
                int(row["candidate_id"]),
                int(row["selection_rank"]),
            )
            for row in sensitivity_rows
        }
    )
    lookup = {
        (
            str(row["dataset_id"]),
            int(row["candidate_id"]),
            str(row["condition_id"]),
        ): row
        for row in sensitivity_rows
    }
    detail: list[dict[str, Any]] = []
    for dataset_id, candidate_id, selection_rank in points:
        base_rows = [
            lookup[(dataset_id, candidate_id, condition_id)]
            for condition_id in sorted(existing_ids)
            if (dataset_id, candidate_id, condition_id) in lookup
        ]
        base_success = (
            len(base_rows) == len(existing_ids)
            and all(row.get("success") is True for row in base_rows)
        )
        base_metrics = (
            matrix_metrics(_stack_named_matrices(base_rows), ridge=ridge)
            if base_success
            else None
        )
        for condition_id in candidate_ids:
            candidate = lookup.get(
                (dataset_id, candidate_id, condition_id)
            )
            success = bool(
                base_success
                and candidate is not None
                and candidate.get("success") is True
            )
            if success:
                combined = matrix_metrics(
                    _stack_named_matrices([*base_rows, candidate]),
                    ridge=ridge,
                )
                row = {
                    "dataset_id": dataset_id,
                    "candidate_id": candidate_id,
                    "selection_rank": selection_rank,
                    "condition_id": condition_id,
                    "success": True,
                    "base_logdet": base_metrics["logdet"],
                    "combined_logdet": combined["logdet"],
                    "logdet_gain": (
                        combined["logdet"] - base_metrics["logdet"]
                    ),
                    "correlation_reduction": (
                        base_metrics["max_abs_correlation"]
                        - combined["max_abs_correlation"]
                    ),
                    "min_singular_gain": (
                        combined["min_singular_value"]
                        - base_metrics["min_singular_value"]
                    ),
                }
            else:
                row = {
                    "dataset_id": dataset_id,
                    "candidate_id": candidate_id,
                    "selection_rank": selection_rank,
                    "condition_id": condition_id,
                    "success": False,
                    "base_logdet": None,
                    "combined_logdet": None,
                    "logdet_gain": None,
                    "correlation_reduction": None,
                    "min_singular_gain": None,
                }
            detail.append(row)

    point_count = len(points)
    catalog_by_id = {
        str(row["condition_id"]): row for row in condition_catalog
    }
    aggregate: list[dict[str, Any]] = []
    for condition_id in candidate_ids:
        rows = [
            row for row in detail if row["condition_id"] == condition_id
        ]
        successful = [row for row in rows if row["success"]]
        gains = np.asarray(
            [row["logdet_gain"] for row in successful],
            dtype=float,
        )
        correlations = np.asarray(
            [row["correlation_reduction"] for row in successful],
            dtype=float,
        )
        singular = np.asarray(
            [row["min_singular_gain"] for row in successful],
            dtype=float,
        )
        all_success = len(successful) == point_count
        aggregate.append(
            {
                "condition_id": condition_id,
                "all_success": all_success,
                "parameter_point_count": point_count,
                "successful_point_count": len(successful),
                "q25_logdet_gain": (
                    float(np.quantile(gains, 0.25))
                    if successful
                    else None
                ),
                "median_correlation_reduction": (
                    float(np.median(correlations))
                    if successful
                    else None
                ),
                "q25_min_singular_gain": (
                    float(np.quantile(singular, 0.25))
                    if successful
                    else None
                ),
                "positive_gain_count": int(np.sum(gains > 0.0)),
                "total_points": int(
                    catalog_by_id[condition_id]["n_points"]
                ),
            }
        )
    ranked = rank_candidate_conditions(
        aggregate,
        minimum_positive=minimum_positive,
    )
    rank_by_id = {
        row["condition_id"]: rank for rank, row in enumerate(ranked, start=1)
    }
    for row in aggregate:
        ranked_row = next(
            item
            for item in ranked
            if item["condition_id"] == row["condition_id"]
        )
        row["eligible"] = bool(ranked_row["eligible"])
        row["rank"] = int(rank_by_id[row["condition_id"]])
    aggregate.sort(key=lambda row: row["rank"])
    return detail, aggregate


def build_recommendation(
    sensitivity_rows: Sequence[Mapping[str, Any]],
    condition_catalog: Sequence[Mapping[str, Any]],
    *,
    ridge: float,
    minimum_positive: int,
) -> dict[str, Any]:
    """Greedily select two robust protocols using the frozen ranking."""
    first_detail, first_ranking = compute_portfolio_gains(
        sensitivity_rows,
        condition_catalog,
        ridge=ridge,
        minimum_positive=minimum_positive,
    )
    selected: list[str] = []
    stages: list[dict[str, Any]] = [
        {"stage": 1, "ranking": first_ranking}
    ]
    numerical_failure = any(
        row.get("success") is not True for row in sensitivity_rows
    )
    if (
        not numerical_failure
        and first_ranking
        and first_ranking[0]["eligible"]
    ):
        selected.append(str(first_ranking[0]["condition_id"]))
        _, second_ranking = compute_portfolio_gains(
            sensitivity_rows,
            condition_catalog,
            ridge=ridge,
            minimum_positive=minimum_positive,
            added_existing=selected,
        )
        stages.append({"stage": 2, "ranking": second_ranking})
        if second_ranking and second_ranking[0]["eligible"]:
            selected.append(str(second_ranking[0]["condition_id"]))
    if numerical_failure:
        selected = []
        status = "FAIL_NUMERICAL"
    else:
        status = (
            "RECOMMEND_TWO"
            if len(selected) == 2
            else "NO_ROBUST_RECOMMENDATION"
        )
    return {
        "status": status,
        "selected": selected,
        "stages": stages,
        "first_stage_detail": first_detail,
        "parameter_estimation_enabled": False,
        "experimental_validation_completed": False,
        "linearity_order_preserved": None,
    }


def _run_jobs(
    jobs: Sequence[Mapping[str, Any]],
    *,
    output: Path,
    spec: Mapping[str, Any],
    inputs: Mapping[str, Any],
    workers: int,
    completed: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    pending = [job for job in jobs if job["job_id"] not in completed]
    payloads = [
        {
            "job": job,
            "spec": spec,
            "parameter_specs": inputs["parameter_specs"],
            "fixed_baseline": inputs["fixed_baseline"],
        }
        for job in pending
    ]
    if payloads:
        with ProcessPoolExecutor(max_workers=workers) as pool:
            futures = {
                pool.submit(run_one_forward, payload): payload["job"]["job_id"]
                for payload in payloads
            }
            for future in as_completed(futures):
                job_id = futures[future]
                completed[job_id] = future.result()
                ordered = [
                    completed[row["job_id"]]
                    for row in jobs
                    if row["job_id"] in completed
                ]
                _atomic_jsonl(output / "forward_results.jsonl", ordered)
    return completed


def _linearity_evidence(
    primary_sensitivity: Sequence[Mapping[str, Any]],
    half_sensitivity: Sequence[Mapping[str, Any]],
    *,
    threshold: float,
) -> list[dict[str, Any]]:
    primary = {
        (
            str(row["dataset_id"]),
            int(row["candidate_id"]),
            str(row["condition_id"]),
        ): row
        for row in primary_sensitivity
    }
    rows: list[dict[str, Any]] = []
    for half in half_sensitivity:
        key = (
            str(half["dataset_id"]),
            int(half["candidate_id"]),
            str(half["condition_id"]),
        )
        full = primary[key]
        full_names = [str(value) for value in full["feature_names"]]
        half_names = [str(value) for value in half["feature_names"]]
        common = [
            name for name in full_names if name in set(half_names)
        ]
        full_index = {name: index for index, name in enumerate(full_names)}
        half_index = {name: index for index, name in enumerate(half_names)}
        full_matrix = np.asarray(full["matrix"], dtype=float)[
            [full_index[name] for name in common]
        ]
        half_matrix = np.asarray(half["matrix"], dtype=float)[
            [half_index[name] for name in common]
        ]
        cosines = column_direction_cosines(full_matrix, half_matrix)
        for parameter, cosine in zip(
            ("k0_1", "k0_2", "k0_3", "G_OH", "G_O"),
            cosines,
        ):
            rows.append(
                {
                    "dataset_id": key[0],
                    "candidate_id": key[1],
                    "condition_id": key[2],
                    "parameter": parameter,
                    "direction_cosine": float(cosine),
                    "stable": bool(float(cosine) >= float(threshold)),
                }
            )
    return rows


def linearity_preserves_recommendation_order(
    primary_sensitivity: Sequence[Mapping[str, Any]],
    half_sensitivity: Sequence[Mapping[str, Any]],
    condition_catalog: Sequence[Mapping[str, Any]],
    *,
    selected: Sequence[str],
    ridge: float,
) -> bool:
    """Check whether the two selected protocols retain their stage-one order."""
    selected_ids = tuple(str(value) for value in selected)
    if len(selected_ids) != 2:
        raise ValueError("linearity order check requires two selected protocols")
    catalog = [
        row
        for row in condition_catalog
        if row["condition_role"] == "existing"
        or str(row["condition_id"]) in selected_ids
    ]
    matrices = [
        row
        for row in primary_sensitivity
        if int(row["selection_rank"]) == 0
        and row["condition_role"] == "existing"
    ] + [dict(row) for row in half_sensitivity]
    _, ranking = compute_portfolio_gains(
        matrices,
        catalog,
        ridge=ridge,
        minimum_positive=0,
    )
    ranked_ids = tuple(str(row["condition_id"]) for row in ranking)
    return ranked_ids[:2] == selected_ids


def _prepare_output(output: Path, *, resume: bool) -> None:
    output.mkdir(parents=True, exist_ok=True)
    unknown = sorted(
        path.name
        for path in output.iterdir()
        if path.name not in RUNNER_FILES | WORKFLOW_FILES
    )
    if unknown:
        raise ValueError(f"unknown output files: {', '.join(unknown)}")
    scientific = sorted(
        path.name for path in output.iterdir() if path.name in RUNNER_FILES
    )
    if scientific and not resume:
        raise ValueError(
            "scientific output already exists; use --resume"
        )


def _resume_expected_jobs(
    primary_jobs: Sequence[Mapping[str, Any]],
    parameter_points: Sequence[Mapping[str, Any]],
    conditions: Sequence[Mapping[str, Any]],
    *,
    parameter_specs: Sequence[Sequence[Any]],
    perturbations: Mapping[str, float],
    task_spec_hash: str,
) -> list[dict[str, Any]]:
    """Return primary plus every valid candidate half-step resume job."""
    rank_zero = [
        row for row in parameter_points if int(row["selection_rank"]) == 0
    ]
    candidates = [
        row for row in conditions if row["condition_role"] == "candidate"
    ]
    return [
        *primary_jobs,
        *build_linearity_jobs(
            rank_zero,
            candidates,
            parameter_specs=parameter_specs,
            perturbations=perturbations,
            task_spec_hash=task_spec_hash,
        ),
    ]


def _freeze_spec(
    spec: Mapping[str, Any],
    *,
    smoke: bool,
    provenance: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        **dict(spec),
        "run_mode": "smoke" if smoke else "formal",
        "source_state": {
            "source_commit": str(provenance["source_commit"]),
            "dirty": bool(provenance["dirty"]),
            "dirty_paths": list(provenance.get("dirty_paths", [])),
            "ignored_workflow_paths": list(
                provenance.get("ignored_workflow_paths", [])
            ),
            "dirty_content_sha256": provenance.get(
                "dirty_content_sha256"
            ),
        },
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task-spec", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--smoke", action="store_true")
    args = parser.parse_args(argv)
    if args.workers < 1:
        parser.error("--workers must be positive")

    started = time.perf_counter()
    spec = load_spec(args.task_spec)
    inputs = load_inputs(ROOT, spec)
    provenance = _git_provenance()
    if not args.smoke and provenance["dirty"]:
        raise ValueError("formal V4 requires a clean source state")
    frozen = _freeze_spec(
        spec,
        smoke=args.smoke,
        provenance=provenance,
    )
    task_hash = _sha256_json(spec)
    conditions = build_condition_catalog(spec, smoke=args.smoke)
    points = list(inputs["parameter_points"])
    if args.smoke:
        points = [
            row
            for row in points
            if row["dataset_id"] == spec["smoke"]["dataset_id"]
            and int(row["selection_rank"])
            == int(spec["smoke"]["selection_rank"])
        ]
    primary_jobs = build_primary_jobs(
        points,
        conditions,
        parameter_specs=inputs["parameter_specs"],
        perturbations=spec["perturbations"],
        task_spec_hash=task_hash,
    )
    _prepare_output(args.output, resume=args.resume)
    _atomic_json(args.output / "v4_task_spec.json", frozen)
    _atomic_csv(
        args.output / "condition_catalog.csv",
        conditions,
        fieldnames=(
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
        ),
    )

    if args.resume:
        resume_jobs = _resume_expected_jobs(
            primary_jobs,
            points,
            conditions,
            parameter_specs=inputs["parameter_specs"],
            perturbations=spec["perturbations"],
            task_spec_hash=task_hash,
        )
        completed = load_completed_jobs(args.output, resume_jobs)
    else:
        completed = {}
    completed = _run_jobs(
        primary_jobs,
        output=args.output,
        spec=spec,
        inputs=inputs,
        workers=args.workers,
        completed=completed,
    )
    primary_rows = [completed[job["job_id"]] for job in primary_jobs]
    sensitivity = build_sensitivity_evidence(
        primary_rows,
        parameter_specs=inputs["parameter_specs"],
        ridge=float(spec["ridge"]),
    )
    recommendation = build_recommendation(
        sensitivity,
        conditions,
        ridge=float(spec["ridge"]),
        minimum_positive=int(spec["minimum_positive_points"]),
    )

    linearity_jobs: list[dict[str, Any]] = []
    linearity_rows: list[dict[str, Any]] = []
    if (
        not args.smoke
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
        all_jobs = [*primary_jobs, *linearity_jobs]
        completed = (
            load_completed_jobs(args.output, all_jobs)
            if args.resume
            else completed
        )
        completed = _run_jobs(
            all_jobs,
            output=args.output,
            spec=spec,
            inputs=inputs,
            workers=args.workers,
            completed=completed,
        )
        baseline_rows = [
            row
            for row in primary_rows
            if int(row["selection_rank"]) == 0
            and row["condition_id"] in recommendation["selected"]
            and row["perturbation_direction"] == "baseline"
        ]
        half_rows = [
            completed[job["job_id"]] for job in linearity_jobs
        ]
        half_sensitivity = build_sensitivity_evidence(
            [*baseline_rows, *half_rows],
            parameter_specs=inputs["parameter_specs"],
            ridge=float(spec["ridge"]),
        )
        if any(row.get("success") is not True for row in half_sensitivity):
            recommendation["status"] = "FAIL_NUMERICAL"
        else:
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

    all_jobs = [*primary_jobs, *linearity_jobs]
    unexpected_resume = sorted(
        set(completed) - {str(row["job_id"]) for row in all_jobs}
    )
    if unexpected_resume:
        raise ValueError(
            "resume data contains half-step jobs outside the rebuilt "
            f"recommendation: {unexpected_resume[0]}"
        )
    all_rows = [completed[job["job_id"]] for job in all_jobs]
    _atomic_json(
        args.output / "job_plan.json",
        {
            "task_spec_hash": task_hash,
            "primary_job_count": len(primary_jobs),
            "linearity_job_count": len(linearity_jobs),
            "jobs": all_jobs,
        },
    )
    _atomic_jsonl(args.output / "forward_results.jsonl", all_rows)
    _atomic_jsonl(args.output / "sensitivity_matrices.jsonl", sensitivity)
    gain_rows: list[dict[str, Any]] = []
    for stage in recommendation["stages"]:
        for row in stage["ranking"]:
            gain_rows.append({"stage": stage["stage"], **row})
    _atomic_csv(
        args.output / "portfolio_gain.csv",
        gain_rows,
        fieldnames=(
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
        ),
    )
    _atomic_csv(
        args.output / "linearity_check.csv",
        linearity_rows,
        fieldnames=(
            "dataset_id",
            "candidate_id",
            "condition_id",
            "parameter",
            "direction_cosine",
            "stable",
        ),
    )
    recommendation.update(
        {
            "analysis_id": spec["analysis_id"],
            "run_mode": "smoke" if args.smoke else "formal",
            "job_count": len(all_jobs),
            "successful_job_count": sum(
                row.get("success") is True for row in all_rows
            ),
            "duration_seconds": time.perf_counter() - started,
            "deferred_experimental_inputs": list(
                spec["deferred_experimental_inputs"]
            ),
        }
    )
    _atomic_json(args.output / "recommendation.json", recommendation)
    artifact_names = sorted(
        RUNNER_FILES - {"run_manifest.json"}
    )
    manifest = {
        "schema_version": 1,
        "analysis_id": spec["analysis_id"],
        "run_mode": recommendation["run_mode"],
        "task_spec_hash": task_hash,
        "source_state": frozen["source_state"],
        "input_hashes": inputs["input_hashes"],
        "primary_job_count": len(primary_jobs),
        "linearity_job_count": len(linearity_jobs),
        "job_count": len(all_jobs),
        "success_count": recommendation["successful_job_count"],
        "workers": args.workers,
        "artifact_sha256": {
            name: _sha256_file(args.output / name)
            for name in artifact_names
        },
    }
    _atomic_json(args.output / "run_manifest.json", manifest)
    print(json.dumps(recommendation, indent=2, allow_nan=False))
    return 0 if recommendation["successful_job_count"] == len(all_jobs) else 2


if __name__ == "__main__":
    raise SystemExit(main())
