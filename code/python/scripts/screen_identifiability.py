#!/usr/bin/env python3
"""可辨识性剖面工具（A 报告约定 + B profile 工具）。

对指定参数做 1-D 目标函数剖面（其余参数固定 truth），自动分类：
  - sharp:      唯一最小值在 truth 附近，窄
  - one-sided:  一侧陡升、另一侧平（只有下/上界）
  - flat:       宽平台，参数不可辨

报告约定（k0_1 sloppy 方向）：
  k0_1 若为 one-sided/flat → 标 non-identifiable，只报下界 + 与 G_OH 的 stiff 组合，
  不报点估计。

用法:
  python screen_identifiability.py --params k0_1,k0_pre --mode legacy [--smoke]
  python screen_identifiability.py --params k0_1,k0_pre --fullres --out report.json
"""
import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "python" / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "python" / "scripts"))

from oer_aem.inversion import (DEFAULT_PARAM_SPECS, InversionObjective,
                               encode_params)
from oer_aem.recovery import truth_library
from run_synthetic_recovery import build_recovery_problem, make_synthetic_target

NOISE_FRACTION = 0.001495726085983469
TARGET_SEED = 1443515106
K0PRE_DEFAULT = 500.0
# 默认 profile 的参数 + 扫描点数
DEFAULT_PARAMS = ["k0_1", "k0_2", "k0_3", "G_OH", "G_O", "scaling_OOH_OH", "k0_pre"]
SPEC_PARAMS = [s[0] for s in DEFAULT_PARAM_SPECS]  # 在搜索盒里的参数

# 固定参数（不在 SPEC 里）的扫描范围：log10
FIXED_SWEEPS = {"k0_pre": (-2.0, 5.0)}


def _spec_range(name):
    for s in DEFAULT_PARAM_SPECS:
        if s[0] == name:
            kind, lo, hi = s[1], s[2], s[3]
            return kind, lo, hi
    raise KeyError(name)


def _sweep_values(name, truth_val, kind, lo, hi, n=15):
    """扫描点：log10 参数在 log 空间；linear 在线性空间；固定参数用 FIXED_SWEEPS。"""
    if name in FIXED_SWEEPS:
        flo, fhi = FIXED_SWEEPS[name]
        vals = [10.0 ** v for v in np.linspace(flo, fhi, n)]
        extra = [truth_val]
    elif kind == "log10":
        vals = [10.0 ** (lo + (hi - lo) * t) for t in np.linspace(0, 1, n)]
        extra = [truth_val * f for f in (1.0, 0.1, 0.3, 3.0, 10.0)]
    else:
        vals = [lo + (hi - lo) * t for t in np.linspace(0, 1, n)]
        extra = [truth_val + d for d in (0.0, -0.2, -0.05, 0.05, 0.2)]
    return sorted(set([round(v, 6) for v in list(vals) + extra]))


def _profile_param(name, truth, free_specs, base_job, base_config, target, smoke):
    """返回 {value: obj} 剖面 + 分类信息。"""
    is_spec = name in SPEC_PARAMS
    # 其余自由参数在 truth 的 x
    x_truth = encode_params(truth, free_specs)
    kind, lo, hi = _spec_range(name) if is_spec else ("log10", None, None)
    truth_val = truth.get(name, K0PRE_DEFAULT if name == "k0_pre" else np.nan)
    sweep = _sweep_values(name, truth_val, kind, lo, hi)

    rows = []
    for v in sweep:
        tp = dict(base_job["truth_params"])
        tp[name] = v
        j = dict(base_job); j["truth_params"] = tp
        cfg, _ = build_recovery_problem(j, smoke=smoke)
        val = float(InversionObjective(target, cfg, free_specs)(x_truth))
        rows.append((v, val))
    return rows, truth_val


def _classify(rows, truth_val):
    floor = min(v for _, v in rows)
    floor_v = next(v for v, o in rows if abs(o - floor) < 1e-12)
    # obj <= 2*floor 的区域（用 truth 附近 floor 更稳：取 truth 点 obj）
    truth_obj = next(o for v, o in rows if abs(v - truth_val) / max(truth_val, 1e-30) < 1e-6)
    within = [v for v, o in rows if o <= 2.0 * truth_obj]
    lo_2x, hi_2x = (min(within), max(within)) if within else (np.nan, np.nan)
    # log 空间宽度
    if lo_2x is not np.nan and lo_2x > 0:
        width = float(np.log10(hi_2x / lo_2x))
    else:
        width = float(hi_2x - lo_2x)
    # 分类
    lo_edge = min(v for v, _ in rows); hi_edge = max(v for v, _ in rows)
    if np.isnan(lo_2x):
        cls = "unidentifiable"
    elif abs(lo_2x - lo_edge) / lo_edge < 0.05 or abs(hi_2x - hi_edge) / hi_edge < 0.05:
        # 平带触到扫描边界 → one-sided（只有一侧有界）
        if abs(lo_2x - lo_edge) / lo_edge < 0.05 and abs(hi_2x - hi_edge) / hi_edge < 0.05:
            cls = "flat"
        else:
            cls = "one-sided"
    elif width <= 0.5:
        cls = "sharp"
    else:
        cls = "one-sided"
    return {
        "floor_obj": floor,
        "truth_obj": truth_obj,
        "within_2x": [lo_2x, hi_2x],
        "log10_width_decades": round(width, 3) if lo_2x > 0 else None,
        "classification": cls,
        "truth_inside_2x": lo_2x <= truth_val <= hi_2x if not np.isnan(lo_2x) else False,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--params", default=",".join(DEFAULT_PARAMS), help="要剖面的参数列表")
    ap.add_argument("--mode", default="legacy", choices=["legacy", "complex_snr", "lockin_only", "hybrid"])
    ap.add_argument("--smoke", action="store_true", help="smoke 分辨率（仅自检）")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    truth = next(t for t in truth_library(DEFAULT_PARAM_SPECS) if t["truth_id"] == "mixed_b")["parameters"]
    params_list = [p.strip() for p in args.params.split(",") if p.strip()]

    report = {"mode": args.mode, "smoke": args.smoke, "truth": truth,
              "params": {}, "convention": {}}
    for name in params_list:
        # 构建 job：把 name 从自由集移除（放进 fixed_params），便于扫描
        free_names = [s for s in SPEC_PARAMS if s != name]
        tp = dict(truth)
        if name == "k0_pre":
            tp["k0_pre"] = K0PRE_DEFAULT
        job = {"feature_mode": args.mode, "truth_id": "mixed_b", "truth_params": tp,
               "noise_fraction": NOISE_FRACTION, "seed": 7, "target_seed": TARGET_SEED,
               "free_parameters": free_names, "backend": "lsoda"}
        base_config, free_specs = build_recovery_problem(job, smoke=args.smoke)
        target = make_synthetic_target(truth, config=base_config,
                                       noise_fraction=NOISE_FRACTION, seed=TARGET_SEED)
        rows, truth_val = _profile_param(name, truth, free_specs, job, base_config, target, args.smoke)
        info = _classify(rows, truth_val)
        report["params"][name] = {
            "truth": truth_val,
            "classification": info["classification"],
            "floor_obj": info["floor_obj"],
            "truth_obj": info["truth_obj"],
            "within_2x": info["within_2x"],
            "log10_width_decades": info["log10_width_decades"],
            "curve": [[v, o] for v, o in rows],
        }
        print(f"{name:<16} cls={info['classification']:<12} truth={truth_val:.4g} "
              f"floor={info['floor_obj']:.5f} within2x={info['within_2x']}")

    # A 报告约定：k0_1 sloppy 方向标记
    if "k0_1" in report["params"]:
        cls = report["params"]["k0_1"]["classification"]
        report["convention"]["k0_1"] = {
            "non_identifiable": cls in ("one-sided", "flat", "unidentifiable"),
            "note": "k0_1 只报下界（~within_2x 下界）+ 与 G_OH 的 stiff 组合，不报点估计",
        }
    if args.out:
        Path(args.out).write_text(json.dumps(report, indent=2, default=float))


if __name__ == "__main__":
    main()
