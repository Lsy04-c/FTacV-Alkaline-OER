#!/usr/bin/env python3
"""Audit frozen feature-channel contracts without running TPE."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import subprocess
import sys
import tempfile
from typing import Any, Iterable

import numpy as np


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "code" / "python" / "src"))
sys.path.insert(0, str(ROOT / "code" / "python" / "scripts"))
sys.path.insert(0, str(ROOT / "code" / "web" / "backend"))

from compare_feature_objectives import (  # noqa: E402
    _config,
    _experimental_target,
)
from main import _analyze_ftacv_data  # noqa: E402
from oer_aem.data_contract import read_strict_experimental_trace  # noqa: E402
from oer_aem import inversion as inversion_module  # noqa: E402
from oer_aem.inversion import (  # noqa: E402
    InversionObjective,
    build_feature_channel_contract,
)


DATASETS = ("FT2", "FT3", "FT4", "FT8")
MODES = ("legacy", "complex_snr", "lockin_only", "hybrid")
EXPECTED_KEYS = {(dataset, mode) for dataset in DATASETS for mode in MODES}
EXCLUSION_REASONS = {
    "not_requested",
    "mode_disabled",
    "target_missing",
    "target_shape_mismatch",
    "target_nonfinite",
    "below_snr_floor",
    "insufficient_valid_points",
    "not_applicable",
}
EXIT_CODES = {
    "PASS": 0,
    "FAIL_CONTRACT": 2,
    "FAIL_NUMERICAL": 3,
    "FAIL_STRUCTURE": 4,
}


def _canonical_sha256(value: Any) -> str:
    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode()
    return hashlib.sha256(payload).hexdigest()


def _record_keys(records: Iterable[dict[str, Any]]) -> list[tuple[Any, Any]]:
    return [
        (record.get("dataset_id"), record.get("feature_mode"))
        for record in records
    ]


def _finite_number(value: Any, *, positive: bool = False) -> bool:
    if isinstance(value, bool):
        return False
    try:
        number = float(value)
    except (TypeError, ValueError):
        return False
    return math.isfinite(number) and (number > 0.0 if positive else True)


def _contract_errors(record: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    contract = record.get("channel_contract")
    if not isinstance(contract, dict):
        return ["channel_contract must be an object"]
    observed_hash = contract.get("sha256")
    unhashed = {key: value for key, value in contract.items() if key != "sha256"}
    try:
        expected_hash = _canonical_sha256(unhashed)
    except (TypeError, ValueError):
        return ["channel contract is not finite canonical JSON"]
    if (
        not isinstance(observed_hash, str)
        or len(observed_hash) != 64
        or observed_hash != expected_hash
    ):
        errors.append("channel contract hash mismatch")
    if contract.get("feature_mode") != record.get("feature_mode"):
        errors.append("feature mode mismatch")
    channels = contract.get("channels")
    if not isinstance(channels, list) or not channels:
        return errors + ["channels must be a non-empty list"]
    active_weight_sum = 0.0
    channel_ids: list[Any] = []
    for channel in channels:
        if not isinstance(channel, dict):
            errors.append("channel must be an object")
            continue
        channel_ids.append(channel.get("channel_id"))
        active = channel.get("active")
        weight = channel.get("loss_weight")
        reason = channel.get("exclusion_reason")
        if active is True:
            if reason is not None:
                errors.append("active channel has exclusion reason")
            if not _finite_number(weight, positive=True):
                errors.append("active channel weight must be finite and positive")
            else:
                active_weight_sum += float(weight)
        elif active is False:
            if reason not in EXCLUSION_REASONS:
                errors.append("inactive channel has invalid exclusion reason")
        else:
            errors.append("channel active flag must be boolean")
    if len(channel_ids) != len(set(channel_ids)):
        errors.append("channel IDs must be unique")
    normalization = contract.get("normalization_weight_sum")
    if not _finite_number(normalization, positive=True):
        errors.append("normalization weight must be finite and positive")
    elif not math.isclose(
        float(normalization),
        active_weight_sum,
        rel_tol=1e-12,
        abs_tol=1e-12,
    ):
        errors.append("normalization weight does not match active weights")
    return errors


def _invariance_errors(
    record: dict[str, Any],
    contract_by_key: dict[tuple[Any, Any], dict[str, Any]],
) -> list[str]:
    errors: list[str] = []
    key = (record.get("dataset_id"), record.get("feature_mode"))
    contract_record = contract_by_key.get(key)
    if contract_record is None:
        return ["invariance record has no contract"]
    contract = contract_record.get("channel_contract")
    if not isinstance(contract, dict):
        return ["invariance record has no valid contract"]
    if (
        not isinstance(contract.get("sha256"), str)
        or not isinstance(contract.get("channels"), list)
        or not _finite_number(
            contract.get("normalization_weight_sum"), positive=True
        )
    ):
        return ["invariance record has no valid contract evidence"]
    contract_hash = contract["sha256"]
    expected_active = sorted(
        channel["channel_id"]
        for channel in contract["channels"]
        if channel["active"]
    )
    hashes = (
        record.get("candidate_a_contract_sha256"),
        record.get("candidate_b_contract_sha256"),
    )
    if hashes != (contract_hash, contract_hash):
        errors.append("candidate contract hash drift")
    normalization = float(contract["normalization_weight_sum"])
    candidate_normalizations = (
        record.get("candidate_a_normalization_weight_sum"),
        record.get("candidate_b_normalization_weight_sum"),
    )
    if not all(
        _finite_number(value, positive=True)
        and math.isclose(
            float(value), normalization, rel_tol=1e-12, abs_tol=1e-12
        )
        for value in candidate_normalizations
    ):
        errors.append("candidate normalization drift")
    for name in (
        "candidate_a_active_channel_ids",
        "candidate_b_active_channel_ids",
    ):
        value = record.get(name)
        if not isinstance(value, list) or sorted(value) != expected_active:
            errors.append("candidate active channel drift")
            break
    if (
        not _finite_number(record.get("feature_fail_penalty"), positive=True)
        or record.get("injected_failure_value")
        != record.get("feature_fail_penalty")
    ):
        errors.append("injected feature failure did not use fixed penalty")
    if record.get("n_feature_fail_delta") != 1:
        errors.append("injected feature failure count mismatch")
    return errors


def evaluate_audit(
    contract_records: list[dict[str, Any]],
    invariance_records: list[dict[str, Any]],
) -> dict[str, Any]:
    """Classify Gate A5 records without writing artifacts."""
    contract_keys = _record_keys(contract_records)
    invariance_keys = _record_keys(invariance_records)
    structure_errors: list[str] = []
    if (
        len(contract_keys) != 16
        or len(set(contract_keys)) != 16
        or set(contract_keys) != EXPECTED_KEYS
    ):
        structure_errors.append("contract dataset/mode set mismatch")
    if (
        len(invariance_keys) != 16
        or len(set(invariance_keys)) != 16
        or set(invariance_keys) != EXPECTED_KEYS
    ):
        structure_errors.append("invariance dataset/mode set mismatch")

    contract_errors: dict[str, list[str]] = {}
    if not structure_errors:
        contract_by_key = {
            key: record for key, record in zip(contract_keys, contract_records)
        }
        for key, record in zip(contract_keys, contract_records):
            errors = _contract_errors(record)
            if errors:
                contract_errors[f"{key[0]}:{key[1]}"] = errors
        for key, record in zip(invariance_keys, invariance_records):
            errors = _invariance_errors(record, contract_by_key)
            if errors:
                contract_errors.setdefault(
                    f"{key[0]}:{key[1]}", []
                ).extend(errors)

    structure_passed = not structure_errors
    contract_passed = structure_passed and not contract_errors
    gate = (
        "FAIL_STRUCTURE"
        if not structure_passed
        else "PASS"
        if contract_passed
        else "FAIL_CONTRACT"
    )
    hashes = {
        record.get("channel_contract", {}).get("sha256")
        for record in contract_records
        if isinstance(record.get("channel_contract"), dict)
    }
    return {
        "schema_version": 1,
        "gate_version": "A5",
        "gate": gate,
        "record_count": len(contract_records),
        "unique_contract_hash_count": len(hashes),
        "structure_passed": structure_passed,
        "contract_passed": contract_passed,
        "eligible_for_tpe": False,
        "structure_errors": structure_errors,
        "contract_errors": contract_errors,
    }


def _active_channel_ids(objective: InversionObjective) -> list[str]:
    return sorted(
        item.channel_id
        for item in objective.channel_contract.channels
        if item.active
    )


def _exercise_candidate_invariance(
    target: dict[str, Any],
    config,
) -> dict[str, Any]:
    objective = InversionObjective(target, config=config)
    candidate_a = copy.deepcopy(target)
    candidate_b = copy.deepcopy(target)
    candidate_b["dc"] = np.asarray(candidate_b["dc"], dtype=float) + 0.01
    injected = copy.deepcopy(target)
    injected["dc"] = np.asarray(injected["dc"], dtype=float)
    injected["dc"][0] = np.nan
    candidates = iter((candidate_a, candidate_b, injected))
    original_forward = inversion_module.forward_current
    original_extract = inversion_module.extract_features
    inversion_module.forward_current = (
        lambda *args, **kwargs: np.zeros(config.n_points, dtype=float)
    )
    inversion_module.extract_features = (
        lambda *args, **kwargs: next(candidates)
    )
    try:
        objective(np.zeros(len(objective.specs), dtype=float))
        hash_a = objective.channel_contract.sha256
        norm_a = objective.channel_contract.normalization_weight_sum
        active_a = _active_channel_ids(objective)
        objective(np.zeros(len(objective.specs), dtype=float))
        hash_b = objective.channel_contract.sha256
        norm_b = objective.channel_contract.normalization_weight_sum
        active_b = _active_channel_ids(objective)
        before = objective.n_feature_fail
        failure_value = objective(
            np.zeros(len(objective.specs), dtype=float)
        )
        failure_delta = objective.n_feature_fail - before
    finally:
        inversion_module.forward_current = original_forward
        inversion_module.extract_features = original_extract
    return {
        "candidate_a_contract_sha256": hash_a,
        "candidate_b_contract_sha256": hash_b,
        "candidate_a_normalization_weight_sum": norm_a,
        "candidate_b_normalization_weight_sum": norm_b,
        "candidate_a_active_channel_ids": active_a,
        "candidate_b_active_channel_ids": active_b,
        "injected_failure_value": failure_value,
        "feature_fail_penalty": float(config.feature_fail_penalty),
        "n_feature_fail_delta": failure_delta,
    }


def build_real_records(
    project_root: Path,
    registry: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Build the 16 target-derived records from strict experimental traces."""
    registry_items = registry.get("datasets")
    if not isinstance(registry_items, list):
        raise ValueError("registry datasets must be a list")
    by_id = {item.get("dataset_id"): item for item in registry_items}
    if set(by_id) != set(DATASETS) or len(registry_items) != 4:
        raise ValueError("registry must contain exactly FT2, FT3, FT4 and FT8")

    contracts: list[dict[str, Any]] = []
    invariance: list[dict[str, Any]] = []
    for dataset_id in DATASETS:
        item = by_id[dataset_id]
        source = project_root / str(item["path"])
        trace, facts = read_strict_experimental_trace(source)
        rows = np.column_stack(
            (trace.potential, trace.current, trace.time)
        )
        analysis = _analyze_ftacv_data(rows)
        for mode in MODES:
            config = _config(
                mode,
                n_points=256,
                meta=analysis["meta"],
                fit_harmonics=(1, 2, 3),
                solver_backend="lsoda",
            )
            target = _experimental_target(rows, analysis, config)
            contract = build_feature_channel_contract(target, config)
            contracts.append(
                {
                    "dataset_id": dataset_id,
                    "feature_mode": mode,
                    "source_path": Path(str(item["path"])).as_posix(),
                    "source_sha256": facts.sha256,
                    "channel_contract": contract.to_evidence(),
                }
            )
            invariance.append(
                {
                    "dataset_id": dataset_id,
                    "feature_mode": mode,
                    **_exercise_candidate_invariance(target, config),
                }
            )
    return contracts, invariance


def _atomic_write(path: Path, payload: bytes) -> None:
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


def _write_json(path: Path, value: Any) -> None:
    _atomic_write(
        path,
        (
            json.dumps(value, indent=2, sort_keys=True, allow_nan=False)
            + "\n"
        ).encode(),
    )


def _write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    payload = "".join(
        json.dumps(
            record, sort_keys=True, separators=(",", ":"), allow_nan=False
        )
        + "\n"
        for record in records
    ).encode()
    _atomic_write(path, payload)


def write_audit_outputs(
    output: Path,
    *,
    contracts: list[dict[str, Any]],
    invariance: list[dict[str, Any]],
    summary: dict[str, Any],
    manifest: dict[str, Any],
) -> None:
    if output.exists() and any(output.iterdir()):
        raise FileExistsError("output directory must be new or empty")
    output.mkdir(parents=True, exist_ok=True)
    _write_jsonl(output / "channel_contracts.jsonl", contracts)
    _write_jsonl(output / "candidate_invariance.jsonl", invariance)
    _write_json(output / "gate_a5_summary.json", summary)
    _write_json(output / "run_manifest.json", manifest)


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
    status = _git_value(project_root, "status", "--porcelain=v1")
    return {
        "schema_version": 1,
        "gate_version": "A5",
        "commit": _git_value(project_root, "rev-parse", "HEAD"),
        "dirty": bool(status),
        "dirty_paths": status.splitlines(),
        "registry_path": registry_path.relative_to(project_root).as_posix(),
        "registry_sha256": hashlib.sha256(
            registry_path.read_bytes()
        ).hexdigest(),
        "python_version": platform.python_version(),
        "numpy_version": np.__version__,
        "command": argv,
        "runs_tpe": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--registry",
        type=Path,
        default=ROOT / "config" / "data-contracts" / "gate-a1-datasets.json",
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    registry = json.loads(args.registry.read_text(encoding="utf-8"))
    contracts, invariance = build_real_records(ROOT, registry)
    summary = evaluate_audit(contracts, invariance)
    manifest = build_manifest(
        ROOT,
        args.registry,
        sys.argv if argv is None else [__file__, *argv],
    )
    write_audit_outputs(
        args.output,
        contracts=contracts,
        invariance=invariance,
        summary=summary,
        manifest=manifest,
    )
    print(json.dumps(summary, sort_keys=True))
    return EXIT_CODES[summary["gate"]]


if __name__ == "__main__":
    raise SystemExit(main())
