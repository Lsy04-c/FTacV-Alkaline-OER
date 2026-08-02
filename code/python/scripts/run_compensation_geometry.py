#!/usr/bin/env python3
"""Infer candidate invariant combinations from LSODA-confirmed compensation moves."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Sequence

import numpy as np


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "code" / "python" / "src"))

from oer_aem.identifiability import fit_compensation_geometry


PARAMETER_NAMES = (
    "k0_1",
    "k0_2",
    "k0_3",
    "G_OH",
    "G_O",
    "scaling_OOH_OH",
)


def reconstruct_candidate(
    *,
    parameter_names: Sequence[str],
    profiled_parameter: str,
    profile_coordinate: float,
    complement_names: Sequence[str],
    complement_unit: np.ndarray,
) -> np.ndarray:
    """Reassemble one full unit-coordinate candidate by parameter name."""

    complement = np.asarray(complement_unit, dtype=float).reshape(-1)
    if complement.shape != (len(complement_names),):
        raise ValueError("complement coordinates must match complement names")
    values = dict(zip(map(str, complement_names), map(float, complement)))
    if profiled_parameter in values:
        raise ValueError("profiled parameter must not occur in complement")
    values[str(profiled_parameter)] = float(profile_coordinate)
    if set(values) != set(map(str, parameter_names)):
        raise ValueError("candidate parameters do not match the common contract")
    return np.asarray([values[name] for name in parameter_names], dtype=float)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


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
    parser.add_argument("--profile-summary", action="append", required=True, type=Path)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    if args.output.exists() and any(args.output.iterdir()):
        raise RuntimeError(f"output directory is not empty: {args.output}")
    args.output.mkdir(parents=True, exist_ok=True)

    records = []
    truth_reference = None
    sources = []
    for path in args.profile_summary:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("backend") != "lsoda" or not payload.get("confirmation_only"):
            raise ValueError(f"source is not an LSODA candidate confirmation: {path}")
        profiled = str(payload["profiled_parameter"])
        complement_names = tuple(map(str, payload["complement_parameter_names"]))
        for row in payload["rows"]:
            candidate = reconstruct_candidate(
                parameter_names=PARAMETER_NAMES,
                profiled_parameter=profiled,
                profile_coordinate=float(row["profile_coordinate"]),
                complement_names=complement_names,
                complement_unit=np.asarray(row["complement_recovered_unit"], dtype=float),
            )
            truth = reconstruct_candidate(
                parameter_names=PARAMETER_NAMES,
                profiled_parameter=profiled,
                profile_coordinate=float(payload["profile_truth_coordinate"]),
                complement_names=complement_names,
                complement_unit=np.asarray(row["complement_truth_unit"], dtype=float),
            )
            if truth_reference is None:
                truth_reference = truth
            elif not np.allclose(truth, truth_reference, rtol=0.0, atol=1e-14):
                raise ValueError("source truth coordinates do not match")
            records.append(
                {
                    "profiled_parameter": profiled,
                    "offset": float(row["offset_from_truth"]),
                    "loss": float(row["minimum_loss"]),
                    "candidate": candidate,
                    "displacement": candidate - truth,
                }
            )
        sources.append({"path": str(path), "sha256": _sha256(path)})

    low_loss = [row for row in records if row["loss"] <= 1.0 and abs(row["offset"]) > 1e-14]
    training = [row for row in low_loss if abs(row["offset"]) <= 0.0500000001]
    selection = [row for row in low_loss if abs(row["offset"]) > 0.0500000001]
    if len(training) < len(PARAMETER_NAMES) or not selection:
        raise ValueError("insufficient train/selection compensation candidates")

    training_matrix = np.vstack([row["displacement"] for row in training])
    selection_matrix = np.vstack([row["displacement"] for row in selection])
    geometry = fit_compensation_geometry(training_matrix)
    directions = np.asarray(geometry["directions"], dtype=float)
    direction_rows = []
    for index in range(directions.shape[1]):
        vector = directions[:, index]
        direction_rows.append(
            {
                "direction": index + 1,
                "training_singular_value": float(geometry["singular_values"][index]),
                "loadings": {
                    name: float(value) for name, value in zip(PARAMETER_NAMES, vector)
                },
                "training_maximum_absolute_motion": float(
                    np.max(np.abs(training_matrix @ vector))
                ),
                "selection_maximum_absolute_motion": float(
                    np.max(np.abs(selection_matrix @ vector))
                ),
                "selection_rms_motion": float(
                    np.sqrt(np.mean((selection_matrix @ vector) ** 2))
                ),
            }
        )

    summary = {
        "status": "SUCCESS",
        "study_kind": "development_low_loss_compensation_geometry",
        "eligible_for_formal_conclusions": False,
        "git_commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip(),
        "parameter_names": list(PARAMETER_NAMES),
        "truth_unit": truth_reference.tolist(),
        "loss_inclusion_threshold": 1.0,
        "split_rule": "abs(offset)<=0.05 train; abs(offset)>0.05 selection",
        "training_candidate_count": len(training),
        "selection_candidate_count": len(selection),
        "training_geometry": geometry,
        "direction_validation": direction_rows,
        "sources": sources,
        "prohibited_claims": [
            "automatic_effective_dimension_selected",
            "candidate_direction_is_globally_invariant",
            "physical_parameter_combination_identified",
        ],
    }
    _write_json(args.output / "summary.json", summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
