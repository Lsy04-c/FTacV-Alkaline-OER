#!/usr/bin/env python3
"""CN vs LSODA 跨参数空间等价性门（低维分子催化模型）。

用法：
    ./scripts/build_mc_cn.sh
    .venv/bin/python scripts/gate_solver_equivalence.py --samples 24

设计原则（沿用 WORK_STATUS §19 对 5 步模型 CN 的做法）：

* 阈值在本文件中**预先冻结**，失败不许调阈值；
* 抽样覆盖整个反演参数边界，而不是单个参数点；
* 同时覆盖四组数据各自的扫描配置（频率、扫速、时长互不相同）；
* CN 与 LSODA **共用同一个稳态初值**——§7 记录过 C++ 自行算初值造成
  18.5% NRMSE 的事故，远大于积分格式本身的差异；
* 参考强度低于最强通道 2% 的**通道**不评价，且通道内**局部幅值**低于该
  通道峰值 2% 的点也不评价相位——相位在无信号处没有定义。§19 只写了
  通道级的 2% 规则；电位分辨比较必须把同一规则用到点级，否则量到的是
  零幅值处的随机相位（2 样本冒烟中实测：某点"相位误差 1.1 rad"处的局部
  幅值只有峰值的 0.016%，掩蔽后同一通道最大相位误差为 0.006 rad）。
  **这是指标定义修正，不是阈值放宽——阈值仍为 §19 的冻结值。**

通过 => CN 可用于搜索加速，入选最优参数仍须由 LSODA 复算。
失败 => 不调阈值，退回 LSODA。
"""

from __future__ import annotations

import argparse
import csv
import json
import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from scipy.stats import qmc

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT / "python"))

from oer_aem import mc_cn_bridge  # noqa: E402
from oer_aem.low_dim_fit import decode, default_bounds  # noqa: E402
from oer_aem.molecular_catalysis import (  # noqa: E402
    calculate_mc_steady_state, initialize_mc_system, simulate,
)

# ===== 预冻结阈值：正式运行后不得修改 =====
THRESHOLDS = {
    "total_nrmse": 0.01,        # 总电流 NRMSE <= 1%
    "dc_nrmse": 0.01,           # DC 分量 NRMSE <= 1%
    "tight_amp": 0.03,          # H2-H3 幅值相对误差 <= 3%
    "tight_phase": 0.05,        # H2-H3 相位误差 <= 0.05 rad
    "loose_amp": 0.10,          # H4 幅值相对误差 <= 10%
    "loose_phase": 0.15,        # H4 相位误差 <= 0.15 rad
    "peak_shift_V": 0.005,      # H3 包络峰位偏移 <= 5 mV
    "weak_channel_ratio": 0.02, # 2% 规则：通道级 + 通道内点级（见 docstring）
}
TIGHT_HARMONICS = (2, 3)
LOOSE_HARMONICS = (4,)

# 四组数据的实测扫描配置（由 low_dim_fit.load_truncated 得到）
DATASET_CONFIGS = (
    ("FT2", 5.008, 0.00975, 1.20, 34.5e-6),
    ("FT3", 5.008, 0.01951, 1.20, 16.9e-6),
    ("FT4", 0.999, 0.00390, 1.20, 28.9e-6),
    ("FT8", 5.008, 0.01756, 1.20, 30.8e-6),
)
E_FIT_HI = 1.65
OUT_POINTS_PER_CYCLE = 256


def _git_commit() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"],
                                       cwd=PROJECT, text=True).strip()
    except Exception:  # noqa: BLE001
        return "unknown"


def _dc_component(signal, points_per_cycle):
    kernel = np.ones(points_per_cycle) / points_per_cycle
    return np.convolve(signal, kernel, mode="same")


def _complex_harmonic(signal, t, harmonic, f0):
    spectrum = np.fft.rfft(signal)
    freqs = np.fft.rfftfreq(signal.size, t[1] - t[0])
    mask = np.abs(freqs - harmonic * f0) < 0.4 * f0
    filtered = np.zeros_like(spectrum)
    filtered[mask] = spectrum[mask]
    analytic = np.fft.irfft(filtered * 2.0, signal.size)
    hil = np.fft.irfft(filtered * 2.0 * -1j, signal.size)
    return analytic + 1j * hil


def _nrmse(a, b):
    denom = float(np.max(np.abs(b)) - np.min(np.abs(b))) or float(np.max(np.abs(b)))
    if denom <= 0:
        return np.inf
    return float(np.sqrt(np.mean((a - b) ** 2)) / denom)


def compare(name, f0, scan_rate, e_start, cdl, free, substeps, max_dt=None):
    total_time = (E_FIT_HI - e_start) / scan_rate
    n_out = int(round(total_time * f0 * OUT_POINTS_PER_CYCLE))
    t = np.linspace(0.0, total_time, n_out, endpoint=False)
    ppc = int(round(1.0 / (f0 * (t[1] - t[0]))))

    params = dict(free)
    params.update(E_start=e_start, v=scan_rate, dE=0.16, f=f0, Ru=10.0,
                  Cdl=cdl, A=1.0, alpha=0.5, total_time=total_time)

    _, i_lsoda, _ = simulate(dict(params, solver_backend="lsoda"), t)
    _, i_cn, _ = simulate(dict(params, solver_backend="cn",
                               cn_substeps=substeps, cn_max_dt=max_dt), t)
    # 参考解算不出来时该比较无从判定，单列一类，不记为 CN 失败
    if not np.all(np.isfinite(i_lsoda)):
        return {"dataset": name, "status": "REFERENCE_UNAVAILABLE"}
    if not np.all(np.isfinite(i_cn)):
        return {"dataset": name, "status": "CN_FAIL"}

    row = {"dataset": name, "status": "ok",
           "total_nrmse": _nrmse(i_cn, i_lsoda),
           "dc_nrmse": _nrmse(_dc_component(i_cn, ppc),
                              _dc_component(i_lsoda, ppc))}

    guard = int(0.08 * n_out)
    ref_amps = {}
    for h in TIGHT_HARMONICS + LOOSE_HARMONICS:
        ref_amps[h] = float(np.max(np.abs(_complex_harmonic(i_lsoda, t, h, f0))[guard:-guard]))
    strongest = max(ref_amps.values()) or 1.0

    e_dc = e_start + scan_rate * t
    for h in TIGHT_HARMONICS + LOOSE_HARMONICS:
        zr = _complex_harmonic(i_lsoda, t, h, f0)[guard:-guard]
        zc = _complex_harmonic(i_cn, t, h, f0)[guard:-guard]
        weak = ref_amps[h] < THRESHOLDS["weak_channel_ratio"] * strongest
        row[f"h{h}_weak"] = int(weak)
        # 幅值误差以通道峰值归一，本身已不会在零点放大
        row[f"h{h}_amp_err"] = float(np.max(np.abs(np.abs(zc) - np.abs(zr)))
                                     / max(ref_amps[h], 1e-30))
        # 相位只在有信号处评价（见模块 docstring）
        live = np.abs(zr) > THRESHOLDS["weak_channel_ratio"] * ref_amps[h]
        row[f"h{h}_live_fraction"] = float(live.mean())
        if live.any():
            phase_diff = np.angle(np.exp(1j * (np.angle(zc) - np.angle(zr))))
            row[f"h{h}_phase_err"] = float(np.max(np.abs(phase_diff[live])))
        else:
            row[f"h{h}_phase_err"] = 0.0
            row[f"h{h}_weak"] = 1
        if h == 3:
            eg = e_dc[guard:-guard]
            row["h3_peak_shift"] = float(abs(eg[int(np.argmax(np.abs(zc)))]
                                             - eg[int(np.argmax(np.abs(zr)))]))
    return row


def verdict(row):
    if row.get("status") == "REFERENCE_UNAVAILABLE":
        return []          # 无参考解，不判定（单独计数）
    if row.get("status") != "ok":
        return [row.get("status", "UNKNOWN")]
    fails = []
    if row["total_nrmse"] > THRESHOLDS["total_nrmse"]:
        fails.append(f"total_nrmse={row['total_nrmse']:.4f}")
    if row["dc_nrmse"] > THRESHOLDS["dc_nrmse"]:
        fails.append(f"dc_nrmse={row['dc_nrmse']:.4f}")
    for h in TIGHT_HARMONICS + LOOSE_HARMONICS:
        if row.get(f"h{h}_weak"):
            continue
        amp_lim = THRESHOLDS["tight_amp"] if h in TIGHT_HARMONICS else THRESHOLDS["loose_amp"]
        ph_lim = THRESHOLDS["tight_phase"] if h in TIGHT_HARMONICS else THRESHOLDS["loose_phase"]
        if row[f"h{h}_amp_err"] > amp_lim:
            fails.append(f"h{h}_amp={row[f'h{h}_amp_err']:.4f}")
        if row[f"h{h}_phase_err"] > ph_lim:
            fails.append(f"h{h}_phase={row[f'h{h}_phase_err']:.4f}")
    if row.get("h3_peak_shift", 0.0) > THRESHOLDS["peak_shift_V"]:
        fails.append(f"h3_peak_shift={row['h3_peak_shift']:.4f}")
    return fails


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--samples", type=int, default=24)
    parser.add_argument("--substeps", type=int, default=1)
    parser.add_argument("--max-dt", type=float, default=None,
                        help="CN 绝对步长上限（秒）。按绝对时间设定，"
                             "而非每周期点数——见 mc_cn_bridge.required_substeps")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--outdir", default="results/solver_gate")
    args = parser.parse_args()

    if not mc_cn_bridge.is_available():
        print("CN 动态库不存在，先运行 scripts/build_mc_cn.sh", file=sys.stderr)
        return 2

    lower, upper = default_bounds()
    sampler = qmc.Sobol(d=len(lower), scramble=True, seed=args.seed)
    units = sampler.random(args.samples)

    rows, failures, no_reference = [], [], []
    for idx, unit in enumerate(units):
        free = decode(unit, lower, upper)
        for name, f0, v, e_start, cdl in DATASET_CONFIGS:
            row = compare(name, f0, v, e_start, cdl, free,
                          args.substeps, args.max_dt)
            row["sample"] = idx
            row.update({f"p_{k}": v2 for k, v2 in free.items()})
            fails = verdict(row)
            row["verdict"] = "PASS" if not fails else "FAIL"
            row["fail_reason"] = ";".join(fails)
            rows.append(row)
            if row.get("status") == "REFERENCE_UNAVAILABLE":
                no_reference.append(row)
            elif fails:
                failures.append(row)
        print(f"  sample {idx+1}/{args.samples} done", flush=True)

    outdir = PROJECT / args.outdir
    outdir.mkdir(parents=True, exist_ok=True)
    fields = sorted({k for r in rows for k in r})
    with open(outdir / "solver_equivalence.csv", "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

    decision = "PASS" if not failures else "FAIL"
    manifest = {
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "commit": _git_commit(), "hostname": platform.node(),
        "interpreter": sys.executable, "worktree": str(PROJECT),
        "library": mc_cn_bridge.library_path(),
        "numpy": np.__version__, "scipy": __import__("scipy").__version__,
        "thresholds_frozen": THRESHOLDS,
        "samples": args.samples, "substeps": args.substeps,
        "max_dt": args.max_dt, "seed": args.seed,
        "datasets": [d[0] for d in DATASET_CONFIGS],
        "n_comparisons": len(rows), "n_failures": len(failures),
        "n_reference_unavailable": len(no_reference),
        "decision": decision,
    }
    with open(outdir / "gate_manifest.json", "w") as fh:
        json.dump(manifest, fh, indent=2, ensure_ascii=False)

    print(f"\n{len(rows)} comparisons, {len(failures)} failures, "
          f"{len(no_reference)} reference-unavailable -> {decision}")
    for row in failures[:12]:
        print(f"  FAIL sample={row['sample']} {row['dataset']}: {row['fail_reason']}")
    return 0 if decision == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
