#!/usr/bin/env python3
"""用 PINTS 的 HaarioACMC 独立校验本项目手写的自适应协方差采样器。

背景：`python/oer_aem/mcmc.py` 是手写实现，原因是拯救者已验收环境不允许
改动依赖（roadmap §2.2）。手写实现有 5 项自洽正确性测试，但**没有外部参照**。
PINTS 是 Gundry 2021 与 Dale-Evans 2021 使用的推断库，其 `HaarioACMC`
与本项目实现的是同一个算法（Haario 自适应协方差）。

PINTS 不进入项目依赖，只作为一次性交叉校验工具，装在隔离环境里：

    python3 -m venv /tmp/pintsenv && /tmp/pintsenv/bin/pip install pints
    /tmp/pintsenv/bin/python scripts/crosscheck_sampler_vs_pints.py \
        --repo python

结果记录在 `docs/external_validation.md`。
"""

from __future__ import annotations

import argparse
import sys

import numpy as np

RHO = 0.8
MEAN = np.array([1.0, -2.0])
STD = np.array([0.5, 0.8])
LOWER = np.array([-6.0, -8.0])
UPPER = np.array([6.0, 4.0])
COV = np.array([[STD[0] ** 2, RHO * STD[0] * STD[1]],
                [RHO * STD[0] * STD[1], STD[1] ** 2]])
INV_COV = np.linalg.inv(COV)


def log_pdf(theta) -> float:
    delta = np.asarray(theta, dtype=float) - MEAN
    return float(-0.5 * delta @ INV_COV @ delta)


def describe(name, samples, rhat):
    corr = np.corrcoef(samples, rowvar=False)[0, 1]
    print(f"  {name:24s} mean=({samples[:, 0].mean():+.4f}, {samples[:, 1].mean():+.4f})  "
          f"std=({samples[:, 0].std(ddof=1):.4f}, {samples[:, 1].std(ddof=1):.4f})  "
          f"corr={corr:+.4f}  rhat={np.max(rhat):.4f}")
    return corr


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default="python", help="oer_aem 包所在目录")
    parser.add_argument("--iterations", type=int, default=24000)
    parser.add_argument("--chains", type=int, default=4)
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args()

    sys.path.insert(0, args.repo)
    from oer_aem.mcmc import run_adaptive_mcmc

    result = run_adaptive_mcmc(
        lambda unit: log_pdf(LOWER + np.asarray(unit) * (UPPER - LOWER)),
        x0_unit=np.array([0.5, 0.5]), lower=LOWER, upper=UPPER,
        names=("a", "b"), n_iterations=args.iterations, thin=4,
        n_chains=args.chains, seed=args.seed)
    ours = result.pooled

    import pints

    class Target(pints.LogPDF):
        def n_parameters(self):
            return 2

        def __call__(self, x):
            if np.any(x < LOWER) or np.any(x > UPPER):
                return -np.inf
            return log_pdf(x)

    starts = [MEAN + np.array([0.3, -0.3]) * i for i in range(args.chains)]
    controller = pints.MCMCController(Target(), args.chains, starts,
                                      method=pints.HaarioACMC)
    controller.set_max_iterations(args.iterations)
    controller.set_log_to_screen(False)
    chains = controller.run()
    half = args.iterations // 2
    theirs = chains[:, half:, :].reshape(-1, 2)

    print(f"  {'真值':24s} mean=({MEAN[0]:+.4f}, {MEAN[1]:+.4f})  "
          f"std=({STD[0]:.4f}, {STD[1]:.4f})  corr={RHO:+.4f}")
    corr_ours = describe("本项目 oer_aem.mcmc", ours, result.gelman_rubin())
    corr_theirs = describe("PINTS HaarioACMC", theirs, pints.rhat(chains[:, half:, :]))

    print(f"\n  实现间差异: |Δmean|={np.abs(ours.mean(0) - theirs.mean(0))}  "
          f"|Δstd|={np.abs(ours.std(0, ddof=1) - theirs.std(0, ddof=1))}  "
          f"|Δcorr|={abs(corr_ours - corr_theirs):.4f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
