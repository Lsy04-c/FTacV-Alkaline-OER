#!/usr/bin/env python3
"""合成数据回收验证：修正似然后，后验能否收敛到已知真值。

这是重跑真实数据的**前置条件**。docs/项目纠错.md §25 记录过一次教训：
似然缺陷导致 6 小时机时的后验全部作废，而缺陷在真实数据上只表现为
R-hat 异常——若当时先在合成数据上验一遍，可以在几分钟内发现。

判据（运行前固定）：
  1. 所有参数 R-hat < 1.1
  2. 所有真值落在 95% 可信区间内
  3. 接受率在 0.05–0.6 之间（过低=链卡死，过高=步长过小）

用法：
    .venv/bin/python scripts/validate_synthetic_recovery.py --iterations 4000
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT / "python"))

from oer_aem.low_dim_fit import (  # noqa: E402
    FIT_HARMONICS, PARAM_NAMES, default_bounds, harmonic_envelopes,
    likelihood_stride, mle_exp_harm_per,
)
from oer_aem.mcmc import run_adaptive_mcmc  # noqa: E402
from oer_aem.molecular_catalysis import simulate  # noqa: E402

TRUTH = {"E0_eff": 1.58, "k0": 50.0, "kf": 200.0, "gamma": 3.0e-10}
_CTX: dict = {}


def _worker_log_posterior(unit):
    """子进程用的对数后验（链并行时由 ProcessPoolExecutor 调用）。"""
    import numpy as _np
    unit = _np.asarray(unit)
    if _np.any(unit <= 0) or _np.any(unit >= 1):
        return -_np.inf
    lower, upper = _CTX["lower"], _CTX["upper"]
    values = lower + unit * (upper - lower)
    params = {**_CTX["pinned"], "E0_eff": values[0], "k0": 10.0 ** values[1],
              "kf": 10.0 ** values[2], "gamma": 10.0 ** values[3]}
    _, current, _ = simulate(params, _CTX["t"])
    if not _np.all(_np.isfinite(current)):
        return -_np.inf
    envelopes = harmonic_envelopes(current, _CTX["fs"], _CTX["f0"], FIT_HARMONICS)
    return mle_exp_harm_per(envelopes, _CTX["target"], _CTX["stride"])


def _init_worker(cycles, noise, seed):
    """在子进程中重建上下文。

    macOS 默认 spawn，子进程不继承运行时设置的全局变量；Linux 的 fork 会，
    因此这个缺陷只在本机暴露、在拯救者上会被掩盖。用 initializer 显式重建，
    两个平台行为一致。
    """
    from oer_aem.low_dim_fit import default_bounds as _bounds
    pinned, t, fs, f0, target = build_case(cycles, noise, seed)
    lower, upper = _bounds()
    _CTX.update(pinned=pinned, t=t, fs=fs, f0=f0, target=target,
                stride=likelihood_stride(fs, f0), lower=lower, upper=upper)


def _chain_task(job):
    start, iterations, seed = job
    from oer_aem.low_dim_fit import PARAM_NAMES as _names
    result = run_adaptive_mcmc(_worker_log_posterior, x0_unit=start,
                               lower=_CTX["lower"], upper=_CTX["upper"],
                               names=_names, n_iterations=iterations,
                               thin=4, n_chains=1, seed=seed)
    chain = result.chains[0]
    return chain.samples, chain.log_posterior, chain.acceptance_rate, seed
RHAT_LIMIT = 1.10
ACCEPT_RANGE = (0.05, 0.60)


def build_case(n_cycles: int, noise_frac: float, seed: int):
    f0, scan_rate, e_start = 5.0, 0.01756, 1.45
    total_time = n_cycles / f0
    e_end = e_start + scan_rate * total_time

    # 扫描窗口必须跨过 E0_eff 且两侧留余量，否则表面氧化还原根本不被激发，
    # 参数在构造上就不可辨识。这个错误 2026-08-23 犯过两次（先是
    # test_molecular_catalysis 的 fixture，随后是本脚本），因此改为硬断言，
    # 不再依赖人去核对。
    margin = 0.04
    if not (e_start + margin < TRUTH["E0_eff"] < e_end - margin):
        raise SystemExit(
            f"合成算例无效：扫描窗口 [{e_start:.3f}, {e_end:.3f}] V 未跨过 "
            f"E0_eff={TRUTH['E0_eff']:.3f} V（两侧需留 {margin*1000:.0f} mV 余量）。"
            f"请增大 --cycles 或调整 E_start。")

    fs = f0 * 256
    n = int(round(total_time * fs))
    t = np.linspace(0.0, total_time, n, endpoint=False)
    pinned = dict(E_start=e_start, v=scan_rate, dE=0.16, f=f0, Ru=10.0,
                  Cdl=30.8e-6, A=1.0, alpha=0.5, total_time=total_time)
    _, current, _ = simulate({**pinned, **TRUTH}, t)

    rng = np.random.default_rng(seed)
    target = harmonic_envelopes(current, fs, f0, FIT_HARMONICS)
    noisy = target + rng.normal(
        0.0, noise_frac * target.max(axis=1, keepdims=True), target.shape)
    return pinned, t, fs, f0, noisy


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cycles", type=int, default=64)
    parser.add_argument("--iterations", type=int, default=4000)
    parser.add_argument("--chains", type=int, default=4)
    parser.add_argument("--workers", type=int, default=4,
                        help="并行运行的链数进程数")
    parser.add_argument("--noise", type=float, default=0.02)
    parser.add_argument("--seed", type=int, default=11)
    args = parser.parse_args()

    pinned, t, fs, f0, target = build_case(args.cycles, args.noise, args.seed)
    stride = likelihood_stride(fs, f0)
    lower, upper = default_bounds()
    _CTX.update(pinned=pinned, t=t, fs=fs, f0=f0, target=target,
                stride=stride, lower=lower, upper=upper)

    def log_posterior(unit):
        unit = np.asarray(unit)
        if np.any(unit <= 0) or np.any(unit >= 1):
            return -np.inf
        values = lower + unit * (upper - lower)
        params = {**pinned, "E0_eff": values[0], "k0": 10.0 ** values[1],
                  "kf": 10.0 ** values[2], "gamma": 10.0 ** values[3]}
        _, current, _ = simulate(params, t)
        if not np.all(np.isfinite(current)):
            return -np.inf
        envelopes = harmonic_envelopes(current, fs, f0, FIT_HARMONICS)
        return mle_exp_harm_per(envelopes, target, stride)

    truth_unit = (np.array([TRUTH["E0_eff"], np.log10(TRUTH["k0"]),
                            np.log10(TRUTH["kf"]), np.log10(TRUTH["gamma"])])
                  - lower) / (upper - lower)
    # 起点故意偏离真值，避免"从真值出发"掩盖不收敛
    start = np.clip(truth_unit + np.array([0.08, -0.10, 0.10, -0.08]), 0.02, 0.98)

    print(f"合成回收：{args.cycles} 周期，噪声 {args.noise:.0%}，"
          f"stride={stride}，{args.chains} 链 × {args.iterations} 迭代", flush=True)

    # 进度输出必须实时。docs/项目纠错.md §22：日志长时间为空时无法区分
    # "正在跑"和"已被收走"，这次本机运行就因缓冲导致跑了半小时日志仍是 0 字节。
    import time
    state = {"n": 0, "t0": time.time()}

    def traced(unit):
        state["n"] += 1
        if state["n"] % 200 == 0:
            print(f"  ... {state['n']} 次似然求值, "
                  f"{time.time() - state['t0']:.0f}s", flush=True)
        return log_posterior(unit)

    from concurrent.futures import ProcessPoolExecutor
    from oer_aem.mcmc import ChainResult, MCMCResult

    jobs = [(start, args.iterations, args.seed + 1000 * i)
            for i in range(args.chains)]
    with ProcessPoolExecutor(max_workers=min(args.chains, args.workers),
                             initializer=_init_worker,
                             initargs=(args.cycles, args.noise, args.seed)) as pool:
        raw = list(pool.map(_chain_task, jobs))
    chains = [ChainResult(s_, lp, ar, sd) for s_, lp, ar, sd in raw]
    result = MCMCResult(chains=chains, names=PARAM_NAMES,
                        lower=lower, upper=upper)
    print(f"  {args.chains} 条链并行完成", flush=True)

    summary = result.summary()
    truth_real = {"E0_eff": TRUTH["E0_eff"], "log10_k0": np.log10(TRUTH["k0"]),
                  "log10_kf": np.log10(TRUTH["kf"]),
                  "log10_gamma": np.log10(TRUTH["gamma"])}

    print(f"\n  {'参数':14s}{'真值':>10s}{'后验中位':>11s}{'95% 区间':>22s}{'rhat':>8s}  判定")
    all_ok = True
    for name, stats in summary.items():
        true_value = truth_real[name]
        inside = stats["q2.5"] <= true_value <= stats["q97.5"]
        converged = stats["rhat"] < RHAT_LIMIT
        ok = inside and converged
        all_ok &= ok
        print(f"  {name:14s}{true_value:10.4f}{stats['median']:11.4f}"
              f"  [{stats['q2.5']:8.4f},{stats['q97.5']:8.4f}]{stats['rhat']:8.3f}"
              f"  {'PASS' if ok else 'FAIL'}"
              f"{'' if inside else ' (真值在区间外)'}"
              f"{'' if converged else ' (未收敛)'}")

    rates = [c.acceptance_rate for c in result.chains]
    rate_ok = all(ACCEPT_RANGE[0] <= r <= ACCEPT_RANGE[1] for r in rates)
    all_ok &= rate_ok
    print(f"\n  接受率 {[round(r, 3) for r in rates]}  "
          f"{'PASS' if rate_ok else 'FAIL（应在 %.2f–%.2f）' % ACCEPT_RANGE}")
    print(f"\n  合成回收判定：{'PASS' if all_ok else 'FAIL'}")
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
