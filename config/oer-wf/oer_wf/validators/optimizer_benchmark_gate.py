"""Independent Gate A6 fixed-budget optimizer benchmark validator."""

from __future__ import annotations

import json
import math
import statistics
from pathlib import Path
from typing import Any, Mapping, Sequence

from oer_wf.models import CheckResult


FROZEN_CONFIG = {
    "gate_version": 1,
    "phase": "development",
    "optimizers": ["tpe", "sobol_pattern", "de_fixed"],
    "parameter_pairs": [
        ["k0_2", "k0_3"],
        ["k0_2", "G_O"],
        ["k0_3", "G_O"],
    ],
    "truth_id": "center",
    "noise_fraction": 0.0,
    "seed": 7,
    "optimization_budget": 100,
    "max_parameter_error": 0.05,
    "require_zero_ode_failures": True,
    "require_zero_boundary_hits": True,
}


def _reject_nonfinite(value: Any, location: str = "root") -> None:
    if isinstance(value, float) and not math.isfinite(value):
        raise FloatingPointError(f"non-finite value at {location}")
    if isinstance(value, dict):
        for key, child in value.items():
            _reject_nonfinite(child, f"{location}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _reject_nonfinite(child, f"{location}[{index}]")


def _load_json(path: Path) -> Any:
    def reject_constant(name: str) -> None:
        raise FloatingPointError(f"non-standard JSON constant: {name}")

    value = json.loads(
        path.read_text(encoding="utf-8"),
        parse_constant=reject_constant,
    )
    _reject_nonfinite(value, path.name)
    return value


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    raw = path.read_text(encoding="utf-8")
    if raw and not raw.endswith("\n"):
        raise ValueError(f"{path.name} has an incomplete final line")
    rows = []
    for line_number, line in enumerate(raw.splitlines(), start=1):
        if not line.strip():
            raise ValueError(f"{path.name}:{line_number} is blank")
        value = json.loads(
            line,
            parse_constant=lambda name: (_ for _ in ()).throw(
                FloatingPointError(
                    f"non-standard JSON constant: {name}"
                )
            ),
        )
        if not isinstance(value, dict):
            raise ValueError(
                f"{path.name}:{line_number} must be an object"
            )
        _reject_nonfinite(value, f"{path.name}:{line_number}")
        rows.append(value)
    return rows


def recompute_selection(
    rows: Sequence[Mapping[str, Any]],
    config: Mapping[str, Any],
) -> dict[str, Any]:
    """Recompute the frozen scientific choice without trusting summary files."""

    optimizer_order = list(config["optimizers"])
    grouped = {
        optimizer: [
            row for row in rows if row["optimizer"] == optimizer
        ]
        for optimizer in optimizer_order
    }
    metrics: dict[str, dict[str, Any]] = {}
    eligible = []
    for optimizer in optimizer_order:
        errors = [
            float(
                row["parameter_metrics"][name][
                    "normalized_bound_error"
                ]
            )
            for row in grouped[optimizer]
            for name in row["free_parameters"]
        ]
        regrets = [
            float(row["best_objective"])
            - float(row["truth_objective"])
            for row in grouped[optimizer]
        ]
        passed = optimizer != "tpe" and all(
            error <= float(config["max_parameter_error"])
            for error in errors
        )
        metrics[optimizer] = {
            "eligible_replacement": passed,
            "worst_parameter_error": max(errors),
            "median_parameter_error": float(statistics.median(errors)),
            "maximum_objective_regret": max(regrets),
            "study_count": len(grouped[optimizer]),
        }
        if passed:
            eligible.append(optimizer)
    preference = {"sobol_pattern": 0, "de_fixed": 1}
    ranked = sorted(
        eligible,
        key=lambda name: (
            metrics[name]["worst_parameter_error"],
            metrics[name]["median_parameter_error"],
            metrics[name]["maximum_objective_regret"],
            preference[name],
        ),
    )
    selected = ranked[0] if ranked else None
    return {
        "gate_version": 1,
        "max_parameter_error": float(config["max_parameter_error"]),
        "optimizer_metrics": metrics,
        "eligible_optimizers": eligible,
        "selected_optimizer": selected,
        "scientific_gate_passed": selected is not None,
        "next_action": (
            "PLAN_LOCKED_CONFIRMATION" if selected else "STOP"
        ),
    }


def _validate_structure(
    summary: Any,
    rows: list[dict[str, Any]],
    evaluations: list[dict[str, Any]],
    selection: Any,
    config: Mapping[str, Any],
) -> tuple[list[str], dict[str, Any] | None]:
    errors: list[str] = []
    if not isinstance(summary, dict) or not isinstance(selection, dict):
        return ["summary and selection must be objects"], None
    pairs = [tuple(pair) for pair in config["parameter_pairs"]]
    optimizers = list(config["optimizers"])
    expected = {
        (
            pair,
            optimizer,
            config["truth_id"],
            float(config["noise_fraction"]),
            int(config["seed"]),
            int(config["optimization_budget"]),
        )
        for pair in pairs
        for optimizer in optimizers
    }
    actual = set()
    job_ids = set()
    for index, row in enumerate(rows):
        try:
            identity = (
                tuple(row["free_parameters"]),
                row["optimizer"],
                row["truth_id"],
                float(row["noise_fraction"]),
                int(row["seed"]),
                int(row["budget"]),
            )
            job_id = str(row["job_id"])
        except (KeyError, TypeError, ValueError) as exc:
            errors.append(f"row[{index}] invalid identity: {exc}")
            continue
        if identity in actual or job_id in job_ids:
            errors.append(f"row[{index}] duplicate identity or job_id")
        actual.add(identity)
        job_ids.add(job_id)
        if row.get("success") is not True:
            errors.append(f"{job_id} success is not true")
        if row.get("optimization_calls") != config["optimization_budget"]:
            errors.append(f"{job_id} optimization call count drift")
        if row.get("diagnostic_truth_calls") != 1:
            errors.append(f"{job_id} truth diagnostic count drift")
        if row.get("truth_diagnostic_sequence") != (
            int(config["optimization_budget"]) + 1
        ):
            errors.append(f"{job_id} truth diagnostic order invalid")
        if config["require_zero_ode_failures"] and row.get(
            "n_ode_fail"
        ) != 0:
            errors.append(f"{job_id} has ODE failures")
        metrics = row.get("parameter_metrics")
        if not isinstance(metrics, dict):
            errors.append(f"{job_id} parameter_metrics missing")
            continue
        if config["require_zero_boundary_hits"] and metrics.get(
            "boundary_hits"
        ) != []:
            errors.append(f"{job_id} has boundary hits")
        for name in row["free_parameters"]:
            item = metrics.get(name)
            if not isinstance(item, dict):
                errors.append(f"{job_id}.{name} metric missing")
                continue
            error = item.get("normalized_bound_error")
            if not isinstance(error, (int, float)):
                errors.append(f"{job_id}.{name} error invalid")
    if actual != expected:
        errors.append(
            "frozen job matrix mismatch: "
            f"missing={len(expected - actual)} extra={len(actual - expected)}"
        )

    evaluations_by_job = {job_id: [] for job_id in job_ids}
    for index, evaluation in enumerate(evaluations):
        job_id = evaluation.get("job_id")
        if job_id not in evaluations_by_job:
            errors.append(f"evaluation[{index}] has unknown job_id")
            continue
        evaluations_by_job[job_id].append(evaluation)
    budget = int(config["optimization_budget"])
    for job_id, trace in evaluations_by_job.items():
        if len(trace) != budget:
            errors.append(f"{job_id} evaluation count={len(trace)}")
            continue
        sequences = [item.get("sequence") for item in trace]
        if sequences != list(range(1, budget + 1)):
            errors.append(f"{job_id} evaluation sequence drift")
        if any(item.get("kind") != "optimization" for item in trace):
            errors.append(f"{job_id} contains non-optimization trace rows")

    if summary.get("job_count") != len(expected):
        errors.append("summary job_count mismatch")
    if summary.get("completed_jobs") != len(expected):
        errors.append("summary completed_jobs mismatch")
    if summary.get("optimization_calls") != len(expected) * budget:
        errors.append("summary optimization_calls mismatch")
    if summary.get("diagnostic_truth_calls") != len(expected):
        errors.append("summary diagnostic_truth_calls mismatch")
    if summary.get("execution_passed") is not True:
        errors.append("summary execution_passed is not true")
    if summary.get("is_smoke") is not False:
        errors.append("formal archive marked as smoke")

    recomputed = None
    if not errors:
        recomputed = recompute_selection(rows, config)
        if selection != recomputed:
            errors.append("selection.json differs from recomputed selection")
        if (
            summary.get("scientific_gate_passed")
            != recomputed["scientific_gate_passed"]
        ):
            errors.append("summary scientific gate mismatch")
    return errors, recomputed


def run(
    archive_dir: Path,
    expected_files: list[str] | None = None,
    *,
    validator_config: dict[str, Any] | None = None,
) -> list[CheckResult]:
    config = validator_config or {}
    if config != FROZEN_CONFIG:
        return [
            CheckResult(
                name="structure:optimizer_benchmark_gate_config",
                passed=False,
                detail="validator config differs from frozen gate v1",
            )
        ]
    required = (
        "summary.json",
        "results.jsonl",
        "evaluations.jsonl",
        "selection.json",
    )
    missing = [name for name in required if not (archive_dir / name).is_file()]
    if missing:
        return [
            CheckResult(
                name="structure:optimizer_benchmark_gate",
                passed=False,
                detail=f"missing inputs: {missing}",
            )
        ]
    try:
        summary = _load_json(archive_dir / "summary.json")
        rows = _load_jsonl(archive_dir / "results.jsonl")
        evaluations = _load_jsonl(archive_dir / "evaluations.jsonl")
        selection = _load_json(archive_dir / "selection.json")
    except FloatingPointError as exc:
        return [
            CheckResult(
                name="numerical:optimizer_benchmark_gate",
                passed=False,
                detail=str(exc),
            )
        ]
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return [
            CheckResult(
                name="structure:optimizer_benchmark_gate",
                passed=False,
                detail=str(exc),
            )
        ]
    errors, recomputed = _validate_structure(
        summary,
        rows,
        evaluations,
        selection,
        config,
    )
    if errors:
        return [
            CheckResult(
                name="structure:optimizer_benchmark_gate",
                passed=False,
                detail="; ".join(errors[:20]),
            )
        ]
    assert recomputed is not None
    selected = recomputed["selected_optimizer"]
    return [
        CheckResult(
            name="structure:optimizer_benchmark_gate",
            passed=True,
            detail="9 jobs and 900 optimization calls independently verified",
        ),
        CheckResult(
            name="scientific:optimizer_benchmark_gate",
            passed=bool(recomputed["scientific_gate_passed"]),
            detail=(
                f"selected_optimizer={selected}"
                if selected
                else "no replacement optimizer passed all three pairs"
            ),
        ),
    ]
