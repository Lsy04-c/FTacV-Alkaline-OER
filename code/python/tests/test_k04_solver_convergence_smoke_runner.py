"""Contracts for the k0_4 LSODA convergence diagnostic."""

import numpy as np

from scripts.run_k04_solver_convergence_smoke import (
    parse_args,
    project_relative_path,
    summarize_pair,
)


def test_summarize_pair_reports_absolute_and_relative_current_difference():
    result = summarize_pair(
        np.array([1.0, -2.0]),
        np.array([1.0 + 1e-6, -2.0]),
    )

    np.testing.assert_allclose(result["maximum_absolute_difference_A"], 1e-6)
    np.testing.assert_allclose(result["rms_difference_A"], 1e-6 / np.sqrt(2.0))
    np.testing.assert_allclose(result["relative_to_reference_peak"], 5e-7)


def test_project_relative_path_accepts_relative_output_path():
    assert project_relative_path("results/smoke/example.npz") == "results/smoke/example.npz"


def test_runner_accepts_explicit_truth_case(tmp_path):
    args = parse_args(["--output", str(tmp_path / "out"), "--truth-id", "mixed_b"])

    assert args.truth_id == "mixed_b"


def test_runner_accepts_transfer_coefficient_override(tmp_path):
    args = parse_args(
        [
            "--output", str(tmp_path / "out"),
            "--transfer-coefficient", "0.4",
        ]
    )

    assert args.transfer_coefficient == 0.4
