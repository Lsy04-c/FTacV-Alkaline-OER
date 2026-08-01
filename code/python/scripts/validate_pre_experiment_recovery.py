#!/usr/bin/env python3
"""Independent archive validator for pre-experiment A6-v2 recovery."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "code" / "python" / "src"))

from oer_aem.portfolio_recovery import (
    build_portfolio_jobs,
    load_pre_experiment_spec,
    summarize_portfolio_recovery,
    target_identity,
    validate_target_reuse,
)


REQUIRED_FILES = {
    "pre_experiment_recovery_spec.json",
    "protocol_catalog.csv",
    "job_plan.json",
    "target_manifest.json",
    "results.jsonl",
    "portfolio_recovery.csv",
    "summary.json",
    "run_manifest.json",
}


def _reject_constant(name: str) -> None:
    raise ValueError(f"non-standard JSON constant rejected: {name}")


def _load_json(path: Path) -> Any:
    return json.loads(
        path.read_text(encoding="utf-8"),
        parse_constant=_reject_constant,
    )


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    raw = path.read_text(encoding="utf-8")
    if raw and not raw.endswith("\n"):
        raise ValueError("results.jsonl ends with an incomplete line")
    rows = []
    for line_number, line in enumerate(raw.splitlines(), 1):
        if not line.strip():
            raise ValueError(f"blank results.jsonl line {line_number}")
        value = json.loads(line, parse_constant=_reject_constant)
        if not isinstance(value, dict):
            raise ValueError(f"results.jsonl line {line_number} is not an object")
        rows.append(value)
    return rows


def _assert_finite(value: Any, location: str) -> None:
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError(f"non-finite value at {location}")
    if isinstance(value, Mapping):
        for key, item in value.items():
            _assert_finite(item, f"{location}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _assert_finite(item, f"{location}[{index}]")


def _canonical(value: Any) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _verify_run_manifest(archive: Path, manifest: Mapping[str, Any]) -> list[str]:
    errors = []
    files = manifest.get("files")
    if not isinstance(files, list):
        return ["run manifest files must be a list"]
    seen = set()
    for item in files:
        if not isinstance(item, dict) or not isinstance(item.get("path"), str):
            errors.append("run manifest contains an invalid file record")
            continue
        name = item["path"]
        if name in seen or Path(name).name != name:
            errors.append(f"run manifest path invalid or duplicate: {name}")
            continue
        seen.add(name)
        path = archive / name
        if not path.is_file():
            errors.append(f"run manifest file missing: {name}")
            continue
        raw = path.read_bytes()
        if item.get("size") != len(raw):
            errors.append(f"run manifest size mismatch: {name}")
        if item.get("sha256") != hashlib.sha256(raw).hexdigest():
            errors.append(f"run manifest hash mismatch: {name}")
    expected = REQUIRED_FILES - {"run_manifest.json"}
    if not expected <= seen:
        errors.append(f"run manifest coverage missing: {sorted(expected - seen)}")
    return errors


def validate_archive(
    project_root: str | Path,
    task_spec: str | Path,
    archive_dir: str | Path,
) -> dict[str, Any]:
    """Validate raw archive evidence and independently rebuild its gate."""
    root = Path(project_root).resolve()
    spec_path = Path(task_spec)
    if not spec_path.is_absolute():
        spec_path = root / spec_path
    archive = Path(archive_dir).resolve()
    errors: list[str] = []
    missing = sorted(name for name in REQUIRED_FILES if not (archive / name).is_file())
    if missing:
        return {
            "gate": "FAIL",
            "stage": None,
            "stage_status": "FAIL_STRUCTURE",
            "errors": [f"required files missing: {missing}"],
        }
    try:
        spec = load_pre_experiment_spec(spec_path)
        source_spec = _load_json(spec_path)
        frozen_spec = _load_json(archive / "pre_experiment_recovery_spec.json")
        plan = _load_json(archive / "job_plan.json")
        target_manifest = _load_json(archive / "target_manifest.json")
        summary = _load_json(archive / "summary.json")
        run_manifest = _load_json(archive / "run_manifest.json")
        rows = _load_jsonl(archive / "results.jsonl")
        for index, row in enumerate(rows):
            _assert_finite(row, f"results[{index}]")
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        return {
            "gate": "FAIL",
            "stage": None,
            "stage_status": "FAIL_STRUCTURE",
            "errors": [str(exc)],
        }

    if _canonical(source_spec) != _canonical(frozen_spec):
        errors.append("frozen pre-experiment spec differs from source spec")
    errors.extend(_verify_run_manifest(archive, run_manifest))

    stage = plan.get("portfolio_stage")
    if stage not in {"S0", "S1", "S2"} or summary.get("portfolio_stage") != stage:
        errors.append("portfolio stage is missing or inconsistent")
    jobs = plan.get("jobs")
    if not isinstance(jobs, list) or plan.get("job_count") != len(jobs):
        errors.append("job plan jobs missing or job_count mismatch")
        jobs = []
    job_ids = [job.get("job_id") for job in jobs if isinstance(job, dict)]
    row_ids = [row.get("job_id") for row in rows]
    if (
        len(job_ids) != len(set(job_ids))
        or len(row_ids) != len(set(row_ids))
        or job_ids != row_ids
    ):
        errors.append("job/result identity coverage mismatch")
    if summary.get("job_count") != len(rows) or summary.get("completed_jobs") != len(rows):
        errors.append("summary job counts disagree with raw results")

    if stage == "S0" and len(rows) != 3:
        errors.append("S0 must contain exactly three structural jobs")
    if stage == "S1" and len(rows) != 81:
        errors.append("S1 must contain exactly 81 studies")
    if stage in {"S1", "S2"} and any(
        row.get("backend") != "lsoda"
        or row.get("configuration", {}).get("solver_backend") != "lsoda"
        or row.get("trials") != 100
        or row.get("n_trials") != 100
        for row in rows
    ):
        errors.append("formal rows must use LSODA and exactly 100 trials")

    for job, row in zip(jobs, rows):
        if not isinstance(job, dict):
            continue
        if row.get("job_input_hash") != job.get("job_input_hash"):
            errors.append(f"job_input_hash mismatch: {row.get('job_id')}")
        expected_conditions = spec.portfolios.get(str(row.get("portfolio_id")))
        if expected_conditions is None or tuple(row.get("condition_ids", ())) != expected_conditions:
            errors.append(f"portfolio condition mismatch: {row.get('job_id')}")
        for identity in row.get("target_identities", []):
            condition_id = identity.get("condition_id")
            expected_identity = target_identity(
                str(row.get("truth_id")),
                float(row.get("noise_fraction")),
                str(condition_id),
            )
            if any(identity.get(key) != value for key, value in expected_identity.items()):
                errors.append(f"target identity mismatch: {row.get('job_id')}")

    records = target_manifest.get("records")
    if not isinstance(records, list):
        errors.append("target manifest records must be a list")
        records = []
    try:
        unique_targets = validate_target_reuse(records)
    except ValueError as exc:
        errors.append(f"target reuse conflict: {exc}")
        unique_targets = {}
    expected_records = [
        {**record, "job_id": row["job_id"], "portfolio_id": row["portfolio_id"]}
        for row in rows
        for record in row.get("target_records", [])
    ]
    if records != expected_records:
        errors.append("target manifest records disagree with result rows")
    if target_manifest.get("target_record_count") != len(records):
        errors.append("target manifest record count mismatch")
    if target_manifest.get("unique_target_count") != len(unique_targets):
        errors.append("target manifest unique target count mismatch")

    rebuilt = None
    if stage in {"S0", "S1", "S2"}:
        try:
            rebuilt = summarize_portfolio_recovery(rows, spec=spec, stage=stage)
        except (KeyError, TypeError, ValueError) as exc:
            errors.append(f"scientific reconstruction failed: {exc}")
    if rebuilt is not None:
        if summary.get("recovery_summary") != rebuilt:
            errors.append("summary recovery gate disagrees with raw-row reconstruction")
        if summary.get("scientific_gate_passed") != rebuilt["scientific_gate_passed"]:
            errors.append("summary scientific gate disagrees with reconstruction")
        if summary.get("stage_status") != rebuilt["stage_status"]:
            errors.append("summary stage status disagrees with reconstruction")
        if summary.get("eligible_parameter_pairs") != rebuilt["eligible_parameter_pairs"]:
            errors.append("summary eligible pairs disagree with reconstruction")

    stage_status = (
        "FAIL_STRUCTURE"
        if errors
        else rebuilt["stage_status"]
        if rebuilt is not None
        else "FAIL_STRUCTURE"
    )
    return {
        "gate": "FAIL" if errors else "PASS",
        "stage": stage,
        "stage_status": stage_status,
        "scientific_gate_passed": (
            rebuilt["scientific_gate_passed"] if rebuilt is not None else None
        ),
        "eligible_parameter_pairs": (
            rebuilt["eligible_parameter_pairs"] if rebuilt is not None else []
        ),
        "errors": errors,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", type=Path, default=ROOT)
    parser.add_argument("--task-spec", type=Path, required=True)
    parser.add_argument("--archive", type=Path, required=True)
    args = parser.parse_args()
    result = validate_archive(args.project_root, args.task_spec, args.archive)
    print(json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False))
    raise SystemExit(0 if result["gate"] == "PASS" else 1)


if __name__ == "__main__":
    main()
