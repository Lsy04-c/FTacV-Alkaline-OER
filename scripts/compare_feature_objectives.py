#!/usr/bin/env python3
"""Compare legacy and complex-SNR objectives under identical TPE budgets."""

from __future__ import annotations

import argparse
import contextlib
import csv
import io
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))
sys.path.insert(0, str(ROOT / "web" / "backend"))

from main import _analyze_ftacv_data
from oer_aem.data_contract import normalize_trace
from oer_aem.defaults import initialize_oer_parameters
from oer_aem.features import complex_harmonic_metrics
from oer_aem.inversion import (
    DEFAULT_PARAM_SPECS,
    InversionConfig,
    TPEInverter,
    encode_params,
    extract_features,
    forward_current,
    make_synthetic_target,
    normalize_vector,
    match_experimental_sampling,
)

OUT = ROOT / "results" / "architecture_validation" / "feature_objective_comparison.csv"
RAW = ROOT / "data" / "raw"
SEEDS = (7, 17, 27)
MODES = ("legacy", "complex_snr", "lockin_only")
DATASETS = (
    "ftacv2-ref-5hz.txt",
    "ftacv3-ref-5Hz.txt",
    "ftacv4-ref-1hz.txt",
    "ftacv8-ref-5Hz.txt",
)
TRUTH = {
    "k0_1": 100.0,
    "k0_2": 50.0,
    "k0_3": 20.0,
    "k0_4": 80.0,
    "G_OH": 1.23,
    "G_O": 2.80,
    "scaling_OOH_OH": 3.2,
    "gamma": 3e-9,
}


def _load_rows(path: Path) -> np.ndarray:
    numeric = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            values = [float(value) for value in line.replace(",", " ").split()[:3]]
        except ValueError:
            continue
        if len(values) == 3:
            numeric.append(values)
    return np.asarray(numeric, dtype=float)


def _base_parameters() -> dict[str, float]:
    with contextlib.redirect_stdout(io.StringIO()):
        params = initialize_oer_parameters()
    params["gamma"] = TRUTH["gamma"]
    return params


def _fixed_parameters() -> dict[str, float]:
    params = _base_parameters()
    return {
        "A": float(params["A"]),
        "Cdl": float(params["Cdl"]),
        "Ru": float(params["Ru"]),
        "gamma": float(TRUTH["gamma"]),
        "E0_pre": float(params["E0_pre"]),
        "k0_pre": float(params["k0_pre"]),
    }


def _free_specs(fixed: Mapping[str, float]):
    return tuple(spec for spec in DEFAULT_PARAM_SPECS if spec[0] not in fixed)


def _config(
    mode: str,
    n_points: int,
    *,
    meta: Mapping[str, float] | None = None,
    fit_harmonics: Sequence[int] = (1, 2, 3),
) -> InversionConfig:
    values = meta or {
        "E_start": 0.924,
        "E_end": 1.923,
        "f": 1.0,
        "dE": 0.16,
    }
    fixed = _fixed_parameters()
    specs = _free_specs(fixed)
    points_per_cycle = 32
    if meta is not None:
        n_points, points_per_cycle = match_experimental_sampling(
            float(values["duration"]),
            float(values["f"]),
            points_per_cycle=32,
        )
    return InversionConfig(
        E_start=float(values["E_start"]),
        E_end=float(values["E_end"]),
        f=float(values["f"]),
        dE=float(values["dE"]),
        n_points=n_points,
        points_per_cycle=points_per_cycle,
        feature_grid_size=64,
        fixed_params=tuple(sorted(fixed.items())),
        param_specs=specs,
        fit_harmonics=tuple(int(h) for h in fit_harmonics),
        feature_mode=mode,
    )


def _experimental_target(
    rows: np.ndarray,
    analysis: Mapping[str, Any],
    config: InversionConfig,
) -> dict[str, Any]:
    tdc = np.asarray(analysis["tdc"], dtype=float)
    order = np.argsort(tdc)
    unique, keep = np.unique(tdc[order], return_index=True)
    target = {
        "dc": np.interp(
            config.e_grid,
            unique,
            np.asarray(analysis["dc"], dtype=float)[order][keep],
        ),
        "harm": [
            np.interp(
                config.e_grid,
                unique,
                np.asarray(channel, dtype=float)[order][keep],
            )
            for channel in analysis["harmonics"]
        ],
        "tafel": None,
        "e_grid": config.e_grid,
        "_experimental_duration": float(analysis["meta"]["duration"]),
        "_experimental_scan_rate": float(analysis["meta"]["v"]),
    }
    if config.feature_mode in ("complex_snr", "lockin_only", "combined"):
        trace = normalize_trace(rows)
        fs = 1.0 / float(np.mean(np.diff(trace.time)))
        target["complex_harmonics"] = complex_harmonic_metrics(
            trace.current[len(trace.current) // 4 :],
            fs=fs,
            f0=float(analysis["meta"]["f"]),
            n_harmonics=max(config.fit_harmonics),
        )
    if config.feature_mode in ("lockin_only", "combined"):
        from oer_aem.inversion import _interpolate_lockin_to_grid
        from oer_aem.signal import estimate_reference_phase, lockin_harmonics
        trace = normalize_trace(rows)
        i0 = len(trace.current) // 4
        t_trim = trace.time[i0:]
        i_trim = trace.current[i0:]
        lockin = lockin_harmonics(
            i_trim, t_trim,
            f0=float(analysis["meta"]["f"]),
            harmonics=tuple(range(1, max(config.fit_harmonics) + 1)),
            potential_resolution=0.05,
            scan_rate=float(analysis["meta"]["v"]),
            reference_phase=estimate_reference_phase(
                trace.potential,
                trace.time,
                float(analysis["meta"]["f"]),
            )[i0:],
        )
        target["lockin"] = _interpolate_lockin_to_grid(
            lockin,
            tdc[i0:],
            config.e_grid,
        )
    return target


def _sampling_evidence(
    config: InversionConfig,
    target: Mapping[str, Any],
) -> dict[str, Any]:
    experimental_duration = float(target.get("_experimental_duration", config.total_time))
    experimental_scan_rate = float(
        target.get("_experimental_scan_rate", config.scan_rate)
    )
    relative_error = abs(config.scan_rate - experimental_scan_rate) / max(
        abs(experimental_scan_rate), 1e-30
    )
    if relative_error > 5e-4:
        raise RuntimeError(
            "simulation scan rate does not match experiment: "
            f"relative_error={relative_error:.6g}"
        )
    return {
        "n_points": config.n_points,
        "points_per_cycle": config.points_per_cycle,
        "fit_harmonics": ";".join(map(str, config.fit_harmonics)),
        "fixed_params": ";".join(
            f"{name}={value:g}" for name, value in config.fixed_params
        ),
        "experimental_duration_s": experimental_duration,
        "simulated_duration_s": config.total_time,
        "experimental_scan_rate_v_s": experimental_scan_rate,
        "simulated_scan_rate_v_s": config.scan_rate,
        "scan_rate_relative_error": relative_error,
    }


def _boundary_hits(best_x: np.ndarray, specs) -> list[str]:
    hits = []
    for value, (name, _, low, high) in zip(best_x, specs):
        width = max(float(high - low), np.finfo(float).eps)
        if min(float(value - low), float(high - value)) / width <= 0.01:
            hits.append(name)
    return hits


def _recovery_error(best_x: np.ndarray, specs) -> float:
    truth_x = encode_params(TRUTH, specs)
    return float(
        np.sqrt(
            np.mean(
                (
                    normalize_vector(best_x, specs)
                    - normalize_vector(truth_x, specs)
                )
                ** 2
            )
        )
    )


def _result_row(
    *,
    dataset: str,
    target_type: str,
    mode: str,
    seed: int,
    trials: int,
    result,
    runtime_s: float,
    specs,
    config: InversionConfig,
    target: Mapping[str, Any],
) -> dict[str, Any]:
    components = result.loss_components
    hits = _boundary_hits(result.best_x, specs)
    current = forward_current(result.best_x, config, specs)
    if current is None:
        common_dc_rmse = float("nan")
        common_h1_h3_rmse = float("nan")
        evaluation_forward_count = 0
    else:
        evaluated = extract_features(current, config)
        common_dc_rmse = float(
            np.sqrt(
                np.mean(
                    (
                        np.asarray(evaluated["dc"])
                        - np.asarray(target["dc"])
                    )
                    ** 2
                )
            )
        )
        harmonic_residuals = np.concatenate(
            [
                np.asarray(evaluated["harm"][idx])
                - np.asarray(target["harm"][idx])
                for idx in range(3)
            ]
        )
        common_h1_h3_rmse = float(
            np.sqrt(np.mean(harmonic_residuals**2))
        )
        evaluation_forward_count = 1
    best = result.best_params
    return {
        "dataset": dataset,
        "target_type": target_type,
        "feature_mode": mode,
        "seed": seed,
        "trials": trials,
        "recovery_error": (
            _recovery_error(result.best_x, specs)
            if target_type == "synthetic"
            else float("nan")
        ),
        "total_loss": result.best_value,
        "loss_dc": components.get("dc", float("nan")),
        "loss_common_harmonics": components.get(
            "common_harmonics", float("nan")
        ),
        "loss_dataset_specific_harmonics": components.get(
            "dataset_specific_harmonics", float("nan")
        ),
        "loss_phase": components.get("phase", float("nan")),
        "loss_physical": components.get("physical", float("nan")),
        "common_dc_rmse": common_dc_rmse,
        "common_h1_h3_rmse": common_h1_h3_rmse,
        "G_OH": best["G_OH"],
        "G_O": best["G_O"],
        "scaling_OOH_OH": best["scaling_OOH_OH"],
        "k0_1": best["k0_1"],
        "k0_2": best["k0_2"],
        "k0_3": best["k0_3"],
        "k0_4": best["k0_4"],
        "boundary_hits": len(hits),
        "boundary_parameters": ";".join(hits),
        "forward_count": result.n_forward,
        "evaluation_forward_count": evaluation_forward_count,
        "runtime_s": runtime_s,
        **_sampling_evidence(config, target),
    }


def _run_job(job: Mapping[str, Any]) -> dict[str, Any]:
    started = time.perf_counter()
    result = TPEInverter(
        config=job["config"],
        specs=job["specs"],
        seed=job["seed"],
        initial_params=job["initial"],
    ).run(job["target"], n_trials=job["trials"])
    return _result_row(
        dataset=job["dataset"],
        target_type=job["target_type"],
        mode=job["mode"],
        seed=job["seed"],
        trials=job["trials"],
        result=result,
        runtime_s=time.perf_counter() - started,
        specs=job["specs"],
        config=job["config"],
        target=job["target"],
    )


def run_comparison(
    trials: int,
    smoke: bool,
    workers: int = 1,
) -> list[dict[str, Any]]:
    n_points = 256 if smoke else 1024
    initial = _base_parameters()
    jobs = []

    for mode in MODES:
        config = _config(mode, n_points)
        specs = config.param_specs
        target = make_synthetic_target(
            TRUTH,
            config=config,
            noise_fraction=0.002,
            seed=101,
        )
        for seed in SEEDS:
            jobs.append(
                dict(
                    dataset="synthetic",
                    target_type="synthetic",
                    mode=mode,
                    seed=seed,
                    trials=trials,
                    initial=initial,
                    specs=specs,
                    config=config,
                    target=target,
                )
            )

    for filename in DATASETS:
        rows = _load_rows(RAW / filename)
        analysis = _analyze_ftacv_data(rows)
        harmonics = tuple(
            int(h) for h in analysis["harmonic_quality"]["fit_harmonics"]
        )
        for mode in MODES:
            config = _config(
                mode,
                n_points,
                meta=analysis["meta"],
                fit_harmonics=harmonics,
            )
            specs = config.param_specs
            target = _experimental_target(rows, analysis, config)
            for seed in SEEDS:
                jobs.append(
                    dict(
                        dataset=filename,
                        target_type="experimental",
                        mode=mode,
                        seed=seed,
                        trials=trials,
                        initial=initial,
                        specs=specs,
                        config=config,
                        target=target,
                    )
                )
    if workers == 1:
        return [_run_job(job) for job in jobs]
    with ProcessPoolExecutor(max_workers=workers) as executor:
        return list(executor.map(_run_job, jobs))


def _write_csv(rows: list[dict[str, Any]], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=list(rows[0]),
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(rows)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--smoke", action="store_true")
    parser.add_argument("--trials", type=int, default=50)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--output", type=Path, default=OUT)
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    if args.trials < 1:
        raise ValueError("--trials must be positive")
    if args.workers < 1:
        raise ValueError("--workers must be positive")
    rows = run_comparison(args.trials, args.smoke, args.workers)
    expected = len(MODES) * len(SEEDS) * (1 + len(DATASETS))
    if len(rows) != expected:
        raise RuntimeError(f"expected {expected} rows, got {len(rows)}")
    schedules = {
        (row["dataset"], row["feature_mode"], row["seed"], row["trials"])
        for row in rows
    }
    if len(schedules) != expected:
        raise RuntimeError("feature modes did not receive identical schedules")
    output = args.output if args.output.is_absolute() else ROOT / args.output
    _write_csv(rows, output)
    print(f"FEATURE_OBJECTIVE_COMPARISON_OK rows={len(rows)} output={output}")


if __name__ == "__main__":
    main()
