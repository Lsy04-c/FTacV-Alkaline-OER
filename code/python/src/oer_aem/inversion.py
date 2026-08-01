"""TPE-based inversion utilities for alkaline OER FTacV microkinetics.

This module promotes the benchmark inversion pipeline into a reusable core API:
parameter encoding, synthetic target generation, objective evaluation, and a
small Optuna TPE wrapper.  It intentionally keeps the mechanistic forward model
explicit; the optimizer only searches physically named AEM parameters.
"""

from __future__ import annotations

import contextlib
import copy
import hashlib
import io
import json
import warnings
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np

from .calibration import measure_tafel
from .defaults import initialize_oer_parameters
from .features import (
    complex_harmonic_metrics,
    snr_weights,
    wrapped_phase_difference,
)
from .physics import OERPhysics
from .signal import OERSignal
from .thermodynamics import apply_alkaline_aem


ParamSpec = Tuple[str, str, float, float]


DEFAULT_PARAM_SPECS: Tuple[ParamSpec, ...] = (
    ("k0_1", "log10", -3.0, 5.0),
    ("k0_2", "log10", -3.0, 5.0),
    ("k0_3", "log10", -3.0, 5.0),
    ("k0_4", "log10", -3.0, 5.0),
    ("G_OH", "linear", 0.8, 1.8),
    ("G_O", "linear", 2.2, 3.4),
    ("scaling_OOH_OH", "linear", 2.8, 3.6),
    ("gamma", "log10", -10.0, -7.0),
)


@dataclass(frozen=True)
class InversionConfig:
    """Scanning and objective settings for FTacV inversion."""

    E_start: float = 0.924
    E_end: float = 1.923
    f: float = 1.0
    dE: float = 0.16
    n_points: int = 8192
    points_per_cycle: int = 256
    feature_grid_size: Optional[int] = None  # None = use full post-discard grid
    discard_fraction: float = 0.25
    sigma_dc: float = 0.02
    sigma_harm: float = 0.05
    sigma_tafel: float = 0.05
    ode_penalty: float = 1e9
    feature_fail_penalty: float = 1e9
    tafel_fail_resid: float = 10.0
    seed: int = 42
    param_specs: Tuple[ParamSpec, ...] = DEFAULT_PARAM_SPECS
    fixed_params: Tuple[Tuple[str, float], ...] = ()
    fit_harmonics: Tuple[int, ...] = (1, 2, 3, 4, 5, 6, 7)
    feature_mode: str = "legacy"
    solver_backend: str = "auto"
    phase_weight: float = 1.0
    snr_floor: float = 3.0

    @property
    def total_time(self) -> float:
        return (self.n_points / self.points_per_cycle) / self.f

    @property
    def scan_rate(self) -> float:
        return (self.E_end - self.E_start) / self.total_time

    @property
    def sample_rate(self) -> float:
        return self.n_points / self.total_time

    @property
    def t_span(self) -> np.ndarray:
        return np.linspace(0.0, self.total_time, self.n_points)

    @property
    def tdc(self) -> np.ndarray:
        return self.E_start + self.t_span * self.scan_rate

    @property
    def discard_index(self) -> int:
        return int(np.clip(round(self.n_points * self.discard_fraction), 0, self.n_points - 2))

    @property
    def resolved_feature_grid_size(self) -> int:
        """Actual number of grid points (auto-resolved from simulation grid)."""
        if self.feature_grid_size is not None and self.feature_grid_size > 0:
            return self.feature_grid_size
        return self.n_points - self.discard_index

    @property
    def e_grid(self) -> np.ndarray:
        tdc_trim = self.tdc[self.discard_index :]
        if self.feature_grid_size is not None and self.feature_grid_size > 0:
            return np.linspace(float(tdc_trim[0]), float(tdc_trim[-1]), self.feature_grid_size)
        return np.asarray(tdc_trim, dtype=float)


@dataclass(frozen=True)
class FeatureChannel:
    """One target-derived observation block in the inversion objective."""

    channel_id: str
    block: str
    harmonic: Optional[int]
    role: str
    requested: bool
    available: bool
    active: bool
    target_weight: float
    loss_weight: float
    n_points: int
    mask_sha256: Optional[str]
    exclusion_reason: Optional[str]
    mask: Optional[np.ndarray] = field(
        default=None, repr=False, compare=False
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "harmonic", (
            None if self.harmonic is None else int(self.harmonic)
        ))
        object.__setattr__(self, "requested", bool(self.requested))
        object.__setattr__(self, "available", bool(self.available))
        object.__setattr__(self, "active", bool(self.active))
        object.__setattr__(self, "target_weight", float(self.target_weight))
        object.__setattr__(self, "loss_weight", float(self.loss_weight))
        object.__setattr__(self, "n_points", int(self.n_points))
        if self.mask is not None:
            values = np.asarray(self.mask, dtype=bool).copy()
            values.setflags(write=False)
            object.__setattr__(self, "mask", values)

    def to_evidence(self) -> Dict[str, Any]:
        return {
            "channel_id": self.channel_id,
            "block": self.block,
            "harmonic": self.harmonic,
            "role": self.role,
            "requested": self.requested,
            "available": self.available,
            "active": self.active,
            "target_weight": self.target_weight,
            "loss_weight": self.loss_weight,
            "n_points": self.n_points,
            "mask_sha256": self.mask_sha256,
            "exclusion_reason": self.exclusion_reason,
        }


@dataclass(frozen=True)
class FeatureChannelContract:
    """Immutable target-side channel selection and normalization evidence."""

    feature_mode: str
    fit_harmonics: Tuple[int, ...]
    phase_weight: float
    snr_floor: float
    channels: Tuple[FeatureChannel, ...]
    normalization_weight_sum: float
    sha256: str

    def to_evidence(self) -> Dict[str, Any]:
        return {
            "schema_version": 1,
            "feature_mode": self.feature_mode,
            "fit_harmonics": list(self.fit_harmonics),
            "phase_weight": self.phase_weight,
            "snr_floor": self.snr_floor,
            "normalization_weight_sum": self.normalization_weight_sum,
            "channels": [item.to_evidence() for item in self.channels],
            "sha256": self.sha256,
        }


def _mask_sha256(mask: np.ndarray) -> str:
    values = np.asarray(mask, dtype=bool).reshape(-1)
    payload = len(values).to_bytes(8, "big") + np.packbits(values).tobytes()
    return hashlib.sha256(payload).hexdigest()


def _channel_role(harmonic: Optional[int]) -> str:
    if harmonic is None:
        return "global"
    return "common" if harmonic <= 3 else "dataset_specific"


def build_feature_channel_contract(
    target: Mapping[str, Any],
    config: InversionConfig,
) -> FeatureChannelContract:
    """Freeze active observations, weights and masks from target data only."""
    expected_size = config.resolved_feature_grid_size
    if "dc" not in target:
        raise ValueError("DC target is missing")
    dc = np.asarray(target["dc"], dtype=float).reshape(-1)
    if dc.size != expected_size:
        raise ValueError("DC target shape does not match feature grid")
    if not np.all(np.isfinite(dc)):
        raise ValueError("DC target must contain only finite values")

    requested = set(int(value) for value in config.fit_harmonics)
    channels: List[FeatureChannel] = []

    def add(
        *,
        channel_id: str,
        block: str,
        harmonic: Optional[int],
        is_requested: bool,
        available: bool,
        active: bool,
        target_weight: float,
        loss_weight: float,
        mask: Optional[np.ndarray],
        reason: Optional[str],
        role: Optional[str] = None,
    ) -> None:
        n_points = int(np.count_nonzero(mask)) if mask is not None else (
            expected_size if active else 0
        )
        channels.append(
            FeatureChannel(
                channel_id=channel_id,
                block=block,
                harmonic=harmonic,
                role=role or _channel_role(harmonic),
                requested=is_requested,
                available=available,
                active=active,
                target_weight=float(target_weight),
                loss_weight=float(loss_weight),
                n_points=n_points,
                mask_sha256=(
                    _mask_sha256(mask) if mask is not None else None
                ),
                exclusion_reason=reason,
                mask=mask,
            )
        )

    full_mask = np.ones(expected_size, dtype=bool)
    add(
        channel_id="dc",
        block="dc",
        harmonic=None,
        is_requested=True,
        available=True,
        active=True,
        target_weight=1.0,
        loss_weight=1.0,
        mask=full_mask,
        reason=None,
    )

    mode = config.feature_mode
    legacy_enabled = mode == "legacy"
    complex_enabled = mode in ("complex_snr", "hybrid", "combined")
    lockin_enabled = mode in ("lockin_only", "hybrid", "combined")

    harmonic_targets = target.get("harm")
    for harmonic in range(1, 8):
        is_requested = harmonic in requested
        reason = None
        available = False
        active = False
        mask = None
        if not legacy_enabled:
            reason = "mode_disabled"
        elif not is_requested:
            reason = "not_requested"
        elif not isinstance(harmonic_targets, (list, tuple)):
            reason = "target_missing"
        elif len(harmonic_targets) < harmonic:
            reason = "target_missing"
        else:
            values = np.asarray(
                harmonic_targets[harmonic - 1], dtype=float
            ).reshape(-1)
            if values.size != expected_size:
                reason = "target_shape_mismatch"
            elif not np.all(np.isfinite(values)):
                reason = "target_nonfinite"
            else:
                available = active = True
                mask = full_mask
        add(
            channel_id=f"legacy_amplitude:H{harmonic}",
            block="legacy_amplitude",
            harmonic=harmonic,
            is_requested=is_requested,
            available=available,
            active=active,
            target_weight=1.0 if active else 0.0,
            loss_weight=1.0 if active else 0.0,
            mask=mask,
            reason=reason,
        )

    complex_target = target.get("complex_harmonics")
    for harmonic in range(1, 8):
        is_requested = harmonic in requested
        pair_reason = None
        pair_available = False
        pair_active = False
        weight = 0.0
        if not complex_enabled:
            pair_reason = "mode_disabled"
        elif not is_requested:
            pair_reason = "not_requested"
        elif not isinstance(complex_target, Mapping):
            pair_reason = "target_missing"
        else:
            arrays = {}
            missing = False
            for name in ("amplitude", "phase", "snr"):
                if name not in complex_target:
                    missing = True
                    break
                arrays[name] = np.asarray(
                    complex_target[name], dtype=float
                ).reshape(-1)
                if arrays[name].size < harmonic:
                    missing = True
                    break
            if missing:
                pair_reason = "target_missing"
            elif not all(
                np.isfinite(arrays[name][harmonic - 1])
                for name in ("amplitude", "phase", "snr")
            ):
                pair_reason = "target_nonfinite"
            else:
                pair_available = True
                weight = float(
                    snr_weights(
                        np.array([arrays["snr"][harmonic - 1]]),
                        floor=config.snr_floor,
                    )[0]
                )
                if weight <= 0.0:
                    pair_reason = "below_snr_floor"
                else:
                    pair_active = True
        for block, phase_scale in (
            ("complex_amplitude", 1.0),
            ("complex_phase", config.phase_weight),
        ):
            add(
                channel_id=f"{block}:H{harmonic}",
                block=block,
                harmonic=harmonic,
                is_requested=is_requested,
                available=pair_available,
                active=pair_active,
                target_weight=weight if pair_active else 0.0,
                loss_weight=(
                    weight * phase_scale if pair_active else 0.0
                ),
                mask=None,
                reason=None if pair_active else pair_reason,
            )

    lockin_target = target.get("lockin")
    for harmonic in range(1, 8):
        is_requested = harmonic in requested
        pair_reason = None
        pair_available = False
        pair_active = False
        mask = None
        if not lockin_enabled:
            pair_reason = "mode_disabled"
        elif not is_requested:
            pair_reason = "not_requested"
        elif not isinstance(lockin_target, Mapping):
            pair_reason = "target_missing"
        else:
            amplitudes = lockin_target.get("amplitude")
            phases = lockin_target.get("phase")
            if (
                not isinstance(amplitudes, (list, tuple))
                or not isinstance(phases, (list, tuple))
                or len(amplitudes) < harmonic
                or len(phases) < harmonic
                or "valid_mask" not in lockin_target
            ):
                pair_reason = "target_missing"
            else:
                amplitude = np.asarray(
                    amplitudes[harmonic - 1], dtype=float
                ).reshape(-1)
                phase = np.asarray(
                    phases[harmonic - 1], dtype=float
                ).reshape(-1)
                valid = np.asarray(
                    lockin_target["valid_mask"], dtype=bool
                ).reshape(-1)
                if (
                    amplitude.size != expected_size
                    or phase.size != expected_size
                    or valid.size != expected_size
                ):
                    pair_reason = "target_shape_mismatch"
                else:
                    pair_available = True
                    mask = valid & np.isfinite(amplitude) & np.isfinite(phase)
                    if np.count_nonzero(mask) < 2:
                        pair_reason = "insufficient_valid_points"
                    else:
                        pair_active = True
        for block, phase_scale in (
            ("lockin_amplitude", 1.0),
            ("lockin_phase", config.phase_weight),
        ):
            add(
                channel_id=f"{block}:H{harmonic}",
                block=block,
                harmonic=harmonic,
                is_requested=is_requested,
                available=pair_available,
                active=pair_active,
                target_weight=1.0 if pair_active else 0.0,
                loss_weight=phase_scale if pair_active else 0.0,
                mask=mask if pair_active else None,
                reason=None if pair_active else pair_reason,
            )

    tafel = target.get("tafel")
    tafel_active = (
        tafel is not None
        and np.asarray(tafel).ndim == 0
        and np.isfinite(float(tafel))
    )
    add(
        channel_id="tafel",
        block="tafel",
        harmonic=None,
        is_requested=True,
        available=tafel_active,
        active=tafel_active,
        target_weight=1.0 if tafel_active else 0.0,
        loss_weight=1.0 if tafel_active else 0.0,
        mask=None,
        reason=None if tafel_active else "not_applicable",
        role="physical",
    )

    normalization = float(
        sum(item.loss_weight for item in channels if item.active)
    )
    evidence = {
        "schema_version": 1,
        "feature_mode": mode,
        "fit_harmonics": sorted(requested),
        "phase_weight": float(config.phase_weight),
        "snr_floor": float(config.snr_floor),
        "normalization_weight_sum": normalization,
        "channels": [item.to_evidence() for item in channels],
    }
    encoded = json.dumps(
        evidence,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode()
    return FeatureChannelContract(
        feature_mode=mode,
        fit_harmonics=tuple(sorted(requested)),
        phase_weight=float(config.phase_weight),
        snr_floor=float(config.snr_floor),
        channels=tuple(channels),
        normalization_weight_sum=normalization,
        sha256=hashlib.sha256(encoded).hexdigest(),
    )


def match_experimental_sampling(
    duration: float,
    frequency: float,
    *,
    points_per_cycle: int = 32,
) -> tuple[int, int]:
    """Return an efficient simulation grid with the experiment's cycle count."""
    if duration <= 0 or frequency <= 0 or points_per_cycle < 2:
        raise ValueError("duration, frequency, and points_per_cycle must be positive")
    cycles = max(1, round(float(duration) * float(frequency)))
    return cycles * int(points_per_cycle), int(points_per_cycle)


@dataclass
class InversionResult:
    """Result returned by :class:`TPEInverter`."""

    success: bool
    best_value: float
    best_x: np.ndarray
    best_params: Dict[str, float]
    n_trials: int
    n_forward: int
    history: List[Dict[str, Any]] = field(default_factory=list)
    n_calls: int = 0
    n_ode_fail: int = 0
    n_feature_fail: int = 0
    n_tafel_fail: int = 0
    fit_quality: Dict[str, Any] = field(default_factory=dict)
    loss_components: Dict[str, float] = field(default_factory=dict)
    channel_contract: Dict[str, Any] = field(default_factory=dict)
    channel_contract_sha256: str = ""
    normalization_weight_sum: float = 0.0


def assess_fit_quality(
    best_value: float,
    feature_grid_size: int,
    fit_harmonics: Sequence[int] = (1, 2, 3, 4, 5, 6, 7),
) -> Dict[str, Any]:
    """Convert the objective value to a human-readable fit-completion signal.

    The objective stores summed squared residuals divided by the channel count.
    This helper converts it back to sigma-unit RMSE per residual element:
    DC + seven harmonics over the common E grid, plus one Tafel residual.
    """

    if not np.isfinite(best_value) or best_value < 0:
        sigma_rmse = float("inf")
    else:
        n_channels = 1 + len(tuple(fit_harmonics))
        n_terms = max(1, n_channels * int(feature_grid_size) + 1)
        divisor = 2.0 + len(tuple(fit_harmonics))
        sigma_rmse = float(np.sqrt((best_value * divisor) / n_terms))

    if sigma_rmse <= 0.75:
        level = "excellent"
        ready = True
        message = "拟合已经进入可人工复核区间，可以开始看参数是否有机理意义。"
    elif sigma_rmse <= 1.25:
        level = "acceptable"
        ready = True
        message = "拟合程度基本够用，建议检查残差分布和参数物理合理性。"
    elif sigma_rmse <= 2.0:
        level = "rough"
        ready = False
        message = "拟合仍偏粗，只适合判断趋势，不建议直接解释机理。"
    else:
        level = "poor"
        ready = False
        message = "拟合不足，优先检查扫描参数、基线、边界和可识别性。"

    if np.isfinite(sigma_rmse):
        completion = float(np.clip(100.0 * (2.0 - sigma_rmse) / 2.0, 0.0, 100.0))
    else:
        completion = 0.0

    return {
        "level": level,
        "ready_for_review": ready,
        "sigma_rmse": sigma_rmse,
        "completion_percent": completion,
        "message": message,
        "fit_harmonics": [int(h) for h in fit_harmonics],
    }


def assess_harmonic_quality(
    harmonics: Sequence[Sequence[float]] | np.ndarray,
    min_relative_rms: float = 0.02,
    min_abs_rms: float = 1e-12,
) -> Dict[str, Any]:
    """Select experimentally resolvable harmonics from raw harmonic envelopes.

    The decision is based on raw amplitude before per-channel normalization.
    A harmonic whose RMS is far below the strongest channel can look large after
    normalization, but it carries weak experimental information and should not
    dominate the inversion objective.
    """

    arr = np.asarray(harmonics, dtype=float)
    if arr.ndim != 2:
        raise ValueError("harmonics must be a 2D array")
    if arr.shape[1] == 7:
        channel_arr = arr
    elif arr.shape[0] == 7:
        channel_arr = arr.T
    else:
        raise ValueError("harmonics must contain 7 channels")

    rms = np.sqrt(np.mean(channel_arr**2, axis=0))
    max_rms = float(np.max(rms)) if rms.size else 0.0
    threshold = max(float(min_abs_rms), float(min_relative_rms) * max(max_rms, 1e-30))
    channels = []
    fit_harmonics = []
    for idx, value in enumerate(rms, start=1):
        dynamic_range = float(np.max(channel_arr[:, idx - 1]) - np.min(channel_arr[:, idx - 1]))
        selected = bool(np.isfinite(value) and value >= threshold and dynamic_range > 0.0)
        if selected:
            fit_harmonics.append(idx)
        channels.append(
            {
                "harmonic": idx,
                "rms": float(value),
                "relative_rms": float(value / max(max_rms, 1e-30)),
                "dynamic_range": dynamic_range,
                "fit": selected,
            }
        )

    return {
        "fit_harmonics": fit_harmonics,
        "threshold_rms": threshold,
        "max_rms": max_rms,
        "channels": channels,
    }


def encode_params(params: Mapping[str, float], specs: Sequence[ParamSpec] = DEFAULT_PARAM_SPECS) -> np.ndarray:
    """Encode physical parameters into optimizer coordinates."""

    x = []
    for name, kind, lo, hi in specs:
        if name not in params:
            raise KeyError(f"Missing parameter: {name}")
        value = float(params[name])
        if kind == "log10":
            if value <= 0:
                raise ValueError(f"{name} must be positive for log10 encoding")
            encoded = float(np.log10(value))
        elif kind == "linear":
            encoded = value
        else:
            raise ValueError(f"Unsupported parameter encoding kind: {kind}")
        if encoded < lo or encoded > hi:
            raise ValueError(f"{name} encoded value {encoded:g} outside bounds [{lo:g}, {hi:g}]")
        x.append(encoded)
    return np.asarray(x, dtype=float)


def decode_vector(x: Sequence[float], specs: Sequence[ParamSpec] = DEFAULT_PARAM_SPECS) -> Dict[str, float]:
    """Decode optimizer coordinates into physical parameter values."""

    arr = np.asarray(x, dtype=float).reshape(-1)
    if len(arr) != len(specs):
        raise ValueError(f"Expected {len(specs)} parameters, got {len(arr)}")
    decoded: Dict[str, float] = {}
    for (name, kind, _, _), value in zip(specs, arr):
        if kind == "log10":
            decoded[name] = float(10.0 ** value)
        elif kind == "linear":
            decoded[name] = float(value)
        else:
            raise ValueError(f"Unsupported parameter encoding kind: {kind}")
    return decoded


def normalize_vector(x: Sequence[float], specs: Sequence[ParamSpec] = DEFAULT_PARAM_SPECS) -> np.ndarray:
    """Map encoded optimizer coordinates to unit coordinates.

    The values in ``x`` are already in encoded coordinates: log10 for kinetic
    constants and gamma, linear for thermodynamic terms. Normalizing this layer
    keeps the search geometry comparable without changing the physical model.
    """

    arr = np.asarray(x, dtype=float).reshape(-1)
    if len(arr) != len(specs):
        raise ValueError(f"Expected {len(specs)} parameters, got {len(arr)}")
    z = []
    for value, (name, _, lo, hi) in zip(arr, specs):
        width = float(hi - lo)
        if width <= 0:
            raise ValueError(f"{name} has invalid bounds [{lo:g}, {hi:g}]")
        if value < lo or value > hi:
            raise ValueError(f"{name} encoded value {value:g} outside bounds [{lo:g}, {hi:g}]")
        z.append((float(value) - lo) / width)
    return np.asarray(z, dtype=float)


def denormalize_vector(z: Sequence[float], specs: Sequence[ParamSpec] = DEFAULT_PARAM_SPECS) -> np.ndarray:
    """Map unit coordinates back to encoded optimizer coordinates."""

    arr = np.asarray(z, dtype=float).reshape(-1)
    if len(arr) != len(specs):
        raise ValueError(f"Expected {len(specs)} parameters, got {len(arr)}")
    x = []
    for value, (name, _, lo, hi) in zip(arr, specs):
        if value < 0.0 or value > 1.0:
            raise ValueError(f"{name} normalized value {value:g} outside [0, 1]")
        x.append(float(lo) + float(value) * float(hi - lo))
    return np.asarray(x, dtype=float)


def make_param_specs_from_physical_bounds(
    bounds: Mapping[str, Sequence[float]],
    specs: Sequence[ParamSpec] = DEFAULT_PARAM_SPECS,
) -> Tuple[ParamSpec, ...]:
    """Override parameter bounds using physical units.

    For log-encoded parameters the caller supplies physical positive bounds,
    e.g. ``k0_1: (1, 1e4)``, and this function converts them to log10 bounds.
    Linear parameters are kept in their original physical units.
    """

    overrides = {str(k): tuple(v) for k, v in bounds.items()}
    names = {name for name, _, _, _ in specs}
    unknown = sorted(set(overrides) - names)
    if unknown:
        raise KeyError(f"Unknown parameter bounds: {', '.join(unknown)}")

    updated: List[ParamSpec] = []
    for name, kind, lo, hi in specs:
        if name not in overrides:
            updated.append((name, kind, lo, hi))
            continue
        raw = overrides[name]
        if len(raw) != 2:
            raise ValueError(f"{name} bounds must contain [low, high]")
        phys_lo, phys_hi = float(raw[0]), float(raw[1])
        if not np.isfinite(phys_lo) or not np.isfinite(phys_hi) or phys_lo >= phys_hi:
            raise ValueError(f"{name} bounds must be finite and increasing")
        if kind == "log10":
            if phys_lo <= 0.0 or phys_hi <= 0.0:
                raise ValueError(f"{name} log10 bounds must be positive in physical units")
            lo_new, hi_new = float(np.log10(phys_lo)), float(np.log10(phys_hi))
        elif kind == "linear":
            lo_new, hi_new = phys_lo, phys_hi
        else:
            raise ValueError(f"Unsupported parameter encoding kind: {kind}")
        updated.append((name, kind, lo_new, hi_new))
    return tuple(updated)


@lru_cache(maxsize=16)
def _cached_base_params(config: InversionConfig) -> Dict[str, Any]:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        params = initialize_oer_parameters()
    params.update(
        {
            "E_start": config.E_start,
            "E_end": config.E_end,
            "f": config.f,
            "dE": config.dE,
            "n_points": config.n_points,
            "points_per_cycle": config.points_per_cycle,
            "total_time": config.total_time,
            "v": config.scan_rate,
            "omega": 2.0 * np.pi * config.f,
            "t_span": config.t_span.copy(),
            "band": np.ones(8),
            "use_fft": True,
        }
    )
    params.update({name: float(value) for name, value in config.fixed_params})
    return params


def _base_params(config: InversionConfig) -> Dict[str, Any]:
    return copy.deepcopy(_cached_base_params(config))


def params_from_vector(
    x: Sequence[float],
    config: InversionConfig,
    specs: Sequence[ParamSpec] = DEFAULT_PARAM_SPECS,
) -> Dict[str, Any]:
    """Build a full forward-model parameter dictionary from an encoded vector."""

    params = _base_params(config)
    params.update(decode_vector(x, specs))
    params = apply_alkaline_aem(params)
    params = OERPhysics.initialize_system(params)
    return params


def forward_current(
    x: Sequence[float],
    config: InversionConfig,
    specs: Sequence[ParamSpec] = DEFAULT_PARAM_SPECS,
) -> Optional[np.ndarray]:
    """Run the selected mechanistic solver and return total current.

    ``cn`` never falls back, ``lsoda`` never calls C++, and ``auto`` preserves
    the historical C++-first behavior with an LSODA fallback.
    """
    params = params_from_vector(x, config, specs)
    backend = str(config.solver_backend).lower()
    if backend not in {"auto", "cn", "lsoda"}:
        raise ValueError("solver_backend must be 'auto', 'cn', or 'lsoda'")

    if backend in {"auto", "cn"}:
        try:
            from .cpp_bridge import is_available, solve_cn
            if is_available():
                y0 = np.zeros(6, dtype=float)
                y0[0] = 1.0
                y0[5] = params["E_start"]
                if params.get("use_steady_state", True):
                    y0 = OERPhysics.calculate_steady_state(params)
                current = solve_cn(params, y0=y0)
                if current is not None and current.size == config.n_points:
                    return np.asarray(current, dtype=float).reshape(-1)
        except Exception:
            if backend == "cn":
                return None
        if backend == "cn":
            return None

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        _, _, _, current = OERPhysics.solve_ode_system(params)
    current = np.asarray(current, dtype=float).reshape(-1)
    if current.size != config.n_points or not np.all(np.isfinite(current)):
        return None
    return current


def _normalize_envelope(values: np.ndarray) -> np.ndarray:
    scale = float(np.max(np.abs(values)))
    if not np.isfinite(scale) or scale <= 1e-30:
        scale = 1e-30
    return values / scale


def _interpolate_lockin_to_grid(
    lockin: Mapping[str, Any],
    source_e: Sequence[float],
    target_e: Sequence[float],
) -> Dict[str, Any]:
    """Interpolate complex lock-in envelopes and preserve wrapped phase."""
    source = np.asarray(source_e, dtype=float).reshape(-1)
    target = np.asarray(target_e, dtype=float).reshape(-1)
    valid = np.asarray(lockin["valid_mask"], dtype=bool).reshape(-1)
    if source.size != valid.size or source.size < 2:
        raise ValueError("source_e and valid_mask must have the same length")
    valid &= np.isfinite(source)
    if np.count_nonzero(valid) < 2:
        raise ValueError("lock-in interpolation requires at least two valid points")

    order = np.argsort(source[valid])
    valid_source = source[valid][order]
    valid_source, unique_indices = np.unique(valid_source, return_index=True)
    grid_valid = (target >= valid_source[0]) & (target <= valid_source[-1])
    amplitudes: List[np.ndarray] = []
    phases: List[np.ndarray] = []
    complex_channels: List[np.ndarray] = []

    for channel in lockin["complex"]:
        values = np.asarray(channel, dtype=complex).reshape(-1)
        if values.size != source.size:
            raise ValueError("lock-in complex channels must match source_e")
        valid_values = values[valid][order][unique_indices]
        real = np.interp(target, valid_source, valid_values.real)
        imag = np.interp(target, valid_source, valid_values.imag)
        mapped = real + 1j * imag
        mapped[~grid_valid] = np.nan + 1j * np.nan
        complex_channels.append(mapped)
        amplitudes.append(np.abs(mapped))
        phases.append(np.angle(mapped))

    return {
        "complex": complex_channels,
        "amplitude": amplitudes,
        "phase": phases,
        "valid_mask": grid_valid,
        "fc_used": float(lockin["fc_used"]),
        "effective_resolution_v": float(lockin["effective_resolution_v"]),
    }


def extract_features(current: Sequence[float], config: InversionConfig) -> Dict[str, Any]:
    """Extract normalized DC/harmonic envelopes and Tafel slope."""

    current_arr = np.asarray(current, dtype=float).reshape(-1)
    signal_params = {"f": config.f, "band": np.ones(8), "use_fft": True}
    dc_all = np.asarray(OERSignal.extract_dc_fft(current_arr, config.sample_rate, signal_params)).reshape(-1)
    harm_all = np.asarray(OERSignal.extract_harmonics(current_arr, config.sample_rate, signal_params))

    i0 = config.discard_index
    tdc_trim = config.tdc[i0:]
    dc = dc_all[i0:]
    harms = harm_all[i0:, :]
    e_grid = config.e_grid

    features: Dict[str, Any] = {
        "dc": np.interp(e_grid, tdc_trim, _normalize_envelope(dc)),
        "harm": [],
    }
    n_required = max(config.fit_harmonics, default=0)
    n_envelopes = 7 if config.feature_mode == "legacy" else max(3, n_required)
    for idx in range(n_envelopes):
        h = harms[:, idx]
        features["harm"].append(np.interp(e_grid, tdc_trim, _normalize_envelope(h)))

    tafel = measure_tafel(tdc_trim, dc)
    features["tafel"] = float(tafel["tafel_slope"]) if tafel.get("success") else None
    features["e_grid"] = e_grid
    if config.feature_mode in ("complex_snr", "hybrid", "combined"):
        features["complex_harmonics"] = complex_harmonic_metrics(
            current_arr[i0:],
            fs=config.sample_rate,
            f0=config.f,
            n_harmonics=n_required,
        )
    if config.feature_mode in ("lockin_only", "hybrid", "combined"):
        from .signal import lockin_harmonics
        t_trim = config.t_span[i0:]
        lockin = lockin_harmonics(
            current_arr[i0:], t_trim,
            f0=config.f, harmonics=tuple(range(1, n_required + 1)),
            potential_resolution=0.05,
            scan_rate=config.scan_rate,
            reference_phase=2.0 * np.pi * config.f * t_trim - np.pi / 2.0,
        )
        features["lockin"] = _interpolate_lockin_to_grid(
            lockin,
            tdc_trim,
            e_grid,
        )
    return features


def make_synthetic_target(
    truth: Mapping[str, float],
    config: Optional[InversionConfig] = None,
    noise_fraction: float = 0.0,
    seed: Optional[int] = None,
) -> Dict[str, Any]:
    """Generate an inverse-crime synthetic target from physical truth parameters."""

    cfg = config or InversionConfig()
    x_true = encode_params(truth, cfg.param_specs)
    current = forward_current(x_true, cfg, cfg.param_specs)
    if current is None:
        raise RuntimeError("Synthetic truth forward simulation failed")

    noisy = np.asarray(current, dtype=float).copy()
    if noise_fraction > 0:
        rng = np.random.default_rng(cfg.seed if seed is None else seed)
        sigma = noise_fraction * float(np.max(np.abs(noisy)))
        noisy = noisy + rng.normal(0.0, sigma, size=noisy.shape)

    features = extract_features(noisy, cfg)

    features.update(
        {
            "truth_params": dict(truth),
            "truth_x": x_true,
            "current": noisy,
            "max_abs_i": float(np.max(np.abs(current))),
            "noise_fraction": float(noise_fraction),
        }
    )
    return features


class InversionObjective:
    """Callable objective for FTacV inversion."""

    def __init__(
        self,
        target: Mapping[str, Any],
        config: Optional[InversionConfig] = None,
        specs: Sequence[ParamSpec] = DEFAULT_PARAM_SPECS,
    ) -> None:
        self.target = target
        self.config = config or InversionConfig()
        self.specs = tuple(specs)
        self.n_calls = 0
        self.n_forward = 0
        self.n_ode_fail = 0
        self.n_feature_fail = 0
        self.n_tafel_fail = 0
        self.best_value = np.inf
        self.best_x: Optional[np.ndarray] = None
        self.last_components: Dict[str, float] = {}
        self.best_components: Dict[str, float] = {}
        self.fit_harmonics = tuple(int(h) for h in self.config.fit_harmonics)
        if self.config.feature_mode not in {
            "legacy",
            "complex_snr",
            "lockin_only",
            "hybrid",
            "combined",
        }:
            raise ValueError(
                "feature_mode must be 'legacy', 'complex_snr', 'lockin_only', "
                "'hybrid', or the legacy alias 'combined'"
            )
        invalid = [h for h in self.fit_harmonics if h < 1 or h > 7]
        if invalid:
            raise ValueError(f"fit_harmonics must be between 1 and 7, got {invalid}")
        self.channel_contract = build_feature_channel_contract(
            self.target, self.config
        )

    @staticmethod
    def _empty_components() -> Dict[str, float]:
        return {
            "dc": 0.0,
            "common_harmonics": 0.0,
            "dataset_specific_harmonics": 0.0,
            "phase": 0.0,
            "lockin_common_amplitude": 0.0,
            "lockin_dataset_specific_amplitude": 0.0,
            "lockin_common_phase": 0.0,
            "lockin_dataset_specific_phase": 0.0,
            "physical": 0.0,
            "feature_failure": 0.0,
        }

    def _active_channels(self, block: str) -> List[FeatureChannel]:
        return [
            item
            for item in self.channel_contract.channels
            if item.active and item.block == block
        ]

    def _candidate_features_valid(self, features: Mapping[str, Any]) -> bool:
        expected_size = self.config.resolved_feature_grid_size
        try:
            dc = np.asarray(features["dc"], dtype=float).reshape(-1)
            if dc.size != expected_size or not np.all(np.isfinite(dc)):
                return False
            harmonics = features.get("harm")
            for channel in self._active_channels("legacy_amplitude"):
                index = int(channel.harmonic) - 1
                if not isinstance(harmonics, (list, tuple)):
                    return False
                if len(harmonics) <= index:
                    return False
                values = np.asarray(harmonics[index], dtype=float).reshape(-1)
                if (
                    values.size != expected_size
                    or not np.all(np.isfinite(values))
                ):
                    return False
            complex_values = features.get("complex_harmonics")
            for block in ("complex_amplitude", "complex_phase"):
                name = "amplitude" if block.endswith("amplitude") else "phase"
                for channel in self._active_channels(block):
                    index = int(channel.harmonic) - 1
                    if (
                        not isinstance(complex_values, Mapping)
                        or name not in complex_values
                    ):
                        return False
                    values = np.asarray(
                        complex_values[name], dtype=float
                    ).reshape(-1)
                    if values.size <= index or not np.isfinite(values[index]):
                        return False
            lockin = features.get("lockin")
            active_lockin = self._active_channels("lockin_amplitude")
            active_lockin += self._active_channels("lockin_phase")
            if active_lockin:
                if not isinstance(lockin, Mapping):
                    return False
                candidate_valid = np.asarray(
                    lockin.get("valid_mask"), dtype=bool
                ).reshape(-1)
                if candidate_valid.size != expected_size:
                    return False
            for channel in active_lockin:
                index = int(channel.harmonic) - 1
                name = (
                    "amplitude"
                    if channel.block.endswith("amplitude")
                    else "phase"
                )
                arrays = lockin.get(name)
                if not isinstance(arrays, (list, tuple)) or len(arrays) <= index:
                    return False
                values = np.asarray(arrays[index], dtype=float).reshape(-1)
                mask = np.asarray(channel.mask, dtype=bool)
                if (
                    values.size != expected_size
                    or not np.all(candidate_valid[mask])
                    or not np.all(np.isfinite(values[mask]))
                ):
                    return False
        except (KeyError, TypeError, ValueError):
            return False
        return True

    def _evaluate(self, x: np.ndarray) -> float:
        self.n_forward += 1
        current = forward_current(x, self.config, self.specs)
        if current is None:
            self.n_ode_fail += 1
            self.last_components = self._empty_components()
            self.last_components["physical"] = float(
                self.config.ode_penalty
            )
            return float(self.config.ode_penalty)

        features = extract_features(current, self.config)
        if not self._candidate_features_valid(features):
            self.n_feature_fail += 1
            self.last_components = self._empty_components()
            self.last_components["feature_failure"] = float(
                self.config.feature_fail_penalty
            )
            return float(self.config.feature_fail_penalty)

        components = self._empty_components()
        dc_channel = self._active_channels("dc")[0]
        components["dc"] = float(
            dc_channel.loss_weight
            * np.mean(
                (
                    (
                        np.asarray(features["dc"])
                        - np.asarray(self.target["dc"])
                    )
                    / self.config.sigma_dc
                )
                ** 2
            )
        )

        for channel in self._active_channels("legacy_amplitude"):
            index = int(channel.harmonic) - 1
            loss = float(
                channel.loss_weight
                * np.mean(
                    (
                        (
                            np.asarray(features["harm"][index])
                            - np.asarray(self.target["harm"][index])
                        )
                        / self.config.sigma_harm
                    )
                    ** 2
                )
            )
            key = (
                "common_harmonics"
                if channel.role == "common"
                else "dataset_specific_harmonics"
            )
            components[key] += loss

        complex_amplitude_channels = self._active_channels(
            "complex_amplitude"
        )
        if complex_amplitude_channels:
            target_amplitudes = np.asarray(
                self.target["complex_harmonics"]["amplitude"], dtype=float
            )
            amplitude_scale = max(
                max(
                    abs(target_amplitudes[int(item.harmonic) - 1])
                    for item in complex_amplitude_channels
                ),
                np.finfo(float).eps,
            )
            simulated_amplitudes = np.asarray(
                features["complex_harmonics"]["amplitude"], dtype=float
            )
            for channel in complex_amplitude_channels:
                index = int(channel.harmonic) - 1
                residual = (
                    (
                        simulated_amplitudes[index]
                        - target_amplitudes[index]
                    )
                    / amplitude_scale
                    / self.config.sigma_harm
                )
                key = (
                    "common_harmonics"
                    if channel.role == "common"
                    else "dataset_specific_harmonics"
                )
                components[key] += float(
                    channel.loss_weight * residual**2
                )

        for channel in self._active_channels("complex_phase"):
            index = int(channel.harmonic) - 1
            residual = wrapped_phase_difference(
                np.asarray(
                    features["complex_harmonics"]["phase"], dtype=float
                )[index],
                np.asarray(
                    self.target["complex_harmonics"]["phase"], dtype=float
                )[index],
            )
            components["phase"] += float(
                channel.loss_weight * residual**2
            )

        for block, component_common, component_specific in (
            (
                "lockin_amplitude",
                "lockin_common_amplitude",
                "lockin_dataset_specific_amplitude",
            ),
            (
                "lockin_phase",
                "lockin_common_phase",
                "lockin_dataset_specific_phase",
            ),
        ):
            name = "amplitude" if block.endswith("amplitude") else "phase"
            for channel in self._active_channels(block):
                index = int(channel.harmonic) - 1
                mask = np.asarray(channel.mask, dtype=bool)
                simulated = np.asarray(
                    features["lockin"][name][index], dtype=float
                )[mask]
                experimental = np.asarray(
                    self.target["lockin"][name][index], dtype=float
                )[mask]
                if name == "amplitude":
                    scale = max(
                        float(np.max(np.abs(experimental))),
                        np.finfo(float).eps,
                    )
                    residual = (
                        (simulated - experimental)
                        / scale
                        / self.config.sigma_harm
                    )
                else:
                    residual = wrapped_phase_difference(
                        simulated, experimental
                    )
                key = (
                    component_common
                    if channel.role == "common"
                    else component_specific
                )
                components[key] += float(
                    channel.loss_weight * np.mean(residual**2)
                )

        tafel_channels = self._active_channels("tafel")
        if tafel_channels:
            channel = tafel_channels[0]
            if features.get("tafel") is None:
                self.n_tafel_fail += 1
                components["physical"] += float(
                    channel.loss_weight * self.config.tafel_fail_resid**2
                )
            else:
                components["physical"] += float(
                    channel.loss_weight
                    * (
                        (
                            float(features["tafel"])
                            - float(self.target["tafel"])
                        )
                        / self.config.sigma_tafel
                    )
                    ** 2
                )

        self.last_components = components
        return float(
            sum(components.values())
            / self.channel_contract.normalization_weight_sum
        )

    def __call__(self, x: Sequence[float]) -> float:
        arr = np.asarray(x, dtype=float).reshape(-1)
        self.n_calls += 1
        value = self._evaluate(arr)
        if value < self.best_value:
            self.best_value = float(value)
            self.best_x = arr.copy()
            self.best_components = dict(self.last_components)
        return float(value)


class TPEInverter:
    """Small Optuna TPE wrapper for mechanistic parameter inversion."""

    def __init__(
        self,
        config: Optional[InversionConfig] = None,
        specs: Sequence[ParamSpec] = DEFAULT_PARAM_SPECS,
        seed: Optional[int] = None,
        n_startup_trials: int = 10,
        initial_params: Optional[Mapping[str, float]] = None,
    ) -> None:
        self.config = config or InversionConfig()
        self.specs = tuple(specs)
        self.seed = self.config.seed if seed is None else seed
        self.n_startup_trials = n_startup_trials
        self.initial_params = dict(initial_params) if initial_params is not None else None

    def _suggest(self, trial: Any) -> np.ndarray:
        z_values = []
        for name, kind, lo, hi in self.specs:
            if kind not in {"log10", "linear"}:
                raise ValueError(f"Unsupported parameter encoding kind: {kind}")
            z_values.append(trial.suggest_float(f"z_{name}", 0.0, 1.0))
        return denormalize_vector(z_values, self.specs)

    def run(self, target: Mapping[str, Any], n_trials: int = 100) -> InversionResult:
        objective = InversionObjective(target, self.config, self.specs)
        return self.run_objective(objective, n_trials=n_trials)

    def run_objective(self, objective: Any, n_trials: int = 100) -> InversionResult:
        """Run the frozen Optuna loop for any inversion-objective protocol."""
        import optuna

        if n_trials < 1:
            raise ValueError("n_trials must be positive")
        optuna.logging.set_verbosity(optuna.logging.WARNING)
        sampler = optuna.samplers.TPESampler(
            seed=self.seed,
            n_startup_trials=min(self.n_startup_trials, max(1, n_trials)),
        )
        study = optuna.create_study(direction="minimize", sampler=sampler)
        initial_x: Optional[np.ndarray] = None
        if self.initial_params is not None:
            initial_x = encode_params(self.initial_params, self.specs)
            initial_z = normalize_vector(initial_x, self.specs)
            study.enqueue_trial(
                {f"z_{name}": float(value) for (name, _, _, _), value in zip(self.specs, initial_z)}
            )
        history: List[Dict[str, Any]] = []

        def optuna_objective(trial: Any) -> float:
            if trial.number == 0 and initial_x is not None:
                return objective(initial_x)
            return objective(self._suggest(trial))

        def callback(study_: Any, trial: Any) -> None:
            if trial.value is None:
                return
            history.append(
                {
                    "trial": len(history) + 1,
                    "value": float(trial.value),
                    "best_so_far": float(study_.best_value),
                    "n_forward": objective.n_forward,
                    "source": "initial" if trial.number == 0 and self.initial_params is not None else "tpe",
                }
            )

        study.optimize(optuna_objective, n_trials=n_trials, callbacks=[callback])
        best_x = objective.best_x
        if best_x is None:
            best_z = np.asarray([study.best_params[f"z_{name}"] for name, _, _, _ in self.specs], dtype=float)
            best_x = denormalize_vector(best_z, self.specs)
        channel_contract_object = getattr(objective, "channel_contract", None)
        if channel_contract_object is not None:
            channel_contract = channel_contract_object.to_evidence()
            channel_contract_sha256 = str(channel_contract_object.sha256)
            normalization_weight_sum = float(
                channel_contract_object.normalization_weight_sum
            )
        else:
            channel_contract = {}
            channel_contract_sha256 = ""
            normalization_weight_sum = 0.0
        return InversionResult(
            success=bool(len(study.trials) == n_trials and np.isfinite(study.best_value)),
            best_value=float(study.best_value),
            best_x=np.asarray(best_x, dtype=float),
            best_params=decode_vector(best_x, self.specs),
            n_trials=int(len(study.trials)),
            n_forward=int(objective.n_forward),
            history=history,
            n_calls=int(objective.n_calls),
            n_ode_fail=int(objective.n_ode_fail),
            n_feature_fail=int(objective.n_feature_fail),
            n_tafel_fail=int(objective.n_tafel_fail),
            fit_quality=assess_fit_quality(
                float(study.best_value),
                self.config.resolved_feature_grid_size,
                self.config.fit_harmonics,
            ),
            loss_components=dict(objective.best_components),
            channel_contract=channel_contract,
            channel_contract_sha256=channel_contract_sha256,
            normalization_weight_sum=normalization_weight_sum,
        )
