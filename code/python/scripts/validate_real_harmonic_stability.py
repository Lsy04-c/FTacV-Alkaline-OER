#!/usr/bin/env python3
"""Gate A4: real-data lock-in stability under legal input perturbations."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import platform
import shlex
import subprocess
import sys
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Sequence

import numpy as np
from scipy.signal import resample_poly

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "code" / "python" / "src"))

from oer_aem.signal import estimate_reference_phase, lockin_harmonics  # noqa: E402

DATA_DIR = ROOT / "data" / "raw"
DATASETS = {
    "FT2": "ftacv2-ref-5hz.txt",
    "FT3": "ftacv3-ref-5Hz.txt",
    "FT4": "ftacv4-ref-1hz.txt",
    "FT8": "ftacv8-ref-5Hz.txt",
}
HARMONICS = tuple(range(1, 8))
VARIANT_NAMES = (
    "downsample_2x",
    "downsample_4x",
    "trim_start_10pct",
    "trim_end_10pct",
)
POTENTIAL_RESOLUTION_V = 0.025
RESOLVABILITY_FRACTION = 0.02
AMPLITUDE_NRMSE_LIMIT = 0.10
PHASE_RMSE_LIMIT_RAD = 0.10
PEAK_SHIFT_LIMIT_V = 0.025
COMMON_VALID_FRACTION_LIMIT = 0.50
INDEPENDENT_INTERVALS_LIMIT = 10

CSV_FIELDS = (
    "dataset",
    "variant",
    "harmonic",
    "f0_hz",
    "scan_rate_v_s",
    "reference_relative_strength",
    "resolved",
    "amplitude_nrmse",
    "phase_rmse_rad",
    "peak_shift_v",
    "peak_comparable",
    "common_valid_fraction",
    "independent_potential_intervals",
    "reference_effective_resolution_v",
    "candidate_effective_resolution_v",
    "reference_n_effective",
    "candidate_n_effective",
)


def _validate_arrays(
    time: Sequence[float],
    potential: Sequence[float],
    current: Sequence[float],
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    t = np.asarray(time, dtype=float).reshape(-1)
    e = np.asarray(potential, dtype=float).reshape(-1)
    i = np.asarray(current, dtype=float).reshape(-1)
    if t.size != e.size or t.size != i.size or t.size < 32:
        raise ValueError("time, potential, and current must share at least 32 points")
    if not np.all(np.isfinite(t)) or not np.all(np.isfinite(e)) or not np.all(np.isfinite(i)):
        raise ValueError("input arrays must be finite")
    dt = np.diff(t)
    if np.any(dt <= 0.0):
        raise ValueError("time must be strictly increasing")
    mean_dt = float(np.mean(dt))
    max_relative_jitter = float(np.max(np.abs(dt - mean_dt)) / mean_dt)
    if max_relative_jitter > 0.02:
        raise ValueError("time must be approximately equally spaced")
    return t, e, i


def build_variants(
    time: Sequence[float],
    potential: Sequence[float],
    current: Sequence[float],
) -> dict[str, dict[str, np.ndarray]]:
    """Return the frozen full, antialiased downsampled, and one-sided trim inputs."""
    t, e, i = _validate_arrays(time, potential, current)
    dt = float(np.mean(np.diff(t)))
    variants = {
        "full": {"time": t.copy(), "potential": e.copy(), "current": i.copy()}
    }
    for factor in (2, 4):
        down_e = np.asarray(resample_poly(e, up=1, down=factor), dtype=float)
        down_i = np.asarray(resample_poly(i, up=1, down=factor), dtype=float)
        down_t = t[0] + np.arange(down_e.size, dtype=float) * dt * factor
        variants[f"downsample_{factor}x"] = {
            "time": down_t,
            "potential": down_e,
            "current": down_i,
        }
    trim = max(1, int(round(0.10 * t.size)))
    if t.size - trim < 32:
        raise ValueError("10% trim must retain at least 32 points")
    variants["trim_start_10pct"] = {
        "time": t[trim:].copy(),
        "potential": e[trim:].copy(),
        "current": i[trim:].copy(),
    }
    variants["trim_end_10pct"] = {
        "time": t[:-trim].copy(),
        "potential": e[:-trim].copy(),
        "current": i[:-trim].copy(),
    }
    return variants


def _normalized_rmse(candidate: np.ndarray, reference: np.ndarray) -> float:
    scale = max(float(np.max(np.abs(reference))), np.finfo(float).eps)
    return float(np.sqrt(np.mean((candidate - reference) ** 2)) / scale)


def compare_complex_envelopes(
    reference_potential: Sequence[float],
    reference_complex: Sequence[complex],
    reference_valid: Sequence[bool],
    candidate_potential: Sequence[float],
    candidate_complex: Sequence[complex],
    candidate_valid: Sequence[bool],
    *,
    potential_resolution: float,
) -> dict[str, object]:
    """Compare complex envelopes after interpolation over their common DC-potential span."""
    ref_e = np.asarray(reference_potential, dtype=float).reshape(-1)
    ref_z = np.asarray(reference_complex, dtype=complex).reshape(-1)
    ref_valid = np.asarray(reference_valid, dtype=bool).reshape(-1)
    cand_e = np.asarray(candidate_potential, dtype=float).reshape(-1)
    cand_z = np.asarray(candidate_complex, dtype=complex).reshape(-1)
    cand_valid = np.asarray(candidate_valid, dtype=bool).reshape(-1)
    if (
        ref_e.size != ref_z.size
        or ref_e.size != ref_valid.size
        or cand_e.size != cand_z.size
        or cand_e.size != cand_valid.size
    ):
        raise ValueError("potential, complex envelope, and valid mask lengths must match")

    def ordered_unique(e: np.ndarray, z: np.ndarray, valid: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        e_valid = e[valid]
        z_valid = z[valid]
        order = np.argsort(e_valid)
        e_sorted = e_valid[order]
        z_sorted = z_valid[order]
        e_unique, indices = np.unique(e_sorted, return_index=True)
        return e_unique, z_sorted[indices]

    ref_e_valid, ref_z_valid = ordered_unique(ref_e, ref_z, ref_valid)
    cand_e_valid, cand_z_valid = ordered_unique(cand_e, cand_z, cand_valid)
    if ref_e_valid.size < 2 or cand_e_valid.size < 2:
        raise ValueError("each envelope needs at least two valid potential points")
    low = max(float(ref_e_valid[0]), float(cand_e_valid[0]))
    high = min(float(ref_e_valid[-1]), float(cand_e_valid[-1]))
    if high <= low:
        raise ValueError("reference and candidate have no common valid potential span")
    span = high - low
    n_intervals = int(np.floor(span / potential_resolution + 1e-12))
    grid = np.linspace(low, high, max(2, n_intervals + 1))

    def interpolate_complex(e: np.ndarray, z: np.ndarray) -> np.ndarray:
        return np.interp(grid, e, z.real) + 1j * np.interp(grid, e, z.imag)

    ref_grid = interpolate_complex(ref_e_valid, ref_z_valid)
    cand_grid = interpolate_complex(cand_e_valid, cand_z_valid)
    ref_amp = np.abs(ref_grid)
    cand_amp = np.abs(cand_grid)
    phase_delta = np.angle(np.exp(1j * (np.angle(cand_grid) - np.angle(ref_grid))))
    reference_span = max(float(ref_e_valid[-1] - ref_e_valid[0]), np.finfo(float).eps)
    ref_peak_index = int(np.argmax(ref_amp))
    peak_comparable = bool(
        ref_peak_index not in {0, grid.size - 1}
        and grid[ref_peak_index] >= low + potential_resolution
        and grid[ref_peak_index] <= high - potential_resolution
    )
    peak_shift = (
        abs(float(grid[int(np.argmax(cand_amp))] - grid[ref_peak_index]))
        if peak_comparable
        else 0.0
    )
    return {
        "amplitude_nrmse": _normalized_rmse(cand_amp, ref_amp),
        "phase_rmse_rad": float(np.sqrt(np.mean(phase_delta**2))),
        "peak_shift_v": peak_shift,
        "peak_comparable": peak_comparable,
        "common_valid_fraction": min(1.0, span / reference_span),
        "independent_potential_intervals": n_intervals,
    }


def assess_gate(rows: Sequence[dict[str, object]]) -> dict[str, object]:
    """Apply the preregistered Gate A4 limits."""
    failures: list[str] = []
    for row in rows:
        prefix = f"{row['dataset']} {row['variant']} H{row['harmonic']}"
        structural_limits = {
            "common_valid_fraction": COMMON_VALID_FRACTION_LIMIT,
            "independent_potential_intervals": INDEPENDENT_INTERVALS_LIMIT,
        }
        for metric, limit in structural_limits.items():
            value = float(row[metric])
            if not np.isfinite(value) or value < limit:
                failures.append(f"{prefix} {metric}={value:.6g}<{limit:.6g}")
        evaluate_signal = int(row["harmonic"]) <= 3 or bool(row["resolved"])
        if not evaluate_signal:
            continue
        upper_limits = {
            "amplitude_nrmse": AMPLITUDE_NRMSE_LIMIT,
            "phase_rmse_rad": PHASE_RMSE_LIMIT_RAD,
        }
        if bool(row["peak_comparable"]):
            upper_limits["peak_shift_v"] = PEAK_SHIFT_LIMIT_V
        for metric, limit in upper_limits.items():
            value = float(row[metric])
            if not np.isfinite(value) or value > limit:
                failures.append(f"{prefix} {metric}={value:.6g}>{limit:.6g}")
    return {"passed": not failures, "n_rows": len(rows), "n_failures": len(failures), "failures": failures}


def _load_dataset(path: Path) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    values = np.loadtxt(path)
    if values.ndim != 2 or values.shape[1] < 3:
        raise ValueError(f"unexpected data schema: {path}")
    return _validate_arrays(values[:, 2], values[:, 0], values[:, 1])


def _estimate_full_metadata(time: np.ndarray, potential: np.ndarray) -> tuple[float, float]:
    trend = np.polyfit(time, potential, 1)
    scan_rate = abs(float(trend[0]))
    detrended = potential - np.polyval(trend, time)
    fs = 1.0 / float(np.mean(np.diff(time)))
    frequencies = np.fft.rfftfreq(time.size, d=1.0 / fs)
    spectrum = np.abs(np.fft.rfft(detrended * np.hanning(time.size)))
    mask = (frequencies >= 0.5) & (frequencies <= 15.0)
    if not np.any(mask):
        raise ValueError("no valid applied-potential fundamental frequency")
    f0 = float(frequencies[mask][np.argmax(spectrum[mask])])
    return f0, scan_rate


def _extract_variant(
    variant: dict[str, np.ndarray],
    *,
    f0: float,
    scan_rate: float,
) -> tuple[np.ndarray, dict[str, object]]:
    time = variant["time"]
    potential = variant["potential"]
    trend = np.polyfit(time, potential, 1)
    dc_potential = np.polyval(trend, time)
    lockin = lockin_harmonics(
        variant["current"],
        time,
        f0=f0,
        harmonics=HARMONICS,
        potential_resolution=POTENTIAL_RESOLUTION_V,
        scan_rate=scan_rate,
        reference_phase=estimate_reference_phase(potential, time, f0),
    )
    return dc_potential, lockin


def _analyze_pair(task: tuple[str, str, str]) -> list[dict[str, object]]:
    label, path_string, variant_name = task
    time, potential, current = _load_dataset(Path(path_string))
    variants = build_variants(time, potential, current)
    f0, scan_rate = _estimate_full_metadata(time, potential)
    ref_e, reference = _extract_variant(variants["full"], f0=f0, scan_rate=scan_rate)
    cand_e, candidate = _extract_variant(variants[variant_name], f0=f0, scan_rate=scan_rate)
    ref_valid = np.asarray(reference["valid_mask"], dtype=bool)
    reference_rms = np.asarray(
        [
            np.sqrt(np.mean(np.abs(np.asarray(z)[ref_valid]) ** 2))
            for z in reference["complex"]
        ],
        dtype=float,
    )
    strength_scale = max(float(reference_rms[0]), np.finfo(float).eps)
    rows: list[dict[str, object]] = []
    for index, harmonic in enumerate(HARMONICS):
        metrics = compare_complex_envelopes(
            ref_e,
            reference["complex"][index],
            ref_valid,
            cand_e,
            candidate["complex"][index],
            candidate["valid_mask"],
            potential_resolution=POTENTIAL_RESOLUTION_V,
        )
        relative_strength = float(reference_rms[index] / strength_scale)
        rows.append(
            {
                "dataset": label,
                "variant": variant_name,
                "harmonic": harmonic,
                "f0_hz": f0,
                "scan_rate_v_s": scan_rate,
                "reference_relative_strength": relative_strength,
                "resolved": relative_strength >= RESOLVABILITY_FRACTION,
                **metrics,
                "reference_effective_resolution_v": reference["effective_resolution_v"],
                "candidate_effective_resolution_v": candidate["effective_resolution_v"],
                "reference_n_effective": reference["n_effective"],
                "candidate_n_effective": candidate["n_effective"],
            }
        )
    return rows


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def collect_provenance(root: Path) -> dict[str, object]:
    """Return the source and runtime identity required by a formal Gate A4 run."""
    commit = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    thread_names = (
        "OMP_NUM_THREADS",
        "OPENBLAS_NUM_THREADS",
        "MKL_NUM_THREADS",
        "NUMEXPR_NUM_THREADS",
    )
    return {
        "source_commit": commit,
        "started_at_cst": datetime.now(
            timezone(timedelta(hours=8))
        ).strftime("%Y-%m-%dT%H:%M:%S%z"),
        "thread_limits": {name: os.environ.get(name, "unset") for name in thread_names},
        "command": shlex.join([sys.executable, *sys.argv]),
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--datasets", nargs="+", choices=tuple(DATASETS), default=tuple(DATASETS))
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=ROOT / "results" / "formal" / "harmonic_stability" / "gate-a4",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    if args.workers < 1:
        raise ValueError("workers must be positive")
    provenance = collect_provenance(ROOT)
    selected = tuple(args.datasets)
    tasks = [
        (label, str(DATA_DIR / DATASETS[label]), variant)
        for label in selected
        for variant in VARIANT_NAMES
    ]
    worker_count = min(args.workers, len(tasks), os.cpu_count() or 1)
    if worker_count == 1:
        nested_rows = [_analyze_pair(task) for task in tasks]
    else:
        with ProcessPoolExecutor(max_workers=worker_count) as executor:
            nested_rows = list(executor.map(_analyze_pair, tasks))
    rows = [row for group in nested_rows for row in group]
    rows.sort(key=lambda row: (str(row["dataset"]), str(row["variant"]), int(row["harmonic"])))

    args.output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = args.output_dir / "harmonic_stability.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)

    gate = assess_gate(rows)
    gate.update(
        {
            "datasets": list(selected),
            "variants": list(VARIANT_NAMES),
            "harmonics": list(HARMONICS),
            "workers": worker_count,
            "thresholds": {
                "potential_resolution_v": POTENTIAL_RESOLUTION_V,
                "resolvability_fraction": RESOLVABILITY_FRACTION,
                "amplitude_nrmse": AMPLITUDE_NRMSE_LIMIT,
                "phase_rmse_rad": PHASE_RMSE_LIMIT_RAD,
                "peak_shift_v": PEAK_SHIFT_LIMIT_V,
                "common_valid_fraction": COMMON_VALID_FRACTION_LIMIT,
                "independent_potential_intervals": INDEPENDENT_INTERVALS_LIMIT,
            },
            "input_sha256": {
                label: _sha256(DATA_DIR / DATASETS[label]) for label in selected
            },
            "environment": {
                "python": platform.python_version(),
                "numpy": np.__version__,
                "scipy": __import__("scipy").__version__,
            },
            "provenance": provenance,
            "csv": str(csv_path),
        }
    )
    summary_path = args.output_dir / "harmonic_stability_summary.json"
    summary_path.write_text(json.dumps(gate, indent=2) + "\n", encoding="utf-8")
    print(
        f"HARMONIC_STABILITY passed={gate['passed']} rows={gate['n_rows']} "
        f"failures={gate['n_failures']} workers={worker_count}"
    )
    return 0 if gate["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
