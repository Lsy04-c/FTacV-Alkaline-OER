"""Tests for the read-only formal-v2 objective-profile evidence validator."""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "code" / "python" / "scripts" / "validate_formal_profile_contract.py"
COMMIT = "c7a9ee1161955377e4beea891b8a3d42b0050a6a"
MODES = ("legacy", "complex_snr", "lockin_only", "hybrid")
PARAMETERS = ("k0_1", "k0_2", "k0_3", "G_OH", "G_O")
TRUTH_PARAMS = {
    "k0_1": 398.1071705534969,
    "k0_2": 0.25118864315095796,
    "k0_3": 158.48931924611142,
    "k0_4": 0.630957344480193,
    "G_OH": 1.4,
    "G_O": 2.68,
    "scaling_OOH_OH": 3.36,
    "gamma": 3.1622776601683795e-09,
}
TRUTH_COORDINATES = {
    "k0_1": 0.7,
    "k0_2": 0.3,
    "k0_3": 0.65,
    "G_OH": 0.6,
    "G_O": 0.4,
}
ROW_FIELDS = (
    "profile_id", "feature_mode", "parameter", "truth_id", "normalized_coordinate",
    "truth_coordinate", "is_truth", "physical_value", "total_loss", "ode_success",
    "tafel_failed", "runtime_seconds", "dc", "common_harmonics",
    "dataset_specific_harmonics", "phase", "lockin_common_amplitude",
    "lockin_dataset_specific_amplitude", "lockin_common_phase",
    "lockin_dataset_specific_phase", "physical",
)


def _full_mask_sha256() -> str:
    return hashlib.sha256((128).to_bytes(8, "big") + b"\xff" * 16).hexdigest()


def _channel_ids() -> tuple[str, ...]:
    return (
        ("dc",)
        + tuple(f"legacy_amplitude:H{harmonic}" for harmonic in range(1, 8))
        + tuple(
            channel
            for harmonic in range(1, 8)
            for channel in (
                f"complex_amplitude:H{harmonic}",
                f"complex_phase:H{harmonic}",
            )
        )
        + tuple(
            channel
            for harmonic in range(1, 8)
            for channel in (
                f"lockin_amplitude:H{harmonic}",
                f"lockin_phase:H{harmonic}",
            )
        )
        + ("tafel",)
    )


def _load_script():
    spec = importlib.util.spec_from_file_location("formal_profile_validator", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _feature_contract(mode: str) -> dict:
    evidence = {
        "schema_version": 2,
        "feature_mode": mode,
        "objective_contract": "formal-v2-no-tafel",
        "tafel_channel_mode": "disabled",
        "fit_harmonics": [1, 2, 3],
        "phase_weight": 1.0,
        "snr_floor": 3.0,
        "normalization_weight_sum": 1.0,
        "channels": [],
    }
    enabled_blocks = {
        "legacy": {"legacy_amplitude"},
        "complex_snr": {"complex_amplitude", "complex_phase"},
        "lockin_only": {"lockin_amplitude", "lockin_phase"},
        "hybrid": {
            "complex_amplitude", "complex_phase", "lockin_amplitude", "lockin_phase",
        },
    }[mode]
    for channel_id in _channel_ids():
        if channel_id == "dc":
            channel = {
                "channel_id": channel_id, "block": "dc", "harmonic": None,
                "role": "global", "requested": True, "available": True,
                "active": True, "target_weight": 1.0, "loss_weight": 1.0,
                "n_points": 128, "mask_sha256": _full_mask_sha256(),
                "exclusion_reason": None,
            }
        elif channel_id == "tafel":
            channel = {
                "channel_id": channel_id, "block": "tafel", "harmonic": None,
                "role": "physical", "requested": False, "available": False,
                "active": False, "target_weight": 0.0, "loss_weight": 0.0,
                "n_points": 0, "mask_sha256": None,
                "exclusion_reason": "disabled_by_objective_contract",
            }
        else:
            block, harmonic_text = channel_id.split(":")
            harmonic = int(harmonic_text.removeprefix("H"))
            requested = harmonic <= 3
            block_enabled = block in enabled_blocks
            active = requested and block_enabled
            channel = {
                "channel_id": channel_id,
                "block": block,
                "harmonic": harmonic,
                "role": "common" if harmonic <= 3 else "dataset_specific",
                "requested": requested,
                "available": active,
                "active": active,
                "target_weight": 1.0 if active else 0.0,
                "loss_weight": 1.0 if active else 0.0,
                "n_points": 128 if active else 0,
                "mask_sha256": (
                    None if block.startswith("complex_") else _full_mask_sha256()
                ) if active else None,
                "exclusion_reason": (
                    None if active else (
                        "mode_disabled" if not block_enabled else "not_requested"
                    )
                ),
            }
        evidence["channels"].append(channel)
    evidence["normalization_weight_sum"] = sum(
        channel["loss_weight"] for channel in evidence["channels"] if channel["active"]
    )
    encoded = json.dumps(evidence, sort_keys=True, separators=(",", ":")).encode()
    return {**evidence, "sha256": hashlib.sha256(encoded).hexdigest()}


def _rehash_contract(contract: dict) -> None:
    body = dict(contract)
    body.pop("sha256")
    contract["sha256"] = hashlib.sha256(
        json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _write_changed_summary(directory: Path, summary: dict) -> None:
    summary_path = directory / "profile_summary.json"
    summary_path.write_text(json.dumps(summary))
    manifest_path = directory / "run_manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["sha256"][summary_path.name] = hashlib.sha256(summary_path.read_bytes()).hexdigest()
    manifest_path.write_text(json.dumps(manifest))


def _write_passing_evidence(directory: Path) -> None:
    directory.mkdir(exist_ok=True)
    configuration = {
        "n_points": 8192,
        "points_per_cycle": 32,
        "feature_grid_size": 128,
        "fit_harmonics": [1, 2, 3],
        "feature_modes": list(MODES),
        "profile_parameters": list(PARAMETERS),
        "truth_id": "mixed_b",
        "grid_points": 41,
        "solver_backend": "lsoda",
        "noise_fraction": 0.0,
        "workers": 8,
        "smoke": False,
        "objective_contract": "formal-v2-no-tafel",
        "tafel_channel_mode": "disabled",
    }
    summaries = []
    rows = []
    for mode in MODES:
        for parameter in PARAMETERS:
            profile_id = f"{mode}__{parameter}"
            contract = _feature_contract(mode)
            summaries.append(
                {
                    "profile_id": profile_id,
                    "feature_mode": mode,
                    "parameter": parameter,
                    "truth_id": "mixed_b",
                    "truth_coordinate": TRUTH_COORDINATES[parameter],
                    "sampled_points": 41,
                    "objective_contract": "formal-v2-no-tafel",
                    "tafel_channel_mode": "disabled",
                    "feature_contract": contract,
                    "feature_contract_sha256": contract["sha256"],
                    "truth_is_global_minimum": True,
                    "truth_loss": 0.0,
                    "finite_fraction": 1.0,
                    "ode_failures": 0,
                    "tafel_failures": 0,
                }
            )
            truth_index = round(TRUTH_COORDINATES[parameter] * 40)
            for index in range(41):
                row = {field: "0.0" for field in ROW_FIELDS}
                row.update(
                    {
                        "profile_id": profile_id,
                        "feature_mode": mode,
                        "parameter": parameter,
                        "truth_id": "mixed_b",
                        "normalized_coordinate": str(
                            TRUTH_COORDINATES[parameter]
                            if index == truth_index else index / 40
                        ),
                        "truth_coordinate": str(TRUTH_COORDINATES[parameter]),
                        "is_truth": str(index == truth_index),
                        "ode_success": "True",
                        "tafel_failed": "False",
                    }
                )
                rows.append(row)
    rows_path = directory / "profile_rows.csv"
    with rows_path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=ROW_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    summary_path = directory / "profile_summary.json"
    summary_path.write_text(
        json.dumps(
            {
                "source_commit": COMMIT,
                "dirty": False,
                "configuration": configuration,
                "expected_profiles": 20,
                "completed_profiles": 20,
                "expected_rows": 820,
                "completed_rows": 820,
                "profiles": summaries,
            }
        )
    )
    manifest = {
        "source_commit": COMMIT,
        "dirty": False,
        "configuration": configuration,
        "tasks": [
            {
                "profile_id": item["profile_id"],
                "feature_mode": item["feature_mode"],
                "parameter": item["parameter"],
                "truth_id": "mixed_b",
                "truth_params": TRUTH_PARAMS,
                "truth_coordinate": TRUTH_COORDINATES[item["parameter"]],
                "grid_points": 41,
                "noise_fraction": 0.0,
                "objective_contract": "formal-v2-no-tafel",
                "tafel_channel_mode": "disabled",
            }
            for item in summaries
        ],
        "sha256": {
            rows_path.name: hashlib.sha256(rows_path.read_bytes()).hexdigest(),
            summary_path.name: hashlib.sha256(summary_path.read_bytes()).hexdigest(),
        },
    }
    (directory / "run_manifest.json").write_text(json.dumps(manifest))


def test_validator_accepts_complete_formal_v2_evidence(tmp_path):
    module = _load_script()
    _write_passing_evidence(tmp_path)

    report = module.validate_formal_profile(tmp_path, expected_commit=COMMIT)

    assert report["gate"] == "PASS"
    assert report["profile_count"] == 20
    assert report["row_count"] == 820


def test_validator_rejects_contract_or_worker_evidence_drift(tmp_path):
    module = _load_script()
    _write_passing_evidence(tmp_path)
    summary_path = tmp_path / "profile_summary.json"
    summary = json.loads(summary_path.read_text())
    summary["profiles"][0]["tafel_channel_mode"] = "legacy_dc_diagnostic"
    summary_path.write_text(json.dumps(summary))
    manifest_path = tmp_path / "run_manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["sha256"][summary_path.name] = hashlib.sha256(
        summary_path.read_bytes()
    ).hexdigest()
    manifest_path.write_text(json.dumps(manifest))

    report = module.validate_formal_profile(tmp_path, expected_commit=COMMIT)

    assert report["gate"] == "FAIL_CONTRACT"
    assert any("tafel_channel_mode" in item for item in report["contract_errors"])


def test_validator_recomputes_truth_global_minimum_from_rows(tmp_path):
    module = _load_script()
    _write_passing_evidence(tmp_path)
    rows_path = tmp_path / "profile_rows.csv"
    rows = list(csv.DictReader(rows_path.open()))
    rows[1]["total_loss"] = "-1.0"
    with rows_path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    manifest_path = tmp_path / "run_manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["sha256"][rows_path.name] = hashlib.sha256(rows_path.read_bytes()).hexdigest()
    manifest_path.write_text(json.dumps(manifest))

    report = module.validate_formal_profile(tmp_path, expected_commit=COMMIT)

    assert report["gate"] == "FAIL_NUMERICAL"
    assert any("truth is not a CSV minimum" in item for item in report["numerical_errors"])


def test_validator_rejects_task_identity_or_truth_provenance_drift(tmp_path):
    module = _load_script()
    _write_passing_evidence(tmp_path)
    manifest_path = tmp_path / "run_manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["tasks"][0]["feature_mode"] = "hybrid"
    manifest["tasks"][0]["truth_params"]["gamma"] = 1.0
    manifest_path.write_text(json.dumps(manifest))

    report = module.validate_formal_profile(tmp_path, expected_commit=COMMIT)

    assert report["gate"] == "FAIL_CONTRACT"
    assert any("task" in item for item in report["contract_errors"])


def test_validator_rejects_semantically_forged_feature_channel(tmp_path):
    module = _load_script()
    _write_passing_evidence(tmp_path)
    summary_path = tmp_path / "profile_summary.json"
    summary = json.loads(summary_path.read_text())
    channel = summary["profiles"][0]["feature_contract"]["channels"][7]
    channel.update({"harmonic": 7, "requested": True, "available": True, "active": True,
                    "target_weight": 1.0, "loss_weight": 1.0, "n_points": 128,
                    "exclusion_reason": None})
    contract = summary["profiles"][0]["feature_contract"]
    _rehash_contract(contract)
    summary["profiles"][0]["feature_contract_sha256"] = contract["sha256"]
    _write_changed_summary(tmp_path, summary)

    report = module.validate_formal_profile(tmp_path, expected_commit=COMMIT)

    assert report["gate"] == "FAIL_CONTRACT"
    assert any("feature_contract" in item for item in report["contract_errors"])


def test_validator_rejects_truth_row_at_wrong_coordinate(tmp_path):
    module = _load_script()
    _write_passing_evidence(tmp_path)
    rows_path = tmp_path / "profile_rows.csv"
    rows = list(csv.DictReader(rows_path.open()))
    truth_index = next(index for index, row in enumerate(rows) if row["is_truth"] == "True")
    rows[truth_index]["normalized_coordinate"] = "1.0"
    with rows_path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    manifest_path = tmp_path / "run_manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["sha256"][rows_path.name] = hashlib.sha256(rows_path.read_bytes()).hexdigest()
    manifest_path.write_text(json.dumps(manifest))

    report = module.validate_formal_profile(tmp_path, expected_commit=COMMIT)

    assert report["gate"] == "FAIL_NUMERICAL"
    assert any("truth coordinate" in item for item in report["numerical_errors"])


def test_validator_rejects_feature_contract_normalization_drift(tmp_path):
    module = _load_script()
    _write_passing_evidence(tmp_path)
    summary = json.loads((tmp_path / "profile_summary.json").read_text())
    contract = summary["profiles"][0]["feature_contract"]
    contract["normalization_weight_sum"] = 1.0
    _rehash_contract(contract)
    summary["profiles"][0]["feature_contract_sha256"] = contract["sha256"]
    _write_changed_summary(tmp_path, summary)

    report = module.validate_formal_profile(tmp_path, expected_commit=COMMIT)

    assert report["gate"] == "FAIL_CONTRACT"
    assert any("normalization_weight_sum" in item for item in report["contract_errors"])


def test_validator_rejects_active_amplitude_phase_pair_drift(tmp_path):
    module = _load_script()
    _write_passing_evidence(tmp_path)
    summary = json.loads((tmp_path / "profile_summary.json").read_text())
    contract = summary["profiles"][5]["feature_contract"]
    channel = next(
        item for item in contract["channels"]
        if item["channel_id"] == "complex_phase:H1"
    )
    channel["loss_weight"] = 0.5
    contract["normalization_weight_sum"] -= 0.5
    _rehash_contract(contract)
    summary["profiles"][5]["feature_contract_sha256"] = contract["sha256"]
    _write_changed_summary(tmp_path, summary)

    report = module.validate_formal_profile(tmp_path, expected_commit=COMMIT)

    assert report["gate"] == "FAIL_CONTRACT"
    assert any("amplitude/phase" in item for item in report["contract_errors"])


def test_validator_rejects_feature_contract_default_drift(tmp_path):
    module = _load_script()
    _write_passing_evidence(tmp_path)
    summary = json.loads((tmp_path / "profile_summary.json").read_text())
    contract = summary["profiles"][5]["feature_contract"]
    contract["phase_weight"] = 0.5
    _rehash_contract(contract)
    summary["profiles"][5]["feature_contract_sha256"] = contract["sha256"]
    _write_changed_summary(tmp_path, summary)

    report = module.validate_formal_profile(tmp_path, expected_commit=COMMIT)

    assert report["gate"] == "FAIL_CONTRACT"
    assert any("phase_weight" in item for item in report["contract_errors"])


def test_validator_rejects_out_of_range_active_lockin_mask_count(tmp_path):
    module = _load_script()
    _write_passing_evidence(tmp_path)
    summary = json.loads((tmp_path / "profile_summary.json").read_text())
    contract = summary["profiles"][10]["feature_contract"]
    for channel in contract["channels"]:
        if channel["channel_id"] in {"lockin_amplitude:H1", "lockin_phase:H1"}:
            channel["n_points"] = 1
            channel["mask_sha256"] = "a" * 64
    _rehash_contract(contract)
    summary["profiles"][10]["feature_contract_sha256"] = contract["sha256"]
    _write_changed_summary(tmp_path, summary)

    report = module.validate_formal_profile(tmp_path, expected_commit=COMMIT)

    assert report["gate"] == "FAIL_CONTRACT"
    assert any("lock-in" in item for item in report["contract_errors"])


def test_validator_rejects_forged_enabled_inactive_reason(tmp_path):
    module = _load_script()
    _write_passing_evidence(tmp_path)
    summary = json.loads((tmp_path / "profile_summary.json").read_text())
    contract = summary["profiles"][5]["feature_contract"]
    for channel in contract["channels"]:
        if channel["channel_id"] in {"complex_amplitude:H1", "complex_phase:H1"}:
            channel.update(
                {
                    "available": True,
                    "active": False,
                    "target_weight": 0.0,
                    "loss_weight": 0.0,
                    "n_points": 0,
                    "exclusion_reason": "forged_reason",
                }
            )
    contract["normalization_weight_sum"] -= 2.0
    _rehash_contract(contract)
    summary["profiles"][5]["feature_contract_sha256"] = contract["sha256"]
    _write_changed_summary(tmp_path, summary)

    report = module.validate_formal_profile(tmp_path, expected_commit=COMMIT)

    assert report["gate"] == "FAIL_CONTRACT"
    assert any("inactive reason" in item for item in report["contract_errors"])


def test_validator_rejects_numeric_zero_for_disabled_tafel_state(tmp_path):
    module = _load_script()
    _write_passing_evidence(tmp_path)
    summary = json.loads((tmp_path / "profile_summary.json").read_text())
    contract = summary["profiles"][0]["feature_contract"]
    tafel = next(item for item in contract["channels"] if item["channel_id"] == "tafel")
    tafel.update({"requested": 0, "available": 0, "active": 0})
    _rehash_contract(contract)
    summary["profiles"][0]["feature_contract_sha256"] = contract["sha256"]
    _write_changed_summary(tmp_path, summary)

    report = module.validate_formal_profile(tmp_path, expected_commit=COMMIT)

    assert report["gate"] == "FAIL_CONTRACT"
    assert any("disabled Tafel" in item for item in report["contract_errors"])


def test_validator_rejects_impossible_available_but_inactive_legacy_channel(tmp_path):
    module = _load_script()
    _write_passing_evidence(tmp_path)
    summary = json.loads((tmp_path / "profile_summary.json").read_text())
    contract = summary["profiles"][0]["feature_contract"]
    channel = next(
        item for item in contract["channels"]
        if item["channel_id"] == "legacy_amplitude:H1"
    )
    channel.update(
        {
            "available": True,
            "active": False,
            "target_weight": 0.0,
            "loss_weight": 0.0,
            "n_points": 0,
            "mask_sha256": None,
            "exclusion_reason": "insufficient_valid_points",
        }
    )
    contract["normalization_weight_sum"] -= 1.0
    _rehash_contract(contract)
    summary["profiles"][0]["feature_contract_sha256"] = contract["sha256"]
    _write_changed_summary(tmp_path, summary)

    report = module.validate_formal_profile(tmp_path, expected_commit=COMMIT)

    assert report["gate"] == "FAIL_CONTRACT"
    assert any("legacy" in item for item in report["contract_errors"])
