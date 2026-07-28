"""A6 synthetic-recovery structure, numerical, and scientific gate."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Optional

from oer_wf.models import CheckResult


def _reject_nonfinite(value: Any, path: str = "root") -> None:
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError(f"non-finite float at {path}: {value!r}")
    if isinstance(value, dict):
        for key, child in value.items():
            _reject_nonfinite(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _reject_nonfinite(child, f"{path}[{index}]")


def _load_json(path: Path) -> Any:
    def reject_constant(name: str) -> None:
        raise ValueError(f"non-standard JSON constant rejected: {name}")

    data = json.loads(path.read_text(encoding="utf-8"), parse_constant=reject_constant)
    _reject_nonfinite(data)
    return data


def run(
    archive_dir: Path,
    expected_files: list[str] | None = None,
    *,
    validator_config: Optional[dict[str, Any]] = None,
) -> list[CheckResult]:
    cfg = validator_config or {}
    parameter_names = cfg.get("parameter_names")
    if not isinstance(parameter_names, list) or not parameter_names:
        return [CheckResult(
            name="structure:recovery_gate_config",
            passed=False,
            detail="parameter_names missing or invalid",
        )]
    try:
        max_boundary = float(cfg.get("max_boundary_hit_rate", 0.0))
    except (TypeError, ValueError):
        return [CheckResult(
            name="structure:recovery_gate_config",
            passed=False,
            detail="max_boundary_hit_rate must be numeric",
        )]
    if not math.isfinite(max_boundary) or not 0.0 <= max_boundary <= 1.0:
        return [CheckResult(
            name="structure:recovery_gate_config",
            passed=False,
            detail="max_boundary_hit_rate must be finite and in [0,1]",
        )]

    summary_path = archive_dir / "summary.json"
    results_path = archive_dir / "results.jsonl"
    if not summary_path.is_file() or not results_path.is_file():
        return [CheckResult(
            name="structure:recovery_gate_inputs",
            passed=False,
            detail="summary.json and results.jsonl are required",
        )]
    try:
        summary = _load_json(summary_path)
        rows = [
            _load_json_line(line, line_no)
            for line_no, line in enumerate(
                results_path.read_text(encoding="utf-8").splitlines(), 1
            )
            if line.strip()
        ]
    except ValueError as exc:
        prefix = (
            "numerical:" if "non-finite" in str(exc) or "constant" in str(exc)
            else "structure:"
        )
        return [CheckResult(
            name=f"{prefix}recovery_gate_inputs",
            passed=False,
            detail=str(exc),
        )]
    if not isinstance(summary, dict):
        return [CheckResult(
            name="structure:summary.json", passed=False, detail="must be an object"
        )]
    job_ids = [row.get("job_id") for row in rows]
    if any(not job_id for job_id in job_ids) or len(set(job_ids)) != len(job_ids):
        return [CheckResult(
            name="structure:results.jsonl",
            passed=False,
            detail="job_id values must be present and unique",
        )]
    if summary.get("job_count") != len(rows) or summary.get("completed_jobs") != len(rows):
        return [CheckResult(
            name="structure:job_count",
            passed=False,
            detail=(
                f"job_count={summary.get('job_count')} "
                f"completed_jobs={summary.get('completed_jobs')} rows={len(rows)}"
            ),
        )]
    recovery = summary.get("recovery_summary")
    groups = recovery.get("groups") if isinstance(recovery, dict) else None
    if not isinstance(groups, list) or recovery.get("group_count") != len(groups):
        return [CheckResult(
            name="structure:recovery_summary",
            passed=False,
            detail="groups missing or group_count mismatch",
        )]

    expected_parameters = set(map(str, parameter_names))
    structure_errors: list[str] = []
    scientific_errors: list[str] = []
    covered_count = 0
    parameter_total = 0
    boundary_violations = 0
    successful_groups = 0
    for index, group in enumerate(groups):
        if not isinstance(group, dict) or not isinstance(group.get("all_success"), bool):
            structure_errors.append(f"group[{index}] invalid or all_success not bool")
            continue
        if group["all_success"]:
            successful_groups += 1
        elif cfg.get("require_all_studies_success", False):
            scientific_errors.append(f"group[{index}] all_success=false")
        parameters = group.get("parameters")
        if not isinstance(parameters, dict) or set(parameters) != expected_parameters:
            structure_errors.append(f"group[{index}] parameter set mismatch")
            continue
        for name in parameter_names:
            item = parameters[name]
            if not isinstance(item, dict) or not isinstance(
                item.get("truth_covered_by_seed_range"), bool
            ):
                structure_errors.append(f"group[{index}].{name} invalid coverage")
                continue
            covered = item["truth_covered_by_seed_range"]
            parameter_total += 1
            covered_count += int(covered)
            if not covered and cfg.get("require_truth_covered_by_seed_range", False):
                scientific_errors.append(f"group[{index}].{name} truth not covered")
            try:
                rate = float(item.get("boundary_hit_rate"))
            except (TypeError, ValueError):
                structure_errors.append(f"group[{index}].{name} invalid boundary rate")
                continue
            if not math.isfinite(rate) or not 0.0 <= rate <= 1.0:
                structure_errors.append(f"group[{index}].{name} boundary rate out of range")
            elif rate > max_boundary:
                boundary_violations += 1
                scientific_errors.append(
                    f"group[{index}].{name} boundary_hit_rate={rate} > {max_boundary}"
                )

    if structure_errors:
        return [CheckResult(
            name="structure:recovery_gate",
            passed=False,
            detail="; ".join(structure_errors[:12]),
        )]
    detail = (
        f"groups={len(groups)}; truth_coverage={covered_count}/{parameter_total}; "
        f"boundary_violations={boundary_violations}; "
        f"study_success={successful_groups}/{len(groups)}"
    )
    return [CheckResult(
        name="scientific:recovery_gate",
        passed=not scientific_errors,
        detail=detail + (
            "; fails: " + "; ".join(scientific_errors[:20])
            if scientific_errors else ""
        ),
    )]


def _load_json_line(line: str, line_no: int) -> dict[str, Any]:
    def reject_constant(name: str) -> None:
        raise ValueError(f"non-standard JSON constant rejected: {name}")

    value = json.loads(line, parse_constant=reject_constant)
    _reject_nonfinite(value, f"results.jsonl:{line_no}")
    if not isinstance(value, dict):
        raise ValueError(f"results.jsonl line {line_no} must be an object")
    return value
