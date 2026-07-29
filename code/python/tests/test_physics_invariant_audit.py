"""Gate A2 formal runner contract and summary tests."""

from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "code" / "python" / "scripts" / "audit_physics_invariants.py"


def _load_script():
    spec = importlib.util.spec_from_file_location(
        "audit_physics_invariants", SCRIPT
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _passing_rows(module):
    return [
        {
            "case_id": case_id,
            "solver_success": True,
            "steady_state_success": True,
            "finite": True,
            "coverage_sum_max_error": 1e-12,
            "coverage_min": 0.0,
            "coverage_max": 1.0,
            "projection_trigger_count": 0,
            "current_closure_relative_error": 1e-14,
            "steady_state_rhs_inf_norm": 1e-12,
            "thermodynamic_sum_error": 0.0,
        }
        for case_id in module.CASE_IDS
    ]


def test_formal_case_library_is_exact_and_fixed():
    module = _load_script()

    assert len(module.CASE_IDS) == 12
    assert len(set(module.CASE_IDS)) == 12
    assert module.FORMAL_CYCLES == 32
    assert module.FORMAL_POINTS_PER_CYCLE == 128


def test_summary_passes_only_complete_invariant_evidence():
    module = _load_script()
    rows = _passing_rows(module)
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

    summary = module.summarize_gate(rows, baseline, m0)

    assert summary["gate"] == "PASS"
    assert summary["case_count"] == 12
    assert summary["eligible_for_next_gate"] is True


def test_summary_fails_each_numerical_invariant():
    module = _load_script()
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
    mutations = [
        ("coverage_sum_max_error", 1.0001e-8),
        ("coverage_min", -1.0001e-8),
        ("coverage_max", 1.0 + 1.0001e-8),
        ("projection_trigger_count", 1),
        ("current_closure_relative_error", 1.0001e-10),
        ("steady_state_rhs_inf_norm", 1.0001e-8),
    ]
    for name, value in mutations:
        rows = _passing_rows(module)
        rows[0][name] = value
        summary = module.summarize_gate(rows, baseline, m0)
        assert summary["gate"] == "FAIL_NUMERICAL", name


def test_summary_separates_baseline_and_physics_failures():
    module = _load_script()
    rows = _passing_rows(module)
    baseline = {
        "passed": False,
        "max_relative_error": 1e-6,
        "baseline_sha256": "a" * 64,
    }
    m0 = {
        "passed": True,
        "state_max_abs_error": 0.0,
        "current_max_abs_error": 0.0,
    }
    assert module.summarize_gate(rows, baseline, m0)["gate"] == (
        "FAIL_NUMERICAL"
    )

    baseline["passed"] = True
    m0["passed"] = False
    assert module.summarize_gate(rows, baseline, m0)["gate"] == (
        "FAIL_PHYSICS"
    )
