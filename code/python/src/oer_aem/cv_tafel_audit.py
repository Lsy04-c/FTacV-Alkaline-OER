"""Read-only exploratory audit for CHI cyclic-voltammetry files.

This module deliberately does not provide a formal Tafel constraint.  It
keeps forward and reverse scans separate and records the missing experimental
metadata that prevents their use in formal inversion.
"""

from __future__ import annotations

import hashlib
import math
import re
from pathlib import Path
from typing import Any

import numpy as np


EXPLORATORY_BLOCKERS = (
    "potential_reference_unresolved",
    "ir_correction_unresolved",
    "electrode_area_unresolved",
    "steady_state_unproven",
)
MINIMUM_EXPLORATORY_R_SQUARED = 0.98


def parse_chi_cv(path: str | Path) -> tuple[dict[str, Any], np.ndarray]:
    """Read CHI header fields and two-column potential/current data."""
    source = Path(path)
    return _parse_chi_cv_text(source.read_text(errors="replace"), source.name)


def _parse_chi_cv_text(text: str, source_name: str) -> tuple[dict[str, Any], np.ndarray]:
    """Parse already-read CHI text so audit data and provenance share one read."""
    header: dict[str, Any] = {"source_file": source_name, "scan_rate_v_s": None}
    rows: list[tuple[float, float]] = []
    for line in text.splitlines():
        match = re.match(
            r"\s*Scan Rate \(V/s\)\s*=\s*([-+0-9.eE]+)\s*$", line
        )
        if match:
            header["scan_rate_v_s"] = float(match.group(1))
            continue
        pieces = re.split(r"[,\t]+", line.strip())
        if len(pieces) != 2:
            continue
        try:
            rows.append((float(pieces[0]), float(pieces[1])))
        except ValueError:
            continue
    if len(rows) < 5:
        raise ValueError("CHI CV file contains fewer than five numeric rows")
    data = np.asarray(rows, dtype=float)
    if not np.all(np.isfinite(data)):
        raise ValueError("CHI CV file contains non-finite numeric rows")
    return header, data


def split_branches(data: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Split a single-cycle CV at its maximum potential without averaging scans."""
    values = np.asarray(data, dtype=float)
    if values.ndim != 2 or values.shape[1] != 2:
        raise ValueError("CV data must have potential and current columns")
    maximum = float(np.max(values[:, 0]))
    turns = np.flatnonzero(np.isclose(values[:, 0], maximum))
    if len(turns) > 2:
        raise ValueError(
            "ambiguous turning plateau: retain time-resolved data before auditing"
        )
    first_turn, last_turn = int(turns[0]), int(turns[-1])
    if first_turn == 0 or last_turn == len(values) - 1:
        raise ValueError("CV data must contain both forward and reverse branches")
    forward = values[: first_turn + 1]
    reverse = values[last_turn:][::-1]
    if np.any(np.diff(forward[:, 0]) < 0.0) or np.any(np.diff(reverse[:, 0]) < 0.0):
        raise ValueError("CV branches are not monotonic around the turning potential")
    return forward, reverse


def summarize_branch(
    branch: np.ndarray,
    current_window_a: tuple[float, float],
) -> dict[str, Any]:
    """Report a raw-current candidate fit; it is not a validated Tafel slope."""
    i_lo, i_hi = map(float, current_window_a)
    if not (0.0 < i_lo < i_hi):
        raise ValueError("current window must satisfy 0 < low < high")
    potential, current = branch[:, 0], branch[:, 1]
    selected = (current >= i_lo) & (current <= i_hi) & (current > 0.0)
    report: dict[str, Any] = {
        "n_points": int(len(branch)),
        "potential_range_raw_v": [float(potential.min()), float(potential.max())],
        "current_range_a": [float(current.min()), float(current.max())],
        "raw_current_candidate": {
            "available": False,
            "current_window_a": [i_lo, i_hi],
            "n_points": int(np.sum(selected)),
            "n_contiguous_segments": 0,
            "current_decade_span": None,
            "minimum_r_squared": MINIMUM_EXPLORATORY_R_SQUARED,
        },
    }
    candidate = report["raw_current_candidate"]
    selected_indices = np.flatnonzero(selected)
    if len(selected_indices) < 10:
        candidate["reason"] = "fewer_than_10_points"
        return report
    segment_count = int(1 + np.sum(np.diff(selected_indices) > 1))
    candidate["n_contiguous_segments"] = segment_count
    selected_current = current[selected]
    decade_span = float(math.log10(selected_current.max() / selected_current.min()))
    candidate["current_decade_span"] = decade_span
    if segment_count != 1:
        candidate["reason"] = "non_contiguous_current_window"
        return report
    if decade_span < 1.0 - 1e-12:
        candidate["reason"] = "less_than_one_current_decade"
        return report
    x = np.log10(selected_current)
    y = potential[selected]
    if np.any(np.diff(selected_current) < 0.0):
        candidate["reason"] = "non_monotonic_current_vs_potential"
        return report
    design = np.column_stack((x, np.ones_like(x)))
    coefficients, _, rank, _ = np.linalg.lstsq(design, y, rcond=None)
    if rank != 2 or not np.all(np.isfinite(coefficients)):
        candidate["reason"] = "rank_deficient_fit"
        return report
    slope, intercept = coefficients
    prediction = slope * x + intercept
    with np.errstate(over="ignore", invalid="ignore"):
        residual = float(np.sum((y - prediction) ** 2))
        total = float(np.sum((y - np.mean(y)) ** 2))
    if not (
        np.all(np.isfinite(prediction))
        and math.isfinite(residual)
        and math.isfinite(total)
        and total > 0.0
    ):
        candidate["reason"] = "nonfinite_fit_metrics"
        return report
    r_squared = float(1.0 - residual / total) if total > 0.0 else 0.0
    if not math.isfinite(r_squared):
        candidate["reason"] = "nonfinite_fit_metrics"
        return report
    candidate["r_squared"] = r_squared
    if r_squared < MINIMUM_EXPLORATORY_R_SQUARED:
        candidate["reason"] = "r_squared_below_threshold"
        return report
    report["raw_current_candidate"].update(
        {
            "available": True,
            "slope_mv_per_dec_raw": float(slope * 1e3),
            "potential_range_raw_v": [float(y.min()), float(y.max())],
        }
    )
    return report


def compare_branches(forward: np.ndarray, reverse: np.ndarray) -> dict[str, float]:
    """Quantify branch hysteresis on the forward branch's potential grid."""
    lower = max(float(forward[:, 0].min()), float(reverse[:, 0].min()))
    upper = min(float(forward[:, 0].max()), float(reverse[:, 0].max()))
    selected = (forward[:, 0] >= lower) & (forward[:, 0] <= upper)
    delta = forward[selected, 1] - np.interp(
        forward[selected, 0], reverse[:, 0], reverse[:, 1]
    )
    return {
        "n_compared_points": int(np.sum(selected)),
        "median_abs_current_difference_a": float(np.median(np.abs(delta))),
        "max_abs_current_difference_a": float(np.max(np.abs(delta))),
    }


def audit_chi_cv(
    path: str | Path,
    *,
    current_window_a: tuple[float, float] = (3e-5, 3e-4),
) -> dict[str, Any]:
    """Return an exploratory-only CV report with both scan branches preserved."""
    source = Path(path)
    source_bytes = source.read_bytes()
    header, data = _parse_chi_cv_text(source_bytes.decode(errors="replace"), source.name)
    forward, reverse = split_branches(data)
    return {
        "classification": "EXPLORATORY_ONLY",
        "input_sha256": hashlib.sha256(source_bytes).hexdigest(),
        "header": header,
        "forward": summarize_branch(forward, current_window_a),
        "reverse": summarize_branch(reverse, current_window_a),
        "hysteresis": compare_branches(forward, reverse),
        "blockers": list(EXPLORATORY_BLOCKERS),
    }
