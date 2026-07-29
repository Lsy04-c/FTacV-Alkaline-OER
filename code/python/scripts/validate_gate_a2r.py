#!/usr/bin/env python3
"""Independently validate a compact Gate A2-R archive."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np


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
STOICHIOMETRY = np.array(
    [
        [-1.0, 0.0, 0.0, 0.0, 0.0],
        [1.0, -1.0, 0.0, 0.0, 1.0],
        [0.0, 1.0, -1.0, 0.0, 0.0],
        [0.0, 0.0, 1.0, -1.0, 0.0],
        [0.0, 0.0, 0.0, 1.0, -1.0],
    ]
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
UNIT_LEDGER = {
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
SOLVER_POLICY = {
    "order": ["LSODA", "BDF"],
    "rtol": 1e-6,
    "dynamic_atol": [3e-11] * 5 + [1e-8],
    "lsoda_first_step": 1e-8,
}
ARTIFACTS = (
    "physics_contract.json",
    "trajectory_metrics.jsonl",
    "backend_attempts.jsonl",
    "implicit_crosscheck.json",
    "baseline_comparison.json",
    "gate_a2r_summary.json",
)
ROW_FIELDS = {
    "case_id",
    "solver_success",
    "steady_state_success",
    "finite",
    "coverage_sum_max_error",
    "coverage_min",
    "coverage_max",
    "projection_trigger_count",
    "current_closure_relative_error",
    "steady_state_rhs_inf_norm",
    "thermodynamic_sum_error",
    "backend_used",
    "fallback_used",
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _result(gate: str, reasons: list[str]) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "gate": gate,
        "eligible_for_next_gate": gate == "PASS",
        "reasons": reasons,
    }


def _finite_number(value: Any) -> bool:
    return (
        not isinstance(value, bool)
        and isinstance(value, (int, float))
        and np.isfinite(float(value))
    )


def _read_jsonl(path: Path) -> list[Any]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _backend_policy_ok(
    rows: list[dict[str, Any]],
    attempt_rows: list[dict[str, Any]],
) -> bool:
    attempts_by_case = {
        row.get("case_id"): row.get("attempts")
        for row in attempt_rows
        if isinstance(row, dict)
    }
    for row in rows:
        case_id = row["case_id"]
        attempts = attempts_by_case.get(case_id)
        if not isinstance(attempts, list) or not attempts:
            return False
        if case_id != "thermo-edge":
            if (
                row["backend_used"] != "LSODA"
                or row["fallback_used"] is not False
                or len(attempts) != 1
                or attempts[0].get("backend") != "LSODA"
                or attempts[0].get("success") is not True
                or attempts[0].get("returned_points") != 4096
            ):
                return False
        elif row["backend_used"] == "LSODA":
            if (
                row["fallback_used"] is not False
                or len(attempts) != 1
                or attempts[0].get("backend") != "LSODA"
                or attempts[0].get("success") is not True
                or attempts[0].get("returned_points") != 4096
            ):
                return False
        elif row["backend_used"] == "BDF":
            if (
                row["fallback_used"] is not True
                or len(attempts) != 2
                or attempts[0].get("backend") != "LSODA"
                or attempts[0].get("success") is not False
                or not attempts[0].get("message")
                or attempts[1].get("backend") != "BDF"
                or attempts[1].get("success") is not True
                or attempts[1].get("returned_points") != 4096
            ):
                return False
        else:
            return False
    return True


def validate_archive(archive: Path) -> dict[str, Any]:
    """Reload and independently recompute Gate A2-R."""
    archive = Path(archive)
    required = (*ARTIFACTS, "run_manifest.json")
    if not archive.is_dir() or any(
        not (archive / name).is_file() for name in required
    ):
        return _result("FAIL_STRUCTURE", ["missing required artifact"])
    try:
        contract = json.loads(
            (archive / "physics_contract.json").read_text(encoding="utf-8")
        )
        rows = _read_jsonl(archive / "trajectory_metrics.jsonl")
        attempt_rows = _read_jsonl(archive / "backend_attempts.jsonl")
        crosscheck = json.loads(
            (archive / "implicit_crosscheck.json").read_text(
                encoding="utf-8"
            )
        )
        baseline = json.loads(
            (archive / "baseline_comparison.json").read_text(
                encoding="utf-8"
            )
        )
        summary = json.loads(
            (archive / "gate_a2r_summary.json").read_text(encoding="utf-8")
        )
        manifest = json.loads(
            (archive / "run_manifest.json").read_text(encoding="utf-8")
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return _result("FAIL_STRUCTURE", [f"unreadable artifact: {exc}"])

    structure_reasons = []
    artifact_hashes = manifest.get("artifacts")
    if not isinstance(artifact_hashes, dict):
        structure_reasons.append("manifest artifacts missing")
    else:
        for name in ARTIFACTS:
            if artifact_hashes.get(name) != _sha256(archive / name):
                structure_reasons.append(f"artifact hash mismatch: {name}")
    if baseline.get("baseline_sha256") != manifest.get("baseline_sha256"):
        structure_reasons.append("baseline provenance hash mismatch")
    row_ids = [row.get("case_id") for row in rows if isinstance(row, dict)]
    attempt_ids = [
        row.get("case_id") for row in attempt_rows if isinstance(row, dict)
    ]
    for label, values, ids in (
        ("trajectory", rows, row_ids),
        ("attempt", attempt_rows, attempt_ids),
    ):
        if (
            len(values) != len(CASE_IDS)
            or len(ids) != len(values)
            or set(ids) != set(CASE_IDS)
            or len(set(ids)) != len(CASE_IDS)
        ):
            structure_reasons.append(f"{label} case set mismatch")
    if any(
        not isinstance(row, dict) or not ROW_FIELDS <= set(row)
        for row in rows
    ):
        structure_reasons.append("trajectory schema mismatch")
    if any(
        not isinstance(row, dict) or not isinstance(row.get("attempts"), list)
        for row in attempt_rows
    ):
        structure_reasons.append("backend-attempt schema mismatch")
    if (
        contract.get("schema_version") != 1
        or contract.get("gate") != "A2-R"
        or contract.get("case_ids") != list(CASE_IDS)
        or contract.get("cycles") != 32
        or contract.get("points_per_cycle") != 128
        or contract.get("solver_policy") != SOLVER_POLICY
        or contract.get("thresholds") != THRESHOLDS
        or contract.get("historical_failed_archive") != "gate-a2-6486d69"
    ):
        structure_reasons.append("frozen A2-R contract mismatch")
    if structure_reasons:
        return _result("FAIL_STRUCTURE", structure_reasons)

    physics_reasons = []
    try:
        observed_stoichiometry = np.asarray(
            contract["stoichiometric_matrix"], dtype=float
        )
    except (KeyError, TypeError, ValueError):
        observed_stoichiometry = np.empty((0, 0))
    if (
        observed_stoichiometry.shape != (5, 5)
        or not np.array_equal(observed_stoichiometry, STOICHIOMETRY)
        or not np.array_equal(
            np.sum(observed_stoichiometry, axis=0), np.zeros(5)
        )
    ):
        physics_reasons.append("stoichiometric contract drift")
    if contract.get("unit_ledger") != UNIT_LEDGER:
        physics_reasons.append("unit ledger drift")

    numerical_reasons = []
    numeric_names = (
        "coverage_sum_max_error",
        "coverage_min",
        "coverage_max",
        "projection_trigger_count",
        "current_closure_relative_error",
        "steady_state_rhs_inf_norm",
        "thermodynamic_sum_error",
    )
    if any(
        not _finite_number(row.get(name))
        for row in rows
        for name in numeric_names
    ):
        numerical_reasons.append("non-finite or null trajectory metric")
    else:
        for row in rows:
            if (
                not row["solver_success"]
                or not row["steady_state_success"]
                or not row["finite"]
                or row["coverage_sum_max_error"] > 1e-8
                or row["coverage_min"] < -1e-8
                or row["coverage_max"] > 1.0 + 1e-8
                or row["projection_trigger_count"] != 0
                or row["current_closure_relative_error"] > 1e-10
                or row["steady_state_rhs_inf_norm"] > 1e-8
            ):
                numerical_reasons.append(
                    f"numerical invariant failed: {row['case_id']}"
                )
            if row["thermodynamic_sum_error"] > 1e-12:
                physics_reasons.append(
                    f"thermodynamic closure failed: {row['case_id']}"
                )
    if not _backend_policy_ok(rows, attempt_rows):
        numerical_reasons.append("backend policy or provenance failed")

    crosscheck_limits = {
        "coverage_max_abs_error": 1e-5,
        "surface_potential_max_abs_error": 1e-4,
        "current_nrmse": 1e-5,
        "current_max_scaled_error": 1e-4,
    }
    if (
        not crosscheck.get("bdf_success")
        or not crosscheck.get("radau_success")
        or not crosscheck.get("passed")
        or any(
            not _finite_number(crosscheck.get(name))
            or crosscheck[name] > limit
            for name, limit in crosscheck_limits.items()
        )
    ):
        numerical_reasons.append("implicit backend cross-check failed")
    if (
        not baseline.get("payload_contract_valid")
        or not baseline.get("passed")
        or baseline.get("record_count") != 72
        or not _finite_number(baseline.get("max_relative_error"))
        or (
            _finite_number(baseline.get("max_relative_error"))
            and baseline["max_relative_error"] > 1e-12
        )
    ):
        numerical_reasons.append("frozen baseline comparison failed")
    m0 = summary.get("m0_fallback")
    if (
        not isinstance(m0, dict)
        or not m0.get("passed")
        or m0.get("state_max_abs_error") != 0.0
        or m0.get("current_max_abs_error") != 0.0
        or m0.get("backend_used") not in {"LSODA", "BDF"}
    ):
        physics_reasons.append("M0 fallback failed")

    if numerical_reasons:
        computed_gate = "FAIL_NUMERICAL"
        reasons = numerical_reasons
    elif physics_reasons:
        computed_gate = "FAIL_PHYSICS"
        reasons = physics_reasons
    else:
        computed_gate = "PASS"
        reasons = []
    fallback_cases = sorted(
        row["case_id"] for row in rows if row.get("fallback_used")
    )
    expected_summary = {
        "gate": computed_gate,
        "case_count": len(rows),
        "expected_case_count": len(CASE_IDS),
        "fallback_cases": fallback_cases,
        "eligible_for_next_gate": computed_gate == "PASS",
        "thresholds": THRESHOLDS,
    }
    if any(summary.get(key) != value for key, value in expected_summary.items()):
        return _result(
            "FAIL_STRUCTURE",
            ["runner summary disagrees with independent recomputation"],
        )
    return _result(computed_gate, reasons)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive", type=Path, required=True)
    args = parser.parse_args()
    result = validate_archive(args.archive.resolve())
    print(json.dumps(result, indent=2, sort_keys=True))
    return {
        "PASS": 0,
        "FAIL_PHYSICS": 2,
        "FAIL_NUMERICAL": 3,
        "FAIL_STRUCTURE": 4,
    }[result["gate"]]


if __name__ == "__main__":
    raise SystemExit(main())
