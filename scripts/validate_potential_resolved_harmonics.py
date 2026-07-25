#!/usr/bin/env python3
"""Phase 1.5 — Potential-resolved harmonic diagnostics on four real FTacV datasets.

Outputs amplitude, phase, valid-region, and resolution evidence for each
harmonic and dataset.  Does NOT run inversions; this is a signal-layer check.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data" / "raw"
OUT_DIR = ROOT / "results" / "potential_resolved_harmonics"
OUT_DIR.mkdir(parents=True, exist_ok=True)

# Known 5 Hz datasets (FT4 is 1 Hz — included for diagnostic completeness)
DATASETS = {
    "FT2": "ftacv2-ref-5hz.txt",
    "FT3": "ftacv3-ref-5Hz.txt",
    "FT4": "ftacv4-ref-1hz.txt",
    "FT8": "ftacv8-ref-5Hz.txt",
}


def load_dataset(path: Path) -> dict:
    rows = np.loadtxt(path, skiprows=0)
    if rows.ndim != 2 or rows.shape[1] < 3:
        raise ValueError(f"Unexpected columns in {path}")
    potential = rows[:, 0]
    current = rows[:, 1]
    time_col = rows[:, 2] if rows.shape[1] >= 3 else np.arange(len(potential))
    return {"potential": potential, "current": current, "time": time_col}


def estimate_scan_params(data: dict) -> dict:
    t = data["time"]
    E = data["potential"]
    fs = 1.0 / float(np.mean(np.diff(t)))
    duration = t[-1] - t[0]
    # Scan rate from DC trend (ignore AC oscillations)
    E_dc_trend = np.polyfit(t, E, 1)[0]
    scan_rate = abs(float(E_dc_trend))
    # Fundamental frequency from FFT of current
    n = len(t)
    spec = np.abs(np.fft.rfft(data["current"] - np.mean(data["current"])))
    freqs = np.fft.rfftfreq(n, d=1.0 / fs)
    # Find peak between 0.5 Hz and 15 Hz
    mask = (freqs > 0.5) & (freqs < 15.0)
    if np.any(mask):
        f0 = float(freqs[mask][np.argmax(spec[mask])])
    else:
        f0 = 1.0
    return {
        "fs": fs,
        "duration": duration,
        "scan_rate": scan_rate,
        "f0": f0,
        "n_points": n,
        "E_range": (float(np.min(E)), float(np.max(E))),
    }


def main() -> int:
    import sys as _sys
    _sys.path.insert(0, str(ROOT / "python"))
    _sys.path.insert(0, str(ROOT / "web" / "backend"))
    from oer_aem.signal import lockin_harmonics

    report: dict[str, dict] = {}
    harmonics = (1, 2, 3, 4, 5, 6, 7)

    for label, filename in DATASETS.items():
        path = DATA_DIR / filename
        if not path.exists():
            print(f"[SKIP] {label}: {path} not found")
            continue

        data = load_dataset(path)
        meta = estimate_scan_params(data)
        print(f"\n{'='*60}")
        print(f"{label}: f0={meta['f0']:.2f} Hz  scan_rate={meta['scan_rate']:.3f} V/s  "
              f"duration={meta['duration']:.2f} s  N={meta['n_points']}")

        result = lockin_harmonics(
            data["current"],
            data["time"],
            f0=meta["f0"],
            harmonics=harmonics,
            potential_resolution=0.025,  # 25 mV target
            scan_rate=meta["scan_rate"],
        )

        E_dc = data["potential"]  # use full potential axis (DC + AC)

        dataset_report: dict = {
            "meta": meta,
            "fc_used": result["fc_used"],
            "effective_resolution_v": result["effective_resolution_v"],
            "edge_trim_samples": result["edge_trim_samples"],
            "n_effective": result["n_effective"],
            "harmonics": {},
        }

        for idx, h in enumerate(harmonics):
            amp = result["amplitude"][idx]
            phase = result["phase"][idx]
            valid = result["valid_mask"]

            amp_valid = amp[valid]
            phase_valid = phase[valid]
            E_valid = E_dc[valid]
            n_pts = len(E_dc)

            # Peak detection in valid region
            if len(amp_valid) > 2:
                peak_idx = int(np.argmax(amp_valid))
                peak_E = float(E_valid[peak_idx])
                peak_amp = float(amp_valid[peak_idx])
                mean_phase = float(np.mean(np.cos(phase_valid)) + 1j * np.mean(np.sin(phase_valid)))
                mean_phase = float(np.arctan2(mean_phase.imag, mean_phase.real))
            else:
                peak_E = float("nan")
                peak_amp = float("nan")
                mean_phase = float("nan")

            h_report = {
                "harmonic": h,
                "mean_amplitude": float(np.mean(amp_valid)) if len(amp_valid) > 0 else float("nan"),
                "peak_amplitude": peak_amp,
                "peak_potential_v": peak_E,
                "mean_phase_rad": mean_phase,
                "amplitude_relative_std": float(np.std(amp_valid) / max(np.mean(amp_valid), 1e-30)) if len(amp_valid) > 1 else float("nan"),
                "n_valid_points": int(np.sum(valid)),
                "n_total_points": n_pts,
                "fraction_trimmed": float(1.0 - np.sum(valid) / n_pts),
            }
            dataset_report["harmonics"][str(h)] = h_report

            print(f"  H{h}: amp_mean={h_report['mean_amplitude']:.3e}  "
                  f"peak={h_report['peak_amplitude']:.3e} @ {peak_E:.3f}V  "
                  f"phase_mean={mean_phase:.3f} rad  "
                  f"resolution={result['effective_resolution_v']:.3f}V  "
                  f"n_eff={result['n_effective']}")

        report[label] = dataset_report

    # Write machine-readable evidence
    out_json = OUT_DIR / "harmonic_diagnostics.json"
    out_json.write_text(json.dumps(report, indent=2, default=str))
    print(f"\nEvidence written to {out_json}")

    # Quick summary
    print(f"\n{'='*60}")
    print("Phase 1.5 Summary:")
    for label, r in report.items():
        res = r["effective_resolution_v"]
        n_eff = r["n_effective"]
        ft = r["harmonics"]["1"]["fraction_trimmed"]
        print(f"  {label}: resolution={res:.3f}V  n_eff={n_eff}  "
              f"edge_trim={ft:.1%}  "
              f"H1_amp={r['harmonics']['1']['mean_amplitude']:.3e}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
