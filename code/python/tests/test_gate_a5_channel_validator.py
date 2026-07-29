"""Independent Gate A5 archive validator tests."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[3]
SCRIPT = (
    ROOT
    / "code"
    / "python"
    / "scripts"
    / "validate_gate_a5_channels.py"
)
DATASETS = ("FT2", "FT3", "FT4", "FT8")
MODES = ("legacy", "complex_snr", "lockin_only", "hybrid")
ARTIFACTS = (
    "channel_contracts.jsonl",
    "candidate_invariance.jsonl",
    "gate_a5_summary.json",
)


def _load_script():
    spec = importlib.util.spec_from_file_location(
        "validate_gate_a5_channels", SCRIPT
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _canonical_sha256(value) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode()
    ).hexdigest()


def _contract(mode: str) -> dict:
    value = {
        "schema_version": 1,
        "feature_mode": mode,
        "fit_harmonics": [1, 2, 3],
        "phase_weight": 0.25,
        "snr_floor": 3.0,
        "normalization_weight_sum": 1.0,
        "channels": [
            {
                "channel_id": "dc",
                "block": "dc",
                "harmonic": None,
                "role": "global",
                "requested": True,
                "available": True,
                "active": True,
                "target_weight": 1.0,
                "loss_weight": 1.0,
                "n_points": 64,
                "mask_sha256": "a" * 64,
                "exclusion_reason": None,
            },
            {
                "channel_id": "legacy_amplitude:H7",
                "block": "legacy_amplitude",
                "harmonic": 7,
                "role": "dataset_specific",
                "requested": False,
                "available": False,
                "active": False,
                "target_weight": 0.0,
                "loss_weight": 0.0,
                "n_points": 0,
                "mask_sha256": None,
                "exclusion_reason": "not_requested",
            },
        ],
    }
    return {**value, "sha256": _canonical_sha256(value)}


def _archive_records() -> tuple[list[dict], list[dict]]:
    contracts = []
    invariance = []
    for dataset in DATASETS:
        for mode in MODES:
            contract = _contract(mode)
            contracts.append(
                {
                    "dataset_id": dataset,
                    "feature_mode": mode,
                    "source_path": f"data/raw/{dataset}.txt",
                    "source_sha256": "b" * 64,
                    "channel_contract": contract,
                }
            )
            invariance.append(
                {
                    "dataset_id": dataset,
                    "feature_mode": mode,
                    "candidate_a_contract_sha256": contract["sha256"],
                    "candidate_b_contract_sha256": contract["sha256"],
                    "candidate_a_normalization_weight_sum": 1.0,
                    "candidate_b_normalization_weight_sum": 1.0,
                    "candidate_a_active_channel_ids": ["dc"],
                    "candidate_b_active_channel_ids": ["dc"],
                    "injected_failure_value": 1e9,
                    "feature_fail_penalty": 1e9,
                    "n_feature_fail_delta": 1,
                }
            )
    return contracts, invariance


def _write_json(path: Path, value) -> None:
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def _write_jsonl(path: Path, records: list[dict]) -> None:
    path.write_text(
        "".join(
            json.dumps(
                item,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
            + "\n"
            for item in records
        ),
        encoding="utf-8",
    )


def _refresh_manifest(archive: Path) -> None:
    manifest_path = archive / "run_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["artifact_sha256"] = {
        name: hashlib.sha256((archive / name).read_bytes()).hexdigest()
        for name in ARTIFACTS
    }
    _write_json(manifest_path, manifest)


def _refresh_summary_hash_count(
    archive: Path,
    contracts: list[dict],
) -> None:
    summary_path = archive / "gate_a5_summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary["unique_contract_hash_count"] = len(
        {
            item["channel_contract"]["sha256"]
            for item in contracts
        }
    )
    _write_json(summary_path, summary)


def _make_archive(tmp_path: Path) -> Path:
    archive = tmp_path / "gate-a5"
    archive.mkdir()
    contracts, invariance = _archive_records()
    _write_jsonl(archive / ARTIFACTS[0], contracts)
    _write_jsonl(archive / ARTIFACTS[1], invariance)
    _write_json(
        archive / ARTIFACTS[2],
        {
            "schema_version": 1,
            "gate_version": "A5",
            "gate": "PASS",
            "record_count": 16,
            "unique_contract_hash_count": 4,
            "structure_passed": True,
            "contract_passed": True,
            "eligible_for_tpe": False,
            "structure_errors": [],
            "contract_errors": {},
        },
    )
    _write_json(
        archive / "run_manifest.json",
        {
            "schema_version": 1,
            "gate_version": "A5",
            "commit": "1" * 40,
            "dirty": False,
            "dirty_paths": [],
            "runs_tpe": False,
            "artifact_sha256": {},
        },
    )
    _refresh_manifest(archive)
    return archive


def test_validator_accepts_complete_independently_hashed_archive(tmp_path):
    module = _load_script()
    archive = _make_archive(tmp_path)

    report = module.validate_archive(archive)

    assert report["gate"] == "PASS"
    assert report["record_count"] == 16
    source = SCRIPT.read_text(encoding="utf-8")
    assert "audit_feature_channel_contracts" not in source
    assert "oer_aem.inversion" not in source


@pytest.mark.parametrize(
    ("mutation", "expected_gate"),
    [
        ("missing_file", "FAIL_STRUCTURE"),
        ("duplicate_contract", "FAIL_STRUCTURE"),
        ("artifact_hash", "FAIL_STRUCTURE"),
        ("nonfinite", "FAIL_NUMERICAL"),
        ("invalid_reason", "FAIL_CONTRACT"),
        ("zero_active_weight", "FAIL_CONTRACT"),
        ("contract_hash", "FAIL_CONTRACT"),
        ("candidate_hash", "FAIL_CONTRACT"),
        ("normalization_drift", "FAIL_CONTRACT"),
        ("missing_failure_injection", "FAIL_CONTRACT"),
        ("runner_summary", "FAIL_STRUCTURE"),
    ],
)
def test_validator_rejects_archive_tampering(
    tmp_path,
    mutation,
    expected_gate,
):
    module = _load_script()
    archive = _make_archive(tmp_path)
    contracts_path = archive / "channel_contracts.jsonl"
    invariance_path = archive / "candidate_invariance.jsonl"
    summary_path = archive / "gate_a5_summary.json"
    contracts = [
        json.loads(line)
        for line in contracts_path.read_text(encoding="utf-8").splitlines()
    ]
    invariance = [
        json.loads(line)
        for line in invariance_path.read_text(encoding="utf-8").splitlines()
    ]
    if mutation == "missing_file":
        summary_path.unlink()
    elif mutation == "duplicate_contract":
        contracts[-1] = contracts[0]
        _write_jsonl(contracts_path, contracts)
        _refresh_manifest(archive)
    elif mutation == "artifact_hash":
        contracts_path.write_bytes(contracts_path.read_bytes() + b"\n")
    elif mutation == "nonfinite":
        text = contracts_path.read_text(encoding="utf-8")
        contracts_path.write_text(
            text.replace(
                '"normalization_weight_sum":1.0',
                '"normalization_weight_sum":NaN',
                1,
            ),
            encoding="utf-8",
        )
        _refresh_manifest(archive)
    elif mutation == "invalid_reason":
        contracts[0]["channel_contract"]["channels"][1][
            "exclusion_reason"
        ] = "unknown"
        contract = contracts[0]["channel_contract"]
        contract["sha256"] = _canonical_sha256(
            {key: value for key, value in contract.items() if key != "sha256"}
        )
        _write_jsonl(contracts_path, contracts)
        _refresh_summary_hash_count(archive, contracts)
        _refresh_manifest(archive)
    elif mutation == "zero_active_weight":
        contracts[0]["channel_contract"]["channels"][0]["loss_weight"] = 0.0
        contract = contracts[0]["channel_contract"]
        contract["sha256"] = _canonical_sha256(
            {key: value for key, value in contract.items() if key != "sha256"}
        )
        _write_jsonl(contracts_path, contracts)
        _refresh_summary_hash_count(archive, contracts)
        _refresh_manifest(archive)
    elif mutation == "contract_hash":
        contracts[0]["channel_contract"]["sha256"] = "0" * 64
        _write_jsonl(contracts_path, contracts)
        _refresh_summary_hash_count(archive, contracts)
        _refresh_manifest(archive)
    elif mutation == "candidate_hash":
        invariance[0]["candidate_b_contract_sha256"] = "0" * 64
        _write_jsonl(invariance_path, invariance)
        _refresh_manifest(archive)
    elif mutation == "normalization_drift":
        invariance[0]["candidate_b_normalization_weight_sum"] = 2.0
        _write_jsonl(invariance_path, invariance)
        _refresh_manifest(archive)
    elif mutation == "missing_failure_injection":
        invariance[0].pop("n_feature_fail_delta")
        _write_jsonl(invariance_path, invariance)
        _refresh_manifest(archive)
    elif mutation == "runner_summary":
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        summary["record_count"] = 15
        _write_json(summary_path, summary)
        _refresh_manifest(archive)

    report = module.validate_archive(archive)

    assert report["gate"] == expected_gate
