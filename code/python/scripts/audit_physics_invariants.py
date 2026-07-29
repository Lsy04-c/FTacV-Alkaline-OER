#!/usr/bin/env python3
"""Run the fixed synthetic Gate A2 physics-invariant audit."""

from __future__ import annotations

import argparse
from contextlib import redirect_stdout
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
    STOICHIOMETRIC_MATRIX,
    OERPhysics,
    coverage_derivatives,
    current_components,
    elementary_rates,
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
REQUIRED_ROW_FIELDS = {
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
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


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


def summarize_gate(
    rows: list[dict[str, Any]],
    baseline: dict[str, Any],
    m0: dict[str, Any],
) -> dict[str, Any]:
    """Classify complete compact evidence without repairing failed metrics."""
    case_ids = [row.get("case_id") for row in rows]
    structure_ok = (
        len(rows) == len(CASE_IDS)
        and set(case_ids) == set(CASE_IDS)
        and len(set(case_ids)) == len(CASE_IDS)
        and all(REQUIRED_ROW_FIELDS <= set(row) for row in rows)
        and "passed" in baseline
        and "baseline_sha256" in baseline
        and "passed" in m0
    )
    if not structure_ok:
        gate = "FAIL_STRUCTURE"
    else:
        numeric_values = [
            row[name]
            for row in rows
            for name in (
                "coverage_sum_max_error",
                "coverage_min",
                "coverage_max",
                "current_closure_relative_error",
                "steady_state_rhs_inf_norm",
                "thermodynamic_sum_error",
            )
        ]
        numerical_ok = (
            all(bool(row["solver_success"]) for row in rows)
            and all(bool(row["steady_state_success"]) for row in rows)
            and all(bool(row["finite"]) for row in rows)
            and all(np.isfinite(float(value)) for value in numeric_values)
            and all(
                row["coverage_sum_max_error"]
                <= THRESHOLDS["coverage_sum_max_error"]
                and row["coverage_min"] >= THRESHOLDS["coverage_min"]
                and row["coverage_max"] <= THRESHOLDS["coverage_max"]
                and row["projection_trigger_count"] == 0
                and row["current_closure_relative_error"]
                <= THRESHOLDS["current_closure_relative_error"]
                and row["steady_state_rhs_inf_norm"]
                <= THRESHOLDS["steady_state_rhs_inf_norm"]
                for row in rows
            )
            and bool(baseline["passed"])
        )
        physics_ok = (
            all(
                row["thermodynamic_sum_error"]
                <= THRESHOLDS["thermodynamic_sum_error"]
                for row in rows
            )
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
        "eligible_for_next_gate": gate == "PASS",
        "thresholds": THRESHOLDS,
    }


def _projection_count(t: float, y: np.ndarray, params: dict) -> int:
    rates = elementary_rates(t, y, params, validate=False)
    unprojected = coverage_derivatives(rates.net)
    return int(np.count_nonzero((y[:5] <= 0.0) & (unprojected < 0.0)))


def _run_case(case_id: str) -> dict[str, Any]:
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
        "solver_message": "",
    }
    try:
        initial = OERPhysics.calculate_steady_state(params)
        row["steady_state_rhs_inf_norm"] = validate_steady_state(
            initial, {**params, "v": 0.0, "dE": 0.0, "omega": 0.0},
            rhs_t=5.0,
        )
        row["steady_state_success"] = True
        projection_count = 0

        def rhs(t: float, y: np.ndarray) -> np.ndarray:
            nonlocal projection_count
            projection_count += _projection_count(t, y, params)
            return OERPhysics.oer_model(t, y, params)

        solution = solve_ivp(
            rhs,
            (0.0, params["total_time"]),
            initial,
            t_eval=params["t_span"],
            method="LSODA",
            rtol=1e-6,
            atol=1e-8,
            first_step=1e-8,
            max_step=min(
                params["total_time"] / 50.0,
                1.0 / (params["f"] * 20.0),
            ),
        )
        row["solver_success"] = bool(solution.success)
        row["solver_message"] = str(solution.message)
        row["projection_trigger_count"] = projection_count
        if not solution.success or solution.y.shape[1] != len(params["t_span"]):
            return row
        states = solution.y.T
        coverages = states[:, :5]
        closures = []
        component_values = []
        for time, state in zip(solution.t, states, strict=True):
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
                    np.all(np.isfinite(states))
                    and np.all(np.isfinite(component_values))
                ),
                "coverage_sum_max_error": float(
                    np.max(np.abs(np.sum(coverages, axis=1) - 1.0))
                ),
                "coverage_min": float(np.min(coverages)),
                "coverage_max": float(np.max(coverages)),
                "current_closure_relative_error": float(np.max(closures)),
                "n_time_points": int(len(solution.t)),
            }
        )
    except Exception as exc:  # preserve a compact failure record
        row["solver_message"] = f"{type(exc).__name__}: {exc}"
    return row


def _compare_baseline(path: Path) -> dict[str, Any]:
    baseline = json.loads(path.read_text(encoding="utf-8"))
    expected_payload = {
        key: value for key, value in baseline.items() if key != "contract"
    }
    payload_hash = hashlib.sha256(
        json.dumps(
            expected_payload,
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
            float(np.max(np.abs(actual - expected) / np.maximum(1.0, np.abs(expected))))
        )
    maximum = max(errors, default=float("inf"))
    return {
        "schema_version": 1,
        "passed": bool(
            contract_ok and maximum <= THRESHOLDS["baseline_relative_error"]
        ),
        "max_relative_error": maximum,
        "baseline_sha256": _sha256(path),
        "payload_contract_valid": contract_ok,
        "record_count": len(errors),
    }


def _m0_fallback() -> dict[str, Any]:
    params = _formal_params("default")
    params["use_steady_state"] = False
    changed = dict(params)
    changed.update({"E_recon": -99.0, "w_recon": 17.0})
    initial = np.array([1.0, 0.0, 0.0, 0.0, 0.0, params["E_start"]])
    grid = params["t_span"][: min(257, len(params["t_span"]))]
    end = float(grid[-1])

    def solve(p: dict) -> Any:
        return solve_ivp(
            lambda t, y: OERPhysics.oer_model(t, y, p),
            (0.0, end),
            initial,
            t_eval=grid,
            method="LSODA",
            rtol=1e-6,
            atol=1e-8,
            first_step=1e-8,
            max_step=1.0 / (p["f"] * 20.0),
        )

    base_sol = solve(params)
    changed_sol = solve(changed)
    solver_ok = (
        base_sol.success
        and changed_sol.success
        and base_sol.y.shape == changed_sol.y.shape
    )
    state_error = (
        float(np.max(np.abs(base_sol.y - changed_sol.y)))
        if solver_ok else float("inf")
    )
    base_current = np.array(
        [
            current_components(float(t), y, params).solution
            for t, y in zip(base_sol.t, base_sol.y.T, strict=True)
        ]
    ) if base_sol.success else np.array([np.inf])
    changed_current = np.array(
        [
            current_components(float(t), y, changed).solution
            for t, y in zip(changed_sol.t, changed_sol.y.T, strict=True)
        ]
    ) if changed_sol.success else np.array([-np.inf])
    current_error = (
        float(np.max(np.abs(base_current - changed_current)))
        if base_current.shape == changed_current.shape else float("inf")
    )
    return {
        "schema_version": 1,
        "passed": bool(solver_ok and state_error == 0.0 and current_error == 0.0),
        "state_max_abs_error": state_error,
        "current_max_abs_error": current_error,
        "solver_success": bool(solver_ok),
    }


def _write_json(path: Path, payload: Any) -> None:
    def json_safe(value: Any) -> Any:
        if isinstance(value, dict):
            return {key: json_safe(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [json_safe(item) for item in value]
        if isinstance(value, (float, np.floating)) and not np.isfinite(value):
            return None
        return value

    path.write_text(
        json.dumps(
            json_safe(payload),
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n",
        encoding="utf-8",
    )


def run(baseline_path: Path, output: Path) -> str:
    if output.exists() and any(output.iterdir()):
        raise FileExistsError("formal output directory must be new or empty")
    output.mkdir(parents=True, exist_ok=True)
    contract = {
        "schema_version": 1,
        "gate": "A2",
        "case_ids": list(CASE_IDS),
        "cycles": FORMAL_CYCLES,
        "points_per_cycle": FORMAL_POINTS_PER_CYCLE,
        "solver": {
            "method": "LSODA",
            "rtol": 1e-6,
            "atol": 1e-8,
            "first_step": 1e-8,
        },
        "stoichiometric_matrix": STOICHIOMETRIC_MATRIX.tolist(),
        "unit_ledger": UNIT_LEDGER,
        "thresholds": THRESHOLDS,
    }
    rows = [_run_case(case_id) for case_id in CASE_IDS]
    baseline = _compare_baseline(baseline_path)
    m0 = _m0_fallback()
    summary = summarize_gate(rows, baseline, m0)
    summary["m0_fallback"] = m0
    _write_json(output / "physics_contract.json", contract)
    (output / "trajectory_metrics.jsonl").write_text(
        "".join(
            json.dumps(
                {
                    key: (
                        None
                        if isinstance(value, (float, np.floating))
                        and not np.isfinite(value)
                        else value
                    )
                    for key, value in row.items()
                },
                sort_keys=True,
                allow_nan=False,
            )
            + "\n"
            for row in rows
        ),
        encoding="utf-8",
    )
    _write_json(output / "baseline_comparison.json", baseline)
    _write_json(output / "gate_a2_summary.json", summary)
    artifact_names = (
        "physics_contract.json",
        "trajectory_metrics.jsonl",
        "baseline_comparison.json",
        "gate_a2_summary.json",
    )
    manifest = {
        "schema_version": 1,
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "source_commit": _git("rev-parse", "HEAD"),
        "source_tree": _git("status", "--porcelain=v1"),
        "baseline_path": str(baseline_path.resolve()),
        "baseline_sha256": _sha256(baseline_path),
        "artifacts": {
            name: _sha256(output / name) for name in artifact_names
        },
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
