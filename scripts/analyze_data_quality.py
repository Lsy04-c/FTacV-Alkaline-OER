#!/usr/bin/env python3
"""批量数据质量评估 — 读取 data/raw/*.txt，输出每组的谐波质量报告。

用法：
    cd /Users/liushiyu/OER-FTAcV
    .venv/bin/python scripts/analyze_data_quality.py

输出：
    results/data_quality/data_quality_summary.csv
    results/data_quality/data_quality_summary.md
    results/data_quality/<name>_harmonics.png
"""

import ast
import sys, os, csv
from pathlib import Path
from typing import Dict, Any

import numpy as np

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT / "python"))
sys.path.insert(0, str(PROJECT / "web" / "backend"))

from main import _analyze_ftacv_data
from oer_aem.signal import _apply_edge_taper

RAW_DIR = PROJECT / "data" / "raw"
OUT_DIR = PROJECT / "results" / "data_quality"
OUT_DIR.mkdir(parents=True, exist_ok=True)


def summarize_fit_harmonics(results):
    """Return channels common to all, optional, and diagnostic-only."""
    selected = [
        set(ast.literal_eval(row["fit_harmonics"]))
        for row in results
        if row.get("fit_harmonics")
    ]
    if not selected:
        return {"common": [], "optional": [], "diagnostic_only": list(range(1, 8))}
    common = set.intersection(*selected)
    union = set.union(*selected)
    return {
        "common": sorted(common),
        "optional": sorted(union - common),
        "diagnostic_only": sorted(set(range(1, 8)) - union),
    }


def _load_numeric(filename: str, min_cols=3) -> np.ndarray:
    """容错加载：跳过非数值表头行，支持空格或逗号分隔。"""
    raw = (RAW_DIR / filename).read_text()
    lines = raw.strip().splitlines()
    numeric_lines = []
    for line in lines:
        # 尝试空格分隔
        parts = line.replace(",", " ").split()
        try:
            vals = [float(x) for x in parts[:min_cols]]
            if len(vals) >= min_cols:
                numeric_lines.append(vals)
            elif len(vals) >= 2:
                numeric_lines.append(vals + [0.0])  # CV: pad缺失的时间列
        except ValueError:
            continue
    return np.array(numeric_lines)


def _load_cv(filename: str) -> Dict[str, Any]:
    """加载 CV 数据，只做基础统计，不做 FTacV 频域分析。"""
    rows = _load_numeric(filename, min_cols=2)
    assert rows.shape[1] >= 2, f"{filename}: expected >=2 columns"
    E, i = rows[:, 0], rows[:, 1]
    t = rows[:, 2] if rows.shape[1] >= 3 else np.arange(len(E), dtype=float)
    if np.all(t == t[0]): t = np.arange(len(E), dtype=float)  # 全是 0 的填充列
    t = t - t[0]
    E_int = E[::10] if len(E) > 200 else E
    i_int = i[::10] if len(i) > 200 else i
    di = np.diff(i_int)
    peaks = []
    for k in range(3, len(di) - 3):
        if di[k-1] > di[k] < di[k+1] and di[k] < -abs(np.median(di))*2:
            peaks.append(float(E_int[k]))
    return {
        "type": "CV", "filename": filename, "n_points": len(t),
        "E_range": f"{float(np.min(E)):.3f} – {float(np.max(E)):.3f}",
        "i_range": f"{float(np.min(i)):.3e} – {float(np.max(i)):.3e}",
        "redox_peaks": peaks[:4],
        "success": True, "error": "",
    }


def _load_ftacv(filename: str) -> Dict[str, Any]:
    """调用 _analyze_ftacv_data 自动识别参数并提取谐波。"""
    rows = _load_numeric(filename)
    assert rows.shape[1] >= 3, f"{filename}: expected >=3 columns"
    try:
        r = _analyze_ftacv_data(rows)
    except Exception as e:
        return {"type": "FTacV", "filename": filename, "success": False, "error": str(e)}
    hq = r["harmonic_quality"]
    ch = hq["channels"]
    return {
        "type": "FTacV", "filename": filename, "success": True, "error": "",
        "n_points": r["meta"]["n_points"], "duration": f"{r['meta']['duration']:.1f}s",
        "E_range": f"{r['meta']['E_start']:.3f} – {r['meta']['E_end']:.3f}",
        "f": f"{r['meta']['f']:.2f} Hz", "dE": f"{r['meta']['dE']:.3f} V",
        "v": f"{r['meta']['v']*1e3:.2f} mV/s", "fs": f"{r['meta']['fs']:.1f} Hz",
        "h1_rms": f"{ch[0]['rms']:.2e}", "h2_rms": f"{ch[1]['rms']:.2e}",
        "h3_rms": f"{ch[2]['rms']:.2e}", "h4_rms": f"{ch[3]['rms']:.2e}",
        "h5_rms": f"{ch[4]['rms']:.2e}", "h6_rms": f"{ch[5]['rms']:.2e}",
        "h7_rms": f"{ch[6]['rms']:.2e}",
        "h2_h1": f"{ch[1]['rms']/max(ch[0]['rms'],1e-30):.3f}",
        "h3_h1": f"{ch[2]['rms']/max(ch[0]['rms'],1e-30):.3f}",
        "h4_h1": f"{ch[3]['rms']/max(ch[0]['rms'],1e-30):.3f}",
        "fit_harmonics": str(hq["fit_harmonics"]),
        "CdlA": _fmt_cdl(r.get("calib", {}).get("cdl", {})),
        "Tafel": _fmt_tafel(r.get("calib", {}).get("tafel", {})),
        "preox": _fmt_preox(r.get("calib", {}).get("preox", {})),
        "raw": r,  # 保留原始 dict 用于后续画图
    }


def _fmt_cdl(cdl: dict) -> str:
    if not cdl.get("success"): return "FAIL"
    return f"{cdl.get('CdlA', 0)*1e6:.1f} µF"


def _fmt_tafel(tafel: dict) -> str:
    if not tafel.get("success"): return "FAIL"
    return f"{tafel.get('b', 0):.0f} mV/dec"


def _fmt_preox(preox: dict) -> str:
    if not preox.get("detected", False): return "not detected"
    return f"Q={preox.get('charge', 0)*1e6:.3f} µC"


def _make_harmonic_figure(result: Dict[str, Any], out_path: str):
    """画一组谐波总览图。"""
    raw = result.get("raw")
    if raw is None:
        return
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    E = np.asarray(raw["E_raw"])
    tdc = np.asarray(raw["tdc"])
    dc = np.asarray(raw["dc"])
    harms = [np.asarray(h) for h in raw["harmonics"]]
    hq = raw["harmonic_quality"]

    fig, axes = plt.subplots(3, 4, figsize=(16, 10))
    fig.suptitle(result["filename"], fontsize=13, fontweight="bold")

    # 总电流
    ax = axes[0, 0]
    ax.plot(E, np.asarray(raw["i_raw"]) * 1e3, linewidth=0.5, color="steelblue")
    ax.set_xlabel("E (V)"); ax.set_ylabel("i (mA)"); ax.set_title("Raw current")

    # DC
    ax = axes[0, 1]
    ax.plot(tdc, dc, linewidth=1, color="darkgreen")
    ax.set_xlabel("E_dc (V)"); ax.set_title("DC envelope (norm.)")

    # 功率谱
    ax = axes[0, 2]
    i_ac = np.asarray(raw["i_raw"]) - np.polyval(np.polyfit(np.arange(len(raw["i_raw"])), raw["i_raw"], 1), np.arange(len(raw["i_raw"])))
    Y = np.abs(np.fft.rfft(_apply_edge_taper(i_ac)))
    f_axis = np.fft.rfftfreq(len(i_ac), 1/raw["meta"]["fs"])
    ax.semilogy(f_axis[f_axis <= 15*raw["meta"]["f"]], Y[f_axis <= 15*raw["meta"]["f"]], linewidth=0.7, color="purple")
    ax.set_xlabel("f (Hz)"); ax.set_title("Power spectrum")

    # 7 个谐波
    colors = plt.cm.tab10.colors
    for k in range(7):
        ax = axes[1 + k // 4, k % 4]
        ax.plot(tdc, harms[k], linewidth=0.8, color=colors[k])
        ch = hq["channels"][k]
        label = f"H{k+1}" + (" ✓" if ch["fit"] else " ✗")
        ax.set_title(label, color="green" if ch["fit"] else "gray")
        ax.set_xlabel("E_dc (V)")

    axes[2, 3].set_visible(False)  # unused subplot
    plt.tight_layout()
    fig.savefig(out_path, dpi=120)
    plt.close(fig)


def main():
    files = sorted(RAW_DIR.glob("*.txt"))
    results = []
    for fp in files:
        name = fp.name
        print(f"Processing {name} ...", end=" ", flush=True)
        if name.startswith("cv"):
            r = _load_cv(name)
        else:
            r = _load_ftacv(name)
        results.append(r)
        print("OK" if r["success"] else f"FAIL: {r['error']}")

        # 谐波图
        if r["success"] and r["type"] == "FTacV":
            png = OUT_DIR / f"{Path(name).stem}_harmonics.png"
            _make_harmonic_figure(r, str(png))

    # ---- CSV ----
    csv_path = OUT_DIR / "data_quality_summary.csv"
    fields = ["filename", "type", "n_points", "duration", "E_range", "f", "dE", "v", "fs",
              "h1_rms", "h2_rms", "h3_rms", "h4_rms", "h5_rms", "h6_rms", "h7_rms",
              "h2_h1", "h3_h1", "h4_h1", "fit_harmonics", "CdlA", "Tafel", "preox",
              "success", "error"]
    with open(csv_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for r in results:
            # Pad missing CV fields
            for k in fields:
                r.setdefault(k, "")
            w.writerow({k: r[k] for k in fields})
    print(f"\nCSV → {csv_path}")

    # ---- Markdown ----
    md_path = OUT_DIR / "data_quality_summary.md"
    with open(md_path, "w") as f:
        f.write("# Data Quality Summary\n\n")
        f.write(f"Analyzed {len(results)} files from `data/raw/`.\n\n")
        f.write("| File | Type | n_pts | E range | f | dE | v | H2/H1 | H3/H1 | H4/H1 | Fit H | CdlA | Tafel | Pre-ox |\n")
        f.write("|------|------|-------|---------|---|---|---|-------|-------|-------|-------|------|-------|--------|\n")
        for r in results:
            if r["success"]:
                f.write(f"| {r['filename']} | {r['type']} | {r.get('n_points','')} | {r.get('E_range','')} | "
                        f"{r.get('f','')} | {r.get('dE','')} | {r.get('v','')} | "
                        f"{r.get('h2_h1','')} | {r.get('h3_h1','')} | {r.get('h4_h1','')} | "
                        f"{r.get('fit_harmonics','')} | {r.get('CdlA','')} | {r.get('Tafel','')} | {r.get('preox','')} |\n")
            else:
                f.write(f"| {r['filename']} | {r['type']} | ❌ {r.get('error','')} |\n")

        f.write("\n## Key Observations\n\n")
        ftacv_ok = [r for r in results if r["success"] and r["type"] == "FTacV"]
        f.write(f"- {len(ftacv_ok)}/{len([r for r in results if r['type']=='FTacV'])} FTacV files analyzed successfully.\n")
        f.write(f"- CV files: {[r['filename'] for r in results if r['type']=='CV']}\n")

        # 谐波判断
        harmonic_summary = summarize_fit_harmonics(ftacv_ok)
        f.write(
            "- Common fitting harmonics across all datasets: "
            f"{harmonic_summary['common']}\n"
        )
        f.write(
            "- Dataset-specific optional fitting harmonics: "
            f"{harmonic_summary['optional']}\n"
        )
        f.write(
            "- Diagnostic-only harmonics across all datasets: "
            f"{harmonic_summary['diagnostic_only']}\n"
        )

    print(f"MD  → {md_path}")
    print("Done.")


if __name__ == "__main__":
    main()
