#!/usr/bin/env python3
"""Phase 2.3 — Grid convergence experiment.

Compares feature_grid_size = 64, 128, 256, None (full) on a synthetic target
and optionally on real datasets.  Reports parameter shifts and loss-component
stability.
"""

from __future__ import annotations

import argparse
import csv
import sys
import time
from pathlib import Path
from typing import Optional, Sequence

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "code" / "python" / "src"))
sys.path.insert(0, str(ROOT / "code" / "web" / "backend"))

from oer_aem.defaults import initialize_oer_parameters
from oer_aem.inversion import (
    InversionConfig,
    TPEInverter,
    encode_params,
    make_synthetic_target,
    DEFAULT_PARAM_SPECS,
)

GRID_SIZES = (64, 128, 256, None)  # None = full grid
SEEDS = (7, 17, 27)
TRIALS_PER_STUDY = 30


def synthetic_row(grid: Optional[int], seed: int) -> dict:
    truth = initialize_oer_parameters()
    truth.update({"gamma": 3e-9, "E0_pre": 1.50, "k0_pre": 300.0})
    config = InversionConfig(
        E_start=0.924, E_end=1.923, f=5.0, dE=0.16,
        n_points=8000, points_per_cycle=32,
        feature_grid_size=grid, seed=seed,
    )
    target = make_synthetic_target(truth, config=config, noise_fraction=0.0)
    perturbed = dict(truth)
    perturbed["k0_1"] = 10.0  # far from truth
    t0 = time.perf_counter()
    result = TPEInverter(
        config=config, specs=DEFAULT_PARAM_SPECS, seed=seed, initial_params=perturbed,
    ).run(target, n_trials=TRIALS_PER_STUDY)
    runtime = time.perf_counter() - t0
    best = result.best_params
    return {
        "target_type": "synthetic",
        "feature_grid_size": "full" if grid is None else str(grid),
        "resolved_grid_size": config.resolved_feature_grid_size,
        "seed": seed,
        "trials": TRIALS_PER_STUDY,
        "best_value": result.best_value,
        "G_OH": best["G_OH"], "G_O": best["G_O"],
        "scaling_OOH_OH": best["scaling_OOH_OH"],
        "k0_1": best["k0_1"], "k0_2": best["k0_2"],
        "k0_3": best["k0_3"], "k0_4": best["k0_4"],
        "loss_dc": result.loss_components.get("dc", float("nan")),
        "loss_common_harmonics": result.loss_components.get("common_harmonics", float("nan")),
        "runtime_s": runtime,
        "n_forward": result.n_forward,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Phase 2.3 grid convergence")
    parser.add_argument("--output", default=str(ROOT / "results" / "architecture_validation" / "grid_convergence.csv"))
    parser.add_argument("--smoke", action="store_true", help="Single-seed smoke test")
    args = parser.parse_args()

    seeds = (7,) if args.smoke else SEEDS
    rows = []
    for grid in GRID_SIZES:
        label = "full" if grid is None else str(grid)
        for seed in seeds:
            print(f"Grid={label} seed={seed} ...", end=" ", flush=True)
            row = synthetic_row(grid, seed)
            rows.append(row)
            print(f"value={row['best_value']:.4f} G_OH={row['G_OH']:.3f} k0_1={row['k0_1']:.1f}")

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    print(f"Wrote {len(rows)} rows to {out}")

    # Quick convergence check
    groups: dict[str, list[dict]] = {}
    for r in rows:
        groups.setdefault(r["feature_grid_size"], []).append(r)
    print("\nGrid convergence summary:")
    ref = groups["full"]
    for label in ["64", "128", "256"]:
        test = groups[label]
        dG_OH = np.mean([abs(t["G_OH"] - r["G_OH"]) / max(abs(r["G_OH"]), 1e-6)
                         for t, r in zip(test, ref)])
        dk01 = np.mean([abs(np.log10(max(t["k0_1"], 1e-6)) - np.log10(max(r["k0_1"], 1e-6)))
                        for t, r in zip(test, ref)])
        print(f"  {label} vs full: dG_OH={dG_OH:.4f}  dlog10(k0_1)={dk01:.3f}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
