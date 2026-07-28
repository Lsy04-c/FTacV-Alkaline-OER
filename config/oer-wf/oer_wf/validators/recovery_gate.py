"""A6 synthetic-recovery structure, numerical, and scientific gate."""

from __future__ import annotations

import json
import math
import statistics
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
    gate_version = cfg.get("gate_version", 1)
    if isinstance(gate_version, bool) or gate_version not in (1, 2):
        return [CheckResult(
            name="structure:recovery_gate_config",
            passed=False,
            detail="gate_version must be 1 or 2",
        )]
    if gate_version == 2:
        return _run_v2(archive_dir, cfg)

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


def _run_v2(archive_dir: Path, cfg: dict[str, Any]) -> list[CheckResult]:
    config, config_error = _parse_v2_config(cfg)
    if config_error:
        return [CheckResult(
            name="structure:recovery_gate_v2_config",
            passed=False,
            detail=config_error,
        )]

    summary_path = archive_dir / "summary.json"
    results_path = archive_dir / "results.jsonl"
    if not summary_path.is_file() or not results_path.is_file():
        return [CheckResult(
            name="structure:recovery_gate_v2_inputs",
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
    except (OSError, ValueError) as exc:
        prefix = (
            "numerical:" if "non-finite" in str(exc) or "constant" in str(exc)
            else "structure:"
        )
        return [CheckResult(
            name=f"{prefix}recovery_gate_v2_inputs",
            passed=False,
            detail=str(exc),
        )]

    if not isinstance(summary, dict):
        return [CheckResult(
            name="structure:recovery_gate_v2",
            passed=False,
            detail="summary.json must be an object",
        )]
    job_ids = [row.get("job_id") for row in rows]
    if any(not job_id for job_id in job_ids) or len(set(job_ids)) != len(job_ids):
        return [CheckResult(
            name="structure:recovery_gate_v2",
            passed=False,
            detail="job_id values must be present and unique",
        )]
    if summary.get("job_count") != len(rows) or summary.get("completed_jobs") != len(rows):
        return [CheckResult(
            name="structure:recovery_gate_v2",
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
            name="structure:recovery_gate_v2",
            passed=False,
            detail="groups missing or group_count mismatch",
        )]

    expected_keys = {
        (mode, truth_id, noise, config["trials"])
        for mode in config["feature_modes"]
        for truth_id in config["truth_ids"]
        for noise in config["noise_fractions"]
    }
    group_map: dict[tuple[str, str, float, int], dict[str, Any]] = {}
    structure_errors: list[str] = []
    for index, group in enumerate(groups):
        if not isinstance(group, dict):
            structure_errors.append(f"group[{index}] must be an object")
            continue
        try:
            key = (
                str(group["feature_mode"]),
                str(group["truth_id"]),
                float(group["noise_fraction"]),
                int(group["trials"]),
            )
        except (KeyError, TypeError, ValueError):
            structure_errors.append(f"group[{index}] invalid identity")
            continue
        if key in group_map:
            structure_errors.append(f"duplicate group {key}")
        group_map[key] = group
    if set(group_map) != expected_keys:
        missing = len(expected_keys - set(group_map))
        extra = len(set(group_map) - expected_keys)
        structure_errors.append(
            f"group coverage mismatch: missing={missing} extra={extra}"
        )

    rows_by_group: dict[tuple[str, str, float, int], list[dict[str, Any]]] = {}
    for index, row in enumerate(rows):
        try:
            key = (
                str(row["feature_mode"]),
                str(row["truth_id"]),
                float(row["noise_fraction"]),
                int(row["trials"]),
            )
        except (KeyError, TypeError, ValueError):
            structure_errors.append(f"row[{index}] invalid group identity")
            continue
        rows_by_group.setdefault(key, []).append(row)
    if set(rows_by_group) != expected_keys:
        missing = len(expected_keys - set(rows_by_group))
        extra = len(set(rows_by_group) - expected_keys)
        structure_errors.append(
            f"result group coverage mismatch: missing={missing} extra={extra}"
        )

    if structure_errors:
        return [CheckResult(
            name="structure:recovery_gate_v2",
            passed=False,
            detail="; ".join(structure_errors[:12]),
        )]

    mode_metrics = {
        mode: {
            "max_error": 0.0,
            "median_error": 0.0,
            "dispersion": 0.0,
            "boundary_rate": 0.0,
            "failures": [],
            "tafel_failures": 0,
            "trials": 0,
        }
        for mode in config["feature_modes"]
    }
    expected_parameter_set = set(config["parameter_names"])
    for key in sorted(expected_keys):
        mode = key[0]
        group = group_map[key]
        members = rows_by_group[key]
        seeds = []
        for row in members:
            try:
                seeds.append(int(row["seed"]))
            except (KeyError, TypeError, ValueError):
                structure_errors.append(f"{key} has invalid seed")
        if sorted(seeds) != config["seeds"]:
            structure_errors.append(
                f"{key} seeds={sorted(seeds)} expected={config['seeds']}"
            )
        if group.get("seeds") != config["seeds"]:
            structure_errors.append(f"{key} summary seeds mismatch")
        if not isinstance(group.get("all_success"), bool):
            structure_errors.append(f"{key} all_success must be bool")
        parameters = group.get("parameters")
        if not isinstance(parameters, dict) or set(parameters) != expected_parameter_set:
            structure_errors.append(f"{key} parameter set mismatch")
            continue
        if any(set(row.get("free_parameters", [])) != expected_parameter_set for row in members):
            structure_errors.append(f"{key} row free_parameters mismatch")
            continue

        all_success = all(row.get("success") is True for row in members)
        if group.get("all_success") is not all_success:
            structure_errors.append(f"{key} all_success disagrees with rows")
        if config["require_all_studies_success"] and not all_success:
            mode_metrics[mode]["failures"].append(f"{key[1:]}.study_success")

        for name in config["parameter_names"]:
            item = parameters[name]
            if not isinstance(item, dict):
                structure_errors.append(f"{key}.{name} summary must be an object")
                continue
            errors: list[float] = []
            signed_errors: list[float] = []
            boundary_hits: list[bool] = []
            for row in members:
                metrics = row.get("parameter_metrics")
                metric = metrics.get(name) if isinstance(metrics, dict) else None
                if not isinstance(metric, dict):
                    structure_errors.append(f"{key}.{name} row metrics missing")
                    continue
                try:
                    error = float(metric["normalized_bound_error"])
                    truth = float(metric["truth"])
                    estimate = float(metric["estimate"])
                except (KeyError, TypeError, ValueError):
                    structure_errors.append(f"{key}.{name} invalid row metric")
                    continue
                boundary_hit = metric.get("boundary_hit")
                if (
                    not math.isfinite(error)
                    or error < 0.0
                    or not math.isfinite(truth)
                    or not math.isfinite(estimate)
                    or not isinstance(boundary_hit, bool)
                ):
                    structure_errors.append(f"{key}.{name} invalid metric value")
                    continue
                errors.append(error)
                signed_errors.append(
                    -error if estimate < truth else error if estimate > truth else 0.0
                )
                boundary_hits.append(boundary_hit)
            if len(errors) != len(config["seeds"]):
                continue

            median_error = float(statistics.median(errors))
            max_error = max(errors)
            dispersion = max(signed_errors) - min(signed_errors)
            boundary_rate = sum(boundary_hits) / len(boundary_hits)
            expected_values = {
                "median_normalized_bound_error": median_error,
                "max_normalized_bound_error": max_error,
                "boundary_hit_rate": boundary_rate,
            }
            for field, expected in expected_values.items():
                try:
                    actual = float(item[field])
                except (KeyError, TypeError, ValueError):
                    structure_errors.append(f"{key}.{name}.{field} invalid")
                    continue
                if not math.isfinite(actual) or not math.isclose(
                    actual, expected, rel_tol=1e-12, abs_tol=1e-15
                ):
                    structure_errors.append(
                        f"{key}.{name}.{field} disagrees with rows"
                    )

            metrics = mode_metrics[mode]
            metrics["max_error"] = max(metrics["max_error"], max_error)
            metrics["median_error"] = max(metrics["median_error"], median_error)
            metrics["dispersion"] = max(metrics["dispersion"], dispersion)
            metrics["boundary_rate"] = max(metrics["boundary_rate"], boundary_rate)
            if median_error > config["max_median_normalized_bound_error"]:
                metrics["failures"].append(f"{key[1:]}.{name}.median_error")
            if max_error > config["max_normalized_bound_error"]:
                metrics["failures"].append(f"{key[1:]}.{name}.max_error")
            if dispersion > config["max_seed_normalized_bound_dispersion"]:
                metrics["failures"].append(f"{key[1:]}.{name}.dispersion")
            if boundary_rate > config["max_boundary_hit_rate"]:
                metrics["failures"].append(f"{key[1:]}.{name}.boundary_rate")

        for row in members:
            try:
                mode_metrics[mode]["tafel_failures"] += int(
                    row.get("n_tafel_fail", 0)
                )
                mode_metrics[mode]["trials"] += int(row.get("n_trials", row["trials"]))
            except (KeyError, TypeError, ValueError):
                structure_errors.append(f"{key} invalid trial diagnostics")

    if structure_errors:
        return [CheckResult(
            name="structure:recovery_gate_v2",
            passed=False,
            detail="; ".join(structure_errors[:12]),
        )]

    passed_modes = [
        mode for mode in config["feature_modes"] if not mode_metrics[mode]["failures"]
    ]
    eligible_modes = [
        mode
        for mode in passed_modes
        if not config["require_nonlegacy_mode"] or mode != config["legacy_mode"]
    ]
    tie_order = {
        mode: index
        for index, mode in enumerate(
            ["complex_snr", "hybrid", "lockin_only", "legacy"]
        )
    }
    ranked = sorted(
        eligible_modes,
        key=lambda mode: (
            mode_metrics[mode]["max_error"],
            mode_metrics[mode]["median_error"],
            mode_metrics[mode]["dispersion"],
            tie_order.get(mode, len(tie_order)),
            mode,
        ),
    )
    mode_details = []
    for mode in config["feature_modes"]:
        metrics = mode_metrics[mode]
        mode_details.append(
            f"{mode}:{'PASS' if mode in passed_modes else 'FAIL'}"
            f"(max_error={metrics['max_error']:.6g},"
            f"median_error={metrics['median_error']:.6g},"
            f"dispersion={metrics['dispersion']:.6g},"
            f"boundary_rate={metrics['boundary_rate']:.6g},"
            f"tafel_failures={metrics['tafel_failures']}/{metrics['trials']})"
        )
    return [CheckResult(
        name="scientific:recovery_gate_v2",
        passed=bool(ranked),
        detail=(
            f"eligible_modes={','.join(ranked) if ranked else 'none'}; "
            f"selected_mode={ranked[0] if ranked else 'none'}; "
            + "; ".join(mode_details)
        ),
    )]


def _parse_v2_config(
    cfg: dict[str, Any],
) -> tuple[dict[str, Any], str | None]:
    list_fields = (
        "parameter_names",
        "feature_modes",
        "truth_ids",
        "noise_fractions",
        "seeds",
    )
    parsed: dict[str, Any] = {}
    for field in list_fields:
        value = cfg.get(field)
        if not isinstance(value, list) or not value:
            return {}, f"{field} missing or invalid"
        if len(set(map(str, value))) != len(value):
            return {}, f"{field} values must be unique"
        parsed[field] = value
    try:
        parsed["parameter_names"] = [str(value) for value in parsed["parameter_names"]]
        parsed["feature_modes"] = [str(value) for value in parsed["feature_modes"]]
        parsed["truth_ids"] = [str(value) for value in parsed["truth_ids"]]
        parsed["noise_fractions"] = [
            float(value) for value in parsed["noise_fractions"]
        ]
        parsed["seeds"] = sorted(int(value) for value in parsed["seeds"])
        parsed["trials"] = int(cfg["trials"])
    except (KeyError, TypeError, ValueError):
        return {}, "noise_fractions, seeds, and trials must be numeric"
    if (
        any(not math.isfinite(value) for value in parsed["noise_fractions"])
        or parsed["trials"] < 1
    ):
        return {}, "noise_fractions must be finite and trials must be positive"

    frozen_thresholds = {
        "max_boundary_hit_rate": 0.0,
        "max_median_normalized_bound_error": 0.025,
        "max_normalized_bound_error": 0.05,
        "max_seed_normalized_bound_dispersion": 0.05,
    }
    for field, frozen_value in frozen_thresholds.items():
        try:
            value = float(cfg[field])
        except (KeyError, TypeError, ValueError):
            return {}, f"{field} missing or non-numeric"
        if not math.isfinite(value) or not 0.0 <= value <= 1.0:
            return {}, f"{field} must be finite and in [0,1]"
        if not math.isclose(value, frozen_value, rel_tol=0.0, abs_tol=1e-15):
            return {}, f"{field} must equal frozen value {frozen_value}"
        parsed[field] = value
    for field in ("require_all_studies_success", "require_nonlegacy_mode"):
        value = cfg.get(field)
        if not isinstance(value, bool):
            return {}, f"{field} must be bool"
        if not value:
            return {}, f"{field} must be true for gate_version 2"
        parsed[field] = value
    legacy_mode = cfg.get("legacy_mode")
    if not isinstance(legacy_mode, str) or legacy_mode not in parsed["feature_modes"]:
        return {}, "legacy_mode must name one feature_modes entry"
    parsed["legacy_mode"] = legacy_mode
    return parsed, None
