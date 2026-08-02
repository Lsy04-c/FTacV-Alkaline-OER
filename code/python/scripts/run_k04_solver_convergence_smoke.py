#!/usr/bin/env python3
"""Separate k0_4 physical effects from the LSODA tolerance floor."""

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
sys.path.insert(0, str(ROOT / "code" / "python"))

from oer_aem.defaults import initialize_oer_parameters
from oer_aem.inversion import InversionConfig, encode_params, forward_current
from oer_aem.recovery import truth_library
from scripts.run_fullspace_optimizer_smoke import (
    PARAMETER_NAMES,
    SCHEMA_PATH,
    parameter_specs_from_schema,
)


RTOLS = (1e-6, 3e-7, 1e-7, 3e-8, 1e-8)


def summarize_pair(reference: np.ndarray, candidate: np.ndarray) -> dict[str, float]:
    """Summarize a current difference without discarding its physical scale."""

    left = np.asarray(reference, dtype=float).reshape(-1)
    right = np.asarray(candidate, dtype=float).reshape(-1)
    if left.shape != right.shape or not np.all(np.isfinite(left)) or not np.all(np.isfinite(right)):
        raise ValueError("currents must be finite and have matching shapes")
    difference = right - left
    peak = float(np.max(np.abs(left)))
    return {
        "maximum_absolute_difference_A": float(np.max(np.abs(difference))),
        "rms_difference_A": float(np.sqrt(np.mean(difference**2))),
        "relative_to_reference_peak": float(np.max(np.abs(difference)) / peak),
    }


def project_relative_path(path: str | Path) -> str:
    """Return a project-relative artifact path for relative or absolute inputs."""

    candidate = Path(path)
    resolved = candidate if candidate.is_absolute() else ROOT / candidate
    return str(resolved.resolve().relative_to(ROOT.resolve()))


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
    parser.add_argument(
        "--truth-id",
        choices=("center", "mixed_a", "mixed_b"),
        default="mixed_a",
    )
    parser.add_argument("--transfer-coefficient", type=float, default=0.5)
    args = parser.parse_args(argv)
    if not 0.0 < args.transfer_coefficient < 1.0:
        parser.error("--transfer-coefficient must be between zero and one")
    return args


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    if args.output.exists() and any(args.output.iterdir()):
        raise RuntimeError(f"output directory is not empty: {args.output}")
    args.output.mkdir(parents=True, exist_ok=True)

    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    specs = parameter_specs_from_schema(schema, PARAMETER_NAMES)
    truth_case = next(
        row for row in truth_library(specs) if row["truth_id"] == args.truth_id
    )
    truth_params = dict(truth_case["parameters"])
    default_params = dict(truth_params)
    default_params["k0_4"] = float(initialize_oer_parameters()["k0_4"])
    encoded_truth = encode_params(truth_params, specs)
    encoded_default = encode_params(default_params, specs)

    currents: dict[str, np.ndarray] = {}
    rows = []
    for rtol in RTOLS:
        config = InversionConfig(
            E_start=0.924097277474612,
            E_end=1.9229037265531128,
            f=5.0,
            dE=0.16,
            n_points=256,
            points_per_cycle=32,
            feature_grid_size=32,
            fit_harmonics=(1, 2, 3),
            feature_mode="hybrid",
            solver_backend="lsoda",
            seed=23,
            param_specs=specs,
            fixed_params=(
                ("dynamic_rtol", float(rtol)),
                ("a", args.transfer_coefficient),
            ),
        )
        truth_current = forward_current(encoded_truth, config, specs)
        default_current = forward_current(encoded_default, config, specs)
        if truth_current is None or default_current is None:
            raise RuntimeError(f"forward solve failed at rtol={rtol:g}")
        key = f"rtol_{rtol:.0e}"
        currents[f"truth_{key}"] = np.asarray(truth_current, dtype=float)
        currents[f"default_{key}"] = np.asarray(default_current, dtype=float)
        rows.append(
            {
                "rtol": float(rtol),
                "truth_vs_default": summarize_pair(truth_current, default_current),
            }
        )

    tightest_key = f"rtol_{RTOLS[-1]:.0e}"
    for row, rtol in zip(rows, RTOLS):
        key = f"rtol_{rtol:.0e}"
        row["truth_vs_tightest"] = summarize_pair(
            currents[f"truth_{tightest_key}"], currents[f"truth_{key}"]
        )
        row["default_vs_tightest"] = summarize_pair(
            currents[f"default_{tightest_key}"], currents[f"default_{key}"]
        )

    currents_path = args.output / "currents.npz"
    np.savez_compressed(currents_path, **currents)
    summary = {
        "status": "SUCCESS",
        "study_kind": "development_k0_4_solver_convergence",
        "eligible_for_formal_conclusions": False,
        "git_commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip(),
        "schema_path": str(SCHEMA_PATH.relative_to(ROOT)),
        "schema_sha256": _sha256(SCHEMA_PATH),
        "truth_id": args.truth_id,
        "physical_conditions": {
            "transfer_coefficient": args.transfer_coefficient,
            "temperature_K": 298.15,
        },
        "truth_k0_4_s^-1": float(truth_params["k0_4"]),
        "model_default_k0_4_s^-1": float(default_params["k0_4"]),
        "rtols": list(RTOLS),
        "rows": rows,
        "artifacts": {
            "currents": {
                "path": project_relative_path(currents_path),
                "sha256": _sha256(currents_path),
            }
        },
        "prohibited_claims": [
            "k0_4_recoverable",
            "rtol_change_approved_for_formal_runs",
        ],
    }
    _write_json(args.output / "summary.json", summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
