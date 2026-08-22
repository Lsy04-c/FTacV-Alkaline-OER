#!/usr/bin/env python3
"""求解器加速可行性基准：C Crank-Nicolson vs SciPy LSODA。

用法：
    cc -O3 -shared -fPIC -o /tmp/mc_cn.so cpp/mc_cn_solver.c -lm
    .venv/bin/python scripts/bench_solver_acceleration.py --lib /tmp/mc_cn.so

结论与完整数据见 `docs/solver_acceleration_feasibility.md`。
本脚本只做基准与精度对照，**不**是正式等价性门——那需要跨参数空间抽样，
见该文档第 7 节。
"""

from __future__ import annotations

import argparse
import ctypes
import sys
import time
from pathlib import Path

import numpy as np
from scipy.integrate import solve_ivp

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT / "python"))

from oer_aem import molecular_catalysis as mc  # noqa: E402

OUT_POINTS_PER_CYCLE = 128


def load_library(path: str):
    lib = ctypes.CDLL(path)
    lib.mc_cn_solve.restype = ctypes.c_int
    lib.mc_cn_solve.argtypes = [
        np.ctypeslib.ndpointer(np.float64, flags="C_CONTIGUOUS"),
        ctypes.c_double, ctypes.c_long, ctypes.c_long,
        *([ctypes.c_double] * 12),
        np.ctypeslib.ndpointer(np.float64, flags="C_CONTIGUOUS"),
        np.ctypeslib.ndpointer(np.float64, flags="C_CONTIGUOUS"),
    ]
    return lib


def harmonic_envelope(current, t, harmonic, f0):
    spectrum = np.fft.rfft(current)
    freqs = np.fft.rfftfreq(len(current), t[1] - t[0])
    mask = np.abs(freqs - harmonic * f0) < 0.4 * f0
    filtered = np.zeros_like(spectrum)
    filtered[mask] = spectrum[mask]
    return np.abs(np.fft.irfft(filtered, len(current)))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lib", required=True, help="编译好的 mc_cn_solver 动态库")
    parser.add_argument("--repeats", type=int, default=20)
    args = parser.parse_args()

    lib = load_library(args.lib)

    scan_rate, e_lo, e_hi = 0.01756, 1.20, 1.65
    total_time = (e_hi - e_lo) / scan_rate
    params = dict(E_start=e_lo, v=scan_rate, dE=0.16, f=5.0, Ru=10.0,
                  Cdl=30.8e-6, A=1.0, gamma=3e-10, k0=50.0, kf=200.0,
                  E0_eff=1.58, total_time=total_time)
    p = mc.initialize_mc_system(params)
    y0 = np.ascontiguousarray(mc.calculate_mc_steady_state(p))
    n_out = int(round(total_time * p["f"] * OUT_POINTS_PER_CYCLE))
    c_args = (p["RTF"], p["alpha"], p["k0"], p["kf"], p["E0_eff"], p["omega"],
              p["E_start"], p["v"], p["dE"], p["invRC"],
              p["gamma"] * p["F"] / p["Cdl"], p["Ru"])

    def c_solve(steps_per_cycle):
        n_steps = n_out * max(1, steps_per_cycle // OUT_POINTS_PER_CYCLE)
        out_t = np.empty(n_out)
        out_i = np.empty(n_out)
        code = lib.mc_cn_solve(y0, total_time, n_steps, n_out, *c_args, out_t, out_i)
        if code != 0:
            raise RuntimeError(f"mc_cn_solve returned {code}")
        return out_t, out_i

    t_grid = np.linspace(0.0, total_time, n_out, endpoint=False)

    def lsoda(rtol, atol, cap_step):
        kwargs = dict(rtol=rtol, atol=atol)
        if cap_step:
            kwargs["max_step"] = 1.0 / (p["f"] * 20)
        start = time.time()
        sol = solve_ivp(lambda tt, y: mc._mc_rhs(tt, y, p),
                        (0.0, total_time), y0, t_eval=t_grid,
                        method="LSODA", **kwargs)
        elapsed = time.time() - start
        e_app = (p["E_start"] + p["v"] * t_grid
                 + p["dE"] * np.sin(p["omega"] * t_grid))
        return elapsed, (e_app - sol.y[1]) / p["Ru"], sol.nfev

    el_ref, i_ref, nfev_ref = lsoda(1e-8, 1e-11, False)
    el_prod, _, nfev_prod = lsoda(1e-6, 1e-9, True)
    reference = {h: harmonic_envelope(i_ref, t_grid, h, p["f"]) for h in (2, 3, 4)}

    print(f"LSODA rtol=1e-8 (reference) : {el_ref:.4f} s  nfev={nfev_ref}")
    print(f"LSODA rtol=1e-6 (production): {el_prod:.4f} s  nfev={nfev_prod}\n")
    print(f"{'C-CN steps/cyc':<16}{'wall(s)':>10}{'vs ref':>10}{'vs prod':>10}   H2/H3/H4 rel err")

    for steps_per_cycle in (128, 256, 512, 1024):
        c_solve(steps_per_cycle)
        start = time.time()
        for _ in range(args.repeats):
            out_t, out_i = c_solve(steps_per_cycle)
        elapsed = (time.time() - start) / args.repeats
        errors = [
            np.max(np.abs(harmonic_envelope(out_i, out_t, h, p["f"]) - reference[h]))
            / np.max(reference[h])
            for h in (2, 3, 4)
        ]
        print(f"{steps_per_cycle:<16}{elapsed:>10.5f}{el_ref/elapsed:>9.0f}x"
              f"{el_prod/elapsed:>9.0f}x   " + " ".join(f"{e:.2e}" for e in errors))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
