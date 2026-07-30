"""Tests for the independent V3 residual-attribution validator."""

from __future__ import annotations

import numpy as np
import pytest

from scripts.validate_v3_residual_attribution import (
    validate_archive,
    validate_residual_row,
)


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
