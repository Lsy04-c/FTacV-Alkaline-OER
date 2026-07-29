#!/usr/bin/env python3
"""Independently validate a compact Gate A2 physics archive."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
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
ARTIFACTS = (
    "physics_contract.json",
    "trajectory_metrics.jsonl",
    "baseline_comparison.json",
    "gate_a2_summary.json",
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


def validate_archive(archive: Path) -> dict[str, Any]:
    """Reload all evidence and recompute the Gate without runner imports."""
    archive = Path(archive)
    required = (*ARTIFACTS, "run_manifest.json")
    if not archive.is_dir() or any(
        not (archive / name).is_file() for name in required
    ):
        return _result("FAIL_STRUCTURE", ["missing required artifact"])
    try:
        contract = json.loads(
            (archive / ARTIFACTS[0]).read_text(encoding="utf-8")
        )
        rows = [
            json.loads(line)
            for line in (archive / ARTIFACTS[1])
            .read_text(encoding="utf-8")
            .splitlines()
            if line.strip()
        ]
        baseline = json.loads(
            (archive / ARTIFACTS[2]).read_text(encoding="utf-8")
        )
        summary = json.loads(
            (archive / ARTIFACTS[3]).read_text(encoding="utf-8")
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
    if (
        baseline.get("baseline_sha256") != manifest.get("baseline_sha256")
    ):
        structure_reasons.append("baseline provenance hash mismatch")
    row_ids = [row.get("case_id") for row in rows if isinstance(row, dict)]
    if (
        len(rows) != len(CASE_IDS)
        or len(row_ids) != len(rows)
        or set(row_ids) != set(CASE_IDS)
        or len(set(row_ids)) != len(CASE_IDS)
    ):
        structure_reasons.append("case library is incomplete or duplicated")
    if any(
        not isinstance(row, dict) or not ROW_FIELDS <= set(row)
        for row in rows
    ):
        structure_reasons.append("trajectory row schema mismatch")
    if contract.get("case_ids") != list(CASE_IDS):
        structure_reasons.append("contract case order mismatch")
    if (
        contract.get("gate") != "A2"
        or contract.get("cycles") != 32
        or contract.get("points_per_cycle") != 128
        or contract.get("thresholds") != THRESHOLDS
        or contract.get("solver")
        != {
            "method": "LSODA",
            "rtol": 1e-6,
            "atol": 1e-8,
            "first_step": 1e-8,
        }
    ):
        structure_reasons.append("frozen execution contract mismatch")
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
    metric_names = (
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
        for name in metric_names
    ):
        numerical_reasons.append("non-finite or null metric")
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
        or not m0.get("solver_success")
        or m0.get("state_max_abs_error") != 0.0
        or m0.get("current_max_abs_error") != 0.0
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
    expected_summary = {
        "gate": computed_gate,
        "case_count": len(rows),
        "expected_case_count": len(CASE_IDS),
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
