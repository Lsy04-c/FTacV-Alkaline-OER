"""Contracts for the seven-parameter optimizer development smoke."""

import numpy as np

from scripts.run_fullspace_optimizer_smoke import (
    assess_fixed_input_equivalence,
    parameter_specs_from_schema,
    parse_args,
    reduce_parameter_problem,
    summarize_recovery,
    validation_fixed_params,
)


def test_schema_builds_seven_parameter_encoded_specs():
    schema = {
        "parameters": {
            "rate": {"transform": "log10", "bounds": [1e-3, 1e3]},
            "energy": {"transform": "linear", "bounds": [0.5, 2.0]},
        }
    }

    specs = parameter_specs_from_schema(schema, ["rate", "energy"])

    assert specs == (
        ("rate", "log10", -3.0, 3.0),
        ("energy", "linear", 0.5, 2.0),
    )


def test_recovery_summary_reports_signed_and_boundary_errors():
    result = summarize_recovery(
        ["a", "b"],
        truth_unit=np.array([0.2, 0.8]),
        recovered_unit=np.array([0.3, 1.0]),
    )

    assert result["signed_errors"] == {"a": 0.1, "b": 0.2}
    assert result["absolute_errors"] == {"a": 0.1, "b": 0.2}
    assert result["maximum_absolute_error"] == 0.2
    assert result["median_absolute_error"] == 0.15
    assert result["boundary_hit"] is True


def test_runner_requires_explicit_output(tmp_path):
    args = parse_args(
        [
            "--output",
            str(tmp_path / "smoke"),
            "--optimizer",
            "tpe_powell_hybrid",
            "--fix-default",
            "k0_4",
        ]
    )

    assert args.output == tmp_path / "smoke"
    assert args.optimizer == ["tpe_powell_hybrid"]
    assert args.fix_default == ["k0_4"]


def test_reduced_problem_removes_fixed_parameter_without_truth_leakage():
    specs = (
        ("a", "linear", 0.0, 1.0),
        ("b", "log10", -2.0, 2.0),
        ("c", "linear", 1.0, 2.0),
    )

    free_specs, free_truth, fixed = reduce_parameter_problem(
        specs,
        truth_unit=np.array([0.2, 0.3, 0.4]),
        fixed_defaults={"b": 100.0},
    )

    assert free_specs == (specs[0], specs[2])
    np.testing.assert_allclose(free_truth, [0.2, 0.4])
    assert fixed == (("b", 100.0),)


def test_fixed_input_gate_requires_current_and_truth_objective_thresholds():
    passed = assess_fixed_input_equivalence(
        target_current=np.array([1.0, 2.0]),
        candidate_current=np.array([1.0, 2.0 + 5e-9]),
        truth_objective=5e-7,
    )
    failed = assess_fixed_input_equivalence(
        target_current=np.array([1.0, 2.0]),
        candidate_current=np.array([1.0, 2.0 + 2e-8]),
        truth_objective=5e-7,
    )

    assert passed["status"] == "PASS"
    assert passed["maximum_absolute_current_difference_A"] < 1e-8
    assert failed["status"] == "FAIL"


def test_validation_rtol_is_added_without_changing_scientific_fixed_inputs():
    fixed = validation_fixed_params((("k0_4", 5000.0),), rtol=1e-8)

    assert fixed == (("k0_4", 5000.0), ("dynamic_rtol", 1e-8))
