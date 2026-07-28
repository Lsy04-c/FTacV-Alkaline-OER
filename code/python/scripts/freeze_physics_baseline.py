#!/usr/bin/env python3
"""Freeze legal-state M0 RHS behavior before the Gate A2 refactor."""

from __future__ import annotations

import argparse
from contextlib import redirect_stdout
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys

import numpy as np


PROJECT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT / "code" / "python" / "src"))

from oer_aem.defaults import initialize_oer_parameters  # noqa: E402
from oer_aem.physics import OERPhysics, initialize_system  # noqa: E402


SOURCE_COMMIT = "727ed64"
PHYSICS_PATH = "code/python/src/oer_aem/physics.py"
TIMES = (0.0, 0.013, 0.071, 0.19, 0.53, 0.91)
K0_NAMES = ("k0_pre", "k0_1", "k0_2", "k0_3", "k0_4")
RHS_PARAM_NAMES = (
    "E_start",
    "v",
    "dE",
    "omega",
    "RTF",
    "a",
    "E0_pre",
    "E01",
    "E02",
    "E03",
    "E04",
    "k0_pre",
    "k0_1",
    "k0_2",
    "k0_3",
    "k0_4",
    "invRC",
    "gamma",
    "F",
    "Cdl",
    "A",
    "beta_recon",
    "E_recon",
    "w_recon",
)


def _git_blob(revision: str) -> str:
    result = subprocess.run(
        ["git", "rev-parse", f"{revision}:{PHYSICS_PATH}"],
        cwd=PROJECT,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _base_params() -> dict:
    with redirect_stdout(io.StringIO()):
        return initialize_oer_parameters()


def _cases() -> list[tuple[str, dict]]:
    return [
        ("default", {}),
        ("rates-low", {"rate_scale": 0.1}),
        ("rates-high", {"rate_scale": 10.0}),
        ("ru-low", {"Ru": 0.1}),
        ("ru-high", {"Ru": 500.0}),
        ("cdl-low", {"Cdl": 5e-6}),
        ("cdl-high", {"Cdl": 80e-6}),
        ("gamma-low", {"gamma": 1e-10}),
        ("gamma-high", {"gamma": 1e-7}),
        ("alpha-low", {"a": 0.25}),
        ("alpha-high", {"a": 0.75}),
        (
            "thermo-edge",
            {
                "G_OH": 1.8,
                "G_O": 2.2,
                "scaling_OOH_OH": 3.6,
            },
        ),
    ]


def _case_params(overrides: dict) -> dict:
    params = _base_params()
    changes = dict(overrides)
    scale = changes.pop("rate_scale", None)
    params.update(changes)
    if scale is not None:
        for name in K0_NAMES:
            params[name] *= float(scale)
    if {"G_OH", "G_O", "scaling_OOH_OH"} & set(changes):
        params = OERPhysics.apply_alkaline_aem_embedded(params)
    return initialize_system(params)


def _state(index: int) -> np.ndarray:
    weights = np.roll(np.arange(1.0, 6.0), index % 5)
    weights = weights + 0.01 * index
    coverage = weights / np.sum(weights)
    return np.concatenate([coverage, [0.92 + 0.07 * index]])


def build_baseline() -> dict:
    source_blob = _git_blob(SOURCE_COMMIT)
    current_blob = _git_blob("HEAD")
    if source_blob != current_blob:
        raise RuntimeError(
            "current physics.py differs from the frozen source commit"
        )
    records = []
    case_contracts = []
    for index, (case_id, overrides) in enumerate(_cases()):
        params = _case_params(overrides)
        state = _state(index)
        compact_params = {
            name: float(params[name]) for name in RHS_PARAM_NAMES
        }
        case_contracts.append(
            {
                "case_id": case_id,
                "overrides": overrides,
                "state": state.tolist(),
            }
        )
        for time in TIMES:
            derivative = OERPhysics.oer_model(
                float(time), state.copy(), params
            )
            records.append(
                {
                    "case_id": case_id,
                    "time": float(time),
                    "state": state.tolist(),
                    "params": compact_params,
                    "dydt": np.asarray(derivative, dtype=float).tolist(),
                }
            )
    payload = {
        "schema_version": 1,
        "source_commit": SOURCE_COMMIT,
        "source_physics_blob": source_blob,
        "times": list(TIMES),
        "cases": case_contracts,
        "rhs_records": records,
    }
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()
    return {
        **payload,
        "contract": {
            "payload_sha256": hashlib.sha256(encoded).hexdigest()
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    if output.exists() and any(output.iterdir()):
        raise FileExistsError("baseline output must be new or empty")
    output.mkdir(parents=True, exist_ok=True)
    path = output / "physics_baseline.json"
    path.write_text(
        json.dumps(
            build_baseline(),
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n",
        encoding="utf-8",
    )
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
