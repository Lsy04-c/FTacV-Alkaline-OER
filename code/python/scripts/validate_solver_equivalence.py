#!/usr/bin/env python3
"""Compare C++ Crank-Nicolson and LSODA in the inversion feature space."""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from pathlib import Path
from typing import Sequence

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "code" / "python" / "src"))

from oer_aem.inversion import (  # noqa: E402
    DEFAULT_PARAM_SPECS,
    InversionConfig,
    extract_features,
    forward_current,
    params_from_vector,
)
from oer_aem.physics import OERPhysics  # noqa: E402
from oer_aem.cpp_bridge import (  # noqa: E402
    is_available as cn_is_available,
    solve_cn_with_status,
)

RESOLVABILITY_FRACTION = 0.02
CSV_FIELDS = (
    "sample",
    "harmonic",
    "lsoda_success",
    "cn_success",
    "lsoda_status",
    "cn_status",
    "lsoda_time_s",
    "cn_time_s",
    "current_nrmse",
    "dc_nrmse",
    "global_relative_strength",
    "global_resolved",
    "lockin_relative_strength",
    "lockin_resolved",
    "global_amplitude_relative_error",
    "global_phase_error_rad",
    "lockin_amplitude_nrmse",
    "lockin_phase_rmse_rad",
    "peak_shift_v",
)


def sample_parameter_vectors(
    specs: Sequence[tuple[str, str, float, float]],
    n_samples: int,
    seed: int,
) -> np.ndarray:
    """Return deterministic stratified samples inside encoded parameter bounds."""
    if n_samples < 1:
        raise ValueError("n_samples must be positive")
    rng = np.random.default_rng(seed)
    unit = np.empty((n_samples, len(specs)), dtype=float)
    for column in range(len(specs)):
        strata = (np.arange(n_samples) + rng.random(n_samples)) / n_samples
        unit[:, column] = strata[rng.permutation(n_samples)]
    unit = 0.05 + 0.90 * unit
    lows = np.asarray([spec[2] for spec in specs], dtype=float)
    highs = np.asarray([spec[3] for spec in specs], dtype=float)
    return lows + unit * (highs - lows)


def normalized_rmse(candidate: np.ndarray, reference: np.ndarray) -> float:
    """Return RMSE normalized by the maximum absolute reference value."""
    candidate_values = np.asarray(candidate, dtype=float)
    reference_values = np.asarray(reference, dtype=float)
    scale = max(float(np.max(np.abs(reference_values))), np.finfo(float).eps)
    return float(np.sqrt(np.mean((candidate_values - reference_values) ** 2)) / scale)


def wrapped_phase_rmse(candidate: np.ndarray, reference: np.ndarray) -> float:
    """Return circular RMSE between wrapped phase arrays."""
    delta = np.angle(
        np.exp(
            1j
            * (
                np.asarray(candidate, dtype=float)
                - np.asarray(reference, dtype=float)
            )
        )
    )
    return float(np.sqrt(np.mean(delta**2)))


def _config(
    backend: str,
    points_per_cycle: int,
    cycles: int,
) -> InversionConfig:
    return InversionConfig(
        E_start=0.924,
        E_end=1.923,
        f=5.0,
        dE=0.16,
        n_points=points_per_cycle * cycles,
        points_per_cycle=points_per_cycle,
        feature_grid_size=128,
        fit_harmonics=(1, 2, 3, 4, 5, 6, 7),
        # The comparison reports both global complex harmonics and potential-
        # resolved lock-in metrics; lockin_only omits the former and causes a
        # KeyError during a real comparison.
        feature_mode="hybrid",
        solver_backend=backend,
    )


def _solve_with_status(
    vector: np.ndarray,
    config: InversionConfig,
) -> tuple[np.ndarray | None, float, int]:
    started = time.perf_counter()
    if config.solver_backend == "cn":
        try:
            params = params_from_vector(vector, config, DEFAULT_PARAM_SPECS)
            y0 = np.zeros(6, dtype=float)
            y0[0] = 1.0
            y0[5] = params["E_start"]
            if params.get("use_steady_state", True):
                y0 = OERPhysics.calculate_steady_state(params)
            current, status = solve_cn_with_status(params, y0=y0)
            return current, time.perf_counter() - started, int(status)
        except Exception:
            return None, time.perf_counter() - started, -5
    current = forward_current(vector, config, DEFAULT_PARAM_SPECS)
    return current, time.perf_counter() - started, (0 if current is not None else -5)


def _solve(
    vector: np.ndarray,
    config: InversionConfig,
) -> tuple[np.ndarray | None, float]:
    """Historical two-value wrapper retained for callers and tests."""
    current, elapsed, _status = _solve_with_status(vector, config)
    return current, elapsed


def compare_sample(
    sample_index: int,
    vector: np.ndarray,
    points_per_cycle: int,
    cycles: int,
) -> list[dict[str, object]]:
    """Compare both solvers for one parameter vector."""
    lsoda_config = _config("lsoda", points_per_cycle, cycles)
    cn_config = _config("cn", points_per_cycle, cycles)
    lsoda_current, lsoda_time, lsoda_status = _solve_with_status(
        vector, lsoda_config
    )
    cn_current, cn_time, cn_status = _solve_with_status(vector, cn_config)
    if lsoda_current is None or cn_current is None:
        return [
            {
                "sample": sample_index,
                "harmonic": 0,
                "lsoda_success": lsoda_current is not None,
                "cn_success": cn_current is not None,
                "lsoda_status": lsoda_status,
                "cn_status": cn_status,
                "lsoda_time_s": lsoda_time,
                "cn_time_s": cn_time,
                "current_nrmse": float("nan"),
                "dc_nrmse": float("nan"),
                "global_relative_strength": float("nan"),
                "global_resolved": False,
                "lockin_relative_strength": float("nan"),
                "lockin_resolved": False,
                "global_amplitude_relative_error": float("nan"),
                "global_phase_error_rad": float("nan"),
                "lockin_amplitude_nrmse": float("nan"),
                "lockin_phase_rmse_rad": float("nan"),
                "peak_shift_v": float("nan"),
            }
        ]

    lsoda_features = extract_features(lsoda_current, lsoda_config)
    cn_features = extract_features(cn_current, cn_config)
    current_error = normalized_rmse(cn_current, lsoda_current)
    dc_error = normalized_rmse(cn_features["dc"], lsoda_features["dc"])
    rows: list[dict[str, object]] = []
    grid = lsoda_config.e_grid
    global_lsoda = lsoda_features["complex_harmonics"]
    global_cn = cn_features["complex_harmonics"]
    lockin_lsoda = lsoda_features["lockin"]
    lockin_cn = cn_features["lockin"]
    common_valid = (
        np.asarray(lockin_lsoda["valid_mask"], dtype=bool)
        & np.asarray(lockin_cn["valid_mask"], dtype=bool)
    )
    if np.count_nonzero(common_valid) < 2:
        raise ValueError("CN and LSODA lock-in features have no common valid region")
    global_reference_amplitudes = np.asarray(global_lsoda["amplitude"], dtype=float)
    global_scale = max(
        float(np.max(np.abs(global_reference_amplitudes))),
        np.finfo(float).eps,
    )
    lockin_reference_amplitudes = np.asarray(lockin_lsoda["amplitude"], dtype=float)
    lockin_rms = np.sqrt(
        np.mean(lockin_reference_amplitudes[:, common_valid] ** 2, axis=1)
    )
    lockin_scale = max(float(np.max(lockin_rms)), np.finfo(float).eps)

    for index, harmonic in enumerate(lsoda_config.fit_harmonics):
        reference_amplitude = float(global_lsoda["amplitude"][index])
        candidate_amplitude = float(global_cn["amplitude"][index])
        global_relative_strength = abs(reference_amplitude) / global_scale
        lockin_relative_strength = float(lockin_rms[index]) / lockin_scale
        global_amplitude_error = abs(candidate_amplitude - reference_amplitude) / max(
            abs(reference_amplitude),
            np.finfo(float).eps,
        )
        global_phase_error = abs(
            float(
                np.angle(
                    np.exp(
                        1j
                        * (
                            float(global_cn["phase"][index])
                            - float(global_lsoda["phase"][index])
                        )
                    )
                )
            )
        )
        reference_lockin_amplitude = np.asarray(
            lockin_lsoda["amplitude"][index],
            dtype=float,
        )[common_valid]
        candidate_lockin_amplitude = np.asarray(
            lockin_cn["amplitude"][index],
            dtype=float,
        )[common_valid]
        reference_lockin_phase = np.asarray(
            lockin_lsoda["phase"][index],
            dtype=float,
        )[common_valid]
        candidate_lockin_phase = np.asarray(
            lockin_cn["phase"][index],
            dtype=float,
        )[common_valid]
        valid_grid = grid[common_valid]
        peak_reference = float(
            valid_grid[np.argmax(reference_lockin_amplitude)]
        )
        peak_candidate = float(
            valid_grid[np.argmax(candidate_lockin_amplitude)]
        )
        rows.append(
            {
                "sample": sample_index,
                "harmonic": harmonic,
                "lsoda_success": True,
                "cn_success": True,
                "lsoda_status": lsoda_status,
                "cn_status": cn_status,
                "lsoda_time_s": lsoda_time,
                "cn_time_s": cn_time,
                "current_nrmse": current_error,
                "dc_nrmse": dc_error,
                "global_relative_strength": global_relative_strength,
                "global_resolved": global_relative_strength >= RESOLVABILITY_FRACTION,
                "lockin_relative_strength": lockin_relative_strength,
                "lockin_resolved": lockin_relative_strength >= RESOLVABILITY_FRACTION,
                "global_amplitude_relative_error": global_amplitude_error,
                "global_phase_error_rad": global_phase_error,
                "lockin_amplitude_nrmse": normalized_rmse(
                    candidate_lockin_amplitude,
                    reference_lockin_amplitude,
                ),
                "lockin_phase_rmse_rad": wrapped_phase_rmse(
                    candidate_lockin_phase,
                    reference_lockin_phase,
                ),
                "peak_shift_v": abs(peak_candidate - peak_reference),
            }
        )
    return rows


def assess_gate(rows: Sequence[dict[str, object]]) -> dict[str, object]:
    """Apply predeclared feature-space equivalence limits."""
    failures: list[str] = []
    successful = [
        row
        for row in rows
        if bool(row["lsoda_success"]) and bool(row["cn_success"])
    ]
    if len(successful) != len(rows):
        failures.append("one or more solver calls failed")

    for row in successful:
        harmonic = int(row["harmonic"])
        low_order = harmonic <= 3
        limits = {
            "current_nrmse": 0.01,
            "dc_nrmse": 0.01,
        }
        if bool(row.get("global_resolved", True)):
            limits.update(
                {
                    "global_amplitude_relative_error": 0.03 if low_order else 0.10,
                    "global_phase_error_rad": 0.05 if low_order else 0.15,
                }
            )
        if bool(row.get("lockin_resolved", True)):
            limits.update(
                {
                    "lockin_amplitude_nrmse": 0.03 if low_order else 0.10,
                    "lockin_phase_rmse_rad": 0.05 if low_order else 0.15,
                    "peak_shift_v": 0.005,
                }
            )
        for metric, limit in limits.items():
            value = float(row[metric])
            if not np.isfinite(value) or value > limit:
                failures.append(
                    f"sample={row['sample']} H{harmonic} "
                    f"{metric}={value:.6g}>{limit:.6g}"
                )

    return {
        "passed": not failures,
        "n_rows": len(rows),
        "n_failures": len(failures),
        "failures": failures,
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--samples", type=int, default=24)
    parser.add_argument("--seed", type=int, default=17)
    parser.add_argument("--points-per-cycle", type=int, default=128)
    parser.add_argument("--cycles", type=int, default=256)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=ROOT / "results" / "solver_equivalence",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    if not cn_is_available():
        raise RuntimeError("C++ CN library is unavailable")
    vectors = sample_parameter_vectors(
        DEFAULT_PARAM_SPECS,
        args.samples,
        args.seed,
    )
    rows: list[dict[str, object]] = []
    for index, vector in enumerate(vectors):
        print(f"sample {index + 1}/{len(vectors)}", flush=True)
        rows.extend(
            compare_sample(
                index,
                vector,
                args.points_per_cycle,
                args.cycles,
            )
        )

    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / "solver_equivalence.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=CSV_FIELDS,
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(rows)

    summary = assess_gate(rows)
    summary.update(
        {
            "samples": args.samples,
            "seed": args.seed,
            "points_per_cycle": args.points_per_cycle,
            "cycles": args.cycles,
            "resolvability_fraction": RESOLVABILITY_FRACTION,
            "csv": str(csv_path),
        }
    )
    summary_path = output_dir / "solver_equivalence_summary.json"
    summary_path.write_text(
        json.dumps(summary, indent=2),
        encoding="utf-8",
    )
    print(
        f"SOLVER_EQUIVALENCE passed={summary['passed']} "
        f"failures={summary['n_failures']} output={summary_path}"
    )
    return 0 if summary["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
