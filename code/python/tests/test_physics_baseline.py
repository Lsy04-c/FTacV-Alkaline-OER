"""Integrity and behavior checks for the pre-refactor Gate A2 baseline."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pytest

from oer_aem.physics import OERPhysics


ROOT = Path(__file__).resolve().parents[3]
BASELINE = (
    ROOT
    / "results"
    / "formal"
    / "physics_invariants"
    / "gate-a2-baseline-727ed64"
    / "physics_baseline.json"
)


def _load_baseline():
    return json.loads(BASELINE.read_text(encoding="utf-8"))


def test_physics_baseline_has_frozen_contract_and_finite_records():
    baseline = _load_baseline()

    assert baseline["schema_version"] == 1
    assert baseline["source_commit"] == "727ed64"
    assert len(baseline["rhs_records"]) == 72
    assert all(len(row["dydt"]) == 6 for row in baseline["rhs_records"])
    assert all(
        np.all(np.isfinite(row["dydt"]))
        for row in baseline["rhs_records"]
    )
    payload = {
        key: value for key, value in baseline.items() if key != "contract"
    }
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()
    assert hashlib.sha256(encoded).hexdigest() == baseline["contract"][
        "payload_sha256"
    ]


def test_current_rhs_matches_frozen_legal_state_baseline():
    baseline = _load_baseline()

    for record in baseline["rhs_records"]:
        actual = OERPhysics.oer_model(
            record["time"],
            np.asarray(record["state"], dtype=float),
            record["params"],
        )
        assert actual == pytest.approx(
            record["dydt"], rel=1e-12, abs=1e-12
        )
