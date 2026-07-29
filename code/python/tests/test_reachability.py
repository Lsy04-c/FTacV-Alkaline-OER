import numpy as np
import pytest


DIAGNOSTIC_SPECS = (
    ("k0_1", "log10", -3.0, 5.0),
    ("k0_2", "log10", -3.0, 5.0),
    ("k0_3", "log10", -3.0, 5.0),
    ("G_OH", "linear", 0.8, 1.8),
    ("G_O", "linear", 2.2, 3.4),
)

BASELINE = {
    "A": 1.0,
    "Cdl": 20e-6,
    "Ru": 10.0,
    "E0_pre": 1.45,
    "k0_pre": 500.0,
    "gamma": 3e-9,
    "k0_4": 5000.0,
    "scaling_OOH_OH": 3.2,
}


def test_sobol_library_is_deterministic_nested_and_covers_bounds():
    from oer_aem.reachability import generate_sobol_library

    first = generate_sobol_library(DIAGNOSTIC_SPECS, 512, seed=29)
    second = generate_sobol_library(DIAGNOSTIC_SPECS, 512, seed=29)
    prefix = generate_sobol_library(DIAGNOSTIC_SPECS, 256, seed=29)

    assert first.sha256 == second.sha256
    assert np.array_equal(first.encoded, second.encoded)
    assert np.array_equal(first.encoded[:256], prefix.encoded)
    assert np.all(first.unit.min(axis=0) <= 0.02)
    assert np.all(first.unit.max(axis=0) >= 0.98)
    assert first.physical[0]["k0_1"] == pytest.approx(
        10.0 ** first.encoded[0, 0]
    )


def test_candidate_score_uses_worst_active_component_and_minimum_gate():
    from oer_aem.reachability import score_candidate

    result = score_candidate(
        {
            "dc_nrmse": 0.05,
            "global_phase_h1": 0.11,
            "lockin_valid_fraction": 0.75,
        },
        {
            "dc_nrmse": 0.10,
            "global_phase_h1": 0.10,
            "lockin_valid_fraction_min": 0.50,
        },
    )

    assert result.score == pytest.approx(1.1)
    assert result.passed is False
    assert result.limiting_metrics == ("global_phase_h1",)


def test_phase_and_mask_metrics_reject_invalid_inputs():
    from oer_aem.reachability import masked_nrmse, wrapped_phase_rmse

    phase = wrapped_phase_rmse(
        np.array([-np.pi + 0.1, 0.0]),
        np.array([np.pi - 0.1, 0.0]),
        np.array([True, False]),
    )
    assert phase == pytest.approx(0.2)
    assert masked_nrmse(
        np.array([1.0, 3.0]),
        np.array([1.0, 1.0]),
        np.array([True, False]),
    ) == pytest.approx(0.0)
    with pytest.raises(ValueError, match="valid"):
        masked_nrmse(
            np.array([1.0]),
            np.array([np.nan]),
            np.array([True]),
        )


def test_fixed_stress_scenarios_are_complete_and_single_factor():
    from oer_aem.reachability import build_fixed_stress_scenarios

    scenarios = build_fixed_stress_scenarios(BASELINE)

    assert len(scenarios) == 16
    assert len({row["scenario_id"] for row in scenarios}) == 16
    for row in scenarios:
        changed = [
            name
            for name, value in row["fixed_params"].items()
            if value != BASELINE[name]
        ]
        assert changed == [row["parameter"]]


@pytest.mark.parametrize(
    ("inputs", "expected"),
    [
        (
            dict(
                contract_valid=False,
                ode_success_fraction=0.0,
                baseline_reached=True,
                stress_changed=True,
                prefix_improvement=1.0,
            ),
            "FAIL_CONTRACT",
        ),
        (
            dict(
                contract_valid=True,
                ode_success_fraction=0.94,
                baseline_reached=True,
                stress_changed=True,
                prefix_improvement=1.0,
            ),
            "INCONCLUSIVE_NUMERICAL",
        ),
        (
            dict(
                contract_valid=True,
                ode_success_fraction=1.0,
                baseline_reached=True,
                stress_changed=True,
                prefix_improvement=0.0,
            ),
            "FIXED_INPUT_SENSITIVE",
        ),
        (
            dict(
                contract_valid=True,
                ode_success_fraction=1.0,
                baseline_reached=True,
                stress_changed=False,
                prefix_improvement=1.0,
            ),
            "REACHED",
        ),
        (
            dict(
                contract_valid=True,
                ode_success_fraction=1.0,
                baseline_reached=False,
                stress_changed=False,
                prefix_improvement=0.11,
            ),
            "INCONCLUSIVE_LIBRARY",
        ),
        (
            dict(
                contract_valid=True,
                ode_success_fraction=1.0,
                baseline_reached=False,
                stress_changed=False,
                prefix_improvement=0.10,
            ),
            "NOT_REACHED_WITHIN_LIBRARY",
        ),
    ],
)
def test_classification_priority(inputs, expected):
    from oer_aem.reachability import classify_dataset

    assert classify_dataset(**inputs) == expected
