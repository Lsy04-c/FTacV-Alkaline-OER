"""Gate A1 registry and formal experimental-contract audit tests."""

from __future__ import annotations

import json
import importlib.util
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[3]
REGISTRY = ROOT / "config" / "data-contracts" / "gate-a1-datasets.json"
SCRIPT = ROOT / "code" / "python" / "scripts" / "audit_experimental_contracts.py"

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


def test_gate_a1_registry_freezes_four_datasets_and_sources():
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))

    assert registry["schema_version"] == 1
    assert registry["gate_version"] == 1
    datasets = registry["datasets"]
    assert {item["dataset_id"] for item in datasets} == {
        "FT2",
        "FT3",
        "FT4",
        "FT8",
    }
    assert len(datasets) == 4
    for item in datasets:
        assert not Path(item["path"]).is_absolute()
        assert item["expected_rows"] == 65536
        assert len(item["sha256"]) == 64
        assert set(item["metadata"]) == REQUIRED_METADATA
        assert all(
            field["source_kind"]
            in {
                "file_observed",
                "derived",
                "externally_declared",
                "legacy_assumption",
                "unresolved",
            }
            for field in item["metadata"].values()
        )


def test_gate_a1_registry_records_user_declaration_without_resolving_preprocessing():
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    declared = {
        "potential_unit": "V",
        "potential_reference": "RHE",
        "current_unit": "A",
        "time_unit": "s",
    }

    for dataset in registry["datasets"]:
        metadata = dataset["metadata"]
        for field_name, expected_value in declared.items():
            field = metadata[field_name]
            assert field["value"] == expected_value
            assert field["source_kind"] == "externally_declared"
            assert "Project lead declaration" in field["source_note"]
            assert (
                "not the original experiment operator"
                in field["source_note"]
            )

        preprocessing = metadata["instrument_preprocessing"]
        assert preprocessing["value"] is None
        assert preprocessing["source_kind"] == "unresolved"
        assert (
            "No processing other than RHE correction was reported"
            in preprocessing["source_note"]
        )
        assert (
            "cannot independently verify"
            in preprocessing["source_note"]
        )


def _load_script():
    spec = importlib.util.spec_from_file_location(
        "audit_experimental_contracts", SCRIPT
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_runner_classifies_current_real_data_as_metadata_failure():
    module = _load_script()
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))

    contracts, summary = module.evaluate_registry(ROOT, registry)

    assert len(contracts["datasets"]) == 4
    assert summary["gate"] == "FAIL_METADATA"
    assert summary["structure_passed"] is True
    assert summary["numerical_passed"] is True
    assert summary["metadata_passed"] is False
    assert summary["eligible_for_inversion"] is False
    for dataset in contracts["datasets"]:
        assert dataset["file_facts"]["n_rows"] == 65536
        assert dataset["checks"]["structure_passed"] is True
        assert dataset["checks"]["numerical_passed"] is True
        assert dataset["missing_metadata"] == ["instrument_preprocessing"]
        assert (
            dataset["metadata"]["potential_reference"]["resolved_value"]
            == "RHE"
        )


def test_runner_rejects_hash_mismatch_as_structure_failure():
    module = _load_script()
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    registry["datasets"][0]["sha256"] = "0" * 64

    _, summary = module.evaluate_registry(ROOT, registry)

    assert summary["gate"] == "FAIL_STRUCTURE"
    assert summary["structure_passed"] is False
    assert summary["eligible_for_inversion"] is False


def test_runner_writes_deterministic_finite_json(tmp_path):
    module = _load_script()
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    contracts, summary = module.evaluate_registry(ROOT, registry)
    output = tmp_path / "audit"

    module.write_audit_outputs(
        output,
        contracts=contracts,
        summary=summary,
        manifest={"schema_version": 1, "commit": "test"},
    )

    assert set(path.name for path in output.iterdir()) == {
        "dataset_contracts.json",
        "gate_a1_summary.json",
        "run_manifest.json",
    }
    for path in output.iterdir():
        text = path.read_text(encoding="utf-8")
        assert text.endswith("\n")
        assert "NaN" not in text
        assert "Infinity" not in text
        json.loads(text)
    with pytest.raises(FileExistsError, match="new or empty"):
        module.write_audit_outputs(
            output,
            contracts=contracts,
            summary=summary,
            manifest={"schema_version": 1, "commit": "test"},
        )
