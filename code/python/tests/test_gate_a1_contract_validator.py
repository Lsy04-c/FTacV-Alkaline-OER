"""Independent Gate A1 archive validator tests."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import math
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
REGISTRY = ROOT / "config" / "data-contracts" / "gate-a1-datasets.json"
RUNNER = ROOT / "code" / "python" / "scripts" / "audit_experimental_contracts.py"
VALIDATOR = ROOT / "code" / "python" / "scripts" / "validate_gate_a1_contracts.py"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _write_archive(tmp_path, registry_path=REGISTRY):
    runner = _load(RUNNER, "gate_a1_runner_fixture")
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    contracts, summary = runner.evaluate_registry(ROOT, registry)
    archive = tmp_path / "archive"
    runner.write_audit_outputs(
        archive,
        contracts=contracts,
        summary=summary,
        manifest={
            "schema_version": 1,
            "commit": "test",
            "dirty": False,
            "dirty_paths": [],
            "registry_sha256": hashlib.sha256(
                registry_path.read_bytes()
            ).hexdigest(),
        },
    )
    return archive


def test_validator_recomputes_current_archive_as_metadata_failure(tmp_path):
    validator = _load(VALIDATOR, "gate_a1_validator_metadata")
    archive = _write_archive(tmp_path)

    result = validator.validate_archive(ROOT, REGISTRY, archive)

    assert result["gate"] == "FAIL_METADATA"
    assert result["structure_passed"] is True
    assert result["numerical_passed"] is True
    assert result["metadata_passed"] is False
    assert result["eligible_for_inversion"] is False


def test_validator_rejects_tampered_reported_gate(tmp_path):
    validator = _load(VALIDATOR, "gate_a1_validator_tamper")
    archive = _write_archive(tmp_path)
    summary_path = archive / "gate_a1_summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary["gate"] = "PASS"
    summary["eligible_for_inversion"] = True
    summary_path.write_text(json.dumps(summary) + "\n", encoding="utf-8")

    result = validator.validate_archive(ROOT, REGISTRY, archive)

    assert result["gate"] == "FAIL_STRUCTURE"
    assert any(
        "reported summary differs" in error
        for error in result["errors"]["structure"]
    )


def test_validator_rejects_registry_hash_mismatch(tmp_path):
    validator = _load(VALIDATOR, "gate_a1_validator_hash")
    archive = _write_archive(tmp_path)
    manifest_path = archive / "run_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["registry_sha256"] = "0" * 64
    manifest_path.write_text(json.dumps(manifest) + "\n", encoding="utf-8")

    result = validator.validate_archive(ROOT, REGISTRY, archive)

    assert result["gate"] == "FAIL_STRUCTURE"
    assert "registry SHA-256 mismatch" in result["errors"]["structure"]


def test_validator_classifies_nonfinite_archive_as_numerical_failure(
    tmp_path,
):
    validator = _load(VALIDATOR, "gate_a1_validator_nonfinite")
    archive = _write_archive(tmp_path)
    contracts_path = archive / "dataset_contracts.json"
    contracts = json.loads(contracts_path.read_text(encoding="utf-8"))
    contracts["datasets"][0]["diagnostics"]["duration_s"] = math.nan
    contracts_path.write_text(
        json.dumps(contracts, allow_nan=True) + "\n",
        encoding="utf-8",
    )

    result = validator.validate_archive(ROOT, REGISTRY, archive)

    assert result["gate"] == "FAIL_NUMERICAL"
    assert result["numerical_passed"] is False


def test_validator_rejects_missing_dataset_registry(tmp_path):
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    registry["datasets"].pop()
    registry_path = tmp_path / "registry-missing.json"
    registry_path.write_text(
        json.dumps(registry, indent=2) + "\n", encoding="utf-8"
    )
    archive = _write_archive(tmp_path)
    validator = _load(VALIDATOR, "gate_a1_validator_missing")

    result = validator.validate_archive(ROOT, registry_path, archive)

    assert result["gate"] == "FAIL_STRUCTURE"
    assert result["structure_passed"] is False


def test_validator_can_pass_with_primary_metadata_sources(tmp_path):
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    for dataset in registry["datasets"]:
        for field_name in (
            "potential_unit",
            "potential_reference",
            "current_unit",
            "time_unit",
            "instrument_preprocessing",
        ):
            field = dataset["metadata"][field_name]
            field["source_kind"] = "externally_declared"
            if field["value"] is None:
                field["value"] = (
                    "RHE"
                    if field_name == "potential_reference"
                    else "none documented"
                )
    registry_path = tmp_path / "registry.json"
    registry_path.write_text(
        json.dumps(registry, indent=2) + "\n", encoding="utf-8"
    )
    archive = _write_archive(tmp_path, registry_path)
    validator = _load(VALIDATOR, "gate_a1_validator_pass")

    result = validator.validate_archive(ROOT, registry_path, archive)

    assert result["gate"] == "PASS"
    assert result["eligible_for_inversion"] is True
