#!/usr/bin/env python3
"""低维 Bonke 分子催化模型的 CMA-ES 优化 + 自适应协方差 MCMC 后验推断。

用法：
    .venv/bin/python scripts/fit_molecular_catalysis.py --mcmc-iterations 3000

设计边界（见 docs/superpowers/plans/2026-08-22-low-dim-bonke-model.md）：
本阶段是探索性拟合，输出后验与相关矩阵用于设计下一轮实验，**不**建立
phase gate、预注册阈值或 manifest 哈希链——那套验收机制等模型定型、
补充实验数据回来之后再上。
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import sys
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT / "python"))

from oer_aem.low_dim_fit import (  # noqa: E402
    FIT_HARMONICS,
    LowDimObjective,
    PARAM_NAMES,
    decode,
    default_bounds,
    harmonic_envelopes,
    implied_sigma,
    load_truncated,
)
from oer_aem.mcmc import run_adaptive_mcmc  # noqa: E402
from oer_aem.molecular_catalysis import simulate  # noqa: E402

# Cdl 来自 results/data_quality/data_quality_summary.md 的 CdlA 列，
# 由同一批 FTacV 数据估出，因此来源标签是 derived_from_data 而非 measured。
DATASETS = (
    ("FT2", "ftacv2-ref-5hz.txt", 34.5e-6),
    ("FT3", "ftacv3-ref-5Hz.txt", 16.9e-6),
    ("FT4", "ftacv4-ref-1hz.txt", 28.9e-6),
    ("FT8", "ftacv8-ref-5Hz.txt", 30.8e-6),
)

PINNED_PROVENANCE = {
    "Ru": "engineering",        # 未测量；EIS 待补。见 docs/项目纠错.md
    "A": "engineering",         # 未测量；与 gamma 完全简并
    "Cdl": "derived_from_data",
    "alpha": "literature",      # BV 对称因子惯例值 0.5
}

E_FIT_LO = 1.20
E_FIT_HI = 1.65

_WORKER = {}


def _git_commit() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=PROJECT, text=True
        ).strip()
    except Exception:  # noqa: BLE001
        return "unknown"


def _build_objective(name: str, filename: str, cdl: float, ru: float) -> LowDimObjective:
    record = load_truncated(PROJECT / "data" / "raw" / filename, name, E_FIT_LO, E_FIT_HI)
    pinned = {"Ru": ru, "Cdl": cdl, "A": 1.0, "alpha": 0.5}
    return LowDimObjective(record, pinned)


def _init_worker(name, filename, cdl, ru):
    _WORKER["objective"] = _build_objective(name, filename, cdl, ru)


def _worker_log_posterior(unit):
    return _WORKER["objective"].log_posterior_unit(np.asarray(unit))


def _chain_task(args):
    """在子进程中运行单条链。"""
    start_unit, iterations, thin, seed = args
    result = run_adaptive_mcmc(
        _worker_log_posterior,
        x0_unit=np.asarray(start_unit),
        lower=default_bounds()[0],
        upper=default_bounds()[1],
        names=PARAM_NAMES,
        n_iterations=iterations,
        thin=thin,
        n_chains=1,
        seed=seed,
    )
    chain = result.chains[0]
    return chain.samples, chain.log_posterior, chain.acceptance_rate, seed


def run_cma(objective: LowDimObjective, evaluations: int, seed: int):
    """CMA-ES 在 [0,1] 空间最小化 HarmPer。"""
    import cma

    options = {
        "bounds": [0.0, 1.0],
        "maxfevals": evaluations,
        "seed": seed,
        "verbose": -9,
        "popsize": 10,
    }
    es = cma.CMAEvolutionStrategy(np.full(len(PARAM_NAMES), 0.5), 0.25, options)
    while not es.stop():
        candidates = es.ask()
        es.tell(candidates, [objective.loss(np.asarray(c)) for c in candidates])
    return np.asarray(es.result.xbest), float(es.result.fbest)


def fit_dataset(name, filename, cdl, ru, args):
    objective = _build_objective(name, filename, cdl, ru)
    record = objective.record

    best_unit, best_loss = run_cma(objective, args.cma_evals, args.seed)
    best_params = decode(best_unit, *default_bounds())

    envelopes = objective._simulate_envelopes(best_unit)
    sigma = implied_sigma(envelopes, objective.target) if envelopes is not None else None

    summary = None
    correlation = None
    samples = None
    acceptance = []
    if args.mcmc_iterations > 0:
        starts = [(best_unit, args.mcmc_iterations, args.thin, args.seed + 1000 * i)
                  for i in range(args.chains)]
        with ProcessPoolExecutor(
            max_workers=min(args.chains, args.workers),
            initializer=_init_worker,
            initargs=(name, filename, cdl, ru),
        ) as pool:
            chain_results = list(pool.map(_chain_task, starts))

        from oer_aem.mcmc import ChainResult, MCMCResult

        chains = [ChainResult(s, lp, ar, sd) for s, lp, ar, sd in chain_results]
        acceptance = [c.acceptance_rate for c in chains]
        result = MCMCResult(chains=chains, names=PARAM_NAMES,
                            lower=default_bounds()[0], upper=default_bounds()[1])
        summary = result.summary()
        correlation = result.correlation()
        samples = result.pooled

    return {
        "dataset": name,
        "filename": filename,
        "f0": record.f0,
        "dE": record.dE,
        "v": record.v,
        "E_fit_lo": float(record.E_start + record.v * record.t[0]),
        "E_fit_hi": record.E_end,
        "n_points": int(record.t.size),
        "Ru": ru,
        "Cdl": cdl,
        "best_unit": best_unit.tolist(),
        "best_params": best_params,
        "best_harmper": best_loss,
        "implied_sigma": None if sigma is None else sigma.tolist(),
        "target_peak": objective.target.max(axis=1).tolist(),
        "summary": summary,
        "correlation": None if correlation is None else correlation.tolist(),
        "acceptance": acceptance,
        "samples": samples,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--outdir", default="results/low_dim_bonke")
    parser.add_argument("--cma-evals", type=int, default=400)
    parser.add_argument("--mcmc-iterations", type=int, default=3000)
    parser.add_argument("--chains", type=int, default=4)
    parser.add_argument("--thin", type=int, default=3)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--ru-sensitivity", type=float, nargs="*", default=[5.0, 20.0],
                        help="额外的 Ru 取值，只跑 CMA-ES，用于量化钉住 Ru 的风险")
    parser.add_argument("--datasets", nargs="*", default=[d[0] for d in DATASETS])
    args = parser.parse_args()

    outdir = PROJECT / args.outdir
    outdir.mkdir(parents=True, exist_ok=True)

    selected = [d for d in DATASETS if d[0] in args.datasets]
    results = []
    for name, filename, cdl in selected:
        print(f"[{datetime.now():%H:%M:%S}] {name}: CMA-ES + MCMC ...", flush=True)
        results.append(fit_dataset(name, filename, cdl, 10.0, args))
        print(f"[{datetime.now():%H:%M:%S}] {name}: HarmPer={results[-1]['best_harmper']:.4f}",
              flush=True)
        # 每完成一个数据集就落盘。WORK_STATUS §16 记录过一次末尾统一写 CSV
        # 导致整轮正式运行只留下表头的事故，这里不重复该模式。
        _write_outputs(outdir, results, ru_rows, args)

    ru_rows = []
    for ru in args.ru_sensitivity:
        for name, filename, cdl in selected:
            objective = _build_objective(name, filename, cdl, ru)
            unit, loss = run_cma(objective, args.cma_evals, args.seed)
            params = decode(unit, *default_bounds())
            ru_rows.append({"dataset": name, "Ru": ru, "harmper": loss, **params})
            print(f"[{datetime.now():%H:%M:%S}] {name} Ru={ru}: HarmPer={loss:.4f}", flush=True)
            _write_outputs(outdir, results, ru_rows, args)

    _write_outputs(outdir, results, ru_rows, args)
    print(f"written -> {outdir}")
    return 0


def _write_outputs(outdir: Path, results, ru_rows, args):
    import csv

    with open(outdir / "posterior_samples.csv", "w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["dataset", *PARAM_NAMES_REAL])
        for row in results:
            if row["samples"] is None:
                continue
            for sample in row["samples"]:
                writer.writerow([row["dataset"],
                                 f"{sample[0]:.6f}",
                                 f"{10 ** sample[1]:.6e}",
                                 f"{10 ** sample[2]:.6e}",
                                 f"{10 ** sample[3]:.6e}"])

    with open(outdir / "posterior_summary.csv", "w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["dataset", "parameter", "mean", "median", "std",
                         "q2.5", "q97.5", "rhat", "provenance"])
        for row in results:
            if row["summary"] is None:
                continue
            for name, stats in row["summary"].items():
                writer.writerow([row["dataset"], name,
                                 f"{stats['mean']:.6g}", f"{stats['median']:.6g}",
                                 f"{stats['std']:.6g}", f"{stats['q2.5']:.6g}",
                                 f"{stats['q97.5']:.6g}", f"{stats['rhat']:.4f}", "fitted"])
            for pin, provenance in PINNED_PROVENANCE.items():
                value = row["Ru"] if pin == "Ru" else (row["Cdl"] if pin == "Cdl"
                                                       else (1.0 if pin == "A" else 0.5))
                writer.writerow([row["dataset"], pin, f"{value:.6g}", f"{value:.6g}",
                                 "0", f"{value:.6g}", f"{value:.6g}", "", provenance])

    with open(outdir / "correlation.csv", "w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["dataset", "parameter", *PARAM_NAMES])
        for row in results:
            if row["correlation"] is None:
                continue
            for i, name in enumerate(PARAM_NAMES):
                writer.writerow([row["dataset"], name,
                                 *[f"{value:.4f}" for value in row["correlation"][i]]])

    with open(outdir / "ru_sensitivity.csv", "w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["dataset", "Ru", "harmper", "E0_eff", "k0", "kf", "gamma"])
        for row in ru_rows:
            writer.writerow([row["dataset"], row["Ru"], f"{row['harmper']:.4f}",
                             f"{row['E0_eff']:.4f}", f"{row['k0']:.4g}",
                             f"{row['kf']:.4g}", f"{row['gamma']:.4g}"])

    manifest = {
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "commit": _git_commit(),
        "python": platform.python_version(),
        "numpy": np.__version__,
        "platform": platform.platform(),
        "model": "Bonke molecular catalysis (surface redox + pseudo-first-order catalysis)",
        "free_parameters": list(PARAM_NAMES),
        "pinned_provenance": PINNED_PROVENANCE,
        "fit_harmonics": list(FIT_HARMONICS),
        "excluded_from_objective": ["DC (未扣除基底背景)", "H1 (双电层与催化电流主导)"],
        "fit_window_V": [E_FIT_LO, E_FIT_HI],
        "objective_optimiser": "HarmPer (Gundry 2021)",
        "objective_bayesian": "MLE-ExpHarmPer, sigma_h profiled out (Jeffreys)",
        "sampler": "adaptive covariance MCMC (Haario), 4 chains",
        "args": vars(args),
        "datasets": [
            {k: row[k] for k in ("dataset", "filename", "f0", "dE", "v",
                                 "E_fit_lo", "E_fit_hi", "n_points", "Ru", "Cdl",
                                 "best_harmper", "acceptance", "implied_sigma",
                                 "target_peak")}
            for row in results
        ],
        "scale_degeneracy_note": (
            "Faradaic current scales as gamma*A; with A pinned, reported gamma is "
            "gamma*A/A_assumed and must not be read as an absolute site density."
        ),
    }
    with open(outdir / "run_manifest.json", "w") as handle:
        json.dump(manifest, handle, indent=2, ensure_ascii=False)


PARAM_NAMES_REAL = ("E0_eff", "k0", "kf", "gamma")

if __name__ == "__main__":
    raise SystemExit(main())
