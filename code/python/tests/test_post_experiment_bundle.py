import json
import hashlib
from pathlib import Path

import numpy as np

from oer_aem.post_experiment import build_post_experiment_bundle


def _manifest(raw_path, method_path, *, state="planned"):
    roles = {
        "baseline_5hz_amp016": "training",
        "lowamp_5hz_amp008": "selection",
        "highfreq_10hz_amp016": "holdout",
    }
    datasets = []
    for index, (condition, role) in enumerate(roles.items()):
        datasets.append(
            {
                "dataset_id": f"d{index}", "experiment_id": f"e{index}",
                "batch_id": "b1", "condition_id": condition,
                "analysis_role": role, "sample_role": "formal_sample",
                "collection_state": state,
                "raw_file": {"path": str(raw_path), "sha256": "0" * 64, "size_bytes": 1},
                "method_file": {"path": str(method_path), "sha256": "0" * 64, "size_bytes": 1},
                "metadata": {
                    key: {"value": "x", "source_kind": "externally_declared"}
                    for key in ("column_contract", "original_reference_electrode", "rhe_conversion", "ph", "temperature_K", "electrolyte", "ir_compensation", "instrument_preprocessing", "current_basis")
                },
            }
        )
    return {
        "schema_version": 1, "manifest_state": state, "intake_id": "i1",
        "role_freeze": {"roles": roles}, "datasets": datasets,
        "independent_inputs": {},
    }


def test_bundle_waits_without_collected_data(tmp_path):
    raw = tmp_path / "raw.txt"; raw.write_text("0 0 0\n")
    method = tmp_path / "method.txt"; method.write_text("method\n")
    manifest = _manifest(raw, method)
    manifest_path = tmp_path / "manifest.json"; manifest_path.write_text(json.dumps(manifest))
    summary = build_post_experiment_bundle(tmp_path, manifest_path, tmp_path / "bundle")
    assert summary["status"] == "WAITING_FOR_DATA"
    assert not (tmp_path / "bundle" / "targets.npz").exists()


def test_bundle_rejects_nonready_metadata_before_reading_arrays(tmp_path):
    raw = tmp_path / "raw.txt"; raw.write_text("0 0 0\n")
    method = tmp_path / "method.txt"; method.write_text("method\n")
    manifest = _manifest(raw, method, state="collected")
    manifest["batch"] = {"collection_date": "x", "operator": "x", "electrode_batch": "x", "catalyst_batch": "x", "substrate": "x", "electrolyte_batch": "x"}
    manifest_path = tmp_path / "manifest.json"; manifest_path.write_text(json.dumps(manifest))
    summary = build_post_experiment_bundle(tmp_path, manifest_path, tmp_path / "bundle")
    assert summary["status"] in {"FAIL_STRUCTURE", "FAIL_METADATA"}


def _record(path: Path) -> dict:
    payload = path.read_bytes()
    return {
        "path": path.name,
        "sha256": hashlib.sha256(payload).hexdigest(),
        "size_bytes": len(payload),
    }


def _collected_fixture(tmp_path):
    source = np.loadtxt(
        Path(__file__).parents[3] / "data" / "raw" / "ftacv4-ref-1hz.txt"
    )[::4]
    roles = {
        "baseline_5hz_amp016": "training",
        "lowamp_5hz_amp008": "selection",
        "highfreq_10hz_amp016": "holdout",
    }
    datasets = []
    for index, (condition, role) in enumerate(roles.items()):
        raw_path = tmp_path / f"raw_{index}.txt"
        values = source.copy()
        values[:, 1] = values[:, 1] * (1.0 + index * 1e-3) + index * 1e-9
        np.savetxt(raw_path, values, fmt="%.10g")
        method_path = tmp_path / f"method_{index}.txt"
        method_path.write_text(f"method-{index}\n", encoding="utf-8")
        metadata = {
            key: {"value": "x", "source_kind": "externally_declared"}
            for key in (
                "column_contract", "original_reference_electrode", "rhe_conversion",
                "ph", "temperature_K", "electrolyte", "ir_compensation",
                "current_basis",
            )
        }
        metadata["instrument_preprocessing"] = {
            "value": {
                "filtering": False, "smoothing": False, "averaging": False,
                "background_subtraction": False, "cropping": False,
                "downsampling": False, "current_normalization": False,
            },
            "source_kind": "externally_declared",
        }
        datasets.append({
            "dataset_id": f"d{index}", "experiment_id": f"e{index}",
            "batch_id": "b1", "condition_id": condition,
            "analysis_role": role, "sample_role": "formal_sample",
            "collection_state": "collected",
            "raw_file": _record(raw_path),
            "method_file": _record(method_path),
            "metadata": metadata,
        })

    independent_path = tmp_path / "independent_inputs.txt"
    independent_path.write_text("independent\n", encoding="utf-8")
    independent_hash = hashlib.sha256(independent_path.read_bytes()).hexdigest()
    independent = {}
    for name in ("Ru", "CdlA", "A", "GammaA", "load"):
        independent[name] = {
            "value": 1.0, "unit": "arb", "uncertainty": 0.1,
            "method": "independent-test-fixture",
            "source_path": str(independent_path.relative_to(tmp_path)),
            "source_sha256": independent_hash,
            "independent_of_ftacv": True,
        }
    manifest = {
        "schema_version": 1, "manifest_state": "collected", "intake_id": "i1",
        "role_freeze": {
            "roles": roles, "frozen_at": "2026-08-09", "frozen_by": "test",
            "role_table_version": "v1",
        },
        "batch": {
            "collection_date": "2026-08-09", "operator": "test",
            "electrode_batch": "e", "catalyst_batch": "c", "substrate": "s",
            "electrolyte_batch": "koh",
        },
        "datasets": datasets,
        "independent_inputs": independent,
    }
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    return manifest_path, datasets


def test_collected_bundle_rebuild_is_byte_deterministic(tmp_path):
    manifest_path, _ = _collected_fixture(tmp_path)
    first = build_post_experiment_bundle(
        tmp_path, manifest_path, tmp_path / "bundle_a"
    )
    second = build_post_experiment_bundle(
        tmp_path, manifest_path, tmp_path / "bundle_b"
    )
    assert first["status"] == second["status"] == "TARGET_BUNDLE_READY"
    assert first["array_sha256"] == second["array_sha256"]
    np.testing.assert_equal(
        np.load(tmp_path / "bundle_a" / "targets.npz")["baseline_5hz_amp016__dc"],
        np.load(tmp_path / "bundle_b" / "targets.npz")["baseline_5hz_amp016__dc"],
    )


def test_collected_bundle_records_role_policy_and_code_provenance(tmp_path):
    manifest_path, _ = _collected_fixture(tmp_path)
    summary = build_post_experiment_bundle(
        tmp_path, manifest_path, tmp_path / "bundle"
    )
    persisted = json.loads((tmp_path / "bundle" / "bundle_summary.json").read_text())

    assert summary["parameter_role_policy"]["free_parameters"] == [
        "k0_2", "k0_3", "G_OH", "G_O",
    ]
    assert len(summary["parameter_role_policy_sha256"]) == 64
    assert persisted["parameter_role_policy_sha256"] == summary[
        "parameter_role_policy_sha256"
    ]
    assert set(summary["code_provenance"]) == {"source_commit", "dirty"}


def test_collected_bundle_rejects_raw_hash_conflict(tmp_path):
    manifest_path, datasets = _collected_fixture(tmp_path)
    raw_path = tmp_path / datasets[0]["raw_file"]["path"]
    raw_path.write_text(raw_path.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    summary = build_post_experiment_bundle(
        tmp_path, manifest_path, tmp_path / "bundle_conflict"
    )
    assert summary["status"] == "FAIL_STRUCTURE"
    assert any("sha256 mismatch" in item for item in summary["intake"]["structure_errors"])
    assert not (tmp_path / "bundle_conflict" / "targets.npz").exists()
