"""Independent Gate A2-R archive validation and tamper tests."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "code" / "python" / "scripts" / "validate_gate_a2r.py"
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
THRESHOLDS = {
    "coverage_sum_max_error": 1e-8,
    "coverage_min": -1e-8,
    "coverage_max": 1.0 + 1e-8,
    "projection_trigger_count": 0,
    "current_closure_relative_error": 1e-10,
    "steady_state_rhs_inf_norm": 1e-8,
    "thermodynamic_sum_error": 1e-12,
    "baseline_relative_error": 1e-12,
    "implicit_coverage_max_abs_error": 1e-5,
    "implicit_surface_potential_max_abs_error": 1e-4,
    "implicit_current_nrmse": 1e-5,
    "implicit_current_max_scaled_error": 1e-4,
}
ARTIFACTS = (
    "physics_contract.json",
    "trajectory_metrics.jsonl",
    "backend_attempts.jsonl",
    "implicit_crosscheck.json",
    "baseline_comparison.json",
    "gate_a2r_summary.json",
)


def _load_validator():
    spec = importlib.util.spec_from_file_location("gate_a2r_validator", SCRIPT)
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
    fallback = case_id == "thermo-edge"
    return {
        "case_id": case_id,
        "solver_success": True,
        "steady_state_success": True,
        "finite": True,
        "coverage_sum_max_error": 1e-12,
        "coverage_min": -1e-10,
        "coverage_max": 1.0 + 1e-10,
        "projection_trigger_count": 0,
        "current_closure_relative_error": 1e-14,
        "steady_state_rhs_inf_norm": 1e-12,
        "thermodynamic_sum_error": 0.0,
        "backend_used": "BDF" if fallback else "LSODA",
        "fallback_used": fallback,
    }


def _attempt_row(case_id: str) -> dict:
    attempts = [
        {
            "backend": "LSODA",
            "success": case_id != "thermo-edge",
            "message": (
                "Unexpected istate" if case_id == "thermo-edge" else "ok"
            ),
            "nfev": 20,
            "returned_points": 1 if case_id == "thermo-edge" else 4096,
        }
    ]
    if case_id == "thermo-edge":
        attempts.append(
            {
                "backend": "BDF",
                "success": True,
                "message": "ok",
                "nfev": 12000,
                "returned_points": 4096,
            }
        )
    return {"case_id": case_id, "attempts": attempts}


def _archive(tmp_path: Path) -> Path:
    archive = tmp_path / "archive"
    archive.mkdir()
    contract = {
        "schema_version": 1,
        "gate": "A2-R",
        "case_ids": list(CASE_IDS),
        "cycles": 32,
        "points_per_cycle": 128,
        "solver_policy": {
            "order": ["LSODA", "BDF"],
            "rtol": 1e-6,
            "dynamic_atol": [3e-11] * 5 + [1e-8],
            "lsoda_first_step": 1e-8,
        },
        "stoichiometric_matrix": [
            [-1.0, 0.0, 0.0, 0.0, 0.0],
            [1.0, -1.0, 0.0, 0.0, 1.0],
            [0.0, 1.0, -1.0, 0.0, 0.0],
            [0.0, 0.0, 1.0, -1.0, 0.0],
            [0.0, 0.0, 0.0, 1.0, -1.0],
        ],
        "unit_ledger": {
            "potential": "V",
            "resistance": "ohm",
            "capacitance_areal": "F cm^-2",
            "area": "cm^2",
            "site_density": "mol cm^-2",
            "rate": "s^-1",
            "coverage": "1",
            "current": "A",
            "free_energy": "eV per electron",
        },
        "thresholds": THRESHOLDS,
        "historical_failed_archive": "gate-a2-6486d69",
    }
    rows = [_row(case_id) for case_id in CASE_IDS]
    attempts = [_attempt_row(case_id) for case_id in CASE_IDS]
    crosscheck = {
        "schema_version": 1,
        "passed": True,
        "bdf_success": True,
        "radau_success": True,
        "coverage_max_abs_error": 2e-6,
        "surface_potential_max_abs_error": 2e-5,
        "current_nrmse": 1e-6,
        "current_max_scaled_error": 3e-5,
    }
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
        "fallback_cases": ["thermo-edge"],
        "eligible_for_next_gate": True,
        "thresholds": THRESHOLDS,
        "m0_fallback": {
            "passed": True,
            "state_max_abs_error": 0.0,
            "current_max_abs_error": 0.0,
            "backend_used": "LSODA",
        },
    }
    _write(archive / "physics_contract.json", contract)
    for name, values in (
        ("trajectory_metrics.jsonl", rows),
        ("backend_attempts.jsonl", attempts),
    ):
        (archive / name).write_text(
            "".join(json.dumps(value, sort_keys=True) + "\n" for value in values),
            encoding="utf-8",
        )
    _write(archive / "implicit_crosscheck.json", crosscheck)
    _write(archive / "baseline_comparison.json", baseline)
    _write(archive / "gate_a2r_summary.json", summary)
    _write(
        archive / "run_manifest.json",
        {
            "schema_version": 1,
            "source_commit": "b" * 40,
            "baseline_sha256": "a" * 64,
            "artifacts": {name: _sha(archive / name) for name in ARTIFACTS},
        },
    )
    return archive


def _rehash(archive: Path, name: str) -> None:
    path = archive / "run_manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest["artifacts"][name] = _sha(archive / name)
    _write(path, manifest)


def _set_summary_gate(archive: Path, gate: str) -> None:
    name = "gate_a2r_summary.json"
    path = archive / name
    summary = json.loads(path.read_text(encoding="utf-8"))
    summary["gate"] = gate
    summary["eligible_for_next_gate"] = gate == "PASS"
    _write(path, summary)
    _rehash(archive, name)


def test_exact_a2r_archive_passes(tmp_path):
    validator = _load_validator()
    assert validator.validate_archive(_archive(tmp_path))["gate"] == "PASS"


@pytest.mark.parametrize("mode", ["missing", "duplicate"])
def test_case_set_tamper_is_structure_failure(tmp_path, mode):
    validator = _load_validator()
    archive = _archive(tmp_path)
    path = archive / "trajectory_metrics.jsonl"
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    rows = rows[:-1] if mode == "missing" else rows[:-1] + [rows[0]]
    path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows)
    )
    _rehash(archive, path.name)
    assert validator.validate_archive(archive)["gate"] == "FAIL_STRUCTURE"


def test_artifact_hash_tamper_is_structure_failure(tmp_path):
    validator = _load_validator()
    archive = _archive(tmp_path)
    with (archive / "trajectory_metrics.jsonl").open("a") as handle:
        handle.write("\n")
    assert validator.validate_archive(archive)["gate"] == "FAIL_STRUCTURE"


def test_dynamic_tolerance_drift_is_structure_failure(tmp_path):
    validator = _load_validator()
    archive = _archive(tmp_path)
    path = archive / "physics_contract.json"
    contract = json.loads(path.read_text())
    contract["solver_policy"]["dynamic_atol"][0] = 1e-8
    _write(path, contract)
    _rehash(archive, path.name)
    assert validator.validate_archive(archive)["gate"] == "FAIL_STRUCTURE"


@pytest.mark.parametrize(
    ("target", "mutation"),
    [
        ("trajectory", ("projection_trigger_count", 1)),
        ("attempt", ("message", "")),
        ("crosscheck", ("current_nrmse", 1.0001e-5)),
    ],
)
def test_numerical_evidence_failure_is_recomputed(
    tmp_path, target, mutation
):
    validator = _load_validator()
    archive = _archive(tmp_path)
    field, value = mutation
    if target == "trajectory":
        path = archive / "trajectory_metrics.jsonl"
        rows = [json.loads(line) for line in path.read_text().splitlines()]
        rows[0][field] = value
        path.write_text(
            "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows)
        )
    elif target == "attempt":
        path = archive / "backend_attempts.jsonl"
        rows = [json.loads(line) for line in path.read_text().splitlines()]
        rows[-1]["attempts"][0][field] = value
        path.write_text(
            "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows)
        )
    else:
        path = archive / "implicit_crosscheck.json"
        value_dict = json.loads(path.read_text())
        value_dict[field] = value
        value_dict["passed"] = False
        _write(path, value_dict)
    _rehash(archive, path.name)
    _set_summary_gate(archive, "FAIL_NUMERICAL")
    assert validator.validate_archive(archive)["gate"] == "FAIL_NUMERICAL"


def test_unexpected_fallback_is_numerical_failure(tmp_path):
    validator = _load_validator()
    archive = _archive(tmp_path)
    path = archive / "trajectory_metrics.jsonl"
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    rows[0]["backend_used"] = "BDF"
    rows[0]["fallback_used"] = True
    path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows)
    )
    _rehash(archive, path.name)
    _set_summary_gate(archive, "FAIL_NUMERICAL")
    summary_path = archive / "gate_a2r_summary.json"
    summary = json.loads(summary_path.read_text())
    summary["fallback_cases"] = ["default", "thermo-edge"]
    _write(summary_path, summary)
    _rehash(archive, summary_path.name)
    assert validator.validate_archive(archive)["gate"] == "FAIL_NUMERICAL"


def test_baseline_provenance_mismatch_is_structure_failure(tmp_path):
    validator = _load_validator()
    archive = _archive(tmp_path)
    path = archive / "baseline_comparison.json"
    baseline = json.loads(path.read_text())
    baseline["baseline_sha256"] = "c" * 64
    _write(path, baseline)
    _rehash(archive, path.name)
    assert validator.validate_archive(archive)["gate"] == "FAIL_STRUCTURE"


def test_runner_summary_tamper_is_structure_failure(tmp_path):
    validator = _load_validator()
    archive = _archive(tmp_path)
    _set_summary_gate(archive, "FAIL_PHYSICS")
    assert validator.validate_archive(archive)["gate"] == "FAIL_STRUCTURE"
