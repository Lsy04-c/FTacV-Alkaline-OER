"""Deterministic parameter anchors for effective-dimension discovery."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

import numpy as np
from scipy.stats import qmc

from .identifiability import coordinate_scales_from_schema


@dataclass(frozen=True)
class ParameterAnchor:
    """One outcome-independent parameter point and its preregistered split."""

    anchor_id: str
    split: str
    unit_coordinates: tuple[float, ...]
    parameters: dict[str, float]


def _validated_splits(
    split_counts: Sequence[tuple[str, int]],
) -> tuple[tuple[str, int], ...]:
    splits = tuple((str(name), int(count)) for name, count in split_counts)
    names = [name for name, _ in splits]
    if (
        not splits
        or any(not name or count <= 0 for name, count in splits)
        or len(names) != len(set(names))
    ):
        raise ValueError("split contract requires unique names and positive counts")
    return splits


def generate_parameter_anchors(
    schema: Mapping[str, object],
    parameter_names: Sequence[str],
    *,
    split_counts: Sequence[tuple[str, int]],
    seed: int,
) -> tuple[ParameterAnchor, ...]:
    """Generate scrambled-Sobol anchors before evaluating model outcomes."""

    names = tuple(str(name) for name in parameter_names)
    if not names or len(names) != len(set(names)):
        raise ValueError("parameter_names must be nonempty and unique")
    coordinate_scales_from_schema(schema, names)
    splits = _validated_splits(split_counts)
    count = sum(value for _, value in splits)
    exponent = int(np.ceil(np.log2(count)))
    sampler = qmc.Sobol(d=len(names), scramble=True, seed=int(seed))
    unit_points = sampler.random_base2(m=exponent)[:count]

    anchors: list[ParameterAnchor] = []
    point_index = 0
    for split, split_count in splits:
        for within_split in range(split_count):
            unit = unit_points[point_index]
            physical = unit_coordinates_to_parameters(schema, names, unit)
            anchors.append(
                ParameterAnchor(
                    anchor_id=f"{split}-{within_split:02d}",
                    split=split,
                    unit_coordinates=tuple(float(value) for value in unit),
                    parameters=physical,
                )
            )
            point_index += 1
    return tuple(anchors)


def unit_coordinates_to_parameters(
    schema: Mapping[str, object],
    parameter_names: Sequence[str],
    unit_coordinates: Sequence[float],
) -> dict[str, float]:
    """Map one point in the closed unit box through schema transforms."""

    names = tuple(str(name) for name in parameter_names)
    coordinate_scales_from_schema(schema, names)
    unit = np.asarray(unit_coordinates, dtype=float)
    if (
        unit.shape != (len(names),)
        or not np.all(np.isfinite(unit))
        or np.any(unit < 0.0)
        or np.any(unit > 1.0)
    ):
        raise ValueError("unit coordinates must be finite and inside [0, 1]")
    parameters = schema["parameters"]
    physical: dict[str, float] = {}
    for column, name in enumerate(names):
        entry = parameters[name]
        lower, upper = map(float, entry["bounds"])
        if entry["transform"] == "linear":
            value = lower + float(unit[column]) * (upper - lower)
        else:
            log_value = np.log10(lower) + float(unit[column]) * (
                np.log10(upper) - np.log10(lower)
            )
            value = 10.0 ** log_value
        physical[name] = float(value)
    return physical


def inactive_direction_probe_points(
    unit_anchor: Sequence[float],
    directions: np.ndarray,
    *,
    active_dimension: int,
    maximum_step: float = 0.05,
) -> list[dict[str, object]]:
    """Create symmetric in-box probes along every discarded direction."""

    anchor = np.asarray(unit_anchor, dtype=float)
    basis = np.asarray(directions, dtype=float)
    parameter_count = anchor.size
    if (
        anchor.shape != (parameter_count,)
        or not np.all(np.isfinite(anchor))
        or np.any(anchor < 0.0)
        or np.any(anchor > 1.0)
    ):
        raise ValueError("unit anchor must be finite and inside [0, 1]")
    if basis.shape != (parameter_count, parameter_count) or not np.allclose(
        basis.T @ basis,
        np.eye(parameter_count),
        rtol=0.0,
        atol=1e-10,
    ):
        raise ValueError("directions must be an orthonormal parameter basis")
    if active_dimension < 0 or active_dimension > parameter_count:
        raise ValueError("active_dimension is out of range")
    if not np.isfinite(maximum_step) or maximum_step <= 0.0:
        raise ValueError("maximum_step must be finite and positive")

    probes: list[dict[str, object]] = []
    for index in range(active_dimension, parameter_count):
        direction = basis[:, index]
        nonzero = np.abs(direction) > np.finfo(float).eps
        boundary = np.min(
            np.minimum(anchor[nonzero], 1.0 - anchor[nonzero])
            / np.abs(direction[nonzero])
        )
        step = min(float(maximum_step), 0.5 * float(boundary))
        if step <= np.finfo(float).eps:
            raise ValueError(
                f"inactive direction {index} has no symmetric in-box step"
            )
        probes.append(
            {
                "direction_index": index,
                "step": step,
                "plus": (anchor + step * direction).tolist(),
                "minus": (anchor - step * direction).tolist(),
            }
        )
    return probes
