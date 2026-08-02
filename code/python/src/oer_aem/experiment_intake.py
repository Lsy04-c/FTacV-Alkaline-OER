"""Pure validation for post-experiment intake before a new Gate A1 audit."""

from __future__ import annotations

import hashlib
import math
from pathlib import Path
from typing import Any, Mapping


REQUIRED_CONDITION_ROLES = {
    "baseline_5hz_amp016": "training",
    "lowamp_5hz_amp008": "selection",
    "highfreq_10hz_amp016": "holdout",
}
ACCEPTED_SOURCE_KINDS = {
    "file_observed",
    "derived",
    "externally_declared",
}
REQUIRED_METADATA = {
    "column_contract",
    "original_reference_electrode",
    "rhe_conversion",
    "ph",
    "temperature_K",
    "electrolyte",
    "ir_compensation",
    "instrument_preprocessing",
    "current_basis",
}
PREPROCESSING_KEYS = {
    "filtering",
    "smoothing",
    "averaging",
    "background_subtraction",
    "cropping",
    "downsampling",
    "current_normalization",
}
INDEPENDENT_INPUT_FIELDS = {
    "value",
    "unit",
    "uncertainty",
    "method",
    "source_path",
    "source_sha256",
    "independent_of_ftacv",
}
BATCH_METADATA_FIELDS = {
    "collection_date",
    "operator",
    "electrode_batch",
    "catalyst_batch",
    "substrate",
    "electrolyte_batch",
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _safe_source_path(root: Path, raw: object, label: str):
    if not isinstance(raw, str) or not raw:
        return None, f"{label} path is missing"
    relative = Path(raw)
    if relative.is_absolute() or ".." in relative.parts:
        return None, f"{label} path must be project-relative"
    if relative.parts and relative.parts[0] in {"results", ".git"}:
        return None, f"{label} path must be a source artifact"
    return root / relative, None


def _contains_nonfinite(value: object) -> bool:
    if isinstance(value, float):
        return not math.isfinite(value)
    if isinstance(value, Mapping):
        return any(_contains_nonfinite(item) for item in value.values())
    if isinstance(value, (list, tuple)):
        return any(_contains_nonfinite(item) for item in value)
    return False


def _duplicates(values: list[object]) -> list[str]:
    strings = [str(value) for value in values if isinstance(value, str) and value]
    return sorted({value for value in strings if strings.count(value) > 1})


def _validate_file(
    project_root: Path,
    record: object,
    label: str,
    errors: list[str],
) -> tuple[Path | None, str | None]:
    if not isinstance(record, Mapping):
        errors.append(f"{label} must be an object")
        return None, None
    path, path_error = _safe_source_path(project_root, record.get("path"), label)
    if path_error:
        errors.append(path_error)
        return None, None
    assert path is not None
    if not path.is_file():
        errors.append(f"{label} file does not exist")
        return path, None
    declared_hash = record.get("sha256")
    if not isinstance(declared_hash, str) or len(declared_hash) != 64:
        errors.append(f"{label} sha256 is missing or invalid")
        return path, None
    actual_hash = _sha256(path)
    if declared_hash.lower() != actual_hash:
        errors.append(f"{label} sha256 mismatch")
    size = record.get("size_bytes")
    if not isinstance(size, int) or isinstance(size, bool) or size != path.stat().st_size:
        errors.append(f"{label} size_bytes mismatch")
    return path, actual_hash


def _validate_metadata(
    dataset_id: str,
    metadata: object,
    errors: list[str],
) -> None:
    if not isinstance(metadata, Mapping):
        errors.append(f"{dataset_id} metadata must be an object")
        return
    missing = REQUIRED_METADATA - set(metadata)
    for name in sorted(missing):
        errors.append(f"{dataset_id} metadata missing: {name}")
    for name in sorted(REQUIRED_METADATA & set(metadata)):
        field = metadata[name]
        if not isinstance(field, Mapping):
            errors.append(f"{dataset_id} metadata {name} must be an object")
            continue
        if field.get("source_kind") not in ACCEPTED_SOURCE_KINDS:
            errors.append(f"{dataset_id} metadata {name} has unresolved source")
        if field.get("value") is None:
            errors.append(f"{dataset_id} metadata {name} value is unresolved")
    preprocessing = metadata.get("instrument_preprocessing")
    if isinstance(preprocessing, Mapping):
        value = preprocessing.get("value")
        if value is not None and (
            not isinstance(value, Mapping)
            or set(value) != PREPROCESSING_KEYS
            or any(not isinstance(item, bool) for item in value.values())
        ):
            errors.append(
                f"{dataset_id} instrument_preprocessing must explicitly map every boolean"
            )


def _validate_independent_inputs(
    project_root: Path,
    inputs: object,
    structure_errors: list[str],
    restrictions: list[str],
) -> None:
    if not isinstance(inputs, Mapping):
        structure_errors.append("independent_inputs must be an object")
        return
    if inputs.get("active_site_amount") is None:
        restrictions.append("no_site_normalized_turnover")
    for name in sorted(inputs):
        record = inputs[name]
        if record is None:
            continue
        if not isinstance(record, Mapping):
            structure_errors.append(f"independent input {name} must be null or an object")
            continue
        missing = INDEPENDENT_INPUT_FIELDS - set(record)
        if missing:
            structure_errors.append(
                f"independent input {name} missing fields: {','.join(sorted(missing))}"
            )
            continue
        source_path, path_error = _safe_source_path(
            project_root,
            record.get("source_path"),
            f"independent input {name}",
        )
        if path_error:
            structure_errors.append(path_error)
        elif source_path is None or not source_path.is_file():
            structure_errors.append(f"independent input {name} source file does not exist")
        elif record.get("source_sha256") != _sha256(source_path):
            structure_errors.append(f"independent input {name} source sha256 mismatch")
        if record.get("independent_of_ftacv") is not True:
            restrictions.append(f"not_eligible_as_fixed_input:{name}")


def validate_intake(project_root: Path, manifest: dict) -> dict:
    """Return a deterministic intake status without mutating inputs."""
    root = Path(project_root)
    structure_errors: list[str] = []
    metadata_errors: list[str] = []
    restrictions: list[str] = []
    missing_conditions: list[str] = []

    if not isinstance(manifest, Mapping):
        structure_errors.append("manifest must be an object")
        datasets: list[object] = []
    else:
        datasets_raw = manifest.get("datasets")
        datasets = list(datasets_raw) if isinstance(datasets_raw, list) else []
        if not isinstance(datasets_raw, list):
            structure_errors.append("datasets must be an array")
        if manifest.get("schema_version") != 1:
            structure_errors.append("schema_version must equal 1")
        if manifest.get("manifest_state") not in {"planned", "collected"}:
            structure_errors.append("manifest_state must be planned or collected")
        if _contains_nonfinite(manifest):
            structure_errors.append("manifest contains non-finite values")

    role_freeze = manifest.get("role_freeze", {}) if isinstance(manifest, Mapping) else {}
    if not isinstance(role_freeze, Mapping) or role_freeze.get("roles") != REQUIRED_CONDITION_ROLES:
        structure_errors.append("role_freeze does not match the frozen role table")

    valid_datasets: list[Mapping[str, Any]] = []
    for index, raw_dataset in enumerate(datasets):
        if not isinstance(raw_dataset, Mapping):
            structure_errors.append(f"datasets[{index}] must be an object")
            continue
        valid_datasets.append(raw_dataset)

    for name in ("dataset_id", "experiment_id", "condition_id"):
        for duplicate in _duplicates([row.get(name) for row in valid_datasets]):
            structure_errors.append(f"duplicate {name}: {duplicate}")
    for index, row in enumerate(valid_datasets):
        for name in ("dataset_id", "experiment_id", "condition_id", "batch_id"):
            if not isinstance(row.get(name), str) or not row.get(name):
                structure_errors.append(f"datasets[{index}] {name} is missing")

    any_collected = any(
        row.get("collection_state") == "collected" for row in valid_datasets
    )
    if any_collected:
        if not isinstance(role_freeze, Mapping):
            structure_errors.append("role_freeze must be an object")
        else:
            for name in ("frozen_at", "frozen_by", "role_table_version"):
                if not isinstance(role_freeze.get(name), str) or not role_freeze.get(name):
                    structure_errors.append(f"role_freeze {name} is missing")
        batch = manifest.get("batch") if isinstance(manifest, Mapping) else None
        if not isinstance(batch, Mapping):
            metadata_errors.append("batch metadata must be an object")
        else:
            for name in sorted(BATCH_METADATA_FIELDS):
                if batch.get(name) is None or batch.get(name) == "":
                    metadata_errors.append(f"batch {name} is unresolved")

    condition_records: dict[str, Mapping[str, Any]] = {}
    for condition_id in REQUIRED_CONDITION_ROLES:
        matching = [row for row in valid_datasets if row.get("condition_id") == condition_id]
        if len(matching) != 1:
            structure_errors.append(
                f"condition {condition_id} must have exactly one primary record"
            )
        elif matching:
            condition_records[condition_id] = matching[0]

    raw_hash_by_role: dict[str, str] = {}
    method_paths: list[Path] = []
    for condition_id, expected_role in REQUIRED_CONDITION_ROLES.items():
        dataset = condition_records.get(condition_id)
        if dataset is None:
            missing_conditions.append(condition_id)
            continue
        dataset_id = str(dataset.get("dataset_id") or condition_id)
        if dataset.get("analysis_role") != expected_role:
            structure_errors.append(f"{condition_id} analysis_role must be {expected_role}")
        if dataset.get("sample_role") != "formal_sample":
            structure_errors.append(f"{condition_id} sample_role must be formal_sample")
        state = dataset.get("collection_state")
        if state not in {"planned", "collected"}:
            structure_errors.append(f"{condition_id} has invalid collection_state")
            continue
        if state == "planned":
            missing_conditions.append(condition_id)
            continue
        _, raw_hash = _validate_file(
            root, dataset.get("raw_file"), f"{dataset_id} raw_file", structure_errors
        )
        method_path, _ = _validate_file(
            root,
            dataset.get("method_file"),
            f"{dataset_id} method_file",
            structure_errors,
        )
        if raw_hash is not None:
            raw_hash_by_role[expected_role] = raw_hash
        if method_path is not None and method_path.is_file():
            method_paths.append(method_path.resolve())
        _validate_metadata(dataset_id, dataset.get("metadata"), metadata_errors)

    if (
        raw_hash_by_role.get("training") is not None
        and raw_hash_by_role.get("training") == raw_hash_by_role.get("holdout")
    ):
        structure_errors.append("training and holdout cannot use the same raw file")
    if len(method_paths) != len(set(method_paths)):
        structure_errors.append("each primary record must have a unique method file")

    independent_inputs = (
        manifest.get("independent_inputs", {}) if isinstance(manifest, Mapping) else {}
    )
    _validate_independent_inputs(root, independent_inputs, structure_errors, restrictions)

    structure_errors = sorted(set(structure_errors))
    metadata_errors = sorted(set(metadata_errors))
    restrictions = sorted(set(restrictions))
    missing_set = set(missing_conditions)
    missing_conditions = [
        condition for condition in REQUIRED_CONDITION_ROLES if condition in missing_set
    ]

    if structure_errors:
        status = "FAIL_STRUCTURE"
        next_action = "correct_intake_structure"
    elif metadata_errors:
        status = "FAIL_METADATA"
        next_action = "recover_primary_metadata"
    elif missing_conditions:
        status = "WAITING_FOR_DATA"
        next_action = "await_collection"
    else:
        status = "READY_FOR_A1_AUDIT"
        next_action = "generate_new_batch_a1_registry"

    return {
        "status": status,
        "structure_errors": structure_errors,
        "metadata_errors": metadata_errors,
        "missing_conditions": missing_conditions,
        "reporting_restrictions": restrictions,
        "next_action": next_action,
    }
