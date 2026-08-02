"""Contracts for rotated-combination profile diagnostics."""

import numpy as np

from scripts.run_combination_profile_smoke import parse_args, reconstruct_with_fixed_combination


def test_reconstruct_with_fixed_combination_solves_pivot_coordinate():
    direction = np.array([0.6, 0.8])
    target = 0.7

    full = reconstruct_with_fixed_combination(
        complement_unit=np.array([0.5]),
        direction=direction,
        target_coordinate=target,
        pivot_index=1,
    )

    np.testing.assert_allclose(full, [0.5, 0.5])
    np.testing.assert_allclose(direction @ full, target)


def test_runner_accepts_fixed_budget_hybrid_search(tmp_path):
    args = parse_args(
        [
            "--output", str(tmp_path / "out"),
            "--geometry", str(tmp_path / "geometry.json"),
            "--search", "tpe_powell_hybrid",
            "--budget", "256",
            "--truth-id", "center",
        ]
    )

    assert args.search == "tpe_powell_hybrid"
    assert args.truth_id == "center"
