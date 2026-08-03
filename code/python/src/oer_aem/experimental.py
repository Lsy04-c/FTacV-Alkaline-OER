"""Experimental FTacV analysis shared by the API and scientific workflows."""

from __future__ import annotations

from typing import Any, Mapping

import numpy as np

from .calibration import calibrate as calibrate_ftacv
from .data_contract import ExperimentalTrace, normalize_by_max_abs
from .features import complex_harmonic_metrics
from .inversion import (
    InversionConfig,
    _interpolate_lockin_to_grid,
    assess_harmonic_quality,
)
from .signal import OERSignal, estimate_reference_phase, lockin_harmonics


def _to_list(values: Any) -> list[Any]:
    array = np.asarray(values)
    return array.tolist()


def _serialize(value: Any) -> Any:
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        return float(value)
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, (list, tuple)):
        return [_serialize(item) for item in value]
    if isinstance(value, dict):
        return {key: _serialize(item) for key, item in value.items()}
    return value


def _validated_relative_trace(trace: ExperimentalTrace) -> ExperimentalTrace:
    potential = np.asarray(trace.potential, dtype=float).reshape(-1)
    current = np.asarray(trace.current, dtype=float).reshape(-1)
    time = np.asarray(trace.time, dtype=float).reshape(-1)
    if (
        potential.size < 4
        or potential.shape != current.shape
        or potential.shape != time.shape
        or not np.all(np.isfinite(potential))
        or not np.all(np.isfinite(current))
        or not np.all(np.isfinite(time))
    ):
        raise ValueError("experimental trace must contain finite aligned vectors")
    if np.any(np.diff(time) <= 0):
        raise ValueError("experimental time must be strictly increasing")
    return ExperimentalTrace(
        potential=potential,
        current=current,
        time=time - time[0],
    )


# 谐波质量严格度 → 相对 H1 的 RMS 阈值（标准档保持原默认 0.02）
_STRICTNESS_RELATIVE_RMS = {
    "strict": 0.03,
    "standard": 0.02,
    "loose": 0.005,
}


def analyze_ftacv_trace(
    trace: ExperimentalTrace,
    strictness: str | None = None,
) -> dict[str, Any]:
    """Return sampling metadata, DC, H1-H7 and calibration diagnostics.

    strictness: 'strict' | 'standard' | 'loose'，决定谐波可解析阈值
    （相对 H1 的 RMS 比例）。None 时按 standard 处理。
    """
    normalized = _validated_relative_trace(trace)
    e_raw = normalized.potential
    i_raw = normalized.current
    time = normalized.time

    duration = float(time[-1])
    dt = float(np.mean(np.diff(time)))
    fs = 1.0 / dt

    slope, intercept = np.polyfit(time, e_raw, 1)
    scan_rate = float(slope)
    e_dc = intercept + slope * time

    e_ac = e_raw - e_dc
    amplitude = float(np.std(e_ac) * np.sqrt(2.0))
    spectrum = np.abs(np.fft.rfft(e_ac))
    frequencies = np.fft.rfftfreq(len(time), dt)
    peak_index = (
        int(np.argmax(spectrum[1:]) + 1) if len(spectrum) > 1 else 1
    )
    frequency = float(frequencies[peak_index])

    signal_parameters = {
        "f": frequency,
        "band": np.ones(8),
        "use_fft": True,
    }
    current_dc = OERSignal.extract_dc_fft(i_raw, fs, signal_parameters)
    harmonics = OERSignal.extract_harmonics(i_raw, fs, signal_parameters)
    rel_threshold = _STRICTNESS_RELATIVE_RMS.get(strictness, _STRICTNESS_RELATIVE_RMS["standard"])
    harmonic_quality = assess_harmonic_quality(harmonics, min_relative_rms=rel_threshold)
    harmonic_quality["strictness"] = strictness or "standard"

    cut = len(time) // 4
    calibration = calibrate_ftacv(
        e_raw[cut:],
        i_raw[cut:],
        time[cut:],
        i_dc=current_dc[cut:],
    )
    calibration_brief = {
        "cdl": (
            calibration["cdl"]
            if calibration["cdl"].get("success")
            else {
                "success": False,
                "error": calibration["cdl"].get("error"),
            }
        ),
        "tafel": (
            calibration["tafel"]
            if calibration["tafel"].get("success")
            else {
                "success": False,
                "error": calibration["tafel"].get("error"),
            }
        ),
        "preox": calibration["preox"],
    }

    return {
        "success": True,
        "meta": {
            "f": frequency,
            "dE": amplitude,
            "v": scan_rate,
            "E_start": float(intercept),
            "E_end": float(intercept + slope * duration),
            "duration": duration,
            "n_points": int(len(time)),
            "fs": fs,
        },
        "tdc": _to_list(e_dc),
        "E_raw": _to_list(e_raw),
        "i_raw": _to_list(i_raw),
        "dc": _to_list(normalize_by_max_abs(current_dc)),
        "harmonics": [
            _to_list(normalize_by_max_abs(harmonics[:, index]))
            for index in range(7)
        ],
        "harmonic_quality": _serialize(harmonic_quality),
        "suggested_fit_harmonics": harmonic_quality["fit_harmonics"],
        "calib": calibration_brief,
    }


def build_experimental_target(
    trace: ExperimentalTrace,
    analysis: Mapping[str, Any],
    config: InversionConfig,
) -> dict[str, Any]:
    """Build DC, complex and lock-in target blocks on ``config.e_grid``."""
    normalized = _validated_relative_trace(trace)
    tdc = np.asarray(analysis["tdc"], dtype=float)
    order = np.argsort(tdc)
    unique, keep = np.unique(tdc[order], return_index=True)
    target: dict[str, Any] = {
        "dc": np.interp(
            config.e_grid,
            unique,
            np.asarray(analysis["dc"], dtype=float)[order][keep],
        ),
        "harm": [
            np.interp(
                config.e_grid,
                unique,
                np.asarray(channel, dtype=float)[order][keep],
            )
            for channel in analysis["harmonics"]
        ],
        "tafel": None,
        "e_grid": config.e_grid,
        "_experimental_duration": float(analysis["meta"]["duration"]),
        "_experimental_scan_rate": float(analysis["meta"]["v"]),
    }
    if config.feature_mode in ("complex_snr", "hybrid", "combined"):
        cut = len(normalized.current) // 4
        target["complex_harmonics"] = complex_harmonic_metrics(
            normalized.current[cut:],
            fs=1.0 / float(np.mean(np.diff(normalized.time))),
            f0=float(analysis["meta"]["f"]),
            n_harmonics=max(config.fit_harmonics),
        )
    if config.feature_mode in ("lockin_only", "hybrid", "combined"):
        cut = len(normalized.current) // 4
        time_trimmed = normalized.time[cut:]
        lockin = lockin_harmonics(
            normalized.current[cut:],
            time_trimmed,
            f0=float(analysis["meta"]["f"]),
            harmonics=tuple(range(1, max(config.fit_harmonics) + 1)),
            potential_resolution=0.05,
            scan_rate=float(analysis["meta"]["v"]),
            reference_phase=estimate_reference_phase(
                normalized.potential,
                normalized.time,
                float(analysis["meta"]["f"]),
            )[cut:],
        )
        target["lockin"] = _interpolate_lockin_to_grid(
            lockin,
            tdc[cut:],
            config.e_grid,
        )
    return target
