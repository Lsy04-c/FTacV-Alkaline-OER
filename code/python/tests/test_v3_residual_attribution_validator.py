"""Tests for the independent V3 residual-attribution validator."""

from __future__ import annotations

import copy
import json

import numpy as np
import pytest

from scripts.validate_v3_residual_attribution import (
    align_job_selection_evidence,
    compare_selection,
    validate_archive,
    validate_residual_row,
)
from scripts.run_v3_residual_attribution import _sha256_json


def _valid_row() -> dict[str, object]:
    residuals: dict[str, object] = {
        "dc": [0.0] * 128,
        "lockin_valid_mask": [False] * 26 + [True] * 76 + [False] * 26,
    }
    for harmonic in (1, 2, 3):
        residuals[f"global_amplitude_h{harmonic}"] = [0.0]
        residuals[f"global_phase_h{harmonic}"] = [0.0]
        residuals[f"lockin_amplitude_h{harmonic}"] = [0.0] * 128
        residuals[f"lockin_phase_h{harmonic}"] = [0.0] * 128
    return {
        "job_id": "v3:FT2:000001",
        "dataset_id": "FT2",
        "candidate_id": 1,
        "job_input_hash": "hash",
        "success": True,
        "e_grid": np.linspace(1.2, 1.6, 128).tolist(),
        "residuals": residuals,
        "candidate_summary": [],
    }


def test_validate_residual_row_accepts_wrapped_phase_and_masked_empty_segments():
    validate_residual_row(_valid_row(), harmonics=(1, 2, 3), grid_size=128)


def test_validate_residual_row_rejects_unwrapped_phase():
    row = _valid_row()
    row["residuals"]["lockin_phase_h2"][60] = 3.2

    with pytest.raises(ValueError, match="phase outside"):
        validate_residual_row(row, harmonics=(1, 2, 3), grid_size=128)


def test_validate_archive_rejects_missing_contract_files(tmp_path):
    result = validate_archive(
        tmp_path,
        tmp_path / "missing-spec.json",
        tmp_path / "archive",
        rerun_nearest=False,
    )

    assert result["gate"] == "FAIL_STRUCTURE"
    assert "missing" in result["errors"][0].lower()
    assert not (tmp_path / "archive" / "acceptance.md").exists()


def _selection_fixture() -> dict[str, list[dict[str, object]]]:
    return {
        "FT2": [
            {
                "candidate_id": 1,
                "score": 2.0,
                "unit_params": [0.1] * 5,
                "selection_rank": 0,
                "selection_min_distance": 0.7846502642103816,
            }
        ]
    }


def test_compare_selection_accepts_one_ulp_distance_difference():
    expected = _selection_fixture()
    actual = json.loads(json.dumps(expected))
    actual["FT2"][0]["selection_min_distance"] = 0.7846502642103815

    compare_selection(actual, expected)


def test_compare_selection_rejects_changed_candidate():
    expected = _selection_fixture()
    actual = copy.deepcopy(expected)
    actual["FT2"][0]["candidate_id"] = 2

    with pytest.raises(ValueError, match="candidate_id"):
        compare_selection(actual, expected)


def test_align_job_selection_evidence_rehashes_only_validated_distance():
    job = {
        "job_id": "v3:FT2:000001",
        "dataset_id": "FT2",
        "candidate_id": 1,
        "selection_rank": 0,
        "selection_min_distance": 0.7846502642103816,
        "physical_params": {"k0_1": 1.0},
    }
    job["job_input_hash"] = _sha256_json(job)
    selection = _selection_fixture()
    selection["FT2"][0]["selection_min_distance"] = 0.7846502642103815

    aligned = align_job_selection_evidence([job], selection)

    assert aligned[0]["selection_min_distance"] == 0.7846502642103815
    payload = {
        key: value
        for key, value in aligned[0].items()
        if key != "job_input_hash"
    }
    assert aligned[0]["job_input_hash"] == _sha256_json(payload)
