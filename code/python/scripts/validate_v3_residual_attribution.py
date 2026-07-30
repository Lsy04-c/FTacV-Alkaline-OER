#!/usr/bin/env python3
"""Independently validate a V3 residual-attribution archive."""

from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
import subprocess
import sys
from typing import Any, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "code" / "python"))
sys.path.insert(0, str(ROOT / "code" / "python" / "src"))

import numpy as np

from oer_aem.residual_attribution import (
    summarize_candidate_residuals,
    summarize_ensemble,
)
from scripts.run_conditional_reachability import build_targets
from scripts.run_v3_residual_attribution import (
    _attribution_evidence,
    _canonical_json,
    _parameter_associations,
    _read_json,
    _read_jsonl,
    _sha256_file,
    _sha256_json,
    _stress_directions,
    build_job_plan,
    load_spec,
    load_v2_inputs,
    run_one_job,
)


REQUIRED_FILES = {
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


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def compare_selection(
    actual: Mapping[str, Any],
    expected: Mapping[str, Any],
) -> None:
    """Compare discrete selection exactly and derived floats within 1 ULP."""
    if set(actual) != set(expected):
        raise ValueError("selection dataset mismatch")
    for dataset_id in sorted(expected):
        actual_rows = actual[dataset_id]
        expected_rows = expected[dataset_id]
        if not isinstance(actual_rows, list) or not isinstance(
            expected_rows, list
        ):
            raise ValueError(f"selection rows must be lists: {dataset_id}")
        if len(actual_rows) != len(expected_rows):
            raise ValueError(f"selection length mismatch: {dataset_id}")
        for index, (left, right) in enumerate(
            zip(actual_rows, expected_rows)
        ):
            for key in ("candidate_id", "selection_rank"):
                if left.get(key) != right.get(key):
                    raise ValueError(
                        f"selection {key} mismatch: {dataset_id}/{index}"
                    )
            if not np.allclose(
                np.asarray(left.get("unit_params"), dtype=float),
                np.asarray(right.get("unit_params"), dtype=float),
                rtol=0.0,
                atol=1e-15,
            ):
                raise ValueError(
                    f"selection unit_params mismatch: {dataset_id}/{index}"
                )
            for key in ("score", "selection_min_distance"):
                left_value = left.get(key)
                right_value = right.get(key)
                if left_value is None or right_value is None:
                    if left_value is not right_value:
                        raise ValueError(
                            f"selection {key} mismatch: {dataset_id}/{index}"
                        )
                elif not math.isclose(
                    float(left_value),
                    float(right_value),
                    rel_tol=1e-15,
                    abs_tol=1e-15,
                ):
                    raise ValueError(
                        f"selection {key} mismatch: {dataset_id}/{index}"
                    )


def align_job_selection_evidence(
    jobs: Sequence[Mapping[str, Any]],
    validated_selection: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Rehash jobs with the already validated platform-local distance value."""
    distances = {
        (str(dataset_id), int(row["candidate_id"])): row.get(
            "selection_min_distance"
        )
        for dataset_id, rows in validated_selection.items()
        for row in rows
    }
    aligned: list[dict[str, Any]] = []
    for source in jobs:
        row = dict(source)
        key = (str(row["dataset_id"]), int(row["candidate_id"]))
        if key not in distances:
            raise ValueError(f"selection evidence missing for job: {row['job_id']}")
        row["selection_min_distance"] = distances[key]
        payload = {
            name: value
            for name, value in row.items()
            if name != "job_input_hash"
        }
        row["job_input_hash"] = _sha256_json(payload)
        aligned.append(row)
    return aligned


def _assert_close(actual: Any, expected: Any, name: str) -> None:
    if expected is None:
        if actual is not None and actual != "":
            raise ValueError(f"{name} mismatch")
    elif isinstance(expected, bool):
        normalized = actual
        if isinstance(actual, str):
            normalized = actual.lower() == "true"
        if normalized is not expected:
            raise ValueError(f"{name} mismatch")
    elif isinstance(expected, (int, float)) and not isinstance(expected, bool):
        if not math.isclose(
            float(actual),
            float(expected),
            rel_tol=1e-10,
            abs_tol=1e-12,
        ):
            raise ValueError(f"{name} mismatch")
    elif str(actual) != str(expected):
        raise ValueError(f"{name} mismatch")


def validate_residual_row(
    row: Mapping[str, Any],
    *,
    harmonics: Sequence[int],
    grid_size: int,
) -> None:
    """Validate one successful residual row without trusting summaries."""
    if row.get("success") is not True:
        raise ValueError(f"V3 job is not successful: {row.get('job_id')}")
    grid = np.asarray(row["e_grid"], dtype=float)
    if grid.shape != (grid_size,) or not np.all(np.isfinite(grid)):
        raise ValueError("invalid V3 feature grid")
    if np.any(np.diff(grid) <= 0.0):
        raise ValueError("V3 feature grid is not strictly increasing")
    residuals = row["residuals"]
    dc = np.asarray(residuals["dc"], dtype=float)
    valid = np.asarray(residuals["lockin_valid_mask"], dtype=bool)
    if dc.shape != (grid_size,) or valid.shape != (grid_size,):
        raise ValueError("V3 residual grid shape mismatch")
    if not np.all(np.isfinite(dc)):
        raise ValueError("non-finite DC residual")
    for harmonic in harmonics:
        for prefix in ("global_amplitude", "global_phase"):
            name = f"{prefix}_h{harmonic}"
            values = np.asarray(residuals[name], dtype=float)
            if values.shape != (1,) or not np.all(np.isfinite(values)):
                raise ValueError(f"invalid {name}")
            if "phase" in name and np.any(np.abs(values) > np.pi + 1e-12):
                raise ValueError(f"phase outside wrapped range: {name}")
        for prefix in ("lockin_amplitude", "lockin_phase"):
            name = f"{prefix}_h{harmonic}"
            values = np.asarray(residuals[name], dtype=float)
            if values.shape != (grid_size,) or not np.all(np.isfinite(values)):
                raise ValueError(f"invalid {name}")
            if "phase" in name and np.any(
                np.abs(values[valid]) > np.pi + 1e-12
            ):
                raise ValueError(f"phase outside wrapped range: {name}")


def _compare_rows(
    actual: Sequence[Mapping[str, Any]],
    expected: Sequence[Mapping[str, Any]],
    *,
    keys: Sequence[str],
    label: str,
) -> None:
    if len(actual) != len(expected):
        raise ValueError(f"{label} row count mismatch")
    for index, (left, right) in enumerate(zip(actual, expected, strict=True)):
        for key in keys:
            _assert_close(
                left.get(key),
                right.get(key),
                f"{label}[{index}].{key}",
            )


def rerun_nearest_candidates(
    root: Path,
    spec: Mapping[str, Any],
    inputs: Mapping[str, Any],
    archived_rows: Sequence[Mapping[str, Any]],
    jobs: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Rerun one nearest candidate per dataset under the frozen environment."""
    targets, configs, _ = build_targets(inputs["v2_spec"])
    archived = {str(row["job_id"]): row for row in archived_rows}
    evidence = []
    for job in jobs:
        if int(job["selection_rank"]) != 0:
            continue
        dataset_id = str(job["dataset_id"])
        rerun = run_one_job(
            {
                "job": job,
                "config": configs[dataset_id],
                "target": targets[dataset_id],
                "harmonics": spec["fit_harmonics"],
            }
        )
        if rerun.get("success") is not True:
            raise ValueError(f"rerun failed for {dataset_id}")
        original = archived[str(job["job_id"])]
        for name, values in original["residuals"].items():
            if name == "lockin_valid_mask":
                if list(values) != list(rerun["residuals"][name]):
                    raise ValueError(f"rerun mask mismatch for {dataset_id}")
                continue
            if not np.allclose(
                np.asarray(values, dtype=float),
                np.asarray(rerun["residuals"][name], dtype=float),
                rtol=1e-8,
                atol=1e-8,
            ):
                raise ValueError(
                    f"rerun residual mismatch for {dataset_id}/{name}"
                )
        evidence.append(
            {
                "dataset_id": dataset_id,
                "candidate_id": int(job["candidate_id"]),
                "backend_used": rerun["solver_backend_used"],
                "steady_state_elapsed_s": rerun["steady_state_elapsed_s"],
                "steady_state_rhs_norm": rerun["steady_state_rhs_norm"],
            }
        )
    if len(evidence) != 4:
        raise ValueError("formal rerun must contain four datasets")
    return evidence


def validate_archive(
    root: str | Path,
    spec_path: str | Path,
    archive: str | Path,
    *,
    rerun_nearest: bool = False,
) -> dict[str, Any]:
    """Validate selection, residuals, scalar evidence and provenance."""
    root = Path(root).resolve()
    archive = Path(archive).resolve()
    errors: list[str] = []
    rerun_evidence: list[dict[str, Any]] = []
    try:
        if not Path(spec_path).is_file():
            raise ValueError(f"missing task spec: {spec_path}")
        missing = sorted(name for name in REQUIRED_FILES if not (archive / name).is_file())
        if missing:
            raise ValueError(f"missing files: {', '.join(missing)}")
        spec = load_spec(spec_path)
        frozen = _read_json(archive / "v3_task_spec.json")
        for key, value in spec.items():
            if frozen.get(key) != value:
                raise ValueError(f"frozen V3 spec mismatch at {key}")
        run_mode = frozen.get("run_mode")
        if run_mode not in {"smoke", "formal"}:
            raise ValueError("invalid V3 run_mode")
        if run_mode == "formal":
            commit = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=root,
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
            if commit != frozen["source_state"]["source_commit"]:
                raise ValueError("validator commit does not match V3 archive")
            if frozen["source_state"]["dirty"]:
                raise ValueError("formal V3 source state is dirty")

        inputs = load_v2_inputs(root, spec)
        jobs, expected_selection = build_job_plan(
            inputs,
            spec,
            smoke=run_mode == "smoke",
        )
        actual_selection = _read_json(archive / "selection.json")
        compare_selection(actual_selection, expected_selection)
        jobs = align_job_selection_evidence(jobs, actual_selection)

        manifest = _read_json(archive / "run_manifest.json")
        if manifest["v3_task_spec_hash"] != _sha256_json(spec):
            raise ValueError("V3 task spec hash mismatch")
        if manifest["v2_input_sha256"] != spec["v2_input_sha256"]:
            raise ValueError("V2 input manifest mismatch")
        for name, digest in manifest["artifact_sha256"].items():
            if digest != _sha256_file(archive / name):
                raise ValueError(f"artifact hash mismatch: {name}")

        result_rows = _read_jsonl(archive / "residual_curves.jsonl")
        expected = {str(job["job_id"]): job for job in jobs}
        if [row.get("job_id") for row in result_rows] != [
            job["job_id"] for job in jobs
        ]:
            raise ValueError("V3 job order or membership mismatch")
        candidate_rows = []
        for row in result_rows:
            job = expected[str(row["job_id"])]
            if row.get("job_input_hash") != job["job_input_hash"]:
                raise ValueError(f"V3 job hash mismatch: {row['job_id']}")
            validate_residual_row(
                row,
                harmonics=spec["fit_harmonics"],
                grid_size=int(spec["feature_grid_size"]),
            )
            rebuilt = summarize_candidate_residuals(
                row["residuals"],
                dataset_id=str(row["dataset_id"]),
                candidate_id=int(row["candidate_id"]),
            )
            if _canonical_json(rebuilt) != _canonical_json(row["candidate_summary"]):
                raise ValueError(
                    f"candidate summary mismatch: {row['job_id']}"
                )
            candidate_rows.extend(rebuilt)

        ensemble_size = (
            int(spec["smoke_ensemble_size"])
            if run_mode == "smoke"
            else int(spec["ensemble_size"])
        )
        rebuilt_matrix = []
        for dataset_id in spec["datasets"]:
            rebuilt_matrix.extend(
                summarize_ensemble(
                    [
                        row
                        for row in candidate_rows
                        if row["dataset_id"] == dataset_id
                    ],
                    nearest_candidate_id=int(
                        expected_selection[dataset_id][0]["candidate_id"]
                    ),
                    ensemble_size=ensemble_size,
                )
            )
        actual_matrix = _read_csv(archive / "residual_matrix.csv")
        _compare_rows(
            actual_matrix,
            rebuilt_matrix,
            keys=list(rebuilt_matrix[0]),
            label="residual_matrix",
        )

        associations = _parameter_associations(inputs, spec["datasets"])
        actual_associations = _read_csv(
            archive / "parameter_associations.csv"
        )
        _compare_rows(
            actual_associations,
            associations,
            keys=list(associations[0]),
            label="parameter_associations",
        )
        stress = _stress_directions(inputs, spec["datasets"])
        actual_stress = _read_csv(archive / "stress_directions.csv")
        _compare_rows(
            actual_stress,
            stress,
            keys=list(stress[0]),
            label="stress_directions",
        )
        evidence = _attribution_evidence(
            rebuilt_matrix,
            stress,
            spec["datasets"],
        )
        actual_evidence = _read_csv(archive / "attribution_evidence.csv")
        _compare_rows(
            actual_evidence,
            evidence,
            keys=list(evidence[0]),
            label="attribution_evidence",
        )
        categories = {
            (row["dataset_id"], row["category"]) for row in evidence
        }
        if len(categories) != 20:
            raise ValueError("V3 evidence must contain five categories per dataset")

        summary = _read_json(archive / "summary.json")
        if summary["job_count"] != len(jobs) or summary["success_count"] != len(jobs):
            raise ValueError("V3 summary job count mismatch")
        if rerun_nearest:
            rerun_evidence = rerun_nearest_candidates(
                root,
                spec,
                inputs,
                result_rows,
                jobs,
            )
    except (
        KeyError,
        TypeError,
        ValueError,
        OSError,
        json.JSONDecodeError,
    ) as exc:
        errors.append(str(exc))

    gate = "PASS" if not errors else "FAIL_STRUCTURE"
    result = {
        "gate": gate,
        "errors": errors,
        "rerun_nearest": bool(rerun_nearest),
        "rerun_evidence": rerun_evidence,
    }
    return result


def format_acceptance(result: Mapping[str, Any]) -> str:
    """Format a validator result without mutating its scientific archive."""
    gate = str(result.get("gate"))
    rerun_nearest = bool(result.get("rerun_nearest"))
    rerun_evidence = list(result.get("rerun_evidence") or [])
    errors = list(result.get("errors") or [])
    lines = [
        "# V3 Residual Attribution Acceptance",
        "",
        f"- Gate: `{gate}`",
        f"- Rerun nearest: `{str(rerun_nearest).lower()}`",
    ]
    if rerun_evidence:
        lines.extend(
            [
                "",
                "## Rerun Evidence",
                *[
                    (
                        f"- {row['dataset_id']}: candidate "
                        f"{row['candidate_id']}, {row['backend_used']}, "
                        f"steady state {row['steady_state_elapsed_s']} s, "
                        f"RHS {row['steady_state_rhs_norm']:.6g}"
                    )
                    for row in rerun_evidence
                ],
            ]
        )
    if errors:
        lines.extend(["", "## Errors", *[f"- {item}" for item in errors]])
    return "\n".join(lines) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--task-spec", type=Path, required=True)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--rerun-nearest", action="store_true")
    parser.add_argument("--acceptance-output", type=Path)
    args = parser.parse_args(argv)
    result = validate_archive(
        args.root,
        args.task_spec,
        args.archive,
        rerun_nearest=args.rerun_nearest,
    )
    if args.acceptance_output is not None:
        args.acceptance_output.parent.mkdir(parents=True, exist_ok=True)
        args.acceptance_output.write_text(
            format_acceptance(result),
            encoding="utf-8",
        )
    print(json.dumps(result, indent=2))
    return 0 if result["gate"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
