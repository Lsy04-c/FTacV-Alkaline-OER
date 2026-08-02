"""Unit contracts for the pre-Gate-A1 experiment intake layer."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

from oer_aem.experiment_intake import validate_intake


ROOT = Path(__file__).resolve().parents[3]
TEMPLATE = (
    ROOT
    / "config"
    / "data-contracts"
    / "post-experiment-intake-v1.template.json"
)

CONDITIONS = (
    ("baseline_5hz_amp016", "training"),
    ("lowamp_5hz_amp008", "selection"),
    ("highfreq_10hz_amp016", "holdout"),
)
PREPROCESSING = {
    "filtering": False,
    "smoothing": False,
    "averaging": False,
    "background_subtraction": False,
    "cropping": False,
    "downsampling": False,
    "current_normalization": False,
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _sourced(value):
    return {
        "value": value,
        "source_kind": "externally_declared",
        "source_note": "test fixture",
    }


def collected_manifest(root: Path) -> dict:
    source = root / "data" / "raw"
    source.mkdir(parents=True, exist_ok=True)
    datasets = []
    for index, (condition_id, role) in enumerate(CONDITIONS, start=1):
        raw = source / f"condition-{index}.txt"
        method = source / f"condition-{index}.method.txt"
        raw.write_text(
            f"0.10 {index}.0e-6 0.00\n0.11 {index}.1e-6 0.01\n",
            encoding="utf-8",
        )
        method.write_text(f"frequency={5 if index < 3 else 10}\n", encoding="utf-8")
        metadata = {
            "column_contract": _sourced(
                ["potential_V_vs_RHE", "current_A", "time_s"]
            ),
            "original_reference_electrode": _sourced("Ag/AgCl"),
            "rhe_conversion": _sourced("declared conversion record"),
            "ph": _sourced(13.0),
            "temperature_K": _sourced(298.15),
            "electrolyte": _sourced("1 M KOH"),
            "ir_compensation": _sourced({"enabled": False, "fraction": 0.0}),
            "instrument_preprocessing": _sourced(dict(PREPROCESSING)),
            "current_basis": _sourced("total_current_A"),
        }
        datasets.append(
            {
                "collection_state": "collected",
                "dataset_id": f"dataset-{index}",
                "condition_id": condition_id,
                "analysis_role": role,
                "experiment_id": f"experiment-{index}",
                "batch_id": "batch-test",
                "sample_role": "formal_sample",
                "raw_file": {
                    "path": raw.relative_to(root).as_posix(),
                    "sha256": _sha256(raw),
                    "size_bytes": raw.stat().st_size,
                },
                "method_file": {
                    "path": method.relative_to(root).as_posix(),
                    "sha256": _sha256(method),
                    "size_bytes": method.stat().st_size,
                },
                "metadata": metadata,
            }
        )
    return {
        "schema_version": 1,
        "intake_id": "test-intake-v1",
        "manifest_state": "collected",
        "role_freeze": {
            "frozen_at": "2026-08-02T00:00:00+08:00",
            "frozen_by": "test-owner",
            "role_table_version": "v1",
            "roles": {condition: role for condition, role in CONDITIONS},
        },
        "batch": {
            "collection_date": "2026-08-02",
            "operator": "test-operator",
            "electrode_batch": "electrode-1",
            "catalyst_batch": "catalyst-1",
            "substrate": "glassy-carbon",
            "electrolyte_batch": "electrolyte-1",
        },
        "datasets": datasets,
        "independent_inputs": {
            "Ru": None,
            "Cdl": None,
            "geometric_area": None,
            "catalyst_loading": None,
            "active_site_amount": None,
        },
    }


def test_empty_frozen_template_waits_for_data():
    manifest = json.loads(TEMPLATE.read_text(encoding="utf-8"))
    result = validate_intake(ROOT, manifest)
    assert result["status"] == "WAITING_FOR_DATA"
    assert result["missing_conditions"] == [
        "baseline_5hz_amp016",
        "lowamp_5hz_amp008",
        "highfreq_10hz_amp016",
    ]
    assert result["structure_errors"] == []
    assert result["metadata_errors"] == []


def test_collected_record_with_missing_file_is_structure_failure(tmp_path):
    manifest = collected_manifest(tmp_path)
    manifest["datasets"][0]["raw_file"]["path"] = "data/raw/missing.txt"
    result = validate_intake(tmp_path, manifest)
    assert result["status"] == "FAIL_STRUCTURE"


def test_holdout_role_cannot_be_reassigned(tmp_path):
    manifest = collected_manifest(tmp_path)
    manifest["datasets"][2]["analysis_role"] = "training"
    assert validate_intake(tmp_path, manifest)["status"] == "FAIL_STRUCTURE"


def test_same_raw_file_cannot_serve_training_and_holdout(tmp_path):
    manifest = collected_manifest(tmp_path)
    manifest["datasets"][2]["raw_file"] = dict(manifest["datasets"][0]["raw_file"])
    assert validate_intake(tmp_path, manifest)["status"] == "FAIL_STRUCTURE"


def test_unknown_preprocessing_is_metadata_failure(tmp_path):
    manifest = collected_manifest(tmp_path)
    manifest["datasets"][0]["metadata"]["instrument_preprocessing"] = {
        "value": None,
        "source_kind": "unresolved",
        "source_note": "unknown",
    }
    assert validate_intake(tmp_path, manifest)["status"] == "FAIL_METADATA"


def test_complete_collected_manifest_is_ready_for_a1(tmp_path):
    result = validate_intake(tmp_path, collected_manifest(tmp_path))
    assert result["status"] == "READY_FOR_A1_AUDIT"
    assert result["next_action"] == "generate_new_batch_a1_registry"


def test_missing_active_site_amount_only_adds_reporting_restriction(tmp_path):
    manifest = collected_manifest(tmp_path)
    manifest["independent_inputs"]["active_site_amount"] = None
    result = validate_intake(tmp_path, manifest)
    assert result["status"] == "READY_FOR_A1_AUDIT"
    assert "no_site_normalized_turnover" in result["reporting_restrictions"]


def test_changed_raw_byte_is_structure_failure(tmp_path):
    manifest = collected_manifest(tmp_path)
    raw = tmp_path / manifest["datasets"][0]["raw_file"]["path"]
    raw.write_text(raw.read_text(encoding="utf-8") + "changed\n", encoding="utf-8")
    result = validate_intake(tmp_path, manifest)
    assert result["status"] == "FAIL_STRUCTURE"
    assert any("sha256" in error for error in result["structure_errors"])


def test_wrong_method_hash_is_structure_failure(tmp_path):
    manifest = collected_manifest(tmp_path)
    manifest["datasets"][0]["method_file"]["sha256"] = "0" * 64
    result = validate_intake(tmp_path, manifest)
    assert result["status"] == "FAIL_STRUCTURE"
    assert any("method_file sha256" in error for error in result["structure_errors"])


def test_duplicate_experiment_id_is_structure_failure(tmp_path):
    manifest = collected_manifest(tmp_path)
    manifest["datasets"][1]["experiment_id"] = manifest["datasets"][0]["experiment_id"]
    result = validate_intake(tmp_path, manifest)
    assert result["status"] == "FAIL_STRUCTURE"
    assert any("experiment_id" in error for error in result["structure_errors"])


def test_missing_dataset_identity_is_structure_failure(tmp_path):
    manifest = collected_manifest(tmp_path)
    manifest["datasets"][0]["experiment_id"] = ""
    result = validate_intake(tmp_path, manifest)
    assert result["status"] == "FAIL_STRUCTURE"
    assert any("experiment_id is missing" in error for error in result["structure_errors"])


def test_method_file_cannot_be_reused_across_primary_records(tmp_path):
    manifest = collected_manifest(tmp_path)
    manifest["datasets"][1]["method_file"] = dict(
        manifest["datasets"][0]["method_file"]
    )
    result = validate_intake(tmp_path, manifest)
    assert result["status"] == "FAIL_STRUCTURE"
    assert any("method file" in error for error in result["structure_errors"])


def test_collected_manifest_requires_role_freeze_provenance(tmp_path):
    manifest = collected_manifest(tmp_path)
    manifest["role_freeze"]["frozen_at"] = None
    result = validate_intake(tmp_path, manifest)
    assert result["status"] == "FAIL_STRUCTURE"
    assert any("role_freeze frozen_at" in error for error in result["structure_errors"])


def test_collected_manifest_requires_batch_metadata(tmp_path):
    manifest = collected_manifest(tmp_path)
    manifest["batch"]["operator"] = None
    result = validate_intake(tmp_path, manifest)
    assert result["status"] == "FAIL_METADATA"
    assert any("batch operator" in error for error in result["metadata_errors"])


def test_unsafe_source_paths_are_structure_failures(tmp_path):
    for path in ("/tmp/raw.txt", "../raw.txt", "results/raw.txt"):
        manifest = collected_manifest(tmp_path)
        manifest["datasets"][0]["raw_file"]["path"] = path
        assert validate_intake(tmp_path, manifest)["status"] == "FAIL_STRUCTURE"


def test_nonfinite_manifest_value_is_structure_failure(tmp_path):
    manifest = collected_manifest(tmp_path)
    manifest["batch"]["temperature_note"] = float("nan")
    result = validate_intake(tmp_path, manifest)
    assert result["status"] == "FAIL_STRUCTURE"
    assert any("non-finite" in error for error in result["structure_errors"])


def test_nonindependent_inputs_are_not_eligible_to_be_fixed(tmp_path):
    manifest = collected_manifest(tmp_path)
    source = tmp_path / "data" / "raw" / "ru-source.txt"
    source.write_text("Ru derived from FTacV fit\n", encoding="utf-8")
    manifest["independent_inputs"]["Ru"] = {
        "value": 12.0,
        "unit": "ohm",
        "uncertainty": 1.0,
        "method": "FTacV fit",
        "source_path": source.relative_to(tmp_path).as_posix(),
        "source_sha256": _sha256(source),
        "independent_of_ftacv": False,
    }
    result = validate_intake(tmp_path, manifest)
    assert result["status"] == "READY_FOR_A1_AUDIT"
    assert "not_eligible_as_fixed_input:Ru" in result["reporting_restrictions"]


def test_validation_does_not_mutate_manifest(tmp_path):
    manifest = collected_manifest(tmp_path)
    before = copy.deepcopy(manifest)
    validate_intake(tmp_path, manifest)
    assert manifest == before
