#!/usr/bin/env python3
"""Stage 3: high-current penalty diagnostic.

This script does not add a transport equation. It asks a narrower question:
if the objective pays extra attention to the high-current/high-potential
region, can the current AEM model reduce the high-region residual?

If the answer is no, the remaining bias is more likely a missing physical term
than an objective-weighting issue.
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Sequence

import numpy as np

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT))
sys.path.insert(0, str(PROJECT / "python"))
sys.path.insert(0, str(PROJECT / "web" / "backend"))

from main import _analyze_ftacv_data
from oer_aem.defaults import initialize_oer_parameters
from oer_aem.inversion import (
    DEFAULT_PARAM_SPECS,
    InversionConfig,
    assess_fit_quality,
    decode_vector,
    denormalize_vector,
    encode_params,
    extract_features,
    forward_current,
    normalize_vector,
)

RAW_DIR = PROJECT / "data" / "raw"
OUT_DIR = PROJECT / "results" / "model_gap"
OUT_DIR.mkdir(parents=True, exist_ok=True)


def _load_numeric(filename: str, min_cols: int = 3) -> np.ndarray:
    raw = (RAW_DIR / filename).read_text()
    numeric_lines = []
    for line in raw.strip().splitlines():
        parts = line.replace(",", " ").split()
        try:
            vals = [float(x) for x in parts[:min_cols]]
            if len(vals) >= min_cols:
                numeric_lines.append(vals)
            elif len(vals) >= 2:
                numeric_lines.append(vals + [0.0])
        except ValueError:
            continue
    return np.asarray(numeric_lines, dtype=float)


def _free_specs_excluding(fixed: Mapping[str, float]):
    fixed_names = set(fixed)
    return tuple(spec for spec in DEFAULT_PARAM_SPECS if spec[0] not in fixed_names)


def _build_target(filename: str, cfg: InversionConfig) -> Dict[str, Any]:
    rows = _load_numeric(filename)
    analysis = _analyze_ftacv_data(rows)
    tdc_raw = np.asarray(analysis["tdc"], dtype=float)
    dc_raw = np.asarray(analysis["dc"], dtype=float)
    harm_raw = [np.asarray(h, dtype=float) for h in analysis["harmonics"]]

    order = np.argsort(tdc_raw)
    x_sorted = tdc_raw[order]
    _, keep = np.unique(x_sorted, return_index=True)
    x = x_sorted[keep]

    tafel_val = analysis.get("calib", {}).get("tafel", {}).get("b", 60.0)
    if not isinstance(tafel_val, (int, float)) or not np.isfinite(tafel_val) or tafel_val <= 0:
        tafel_val = 60.0

    return {
        "dc": np.interp(cfg.e_grid, x, dc_raw[order][keep]),
        "harm": [np.interp(cfg.e_grid, x, h[order][keep]) for h in harm_raw],
        "tafel": float(tafel_val),
        "e_grid": cfg.e_grid,
        "fit_harmonics": analysis["harmonic_quality"]["fit_harmonics"],
        "meta": analysis["meta"],
    }


def _loss(
    x: Sequence[float],
    target: Mapping[str, Any],
    cfg: InversionConfig,
    specs,
    high_weight: float,
) -> float:
    current = forward_current(x, cfg, specs)
    if current is None:
        return float(cfg.ode_penalty)
    features = extract_features(current, cfg)

    total = float(np.sum(((features["dc"] - target["dc"]) / cfg.sigma_dc) ** 2))
    for harmonic in cfg.fit_harmonics:
        idx = int(harmonic) - 1
        total += float(np.sum(((features["harm"][idx] - target["harm"][idx]) / cfg.sigma_harm) ** 2))

    if features["tafel"] is None:
        total += cfg.tafel_fail_resid**2
    else:
        total += float(((features["tafel"] - target["tafel"]) / cfg.sigma_tafel) ** 2)

    hi = cfg.e_grid >= np.percentile(cfg.e_grid, 70)
    if high_weight > 0:
        high_dc = float(np.sum(((features["dc"][hi] - target["dc"][hi]) / cfg.sigma_dc) ** 2))
        total += float(high_weight) * high_dc

    return total / float(2 + len(cfg.fit_harmonics) + max(high_weight, 0.0))


def _fit_one(
    filename: str,
    high_weight: float,
    n_trials: int,
    ru: float,
    seed: int = 42,
) -> Dict[str, Any]:
    rows = _load_numeric(filename)
    analysis = _analyze_ftacv_data(rows)
    fit_h = analysis["harmonic_quality"]["fit_harmonics"]

    base = initialize_oer_parameters()
    fixed = {
        "Cdl": float(base["Cdl"]),
        "Ru": float(ru),
        "A": float(base["A"]),
        "gamma": 3e-9,
    }
    specs = _free_specs_excluding(fixed)
    cfg = InversionConfig(
        E_start=analysis["meta"]["E_start"],
        E_end=analysis["meta"]["E_end"],
        f=analysis["meta"]["f"],
        dE=analysis["meta"]["dE"],
        n_points=2048,
        points_per_cycle=128,
        feature_grid_size=200,
        fixed_params=tuple(fixed.items()),
        fit_harmonics=tuple(fit_h),
    )
    target = _build_target(filename, cfg)

    import optuna

    optuna.logging.set_verbosity(optuna.logging.WARNING)
    sampler = optuna.samplers.TPESampler(seed=seed, n_startup_trials=min(8, n_trials))
    study = optuna.create_study(direction="minimize", sampler=sampler)

    base.update(fixed)
    base["E0_pre"] = 1.50
    base["k0_pre"] = 300.0
    initial_x = encode_params(base, specs)
    initial_z = normalize_vector(initial_x, specs)
    study.enqueue_trial({f"z_{name}": float(z) for (name, _, _, _), z in zip(specs, initial_z)})

    best_x = None
    best_value = np.inf

    def objective(trial):
        nonlocal best_x, best_value
        if trial.number == 0:
            x = initial_x
        else:
            z = [trial.suggest_float(f"z_{name}", 0.0, 1.0) for name, _, _, _ in specs]
            x = denormalize_vector(z, specs)
        value = _loss(x, target, cfg, specs, high_weight)
        if value < best_value:
            best_value = float(value)
            best_x = np.asarray(x, dtype=float).copy()
        return float(value)

    study.optimize(objective, n_trials=n_trials)
    if best_x is None:
        best_z = np.asarray([study.best_params[f"z_{name}"] for name, _, _, _ in specs], dtype=float)
        best_x = denormalize_vector(best_z, specs)
        best_value = float(study.best_value)

    current = forward_current(best_x, cfg, specs)
    if current is None:
        raise RuntimeError("best forward simulation failed")
    features = extract_features(current, cfg)
    hi = cfg.e_grid >= np.percentile(cfg.e_grid, 70)
    lo = cfg.e_grid < np.percentile(cfg.e_grid, 20)

    # Sign convention: positive bias means experiment > simulation.
    resid = np.asarray(target["dc"]) - np.asarray(features["dc"])
    bias_lo = float(np.mean(resid[lo]))
    bias_hi = float(np.mean(resid[hi]))
    rmse_hi = float(np.sqrt(np.mean(resid[hi] ** 2)))

    best_params = decode_vector(best_x, specs)
    best_params.update(fixed)
    quality = assess_fit_quality(best_value, cfg.feature_grid_size, cfg.fit_harmonics)
    return {
        "dataset": filename,
        "high_weight": float(high_weight),
        "Ru": float(ru),
        "best": float(best_value),
        "level": quality["level"],
        "bias_lo": bias_lo,
        "bias_hi": bias_hi,
        "abs_bias_hi": abs(bias_hi),
        "rmse_hi": rmse_hi,
        "G_OH": float(best_params.get("G_OH", np.nan)),
        "G_O": float(best_params.get("G_O", np.nan)),
        "scaling_OOH_OH": float(best_params.get("scaling_OOH_OH", np.nan)),
        "gamma": float(best_params.get("gamma", np.nan)),
    }


def _ftacv_files() -> list[str]:
    quality_csv = PROJECT / "results" / "data_quality" / "data_quality_summary.csv"
    rows = list(csv.DictReader(open(quality_csv)))
    return [r["filename"] for r in rows if r.get("type") == "FTacV" and r.get("success") == "True"]


def _write_report(results: list[Dict[str, Any]], weights: Iterable[float], n_trials: int, ru: float) -> None:
    csv_path = OUT_DIR / "high_current_penalty.csv"
    with csv_path.open("w", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=list(results[0].keys()),
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(results)

    lines = [
        "# High-Current Penalty Diagnostic",
        "",
        f"Ru fixed at {ru:g} ohm. gamma fixed at 3e-9 mol/cm2 and removed from optimizer specs.",
        f"Trials per dataset/weight: {n_trials}",
        "",
        "Sign convention: `bias_hi = experiment - simulation`. Positive values mean the model underpredicts the high-current region.",
        "",
        "| Dataset | high_weight | best | level | bias_lo | bias_hi | rmse_hi | G_OH | G_O | scaling |",
        "|---------|-------------|------|-------|---------|---------|---------|------|-----|---------|",
    ]
    for r in results:
        lines.append(
            f"| {r['dataset']} | {r['high_weight']:.1f} | {r['best']:.1f} | {r['level']} | "
            f"{r['bias_lo']:+.3f} | {r['bias_hi']:+.3f} | {r['rmse_hi']:.3f} | "
            f"{r['G_OH']:.2f} | {r['G_O']:.2f} | {r['scaling_OOH_OH']:.2f} |"
        )

    lines.extend(["", "## Interpretation", ""])
    for dataset in sorted({r["dataset"] for r in results}):
        subset = [r for r in results if r["dataset"] == dataset]
        baseline = min((r for r in subset if r["high_weight"] == 0.0), key=lambda r: r["abs_bias_hi"])
        best = min(subset, key=lambda r: r["abs_bias_hi"])
        delta = baseline["abs_bias_hi"] - best["abs_bias_hi"]
        if delta > 0.10:
            conclusion = "high-current weighting helps; objective weighting is part of the problem"
        else:
            conclusion = "high-current weighting does not materially reduce bias; likely missing physics"
        lines.append(
            f"- `{dataset}`: best |bias_hi| {best['abs_bias_hi']:.3f} at weight {best['high_weight']:.1f}; "
            f"improvement vs weight 0 = {delta:.3f}. {conclusion}."
        )

    lines.extend(
        [
            "",
            "## Next Decision",
            "",
            "- If high-current weighting reduces `|bias_hi|` without pushing `G_OH/G_O/scaling` to bounds, revise the objective function first.",
            "- If high-current weighting cannot reduce `|bias_hi|`, do not keep tuning weights. Move to a missing-physics test.",
            "- Because positive `bias_hi` means experiment > simulation, a simple OH- depletion/current-limiting term would likely worsen the high-current DC residual. Check residual sign before adding OH- transport.",
        ]
    )

    md_path = OUT_DIR / "high_current_penalty.md"
    md_path.write_text("\n".join(lines) + "\n")
    print(f"CSV → {csv_path}")
    print(f"Report → {md_path}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trials", type=int, default=20)
    parser.add_argument("--ru", type=float, default=30.0)
    parser.add_argument("--weights", type=float, nargs="*", default=[0.0, 2.0, 5.0, 10.0])
    parser.add_argument("--dataset", action="append", help="Limit to one or more dataset filenames.")
    args = parser.parse_args()

    datasets = args.dataset if args.dataset else _ftacv_files()
    results: list[Dict[str, Any]] = []
    for dataset in datasets:
        for weight in args.weights:
            print(f"{dataset} high_weight={weight:g} ...", end=" ", flush=True)
            row = _fit_one(dataset, weight, args.trials, args.ru)
            results.append(row)
            print(f"bias_hi={row['bias_hi']:+.3f} best={row['best']:.1f}")

    if results:
        _write_report(results, args.weights, args.trials, args.ru)


if __name__ == "__main__":
    main()
