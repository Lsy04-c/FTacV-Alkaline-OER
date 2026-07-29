"""Independent Gate A2 archive validation and tamper tests."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "code" / "python" / "scripts" / "validate_gate_a2_physics.py"
CASE_IDS = (
    "default",
    "rates-low",
    "rates-high",
    "ru-low",
    "ru-high",
    "cdl-low",
    "cdl-high",
    "gamma-low",
    "gamma-high",
    "alpha-low",
    "alpha-high",
    "thermo-edge",
)
STOICHIOMETRY = [
    [-1.0, 0.0, 0.0, 0.0, 0.0],
    [1.0, -1.0, 0.0, 0.0, 1.0],
    [0.0, 1.0, -1.0, 0.0, 0.0],
    [0.0, 0.0, 1.0, -1.0, 0.0],
    [0.0, 0.0, 0.0, 1.0, -1.0],
]
THRESHOLDS = {
    "coverage_sum_max_error": 1e-8,
    "coverage_min": -1e-8,
    "coverage_max": 1.0 + 1e-8,
    "projection_trigger_count": 0,
    "current_closure_relative_error": 1e-10,
    "steady_state_rhs_inf_norm": 1e-8,
    "thermodynamic_sum_error": 1e-12,
    "baseline_relative_error": 1e-12,
}
UNITS = {
    "potential": "V",
    "resistance": "ohm",
    "capacitance_areal": "F cm^-2",
    "area": "cm^2",
    "site_density": "mol cm^-2",
    "rate": "s^-1",
    "coverage": "1",
    "current": "A",
    "free_energy": "eV per electron",
}


def _load_validator():
    spec = importlib.util.spec_from_file_location("gate_a2_validator", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write(path: Path, payload) -> None:
    path.write_text(
        json.dumps(payload, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def _row(case_id: str) -> dict:
    return {
        "case_id": case_id,
        "solver_success": True,
        "steady_state_success": True,
        "finite": True,
        "coverage_sum_max_error": 1e-12,
        "coverage_min": 0.0,
        "coverage_max": 1.0,
        "projection_trigger_count": 0,
        "current_closure_relative_error": 1e-12,
        "steady_state_rhs_inf_norm": 1e-12,
        "thermodynamic_sum_error": 0.0,
    }


def _archive(tmp_path: Path) -> Path:
    archive = tmp_path / "archive"
    archive.mkdir()
    contract = {
        "schema_version": 1,
        "gate": "A2",
        "case_ids": list(CASE_IDS),
        "cycles": 32,
        "points_per_cycle": 128,
        "solver": {
            "method": "LSODA",
            "rtol": 1e-6,
            "atol": 1e-8,
            "first_step": 1e-8,
        },
        "stoichiometric_matrix": STOICHIOMETRY,
        "unit_ledger": UNITS,
        "thresholds": THRESHOLDS,
    }
    rows = [_row(case_id) for case_id in CASE_IDS]
    baseline = {
        "schema_version": 1,
        "passed": True,
        "max_relative_error": 1e-13,
        "baseline_sha256": "a" * 64,
        "payload_contract_valid": True,
        "record_count": 72,
    }
    summary = {
        "schema_version": 1,
        "gate": "PASS",
        "case_count": 12,
        "expected_case_count": 12,
        "eligible_for_next_gate": True,
        "thresholds": THRESHOLDS,
        "m0_fallback": {
            "schema_version": 1,
            "passed": True,
            "state_max_abs_error": 0.0,
            "current_max_abs_error": 0.0,
            "solver_success": True,
        },
    }
    _write(archive / "physics_contract.json", contract)
    (archive / "trajectory_metrics.jsonl").write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )
    _write(archive / "baseline_comparison.json", baseline)
    _write(archive / "gate_a2_summary.json", summary)
    names = (
        "physics_contract.json",
        "trajectory_metrics.jsonl",
        "baseline_comparison.json",
        "gate_a2_summary.json",
    )
    _write(
        archive / "run_manifest.json",
        {
            "schema_version": 1,
            "source_commit": "b" * 40,
            "baseline_sha256": "a" * 64,
            "artifacts": {name: _sha(archive / name) for name in names},
        },
    )
    return archive


def _rewrite_and_rehash(archive: Path, name: str, payload) -> None:
    _write(archive / name, payload)
    manifest_path = archive / "run_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["artifacts"][name] = _sha(archive / name)
    _write(manifest_path, manifest)


def _set_summary_gate(archive: Path, gate: str) -> None:
    path = archive / "gate_a2_summary.json"
    summary = json.loads(path.read_text(encoding="utf-8"))
    summary["gate"] = gate
    summary["eligible_for_next_gate"] = gate == "PASS"
    _rewrite_and_rehash(archive, path.name, summary)


def test_exact_archive_passes(tmp_path):
    validator = _load_validator()
    result = validator.validate_archive(_archive(tmp_path))
    assert result["gate"] == "PASS"


@pytest.mark.parametrize("mode", ["missing", "duplicate"])
def test_missing_or_duplicate_case_is_structure_failure(tmp_path, mode):
    validator = _load_validator()
    archive = _archive(tmp_path)
    path = archive / "trajectory_metrics.jsonl"
    rows = [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
    ]
    rows = rows[:-1] if mode == "missing" else rows[:-1] + [rows[0]]
    path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )
    manifest = json.loads(
        (archive / "run_manifest.json").read_text(encoding="utf-8")
    )
    manifest["artifacts"][path.name] = _sha(path)
    _write(archive / "run_manifest.json", manifest)
    assert validator.validate_archive(archive)["gate"] == "FAIL_STRUCTURE"


def test_null_metric_is_numerical_failure(tmp_path):
    validator = _load_validator()
    archive = _archive(tmp_path)
    path = archive / "trajectory_metrics.jsonl"
    rows = [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
    ]
    rows[0]["coverage_min"] = None
    path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )
    manifest = json.loads(
        (archive / "run_manifest.json").read_text(encoding="utf-8")
    )
    manifest["artifacts"][path.name] = _sha(path)
    _write(archive / "run_manifest.json", manifest)
    _set_summary_gate(archive, "FAIL_NUMERICAL")
    assert validator.validate_archive(archive)["gate"] == "FAIL_NUMERICAL"


@pytest.mark.parametrize("field", ["stoichiometric_matrix", "unit_ledger"])
def test_contract_physics_drift_is_physics_failure(tmp_path, field):
    validator = _load_validator()
    archive = _archive(tmp_path)
    contract = json.loads(
        (archive / "physics_contract.json").read_text(encoding="utf-8")
    )
    if field == "stoichiometric_matrix":
        contract[field][0][0] = -2.0
    else:
        contract[field]["current"] = "mA"
    _rewrite_and_rehash(archive, "physics_contract.json", contract)
    _set_summary_gate(archive, "FAIL_PHYSICS")
    assert validator.validate_archive(archive)["gate"] == "FAIL_PHYSICS"


def test_projection_and_current_threshold_are_independently_checked(tmp_path):
    validator = _load_validator()
    archive = _archive(tmp_path)
    path = archive / "trajectory_metrics.jsonl"
    rows = [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
    ]
    rows[0]["current_closure_relative_error"] = 1e-10
    path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )
    manifest = json.loads(
        (archive / "run_manifest.json").read_text(encoding="utf-8")
    )
    manifest["artifacts"][path.name] = _sha(path)
    _write(archive / "run_manifest.json", manifest)
    assert validator.validate_archive(archive)["gate"] == "PASS"

    rows[0]["current_closure_relative_error"] = 1.0001e-10
    rows[1]["projection_trigger_count"] = 1
    path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )
    manifest["artifacts"][path.name] = _sha(path)
    _write(archive / "run_manifest.json", manifest)
    _set_summary_gate(archive, "FAIL_NUMERICAL")
    assert validator.validate_archive(archive)["gate"] == "FAIL_NUMERICAL"


def test_baseline_hash_mismatch_is_structure_failure(tmp_path):
    validator = _load_validator()
    archive = _archive(tmp_path)
    baseline = json.loads(
        (archive / "baseline_comparison.json").read_text(encoding="utf-8")
    )
    baseline["baseline_sha256"] = "c" * 64
    _rewrite_and_rehash(archive, "baseline_comparison.json", baseline)
    assert validator.validate_archive(archive)["gate"] == "FAIL_STRUCTURE"


def test_runner_summary_tampering_is_structure_failure(tmp_path):
    validator = _load_validator()
    archive = _archive(tmp_path)
    summary = json.loads(
        (archive / "gate_a2_summary.json").read_text(encoding="utf-8")
    )
    summary["gate"] = "FAIL_PHYSICS"
    _rewrite_and_rehash(archive, "gate_a2_summary.json", summary)
    assert validator.validate_archive(archive)["gate"] == "FAIL_STRUCTURE"
