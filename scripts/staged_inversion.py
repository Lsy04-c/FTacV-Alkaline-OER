#!/usr/bin/env python3
"""分层参数反演 —— 按实验条件→预氧化→AEM机理的顺序逐步约束参数。

用法：
    cd /Users/liushiyu/OER-FTAcV
    .venv/bin/python scripts/staged_inversion.py

输出：
    results/staged_inversion/staged_summary.md
    results/staged_inversion/<dataset>_layer3_fit.png
"""

import sys, os, json, copy
from pathlib import Path
from typing import Dict, Any, List, Optional

import numpy as np

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT))
sys.path.insert(0, str(PROJECT / "python"))
sys.path.insert(0, str(PROJECT / "web" / "backend"))

from main import _analyze_ftacv_data
from oer_aem.inversion import (
    InversionConfig, TPEInverter,
    encode_params, DEFAULT_PARAM_SPECS,
)
from oer_aem.defaults import initialize_oer_parameters


def _load_numeric(filename: str, min_cols=3):
    """容错加载：跳过非数值表头行，支持空格或逗号分隔。"""
    raw = (RAW_DIR / filename).read_text()
    lines = raw.strip().splitlines()
    numeric_lines = []
    for line in lines:
        parts = line.replace(",", " ").split()
        try:
            vals = [float(x) for x in parts[:min_cols]]
            if len(vals) >= min_cols:
                numeric_lines.append(vals)
            elif len(vals) >= 2:
                numeric_lines.append(vals + [0.0])
        except ValueError:
            continue
    return np.array(numeric_lines)

OUT_DIR = PROJECT / "results" / "staged_inversion"
OUT_DIR.mkdir(parents=True, exist_ok=True)
RAW_DIR = PROJECT / "data" / "raw"


def _free_specs_excluding(fixed: Dict[str, float]):
    """Return optimizer specs after removing parameters fixed by experiment."""
    fixed_names = set(fixed)
    return tuple(spec for spec in DEFAULT_PARAM_SPECS if spec[0] not in fixed_names)


def _preox_specs(preox_bounds: Dict[str, List[float]], fixed: Dict[str, float]):
    """把 Layer 2 的预氧化边界转成 optimizer specs。

    ``E0_pre`` 走线性尺度，``k0_pre`` 走 log10 —— 与 DEFAULT_PARAM_SPECS 中
    速率常数的处理保持一致。跨参数比较 CV 时必须记住这两种尺度不可比，
    这正是 docs/项目纠错.md 第 10 条撤回旧稳定性结论的原因。
    """
    specs = []
    for name, bounds in preox_bounds.items():
        if name in fixed:
            continue
        if name.startswith("k0"):
            specs.append((name, "log10", float(np.log10(bounds[0])),
                          float(np.log10(bounds[1]))))
        else:
            specs.append((name, "linear", float(bounds[0]), float(bounds[1])))
    return tuple(specs)


# ============================================================
# Layer 1：实验条件参数（固定，来自标定或多数据集平均）
# ============================================================
def layer1_experimental_params(quality_data: List[Dict]) -> Dict[str, float]:
    """从数据质量报告提取 Cdl、Ru、A、gamma 的合理固定值。"""
    cdl_vals = []
    for r in quality_data:
        if r.get("type") == "FTacV" and r.get("success"):
            cdl_str = r.get("CdlA", "FAIL").replace(" µF", "")
            try: cdl_vals.append(float(cdl_str))
            except: pass
    avg_cdl = np.mean(cdl_vals) * 1e-6 if cdl_vals else 30e-6  # F/cm²

    # gamma 文献范围：1e-9 (Moysiadou 2020 表面Co密度) ~ 1e-8 (上限)
    gamma_fixed = 3e-9  # 取文献范围中值作为固定值
    return {
        "Cdl": float(avg_cdl),
        "Ru": 10.0,
        "A": 1.0,
        "gamma": gamma_fixed,
    }


# ============================================================
# Layer 2：预氧化参数（窄边界约束）
# ============================================================
def layer2_preox_bounds() -> Dict[str, List[float]]:
    """E0_pre、k0_pre 的窄边界。E0_pre 来自 Moysiadou 2020（1.50V），
    k0_pre 来自 Bonke 2016（CoOx k0cat≈90-325 s⁻¹）。"""
    return {
        "E0_pre": [1.40, 1.55],
        "k0_pre": [50.0, 800.0],
    }


# ============================================================
# Layer 3：AEM 机理参数（TPE 反演）
# ============================================================
def layer3_invert_aem(
    dataset_name: str,
    fixed: Dict[str, float],
    preox_bounds: Dict[str, List[float]],
    n_trials: int = 100,
) -> Dict[str, Any]:
    """对单个数据集运行 Layer 2+3 联合 TPE 反演。"""

    # 加载数据
    rows = _load_numeric(dataset_name)
    analysis = _analyze_ftacv_data(rows)
    hq = analysis["harmonic_quality"]
    fit_h = hq["fit_harmonics"]

    # 构建 InversionConfig
    cfg = InversionConfig(
        E_start=analysis["meta"]["E_start"],
        E_end=analysis["meta"]["E_end"],
        f=analysis["meta"]["f"],
        dE=analysis["meta"]["dE"],
        n_points=4096,
        points_per_cycle=128,
        feature_grid_size=200,
        fixed_params=tuple(fixed.items()),
    )
    # 更新 fit_harmonics 为实验判定值
    cfg = InversionConfig(
        E_start=cfg.E_start, E_end=cfg.E_end,
        f=cfg.f, dE=cfg.dE,
        n_points=cfg.n_points, points_per_cycle=cfg.points_per_cycle,
        feature_grid_size=cfg.feature_grid_size,
        fixed_params=tuple(fixed.items()),
        fit_harmonics=tuple(fit_h),
    )

    # 构建反演目标（直接插值到 e_grid）
    tdc_raw = np.asarray(analysis["tdc"])
    dc_raw = np.asarray(analysis["dc"])
    harm_raw = [np.asarray(h) for h in analysis["harmonics"]]
    order = np.argsort(tdc_raw)
    x = tdc_raw[order]; _, keep = np.unique(x, return_index=True); x = x[keep]
    # Tafel 提取失败时必须留空，不能回退到写死的 60 mV/dec。
    # 四组数据的 Tafel 提取全部是 FAIL 或 0 mV/dec（见
    # results/data_quality/data_quality_summary.md），旧的兜底值让四次独立
    # 反演都在拟合同一个伪造目标，既污染目标函数，又人为拉近了各数据集的
    # 最优参数。InversionObjective 已支持 target["tafel"] is None（跳过该项）。
    tafel_raw = analysis.get("calib", {}).get("tafel", {}).get("b")
    tafel_val = (float(tafel_raw)
                 if isinstance(tafel_raw, (int, float)) and tafel_raw > 0
                 else None)
    target = {
        "dc": np.interp(cfg.e_grid, x, dc_raw[order][keep]),
        "harm": [np.interp(cfg.e_grid, x, h[order][keep]) for h in harm_raw],
        "tafel": tafel_val,
        "e_grid": cfg.e_grid,
    }

    # 初始参数：来自 defaults
    base = initialize_oer_parameters()
    base.update(fixed)
    base["E0_pre"] = 1.50
    base["k0_pre"] = 300.0

    # TPE 反演。Layer 2 的预氧化边界此前只被计算、从未被读取，
    # E0_pre/k0_pre 实际是四组数据共用的硬编码常数，报告中的
    # "Layer 2" 表格因此是装饰性的。现在把它们真正接进 optimizer specs。
    specs = _free_specs_excluding(fixed) + _preox_specs(preox_bounds, fixed)
    result = TPEInverter(config=cfg, specs=specs, seed=42, initial_params=base).run(target, n_trials=n_trials)

    return {
        "dataset": dataset_name,
        "fit_harmonics": fit_h,
        "best_value": result.best_value,
        "best_params": result.best_params,
        "fit_quality": result.fit_quality,
        "n_trials": result.n_trials,
        "n_forward": result.n_forward,
    }


# ============================================================
# Layer 4：跨数据稳定性诊断
# ============================================================
def layer4_cross_validation(results: List[Dict]) -> Dict[str, Any]:
    """汇总多个数据集的反演结果，计算参数跨数据稳定性。"""
    from collections import defaultdict
    param_vals = defaultdict(list)
    for r in results:
        bp = r.get("best_params", {})
        for k, v in bp.items():
            param_vals[k].append(v)

    stability = {}
    for k, vals in param_vals.items():
        arr = np.array(vals, dtype=float)
        mu, sd = float(np.mean(arr)), float(np.std(arr))
        cv = sd / max(abs(mu), 1e-30)
        if cv < 0.1: level = "stable"
        elif cv < 0.3: level = "moderate"
        elif cv < 0.5: level = "unstable"
        else: level = "unreliable"
        stability[k] = {"mean": mu, "std": sd, "cv": cv, "level": level}

    return stability


# ============================================================
# 主流程
# ============================================================
def main():
    # ---- 读取质量数据 ----
    import csv
    quality_csv = PROJECT / "results" / "data_quality" / "data_quality_summary.csv"
    quality_data = list(csv.DictReader(open(quality_csv)))
    ftacv_files = [r for r in quality_data if r["type"] == "FTacV" and r["success"] == "True"]

    # ---- Layer 1 ----
    fixed = layer1_experimental_params(quality_data)
    print(f"Layer 1 — 实验条件参数固定:")
    for k, v in fixed.items():
        print(f"  {k} = {v:.3e}" if v < 0.01 else f"  {k} = {v:.4g}")

    # ---- Layer 2 ----
    preox = layer2_preox_bounds()
    print(f"\nLayer 2 — 预氧化参数边界:")
    for k, v in preox.items():
        print(f"  {k} ∈ [{v[0]:.2f}, {v[1]:.2f}]")

    # ---- Layer 3（对每个可拟合的 FTacV 数据集） ----
    print(f"\nLayer 3 — AEM 机理参数 TPE 反演 ({len(ftacv_files)} 组数据):")
    layer3_results = []
    for r in ftacv_files:
        name = r["filename"]
        fit_h_str = r["fit_harmonics"]
        print(f"  {name}  fit_h={fit_h_str}  n_trials=50 ...", end=" ", flush=True)
        try:
            l3 = layer3_invert_aem(name, fixed, preox, n_trials=50)
            layer3_results.append(l3)
            q = l3["fit_quality"]
            print(f"best={l3['best_value']:.4f}  {q['level']}")
        except Exception as e:
            print(f"FAIL: {e}")

    if not layer3_results:
        print("No successful inversions. Exiting.")
        return

    # ---- Layer 4 ----
    stability = layer4_cross_validation(layer3_results)
    print(f"\nLayer 4 — 跨数据参数稳定性:")
    for k in sorted(stability.keys()):
        s = stability[k]
        print(f"  {k:20s} mean={s['mean']:.4g}  std={s['std']:.4g}  cv={s['cv']:.3f}  [{s['level']}]")

    # ---- 输出报告 ----
    md_path = OUT_DIR / "staged_summary.md"
    with open(md_path, "w") as f:
        f.write("# Staged Inversion Report\n\n")
        f.write("## Layer 1 — Fixed Experimental Parameters\n\n")
        f.write("| Param | Value |\n|-------|-------|\n")
        for k, v in fixed.items():
            f.write(f"| {k} | {v:.4g} |\n")

        f.write("\n## Layer 2 — Pre-Oxidation Bounds\n\n")
        f.write("| Param | Lower | Upper |\n|-------|-------|-------|\n")
        for k, v in preox.items():
            f.write(f"| {k} | {v[0]:.3f} | {v[1]:.3f} |\n")

        f.write("\n## Layer 3 — AEM Inversion Results\n\n")
        f.write("| Dataset | Fit H | Best Value | Level | n_forward |\n")
        f.write("|---------|-------|------------|-------|----------|\n")
        for r in layer3_results:
            q = r["fit_quality"]
            f.write(f"| {r['dataset']} | {r['fit_harmonics']} | {r['best_value']:.4f} | {q['level']} | {r['n_forward']} |\n")

        f.write("\n## Layer 4 — Cross-Dataset Parameter Stability\n\n")
        f.write("| Param | Mean | Std | CV | Level |\n")
        f.write("|-------|------|-----|-----|-------|\n")
        for k in sorted(stability.keys()):
            s = stability[k]
            f.write(f"| {k} | {s['mean']:.4g} | {s['std']:.4g} | {s['cv']:.3f} | {s['level']} |\n")

        f.write("\n## Diagnostics\n\n")
        fixed_params_for_diag = {k: v for k, v in stability.items() if v['cv'] < 0.3}
        unstable_params = {k: v for k, v in stability.items() if v['cv'] >= 0.3}
        if unstable_params:
            f.write("**Unstable parameters (high cross-dataset variance):**\n")
            for k, s in unstable_params.items():
                f.write(f"- `{k}`: CV={s['cv']:.2f} — likely coupled or unresolvable\n")
        if fixed_params_for_diag:
            f.write("**Stable parameters (consistent across datasets):**\n")
            for k, s in fixed_params_for_diag.items():
                f.write(f"- `{k}`: CV={s['cv']:.2f}\n")

    print(f"\nReport → {md_path}")
    print("Done.")


if __name__ == "__main__":
    main()
