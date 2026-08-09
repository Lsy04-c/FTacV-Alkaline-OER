"""Auditable search-step policies for expensive recovery optimizers."""

from __future__ import annotations

import math
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from .inversion import DEFAULT_PARAM_SPECS, ParamSpec
from .recovery import ParameterSelection, build_parameter_selection


def selection_evidence_hash(evidence: Mapping[str, Any]) -> str:
    """Return a deterministic digest for a parameter-role evidence record."""
    payload = json.dumps(
        evidence,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def validate_parameter_selection_evidence(
    evidence: Mapping[str, Any], *, formal: bool = False
) -> dict[str, Any]:
    """Validate role evidence before accepting a formal search result.

    Legacy runners may omit this schema while their historical job format is
    being preserved.  A formal search must provide the complete role groups,
    however, and cannot claim a fixed-role override as formal evidence.
    """
    if not isinstance(evidence, Mapping):
        raise ValueError("parameter role evidence must be a mapping")
    required = {
        "selection_schema_version",
        "free_parameters",
        "fixed_params",
        "diagnostic_parameters",
        "roles",
        "role_groups",
        "role_override",
    }
    missing = sorted(required - set(evidence))
    if missing:
        if formal:
            raise ValueError(
                "formal search requires complete parameter role evidence; "
                f"missing role evidence: {', '.join(missing)}"
            )
        return dict(evidence)
    if evidence["selection_schema_version"] != 1:
        raise ValueError("unsupported parameter role evidence schema")
    free = list(evidence["free_parameters"])
    fixed_params = dict(evidence["fixed_params"])
    diagnostic = list(evidence["diagnostic_parameters"])
    roles = dict(evidence["roles"])
    groups = dict(evidence["role_groups"])
    if set(groups) != {"free", "fixed", "diagnostic"}:
        raise ValueError("parameter role evidence has invalid role groups")
    if any(not isinstance(item, str) for item in (*free, *diagnostic)):
        raise ValueError("parameter role evidence names must be strings")
    if len(set(free)) != len(free) or len(set(diagnostic)) != len(diagnostic):
        raise ValueError("parameter role evidence contains duplicate names")
    group_sets = {name: set(values) for name, values in groups.items()}
    if any(len(values) != len(group_sets[name]) for name, values in groups.items()):
        raise ValueError("parameter role evidence contains duplicate role names")
    if set(free) != group_sets["free"]:
        raise ValueError("free parameter role evidence is inconsistent")
    if set(diagnostic) != group_sets["diagnostic"]:
        raise ValueError("diagnostic parameter role evidence is inconsistent")
    if set(fixed_params) != group_sets["fixed"] | group_sets["diagnostic"]:
        raise ValueError("fixed parameter role evidence is inconsistent")
    if set(roles) != group_sets["free"] | group_sets["fixed"] | group_sets["diagnostic"]:
        raise ValueError("parameter role evidence does not cover all assignments")
    for role, names in group_sets.items():
        if any(roles[name] != role for name in names):
            raise ValueError("parameter role evidence map is inconsistent")
    if set().union(*group_sets.values()) and sum(map(len, group_sets.values())) != len(
        set().union(*group_sets.values())
    ):
        raise ValueError("parameter role evidence assigns a parameter twice")
    if not isinstance(evidence["role_override"], bool):
        raise ValueError("role_override must be boolean")
    if formal and evidence["role_override"]:
        raise ValueError("formal search cannot use a role override")
    return dict(evidence)


def build_scientific_parameter_selection(
    parameters: Mapping[str, float],
    *,
    free_names: Sequence[str],
    fixed_override: Mapping[str, float] | None = None,
    specs: Sequence[ParamSpec] = DEFAULT_PARAM_SPECS,
    diagnostic: bool = False,
) -> ParameterSelection:
    """Adapt a truth/runtime parameter mapping to an explicit search contract.

    The raw search runners historically inferred fixed values by subtracting
    the free names from a truth dictionary.  This adapter makes that
    assignment auditable and rejects a fixed override that silently targets a
    free parameter.  ``diagnostic=True`` is the only route that can reopen a
    currently fixed role such as ``gamma``.
    """
    free = tuple(str(name).strip() for name in free_names if str(name).strip())
    if not free:
        raise ValueError("at least one search parameter is required")
    overrides = {
        str(name).strip(): value
        for name, value in (fixed_override or {}).items()
    }
    overlap = set(free) & set(overrides)
    if overlap:
        raise ValueError(
            "parameter assigned to multiple roles: " + ", ".join(sorted(overlap))
        )
    assigned = dict(parameters)
    assigned.update(overrides)
    free_set = set(free)
    fixed = {name: value for name, value in assigned.items() if name not in free_set}
    return build_parameter_selection(
        free_names=free,
        fixed_values=fixed,
        specs=specs,
        allow_role_override=bool(diagnostic),
    )


def validate_cma_sigma(
    sigma: float, *, diagnostic: bool = False, maximum: float = 0.10
) -> float:
    """Validate CMA-ES sigma in normalized coordinates.

    Formal runs reject the historically used 0.25 step because it can cross a
    narrow basin in one generation.  Diagnostic explorations may opt in, but
    their results are not formal recovery evidence.
    """
    value = float(sigma)
    if not math.isfinite(value) or value <= 0.0:
        raise ValueError("CMA sigma must be a finite positive number")
    if value > float(maximum) and not diagnostic:
        raise ValueError(
            "CMA sigma exceeds the formal limit; derive it from a profile "
            "contract or pass diagnostic=True"
        )
    return value


def derive_cma_sigma(
    profile_half_width: float | None,
    *,
    safety: float = 0.5,
    floor: float = 0.005,
    cap: float = 0.10,
) -> float:
    """Derive a conservative normalized CMA step from a profile half-width."""
    if profile_half_width is None or not math.isfinite(float(profile_half_width)):
        raise ValueError("profile half-width is required and must be finite")
    if float(profile_half_width) <= 0.0:
        raise ValueError("profile half-width must be positive")
    if not (0.0 < float(safety) <= 1.0):
        raise ValueError("safety must be in (0, 1]")
    if not (0.0 < float(floor) <= float(cap)):
        raise ValueError("floor/cap must satisfy 0 < floor <= cap")
    return min(float(cap), max(float(floor), float(profile_half_width) * float(safety)))


def load_profile_sigma_contract(
    path: str | Path,
    free_names: Sequence[str],
    *,
    feature_mode: str | None = None,
    expected_truth_id: str | None = None,
    expected_configuration: Mapping[str, Any] | None = None,
    expected_source_commit: str | None = None,
) -> dict[str, Any]:
    """Load and hash an objective-profile summary for a formal CMA step.

    ``run_objective_profiles.py`` reports ``delta_1_width`` as a full width in
    normalized coordinates.  The optimizer uses half of the narrowest width,
    so every free parameter must be represented.  This is a provenance
    contract, not a confidence interval: one-sided/remote valleys must be
    rejected by the caller or by a preregistered profile gate before use.
    """
    source = Path(path)
    raw = source.read_bytes()
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("profile summary must be valid UTF-8 JSON") from exc
    if not isinstance(payload, Mapping) or not isinstance(payload.get("profiles"), list):
        raise ValueError("profile summary must contain a profiles array")
    if payload.get("infrastructure_passed") is not True:
        raise ValueError("profile summary infrastructure gate did not pass")
    if payload.get("dirty") is not False:
        raise ValueError("formal profile summary must come from a clean worktree")
    if not isinstance(payload.get("source_commit"), str) or not payload["source_commit"]:
        raise ValueError("profile summary source_commit is missing")
    if (
        expected_source_commit is not None
        and payload["source_commit"] != expected_source_commit
    ):
        raise ValueError("profile summary source_commit does not match this execution")
    configuration = payload.get("configuration")
    if not isinstance(configuration, Mapping):
        raise ValueError("profile summary configuration is missing")
    if configuration.get("solver_backend") != "lsoda":
        raise ValueError("formal profile summary must use the LSODA backend")
    if configuration.get("smoke") is not False:
        raise ValueError("formal profile summary must not be a smoke run")
    if expected_truth_id is not None and configuration.get("truth_id") != expected_truth_id:
        raise ValueError("profile summary truth_id does not match the recovery task")
    if expected_configuration is not None:
        for key, expected in expected_configuration.items():
            actual = configuration.get(key)
            if isinstance(expected, (list, tuple)):
                if actual != list(expected):
                    raise ValueError(f"profile summary configuration mismatch: {key}")
            elif actual != expected:
                raise ValueError(f"profile summary configuration mismatch: {key}")
    available_modes = configuration.get("feature_modes")
    if feature_mode is not None and (
        not isinstance(available_modes, list) or feature_mode not in available_modes
    ):
        raise ValueError("profile summary does not contain the requested feature mode")
    requested = tuple(str(name) for name in free_names)
    if not requested or len(set(requested)) != len(requested):
        raise ValueError("free_names must be non-empty and unique")
    candidates: dict[str, Mapping[str, Any]] = {}
    for item in payload["profiles"]:
        if not isinstance(item, Mapping):
            raise ValueError("profile summary entries must be objects")
        if feature_mode is not None and item.get("feature_mode") != feature_mode:
            continue
        name = item.get("parameter")
        if not isinstance(name, str) or not name:
            raise ValueError("profile summary parameter is missing")
        if name in candidates:
            raise ValueError(f"duplicate profile summary for {name}")
        candidates[name] = item
    missing = sorted(set(requested) - set(candidates))
    if missing:
        raise ValueError("profile summary is missing free parameters: " + ", ".join(missing))

    widths: dict[str, float] = {}
    profile_ids: dict[str, str | None] = {}
    for name in requested:
        item = candidates[name]
        width = item.get("delta_1_width")
        if not isinstance(width, (int, float)) or not math.isfinite(float(width)):
            raise ValueError(f"profile width for {name} is missing or non-finite")
        if float(width) <= 0.0:
            raise ValueError(f"profile width for {name} must be positive")
        if float(width) > 1.0 + 1e-12:
            raise ValueError(f"profile width for {name} exceeds normalized bounds")
        semantics = item.get("interval_semantics")
        if semantics != "objective diagnostic, not confidence interval":
            raise ValueError(f"profile semantics for {name} are not recognized")
        if expected_truth_id is not None and item.get("truth_id") != expected_truth_id:
            raise ValueError(f"profile truth_id for {name} does not match the recovery task")
        if expected_truth_id is not None:
            if item.get("truth_is_global_minimum") is not True:
                raise ValueError(f"profile for {name} does not place truth at the global minimum")
            if item.get("remote_delta_1_minimum") is True:
                raise ValueError(f"profile for {name} contains a remote near-minimum")
            if item.get("finite_fraction") != 1.0:
                raise ValueError(f"profile for {name} contains non-finite evaluations")
            if item.get("ode_failures", 0) != 0 or item.get("tafel_failures", 0) != 0:
                raise ValueError(f"profile for {name} contains solver/feature failures")
        widths[name] = float(width) / 2.0
        profile_ids[name] = (
            str(item["profile_id"]) if item.get("profile_id") is not None else None
        )
    selected = min(widths.values())
    return {
        "source_path": str(source),
        "source_sha256": hashlib.sha256(raw).hexdigest(),
        "source_commit": payload.get("source_commit"),
        "configuration": dict(configuration),
        "free_parameters": list(requested),
        "feature_mode": feature_mode,
        "profile_ids": profile_ids,
        "half_width_by_parameter": widths,
        "selected_half_width": float(selected),
        "selection_rule": "minimum half of delta_1_width across free parameters",
    }
