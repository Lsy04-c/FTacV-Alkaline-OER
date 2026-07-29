#!/usr/bin/env python3
"""Run the fixed M0/M1 reconstruction experiment without causal claims."""

from __future__ import annotations

import argparse
import csv
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "code" / "python" / "src"))
sys.path.insert(0, str(ROOT / "code" / "python" / "scripts"))

import compare_feature_objectives as feature_compare
from oer_aem.data_contract import normalize_trace, residual_exp_minus_sim
from oer_aem.experimental import analyze_ftacv_trace, build_experimental_target
from oer_aem.features import snr_weights, wrapped_phase_difference
from oer_aem.inversion import (
    DEFAULT_PARAM_SPECS,
    InversionConfig,
    TPEInverter,
    extract_features,
    forward_current,
)
from oer_aem.model_compare import information_criteria, reconstruction_gate

OUT = (
    ROOT
    / "results"
    / "architecture_validation"
    / "reconstruction_model_comparison.csv"
)
SEEDS = (7, 17, 27)
MODELS = ("M0", "M1")
THERMO_PARAMS = ("G_OH", "G_O", "scaling_OOH_OH")
BETA_SPEC = ("beta_recon", "linear", 0.0, 5.0)


def _model_setup(
    model: str,
    feature_mode: str,
    n_points: int,
    meta: Mapping[str, float],
    fit_harmonics: Sequence[int],
) -> tuple[InversionConfig, tuple]:
    fixed = feature_compare._fixed_parameters()
    fixed.update({"E_recon": 1.55, "w_recon": 0.05})
    if model == "M0":
        fixed["beta_recon"] = 0.0
    specs = tuple(
        spec for spec in DEFAULT_PARAM_SPECS if spec[0] not in fixed
    )
    if model == "M1":
        specs = specs + (BETA_SPEC,)
    config = InversionConfig(
        E_start=float(meta["E_start"]),
        E_end=float(meta["E_end"]),
        f=float(meta["f"]),
        dE=float(meta["dE"]),
        n_points=feature_compare.match_experimental_sampling(
            float(meta["duration"]), float(meta["f"]), points_per_cycle=32
        )[0],
        points_per_cycle=32,
        feature_grid_size=64,
        fixed_params=tuple(sorted(fixed.items())),
        param_specs=specs,
        fit_harmonics=tuple(int(h) for h in fit_harmonics),
        feature_mode=feature_mode,
    )
    return config, specs


def _diagnostic_metrics(
    result,
    target: Mapping[str, Any],
    config: InversionConfig,
    specs,
) -> tuple[float, float, float, float]:
    current = forward_current(result.best_x, config, specs)
    if current is None:
        return (float("nan"),) * 4
    simulated = extract_features(current, config)
    high = config.e_grid >= np.percentile(config.e_grid, 80.0)
    residual = residual_exp_minus_sim(target["dc"], simulated["dc"])
    high_bias = float(np.mean(residual[high]))
    high_rmse = float(np.sqrt(np.mean(residual[high] ** 2)))
    high_shape_rmse = float(
        np.sqrt(np.mean((residual[high] - np.mean(residual[high])) ** 2))
    )

    selected = np.arange(3)
    if config.feature_mode == "legacy":
        harmonic_loss = sum(
            float(
                np.sum(
                    (
                        (
                            simulated["harm"][idx]
                            - np.asarray(target["harm"][idx])
                        )
                        / config.sigma_harm
                    )
                    ** 2
                )
            )
            for idx in selected
        )
    else:
        experimental_complex = target["complex_harmonics"]
        simulated_complex = simulated["complex_harmonics"]
        weights = snr_weights(
            np.asarray(experimental_complex["snr"])[selected],
            floor=config.snr_floor,
        )
        target_amplitude = np.asarray(
            experimental_complex["amplitude"]
        )[selected]
        simulated_amplitude = np.asarray(
            simulated_complex["amplitude"]
        )[selected]
        amplitude_scale = max(
            float(np.max(np.abs(target_amplitude))),
            np.finfo(float).eps,
        )
        amplitude_residual = (
            (simulated_amplitude - target_amplitude)
            / amplitude_scale
            / config.sigma_harm
        )
        phase_residual = wrapped_phase_difference(
            np.asarray(simulated_complex["phase"])[selected],
            np.asarray(experimental_complex["phase"])[selected],
        )
        harmonic_loss = float(
            np.sum(weights * amplitude_residual**2)
            + config.phase_weight * np.sum(weights * phase_residual**2)
        )
    return high_bias, high_rmse, high_shape_rmse, harmonic_loss


def _beta_boundary_hit(result, model: str) -> bool:
    if model == "M0":
        return False
    beta = float(result.best_params["beta_recon"])
    width = BETA_SPEC[3] - BETA_SPEC[2]
    return min(beta - BETA_SPEC[2], BETA_SPEC[3] - beta) / width <= 0.01


def _run_row(
    *,
    filename: str,
    model: str,
    seed: int,
    trials: int,
    config: InversionConfig,
    specs,
    target: Mapping[str, Any],
    initial: Mapping[str, float],
) -> dict[str, Any]:
    started = time.perf_counter()
    result = TPEInverter(
        config=config,
        specs=specs,
        seed=seed,
        initial_params=initial,
    ).run(target, n_trials=trials)
    runtime_s = time.perf_counter() - started
    residual_loss = float(sum(result.loss_components.values()))
    n_observations = (
        config.feature_grid_size + 2 * len(config.fit_harmonics)
    )
    criteria = information_criteria(
        residual_loss,
        n_observations=n_observations,
        n_parameters=len(specs),
    )
    (
        high_potential_bias,
        high_potential_rmse,
        high_potential_shape_rmse,
        h1_h3_loss,
    ) = _diagnostic_metrics(
        result,
        target,
        config,
        specs,
    )
    return {
        "dataset": filename,
        "model": model,
        "feature_mode": config.feature_mode,
        "seed": seed,
        "trials": trials,
        "total_loss": result.best_value,
        "residual_loss": residual_loss,
        "aic": criteria["aic"],
        "bic": criteria["bic"],
        "high_potential_bias": high_potential_bias,
        "high_potential_rmse": high_potential_rmse,
        "high_potential_shape_rmse": high_potential_shape_rmse,
        "h1_h3_loss": h1_h3_loss,
        "G_OH": result.best_params["G_OH"],
        "G_O": result.best_params["G_O"],
        "scaling_OOH_OH": result.best_params["scaling_OOH_OH"],
        "beta_recon": result.best_params.get("beta_recon", 0.0),
        "beta_boundary_hit": _beta_boundary_hit(result, model),
        "forward_count": result.n_forward,
        "runtime_s": runtime_s,
        **feature_compare._sampling_evidence(config, target),
    }


def _coefficient_of_variation(values: Sequence[float]) -> float:
    array = np.asarray(values, dtype=float)
    return float(np.std(array) / max(abs(float(np.mean(array))), 1e-12))


def _run_row_job(job: Mapping[str, Any]) -> dict[str, Any]:
    return _run_row(**job)


def _apply_gate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    dataset_checks = []
    check_by_dataset = {}
    for dataset in feature_compare.DATASETS:
        paired = []
        for seed in SEEDS:
            m0 = next(
                row for row in rows
                if row["dataset"] == dataset
                and row["model"] == "M0"
                and row["seed"] == seed
            )
            m1 = next(
                row for row in rows
                if row["dataset"] == dataset
                and row["model"] == "M1"
                and row["seed"] == seed
            )
            paired.append(
                {
                    "structured_improved": (
                        float(m1["high_potential_rmse"])
                        < float(m0["high_potential_rmse"])
                        and float(m1["high_potential_shape_rmse"])
                        < float(m0["high_potential_shape_rmse"])
                    ),
                    "harmonics_not_worse": (
                        float(m1["h1_h3_loss"])
                        <= 1.05 * max(float(m0["h1_h3_loss"]), 1e-12)
                    ),
                    "complexity_supported": float(m1["bic"]) < float(m0["bic"]),
                    "boundary_hit": bool(m1["beta_boundary_hit"]),
                }
            )
        required_pairs = len(SEEDS) // 2 + 1
        check = {
            "dataset": dataset,
            "improved": sum(p["structured_improved"] for p in paired) >= required_pairs,
            "harmonics_not_worse": sum(p["harmonics_not_worse"] for p in paired) >= required_pairs,
            "boundary_hit": all(p["boundary_hit"] for p in paired),
            "complexity_supported": sum(p["complexity_supported"] for p in paired) >= required_pairs,
        }
        dataset_checks.append(check)
        check_by_dataset[dataset] = check

    cv_ratios = []
    for parameter in THERMO_PARAMS:
        cv_m0 = _coefficient_of_variation(
            [
                np.median([
                    row[parameter] for row in rows
                    if row["dataset"] == dataset and row["model"] == "M0"
                ])
                for dataset in feature_compare.DATASETS
            ]
        )
        cv_m1 = _coefficient_of_variation(
            [
                np.median([
                    row[parameter] for row in rows
                    if row["dataset"] == dataset and row["model"] == "M1"
                ])
                for dataset in feature_compare.DATASETS
            ]
        )
        cv_ratios.append(cv_m1 / max(cv_m0, 1e-12))
    thermo_cv_ratio = max(cv_ratios)
    gate = reconstruction_gate(dataset_checks, thermo_cv_ratio)

    for row in rows:
        check = check_by_dataset[row["dataset"]]
        row.update(
            {
                "high_structure_improved": check["improved"],
                "harmonics_not_worse": check["harmonics_not_worse"],
                "complexity_supported": check["complexity_supported"],
                "thermo_cv_ratio": gate["thermo_cv_ratio"],
                "datasets_passed": gate["datasets_passed"],
                "accepted": gate["accepted"],
            }
        )
    return gate


def run_comparison(
    trials: int,
    smoke: bool,
    feature_mode: str,
    workers: int = 1,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    n_points = 256 if smoke else 1024
    initial = feature_compare._base_parameters()
    jobs = []
    for filename in feature_compare.DATASETS:
        raw_rows = feature_compare._load_rows(feature_compare.RAW / filename)
        trace = normalize_trace(raw_rows)
        analysis = analyze_ftacv_trace(trace)
        harmonics = tuple(
            int(h) for h in analysis["harmonic_quality"]["fit_harmonics"]
        )
        configs = {
            model: _model_setup(
                model,
                feature_mode,
                n_points,
                analysis["meta"],
                harmonics,
            )
            for model in MODELS
        }
        target = build_experimental_target(
            trace,
            analysis,
            configs["M0"][0],
        )
        for model in MODELS:
            config, specs = configs[model]
            for seed in SEEDS:
                jobs.append(
                    dict(
                        filename=filename,
                        model=model,
                        seed=seed,
                        trials=trials,
                        config=config,
                        specs=specs,
                        target=target,
                        initial=initial,
                    )
                )
    if workers == 1:
        rows_out = [_run_row_job(job) for job in jobs]
    else:
        with ProcessPoolExecutor(max_workers=workers) as executor:
            rows_out = list(executor.map(_run_row_job, jobs))
    return rows_out, _apply_gate(rows_out)


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
    parser.add_argument(
        "--feature-mode",
        choices=("legacy", "complex_snr"),
        default="complex_snr",
    )
    parser.add_argument("--output", type=Path, default=OUT)
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    if args.trials < 1:
        raise ValueError("--trials must be positive")
    if args.workers < 1:
        raise ValueError("--workers must be positive")
    rows, gate = run_comparison(
        trials=args.trials,
        smoke=args.smoke,
        feature_mode=args.feature_mode,
        workers=args.workers,
    )
    expected = len(feature_compare.DATASETS) * len(MODELS) * len(SEEDS)
    if len(rows) != expected:
        raise RuntimeError(f"expected {expected} rows, got {len(rows)}")
    output = args.output if args.output.is_absolute() else ROOT / args.output
    _write_csv(rows, output)
    decision = "accepted" if gate["accepted"] else "rejected"
    print(
        "RECONSTRUCTION_MODEL_COMPARISON_OK "
        f"rows={len(rows)} decision={decision} "
        f"datasets_passed={gate['datasets_passed']} "
        f"thermo_cv_ratio={gate['thermo_cv_ratio']:.6g} "
        f"output={output}"
    )


if __name__ == "__main__":
    main()
