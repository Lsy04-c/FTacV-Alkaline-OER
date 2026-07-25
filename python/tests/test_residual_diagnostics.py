"""Tests for machine-readable residual-diagnostic output."""

import csv

import pytest

from scripts.residual_diagnostics import (
    _checkpoint_contract,
    _write_contract_csv,
)


def test_contract_csv_records_sampling_configuration(tmp_path):
    output = tmp_path / "residual_contract.csv"
    row = {
        "dataset": "example.txt",
        "grid": "full",
        "n_points": 128,
        "bias_lo": 0.01,
        "bias_mid": 0.02,
        "bias_hi": 0.03,
        "sign_convention": "experiment - simulation",
        "simulation_n_points": 8192,
        "points_per_cycle": 32,
        "fit_harmonics": "1;2;3;5",
        "fixed_params": "Cdl=0.0001;Ru=25",
        "experimental_duration_s": 51.2,
        "simulated_duration_s": 51.2,
        "experimental_scan_rate_v_s": 0.01,
        "simulated_scan_rate_v_s": 0.01,
        "scan_rate_relative_error": 0.0,
    }

    _write_contract_csv(output, [{"grid_rows": [row]}])

    with output.open(encoding="utf-8") as handle:
        written = list(csv.DictReader(handle))
    assert written == [{key: str(value) for key, value in row.items()}]


def test_contract_checkpoint_rewrites_all_accumulated_rows(tmp_path):
    output = tmp_path / "residual_contract.csv"
    first = {
        "dataset": "first.txt",
        "grid": "full",
        "n_points": 128,
        "bias_lo": 0.01,
        "bias_mid": 0.02,
        "bias_hi": 0.03,
        "sign_convention": "experiment - simulation",
        "simulation_n_points": 8192,
        "points_per_cycle": 32,
        "fit_harmonics": "1;2;3",
        "fixed_params": "Ru=25",
        "experimental_duration_s": 51.2,
        "simulated_duration_s": 51.2,
        "experimental_scan_rate_v_s": 0.01,
        "simulated_scan_rate_v_s": 0.01,
        "scan_rate_relative_error": 0.0,
    }
    second = dict(first, dataset="second.txt", grid="trimmed")

    _checkpoint_contract(output, [{"grid_rows": [first]}])
    _checkpoint_contract(
        output,
        [{"grid_rows": [first]}, {"grid_rows": [second]}],
    )

    with output.open(encoding="utf-8") as handle:
        written = list(csv.DictReader(handle))
    assert [row["dataset"] for row in written] == [
        "first.txt",
        "second.txt",
    ]


def test_contract_checkpoint_preserves_previous_file_on_write_error(tmp_path):
    output = tmp_path / "residual_contract.csv"
    output.write_text("known-good\n", encoding="utf-8")
    invalid = {
        "dataset": "bad.txt",
        "grid": "full",
        "unexpected_field": "reject me",
    }

    with pytest.raises(ValueError, match="fields not in fieldnames"):
        _checkpoint_contract(output, [{"grid_rows": [invalid]}])

    assert output.read_text(encoding="utf-8") == "known-good\n"
