"""Independent validator for the locked A6 Sobol confirmation archive."""

from __future__ import annotations

import hashlib
import json
import math
import statistics
from pathlib import Path
from typing import Any, Mapping, Sequence

from oer_wf.models import CheckResult


FROZEN_CONFIG = {
    "gate_version": 1,
    "recovery_gate_version": 2,
    "optimizer": "sobol_pattern",
    "parameter_pairs": [
        ["k0_2", "k0_3"],
        ["k0_2", "G_O"],
        ["k0_3", "G_O"],
    ],
    "truth_ids": ["center", "mixed_a", "mixed_b"],
    "noise_fractions": [0.0, 0.001495726085983469],
    "seeds": [7, 17, 27],
    "optimization_budget": 100,
    "development_identity": ["center", 0.0, 7],
    "development_evidence_sha256": (
        "116099242f034c133f4895d068429673f0a12be611b76ea00cc3ebf415a83b8a"
    ),
    "development_source_results_sha256": (
        "e93ccab24c4a91d9d4d9a2b8e014826b6b1a07b7d0891c6e7dd944b78e17b432"
    ),
    "max_median_normalized_bound_error": 0.025,
    "max_normalized_bound_error": 0.05,
    "max_seed_normalized_bound_dispersion": 0.05,
    "max_boundary_hit_rate": 0.0,
}


def _reject_nonfinite(value: Any, location: str) -> None:
    if isinstance(value, float) and not math.isfinite(value):
        raise FloatingPointError(f"non-finite value at {location}")
    if isinstance(value, dict):
        for key, child in value.items():
            _reject_nonfinite(child, f"{location}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _reject_nonfinite(child, f"{location}[{index}]")


def _load_json(path: Path) -> Any:
    value = json.loads(
        path.read_text(encoding="utf-8"),
        parse_constant=lambda name: (_ for _ in ()).throw(
            FloatingPointError(f"non-standard JSON constant: {name}")
        ),
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


def _identity(row: Mapping[str, Any]) -> tuple[Any, ...]:
    return (
        tuple(row["free_parameters"]),
        str(row["truth_id"]),
        float(row["noise_fraction"]),
        int(row["seed"]),
    )


def _expected_confirmation(config: Mapping[str, Any]):
    development = tuple(config["development_identity"])
    return {
        (tuple(pair), truth, float(noise), int(seed))
        for pair in config["parameter_pairs"]
        for truth in config["truth_ids"]
        for noise in config["noise_fractions"]
        for seed in config["seeds"]
        if (truth, float(noise), int(seed)) != development
    }


def _recompute_gate(
    development: Sequence[Mapping[str, Any]],
    confirmation: Sequence[Mapping[str, Any]],
    config: Mapping[str, Any],
) -> dict[str, Any]:
    rows = [*development, *confirmation]
    pair_results: dict[str, dict[str, Any]] = {}
    eligible_pairs = []
    for raw_pair in config["parameter_pairs"]:
        pair = tuple(raw_pair)
        pair_rows = [
            row
            for row in rows
            if tuple(row["free_parameters"]) == pair
        ]
        failures = []
        aggregate = {
            "max_error": 0.0,
            "median_error": 0.0,
            "dispersion": 0.0,
            "boundary_rate": 0.0,
        }
        groups: dict[str, Any] = {}
        for truth in config["truth_ids"]:
            for noise in map(float, config["noise_fractions"]):
                members = [
                    row
                    for row in pair_rows
                    if row["truth_id"] == truth
                    and float(row["noise_fraction"]) == noise
                ]
                seeds = sorted(int(row["seed"]) for row in members)
                if seeds != list(config["seeds"]):
                    raise ValueError(
                        f"{pair}/{truth}/{noise:g} seed matrix mismatch"
                    )
                parameter_metrics = {}
                for name in pair:
                    errors = []
                    signed_errors = []
                    boundary_hits = []
                    for row in members:
                        metric = row["parameter_metrics"][name]
                        error = float(metric["normalized_bound_error"])
                        truth_value = float(metric["truth"])
                        estimate = float(metric["estimate"])
                        boundary = metric["boundary_hit"]
                        if (
                            error < 0.0
                            or not math.isfinite(error)
                            or not math.isfinite(truth_value)
                            or not math.isfinite(estimate)
                            or not isinstance(boundary, bool)
                        ):
                            raise ValueError("invalid parameter metric")
                        errors.append(error)
                        signed_errors.append(
                            -error
                            if estimate < truth_value
                            else error
                            if estimate > truth_value
                            else 0.0
                        )
                        boundary_hits.append(boundary)
                    median_error = float(statistics.median(errors))
                    max_error = max(errors)
                    dispersion = max(signed_errors) - min(signed_errors)
                    boundary_rate = sum(boundary_hits) / len(boundary_hits)
                    parameter_metrics[name] = {
                        "median_normalized_bound_error": median_error,
                        "max_normalized_bound_error": max_error,
                        "seed_normalized_bound_dispersion": dispersion,
                        "boundary_hit_rate": boundary_rate,
                    }
                    aggregate["max_error"] = max(
                        aggregate["max_error"], max_error
                    )
                    aggregate["median_error"] = max(
                        aggregate["median_error"], median_error
                    )
                    aggregate["dispersion"] = max(
                        aggregate["dispersion"], dispersion
                    )
                    aggregate["boundary_rate"] = max(
                        aggregate["boundary_rate"], boundary_rate
                    )
                    prefix = f"{truth}/noise-{noise:g}/{name}"
                    if (
                        median_error
                        > config["max_median_normalized_bound_error"]
                    ):
                        failures.append(f"{prefix}/median_error")
                    if max_error > config["max_normalized_bound_error"]:
                        failures.append(f"{prefix}/max_error")
                    if (
                        dispersion
                        > config[
                            "max_seed_normalized_bound_dispersion"
                        ]
                    ):
                        failures.append(f"{prefix}/dispersion")
                    if boundary_rate > config["max_boundary_hit_rate"]:
                        failures.append(f"{prefix}/boundary_rate")
                groups[f"{truth}__noise-{noise:g}"] = {
                    "seeds": list(config["seeds"]),
                    "parameters": parameter_metrics,
                }
        key = ",".join(pair)
        passed = not failures
        pair_results[key] = {
            "passed": passed,
            **aggregate,
            "failures": failures,
            "groups": groups,
        }
        if passed:
            eligible_pairs.append(list(pair))
    return {
        "gate_version": 2,
        "optimizer": config["optimizer"],
        "thresholds": {
            "max_median_normalized_bound_error": config[
                "max_median_normalized_bound_error"
            ],
            "max_normalized_bound_error": config[
                "max_normalized_bound_error"
            ],
            "max_seed_normalized_bound_dispersion": config[
                "max_seed_normalized_bound_dispersion"
            ],
            "max_boundary_hit_rate": config[
                "max_boundary_hit_rate"
            ],
        },
        "development_studies": 3,
        "confirmation_studies": 51,
        "combined_studies": 54,
        "pair_results": pair_results,
        "eligible_pairs": eligible_pairs,
        "scientific_gate_passed": bool(eligible_pairs),
        "next_action": (
            "PLAN_LSODA_CONFIRMATION" if eligible_pairs else "STOP"
        ),
    }


def _validate(
    archive: Path,
    config: Mapping[str, Any],
) -> tuple[list[str], dict[str, Any] | None]:
    plan = _load_json(archive / "benchmark_plan.json")
    development_evidence = _load_json(
        archive / "development_evidence.snapshot.json"
    )
    confirmation = _load_jsonl(archive / "results.jsonl")
    evaluations = _load_jsonl(archive / "evaluations.jsonl")
    summary = _load_json(archive / "summary.json")
    reported_gate = _load_json(archive / "confirmation_gate.json")
    errors = []

    snapshot_bytes = (
        archive / "development_evidence.snapshot.json"
    ).read_bytes()
    snapshot_hash = hashlib.sha256(snapshot_bytes).hexdigest()
    if snapshot_hash != config["development_evidence_sha256"]:
        errors.append("development evidence SHA-256 mismatch")
    if development_evidence.get("source_results_sha256") != config[
        "development_source_results_sha256"
    ]:
        errors.append("development source results SHA-256 mismatch")
    development = development_evidence.get("development_rows")
    if not isinstance(development, list):
        return ["development_rows missing"], None

    expected_development = {
        (
            tuple(pair),
            str(config["development_identity"][0]),
            float(config["development_identity"][1]),
            int(config["development_identity"][2]),
        )
        for pair in config["parameter_pairs"]
    }
    if len(development) != 3 or {
        _identity(row) for row in development
    } != expected_development:
        errors.append("development three-study matrix mismatch")
    for row in development:
        if (
            row.get("optimizer") != config["optimizer"]
            or row.get("feature_mode") != "hybrid"
            or row.get("success") is not True
            or row.get("optimization_calls")
            != config["optimization_budget"]
            or row.get("diagnostic_truth_calls") != 1
            or row.get("truth_diagnostic_sequence") != 101
            or row.get("n_ode_fail") != 0
            or row.get("parameter_metrics", {}).get("boundary_hits") != []
        ):
            errors.append(
                f"development row contract mismatch: {row.get('job_id')}"
            )

    expected_confirmation = _expected_confirmation(config)
    actual_confirmation = set()
    job_ids = set()
    for index, row in enumerate(confirmation):
        try:
            identity = _identity(row)
            job_id = str(row["job_id"])
        except (KeyError, TypeError, ValueError) as exc:
            errors.append(f"confirmation[{index}] identity invalid: {exc}")
            continue
        if identity in actual_confirmation or job_id in job_ids:
            errors.append("duplicate confirmation identity or job_id")
        actual_confirmation.add(identity)
        job_ids.add(job_id)
        if row.get("optimizer") != config["optimizer"]:
            errors.append(f"{job_id} optimizer mismatch")
        if row.get("feature_mode") != "hybrid":
            errors.append(f"{job_id} feature mode mismatch")
        if row.get("success") is not True:
            errors.append(f"{job_id} failed")
        if row.get("optimization_calls") != config[
            "optimization_budget"
        ]:
            errors.append(f"{job_id} optimization call count drift")
        if row.get("diagnostic_truth_calls") != 1:
            errors.append(f"{job_id} diagnostic call count drift")
        if row.get("truth_diagnostic_sequence") != 101:
            errors.append(f"{job_id} truth diagnostic order invalid")
        if row.get("n_ode_fail") != 0:
            errors.append(f"{job_id} ODE failures")
        if row.get("parameter_metrics", {}).get("boundary_hits") != []:
            errors.append(f"{job_id} boundary hits")
    if (
        len(confirmation) != 51
        or actual_confirmation != expected_confirmation
    ):
        errors.append("confirmation 51-study matrix mismatch")

    traces = {job_id: [] for job_id in job_ids}
    for index, row in enumerate(evaluations):
        job_id = row.get("job_id")
        if job_id not in traces:
            errors.append(f"evaluation[{index}] unknown job_id")
            continue
        traces[job_id].append(row)
    budget = int(config["optimization_budget"])
    for job_id, rows in traces.items():
        if len(rows) != budget:
            errors.append(f"{job_id} evaluation count mismatch")
            continue
        if [row.get("sequence") for row in rows] != list(
            range(1, budget + 1)
        ):
            errors.append(f"{job_id} evaluation sequence mismatch")
        if any(row.get("kind") != "optimization" for row in rows):
            errors.append(f"{job_id} trace kind mismatch")

    plan_development = plan.get("development_evidence")
    if not isinstance(plan_development, dict):
        errors.append("plan development evidence missing")
    else:
        if plan_development.get("sha256") != snapshot_hash:
            errors.append("plan development evidence hash mismatch")
        if plan_development.get("source_results_sha256") != config[
            "development_source_results_sha256"
        ]:
            errors.append("plan source results hash mismatch")
    if (
        plan.get("phase") != "confirmation"
        or plan.get("backend") != "cn"
        or plan.get("budget") != budget
        or plan.get("is_smoke") is not False
    ):
        errors.append("benchmark plan contract mismatch")
    plan_jobs = plan.get("jobs")
    if not isinstance(plan_jobs, list) or len(plan_jobs) != 51:
        errors.append("benchmark plan job count mismatch")
    else:
        try:
            plan_identities = {_identity(row) for row in plan_jobs}
            plan_job_ids = {str(row["job_id"]) for row in plan_jobs}
        except (KeyError, TypeError, ValueError):
            errors.append("benchmark plan job identity invalid")
        else:
            if (
                plan_identities != expected_confirmation
                or plan_job_ids != job_ids
            ):
                errors.append("benchmark plan job matrix mismatch")

    if (
        summary.get("job_count") != 51
        or summary.get("completed_jobs") != 51
        or summary.get("optimization_calls") != 5100
        or summary.get("diagnostic_truth_calls") != 51
        or summary.get("n_ode_fail") != 0
        or summary.get("execution_passed") is not True
        or summary.get("is_smoke") is not False
    ):
        errors.append("summary contract mismatch")

    recomputed = None
    if not errors:
        recomputed = _recompute_gate(
            development,
            confirmation,
            config,
        )
        if reported_gate != recomputed:
            errors.append("confirmation gate differs from recomputation")
        if summary.get("scientific_gate_passed") != recomputed[
            "scientific_gate_passed"
        ]:
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
                name="structure:optimizer_confirmation_gate_config",
                passed=False,
                detail="validator config differs from frozen confirmation gate",
            )
        ]
    required = (
        "benchmark_plan.json",
        "development_evidence.snapshot.json",
        "results.jsonl",
        "evaluations.jsonl",
        "summary.json",
        "confirmation_gate.json",
    )
    missing = [name for name in required if not (archive_dir / name).is_file()]
    if missing:
        return [
            CheckResult(
                name="structure:optimizer_confirmation_gate",
                passed=False,
                detail=f"missing inputs: {missing}",
            )
        ]
    try:
        errors, gate = _validate(archive_dir, config)
    except FloatingPointError as exc:
        return [
            CheckResult(
                name="numerical:optimizer_confirmation_gate",
                passed=False,
                detail=str(exc),
            )
        ]
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        return [
            CheckResult(
                name="structure:optimizer_confirmation_gate",
                passed=False,
                detail=str(exc),
            )
        ]
    if errors:
        return [
            CheckResult(
                name="structure:optimizer_confirmation_gate",
                passed=False,
                detail="; ".join(errors[:20]),
            )
        ]
    assert gate is not None
    eligible = [
        ",".join(pair) for pair in gate["eligible_pairs"]
    ]
    return [
        CheckResult(
            name="structure:optimizer_confirmation_gate",
            passed=True,
            detail="51 confirmation + 3 development studies verified",
        ),
        CheckResult(
            name="scientific:optimizer_confirmation_gate",
            passed=bool(eligible),
            detail=(
                f"eligible_pairs={';'.join(eligible)}"
                if eligible
                else "eligible_pairs=none"
            ),
        ),
    ]
