#!/usr/bin/env python3
"""Profile likelihood：直接刻画哪些参数方向是平的（可辨识性诊断）。

为什么用它而不是继续调 MCMC（docs/项目纠错.md §26）：
固定步长扫描证明后验是一条又窄又弯的脊——每个 scale 下链间散布都比链内
大 10–100 倍，各向同性提议无法沿脊移动。MCMC 用于量化不确定度的前提是
后验单峰且可遍历；在确认之前用它，顺序就反了。

Profile 不需要采样收敛：固定一个参数于网格，对其余参数做局部优化，
剖面平坦即该参数不可辨识。

用法：
    .venv/bin/python scripts/profile_likelihood.py --points 15 --workers 16
"""

from __future__ import annotations

import argparse
import csv
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
from scipy.optimize import minimize

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT / "python"))

from oer_aem.low_dim_fit import (  # noqa: E402
    FIT_HARMONICS, PARAM_NAMES, default_bounds, harm_per,
    harmonic_envelopes,
)
from oer_aem.molecular_catalysis import simulate  # noqa: E402

TRUTH = {"E0_eff": 1.58, "k0": 50.0, "kf": 200.0, "gamma": 3.0e-10}
_CTX: dict = {}


def _build(noise: float, seed: int):
    f0, scan_rate, e_start, n_cycles = 5.0, 0.01756, 1.45, 64
    total_time = n_cycles / f0
    fs = f0 * 256
    n = int(round(total_time * fs))
    t = np.linspace(0.0, total_time, n, endpoint=False)
    pinned = dict(E_start=e_start, v=scan_rate, dE=0.16, f=f0, Ru=10.0,
                  Cdl=30.8e-6, A=1.0, alpha=0.5, total_time=total_time)
    _, current, _ = simulate({**pinned, **TRUTH}, t)
    rng = np.random.default_rng(seed)
    target = harmonic_envelopes(current, fs, f0, FIT_HARMONICS)
    target = target + rng.normal(
        0.0, noise * target.max(axis=1, keepdims=True), target.shape)
    return pinned, t, fs, f0, target


def _init(noise, seed):
    pinned, t, fs, f0, target = _build(noise, seed)
    lower, upper = default_bounds()
    _CTX.update(pinned=pinned, t=t, fs=fs, f0=f0, target=target,
                lower=lower, upper=upper)


def _loss(unit):
    unit = np.asarray(unit, dtype=float)
    if np.any(unit < 0) or np.any(unit > 1):
        return 1e6
    values = _CTX["lower"] + unit * (_CTX["upper"] - _CTX["lower"])
    params = {**_CTX["pinned"], "E0_eff": values[0], "k0": 10.0 ** values[1],
              "kf": 10.0 ** values[2], "gamma": 10.0 ** values[3]}
    _, current, _ = simulate(params, _CTX["t"])
    if not np.all(np.isfinite(current)):
        return 1e6
    envelopes = harmonic_envelopes(current, _CTX["fs"], _CTX["f0"], FIT_HARMONICS)
    return harm_per(envelopes, _CTX["target"])


def _profile_sweep(job):
    """对第 index 个参数做 continuation 扫描：从全局最优点向两侧推进。

    每个网格点以**相邻点的解**作为起点。剖面本应光滑，相邻点的最优解也
    相近；独立多起点优化在 3 个自由参数（其中两个跨 5-6 个数量级）上预算
    不足，会产生锯齿——相邻点跳 5-10 倍，测到的是优化器噪声而非似然面。
    """
    index, grid, anchor_unit, seed = job
    free = [i for i in range(4) if i != index]
    rng = np.random.default_rng(seed)

    def solve(fixed_unit, start, budget):
        best_val, best_x = np.inf, start
        for attempt in range(2):
            x0 = start if attempt == 0 else np.clip(
                start + rng.normal(0, 0.05, size=3), 0.02, 0.98)

            def wrapped(free_vals):
                unit = np.empty(4)
                unit[index] = fixed_unit
                unit[free] = free_vals
                return _loss(unit)

            res = minimize(wrapped, x0, method="Nelder-Mead",
                           options={"maxfev": budget, "xatol": 1e-4,
                                    "fatol": 1e-6, "adaptive": True})
            if res.fun < best_val:
                best_val, best_x = float(res.fun), np.asarray(res.x)
        return best_val, np.clip(best_x, 0.02, 0.98)

    # 锚点用较大预算求一次可靠的解，再向两侧 continuation
    anchor_start = np.asarray([anchor_unit[i] for i in free])
    centre = int(np.argmin(np.abs(grid - anchor_unit[index])))
    out = {}
    val, x = solve(float(grid[centre]), anchor_start, 900)
    out[centre] = val
    warm = x
    for j in range(centre + 1, len(grid)):
        val, warm = solve(float(grid[j]), warm, 450)
        out[j] = val
    warm = x
    for j in range(centre - 1, -1, -1):
        val, warm = solve(float(grid[j]), warm, 450)
        out[j] = val
    return index, [(float(grid[j]), out[j]) for j in sorted(out)]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--points", type=int, default=15)
    parser.add_argument("--workers", type=int, default=16)
    parser.add_argument("--noise", type=float, default=0.02)
    parser.add_argument("--seed", type=int, default=11)
    parser.add_argument("--out", default="results/profile_likelihood/profile.csv")
    args = parser.parse_args()

    lower, upper = default_bounds()
    grid = np.linspace(0.03, 0.97, args.points)
    truth_unit = (np.array([TRUTH["E0_eff"], np.log10(TRUTH["k0"]),
                            np.log10(TRUTH["kf"]), np.log10(TRUTH["gamma"])])
                  - lower) / (upper - lower)
    jobs = [(i, grid, truth_unit, args.seed + 97 * i) for i in range(4)]

    with ProcessPoolExecutor(max_workers=min(args.workers, 4), initializer=_init,
                             initargs=(args.noise, args.seed)) as pool:
        sweeps = list(pool.map(_profile_sweep, jobs))
    results = [(idx, u, v) for idx, pts in sweeps for u, v in pts]

    truth_real = np.array([TRUTH["E0_eff"], np.log10(TRUTH["k0"]),
                           np.log10(TRUTH["kf"]), np.log10(TRUTH["gamma"])])
    out_path = PROJECT / args.out
    out_path.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    print("Profile likelihood（合成数据，真值已知，噪声 %.0f%%）\n" % (100 * args.noise))
    for index, name in enumerate(PARAM_NAMES):
        pts = sorted([r for r in results if r[0] == index], key=lambda r: r[1])
        units = np.array([p[1] for p in pts])
        losses = np.array([p[2] for p in pts])
        # 剖面必须光滑；相邻点大幅跳变说明内层优化失败，此时数字无意义
        jag = np.max(np.abs(np.diff(losses)) / np.maximum(losses[:-1], 1e-12))
        smooth = "" if jag < 1.0 else f"   [剖面锯齿 {jag:.1f}x，内层优化可能未收敛]"
        values = lower[index] + units * (upper[index] - lower[index])
        best = losses.min()
        # 剖面在最优值上抬升 10% 之内的区间宽度 = 该参数被约束的程度
        inside = values[losses <= best * 1.10]
        width = inside.max() - inside.min() if inside.size else np.nan
        span = upper[index] - lower[index]
        print(f"  {name:14s} 最优 {values[int(np.argmin(losses))]:8.3f}  "
              f"真值 {truth_real[index]:8.3f}  "
              f"10% 抬升区间宽 {width:7.3f} / 先验 {span:6.3f} = {width/span:5.1%}"
              f"{'   <== 几乎不受约束' if width/span > 0.5 else ''}{smooth}")
        for u, v, l in zip(units, values, losses):
            rows.append({"parameter": name, "unit": f"{u:.4f}",
                         "value": f"{v:.6g}", "harmper": f"{l:.6g}"})

    with open(out_path, "w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["parameter", "unit", "value", "harmper"])
        writer.writeheader()
        writer.writerows(rows)
    print(f"\n写入 {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
