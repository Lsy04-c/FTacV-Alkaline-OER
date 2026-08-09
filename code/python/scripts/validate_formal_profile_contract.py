#!/usr/bin/env python3
"""Read-only acceptance gate for a formal-v2-no-tafel profile run."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
from typing import Any


FEATURE_MODES = ("legacy", "complex_snr", "lockin_only", "hybrid")
PROFILE_PARAMETERS = ("k0_1", "k0_2", "k0_3", "G_OH", "G_O")
EXPECTED_MIXED_B_TRUTH_PARAMS = {
    "k0_1": 398.1071705534969,
    "k0_2": 0.25118864315095796,
    "k0_3": 158.48931924611142,
    "k0_4": 0.630957344480193,
    "G_OH": 1.4,
    "G_O": 2.68,
    "scaling_OOH_OH": 3.36,
    "gamma": 3.1622776601683795e-09,
}
EXPECTED_TRUTH_COORDINATES = {
    "k0_1": 0.7,
    "k0_2": 0.3,
    "k0_3": 0.65,
    "G_OH": 0.6,
    "G_O": 0.4,
}
EXPECTED_CONFIG = {
    "n_points": 8192,
    "points_per_cycle": 32,
    "feature_grid_size": 128,
    "fit_harmonics": [1, 2, 3],
    "feature_modes": list(FEATURE_MODES),
    "profile_parameters": list(PROFILE_PARAMETERS),
    "truth_id": "mixed_b",
    "grid_points": 41,
    "solver_backend": "lsoda",
    "noise_fraction": 0.0,
    "workers": 8,
    "smoke": False,
    "objective_contract": "formal-v2-no-tafel",
    "tafel_channel_mode": "disabled",
}
EXPECTED_ROW_FIELDS = (
    "profile_id",
    "feature_mode",
    "parameter",
    "truth_id",
    "normalized_coordinate",
    "truth_coordinate",
    "is_truth",
    "physical_value",
    "total_loss",
    "ode_success",
    "tafel_failed",
    "runtime_seconds",
    "dc",
    "common_harmonics",
    "dataset_specific_harmonics",
    "phase",
    "lockin_common_amplitude",
    "lockin_dataset_specific_amplitude",
    "lockin_common_phase",
    "lockin_dataset_specific_phase",
    "physical",
)
NUMERIC_ROW_FIELDS = tuple(
    field
    for field in EXPECTED_ROW_FIELDS
    if field
    not in {"profile_id", "feature_mode", "parameter", "truth_id", "is_truth", "ode_success", "tafel_failed"}
)
EXPECTED_CHANNEL_IDS = (
    ("dc",)
    + tuple(f"legacy_amplitude:H{harmonic}" for harmonic in range(1, 8))
    + tuple(
        channel
        for harmonic in range(1, 8)
        for channel in (f"complex_amplitude:H{harmonic}", f"complex_phase:H{harmonic}")
    )
    + tuple(
        channel
        for harmonic in range(1, 8)
        for channel in (f"lockin_amplitude:H{harmonic}", f"lockin_phase:H{harmonic}")
    )
    + ("tafel",)
)
EXPECTED_CHANNEL_FIELDS = {
    "channel_id", "block", "harmonic", "role", "requested", "available", "active",
    "target_weight", "loss_weight", "n_points", "mask_sha256", "exclusion_reason",
}
EXPECTED_TASK_FIELDS = {
    "profile_id", "feature_mode", "parameter", "truth_id", "truth_params",
    "truth_coordinate", "grid_points", "noise_fraction", "objective_contract",
    "tafel_channel_mode",
}
MODE_ENABLED_BLOCKS = {
    "legacy": {"legacy_amplitude"},
    "complex_snr": {"complex_amplitude", "complex_phase"},
    "lockin_only": {"lockin_amplitude", "lockin_phase"},
    "hybrid": {
        "complex_amplitude", "complex_phase", "lockin_amplitude", "lockin_phase",
    },
}
EXPECTED_FEATURE_CONTRACT_FIELDS = {
    "schema_version", "feature_mode", "objective_contract", "tafel_channel_mode",
    "fit_harmonics", "phase_weight", "snr_floor", "normalization_weight_sum",
    "channels", "sha256",
}
EXPECTED_FEATURE_GRID_SIZE = 128
EXPECTED_FULL_MASK_SHA256 = hashlib.sha256(
    EXPECTED_FEATURE_GRID_SIZE.to_bytes(8, "big")
    + b"\xff" * (EXPECTED_FEATURE_GRID_SIZE // 8)
).hexdigest()
EXIT_CODES = {
    "PASS": 0,
    "FAIL_STRUCTURE": 2,
    "FAIL_CONTRACT": 3,
    "FAIL_NUMERICAL": 4,
}


def _reject_nonfinite(value: str) -> None:
    raise ValueError(f"non-finite JSON value: {value}")


def _load_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(), parse_constant=_reject_nonfinite)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        raise ValueError(f"invalid JSON {path.name}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"JSON root must be an object: {path.name}")
    return payload


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _feature_contract_hash(contract: dict[str, Any]) -> str | None:
    supplied = contract.get("sha256")
    if not isinstance(supplied, str) or len(supplied) != 64:
        return None
    body = dict(contract)
    body.pop("sha256", None)
    try:
        encoded = json.dumps(
            body, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    except (TypeError, ValueError):
        return None
    return hashlib.sha256(encoded).hexdigest()


def _as_bool(value: Any) -> bool | None:
    if value is True or value == "True":
        return True
    if value is False or value == "False":
        return False
    return None


def _finite_number(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )


def _matches_coordinate(value: Any, parameter: str) -> bool:
    return _finite_number(value) and math.isclose(
        float(value), EXPECTED_TRUTH_COORDINATES[parameter],
        rel_tol=0.0, abs_tol=1e-12,
    )


def _is_sha256(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(
        character in "0123456789abcdef" for character in value
    )


def _is_zero(value: Any) -> bool:
    return _finite_number(value) and float(value) == 0.0


def _validate_truth_params(value: Any, errors: list[str], *, label: str) -> None:
    if not isinstance(value, dict) or set(value) != set(EXPECTED_MIXED_B_TRUTH_PARAMS):
        errors.append(f"{label}: truth_params field set mismatch")
        return
    for name, expected in EXPECTED_MIXED_B_TRUTH_PARAMS.items():
        actual = value.get(name)
        if not _finite_number(actual) or not math.isclose(
            float(actual), expected, rel_tol=1e-12, abs_tol=0.0
        ):
            errors.append(f"{label}: truth_params mismatch: {name}")


def _validate_inactive_channel(
    channel: dict[str, Any], errors: list[str], *, label: str, reason: str | None,
    require_unavailable: bool,
) -> None:
    if channel.get("active") is not False:
        errors.append(f"{label}: inactive channel marked active")
    if require_unavailable and channel.get("available") is not False:
        errors.append(f"{label}: inactive channel marked available")
    if not _is_zero(channel.get("target_weight")) or not _is_zero(channel.get("loss_weight")):
        errors.append(f"{label}: inactive channel has a nonzero weight")
    if channel.get("n_points") != 0:
        errors.append(f"{label}: inactive channel has points")
    actual_reason = channel.get("exclusion_reason")
    if reason is None:
        if not isinstance(actual_reason, str) or not actual_reason:
            errors.append(f"{label}: inactive channel lacks a reason")
    elif actual_reason != reason:
        errors.append(f"{label}: inactive channel reason mismatch")
    if channel.get("mask_sha256") is not None:
        errors.append(f"{label}: inactive channel has a mask")


def _validate_enabled_inactive_reason(
    channel: dict[str, Any], errors: list[str], *, label: str, block: str,
) -> None:
    available = channel.get("available")
    if available is True:
        if block.startswith("complex_"):
            allowed_reasons = {"below_snr_floor"}
        elif block.startswith("lockin_"):
            allowed_reasons = {"insufficient_valid_points"}
        else:
            errors.append(f"{label}: legacy channel cannot be available but inactive")
            return
    elif available is False:
        if block.startswith("complex_"):
            allowed_reasons = {"target_missing", "target_nonfinite"}
        elif block.startswith("lockin_"):
            allowed_reasons = {"target_missing", "target_shape_mismatch"}
        else:
            allowed_reasons = {
                "target_missing", "target_shape_mismatch", "target_nonfinite",
            }
    else:
        errors.append(f"{label}: inactive availability is not boolean")
        return
    if channel.get("exclusion_reason") not in allowed_reasons:
        errors.append(f"{label}: inactive reason is not runner-valid")


def _validate_feature_channel_semantics(
    channel: dict[str, Any], errors: list[str], *, profile_id: str, feature_mode: str
) -> None:
    channel_id = channel["channel_id"]
    label = f"{profile_id}: feature_contract {channel_id}"
    if channel_id == "dc":
        expected = {
            "block": "dc", "harmonic": None, "role": "global", "requested": True,
            "available": True, "active": True, "target_weight": 1.0, "loss_weight": 1.0,
            "exclusion_reason": None,
        }
        for key, value in expected.items():
            if (
                channel.get(key) is not value
                if key in {"requested", "available", "active"}
                else channel.get(key) != value
            ):
                errors.append(f"{label}: {key} mismatch")
        if (
            channel.get("n_points") != EXPECTED_FEATURE_GRID_SIZE
            or channel.get("mask_sha256") != EXPECTED_FULL_MASK_SHA256
        ):
            errors.append(f"{label}: active DC evidence mismatch")
        return
    if channel_id == "tafel":
        expected = {
            "block": "tafel", "harmonic": None, "role": "physical", "requested": False,
            "available": False, "active": False, "target_weight": 0.0, "loss_weight": 0.0,
            "n_points": 0, "mask_sha256": None,
            "exclusion_reason": "disabled_by_objective_contract",
        }
        for key, value in expected.items():
            if (
                channel.get(key) is not value
                if key in {"requested", "available", "active"}
                else channel.get(key) != value
            ):
                errors.append(f"{label}: disabled Tafel {key} mismatch")
        return

    block, harmonic_text = channel_id.split(":", maxsplit=1)
    harmonic = int(harmonic_text.removeprefix("H"))
    requested = harmonic <= 3
    if channel.get("block") != block or channel.get("harmonic") != harmonic:
        errors.append(f"{label}: block or harmonic mismatch")
    if channel.get("role") != ("common" if requested else "dataset_specific"):
        errors.append(f"{label}: role mismatch")
    if channel.get("requested") is not requested:
        errors.append(f"{label}: requested mismatch")
    enabled = block in MODE_ENABLED_BLOCKS[feature_mode]
    if not enabled:
        _validate_inactive_channel(
            channel, errors, label=label, reason="mode_disabled", require_unavailable=True,
        )
        return
    if not requested:
        _validate_inactive_channel(
            channel, errors, label=label, reason="not_requested", require_unavailable=True,
        )
        return
    if channel.get("active") is False:
        _validate_inactive_channel(
            channel, errors, label=label, reason=None, require_unavailable=False,
        )
        _validate_enabled_inactive_reason(
            channel, errors, label=label, block=block,
        )
        return
    if channel.get("active") is not True or channel.get("available") is not True:
        errors.append(f"{label}: active channel availability mismatch")
    if (
        not _finite_number(channel.get("target_weight"))
        or float(channel["target_weight"]) <= 0.0
        or not _finite_number(channel.get("loss_weight"))
        or float(channel["loss_weight"]) <= 0.0
        or not isinstance(channel.get("n_points"), int)
        or channel["n_points"] <= 0
        or channel.get("exclusion_reason") is not None
    ):
        errors.append(f"{label}: active channel evidence mismatch")
    mask = channel.get("mask_sha256")
    if block == "legacy_amplitude":
        if (
            channel.get("target_weight") != 1.0
            or channel.get("loss_weight") != 1.0
            or channel.get("n_points") != EXPECTED_FEATURE_GRID_SIZE
            or mask != EXPECTED_FULL_MASK_SHA256
        ):
            errors.append(f"{label}: legacy active evidence mismatch")
    elif block.startswith("complex_"):
        if mask is not None or float(channel["target_weight"]) > 1.0:
            errors.append(f"{label}: complex active evidence mismatch")
        if channel.get("n_points") != EXPECTED_FEATURE_GRID_SIZE:
            errors.append(f"{label}: complex channel point count mismatch")
    elif block.startswith("lockin_"):
        if (
            channel.get("target_weight") != 1.0
            or not _is_sha256(mask)
            or not isinstance(channel.get("n_points"), int)
            or not 2 <= channel["n_points"] <= EXPECTED_FEATURE_GRID_SIZE
        ):
            errors.append(f"{label}: lock-in active evidence mismatch")


def _validate_amplitude_phase_pairs(
    channels: list[dict[str, Any]],
    errors: list[str],
    *, profile_id: str, phase_weight: float,
) -> None:
    by_id = {channel["channel_id"]: channel for channel in channels}
    for prefix in ("complex", "lockin"):
        for harmonic in range(1, 8):
            amplitude = by_id[f"{prefix}_amplitude:H{harmonic}"]
            phase = by_id[f"{prefix}_phase:H{harmonic}"]
            label = f"{profile_id}: feature_contract {prefix} amplitude/phase H{harmonic}"
            for key in (
                "requested", "available", "active", "target_weight", "n_points",
                "mask_sha256", "exclusion_reason",
            ):
                if amplitude.get(key) != phase.get(key):
                    errors.append(f"{label}: {key} mismatch")
            if amplitude.get("active") is True:
                if not all(
                    _finite_number(value)
                    for value in (
                        amplitude.get("target_weight"), amplitude.get("loss_weight"),
                        phase.get("loss_weight"),
                    )
                ):
                    errors.append(f"{label}: active weight is not finite")
                    continue
                if not math.isclose(
                    float(amplitude["loss_weight"]), float(amplitude["target_weight"]),
                    rel_tol=0.0, abs_tol=1e-15,
                ) or not math.isclose(
                    float(phase["loss_weight"]),
                    float(amplitude["target_weight"]) * phase_weight,
                    rel_tol=0.0, abs_tol=1e-15,
                ):
                    errors.append(f"{label}: active loss-weight relationship mismatch")
            elif phase.get("loss_weight") != amplitude.get("loss_weight"):
                errors.append(f"{label}: inactive loss-weight mismatch")


def _expected_profile_ids() -> set[str]:
    return {
        f"{mode}__{parameter}"
        for mode in FEATURE_MODES
        for parameter in PROFILE_PARAMETERS
    }


def _empty_report(expected_commit: str) -> dict[str, Any]:
    return {
        "gate_version": "formal-v2-no-tafel-profile-v1",
        "expected_commit": expected_commit,
        "gate": "FAIL_STRUCTURE",
        "structure_errors": [],
        "contract_errors": [],
        "numerical_errors": [],
        "profile_count": 0,
        "row_count": 0,
    }


def _validate_config(
    config: Any,
    errors: list[str],
    *,
    label: str,
) -> None:
    if not isinstance(config, dict):
        errors.append(f"{label} configuration is not an object")
        return
    for key, expected in EXPECTED_CONFIG.items():
        if config.get(key) != expected:
            errors.append(f"{label} configuration mismatch: {key}")
    if set(config) != set(EXPECTED_CONFIG):
        errors.append(f"{label} configuration field set mismatch")


def _validate_feature_contract(
    profile: dict[str, Any], errors: list[str], profile_id: str
) -> None:
    feature_mode = profile.get("feature_mode")
    if feature_mode not in MODE_ENABLED_BLOCKS:
        errors.append(f"{profile_id}: feature_contract has invalid feature_mode")
        return
    contract = profile.get("feature_contract")
    if not isinstance(contract, dict):
        errors.append(f"{profile_id}: missing worker feature_contract")
        return
    if set(contract) != EXPECTED_FEATURE_CONTRACT_FIELDS:
        errors.append(f"{profile_id}: feature_contract field set mismatch")
        return
    expected_hash = _feature_contract_hash(contract)
    if expected_hash is None or expected_hash != contract.get("sha256"):
        errors.append(f"{profile_id}: feature_contract hash mismatch")
    if profile.get("feature_contract_sha256") != contract.get("sha256"):
        errors.append(f"{profile_id}: worker feature_contract SHA mismatch")
    for key, expected in {
        "schema_version": 2,
        "objective_contract": "formal-v2-no-tafel",
        "tafel_channel_mode": "disabled",
        "fit_harmonics": [1, 2, 3],
        "phase_weight": 1.0,
        "snr_floor": 3.0,
    }.items():
        if contract.get(key) != expected:
            errors.append(f"{profile_id}: feature_contract mismatch: {key}")
    if contract.get("feature_mode") != profile.get("feature_mode"):
        errors.append(f"{profile_id}: feature_contract feature_mode mismatch")
    channels = contract.get("channels")
    if not isinstance(channels, list) or tuple(
        item.get("channel_id") if isinstance(item, dict) else None
        for item in channels
    ) != EXPECTED_CHANNEL_IDS:
        errors.append(f"{profile_id}: feature_contract channel ID set mismatch")
        return
    if any(
        set(item) != EXPECTED_CHANNEL_FIELDS
        for item in channels
        if isinstance(item, dict)
    ):
        errors.append(f"{profile_id}: feature_contract channel schema mismatch")
        return
    for channel in channels:
        if not isinstance(channel, dict):
            errors.append(f"{profile_id}: feature_contract channel is not an object")
            return
        _validate_feature_channel_semantics(
            channel,
            errors,
            profile_id=profile_id,
            feature_mode=feature_mode,
        )
    phase_weight = contract.get("phase_weight")
    if not _finite_number(phase_weight):
        errors.append(f"{profile_id}: feature_contract phase_weight is not finite")
        return
    _validate_amplitude_phase_pairs(
        channels,
        errors,
        profile_id=profile_id,
        phase_weight=float(phase_weight),
    )
    normalization = contract.get("normalization_weight_sum")
    expected_normalization = sum(
        float(channel["loss_weight"])
        for channel in channels
        if channel.get("active") is True and _finite_number(channel.get("loss_weight"))
    )
    if not _finite_number(normalization) or not math.isclose(
        float(normalization), expected_normalization, rel_tol=1e-12, abs_tol=1e-15,
    ):
        errors.append(f"{profile_id}: feature_contract normalization_weight_sum mismatch")


def validate_formal_profile(
    input_dir: Path, *, expected_commit: str
) -> dict[str, Any]:
    """Validate frozen formal-v2 profile evidence without modifying it."""
    report = _empty_report(expected_commit)
    directory = Path(input_dir)
    required = {
        "profile_rows.csv": directory / "profile_rows.csv",
        "profile_summary.json": directory / "profile_summary.json",
        "run_manifest.json": directory / "run_manifest.json",
    }
    missing = [name for name, path in required.items() if not path.is_file()]
    if missing:
        report["structure_errors"].extend(
            f"missing artifact: {name}" for name in missing
        )
        return report
    try:
        summary = _load_json(required["profile_summary.json"])
        manifest = _load_json(required["run_manifest.json"])
    except ValueError as exc:
        report["structure_errors"].append(str(exc))
        return report

    for label, payload in (("summary", summary), ("manifest", manifest)):
        if payload.get("source_commit") != expected_commit:
            report["contract_errors"].append(f"{label} source_commit mismatch")
        if payload.get("dirty") is not False:
            report["contract_errors"].append(f"{label} must be clean")
        _validate_config(
            payload.get("configuration"), report["contract_errors"], label=label
        )
    if summary.get("configuration") != manifest.get("configuration"):
        report["contract_errors"].append("summary and manifest configuration differ")
    hashes = manifest.get("sha256")
    if not isinstance(hashes, dict):
        report["structure_errors"].append("manifest sha256 is missing")
    else:
        for name, path in required.items():
            if name == "run_manifest.json":
                continue
            if hashes.get(name) != _sha256(path):
                report["contract_errors"].append(f"manifest hash mismatch: {name}")

    tasks = manifest.get("tasks")
    if not isinstance(tasks, list) or len(tasks) != 20:
        report["structure_errors"].append("manifest task count is not 20")
    else:
        task_ids = {item.get("profile_id") for item in tasks if isinstance(item, dict)}
        if task_ids != _expected_profile_ids():
            report["structure_errors"].append("manifest task profile IDs mismatch")
        for task in tasks:
            if not isinstance(task, dict):
                report["contract_errors"].append("manifest task contract mismatch")
                continue
            profile_id = task.get("profile_id")
            mode, separator, parameter = str(profile_id).partition("__")
            if set(task) != EXPECTED_TASK_FIELDS:
                report["contract_errors"].append(
                    f"{profile_id}: manifest task field set mismatch"
                )
            if (
                separator != "__"
                or mode not in FEATURE_MODES
                or parameter not in PROFILE_PARAMETERS
                or task.get("feature_mode") != mode
                or task.get("parameter") != parameter
            ):
                report["contract_errors"].append(
                    f"{profile_id}: manifest task identity mismatch"
                )
                continue
            for key, value in {
                "truth_id": "mixed_b",
                "grid_points": 41,
                "noise_fraction": 0.0,
                "objective_contract": "formal-v2-no-tafel",
                "tafel_channel_mode": "disabled",
            }.items():
                if task.get(key) != value:
                    report["contract_errors"].append(
                        f"{profile_id}: manifest task {key} mismatch"
                    )
            _validate_truth_params(
                task.get("truth_params"), report["contract_errors"], label=f"{profile_id}: manifest task",
            )
            if not _matches_coordinate(task.get("truth_coordinate"), parameter):
                report["contract_errors"].append(
                    f"{profile_id}: manifest task truth_coordinate mismatch"
                )

    profiles = summary.get("profiles")
    if not isinstance(profiles, list):
        report["structure_errors"].append("profiles must be a list")
        return report
    report["profile_count"] = len(profiles)
    if summary.get("expected_profiles") != 20 or summary.get("completed_profiles") != 20:
        report["structure_errors"].append("summary profile count is not 20")
    if len(profiles) != 20:
        report["structure_errors"].append("profile list count is not 20")
    profile_ids = {
        item.get("profile_id") for item in profiles if isinstance(item, dict)
    }
    if profile_ids != _expected_profile_ids():
        report["structure_errors"].append("profile ID set mismatch")
    for item in profiles:
        if not isinstance(item, dict):
            report["structure_errors"].append("profile summary is not an object")
            continue
        profile_id = str(item.get("profile_id"))
        mode, separator, parameter = profile_id.partition("__")
        if separator != "__" or mode not in FEATURE_MODES or parameter not in PROFILE_PARAMETERS:
            report["structure_errors"].append(f"{profile_id}: invalid profile ID")
        if item.get("feature_mode") != mode or item.get("parameter") != parameter:
            report["contract_errors"].append(f"{profile_id}: profile identity mismatch")
        if item.get("truth_id") != "mixed_b":
            report["contract_errors"].append(f"{profile_id}: truth ID mismatch")
        if parameter in EXPECTED_TRUTH_COORDINATES and not _matches_coordinate(
            item.get("truth_coordinate"), parameter
        ):
            report["contract_errors"].append(
                f"{profile_id}: profile truth_coordinate mismatch"
            )
        if item.get("objective_contract") != "formal-v2-no-tafel":
            report["contract_errors"].append(f"{profile_id}: objective_contract")
        if item.get("tafel_channel_mode") != "disabled":
            report["contract_errors"].append(f"{profile_id}: tafel_channel_mode")
        if item.get("sampled_points") != 41:
            report["structure_errors"].append(f"{profile_id}: sampled_points")
        _validate_feature_contract(item, report["contract_errors"], profile_id)
        if item.get("truth_is_global_minimum") is not True:
            report["numerical_errors"].append(f"{profile_id}: summary truth not global minimum")
        if item.get("ode_failures") != 0 or item.get("tafel_failures") != 0:
            report["numerical_errors"].append(f"{profile_id}: failure count")
        if item.get("finite_fraction") != 1.0:
            report["numerical_errors"].append(f"{profile_id}: non-finite profile")
        truth_loss = item.get("truth_loss")
        if not isinstance(truth_loss, (int, float)) or not math.isfinite(truth_loss):
            report["numerical_errors"].append(f"{profile_id}: non-finite truth loss")

    try:
        with required["profile_rows.csv"].open(newline="") as handle:
            reader = csv.DictReader(handle)
            if tuple(reader.fieldnames or ()) != EXPECTED_ROW_FIELDS:
                report["structure_errors"].append("CSV field schema mismatch")
            rows = list(reader)
    except (OSError, csv.Error) as exc:
        report["structure_errors"].append(f"invalid CSV: {exc}")
        rows = []
    report["row_count"] = len(rows)
    if summary.get("expected_rows") != 820 or summary.get("completed_rows") != 820:
        report["structure_errors"].append("summary row count is not 820")
    if len(rows) != 820:
        report["structure_errors"].append("CSV row count is not 820")
    row_counts: dict[str, int] = {}
    row_losses: dict[str, list[float]] = {}
    truth_rows: dict[str, tuple[float, float, float]] = {}
    for row in rows:
        profile_id = row.get("profile_id")
        if not profile_id:
            report["structure_errors"].append("CSV row missing profile_id")
            continue
        row_counts[profile_id] = row_counts.get(profile_id, 0) + 1
        mode, separator, parameter = profile_id.partition("__")
        if (
            separator != "__"
            or mode not in FEATURE_MODES
            or parameter not in PROFILE_PARAMETERS
            or row.get("feature_mode") != mode
            or row.get("parameter") != parameter
            or row.get("truth_id") != "mixed_b"
        ):
            report["contract_errors"].append(f"{profile_id}: CSV identity mismatch")
        if _as_bool(row.get("ode_success")) is not True:
            report["numerical_errors"].append(f"{profile_id}: ODE failure row")
        if _as_bool(row.get("tafel_failed")) is not False:
            report["numerical_errors"].append(f"{profile_id}: Tafel failure row")
        numeric: dict[str, float] = {}
        for key in NUMERIC_ROW_FIELDS:
            try:
                value = float(row[key])
            except (KeyError, TypeError, ValueError):
                report["structure_errors"].append(f"{profile_id}: invalid {key}")
                continue
            if not math.isfinite(value):
                report["numerical_errors"].append(f"{profile_id}: non-finite {key}")
            numeric[key] = value
        if "total_loss" in numeric:
            row_losses.setdefault(profile_id, []).append(numeric["total_loss"])
        if parameter in EXPECTED_TRUTH_COORDINATES and not _matches_coordinate(
            numeric.get("truth_coordinate"), parameter
        ):
            report["contract_errors"].append(
                f"{profile_id}: CSV truth_coordinate mismatch"
            )
        if numeric.get("physical", 0.0) != 0.0:
            report["numerical_errors"].append(f"{profile_id}: nonzero physical component")
        is_truth = _as_bool(row.get("is_truth"))
        if is_truth is None:
            report["structure_errors"].append(f"{profile_id}: invalid is_truth")
        elif is_truth and "total_loss" in numeric:
            if profile_id in truth_rows:
                report["structure_errors"].append(f"{profile_id}: duplicate truth row")
            else:
                truth_rows[profile_id] = (
                    numeric["total_loss"],
                    numeric.get("normalized_coordinate", math.nan),
                    numeric.get("truth_coordinate", math.nan),
                )
    if set(row_counts) != _expected_profile_ids() or any(
        count != 41 for count in row_counts.values()
    ):
        report["structure_errors"].append("CSV profile row distribution mismatch")
    summaries_by_id = {
        item.get("profile_id"): item for item in profiles if isinstance(item, dict)
    }
    for profile_id in _expected_profile_ids():
        losses = row_losses.get(profile_id, [])
        truth = truth_rows.get(profile_id)
        if truth is None:
            report["structure_errors"].append(f"{profile_id}: missing truth row")
            continue
        if len(losses) != 41:
            continue
        minimum = min(losses)
        if not math.isclose(truth[0], minimum, rel_tol=1e-12, abs_tol=1e-15):
            report["numerical_errors"].append(f"{profile_id}: truth is not a CSV minimum")
        parameter = profile_id.partition("__")[2]
        expected_coordinate = EXPECTED_TRUTH_COORDINATES[parameter]
        if not math.isclose(
            truth[1], expected_coordinate, rel_tol=0.0, abs_tol=1e-12
        ):
            report["numerical_errors"].append(
                f"{profile_id}: truth row normalized_coordinate does not match truth coordinate"
            )
        if not math.isclose(
            truth[2], expected_coordinate, rel_tol=0.0, abs_tol=1e-12
        ):
            report["contract_errors"].append(
                f"{profile_id}: truth row truth_coordinate mismatch"
            )
        summary_truth = summaries_by_id.get(profile_id, {}).get("truth_loss")
        if not isinstance(summary_truth, (int, float)) or not math.isclose(
            float(summary_truth), truth[0], rel_tol=1e-12, abs_tol=1e-15
        ):
            report["numerical_errors"].append(f"{profile_id}: summary truth loss mismatch")

    if report["structure_errors"]:
        report["gate"] = "FAIL_STRUCTURE"
    elif report["contract_errors"]:
        report["gate"] = "FAIL_CONTRACT"
    elif report["numerical_errors"]:
        report["gate"] = "FAIL_NUMERICAL"
    else:
        report["gate"] = "PASS"
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--expected-commit", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.output.exists():
        raise FileExistsError(f"refusing to overwrite: {args.output}")
    report = validate_formal_profile(
        args.input_dir, expected_commit=args.expected_commit
    )
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(args.output)
    return EXIT_CODES[report["gate"]]


if __name__ == "__main__":
    raise SystemExit(main())
