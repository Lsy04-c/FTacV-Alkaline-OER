"""Frozen multi-protocol synthetic-recovery contracts for pre-experiment A6-v2."""

from __future__ import annotations

import json
import hashlib
import math
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping, Sequence

import numpy as np

from .inversion import InversionConfig, ParamSpec


FROZEN_PORTFOLIOS = {
    "P0": ("baseline_5hz_amp_016",),
    "P1": ("baseline_5hz_amp_016", "candidate_5hz_amp_008"),
    "P2": (
        "baseline_5hz_amp_016",
        "candidate_5hz_amp_008",
        "candidate_10hz_matched_scan",
    ),
}
FROZEN_PARAMETER_PAIRS = (
    ("k0_2", "k0_3"),
    ("k0_3", "G_O"),
    ("G_OH", "G_O"),
)
FROZEN_TRUTHS = ("center", "mixed_a", "mixed_b")
FROZEN_OPTIMIZER_SEEDS = (7, 17, 27)
FROZEN_THRESHOLDS = {
    "max_median_normalized_bound_error": 0.025,
    "max_normalized_bound_error": 0.05,
    "max_seed_normalized_bound_dispersion": 0.05,
    "max_boundary_hit_rate": 0.0,
    "require_all_studies_success": True,
}


@dataclass(frozen=True)
class ProtocolCondition:
    condition_id: str
    E_start: float
    E_end: float
    f: float
    dE: float
    cycles: int
    points_per_cycle: int

    @property
    def n_points(self) -> int:
        return self.cycles * self.points_per_cycle


@dataclass(frozen=True)
class PreExperimentRecoverySpec:
    schema_version: int
    design_id: str
    model_id: str
    beta_recon: float
    conditions: Mapping[str, ProtocolCondition]
    portfolios: Mapping[str, tuple[str, ...]]
    parameter_pairs: tuple[tuple[str, str], ...]
    truth_ids: tuple[str, ...]
    optimizer_seeds: tuple[int, ...]
    trials: int
    feature_mode: str
    fit_harmonics: tuple[int, ...]
    feature_grid_size: int
    formal_backend: str
    noise_fractions: Mapping[str, float]
    noise_evidence: str
    thresholds: Mapping[str, float | bool]
    stop_s2_if_all_p2_fail_s1: bool


def _require_finite(value: object, name: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be numeric") from exc
    if not math.isfinite(number):
        raise ValueError(f"{name} must be finite")
    return number


def _reject_constant(name: str) -> None:
    raise ValueError(f"non-standard JSON constant rejected: {name}")


def load_pre_experiment_spec(path: str | Path) -> PreExperimentRecoverySpec:
    """Load the immutable, pre-registered A6-v2 scientific contract."""
    try:
        payload = json.loads(
            Path(path).read_text(encoding="utf-8"),
            parse_constant=_reject_constant,
        )
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot load pre-experiment recovery spec: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError("pre-experiment recovery spec must be an object")

    model = payload.get("model")
    window = payload.get("potential_window")
    raw_conditions = payload.get("conditions")
    if not isinstance(model, dict) or not isinstance(window, dict):
        raise ValueError("model and potential_window must be objects")
    if not isinstance(raw_conditions, dict) or not raw_conditions:
        raise ValueError("conditions must be a non-empty object")

    e_start = _require_finite(window.get("E_start"), "E_start")
    e_end = _require_finite(window.get("E_end"), "E_end")
    if e_end <= e_start:
        raise ValueError("E_end must be greater than E_start")
    conditions: dict[str, ProtocolCondition] = {}
    for condition_id, raw in raw_conditions.items():
        if not isinstance(condition_id, str) or not isinstance(raw, dict):
            raise ValueError("condition entries must be named objects")
        f = _require_finite(raw.get("f"), f"{condition_id}.f")
        dE = _require_finite(raw.get("dE"), f"{condition_id}.dE")
        cycles = raw.get("cycles")
        points = raw.get("points_per_cycle")
        if (
            not isinstance(cycles, int)
            or isinstance(cycles, bool)
            or cycles < 1
            or not isinstance(points, int)
            or isinstance(points, bool)
            or points < 2
            or f <= 0.0
            or dE <= 0.0
        ):
            raise ValueError(f"invalid sampling contract for {condition_id}")
        conditions[condition_id] = ProtocolCondition(
            condition_id=condition_id,
            E_start=e_start,
            E_end=e_end,
            f=f,
            dE=dE,
            cycles=cycles,
            points_per_cycle=points,
        )

    raw_portfolios = payload.get("portfolios")
    if not isinstance(raw_portfolios, dict):
        raise ValueError("portfolios must be an object")
    portfolios = {
        str(name): tuple(str(item) for item in values)
        for name, values in raw_portfolios.items()
        if isinstance(values, list)
    }
    if portfolios != FROZEN_PORTFOLIOS or len(portfolios) != len(raw_portfolios):
        raise ValueError("portfolios must equal the frozen nested P0/P1/P2 contract")
    if any(item not in conditions for values in portfolios.values() for item in values):
        raise ValueError("portfolio references an unknown condition")

    pairs = payload.get("parameter_pairs")
    if not isinstance(pairs, list) or any(not isinstance(pair, list) for pair in pairs):
        raise ValueError("parameter_pairs must be a list of pairs")
    parameter_pairs = tuple(tuple(str(name) for name in pair) for pair in pairs)
    if parameter_pairs != FROZEN_PARAMETER_PAIRS:
        raise ValueError("parameter_pairs must equal the frozen contract")

    truths = payload.get("truth_ids")
    seeds = payload.get("optimizer_seeds")
    if not isinstance(truths, list) or tuple(truths) != FROZEN_TRUTHS:
        raise ValueError("truth_ids must equal the frozen contract")
    if not isinstance(seeds, list) or tuple(seeds) != FROZEN_OPTIMIZER_SEEDS:
        raise ValueError("optimizer_seeds must equal the frozen contract")
    if payload.get("trials") != 100:
        raise ValueError("trials must equal the frozen value 100")
    if payload.get("feature_mode") != "hybrid":
        raise ValueError("feature_mode must equal hybrid")
    if payload.get("fit_harmonics") != [1, 2, 3]:
        raise ValueError("fit_harmonics must equal H1-H3")
    if payload.get("feature_grid_size") != 128:
        raise ValueError("feature_grid_size must equal 128")
    if payload.get("formal_backend") != "lsoda":
        raise ValueError("formal_backend must equal lsoda")
    if model.get("id") != "M0" or model.get("beta_recon") != 0.0:
        raise ValueError("model must equal frozen M0 with beta_recon=0")

    noise = payload.get("noise_fractions")
    if not isinstance(noise, dict):
        raise ValueError("noise_fractions must be an object")
    parsed_noise = {name: _require_finite(value, name) for name, value in noise.items()}
    if parsed_noise != {"S1": 0.0, "S2": 0.001495726085983469}:
        raise ValueError("noise_fractions must equal the frozen S1/S2 values")

    thresholds = payload.get("thresholds")
    if thresholds != FROZEN_THRESHOLDS:
        raise ValueError("thresholds must equal frozen recovery gate v2 values")
    stage_policy = payload.get("stage_policy")
    if not isinstance(stage_policy, dict) or stage_policy.get(
        "stop_s2_if_all_p2_fail_s1"
    ) is not True:
        raise ValueError("S1 all-P2-fail stop policy must be enabled")
    noise_evidence = payload.get("noise_evidence")
    if not isinstance(noise_evidence, str) or not noise_evidence:
        raise ValueError("noise_evidence must be a non-empty relative path")
    evidence_path = Path(noise_evidence)
    if evidence_path.is_absolute() or ".." in evidence_path.parts:
        raise ValueError("noise_evidence must be a safe relative path")

    return PreExperimentRecoverySpec(
        schema_version=int(payload.get("schema_version", 0)),
        design_id=str(payload.get("design_id", "")),
        model_id="M0",
        beta_recon=0.0,
        conditions=MappingProxyType(conditions),
        portfolios=MappingProxyType(dict(portfolios)),
        parameter_pairs=parameter_pairs,
        truth_ids=tuple(truths),
        optimizer_seeds=tuple(int(seed) for seed in seeds),
        trials=100,
        feature_mode="hybrid",
        fit_harmonics=(1, 2, 3),
        feature_grid_size=128,
        formal_backend="lsoda",
        noise_fractions=MappingProxyType(parsed_noise),
        noise_evidence=noise_evidence,
        thresholds=MappingProxyType(dict(FROZEN_THRESHOLDS)),
        stop_s2_if_all_p2_fail_s1=True,
    )


def target_identity(
    truth_id: str,
    noise_fraction: float,
    condition_id: str,
) -> dict[str, str | int]:
    """Return a portfolio-independent identity for one synthetic observation."""
    if not truth_id or not condition_id:
        raise ValueError("truth_id and condition_id must be non-empty")
    noise = _require_finite(noise_fraction, "noise_fraction")
    if noise < 0.0:
        raise ValueError("noise_fraction must be non-negative")
    key = f"{truth_id}|{noise:.17g}|{condition_id}"
    return {
        "target_key": key,
        "target_seed": int(hashlib.sha256(key.encode("utf-8")).hexdigest()[:8], 16),
    }


def _hash_value(digest: Any, label: str, value: Any) -> None:
    digest.update(label.encode("utf-8"))
    digest.update(b"\0")
    if isinstance(value, np.ndarray):
        array = np.ascontiguousarray(value)
        digest.update(b"array\0")
        digest.update(array.dtype.str.encode("ascii"))
        digest.update(np.asarray(array.shape, dtype=np.int64).tobytes())
        digest.update(array.tobytes())
        return
    if isinstance(value, Mapping):
        digest.update(b"mapping\0")
        for key in sorted(value):
            _hash_value(digest, str(key), value[key])
        return
    if isinstance(value, (list, tuple)):
        digest.update(b"sequence\0")
        for index, item in enumerate(value):
            _hash_value(digest, str(index), item)
        return
    digest.update(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
        .encode("utf-8")
    )


def target_sha256(
    target: Mapping[str, Any],
    channel_contract_sha256: str,
) -> str:
    """Hash every target-side input used by the frozen hybrid H1-H3 loss."""
    required = ("current", "dc", "harm", "complex_harmonics", "lockin")
    missing = [name for name in required if name not in target]
    if missing:
        raise ValueError(f"target missing hash inputs: {', '.join(missing)}")
    if not isinstance(channel_contract_sha256, str) or not channel_contract_sha256:
        raise ValueError("channel contract hash must be non-empty")
    frozen_inputs = {
        "current": np.asarray(target["current"]),
        "dc": np.asarray(target["dc"]),
        "harm": tuple(np.asarray(item) for item in target["harm"][:3]),
        "complex_harmonics": {
            "amplitude": np.asarray(target["complex_harmonics"]["amplitude"])[
                :3
            ],
            "phase": np.asarray(target["complex_harmonics"]["phase"])[
                :3
            ],
        },
        "lockin": {
            "amplitude": tuple(
                np.asarray(item) for item in target["lockin"]["amplitude"][:3]
            ),
            "phase": tuple(
                np.asarray(item) for item in target["lockin"]["phase"][:3]
            ),
            "valid_mask": np.asarray(target["lockin"]["valid_mask"], dtype=bool),
        },
        "channel_contract_sha256": channel_contract_sha256,
    }
    digest = hashlib.sha256()
    _hash_value(digest, "hybrid_target_v1", frozen_inputs)
    return digest.hexdigest()


def validate_target_reuse(records: Sequence[Mapping[str, Any]]) -> dict[str, str]:
    """Reject evidence where one deterministic target key has multiple hashes."""
    by_key: dict[str, str] = {}
    for index, record in enumerate(records):
        key = record.get("target_key")
        target_hash = record.get("target_sha256")
        if not isinstance(key, str) or not key:
            raise ValueError(f"target record {index} has invalid target_key")
        if (
            not isinstance(target_hash, str)
            or len(target_hash) != 64
            or any(character not in "0123456789abcdef" for character in target_hash)
        ):
            raise ValueError(f"target record {index} has invalid target_sha256")
        previous = by_key.setdefault(key, target_hash)
        if previous != target_hash:
            raise ValueError(f"conflicting hashes for target key {key}")
    return by_key


class PortfolioObjective:
    """Equal-weight mean of independently normalized condition objectives."""

    def __init__(
        self,
        objectives: Sequence[tuple[str, Any]],
        *,
        failure_penalty: float,
    ) -> None:
        self.objectives = tuple(objectives)
        names = [name for name, _ in self.objectives]
        if not names:
            raise ValueError("portfolio must contain at least one condition")
        if len(names) != len(set(names)):
            raise ValueError("portfolio condition ids must be unique")
        self.failure_penalty = _require_finite(failure_penalty, "failure_penalty")
        if self.failure_penalty <= 0.0:
            raise ValueError("failure_penalty must be positive")
        self.n_calls = 0
        self.best_value = float("inf")
        self.best_x: np.ndarray | None = None
        self.last_condition_losses: dict[str, float] = {}
        self.best_condition_losses: dict[str, float] = {}
        self.last_components: dict[str, float] = {}
        self.best_components: dict[str, float] = {}

    @property
    def n_forward(self) -> int:
        return sum(int(objective.n_forward) for _, objective in self.objectives)

    @property
    def n_ode_fail(self) -> int:
        return sum(int(objective.n_ode_fail) for _, objective in self.objectives)

    @property
    def n_feature_fail(self) -> int:
        return sum(int(objective.n_feature_fail) for _, objective in self.objectives)

    @property
    def n_tafel_fail(self) -> int:
        return sum(int(objective.n_tafel_fail) for _, objective in self.objectives)

    def __call__(self, x: Sequence[float]) -> float:
        self.n_calls += 1
        losses = {
            condition_id: float(objective(x))
            for condition_id, objective in self.objectives
        }
        self.last_condition_losses = losses
        self.last_components = {
            f"condition:{condition_id}": value
            for condition_id, value in losses.items()
        }
        value = (
            float(np.mean(tuple(losses.values())))
            if all(math.isfinite(item) for item in losses.values())
            else self.failure_penalty
        )
        if value < self.best_value:
            self.best_value = value
            self.best_x = np.asarray(x, dtype=float).reshape(-1).copy()
            self.best_condition_losses = dict(losses)
            self.best_components = dict(self.last_components)
        return value


def build_condition_config(
    spec: PreExperimentRecoverySpec,
    condition: ProtocolCondition,
    *,
    truth: Mapping[str, float],
    free_specs: Sequence[ParamSpec],
    backend: str,
    seed: int,
    smoke: bool,
) -> InversionConfig:
    """Build one condition config while freezing all non-free truth values."""
    if condition.condition_id not in spec.conditions:
        raise ValueError("condition is not part of the frozen specification")
    if backend not in {"cn", "lsoda"}:
        raise ValueError("backend must be cn or lsoda")
    if not smoke and backend != spec.formal_backend:
        raise ValueError("formal backend must equal frozen lsoda backend")
    free_names = {name for name, *_ in free_specs}
    if len(free_names) != len(tuple(free_specs)) or not free_names:
        raise ValueError("free_specs must contain unique parameters")
    missing = sorted(free_names - set(truth))
    if missing:
        raise ValueError(f"free parameters missing from truth: {', '.join(missing)}")
    fixed_params = tuple(
        (name, float(value))
        for name, value in truth.items()
        if name not in free_names
    ) + (("beta_recon", spec.beta_recon),)
    points_per_cycle = 32 if smoke else condition.points_per_cycle
    cycles = min(condition.cycles, 8) if smoke else condition.cycles
    return InversionConfig(
        E_start=condition.E_start,
        E_end=condition.E_end,
        f=condition.f,
        dE=condition.dE,
        n_points=cycles * points_per_cycle,
        points_per_cycle=points_per_cycle,
        feature_grid_size=spec.feature_grid_size,
        fit_harmonics=spec.fit_harmonics,
        feature_mode=spec.feature_mode,
        solver_backend=backend,
        seed=int(seed),
        fixed_params=fixed_params,
    )
