#!/usr/bin/env python3
"""Audit frozen FTacV raw files against the Gate A1 data contract."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import subprocess
import sys
import tempfile
from typing import Any

import numpy as np


PROJECT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT / "code" / "python" / "src"))

from oer_aem.data_contract import (  # noqa: E402
    GATE_A1_THRESHOLDS,
    derive_sampling_diagnostics,
    read_strict_experimental_trace,
)


ACCEPTED_METADATA_SOURCES = {
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
EXPECTED_DATASET_IDS = {"FT2", "FT3", "FT4", "FT8"}
DERIVED_METADATA_KEYS = {
    "frequency_hz": "frequency_hz",
    "amplitude_v": "amplitude_v",
    "scan_rate_v_s": "scan_rate_v_s",
}
EXIT_CODES = {
    "PASS": 0,
    "FAIL_METADATA": 2,
    "FAIL_NUMERICAL": 3,
    "FAIL_STRUCTURE": 4,
}


def _finite_tree(value: Any) -> bool:
    if isinstance(value, float):
        return math.isfinite(value)
    if isinstance(value, dict):
        return all(_finite_tree(child) for child in value.values())
    if isinstance(value, list):
        return all(_finite_tree(child) for child in value)
    return True


def _relative_error(observed: float, declared: float) -> float:
    return abs(observed - declared) / max(abs(declared), 1e-30)


def _dataset_contract(
    project_root: Path,
    item: dict[str, Any],
) -> dict[str, Any]:
    structure_errors: list[str] = []
    numerical_errors: list[str] = []
    metadata_errors: list[str] = []
    relative_path = Path(str(item.get("path", "")))
    if relative_path.is_absolute() or ".." in relative_path.parts:
        structure_errors.append("dataset path must be project-relative")
    source = project_root / relative_path

    trace = None
    facts = None
    diagnostics: dict[str, Any] = {}
    try:
        trace, facts = read_strict_experimental_trace(source)
    except (OSError, UnicodeError, ValueError) as exc:
        message = str(exc)
        if "finite" in message or "time must" in message:
            numerical_errors.append(message)
        else:
            structure_errors.append(message)

    if facts is not None:
        expected = {
            "sha256": str(item.get("sha256", "")),
            "byte_count": int(item.get("byte_count", -1)),
            "n_rows": int(item.get("expected_rows", -1)),
            "n_columns": int(item.get("expected_columns", -1)),
        }
        observed = {
            "sha256": facts.sha256,
            "byte_count": facts.byte_count,
            "n_rows": facts.n_rows,
            "n_columns": facts.n_columns,
        }
        for name, expected_value in expected.items():
            if observed[name] != expected_value:
                structure_errors.append(
                    f"{name} mismatch: {observed[name]!r} != "
                    f"{expected_value!r}"
                )
    else:
        observed = {}

    if trace is not None and not structure_errors:
        try:
            diagnostics = derive_sampling_diagnostics(trace)
        except (ValueError, FloatingPointError) as exc:
            numerical_errors.append(str(exc))
    if diagnostics:
        thresholds = GATE_A1_THRESHOLDS
        if diagnostics["max_timestamp_residual_samples"] > thresholds[
            "max_timestamp_residual_samples"
        ]:
            numerical_errors.append(
                "timestamp residual exceeds frozen threshold"
            )
        if diagnostics["max_gap_ratio"] > thresholds["max_gap_ratio"]:
            numerical_errors.append("sampling gap exceeds frozen threshold")
        if diagnostics["points_per_cycle"] < thresholds[
            "min_points_per_cycle"
        ]:
            numerical_errors.append(
                "points per cycle below frozen threshold"
            )
        if diagnostics["complete_cycles"] < thresholds[
            "min_complete_cycles"
        ]:
            numerical_errors.append(
                "complete cycles below frozen threshold"
            )
        if not _finite_tree(diagnostics):
            numerical_errors.append("diagnostics contain non-finite values")

    metadata = item.get("metadata")
    resolved_metadata: dict[str, Any] = {}
    missing_metadata: list[str] = []
    if not isinstance(metadata, dict) or set(metadata) != REQUIRED_METADATA:
        structure_errors.append("required metadata fields mismatch")
        metadata = {}
    for name in sorted(REQUIRED_METADATA):
        field = metadata.get(name, {})
        source_kind = field.get("source_kind")
        declared_value = field.get("value")
        resolved_value = declared_value
        if name in DERIVED_METADATA_KEYS and diagnostics:
            resolved_value = diagnostics[DERIVED_METADATA_KEYS[name]]
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
        if source_kind not in ACCEPTED_METADATA_SOURCES:
            missing_metadata.append(name)
            metadata_errors.append(
                f"{name} source is {source_kind or 'missing'}"
            )
        elif resolved_value is None:
            missing_metadata.append(name)
            metadata_errors.append(f"{name} has no resolved value")

    if diagnostics:
        for metadata_name, threshold_name in (
            ("frequency_hz", "max_frequency_relative_error"),
            ("scan_rate_v_s", "max_scan_rate_relative_error"),
            ("amplitude_v", "max_amplitude_relative_error"),
        ):
            declared = metadata.get(metadata_name, {}).get("value")
            if declared is not None:
                observed_value = diagnostics[metadata_name]
                error = _relative_error(observed_value, float(declared))
                resolved_metadata[metadata_name][
                    "declared_relative_error"
                ] = error
                if error > GATE_A1_THRESHOLDS[threshold_name]:
                    numerical_errors.append(
                        f"{metadata_name} differs from declaration"
                    )

    return {
        "dataset_id": item.get("dataset_id"),
        "path": relative_path.as_posix(),
        "file_facts": observed,
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


def evaluate_registry(
    project_root: Path,
    registry: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Evaluate all registered datasets without writing output."""
    if (
        registry.get("schema_version") != 1
        or registry.get("gate_version") != 1
        or not isinstance(registry.get("datasets"), list)
    ):
        raise ValueError("unsupported Gate A1 registry")
    items = registry["datasets"]
    dataset_ids = [item.get("dataset_id") for item in items]
    if len(items) != 4 or set(dataset_ids) != EXPECTED_DATASET_IDS:
        raise ValueError("registry must contain exactly FT2, FT3, FT4 and FT8")
    if len(dataset_ids) != len(set(dataset_ids)):
        raise ValueError("registry dataset IDs must be unique")

    results = [
        _dataset_contract(project_root, item)
        for item in sorted(items, key=lambda value: value["dataset_id"])
    ]
    structure_passed = all(
        item["checks"]["structure_passed"] for item in results
    )
    numerical_passed = all(
        item["checks"]["numerical_passed"] for item in results
    )
    metadata_passed = all(
        item["checks"]["metadata_passed"] for item in results
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
        "thresholds": dict(GATE_A1_THRESHOLDS),
        "datasets": results,
    }
    summary = {
        "schema_version": 1,
        "gate_version": 1,
        "dataset_count": len(results),
        "gate": gate,
        "structure_passed": structure_passed,
        "numerical_passed": numerical_passed,
        "metadata_passed": metadata_passed,
        "eligible_for_inversion": gate == "PASS",
        "missing_metadata": {
            item["dataset_id"]: item["missing_metadata"]
            for item in results
            if item["missing_metadata"]
        },
    }
    return contracts, summary


def _write_json_atomic(path: Path, value: Any) -> None:
    payload = (
        json.dumps(
            value,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", dir=path.parent
    )
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
    finally:
        temporary = Path(temporary_name)
        if temporary.exists():
            temporary.unlink()


def write_audit_outputs(
    output: Path,
    *,
    contracts: dict[str, Any],
    summary: dict[str, Any],
    manifest: dict[str, Any],
) -> None:
    """Write the three compact Gate A1 artifacts to a new or empty folder."""
    if output.exists() and any(output.iterdir()):
        raise FileExistsError("output directory must be new or empty")
    output.mkdir(parents=True, exist_ok=True)
    _write_json_atomic(output / "dataset_contracts.json", contracts)
    _write_json_atomic(output / "gate_a1_summary.json", summary)
    _write_json_atomic(output / "run_manifest.json", manifest)


def _git_value(project_root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=project_root,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def build_manifest(
    project_root: Path,
    registry_path: Path,
    argv: list[str],
) -> dict[str, Any]:
    registry_bytes = registry_path.read_bytes()
    status = _git_value(project_root, "status", "--porcelain=v1")
    return {
        "schema_version": 1,
        "commit": _git_value(project_root, "rev-parse", "HEAD"),
        "dirty": bool(status),
        "dirty_paths": status.splitlines(),
        "registry_path": registry_path.relative_to(project_root).as_posix(),
        "registry_sha256": hashlib.sha256(registry_bytes).hexdigest(),
        "python_version": platform.python_version(),
        "numpy_version": np.__version__,
        "command": argv,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args(argv)
    started_at = datetime.now(timezone.utc).isoformat()
    registry_path = arguments.registry.resolve()
    project_root = PROJECT.resolve()
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    contracts, summary = evaluate_registry(project_root, registry)
    manifest = build_manifest(
        project_root,
        registry_path,
        sys.argv if argv is None else [str(Path(__file__)), *argv],
    )
    manifest["started_at"] = started_at
    manifest["finished_at"] = datetime.now(timezone.utc).isoformat()
    if manifest["dirty"]:
        summary = {
            **summary,
            "gate": "FAIL_STRUCTURE",
            "structure_passed": False,
            "eligible_for_inversion": False,
            "repository_error": "formal audit requires a clean worktree",
        }
    write_audit_outputs(
        arguments.output.resolve(),
        contracts=contracts,
        summary=summary,
        manifest=manifest,
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    return EXIT_CODES[summary["gate"]]


if __name__ == "__main__":
    raise SystemExit(main())
