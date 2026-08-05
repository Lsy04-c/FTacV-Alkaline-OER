#!/usr/bin/env python3
"""Raw-cmaes 适配版 CMA-ES 合成恢复筛选。

搜索 z∈[0,1]^n（经 denormalize_vector 映射回编码坐标），带 bounds、
盒子中点温启动 mean、sigma=0.25、popsize=4+3ln(n)，CMA 收敛
(should_stop) 后以当前最优点倍增 popsize 重启（IPOP 式）。

设计背景（2026-08-06）：
- optuna 4.9.0 弃用了 CmaEsSampler 的 restart_strategy/x0，无法做适配，
  故直接用 raw cmaes 包。
- smoke 分辨率(256点)下 truth 点 Tafel 特征提取失败、landscape 失真，
  正式筛选必须全量(8192点)；--smoke 仅作本地机制自检。

用法:
  python screen_cmaes_raw.py --mode legacy --seed 7 --trials 500
  python screen_cmaes_raw.py --smoke --trials 30   # 本地自检
"""
import argparse
import json
import time
from pathlib import Path
from typing import Mapping, Optional, Sequence

import numpy as np

try:
    import cmaes
except ImportError as e:  # pragma: no cover
    raise SystemExit("需要 cmaes 包: pip install cmaes") from e

from oer_aem.inversion import (
    DEFAULT_PARAM_SPECS,
    InversionObjective,
    decode_vector,
    denormalize_vector,
)
from oer_aem.recovery import recovery_metrics, truth_library
from run_synthetic_recovery import build_recovery_problem, make_synthetic_target

NOISE_FRACTION = 0.001495726085983469
TARGET_SEED = 1443515106
FREE = ["k0_1", "k0_2", "k0_3", "G_OH", "G_O", "scaling_OOH_OH"]


def run_raw_cmaes(
    mode: str,
    seed: int,
    trials: int,
    smoke: bool = False,
    free_names: Sequence[str] = FREE,
    fixed_override: Optional[Mapping[str, float]] = None,
) -> dict:
    truths = truth_library(DEFAULT_PARAM_SPECS)
    truth = next(t for t in truths if t["truth_id"] == "mixed_b")
    params = truth["parameters"]  # 真值：用于生成 target 与恢复度量
    # 优化器的固定参数：可把某个非自由参数钉在大值（准平衡区降维实验）
    opt_truth = dict(params)
    if fixed_override:
        opt_truth.update(fixed_override)
    job = {
        "feature_mode": mode,
        "truth_id": "mixed_b",
        "truth_params": opt_truth,
        "noise_fraction": NOISE_FRACTION,
        "seed": seed,
        "target_seed": TARGET_SEED,
        "trials": trials,
        "free_parameters": list(free_names),
        "backend": "lsoda",
    }
    config, free_specs = build_recovery_problem(job, smoke=smoke)
    target = make_synthetic_target(
        params, config=config, noise_fraction=NOISE_FRACTION, seed=TARGET_SEED
    )
    objective = InversionObjective(target, config, free_specs)

    dim = len(free_specs)
    bounds = np.tile(np.array([0.0, 1.0]), (dim, 1))
    sigma = 0.25
    popsize = int(4 + 3 * np.log(dim))
    mean = np.full(dim, 0.5)  # 盒子中点温启动（不取巧，非 truth）
    optimizer = cmaes.CMA(mean=mean, sigma=sigma, bounds=bounds, seed=seed,
                          population_size=popsize)

    best_value = float("inf")
    best_z: np.ndarray | None = None
    n_eval = 0
    n_restarts = 0
    while n_eval < trials:
        # cmaes 0.13 的 ask() 每次返回一个个体；攒满一代再 tell()
        pop = min(popsize, trials - n_eval)
        xs = [optimizer.ask() for _ in range(pop)]
        vals = []
        for x in xs:
            v = objective(denormalize_vector(np.asarray(x, dtype=float), free_specs))
            vals.append(float(v))
            n_eval += 1
            if v < best_value:
                best_value = float(v)
                best_z = np.array(x, dtype=float)
        if pop < popsize:
            break  # 预算在最后一代耗尽，不 tell
        optimizer.tell(list(zip(xs, vals)))
        if optimizer.should_stop():
            n_restarts += 1
            popsize = min(popsize * 2, max(4, trials // 4))
            mean = best_z if best_z is not None else np.full(dim, 0.5)
            optimizer = cmaes.CMA(mean=mean, sigma=sigma, bounds=bounds,
                                  seed=seed + 1000 * n_restarts,
                                  population_size=popsize)

    enc_best = denormalize_vector(best_z, free_specs) if best_z is not None else None
    best_params = decode_vector(enc_best, free_specs) if enc_best is not None else {}
    metrics = recovery_metrics(truth=params, estimate=best_params, specs=free_specs)
    return {
        "mode": mode,
        "seed": seed,
        "trials": trials,
        "smoke": smoke,
        "sampler": "cmaes_raw",
        "best_value": best_value,
        "best_params": best_params,
        "n_forward": int(objective.n_forward),
        "n_ode_fail": int(objective.n_ode_fail),
        "n_feature_fail": int(objective.n_feature_fail),
        "n_tafel_fail": int(objective.n_tafel_fail),
        "n_restarts": int(n_restarts),
        "truth": params,
        "metrics": {
            name: {"normalized_bound_error": metrics[name]["normalized_bound_error"]}
            for name, *_ in free_specs
        },
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", default="legacy",
                    choices=["legacy", "complex_snr", "lockin_only", "hybrid"])
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--trials", type=int, default=500)
    ap.add_argument("--smoke", action="store_true", help="smoke 分辨率（仅自检，landscape 失真）")
    ap.add_argument("--free", default=",".join(FREE),
                    help="自由参数（逗号分隔），默认 6 个")
    ap.add_argument("--fixed-override", default=None,
                    help="把非自由参数钉在给定值，如 'k0_1=10000'（准平衡区降维）")
    ap.add_argument("--out", default=None, help="结果 JSON 输出路径")
    args = ap.parse_args()

    free_names = [s.strip() for s in args.free.split(",") if s.strip()]
    fixed_override = None
    if args.fixed_override:
        fixed_override = {}
        for spec in args.fixed_override.split(","):
            name, _, value = spec.partition("=")
            fixed_override[name.strip()] = float(value)

    t0 = time.perf_counter()
    res = run_raw_cmaes(args.mode, args.seed, args.trials, smoke=args.smoke,
                        free_names=free_names, fixed_override=fixed_override)
    res["runtime_seconds"] = round(time.perf_counter() - t0, 2)
    print(json.dumps(res, indent=2, default=float))
    if args.out:
        Path(args.out).write_text(json.dumps(res, indent=2, default=float))


if __name__ == "__main__":
    main()
