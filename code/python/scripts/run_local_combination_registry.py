#!/usr/bin/env python3
"""Register the evidence boundary of one local compensation coordinate."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import subprocess
from pathlib import Path
from typing import Mapping, Sequence

import numpy as np


ROOT = Path(__file__).resolve().parents[3]
DEFAULT_SCHEMA = ROOT / "config/parameter-schemas/m0-total-current-effective-v1.json"


def _weakest(summary: Mapping[str, object]) -> Mapping[str, object]:
    if summary.get("status") != "SUCCESS":
        raise ValueError("geometry summary is not successful")
    rows = summary.get("direction_validation")
    if not isinstance(rows, list) or not rows:
        raise ValueError("geometry summary has no validated directions")
    return min(rows, key=lambda row: float(row["training_singular_value"]))


def _loadings(summary: Mapping[str, object]) -> dict[str, float]:
    raw = _weakest(summary).get("loadings")
    if not isinstance(raw, Mapping):
        raise ValueError("weakest direction has no loadings")
    values = {str(name): float(value) for name, value in raw.items()}
    if not values or not all(math.isfinite(value) for value in values.values()):
        raise ValueError("direction loadings must be finite")
    return values


def direction_angle_degrees(
    left: Mapping[str, object],
    right: Mapping[str, object],
) -> float:
    """Return the acute angle between sign-indeterminate SVD directions."""

    left_loadings = _loadings(left)
    right_loadings = _loadings(right)
    if set(left_loadings) != set(right_loadings):
        raise ValueError("direction parameter contracts do not match")
    names = sorted(left_loadings)
    a = np.asarray([left_loadings[name] for name in names], dtype=float)
    b = np.asarray([right_loadings[name] for name in names], dtype=float)
    a /= np.linalg.norm(a)
    b /= np.linalg.norm(b)
    cosine = float(np.clip(abs(np.dot(a, b)), 0.0, 1.0))
    angle = math.degrees(math.acos(cosine))
    return 0.0 if abs(angle) < 1e-12 else float(angle)


def physical_goh_logk01_coefficient(
    summary: Mapping[str, object],
    schema: Mapping[str, object],
) -> float:
    """Convert the normalized weakest direction to eV per log10 decade."""

    parameters = schema.get("parameters")
    if not isinstance(parameters, Mapping):
        raise ValueError("schema has no parameter mapping")
    k01 = parameters.get("k0_1")
    goh = parameters.get("G_OH")
    if not isinstance(k01, Mapping) or not isinstance(goh, Mapping):
        raise ValueError("schema lacks k0_1 or G_OH")
    if k01.get("transform") != "log10" or goh.get("transform") != "linear":
        raise ValueError("unexpected k0_1/G_OH transforms")
    k_bounds = tuple(map(float, k01.get("bounds", ())))
    g_bounds = tuple(map(float, goh.get("bounds", ())))
    if len(k_bounds) != 2 or len(g_bounds) != 2 or min(k_bounds) <= 0.0:
        raise ValueError("invalid k0_1/G_OH bounds")
    log_width = math.log10(k_bounds[1]) - math.log10(k_bounds[0])
    energy_width = g_bounds[1] - g_bounds[0]
    loadings = _loadings(summary)
    if abs(loadings.get("G_OH", 0.0)) <= 1e-15:
        raise ValueError("G_OH loading is zero")
    return float(
        -loadings["k0_1"] * energy_width
        / (loadings["G_OH"] * log_width)
    )


def evaluate_context(
    summary: Mapping[str, object],
    schema: Mapping[str, object],
) -> dict[str, object]:
    """Recompute the frozen local-geometry diagnostics for one context."""

    weakest = _weakest(summary)
    loadings = _loadings(summary)
    pair_sum = loadings.get("k0_1", 0.0) ** 2 + loadings.get("G_OH", 0.0) ** 2
    selection = float(weakest["selection_maximum_absolute_motion"])
    if not math.isfinite(selection):
        raise ValueError("selection motion must be finite")
    return {
        "minimum_training_singular_value": float(
            weakest["training_singular_value"]
        ),
        "weakest_direction_loadings": loadings,
        "goh_k01_loading_square_sum": float(pair_sum),
        "selection_maximum_absolute_motion": selection,
        "physical_coefficient_eV_per_decade": physical_goh_logk01_coefficient(
            summary, schema
        ),
        "local_geometry_gate": bool(pair_sum >= 0.95 and selection <= 0.02),
    }


def _parse_named_path(raw: str) -> tuple[str, Path]:
    name, separator, path = raw.partition("=")
    if not separator or not name or not path:
        raise argparse.ArgumentTypeError("expected NAME=PATH")
    return name, Path(path)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load(path: Path) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return payload


def _write_json(path: Path, payload: object) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--schema", type=Path, default=DEFAULT_SCHEMA)
    parser.add_argument("--baseline-geometry", required=True, type=Path)
    parser.add_argument(
        "--protocol-geometry", action="append", default=[], type=_parse_named_path
    )
    parser.add_argument(
        "--anchor-challenge", action="append", default=[], type=_parse_named_path
    )
    parser.add_argument(
        "--transfer-holdout", action="append", default=[], type=_parse_named_path
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    if args.output.exists() and any(args.output.iterdir()):
        raise RuntimeError(f"output directory is not empty: {args.output}")
    args.output.mkdir(parents=True, exist_ok=True)

    schema = _load(args.schema)
    baseline = _load(args.baseline_geometry)
    baseline_evaluation = evaluate_context(baseline, schema)
    sources = [
        {
            "role": "baseline",
            "name": "mixed_a_baseline",
            "path": str(args.baseline_geometry),
            "sha256": _sha256(args.baseline_geometry),
        }
    ]

    protocols = {}
    for name, path in args.protocol_geometry:
        payload = _load(path)
        row = evaluate_context(payload, schema)
        row["angle_to_baseline_degrees"] = direction_angle_degrees(
            baseline, payload
        )
        protocols[name] = row
        sources.append(
            {"role": "protocol", "name": name, "path": str(path), "sha256": _sha256(path)}
        )

    anchors = {}
    for name, path in args.anchor_challenge:
        payload = _load(path)
        row = evaluate_context(payload, schema)
        row["angle_to_baseline_degrees"] = direction_angle_degrees(
            baseline, payload
        )
        anchors[name] = row
        sources.append(
            {"role": "anchor_challenge", "name": name, "path": str(path), "sha256": _sha256(path)}
        )

    transfer_holdouts = {}
    gas_constant = 8.31446261815324
    faraday = 96485.33212
    temperature = 298.15
    for name, path in args.transfer_holdout:
        transfer = float(name)
        if not 0.0 < transfer < 1.0:
            raise ValueError("transfer holdout name must be a number in (0, 1)")
        payload = _load(path)
        row = evaluate_context(payload, schema)
        theory = gas_constant * temperature * math.log(10.0) / (
            (1.0 - transfer) * faraday
        )
        observed = float(row["physical_coefficient_eV_per_decade"])
        relative_error = abs(observed - theory) / theory
        row.update(
            {
                "transfer_coefficient": transfer,
                "forward_bv_theory_eV_per_decade": theory,
                "relative_theory_error": relative_error,
                "mechanism_gate": bool(
                    row["local_geometry_gate"] and relative_error <= 0.10
                ),
            }
        )
        transfer_holdouts[name] = row
        sources.append(
            {"role": "transfer_holdout", "name": name, "path": str(path), "sha256": _sha256(path)}
        )

    protocol_gate = bool(protocols) and all(
        row["local_geometry_gate"] for row in protocols.values()
    )
    anchor_invariance_rejected = bool(anchors) and any(
        not row["local_geometry_gate"] for row in anchors.values()
    )
    mechanism_gate = bool(transfer_holdouts) and all(
        row["mechanism_gate"] for row in transfer_holdouts.values()
    )
    summary = {
        "status": "SUCCESS",
        "study_kind": "development_local_combination_registry",
        "eligible_for_formal_conclusions": False,
        "git_commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip(),
        "schema_path": str(args.schema),
        "schema_sha256": _sha256(args.schema),
        "claim_level": "LOCAL_ONLY",
        "registered_coordinate": "G_OH - c*log10(k0_1)",
        "baseline": baseline_evaluation,
        "protocol_contexts": protocols,
        "anchor_challenges": anchors,
        "transfer_holdouts": transfer_holdouts,
        "gates": {
            "cross_protocol_local_geometry": protocol_gate,
            "cross_anchor_global_invariance": False,
            "cross_anchor_rejection_supported": anchor_invariance_rejected,
            "forward_bv_mechanism_scaling": mechanism_gate,
            "temperature_perturbation_allowed": False,
        },
        "sources": sources,
        "prohibited_claims": [
            "global_effective_coordinate",
            "global_parameter_reduction",
            "individual_G_OH_point_estimate",
            "individual_k0_1_point_estimate",
            "validated_BV_scaling_law",
            "confidence_interval",
            "real_data_parameter_identifiable",
        ],
    }
    _write_json(args.output / "summary.json", summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
