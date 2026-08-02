"""Contracts for complement-reoptimized profile diagnostics."""

import numpy as np

from scripts.run_reoptimized_profile_smoke import (
    encoded_best_to_unit,
    parse_args,
    protocol_config,
    split_profile_problem,
)


def test_split_profile_problem_removes_profiled_and_fixed_parameters():
    specs = (
        ("a", "linear", 0.0, 1.0),
        ("b", "linear", 0.0, 1.0),
        ("c", "linear", 0.0, 1.0),
    )

    complement, complement_truth = split_profile_problem(
        specs,
        truth_unit=np.array([0.2, 0.3, 0.4]),
        profiled_name="b",
        fixed_names={"c"},
    )

    assert complement == (specs[0],)
    np.testing.assert_allclose(complement_truth, [0.2])


def test_runner_accepts_explicit_profile_budget(tmp_path):
    source = tmp_path / "source.json"
    args = parse_args(
        [
            "--output", str(tmp_path / "out"),
            "--budget", "96",
            "--candidate-source", str(source),
            "--confirm-only",
            "--truth-id", "center",
        ]
    )

    assert args.budget == 96
    assert args.candidate_source == source
    assert args.confirm_only is True
    assert args.truth_id == "center"


def test_runner_accepts_physical_condition_overrides(tmp_path):
    args = parse_args(
        [
            "--output", str(tmp_path / "out"),
            "--transfer-coefficient", "0.4",
            "--temperature", "310.0",
            "--fixed-k04-source", "truth",
        ]
    )

    assert args.transfer_coefficient == 0.4
    assert args.temperature == 310.0
    assert args.fixed_k04_source == "truth"


def test_runner_rejects_invalid_physical_conditions(tmp_path):
    with np.testing.assert_raises(SystemExit):
        parse_args(
            [
                "--output", str(tmp_path / "out"),
                "--transfer-coefficient", "1.0",
            ]
        )

    with np.testing.assert_raises(SystemExit):
        parse_args(
            [
                "--output", str(tmp_path / "out"),
                "--temperature", "0.0",
            ]
        )


def test_encoded_best_is_converted_back_to_unit_coordinates():
    specs = (("a", "linear", -2.0, 2.0),)

    unit = encoded_best_to_unit(np.array([1.0]), specs)

    np.testing.assert_allclose(unit, [0.75])


def test_high_frequency_protocol_preserves_baseline_scan_rate():
    baseline = protocol_config("baseline", "cn")
    high_frequency = protocol_config("highfreq_matched", "cn")

    assert high_frequency.n_points == 2 * baseline.n_points
    assert high_frequency.scan_rate == baseline.scan_rate


def test_protocol_config_propagates_physical_conditions_to_target_and_candidates():
    config = protocol_config(
        "baseline",
        "cn",
        transfer_coefficient=0.4,
        temperature=310.0,
    )

    assert dict(config.fixed_params) == {"a": 0.4, "T": 310.0}
