"""Tests for the V3 residual-attribution runner contract."""

from __future__ import annotations

import json
from pathlib import Path
import warnings

import pytest

from scripts.run_v3_residual_attribution import (
    _parameter_associations,
    build_job_plan,
    load_completed_jobs,
    load_spec,
    load_v2_inputs,
)


ROOT = Path(__file__).resolve().parents[3]
SPEC_PATH = ROOT / "config" / "residual" / "v3-residual-attribution.json"


def test_real_v2_inputs_build_four_by_twelve_plan():
    spec = load_spec(SPEC_PATH)
    inputs = load_v2_inputs(ROOT, spec)

    plan, selection = build_job_plan(inputs, spec, smoke=False)

    assert len(plan) == 48
    assert set(selection) == {"FT2", "FT3", "FT4", "FT8"}
    assert all(len(rows) == 12 for rows in selection.values())
    assert len({row["job_id"] for row in plan}) == 48


def test_smoke_plan_keeps_one_nearest_candidate_per_dataset():
    spec = load_spec(SPEC_PATH)
    inputs = load_v2_inputs(ROOT, spec)

    plan, selection = build_job_plan(inputs, spec, smoke=True)

    assert len(plan) == 4
    assert all(len(rows) == 1 for rows in selection.values())
    for dataset_id, rows in selection.items():
        expected = inputs["summary"]["datasets"][dataset_id][
            "nearest_candidate"
        ]["candidate_id"]
        assert rows[0]["candidate_id"] == expected


def test_load_completed_jobs_rejects_duplicate_job(tmp_path):
    result_path = tmp_path / "residual_curves.jsonl"
    row = {"job_id": "v3:FT2:000001", "job_input_hash": "hash"}
    result_path.write_text(
        json.dumps(row) + "\n" + json.dumps(row) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="duplicate job_id"):
        load_completed_jobs(
            tmp_path,
            [{"job_id": row["job_id"], "job_input_hash": "hash"}],
        )


def test_load_completed_jobs_rejects_changed_job_hash(tmp_path):
    result_path = tmp_path / "residual_curves.jsonl"
    result_path.write_text(
        json.dumps(
            {
                "job_id": "v3:FT2:000001",
                "job_input_hash": "old",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="job hash mismatch"):
        load_completed_jobs(
            tmp_path,
            [{"job_id": "v3:FT2:000001", "job_input_hash": "new"}],
        )


def test_constant_metric_association_is_explicit_without_warning():
    inputs = {
        "parameter_names": ["k0_1"],
        "base_rows": [
            {
                "dataset_id": "FT2",
                "success": True,
                "unit_params": [index / 3],
                "metrics": {"constant_metric": 1.0},
                "score": float(index),
            }
            for index in range(4)
        ],
    }

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        rows = _parameter_associations(inputs, ["FT2"])

    constant = next(row for row in rows if row["metric"] == "constant_metric")
    assert caught == []
    assert constant["spearman_rho"] == 0.0
    assert constant["pvalue"] == 1.0
