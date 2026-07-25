"""TPE-based inversion utilities for alkaline OER FTacV microkinetics.

This module promotes the benchmark inversion pipeline into a reusable core API:
parameter encoding, synthetic target generation, objective evaluation, and a
small Optuna TPE wrapper.  It intentionally keeps the mechanistic forward model
explicit; the optimizer only searches physically named AEM parameters.
"""

from __future__ import annotations

import contextlib
import copy
import io
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
    feature_grid_size: int = 200
    discard_fraction: float = 0.25
    sigma_dc: float = 0.02
    sigma_harm: float = 0.05
    sigma_tafel: float = 0.05
    ode_penalty: float = 1e9
    tafel_fail_resid: float = 10.0
    seed: int = 42
    param_specs: Tuple[ParamSpec, ...] = DEFAULT_PARAM_SPECS
    fixed_params: Tuple[Tuple[str, float], ...] = ()
    fit_harmonics: Tuple[int, ...] = (1, 2, 3, 4, 5, 6, 7)
    feature_mode: str = "legacy"
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
    def e_grid(self) -> np.ndarray:
        tdc_trim = self.tdc[self.discard_index :]
        return np.linspace(float(tdc_trim[0]), float(tdc_trim[-1]), self.feature_grid_size)


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
    n_tafel_fail: int = 0
    fit_quality: Dict[str, Any] = field(default_factory=dict)
    loss_components: Dict[str, float] = field(default_factory=dict)


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
    """Run the mechanistic forward model and return total current.

    Tries the compiled C++ Crank-Nicolson solver first; falls back to
    scipy LSODA if the library is unavailable or the C++ solver fails.
    """
    params = params_from_vector(x, config, specs)

    # --- C++ fast path ---
    try:
        from .cpp_bridge import is_available, solve_cn
        if is_available():
            current = solve_cn(params)
            if current is not None and current.size == config.n_points:
                return np.asarray(current, dtype=float).reshape(-1)
    except Exception:
        pass  # fall through to scipy

    # --- scipy fallback ---
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
    n_envelopes = n_required if config.feature_mode == "complex_snr" else 7
    for idx in range(n_envelopes):
        h = harms[:, idx]
        features["harm"].append(np.interp(e_grid, tdc_trim, _normalize_envelope(h)))

    tafel = measure_tafel(tdc_trim, dc)
    features["tafel"] = float(tafel["tafel_slope"]) if tafel.get("success") else None
    features["e_grid"] = e_grid
    if config.feature_mode == "complex_snr":
        features["complex_harmonics"] = complex_harmonic_metrics(
            current_arr[i0:],
            fs=config.sample_rate,
            f0=config.f,
            n_harmonics=n_required,
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
        self.n_tafel_fail = 0
        self.best_value = np.inf
        self.best_x: Optional[np.ndarray] = None
        self.last_components: Dict[str, float] = {}
        self.best_components: Dict[str, float] = {}
        self.fit_harmonics = tuple(int(h) for h in self.config.fit_harmonics)
        if self.config.feature_mode not in {"legacy", "complex_snr"}:
            raise ValueError(
                "feature_mode must be either 'legacy' or 'complex_snr'"
            )
        invalid = [h for h in self.fit_harmonics if h < 1 or h > 7]
        if invalid:
            raise ValueError(f"fit_harmonics must be between 1 and 7, got {invalid}")

    def _evaluate(self, x: np.ndarray) -> float:
        self.n_forward += 1
        current = forward_current(x, self.config, self.specs)
        if current is None:
            self.n_ode_fail += 1
            self.last_components = {
                "dc": 0.0,
                "common_harmonics": 0.0,
                "dataset_specific_harmonics": 0.0,
                "phase": 0.0,
                "physical": float(self.config.ode_penalty),
            }
            return float(self.config.ode_penalty)

        features = extract_features(current, self.config)
        dc_loss = float(
            np.sum(
                (
                    (features["dc"] - self.target["dc"])
                    / self.config.sigma_dc
                )
                ** 2
            )
        )
        common_harmonic_loss = 0.0
        dataset_specific_harmonic_loss = 0.0
        phase_loss = 0.0
        if self.config.feature_mode == "legacy":
            for harmonic in self.fit_harmonics:
                idx = harmonic - 1
                channel_loss = float(
                    np.sum(
                        (
                            (
                                features["harm"][idx]
                                - self.target["harm"][idx]
                            )
                            / self.config.sigma_harm
                        )
                        ** 2
                    )
                )
                if harmonic <= 3:
                    common_harmonic_loss += channel_loss
                else:
                    dataset_specific_harmonic_loss += channel_loss
        else:
            selected = np.asarray(self.fit_harmonics, dtype=int) - 1
            simulated = features["complex_harmonics"]
            experimental = self.target["complex_harmonics"]
            weights = snr_weights(
                np.asarray(experimental["snr"])[selected],
                floor=self.config.snr_floor,
            )
            target_amplitude = np.asarray(experimental["amplitude"])[selected]
            simulated_amplitude = np.asarray(simulated["amplitude"])[selected]
            amplitude_scale = max(
                float(np.max(np.abs(target_amplitude))),
                np.finfo(float).eps,
            )
            amplitude_residual = (
                (simulated_amplitude - target_amplitude)
                / amplitude_scale
                / self.config.sigma_harm
            )
            channel_losses = weights * amplitude_residual**2
            common_mask = np.asarray(self.fit_harmonics) <= 3
            common_harmonic_loss = float(np.sum(channel_losses[common_mask]))
            dataset_specific_harmonic_loss = float(
                np.sum(channel_losses[~common_mask])
            )
            phase_residual = wrapped_phase_difference(
                np.asarray(simulated["phase"])[selected],
                np.asarray(experimental["phase"])[selected],
            )
            phase_loss = float(
                self.config.phase_weight
                * np.sum(weights * phase_residual**2)
            )

        physical_loss = 0.0
        target_tafel = self.target.get("tafel")
        if target_tafel is not None:
            if features["tafel"] is None:
                self.n_tafel_fail += 1
                physical_loss += self.config.tafel_fail_resid**2
            else:
                physical_loss += float(
                    (
                        (features["tafel"] - float(target_tafel))
                        / self.config.sigma_tafel
                    )
                    ** 2
                )
        self.last_components = {
            "dc": dc_loss,
            "common_harmonics": common_harmonic_loss,
            "dataset_specific_harmonics": dataset_specific_harmonic_loss,
            "phase": phase_loss,
            "physical": physical_loss,
        }
        total = sum(self.last_components.values())
        return total / float(2 + len(self.fit_harmonics))

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
        import optuna

        optuna.logging.set_verbosity(optuna.logging.WARNING)
        objective = InversionObjective(target, self.config, self.specs)
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
            n_tafel_fail=int(objective.n_tafel_fail),
            fit_quality=assess_fit_quality(
                float(study.best_value),
                self.config.feature_grid_size,
                self.config.fit_harmonics,
            ),
            loss_components=dict(objective.best_components),
        )
