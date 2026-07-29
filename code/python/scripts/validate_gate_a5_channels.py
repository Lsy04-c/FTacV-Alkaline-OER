#!/usr/bin/env python3
"""Independently validate a Gate A5 feature-channel archive."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import re
from typing import Any


DATASETS = ("FT2", "FT3", "FT4", "FT8")
MODES = ("legacy", "complex_snr", "lockin_only", "hybrid")
EXPECTED_KEYS = {(dataset, mode) for dataset in DATASETS for mode in MODES}
ARTIFACTS = (
    "channel_contracts.jsonl",
    "candidate_invariance.jsonl",
    "gate_a5_summary.json",
)
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


class NumericalArchiveError(ValueError):
    """Raised when an artifact contains a non-finite JSON number."""


def _reject_constant(value: str) -> None:
    raise NumericalArchiveError(f"non-finite JSON constant: {value}")


def _load_json(path: Path) -> Any:
    return json.loads(
        path.read_text(encoding="utf-8"),
        parse_constant=_reject_constant,
    )


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for line_number, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        if not line.strip():
            raise ValueError(f"{path.name}:{line_number} is blank")
        value = json.loads(line, parse_constant=_reject_constant)
        if not isinstance(value, dict):
            raise ValueError(f"{path.name}:{line_number} is not an object")
        records.append(value)
    return records


def _canonical_sha256(value: Any) -> str:
    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode()
    return hashlib.sha256(payload).hexdigest()


def _finite_number(value: Any, *, positive: bool = False) -> bool:
    if isinstance(value, bool):
        return False
    try:
        number = float(value)
    except (TypeError, ValueError):
        return False
    return math.isfinite(number) and (number > 0.0 if positive else True)


def _keys(records: list[dict[str, Any]]) -> list[tuple[Any, Any]]:
    return [
        (record.get("dataset_id"), record.get("feature_mode"))
        for record in records
    ]


def _validate_contract(record: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    contract = record.get("channel_contract")
    if not isinstance(contract, dict):
        return ["missing channel_contract object"]
    required = {
        "schema_version",
        "feature_mode",
        "fit_harmonics",
        "phase_weight",
        "snr_floor",
        "normalization_weight_sum",
        "channels",
        "sha256",
    }
    if set(contract) != required:
        errors.append("channel contract fields mismatch")
    observed_hash = contract.get("sha256")
    unhashed = {key: value for key, value in contract.items() if key != "sha256"}
    try:
        expected_hash = _canonical_sha256(unhashed)
    except (TypeError, ValueError):
        return errors + ["channel contract is not finite canonical JSON"]
    if (
        not isinstance(observed_hash, str)
        or len(observed_hash) != 64
        or observed_hash != expected_hash
    ):
        errors.append("channel contract hash mismatch")
    if contract.get("schema_version") != 1:
        errors.append("channel contract schema mismatch")
    if contract.get("feature_mode") != record.get("feature_mode"):
        errors.append("channel contract mode mismatch")
    if not _finite_number(contract.get("phase_weight"), positive=True):
        errors.append("phase weight must be finite and positive")
    if not _finite_number(contract.get("snr_floor")):
        errors.append("SNR floor must be finite")
    channels = contract.get("channels")
    if not isinstance(channels, list) or not channels:
        return errors + ["channels must be a non-empty list"]

    channel_ids: list[Any] = []
    active_weight_sum = 0.0
    for channel in channels:
        if not isinstance(channel, dict):
            errors.append("channel must be an object")
            continue
        channel_ids.append(channel.get("channel_id"))
        active = channel.get("active")
        available = channel.get("available")
        requested = channel.get("requested")
        if not isinstance(available, bool) or not isinstance(requested, bool):
            errors.append("channel availability/request flags must be boolean")
        if not isinstance(channel.get("n_points"), int):
            errors.append("channel point count must be an integer")
        if active is True:
            if channel.get("exclusion_reason") is not None:
                errors.append("active channel has exclusion reason")
            if not _finite_number(
                channel.get("target_weight"), positive=True
            ):
                errors.append("active target weight must be positive")
            if not _finite_number(
                channel.get("loss_weight"), positive=True
            ):
                errors.append("active loss weight must be positive")
            else:
                active_weight_sum += float(channel["loss_weight"])
            if channel.get("n_points", 0) <= 0:
                errors.append("active channel has no points")
        elif active is False:
            if channel.get("exclusion_reason") not in EXCLUSION_REASONS:
                errors.append("inactive channel has invalid exclusion reason")
            if channel.get("target_weight") != 0.0:
                errors.append("inactive target weight must be zero")
            if channel.get("loss_weight") != 0.0:
                errors.append("inactive loss weight must be zero")
        else:
            errors.append("channel active flag must be boolean")
    if len(channel_ids) != len(set(channel_ids)):
        errors.append("channel IDs must be unique")
    normalization = contract.get("normalization_weight_sum")
    if not _finite_number(normalization, positive=True):
        errors.append("normalization weight must be positive")
    elif not math.isclose(
        float(normalization),
        active_weight_sum,
        rel_tol=1e-12,
        abs_tol=1e-12,
    ):
        errors.append("normalization does not equal active loss weights")
    return errors


def _validate_invariance(
    record: dict[str, Any],
    contract_record: dict[str, Any],
) -> list[str]:
    errors: list[str] = []
    contract = contract_record.get("channel_contract")
    if not isinstance(contract, dict):
        return ["invariance has no valid contract evidence"]
    contract_hash = contract.get("sha256")
    if (
        record.get("candidate_a_contract_sha256") != contract_hash
        or record.get("candidate_b_contract_sha256") != contract_hash
    ):
        errors.append("candidate contract hash drift")
    normalization = contract.get("normalization_weight_sum")
    if not _finite_number(normalization, positive=True):
        return errors + ["contract normalization unavailable"]
    for name in (
        "candidate_a_normalization_weight_sum",
        "candidate_b_normalization_weight_sum",
    ):
        value = record.get(name)
        if (
            not _finite_number(value, positive=True)
            or not math.isclose(
                float(value),
                float(normalization),
                rel_tol=1e-12,
                abs_tol=1e-12,
            )
        ):
            errors.append("candidate normalization drift")
            break
    expected_active = sorted(
        channel.get("channel_id")
        for channel in contract.get("channels", [])
        if channel.get("active") is True
    )
    for name in (
        "candidate_a_active_channel_ids",
        "candidate_b_active_channel_ids",
    ):
        value = record.get(name)
        if not isinstance(value, list) or sorted(value) != expected_active:
            errors.append("candidate active channel drift")
            break
    penalty = record.get("feature_fail_penalty")
    failure = record.get("injected_failure_value")
    if (
        not _finite_number(penalty, positive=True)
        or not _finite_number(failure, positive=True)
        or float(failure) != float(penalty)
    ):
        errors.append("feature failure penalty mismatch")
    if record.get("n_feature_fail_delta") != 1:
        errors.append("feature failure counter mismatch")
    return errors


def _base_report(gate: str) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "gate_version": "A5",
        "gate": gate,
        "record_count": 0,
        "structure_errors": [],
        "numerical_errors": [],
        "contract_errors": {},
    }


def validate_archive(archive: Path) -> dict[str, Any]:
    """Validate archive bytes, schema and contract semantics independently."""
    report = _base_report("FAIL_STRUCTURE")
    required_paths = [archive / name for name in (*ARTIFACTS, "run_manifest.json")]
    missing = [path.name for path in required_paths if not path.is_file()]
    if missing:
        report["structure_errors"].append(
            f"missing required artifacts: {sorted(missing)}"
        )
        return report
    try:
        manifest = _load_json(archive / "run_manifest.json")
    except NumericalArchiveError as exc:
        report["gate"] = "FAIL_NUMERICAL"
        report["numerical_errors"].append(str(exc))
        return report
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        report["structure_errors"].append(str(exc))
        return report
    if not isinstance(manifest, dict):
        report["structure_errors"].append("manifest must be an object")
        return report
    artifact_hashes = manifest.get("artifact_sha256")
    if not isinstance(artifact_hashes, dict) or set(artifact_hashes) != set(
        ARTIFACTS
    ):
        report["structure_errors"].append("manifest artifact hashes mismatch")
        return report
    for name in ARTIFACTS:
        observed = hashlib.sha256((archive / name).read_bytes()).hexdigest()
        if artifact_hashes.get(name) != observed:
            report["structure_errors"].append(f"{name} hash mismatch")
    if report["structure_errors"]:
        return report
    if (
        manifest.get("schema_version") != 1
        or manifest.get("gate_version") != "A5"
        or manifest.get("runs_tpe") is not False
        or manifest.get("dirty") is not False
        or manifest.get("dirty_paths") != []
        or not isinstance(manifest.get("commit"), str)
        or re.fullmatch(r"[0-9a-f]{40}", manifest["commit"]) is None
    ):
        report["structure_errors"].append("manifest provenance mismatch")
        return report

    try:
        contracts = _load_jsonl(archive / ARTIFACTS[0])
        invariance = _load_jsonl(archive / ARTIFACTS[1])
        summary = _load_json(archive / ARTIFACTS[2])
    except NumericalArchiveError as exc:
        report["gate"] = "FAIL_NUMERICAL"
        report["numerical_errors"].append(str(exc))
        return report
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        report["structure_errors"].append(str(exc))
        return report

    report["record_count"] = len(contracts)
    contract_keys = _keys(contracts)
    invariance_keys = _keys(invariance)
    if (
        len(contract_keys) != 16
        or len(set(contract_keys)) != 16
        or set(contract_keys) != EXPECTED_KEYS
    ):
        report["structure_errors"].append("contract dataset/mode set mismatch")
    if (
        len(invariance_keys) != 16
        or len(set(invariance_keys)) != 16
        or set(invariance_keys) != EXPECTED_KEYS
    ):
        report["structure_errors"].append(
            "invariance dataset/mode set mismatch"
        )
    unique_hash_count = len(
        {
            record.get("channel_contract", {}).get("sha256")
            for record in contracts
            if isinstance(record.get("channel_contract"), dict)
        }
    )
    if not isinstance(summary, dict) or (
        summary.get("schema_version") != 1
        or summary.get("gate_version") != "A5"
        or summary.get("record_count") != len(contracts)
        or summary.get("unique_contract_hash_count") != unique_hash_count
        or summary.get("eligible_for_tpe") is not False
    ):
        report["structure_errors"].append("runner summary mismatch")
    if report["structure_errors"]:
        return report

    contract_by_key = {
        key: record for key, record in zip(contract_keys, contracts)
    }
    for key, record in zip(contract_keys, contracts):
        errors = _validate_contract(record)
        if errors:
            report["contract_errors"][f"{key[0]}:{key[1]}"] = errors
    for key, record in zip(invariance_keys, invariance):
        errors = _validate_invariance(record, contract_by_key[key])
        if errors:
            report["contract_errors"].setdefault(
                f"{key[0]}:{key[1]}", []
            ).extend(errors)

    if report["contract_errors"]:
        report["gate"] = "FAIL_CONTRACT"
    elif (
        summary.get("gate") != "PASS"
        or summary.get("structure_passed") is not True
        or summary.get("contract_passed") is not True
        or summary.get("structure_errors") != []
        or summary.get("contract_errors") != {}
    ):
        report["structure_errors"].append("runner PASS summary mismatch")
    else:
        report["gate"] = "PASS"
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive", type=Path, required=True)
    args = parser.parse_args(argv)
    report = validate_archive(args.archive)
    print(json.dumps(report, indent=2, sort_keys=True, allow_nan=False))
    return EXIT_CODES[report["gate"]]


if __name__ == "__main__":
    raise SystemExit(main())
