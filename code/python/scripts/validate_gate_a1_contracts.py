#!/usr/bin/env python3
"""Independently validate a Gate A1 experimental-contract archive."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import sys
from typing import Any

import numpy as np


EXPECTED_IDS = {"FT2", "FT3", "FT4", "FT8"}
ACCEPTED_SOURCES = {
    "file_observed",
    "derived",
    "externally_declared",
}
REQUIRED_METADATA = {
    "potential_unit",
    "potential_reference",
    "current_unit",
    "time_unit",
    "frequency_hz",
    "amplitude_v",
    "scan_rate_v_s",
    "scan_direction",
    "continuous_forward_scan",
    "instrument_preprocessing",
}
THRESHOLDS = {
    "expected_rows": 65536,
    "max_timestamp_residual_samples": 1e-2,
    "max_gap_ratio": 1.05,
    "min_points_per_cycle": 64.0,
    "min_complete_cycles": 20,
    "max_frequency_relative_error": 1e-3,
    "max_scan_rate_relative_error": 5e-4,
    "max_amplitude_relative_error": 5e-3,
}
EXIT_CODES = {
    "PASS": 0,
    "FAIL_METADATA": 2,
    "FAIL_NUMERICAL": 3,
    "FAIL_STRUCTURE": 4,
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


def _read_raw(path: Path) -> tuple[np.ndarray, dict[str, Any]]:
    raw = path.read_bytes()
    if not raw or not raw.strip():
        raise ValueError("experimental file must not be empty")
    rows = []
    for line_number, line in enumerate(
        raw.decode("utf-8").splitlines(), start=1
    ):
        fields = line.split()
        if len(fields) != 3:
            raise ValueError(
                f"line {line_number} must contain exactly three columns"
            )
        try:
            rows.append([float(field) for field in fields])
        except ValueError as exc:
            raise ValueError(
                f"line {line_number} must be numeric"
            ) from exc
    values = np.asarray(rows, dtype=float)
    if not np.all(np.isfinite(values)):
        raise FloatingPointError("experimental values must be finite")
    if np.any(np.diff(values[:, 2]) <= 0):
        raise FloatingPointError("time must be strictly increasing")
    return values, {
        "sha256": hashlib.sha256(raw).hexdigest(),
        "byte_count": len(raw),
        "n_rows": int(values.shape[0]),
        "n_columns": int(values.shape[1]),
    }


def _diagnostics(values: np.ndarray) -> dict[str, float | int]:
    potential = values[:, 0]
    time = values[:, 2]
    delta = np.diff(time)
    duration = float(time[-1] - time[0])
    nominal_delta = duration / (len(time) - 1)
    median_delta = float(np.median(delta))
    rate = 1.0 / nominal_delta
    relative_time = time - time[0]
    nominal_time = np.arange(len(time), dtype=float) * nominal_delta

    ramp_matrix = np.column_stack(
        [relative_time, np.ones_like(relative_time)]
    )
    initial_slope, initial_intercept = np.linalg.lstsq(
        ramp_matrix, potential, rcond=None
    )[0]
    residual = potential - (
        float(initial_slope) * relative_time + float(initial_intercept)
    )
    amplitude_spectrum = np.abs(np.fft.rfft(residual))
    frequency_axis = np.fft.rfftfreq(len(time), nominal_delta)
    peak = int(np.argmax(amplitude_spectrum[1:]) + 1)
    frequency = float(frequency_axis[peak])
    phase = 2.0 * np.pi * frequency * relative_time
    joint_matrix = np.column_stack(
        [
            relative_time,
            np.ones_like(relative_time),
            np.sin(phase),
            np.cos(phase),
        ]
    )
    coefficients = np.linalg.lstsq(
        joint_matrix, potential, rcond=None
    )[0]
    scan_rate = float(coefficients[0])
    amplitude = float(np.hypot(coefficients[2], coefficients[3]))
    cycle_count = duration * frequency
    result = {
        "time_start": float(time[0]),
        "time_end": float(time[-1]),
        "duration_s": duration,
        "dt_min_s": float(np.min(delta)),
        "dt_median_s": median_delta,
        "dt_nominal_s": float(nominal_delta),
        "dt_max_s": float(np.max(delta)),
        "sampling_rate_hz": float(rate),
        "max_relative_jitter": float(
            np.max(np.abs(delta - median_delta)) / median_delta
        ),
        "max_timestamp_residual_samples": float(
            np.max(np.abs(relative_time - nominal_time)) / nominal_delta
        ),
        "max_gap_ratio": float(np.max(delta) / nominal_delta),
        "frequency_hz": frequency,
        "scan_rate_v_s": scan_rate,
        "amplitude_v": amplitude,
        "points_per_cycle": float(rate / frequency),
        "complete_cycles": int(np.floor(cycle_count)),
        "cycle_remainder": float(
            cycle_count - np.floor(cycle_count)
        ),
    }
    _reject_nonfinite(result, "diagnostics")
    return result


def _relative_error(observed: float, declared: float) -> float:
    return abs(observed - declared) / max(abs(declared), 1e-30)


def _recompute_dataset(
    project_root: Path,
    item: dict[str, Any],
) -> dict[str, Any]:
    structure_errors: list[str] = []
    numerical_errors: list[str] = []
    metadata_errors: list[str] = []
    relative_path = Path(str(item.get("path", "")))
    if relative_path.is_absolute() or ".." in relative_path.parts:
        structure_errors.append("dataset path must be project-relative")
    values = None
    facts: dict[str, Any] = {}
    try:
        values, facts = _read_raw(project_root / relative_path)
    except FloatingPointError as exc:
        numerical_errors.append(str(exc))
    except (OSError, UnicodeError, ValueError) as exc:
        structure_errors.append(str(exc))

    if facts:
        expected = {
            "sha256": str(item.get("sha256", "")),
            "byte_count": int(item.get("byte_count", -1)),
            "n_rows": int(item.get("expected_rows", -1)),
            "n_columns": int(item.get("expected_columns", -1)),
        }
        for key, value in expected.items():
            if facts[key] != value:
                structure_errors.append(
                    f"{key} mismatch: {facts[key]!r} != {value!r}"
                )

    diagnostics: dict[str, Any] = {}
    if values is not None and not structure_errors:
        try:
            diagnostics = _diagnostics(values)
        except (FloatingPointError, ValueError) as exc:
            numerical_errors.append(str(exc))
    if diagnostics:
        if (
            diagnostics["max_timestamp_residual_samples"]
            > THRESHOLDS["max_timestamp_residual_samples"]
        ):
            numerical_errors.append(
                "timestamp residual exceeds frozen threshold"
            )
        if diagnostics["max_gap_ratio"] > THRESHOLDS["max_gap_ratio"]:
            numerical_errors.append("sampling gap exceeds frozen threshold")
        if (
            diagnostics["points_per_cycle"]
            < THRESHOLDS["min_points_per_cycle"]
        ):
            numerical_errors.append(
                "points per cycle below frozen threshold"
            )
        if (
            diagnostics["complete_cycles"]
            < THRESHOLDS["min_complete_cycles"]
        ):
            numerical_errors.append(
                "complete cycles below frozen threshold"
            )

    metadata = item.get("metadata")
    if not isinstance(metadata, dict) or set(metadata) != REQUIRED_METADATA:
        structure_errors.append("required metadata fields mismatch")
        metadata = {}
    resolved_metadata: dict[str, Any] = {}
    missing_metadata = []
    for name in sorted(REQUIRED_METADATA):
        field = metadata.get(name, {})
        source_kind = field.get("source_kind")
        declared_value = field.get("value")
        resolved_value = declared_value
        if name in {"frequency_hz", "amplitude_v", "scan_rate_v_s"}:
            if diagnostics:
                resolved_value = diagnostics[name]
        elif name == "scan_direction" and diagnostics:
            resolved_value = (
                "forward"
                if diagnostics["scan_rate_v_s"] > 0
                else "reverse"
            )
        elif name == "continuous_forward_scan" and diagnostics:
            resolved_value = diagnostics["scan_rate_v_s"] > 0
        resolved_metadata[name] = {
            "declared_value": declared_value,
            "resolved_value": resolved_value,
            "source_kind": source_kind,
            "source_note": field.get("source_note"),
        }
        if source_kind not in ACCEPTED_SOURCES:
            missing_metadata.append(name)
            metadata_errors.append(
                f"{name} source is {source_kind or 'missing'}"
            )
        elif resolved_value is None:
            missing_metadata.append(name)
            metadata_errors.append(f"{name} has no resolved value")

    if diagnostics:
        for name, threshold in (
            ("frequency_hz", "max_frequency_relative_error"),
            ("scan_rate_v_s", "max_scan_rate_relative_error"),
            ("amplitude_v", "max_amplitude_relative_error"),
        ):
            declared = metadata.get(name, {}).get("value")
            if declared is not None:
                error = _relative_error(
                    diagnostics[name], float(declared)
                )
                resolved_metadata[name][
                    "declared_relative_error"
                ] = error
                if error > THRESHOLDS[threshold]:
                    numerical_errors.append(
                        f"{name} differs from declaration"
                    )

    return {
        "dataset_id": item.get("dataset_id"),
        "path": relative_path.as_posix(),
        "file_facts": facts,
        "diagnostics": diagnostics,
        "metadata": resolved_metadata,
        "missing_metadata": sorted(set(missing_metadata)),
        "errors": {
            "structure": structure_errors,
            "numerical": numerical_errors,
            "metadata": metadata_errors,
        },
        "checks": {
            "structure_passed": not structure_errors,
            "numerical_passed": not numerical_errors,
            "metadata_passed": not metadata_errors,
        },
    }


def _recompute(
    project_root: Path,
    registry: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    if (
        registry.get("schema_version") != 1
        or registry.get("gate_version") != 1
        or not isinstance(registry.get("datasets"), list)
    ):
        raise ValueError("unsupported Gate A1 registry")
    datasets = registry["datasets"]
    ids = [item.get("dataset_id") for item in datasets]
    if len(datasets) != 4 or set(ids) != EXPECTED_IDS:
        raise ValueError("registry must contain exactly FT2, FT3, FT4 and FT8")
    if len(ids) != len(set(ids)):
        raise ValueError("registry dataset IDs must be unique")
    rows = [
        _recompute_dataset(project_root, item)
        for item in sorted(datasets, key=lambda value: value["dataset_id"])
    ]
    structure_passed = all(
        row["checks"]["structure_passed"] for row in rows
    )
    numerical_passed = all(
        row["checks"]["numerical_passed"] for row in rows
    )
    metadata_passed = all(
        row["checks"]["metadata_passed"] for row in rows
    )
    if not structure_passed:
        gate = "FAIL_STRUCTURE"
    elif not numerical_passed:
        gate = "FAIL_NUMERICAL"
    elif not metadata_passed:
        gate = "FAIL_METADATA"
    else:
        gate = "PASS"
    contracts = {
        "schema_version": 1,
        "gate_version": 1,
        "thresholds": dict(THRESHOLDS),
        "datasets": rows,
    }
    summary = {
        "schema_version": 1,
        "gate_version": 1,
        "dataset_count": 4,
        "gate": gate,
        "structure_passed": structure_passed,
        "numerical_passed": numerical_passed,
        "metadata_passed": metadata_passed,
        "eligible_for_inversion": gate == "PASS",
        "missing_metadata": {
            row["dataset_id"]: row["missing_metadata"]
            for row in rows
            if row["missing_metadata"]
        },
    }
    return contracts, summary


def validate_archive(
    project_root: Path,
    registry_path: Path,
    archive: Path,
) -> dict[str, Any]:
    """Return the independently recomputed final Gate A1 result."""
    errors = {"structure": [], "numerical": [], "metadata": []}
    required = {
        "dataset_contracts.json",
        "gate_a1_summary.json",
        "run_manifest.json",
    }
    missing = sorted(
        name for name in required if not (archive / name).is_file()
    )
    if missing:
        return {
            "gate": "FAIL_STRUCTURE",
            "structure_passed": False,
            "numerical_passed": False,
            "metadata_passed": False,
            "eligible_for_inversion": False,
            "errors": {
                **errors,
                "structure": [f"missing archive files: {missing}"],
            },
        }
    try:
        registry = _load_json(registry_path)
        reported_contracts = _load_json(
            archive / "dataset_contracts.json"
        )
        reported_summary = _load_json(
            archive / "gate_a1_summary.json"
        )
        manifest = _load_json(archive / "run_manifest.json")
    except FloatingPointError as exc:
        return {
            "gate": "FAIL_NUMERICAL",
            "structure_passed": True,
            "numerical_passed": False,
            "metadata_passed": False,
            "eligible_for_inversion": False,
            "errors": {**errors, "numerical": [str(exc)]},
        }
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return {
            "gate": "FAIL_STRUCTURE",
            "structure_passed": False,
            "numerical_passed": False,
            "metadata_passed": False,
            "eligible_for_inversion": False,
            "errors": {**errors, "structure": [str(exc)]},
        }

    registry_hash = hashlib.sha256(registry_path.read_bytes()).hexdigest()
    if manifest.get("registry_sha256") != registry_hash:
        errors["structure"].append("registry SHA-256 mismatch")
    if manifest.get("dirty") is not False:
        errors["structure"].append("formal manifest is dirty")
    try:
        recomputed_contracts, recomputed_summary = _recompute(
            project_root, registry
        )
    except FloatingPointError as exc:
        errors["numerical"].append(str(exc))
        recomputed_contracts = None
        recomputed_summary = None
    except (OSError, ValueError, KeyError) as exc:
        errors["structure"].append(str(exc))
        recomputed_contracts = None
        recomputed_summary = None

    if recomputed_contracts is not None:
        if reported_contracts != recomputed_contracts:
            errors["structure"].append(
                "reported contracts differ from independent recomputation"
            )
        if reported_summary != recomputed_summary:
            errors["structure"].append(
                "reported summary differs from independent recomputation"
            )

    if errors["structure"]:
        gate = "FAIL_STRUCTURE"
        structure_passed = False
        numerical_passed = not errors["numerical"]
        metadata_passed = False
    elif errors["numerical"]:
        gate = "FAIL_NUMERICAL"
        structure_passed = True
        numerical_passed = False
        metadata_passed = False
    else:
        assert recomputed_summary is not None
        gate = recomputed_summary["gate"]
        structure_passed = recomputed_summary["structure_passed"]
        numerical_passed = recomputed_summary["numerical_passed"]
        metadata_passed = recomputed_summary["metadata_passed"]
        errors["metadata"] = [
            f"{dataset_id}: {','.join(fields)}"
            for dataset_id, fields in recomputed_summary[
                "missing_metadata"
            ].items()
        ]
    return {
        "gate": gate,
        "structure_passed": structure_passed,
        "numerical_passed": numerical_passed,
        "metadata_passed": metadata_passed,
        "eligible_for_inversion": gate == "PASS",
        "errors": errors,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--archive", type=Path, required=True)
    arguments = parser.parse_args(argv)
    result = validate_archive(
        Path(__file__).resolve().parents[3],
        arguments.registry.resolve(),
        arguments.archive.resolve(),
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return EXIT_CODES[result["gate"]]


if __name__ == "__main__":
    raise SystemExit(main())
