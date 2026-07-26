#!/usr/bin/env python3
"""Ru 扫描：测试 10-50 Ω 下高电流偏差是否改善。

用法：cd /Users/liushiyu/OER-FTAcV && .venv/bin/python code/python/scripts/sweep_ru.py
输出：results/diagnostics/model_gap/ru_sweep.md
"""

import sys, os, csv
from pathlib import Path
import numpy as np

PROJECT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT))
sys.path.insert(0, str(PROJECT / "code" / "python" / "src"))
sys.path.insert(0, str(PROJECT / "code" / "web" / "backend"))

from main import _analyze_ftacv_data
from oer_aem.inversion import InversionConfig, TPEInverter, DEFAULT_PARAM_SPECS
from oer_aem.defaults import initialize_oer_parameters
from oer_aem.physics import OERPhysics
from oer_aem.signal import OERSignal
from oer_aem.thermodynamics import apply_alkaline_aem

RAW_DIR = PROJECT / "data" / "raw"
OUT_DIR = PROJECT / "results" / "model_gap"


def _free_specs_excluding(fixed):
    """Return optimizer specs after removing parameters fixed by experiment."""
    fixed_names = set(fixed)
    return tuple(spec for spec in DEFAULT_PARAM_SPECS if spec[0] not in fixed_names)


def _load_numeric(filename, min_cols=3):
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


def bias_hi_for_params(params, analysis):
    """跑正演，返回高电流区 DC 归一化偏差。"""
    p = dict(params)
    p = apply_alkaline_aem(p)
    p = OERPhysics.initialize_system(p)
    t, y, E_act, i_tot = OERPhysics.solve_ode_system(p)
    df = OERSignal.safe_df(t)
    sim_dc = OERSignal.process_current(i_tot, df, p)[:, 0]
    sim_tdc = p['E_start'] + t * p['v']
    exp_tdc = np.asarray(analysis['tdc'])
    exp_dc = np.asarray(analysis['dc'])

    order = np.argsort(sim_tdc)
    x = sim_tdc[order]; _, keep = np.unique(x, return_index=True); x = x[keep]
    sim_dc_interp = np.interp(exp_tdc, x, sim_dc[order][keep])

    e = exp_tdc
    hi = e >= np.percentile(e, 70)
    dc_resid = (exp_dc - sim_dc_interp) / max(np.max(np.abs(exp_dc)), 1e-30)
    return float(np.mean(dc_resid[hi]))


def main():
    ru_values = [10, 20, 30, 40, 50]
    # 用 ftacv2 (质量最好) 做 Ru 扫描
    dataset = "ftacv2-ref-5hz.txt"

    rows = _load_numeric(dataset)
    analysis = _analyze_ftacv_data(rows)
    hq = analysis['harmonic_quality']
    fit_h = hq['fit_harmonics']

    base = initialize_oer_parameters()
    base['gamma'] = 3e-9

    results = []
    for ru in ru_values:
        fixed = {'Cdl': float(base['Cdl']), 'Ru': float(ru),
                 'A': float(base['A']), 'gamma': float(base['gamma'])}
        cfg = InversionConfig(
            E_start=analysis['meta']['E_start'], E_end=analysis['meta']['E_end'],
            f=analysis['meta']['f'], dE=analysis['meta']['dE'],
            n_points=2048, points_per_cycle=128, feature_grid_size=200,
            fixed_params=tuple(fixed.items()), fit_harmonics=tuple(fit_h),
        )
        # Build target
        tdc_raw = np.asarray(analysis['tdc']); dc_raw = np.asarray(analysis['dc'])
        harm_raw = [np.asarray(h) for h in analysis['harmonics']]
        order = np.argsort(tdc_raw); x = tdc_raw[order]
        _, keep = np.unique(x, return_index=True); x = x[keep]
        target = {
            'dc': np.interp(cfg.e_grid, x, dc_raw[order][keep]),
            'harm': [np.interp(cfg.e_grid, x, h[order][keep]) for h in harm_raw],
            'tafel': 60.0, 'e_grid': cfg.e_grid,
        }
        specs = _free_specs_excluding(fixed)
        result = TPEInverter(config=cfg, specs=specs, seed=42, initial_params=base).run(target, n_trials=30)
        best_p = result.best_params; best_p.update(fixed)
        best_p['E0_pre'] = 1.50; best_p['k0_pre'] = 300.0
        best_p['E_start'] = cfg.E_start; best_p['E_end'] = cfg.E_end
        best_p['f'] = cfg.f; best_p['dE'] = cfg.dE
        best_p['n_points'] = cfg.n_points; best_p['points_per_cycle'] = cfg.points_per_cycle
        best_p['total_time'] = cfg.total_time; best_p['v'] = cfg.scan_rate
        best_p['omega'] = 2 * np.pi * cfg.f
        best_p['t_span'] = np.linspace(0, cfg.total_time, cfg.n_points)

        bh = bias_hi_for_params(best_p, analysis)
        results.append({'Ru': ru, 'best': result.best_value, 'bias_hi': bh,
                        'G_OH': best_p.get('G_OH'), 'G_O': best_p.get('G_O'),
                        'scaling': best_p.get('scaling_OOH_OH')})
        print(f"Ru={ru:3.0f}Ω  best={result.best_value:.1f}  bias_hi={bh:+.3f}  G_OH={best_p.get('G_OH',0):.2f} G_O={best_p.get('G_O',0):.2f}")

    # Report
    lines = ["# Ru Sweep Report", "", f"Dataset: {dataset}", "", "| Ru (Ω) | best | bias_hi | G_OH | G_O | scaling |", "|--------|------|---------|------|-----|---------|"]
    for r in results:
        lines.append(f"| {r['Ru']:.0f} | {r['best']:.1f} | {r['bias_hi']:+.3f} | {r['G_OH']:.2f} | {r['G_O']:.2f} | {r['scaling']:.2f} |")

    lines.append("")
    bias_vals = [r['bias_hi'] for r in results]
    min_bias = min(bias_vals)
    best_ru = results[bias_vals.index(min_bias)]['Ru']
    lines.append(f"**最优 Ru = {best_ru:.0f} Ω，bias_hi = {min_bias:+.3f}**")

    if min_bias < 0.3:
        lines.append(f"Ru 调整可将 bias_hi 降至 0.3 以下 → 高电流偏差主要来自欧姆降/膜层电阻。")
    else:
        lines.append(f"即使 Ru={best_ru:.0f}Ω, bias_hi 仍={min_bias:+.3f} → Ru 不是主因，下一个怀疑 OH⁻ 传质。")

    (OUT_DIR / "ru_sweep.md").write_text("\n".join(lines) + "\n")
    print(f"\nReport → {OUT_DIR / 'ru_sweep.md'}")


if __name__ == "__main__":
    main()
