"""Gate A2-R runner contract and classification tests."""

from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "code" / "python" / "scripts" / "audit_gate_a2r.py"


def _load_script():
    spec = importlib.util.spec_from_file_location("audit_gate_a2r", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _passing_evidence(module):
    rows = [
        {
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
            "backend_used": (
                "BDF" if case_id == "thermo-edge" else "LSODA"
            ),
            "fallback_used": case_id == "thermo-edge",
        }
        for case_id in module.CASE_IDS
    ]
    attempts = []
    for case_id in module.CASE_IDS:
        if case_id == "thermo-edge":
            values = [
                {
                    "backend": "LSODA",
                    "success": False,
                    "message": "Unexpected istate",
                    "nfev": 23,
                    "returned_points": 1,
                },
                {
                    "backend": "BDF",
                    "success": True,
                    "message": "ok",
                    "nfev": 12000,
                    "returned_points": 4096,
                },
            ]
        else:
            values = [
                {
                    "backend": "LSODA",
                    "success": True,
                    "message": "ok",
                    "nfev": 100,
                    "returned_points": 4096,
                }
            ]
        attempts.append({"case_id": case_id, "attempts": values})
    baseline = {
        "passed": True,
        "max_relative_error": 1e-13,
        "baseline_sha256": "a" * 64,
    }
    m0 = {
        "passed": True,
        "state_max_abs_error": 0.0,
        "current_max_abs_error": 0.0,
    }
    crosscheck = {
        "passed": True,
        "bdf_success": True,
        "radau_success": True,
        "coverage_max_abs_error": 2e-6,
        "surface_potential_max_abs_error": 2e-5,
        "current_nrmse": 1e-6,
        "current_max_scaled_error": 3e-5,
    }
    return rows, attempts, baseline, m0, crosscheck


def test_a2r_contract_is_exact_and_passes_complete_evidence():
    module = _load_script()
    evidence = _passing_evidence(module)

    summary = module.summarize_gate(*evidence)

    assert len(module.CASE_IDS) == 12
    assert module.DYNAMIC_ATOL_VALUES == [3e-11] * 5 + [1e-8]
    assert summary["gate"] == "PASS"
    assert summary["fallback_cases"] == ["thermo-edge"]
    assert summary["eligible_for_next_gate"] is True


def test_a2r_rejects_each_numerical_invariant():
    module = _load_script()
    mutations = [
        ("projection_trigger_count", 1),
        ("coverage_min", -1.0001e-8),
        ("coverage_max", 1.0 + 1.0001e-8),
        ("coverage_sum_max_error", 1.0001e-8),
        ("current_closure_relative_error", 1.0001e-10),
    ]
    for field, value in mutations:
        rows, attempts, baseline, m0, crosscheck = _passing_evidence(module)
        rows[0][field] = value
        summary = module.summarize_gate(
            rows, attempts, baseline, m0, crosscheck
        )
        assert summary["gate"] == "FAIL_NUMERICAL", field


def test_a2r_rejects_unexpected_or_unexplained_fallback():
    module = _load_script()
    rows, attempts, baseline, m0, crosscheck = _passing_evidence(module)
    rows[0]["backend_used"] = "BDF"
    rows[0]["fallback_used"] = True
    attempts[0]["attempts"] = attempts[-1]["attempts"]
    assert module.summarize_gate(
        rows, attempts, baseline, m0, crosscheck
    )["gate"] == "FAIL_NUMERICAL"

    rows, attempts, baseline, m0, crosscheck = _passing_evidence(module)
    attempts[-1]["attempts"][0]["message"] = ""
    assert module.summarize_gate(
        rows, attempts, baseline, m0, crosscheck
    )["gate"] == "FAIL_NUMERICAL"


def test_a2r_rejects_implicit_crosscheck_or_baseline_failure():
    module = _load_script()
    rows, attempts, baseline, m0, crosscheck = _passing_evidence(module)
    crosscheck["current_nrmse"] = 1.0001e-5
    crosscheck["passed"] = False
    assert module.summarize_gate(
        rows, attempts, baseline, m0, crosscheck
    )["gate"] == "FAIL_NUMERICAL"

    rows, attempts, baseline, m0, crosscheck = _passing_evidence(module)
    baseline["passed"] = False
    assert module.summarize_gate(
        rows, attempts, baseline, m0, crosscheck
    )["gate"] == "FAIL_NUMERICAL"


def test_a2r_rejects_malformed_case_set_as_structure_failure():
    module = _load_script()
    rows, attempts, baseline, m0, crosscheck = _passing_evidence(module)
    rows.pop()
    summary = module.summarize_gate(
        rows, attempts, baseline, m0, crosscheck
    )
    assert summary["gate"] == "FAIL_STRUCTURE"
