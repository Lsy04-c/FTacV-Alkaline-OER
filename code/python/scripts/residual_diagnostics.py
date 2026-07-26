#!/usr/bin/env python3
"""Stage 2: 定位 poor fit 来源 —— 对每组 FTacV 数据做残差诊断。

用法：
    cd /Users/liushiyu/OER-FTAcV
    .venv/bin/python code/python/scripts/residual_diagnostics.py
    .venv/bin/python code/python/scripts/residual_diagnostics.py \
        --output results/formal/architecture_validation/residual_contract.csv

输出：
    results/diagnostics/model_gap/model_gap_summary.md
    results/formal/architecture_validation/residual_contract.csv
"""

import argparse
import csv
import sys
from pathlib import Path
from typing import Dict, Any

import numpy as np

PROJECT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT))
sys.path.insert(0, str(PROJECT / "code" / "python" / "src"))
sys.path.insert(0, str(PROJECT / "code" / "web" / "backend"))

from main import _analyze_ftacv_data
from oer_aem.data_contract import normalize_by_max_abs, residual_on_grid
from oer_aem.inversion import (
    InversionConfig,
    TPEInverter,
    DEFAULT_PARAM_SPECS,
    match_experimental_sampling,
)
from oer_aem.defaults import initialize_oer_parameters

RAW_DIR = PROJECT / "data" / "raw"
OUT_DIR = PROJECT / "results" / "model_gap"
OUT_DIR.mkdir(parents=True, exist_ok=True)


def _free_specs_excluding(fixed: Dict[str, float]):
    """Return optimizer specs after removing parameters fixed by experiment."""
    fixed_names = set(fixed)
    return tuple(spec for spec in DEFAULT_PARAM_SPECS if spec[0] not in fixed_names)


def _load_numeric(filename: str, min_cols=3):
    raw = (RAW_DIR / filename).read_text()
    lines = raw.strip().splitlines()
    numeric_lines = []
    for line in lines:
        parts = line.replace(",", " ").split()
        try:
            vals = [float(x) for x in parts[:min_cols]]
            if len(vals) >= min_cols: numeric_lines.append(vals)
            elif len(vals) >= 2: numeric_lines.append(vals + [0.0])
        except ValueError: continue
    return np.array(numeric_lines)


def run_forward_with_params(params, analysis):
    """用给定参数跑正演，保留原始模拟网格并对齐谐波诊断。"""
    from oer_aem.physics import OERPhysics
    from oer_aem.signal import OERSignal
    from oer_aem.thermodynamics import apply_alkaline_aem
    import copy

    p = copy.deepcopy(params)
    p = apply_alkaline_aem(p)
    p = OERPhysics.initialize_system(p)

    t, y, E_act, i_tot = OERPhysics.solve_ode_system(p)
    df = OERSignal.safe_df(t)
    proc = OERSignal.process_current(i_tot, df, p)
    sim_dc = normalize_by_max_abs(np.asarray(proc[:, 0]))
    sim_harm = [
        normalize_by_max_abs(np.asarray(proc[:, k + 1])) for k in range(7)
    ]
    sim_tdc = p['E_start'] + t * p['v']

    # 插值到实验电位网格
    exp_tdc = np.asarray(analysis['tdc'])
    exp_dc = np.asarray(analysis['dc'])
    exp_harm = [np.asarray(h) for h in analysis['harmonics']]

    order = np.argsort(sim_tdc)
    x = sim_tdc[order]; _, keep = np.unique(x, return_index=True); x = x[keep]
    sim_dc_interp = np.interp(exp_tdc, x, sim_dc[order][keep])
    harms_interp = [np.interp(exp_tdc, x, h[order][keep]) for h in sim_harm]

    return (
        exp_tdc,
        exp_dc,
        exp_harm,
        x,
        sim_dc[order][keep],
        sim_dc_interp,
        harms_interp,
    )


def _grid_residual_row(
    filename: str,
    grid_name: str,
    common_e: np.ndarray,
    exp_e: np.ndarray,
    exp_i: np.ndarray,
    sim_e: np.ndarray,
    sim_i: np.ndarray,
) -> Dict[str, Any]:
    """Summarize normalized experiment-minus-simulation residuals on one grid."""
    residual = residual_on_grid(exp_e, exp_i, sim_e, sim_i, common_e)
    exp_on_grid = np.interp(common_e, exp_e, exp_i)
    normalized = residual / max(float(np.max(np.abs(exp_on_grid))), 1e-30)
    low_edge, high_edge = np.percentile(common_e, [20.0, 80.0])
    masks = (
        common_e < low_edge,
        (common_e >= low_edge) & (common_e < high_edge),
        common_e >= high_edge,
    )
    return {
        "dataset": filename,
        "grid": grid_name,
        "n_points": int(common_e.size),
        "bias_lo": float(np.mean(normalized[masks[0]])),
        "bias_mid": float(np.mean(normalized[masks[1]])),
        "bias_hi": float(np.mean(normalized[masks[2]])),
        "sign_convention": "experiment - simulation",
    }


def diagnose_dataset(filename: str, n_trials=30) -> Dict[str, Any]:
    """对单个数据集运行反演 + 残差诊断。"""
    rows = _load_numeric(filename)
    analysis = _analyze_ftacv_data(rows)
    hq = analysis['harmonic_quality']
    fit_h = hq['fit_harmonics']

    base = initialize_oer_parameters()
    base['gamma'] = 3e-9
    fixed = {'Cdl': float(base['Cdl']), 'Ru': float(base['Ru']),
             'A': float(base['A']), 'gamma': float(base['gamma'])}

    n_points, points_per_cycle = match_experimental_sampling(
        float(analysis["meta"]["duration"]),
        float(analysis["meta"]["f"]),
        points_per_cycle=32,
    )
    cfg = InversionConfig(
        E_start=analysis['meta']['E_start'], E_end=analysis['meta']['E_end'],
        f=analysis['meta']['f'], dE=analysis['meta']['dE'],
        n_points=n_points, points_per_cycle=points_per_cycle, feature_grid_size=200,
        fixed_params=tuple(fixed.items()), fit_harmonics=tuple(fit_h),
    )

    # Build target
    tdc_raw = np.asarray(analysis['tdc'])
    dc_raw = np.asarray(analysis['dc'])
    harm_raw = [np.asarray(h) for h in analysis['harmonics']]
    order = np.argsort(tdc_raw)
    x = tdc_raw[order]; _, keep = np.unique(x, return_index=True); x = x[keep]
    target = {
        'dc': np.interp(cfg.e_grid, x, dc_raw[order][keep]),
        'harm': [np.interp(cfg.e_grid, x, h[order][keep]) for h in harm_raw],
        'tafel': 60.0, 'e_grid': cfg.e_grid,
    }

    specs = _free_specs_excluding(fixed)
    result = TPEInverter(config=cfg, specs=specs, seed=42, initial_params=base).run(target, n_trials=n_trials)

    # 用最优参数跑正演
    best_p = result.best_params
    best_p.update(fixed)
    best_p['E0_pre'] = 1.50
    best_p['k0_pre'] = 300.0
    best_p['E_start'] = cfg.E_start; best_p['E_end'] = cfg.E_end
    best_p['f'] = cfg.f; best_p['dE'] = cfg.dE
    best_p['n_points'] = cfg.n_points; best_p['points_per_cycle'] = cfg.points_per_cycle
    best_p['total_time'] = cfg.total_time
    best_p['v'] = cfg.scan_rate
    best_p['omega'] = 2 * np.pi * cfg.f
    best_p['t_span'] = np.linspace(0, cfg.total_time, cfg.n_points)

    (
        exp_tdc,
        exp_dc,
        exp_harm,
        sim_e,
        sim_dc_native,
        sim_dc,
        sim_harm,
    ) = run_forward_with_params(best_p, analysis)

    # 完整实验网格和裁剪反演网格共享同一插值及残差符号契约。
    exp_order = np.argsort(exp_tdc)
    exp_unique, exp_keep = np.unique(exp_tdc[exp_order], return_index=True)
    exp_dc_unique = exp_dc[exp_order][exp_keep]
    grid_rows = [
        _grid_residual_row(
            filename,
            "full",
            exp_unique,
            exp_unique,
            exp_dc_unique,
            sim_e,
            sim_dc_native,
        ),
        _grid_residual_row(
            filename,
            "trimmed",
            cfg.e_grid,
            exp_unique,
            exp_dc_unique,
            sim_e,
            sim_dc_native,
        ),
    ]
    experimental_scan_rate = float(analysis["meta"]["v"])
    scan_rate_relative_error = abs(cfg.scan_rate - experimental_scan_rate) / max(
        abs(experimental_scan_rate), 1e-30
    )
    if scan_rate_relative_error > 5e-4:
        raise RuntimeError(
            f"{filename}: simulation scan rate mismatch "
            f"({scan_rate_relative_error:.6g})"
        )
    for row in grid_rows:
        row.update(
            {
                "simulation_n_points": cfg.n_points,
                "points_per_cycle": cfg.points_per_cycle,
                "fit_harmonics": ";".join(map(str, cfg.fit_harmonics)),
                "fixed_params": ";".join(
                    f"{name}={value:g}" for name, value in cfg.fixed_params
                ),
                "experimental_duration_s": float(analysis["meta"]["duration"]),
                "simulated_duration_s": cfg.total_time,
                "experimental_scan_rate_v_s": experimental_scan_rate,
                "simulated_scan_rate_v_s": cfg.scan_rate,
                "scan_rate_relative_error": scan_rate_relative_error,
            }
        )

    dc_resid = residual_on_grid(
        exp_unique,
        exp_dc_unique,
        sim_e,
        sim_dc_native,
        exp_tdc,
    ) / max(np.max(np.abs(exp_dc)), 1e-30)
    h1_resid = (exp_harm[0] - sim_harm[0]) / max(np.max(np.abs(exp_harm[0])), 1e-30)

    # 分段统计
    e = exp_tdc
    lo = e < np.percentile(e, 20)
    mid = (e >= np.percentile(e, 20)) & (e < np.percentile(e, 80))
    hi = e >= np.percentile(e, 80)

    return {
        'filename': filename, 'best_value': result.best_value,
        'fit_quality': result.fit_quality,
        'dc_resid': dc_resid.tolist(), 'h1_resid': h1_resid.tolist(),
        'exp_tdc': e.tolist(), 'exp_dc': exp_dc.tolist(), 'sim_dc': sim_dc.tolist(),
        'dc_bias_lo': float(np.mean(dc_resid[lo])),
        'dc_bias_mid': float(np.mean(dc_resid[mid])),
        'dc_bias_hi': float(np.mean(dc_resid[hi])),
        'grid_rows': grid_rows,
        'onset_offset': _onset_diff(exp_tdc, exp_dc, sim_dc),
        'h1_peak_shift': _peak_shift(exp_tdc, exp_harm[0], sim_harm[0]),
        'h2_peak_shift': _peak_shift(exp_tdc, exp_harm[1], sim_harm[1]),
    }


def _onset_diff(tdc, exp_dc, sim_dc):
    """DC 包络达 5% 峰值的电位差（模拟 - 实验）。"""
    thresh = 0.05
    mx_e = max(np.max(np.abs(exp_dc)), 1e-30)
    mx_s = max(np.max(np.abs(sim_dc)), 1e-30)
    ie = np.argmax(exp_dc >= mx_e * thresh) if np.any(exp_dc >= mx_e * thresh) else 0
    si = np.argmax(sim_dc >= mx_s * thresh) if np.any(sim_dc >= mx_s * thresh) else 0
    return float(tdc[si] - tdc[ie]) if ie > 0 and si > 0 else 0.0


def _peak_shift(tdc, exp_h, sim_h):
    """谐波峰位电位差（模拟 - 实验）。"""
    ie = int(np.argmax(np.abs(exp_h)))
    si = int(np.argmax(np.abs(sim_h)))
    return float(tdc[si] - tdc[ie])


def _classify_residual(diag: Dict) -> str:
    """根据残差形态分类偏差来源。"""
    reasons = []
    if abs(diag['dc_bias_lo']) > 0.3:
        reasons.append('低电位基线偏移 → 基底背景/Cdl')
    if abs(diag['dc_bias_hi']) > 0.3:
        reasons.append('高电流段偏差 → Ru/传质/气泡')
    if abs(diag['onset_offset']) > 0.05:
        reasons.append(f"onset错位({diag['onset_offset']:+.2f}V) → E0_pre/预氧化")
    if abs(diag['h1_peak_shift']) > 0.03:
        reasons.append(f"H1峰位偏移({diag['h1_peak_shift']:+.3f}V)")
    if abs(diag['h2_peak_shift']) > 0.03:
        reasons.append(f"H2峰位偏移({diag['h2_peak_shift']:+.3f}V)")
    return '; '.join(reasons) if reasons else '偏差较小，需进一步检查谐波残差形态'


def _write_contract_csv(path: Path, diagnostics: list[Dict[str, Any]]) -> None:
    """Write the machine-readable full/trimmed residual contract."""
    rows = [row for diagnostic in diagnostics for row in diagnostic["grid_rows"]]
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    try:
        with temporary.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=[
                    "dataset",
                    "grid",
                    "n_points",
                    "bias_lo",
                    "bias_mid",
                    "bias_hi",
                    "sign_convention",
                    "simulation_n_points",
                    "points_per_cycle",
                    "fit_harmonics",
                    "fixed_params",
                    "experimental_duration_s",
                    "simulated_duration_s",
                    "experimental_scan_rate_v_s",
                    "simulated_scan_rate_v_s",
                    "scan_rate_relative_error",
                ],
                lineterminator="\n",
            )
            writer.writeheader()
            writer.writerows(rows)
        temporary.replace(path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def _checkpoint_contract(
    path: Path,
    diagnostics: list[Dict[str, Any]],
) -> None:
    """Atomically persist every completed dataset collected so far."""
    _write_contract_csv(path, diagnostics)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        help="write the residual contract CSV instead of the historical Markdown report",
    )
    parser.add_argument("--trials", type=int, default=30)
    return parser.parse_args()


def main():
    args = _parse_args()
    quality_csv = PROJECT / "results" / "data_quality" / "data_quality_summary.csv"
    with quality_csv.open(encoding="utf-8") as handle:
        quality_data = list(csv.DictReader(handle))
    ftacv_files = [r for r in quality_data if r['type'] == 'FTacV' and r['success'] == 'True']
    output = None
    if args.output is not None:
        output = args.output if args.output.is_absolute() else PROJECT / args.output

    diagnostics = []
    for r in ftacv_files:
        name = r['filename']
        print(f"Diagnosing {name} ...", end=" ", flush=True)
        try:
            d = diagnose_dataset(name, n_trials=args.trials)
            d['classification'] = _classify_residual(d)
            diagnostics.append(d)
            if output is not None:
                _checkpoint_contract(output, diagnostics)
            print(f"best={d['best_value']:.2f} bias_lo={d['dc_bias_lo']:+.2f} bias_hi={d['dc_bias_hi']:+.2f} onset={d['onset_offset']:+.3f}V")
        except Exception as e:
            print(f"FAIL: {e}")

    if output is not None:
        _checkpoint_contract(output, diagnostics)
        print(f"\nResidual contract → {output}")
        print("Done.")
        return

    # Historical Markdown report
    lines = [
        "# Model Gap Summary",
        "",
        "## DC Residual Diagnostics",
        "",
        "| Dataset | best | bias_lo | bias_mid | bias_hi | onset_offset | H1_peak_shift | H2_peak_shift | Primary Suspect |",
        "|---------|------|---------|----------|---------|-------------|--------------|--------------|-----------------|",
    ]
    for d in diagnostics:
        lines.append(f"| {d['filename']} | {d['best_value']:.1f} | {d['dc_bias_lo']:+.2f} | {d['dc_bias_mid']:+.2f} | {d['dc_bias_hi']:+.2f} | {d['onset_offset']:+.3f} | {d['h1_peak_shift']:+.3f} | {d['h2_peak_shift']:+.3f} | {d['classification']} |")

    # Count dominant cause
    bias_lo_count = sum(1 for d in diagnostics if abs(d['dc_bias_lo']) > 0.3)
    bias_hi_count = sum(1 for d in diagnostics if abs(d['dc_bias_hi']) > 0.3)
    onset_count = sum(1 for d in diagnostics if abs(d['onset_offset']) > 0.05)

    lines.append("")
    lines.append("## Summary")
    lines.append(f"- {bias_lo_count}/{len(diagnostics)} datasets: significant low-potential baseline offset → 基底背景/Cdl 是首要怀疑对象")
    lines.append(f"- {bias_hi_count}/{len(diagnostics)} datasets: significant high-current deviation")
    lines.append(f"- {onset_count}/{len(diagnostics)} datasets: onset misalignment → E0_pre/预氧化需核查")
    lines.append("")
    lines.append("## Recommendation")
    if bias_lo_count > 0:
        lines.append("优先补最低复杂度背景项 `I_bg(E) = b0 + b1*E + b2*E²`，由低电位区约束。")
    lines.append("→ 进入 Stage 3（背景模型实现）。")

    md = OUT_DIR / "model_gap_summary.md"
    md.write_text("\n".join(lines) + "\n")
    print(f"\nReport → {md}")
    print("Done.")


if __name__ == "__main__":
    main()
