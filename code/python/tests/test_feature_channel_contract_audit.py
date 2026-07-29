"""Gate A5 feature-channel contract audit tests."""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest
import numpy as np

from oer_aem.inversion import InversionConfig


ROOT = Path(__file__).resolve().parents[3]
REGISTRY = ROOT / "config" / "data-contracts" / "gate-a1-datasets.json"
SCRIPT = (
    ROOT
    / "code"
    / "python"
    / "scripts"
    / "audit_feature_channel_contracts.py"
)
DATASETS = ("FT2", "FT3", "FT4", "FT8")
MODES = ("legacy", "complex_snr", "lockin_only", "hybrid")


def _load_script():
    spec = importlib.util.spec_from_file_location(
        "audit_feature_channel_contracts", SCRIPT
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _contract(mode: str) -> dict:
    evidence = {
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
    payload = json.dumps(
        evidence,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode()
    return {
        **evidence,
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


def _passing_records() -> tuple[list[dict], list[dict]]:
    contracts = []
    invariance = []
    for dataset in DATASETS:
        for mode in MODES:
            contract = _contract(mode)
            contracts.append(
                {
                    "dataset_id": dataset,
                    "feature_mode": mode,
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
                    "injected_failure_value": 12345.0,
                    "feature_fail_penalty": 12345.0,
                    "n_feature_fail_delta": 1,
                }
            )
    return contracts, invariance


def test_audit_accepts_16_unique_dataset_mode_records_with_repeated_hashes():
    module = _load_script()
    contracts, invariance = _passing_records()

    summary = module.evaluate_audit(contracts, invariance)

    assert summary["gate"] == "PASS"
    assert summary["record_count"] == 16
    assert summary["unique_contract_hash_count"] == 4
    assert summary["structure_passed"] is True
    assert summary["contract_passed"] is True


@pytest.mark.parametrize("mutation", ["missing", "duplicate"])
def test_audit_classifies_malformed_dataset_mode_set_as_structure_failure(
    mutation,
):
    module = _load_script()
    contracts, invariance = _passing_records()
    if mutation == "missing":
        contracts.pop()
    else:
        contracts[-1] = copy.deepcopy(contracts[0])

    summary = module.evaluate_audit(contracts, invariance)

    assert summary["gate"] == "FAIL_STRUCTURE"
    assert summary["structure_passed"] is False


@pytest.mark.parametrize(
    "mutation",
    [
        "contract_hash",
        "missing_contract",
        "zero_weight",
        "missing_reason",
        "candidate_hash",
        "candidate_normalization",
        "candidate_channels",
        "failure_penalty",
        "failure_count",
    ],
)
def test_audit_classifies_contract_drift_as_contract_failure(mutation):
    module = _load_script()
    contracts, invariance = _passing_records()
    if mutation == "contract_hash":
        contracts[0]["channel_contract"]["sha256"] = "0" * 64
    elif mutation == "missing_contract":
        contracts[0].pop("channel_contract")
    elif mutation == "zero_weight":
        contracts[0]["channel_contract"]["channels"][0][
            "loss_weight"
        ] = 0.0
    elif mutation == "missing_reason":
        contracts[0]["channel_contract"]["channels"][1][
            "exclusion_reason"
        ] = None
    elif mutation == "candidate_hash":
        invariance[0]["candidate_b_contract_sha256"] = "0" * 64
    elif mutation == "candidate_normalization":
        invariance[0]["candidate_b_normalization_weight_sum"] = 2.0
    elif mutation == "candidate_channels":
        invariance[0]["candidate_b_active_channel_ids"] = ["dc", "H1"]
    elif mutation == "failure_penalty":
        invariance[0]["injected_failure_value"] = 999.0
    elif mutation == "failure_count":
        invariance[0]["n_feature_fail_delta"] = 0

    summary = module.evaluate_audit(contracts, invariance)

    assert summary["gate"] == "FAIL_CONTRACT"
    assert summary["structure_passed"] is True
    assert summary["contract_passed"] is False


def test_candidate_exercise_consumes_two_finite_candidates_before_injection():
    module = _load_script()
    config = InversionConfig(
        n_points=8,
        points_per_cycle=8,
        discard_fraction=0.5,
        feature_grid_size=4,
        fit_harmonics=(1, 2, 3),
        feature_mode="legacy",
        feature_fail_penalty=12345.0,
    )
    target = {
        "dc": np.arange(4, dtype=float),
        "harm": [
            np.full(4, harmonic, dtype=float)
            for harmonic in range(1, 8)
        ],
        "tafel": None,
    }

    evidence = module._exercise_candidate_invariance(target, config)

    assert evidence["injected_failure_value"] == 12345.0
    assert evidence["n_feature_fail_delta"] == 1


def test_real_runner_builds_and_writes_finite_16_record_archive(tmp_path):
    module = _load_script()
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))

    contracts, invariance = module.build_real_records(ROOT, registry)
    summary = module.evaluate_audit(contracts, invariance)
    output = tmp_path / "audit"
    module.write_audit_outputs(
        output,
        contracts=contracts,
        invariance=invariance,
        summary=summary,
        manifest={"schema_version": 1, "commit": "test"},
    )

    assert summary["gate"] == "PASS"
    assert len(contracts) == len(invariance) == 16
    assert set(path.name for path in output.iterdir()) == {
        "channel_contracts.jsonl",
        "candidate_invariance.jsonl",
        "gate_a5_summary.json",
        "run_manifest.json",
    }
    for path in output.iterdir():
        text = path.read_text(encoding="utf-8")
        assert text.endswith("\n")
        assert "NaN" not in text
        assert "Infinity" not in text
    written_manifest = json.loads(
        (output / "run_manifest.json").read_text(encoding="utf-8")
    )
    assert set(written_manifest["artifact_sha256"]) == {
        "channel_contracts.jsonl",
        "candidate_invariance.jsonl",
        "gate_a5_summary.json",
    }
    for name, digest in written_manifest["artifact_sha256"].items():
        assert digest == hashlib.sha256((output / name).read_bytes()).hexdigest()
    with pytest.raises(FileExistsError, match="new or empty"):
        module.write_audit_outputs(
            output,
            contracts=contracts,
            invariance=invariance,
            summary=summary,
            manifest={"schema_version": 1, "commit": "test"},
        )
