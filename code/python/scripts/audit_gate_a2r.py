#!/usr/bin/env python3
"""Run the fixed Gate A2-R conservative-integration audit."""

from __future__ import annotations

import argparse
from contextlib import redirect_stdout
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
from typing import Any

import numpy as np
from scipy.integrate import solve_ivp


PROJECT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT / "code" / "python" / "src"))

from oer_aem.defaults import initialize_oer_parameters  # noqa: E402
from oer_aem.physics import (  # noqa: E402
    DYNAMIC_ATOL,
    STOICHIOMETRIC_MATRIX,
    DynamicSolverError,
    OERPhysics,
    current_components,
    initialize_system,
    validate_steady_state,
)


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
FORMAL_CYCLES = 32
FORMAL_POINTS_PER_CYCLE = 128
DYNAMIC_ATOL_VALUES = [3e-11] * 5 + [1e-8]
K0_NAMES = ("k0_pre", "k0_1", "k0_2", "k0_3", "k0_4")
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


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=PROJECT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _base_params() -> dict[str, Any]:
    with redirect_stdout(io.StringIO()):
        return initialize_oer_parameters()


def _case_overrides() -> dict[str, dict[str, float]]:
    return {
        "default": {},
        "rates-low": {"rate_scale": 0.1},
        "rates-high": {"rate_scale": 10.0},
        "ru-low": {"Ru": 0.1},
        "ru-high": {"Ru": 500.0},
        "cdl-low": {"Cdl": 5e-6},
        "cdl-high": {"Cdl": 80e-6},
        "gamma-low": {"gamma": 1e-10},
        "gamma-high": {"gamma": 1e-7},
        "alpha-low": {"a": 0.25},
        "alpha-high": {"a": 0.75},
        "thermo-edge": {
            "G_OH": 1.8,
            "G_O": 2.2,
            "scaling_OOH_OH": 3.6,
        },
    }


def _formal_params(case_id: str) -> dict[str, Any]:
    params = _base_params()
    changes = dict(_case_overrides()[case_id])
    scale = changes.pop("rate_scale", None)
    params.update(changes)
    if scale is not None:
        for name in K0_NAMES:
            params[name] *= scale
    if case_id == "thermo-edge":
        params = OERPhysics.apply_alkaline_aem_embedded(params)
    params["n_points"] = FORMAL_CYCLES * FORMAL_POINTS_PER_CYCLE
    params["total_time"] = FORMAL_CYCLES / params["f"]
    params["v"] = (
        params["E_end"] - params["E_start"]
    ) / params["total_time"]
    params["t_span"] = np.linspace(
        0.0, params["total_time"], params["n_points"]
    )
    return initialize_system(params)


def _backend_policy_ok(
    rows: list[dict[str, Any]],
    attempt_rows: list[dict[str, Any]],
) -> bool:
    by_case = {
        item.get("case_id"): item.get("attempts")
        for item in attempt_rows
        if isinstance(item, dict)
    }
    for row in rows:
        case_id = row["case_id"]
        attempts = by_case.get(case_id)
        if not isinstance(attempts, list) or not attempts:
            return False
        if case_id != "thermo-edge":
            if (
                row["backend_used"] != "LSODA"
                or row["fallback_used"]
                or len(attempts) != 1
                or attempts[0].get("backend") != "LSODA"
                or attempts[0].get("success") is not True
            ):
                return False
            continue
        if row["backend_used"] == "LSODA":
            if (
                row["fallback_used"]
                or len(attempts) != 1
                or attempts[0].get("backend") != "LSODA"
                or attempts[0].get("success") is not True
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
            ):
                return False
        else:
            return False
    return True


def summarize_gate(
    rows: list[dict[str, Any]],
    attempt_rows: list[dict[str, Any]],
    baseline: dict[str, Any],
    m0: dict[str, Any],
    crosscheck: dict[str, Any],
) -> dict[str, Any]:
    """Classify A2-R evidence while preserving failure categories."""
    case_ids = [row.get("case_id") for row in rows]
    attempt_ids = [row.get("case_id") for row in attempt_rows]
    structure_ok = (
        len(rows) == len(CASE_IDS)
        and set(case_ids) == set(CASE_IDS)
        and len(set(case_ids)) == len(CASE_IDS)
        and len(attempt_rows) == len(CASE_IDS)
        and set(attempt_ids) == set(CASE_IDS)
        and len(set(attempt_ids)) == len(CASE_IDS)
        and all(ROW_FIELDS <= set(row) for row in rows)
        and "passed" in baseline
        and "baseline_sha256" in baseline
        and "passed" in m0
        and "passed" in crosscheck
    )
    if not structure_ok:
        gate = "FAIL_STRUCTURE"
    else:
        numeric_names = (
            "coverage_sum_max_error",
            "coverage_min",
            "coverage_max",
            "current_closure_relative_error",
            "steady_state_rhs_inf_norm",
            "thermodynamic_sum_error",
        )
        finite_metrics = all(
            np.isfinite(float(row[name]))
            for row in rows
            for name in numeric_names
        )
        numerical_ok = (
            finite_metrics
            and all(row["solver_success"] for row in rows)
            and all(row["steady_state_success"] for row in rows)
            and all(row["finite"] for row in rows)
            and all(
                row["coverage_sum_max_error"] <= 1e-8
                and row["coverage_min"] >= -1e-8
                and row["coverage_max"] <= 1.0 + 1e-8
                and row["projection_trigger_count"] == 0
                and row["current_closure_relative_error"] <= 1e-10
                and row["steady_state_rhs_inf_norm"] <= 1e-8
                for row in rows
            )
            and _backend_policy_ok(rows, attempt_rows)
            and bool(baseline["passed"])
            and bool(crosscheck["passed"])
        )
        physics_ok = (
            all(row["thermodynamic_sum_error"] <= 1e-12 for row in rows)
            and bool(m0["passed"])
        )
        if not numerical_ok:
            gate = "FAIL_NUMERICAL"
        elif not physics_ok:
            gate = "FAIL_PHYSICS"
        else:
            gate = "PASS"
    return {
        "schema_version": 1,
        "gate": gate,
        "case_count": len(rows),
        "expected_case_count": len(CASE_IDS),
        "fallback_cases": sorted(
            row["case_id"] for row in rows if row.get("fallback_used")
        ),
        "eligible_for_next_gate": gate == "PASS",
        "thresholds": THRESHOLDS,
    }


def _attempt_dicts(attempts: tuple) -> list[dict[str, Any]]:
    return [asdict(item) for item in attempts]


def _run_case(
    case_id: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    params = _formal_params(case_id)
    row: dict[str, Any] = {
        "case_id": case_id,
        "solver_success": False,
        "steady_state_success": False,
        "finite": False,
        "coverage_sum_max_error": float("inf"),
        "coverage_min": float("-inf"),
        "coverage_max": float("inf"),
        "projection_trigger_count": 0,
        "current_closure_relative_error": float("inf"),
        "steady_state_rhs_inf_norm": float("inf"),
        "thermodynamic_sum_error": abs(
            sum(params[f"DeltaG{i}"] for i in range(1, 5)) - 4.92
        ),
        "backend_used": "",
        "fallback_used": False,
        "solver_message": "",
    }
    attempt_row = {"case_id": case_id, "attempts": []}
    try:
        initial = OERPhysics.calculate_steady_state(params)
        stationary = dict(params)
        stationary.update({"v": 0.0, "dE": 0.0, "omega": 0.0})
        row["steady_state_rhs_inf_norm"] = validate_steady_state(
            initial, stationary, rhs_t=5.0
        )
        row["steady_state_success"] = True
        result = OERPhysics.solve_ode_system_detailed(params)
        attempt_row["attempts"] = _attempt_dicts(result.attempts)
        row.update(
            {
                "solver_success": True,
                "backend_used": result.backend_used,
                "fallback_used": result.fallback_used,
                "solver_message": result.attempts[-1].message,
                "n_time_points": int(len(result.t)),
            }
        )
        coverages = result.y[:, :5]
        closures = []
        component_values = []
        for time, state in zip(result.t, result.y, strict=True):
            parts = current_components(float(time), state, params)
            scale = max(
                abs(parts.solution),
                abs(parts.capacitive),
                abs(parts.faradaic),
                1e-12,
            )
            closures.append(abs(parts.closure_residual) / scale)
            component_values.extend(
                (parts.solution, parts.capacitive, parts.faradaic)
            )
        row.update(
            {
                "finite": bool(
                    np.all(np.isfinite(result.y))
                    and np.all(np.isfinite(component_values))
                ),
                "coverage_sum_max_error": float(
                    np.max(np.abs(np.sum(coverages, axis=1) - 1.0))
                ),
                "coverage_min": float(np.min(coverages)),
                "coverage_max": float(np.max(coverages)),
                "current_closure_relative_error": float(np.max(closures)),
            }
        )
    except DynamicSolverError as exc:
        attempt_row["attempts"] = _attempt_dicts(exc.attempts)
        row["solver_message"] = str(exc)
    except Exception as exc:  # preserve compact failure evidence
        row["solver_message"] = f"{type(exc).__name__}: {exc}"
    return row, attempt_row


def _compare_baseline(path: Path) -> dict[str, Any]:
    baseline = json.loads(path.read_text(encoding="utf-8"))
    payload = {
        key: value for key, value in baseline.items() if key != "contract"
    }
    payload_hash = hashlib.sha256(
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode()
    ).hexdigest()
    contract_ok = payload_hash == baseline["contract"]["payload_sha256"]
    errors = []
    for record in baseline["rhs_records"]:
        expected = np.asarray(record["dydt"], dtype=float)
        actual = OERPhysics.oer_model(
            record["time"],
            np.asarray(record["state"], dtype=float),
            record["params"],
        )
        errors.append(
            float(
                np.max(
                    np.abs(actual - expected)
                    / np.maximum(1.0, np.abs(expected))
                )
            )
        )
    maximum = max(errors, default=float("inf"))
    return {
        "schema_version": 1,
        "passed": bool(contract_ok and maximum <= 1e-12),
        "max_relative_error": maximum,
        "baseline_sha256": _sha256(path),
        "payload_contract_valid": contract_ok,
        "record_count": len(errors),
    }


def _m0_fallback() -> dict[str, Any]:
    params = _formal_params("default")
    params["use_steady_state"] = False
    params["n_points"] = 257
    params["total_time"] = 2.0 / params["f"]
    params["v"] = (
        params["E_end"] - params["E_start"]
    ) / params["total_time"]
    params["t_span"] = np.linspace(0.0, params["total_time"], 257)
    params = initialize_system(params)
    changed = dict(params)
    changed.update({"E_recon": -99.0, "w_recon": 17.0})
    base = OERPhysics.solve_ode_system_detailed(params)
    alternative = OERPhysics.solve_ode_system_detailed(changed)
    state_error = float(np.max(np.abs(base.y - alternative.y)))
    current_error = float(np.max(np.abs(base.i_total - alternative.i_total)))
    return {
        "schema_version": 1,
        "passed": bool(
            state_error == 0.0
            and current_error == 0.0
            and base.backend_used == alternative.backend_used
        ),
        "state_max_abs_error": state_error,
        "current_max_abs_error": current_error,
        "backend_used": base.backend_used,
    }


def _implicit_crosscheck() -> dict[str, Any]:
    params = _formal_params("thermo-edge")
    initial = OERPhysics.calculate_steady_state(params)
    outputs = {}
    for backend in ("BDF", "Radau"):
        sol = solve_ivp(
            lambda t, y: OERPhysics.oer_model(t, y, params),
            (0.0, params["total_time"]),
            initial.copy(),
            t_eval=params["t_span"],
            method=backend,
            rtol=1e-6,
            atol=DYNAMIC_ATOL.copy(),
            max_step=1.0 / (params["f"] * 20.0),
        )
        outputs[backend] = sol
    bdf = outputs["BDF"]
    radau = outputs["Radau"]
    complete = (
        bdf.success
        and radau.success
        and len(bdf.t) == len(params["t_span"])
        and len(radau.t) == len(params["t_span"])
    )
    if complete:
        potential = (
            params["E_start"]
            + params["v"] * bdf.t
            + params["dE"] * np.sin(params["omega"] * bdf.t)
        )
        bdf_current = (potential - bdf.y[5]) / params["Ru"]
        radau_current = (potential - radau.y[5]) / params["Ru"]
        current_scale = max(float(np.ptp(radau_current)), 1e-12)
        coverage_error = float(
            np.max(np.abs(bdf.y[:5] - radau.y[:5]))
        )
        potential_error = float(np.max(np.abs(bdf.y[5] - radau.y[5])))
        current_nrmse = float(
            np.sqrt(np.mean((bdf_current - radau_current) ** 2))
            / current_scale
        )
        current_max = float(
            np.max(np.abs(bdf_current - radau_current)) / current_scale
        )
    else:
        coverage_error = potential_error = float("inf")
        current_nrmse = current_max = float("inf")
    passed = bool(
        complete
        and coverage_error <= 1e-5
        and potential_error <= 1e-4
        and current_nrmse <= 1e-5
        and current_max <= 1e-4
    )
    return {
        "schema_version": 1,
        "passed": passed,
        "bdf_success": bool(bdf.success),
        "radau_success": bool(radau.success),
        "bdf_message": str(bdf.message),
        "radau_message": str(radau.message),
        "coverage_max_abs_error": coverage_error,
        "surface_potential_max_abs_error": potential_error,
        "current_nrmse": current_nrmse,
        "current_max_scaled_error": current_max,
    }


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (float, np.floating)) and not np.isfinite(value):
        return None
    return value


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(
            _json_safe(payload),
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n",
        encoding="utf-8",
    )


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text(
        "".join(
            json.dumps(
                _json_safe(row), sort_keys=True, allow_nan=False
            )
            + "\n"
            for row in rows
        ),
        encoding="utf-8",
    )


def run(baseline_path: Path, output: Path) -> str:
    if output.exists() and any(output.iterdir()):
        raise FileExistsError("formal output directory must be new or empty")
    output.mkdir(parents=True, exist_ok=True)
    if not np.array_equal(DYNAMIC_ATOL, np.asarray(DYNAMIC_ATOL_VALUES)):
        raise RuntimeError("runtime dynamic tolerances differ from A2-R")
    contract = {
        "schema_version": 1,
        "gate": "A2-R",
        "case_ids": list(CASE_IDS),
        "cycles": FORMAL_CYCLES,
        "points_per_cycle": FORMAL_POINTS_PER_CYCLE,
        "solver_policy": {
            "order": ["LSODA", "BDF"],
            "rtol": 1e-6,
            "dynamic_atol": DYNAMIC_ATOL_VALUES,
            "lsoda_first_step": 1e-8,
        },
        "stoichiometric_matrix": STOICHIOMETRIC_MATRIX.tolist(),
        "unit_ledger": UNIT_LEDGER,
        "thresholds": THRESHOLDS,
        "historical_failed_archive": "gate-a2-6486d69",
    }
    evidence = [_run_case(case_id) for case_id in CASE_IDS]
    rows = [item[0] for item in evidence]
    attempt_rows = [item[1] for item in evidence]
    baseline = _compare_baseline(baseline_path)
    m0 = _m0_fallback()
    crosscheck = _implicit_crosscheck()
    summary = summarize_gate(
        rows, attempt_rows, baseline, m0, crosscheck
    )
    summary["m0_fallback"] = m0
    _write_json(output / "physics_contract.json", contract)
    _write_jsonl(output / "trajectory_metrics.jsonl", rows)
    _write_jsonl(output / "backend_attempts.jsonl", attempt_rows)
    _write_json(output / "implicit_crosscheck.json", crosscheck)
    _write_json(output / "baseline_comparison.json", baseline)
    _write_json(output / "gate_a2r_summary.json", summary)
    artifacts = (
        "physics_contract.json",
        "trajectory_metrics.jsonl",
        "backend_attempts.jsonl",
        "implicit_crosscheck.json",
        "baseline_comparison.json",
        "gate_a2r_summary.json",
    )
    manifest = {
        "schema_version": 1,
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "source_commit": _git("rev-parse", "HEAD"),
        "source_tree": _git("status", "--porcelain=v1"),
        "baseline_path": str(baseline_path.resolve()),
        "baseline_sha256": _sha256(baseline_path),
        "artifacts": {name: _sha256(output / name) for name in artifacts},
    }
    _write_json(output / "run_manifest.json", manifest)
    return summary["gate"]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    gate = run(args.baseline.resolve(), args.output.resolve())
    print(gate)
    return {"PASS": 0, "FAIL_PHYSICS": 2, "FAIL_NUMERICAL": 3}.get(gate, 4)


if __name__ == "__main__":
    raise SystemExit(main())
