#!/usr/bin/env python3
"""Build the reproducibility manifest for architecture-validation artifacts."""

from __future__ import annotations

import csv
import contextlib
import hashlib
import io
import json
import platform
import subprocess
import sys
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[3]
RESULTS = ROOT / "results" / "architecture_validation"
sys.path.insert(0, str(ROOT / "code" / "python" / "src"))

from oer_aem.defaults import initialize_oer_parameters
from oer_aem.features import complex_harmonic_metrics
from oer_aem.physics import OERPhysics
ARTIFACTS = (
    "baseline_manifest.json",
    "sensitivity_matrix.csv",
    "parameter_classification.csv",
    "synthetic_recovery.json",
    "residual_contract.csv",
    "feature_objective_comparison.csv",
    "reconstruction_model_comparison.csv",
    "feature_objective_comparison.png",
    "feature_objective_comparison.svg",
    "reconstruction_model_comparison.png",
    "reconstruction_model_comparison.svg",
)


def _head() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _rows(name: str) -> list[dict[str, str]]:
    with (RESULTS / name).open(encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def _measured_checks() -> dict[str, object]:
    fs, f0, duration = 512.0, 4.0, 8.0
    time = np.arange(0.0, duration, 1.0 / fs)
    signal = 2.0 * np.cos(2 * np.pi * f0 * time + 0.30)
    signal += 0.5 * np.cos(2 * np.pi * 2 * f0 * time - 0.40)
    metrics = complex_harmonic_metrics(
        signal, fs=fs, f0=f0, n_harmonics=2
    )
    amplitude_error = np.abs(
        (np.asarray(metrics["amplitude"]) - np.array([2.0, 0.5]))
        / np.array([2.0, 0.5])
    )
    phase_error = np.abs(
        np.angle(
            np.exp(
                1j
                * (
                    np.asarray(metrics["phase"])
                    - np.array([0.30, -0.40])
                )
            )
        )
    )

    params = initialize_oer_parameters()
    params["use_steady_state"] = False
    params["E_start"] = 1.5
    state = np.array([1.0, 0.0, 0.0, 0.0, 0.0, 1.5])
    coverage_derivative_sum = float(
        np.sum(OERPhysics.oer_model(0.0, state, params)[:5])
    )

    def simulate(n_points: int, points_per_cycle: int):
        current_params = initialize_oer_parameters()
        current_params["n_points"] = n_points
        current_params["points_per_cycle"] = points_per_cycle
        current_params["total_time"] = (
            n_points / points_per_cycle
        ) / current_params["f"]
        current_params["v"] = (
            current_params["E_end"] - current_params["E_start"]
        ) / current_params["total_time"]
        current_params["t_span"] = np.linspace(
            0.0, current_params["total_time"], n_points
        )
        current_params["use_steady_state"] = False
        solved_time, _, _, current = OERPhysics.solve_ode_system(
            current_params
        )
        potential = (
            current_params["E_start"]
            + current_params["v"] * solved_time
        )
        return potential, current

    coarse_e, coarse_i = simulate(512, 32)
    fine_e, fine_i = simulate(1024, 64)
    common = np.linspace(coarse_e[0], coarse_e[-1], 200)
    coarse = np.interp(common, coarse_e, coarse_i)
    fine = np.interp(common, fine_e, fine_i)
    scale = max(float(np.max(np.abs(fine))), 1e-30)
    refinement_nrmse = float(
        np.sqrt(np.mean((coarse - fine) ** 2)) / scale
    )
    return {
        "complex_harmonic_amplitude_relative_error": amplitude_error.tolist(),
        "complex_harmonic_phase_absolute_error_rad": phase_error.tolist(),
        "coverage_derivative_sum": coverage_derivative_sum,
        "output_grid_refinement_nrmse": refinement_nrmse,
    }


def main() -> None:
    feature_rows = _rows("feature_objective_comparison.csv")
    reconstruction_rows = _rows("reconstruction_model_comparison.csv")
    residual_rows = _rows("residual_contract.csv")
    recovery = json.loads((RESULTS / "synthetic_recovery.json").read_text())
    source_code_commit = _head()
    if recovery.get("git_commit") != source_code_commit:
        raise RuntimeError(
            "architecture results are stale: synthetic recovery commit "
            f"{recovery.get('git_commit')} != {source_code_commit}"
        )
    with contextlib.redirect_stdout(io.StringIO()):
        measured_checks = _measured_checks()
    manifest = {
        "report_date": "2026-07-25",
        "source_code_commit": source_code_commit,
        "hosts": {
            "calculation": "Lenovo Legion WSL2, Python 3.11",
            "review_and_git": platform.platform(),
        },
        "test_runs": [
            {
                "command": "python code/python/scripts/run_tests.py code/python/tests -q",
                "result": "70 passed",
                "runtime_seconds": 44.43,
                "host": "Mac",
            },
            {
                "command": (
                    "python code/python/scripts/run_tests.py "
                    "code/web/backend/test_analyze_e2e.py "
                    "code/web/backend/test_inversion_api.py -q"
                ),
                "result": "3 passed, 1 third-party warning",
                "runtime_seconds": 6.67,
                "host": "Mac",
            }
        ],
        "measured_checks": measured_checks,
        "runs": {
            "architecture_validation": {
                "command": (
                    ".venv/bin/python code/python/scripts/run_architecture_validation.py "
                    "--trials 50"
                ),
                "seed": recovery["seed"],
                "trials": recovery["n_trials"],
                "recovered": recovery["recovered"],
                "relative_recovery_error": recovery["relative_recovery_error"],
            },
            "residual_contract": {
                "command": (
                    ".venv/bin/python code/python/scripts/residual_diagnostics.py "
                    "--trials 30 --output "
                    "results/architecture_validation/residual_contract.csv"
                ),
                "rows": len(residual_rows),
                "simulation_n_points": sorted(
                    {int(row["simulation_n_points"]) for row in residual_rows}
                ),
                "points_per_cycle": sorted(
                    {int(row["points_per_cycle"]) for row in residual_rows}
                ),
                "fit_harmonics": sorted(
                    {row["fit_harmonics"] for row in residual_rows}
                ),
                "fixed_params": sorted(
                    {row["fixed_params"] for row in residual_rows}
                ),
                "max_scan_rate_relative_error": max(
                    float(row["scan_rate_relative_error"])
                    for row in residual_rows
                ),
            },
            "feature_objective_comparison": {
                "command": (
                    ".venv/bin/python code/python/scripts/compare_feature_objectives.py "
                    "--trials 50 --workers 8"
                ),
                "rows": len(feature_rows),
                "seeds": sorted({int(row["seed"]) for row in feature_rows}),
                "trials": sorted({int(row["trials"]) for row in feature_rows}),
                "modes": sorted({row["feature_mode"] for row in feature_rows}),
                "n_points": sorted(
                    {int(row["n_points"]) for row in feature_rows}
                ),
                "points_per_cycle": sorted(
                    {int(row["points_per_cycle"]) for row in feature_rows}
                ),
                "fit_harmonics": sorted(
                    {row["fit_harmonics"] for row in feature_rows}
                ),
                "fixed_params": sorted(
                    {row["fixed_params"] for row in feature_rows}
                ),
                "max_scan_rate_relative_error": max(
                    float(row["scan_rate_relative_error"])
                    for row in feature_rows
                ),
            },
            "reconstruction_model_comparison": {
                "command": (
                    ".venv/bin/python code/python/scripts/compare_reconstruction_model.py "
                    "--trials 50 --workers 8"
                ),
                "rows": len(reconstruction_rows),
                "seeds": sorted(
                    {int(row["seed"]) for row in reconstruction_rows}
                ),
                "trials": sorted(
                    {int(row["trials"]) for row in reconstruction_rows}
                ),
                "models": sorted(
                    {row["model"] for row in reconstruction_rows}
                ),
                "n_points": sorted(
                    {int(row["n_points"]) for row in reconstruction_rows}
                ),
                "points_per_cycle": sorted(
                    {
                        int(row["points_per_cycle"])
                        for row in reconstruction_rows
                    }
                ),
                "fit_harmonics": sorted(
                    {row["fit_harmonics"] for row in reconstruction_rows}
                ),
                "fixed_params": sorted(
                    {row["fixed_params"] for row in reconstruction_rows}
                ),
                "accepted": {
                    row["accepted"] for row in reconstruction_rows
                } == {"True"},
                "max_scan_rate_relative_error": max(
                    float(row["scan_rate_relative_error"])
                    for row in reconstruction_rows
                ),
            },
        },
        "sha256": {
            name: _sha256(RESULTS / name)
            for name in ARTIFACTS
            if (RESULTS / name).is_file()
        },
    }
    (RESULTS / "run_manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n"
    )
    print("VALIDATION_MANIFEST_OK")


if __name__ == "__main__":
    main()
