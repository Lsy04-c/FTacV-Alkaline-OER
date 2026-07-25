"""测试 TPE 反演正式模块的最小行为。"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import numpy as np
import pytest

from oer_aem.inversion import (
    DEFAULT_PARAM_SPECS,
    InversionConfig,
    InversionObjective,
    TPEInverter,
    assess_fit_quality,
    assess_harmonic_quality,
    decode_vector,
    denormalize_vector,
    encode_params,
    make_param_specs_from_physical_bounds,
    make_synthetic_target,
    normalize_vector,
    params_from_vector,
)

TRUTH = {
    'k0_1': 100.0,
    'k0_2': 50.0,
    'k0_3': 20.0,
    'k0_4': 80.0,
    'G_OH': 1.23,
    'G_O': 2.80,
    'scaling_OOH_OH': 3.2,
    'gamma': 1e-9,
}


def test_encode_decode_roundtrip():
    params = {
        'k0_1': 100.0,
        'k0_2': 10.0,
        'k0_3': 1.0,
        'k0_4': 0.1,
        'G_OH': 1.25,
        'G_O': 2.75,
        'scaling_OOH_OH': 3.15,
        'gamma': 2e-9,
    }

    x = encode_params(params, DEFAULT_PARAM_SPECS)
    decoded = decode_vector(x, DEFAULT_PARAM_SPECS)

    for key, expected in params.items():
        assert decoded[key] == pytest.approx(expected)


def test_normalize_denormalize_vector_roundtrip():
    params = {
        'k0_1': 100.0,
        'k0_2': 10.0,
        'k0_3': 1.0,
        'k0_4': 0.1,
        'G_OH': 1.25,
        'G_O': 2.75,
        'scaling_OOH_OH': 3.15,
        'gamma': 2e-9,
    }

    x = encode_params(params, DEFAULT_PARAM_SPECS)
    z = normalize_vector(x, DEFAULT_PARAM_SPECS)
    x2 = denormalize_vector(z, DEFAULT_PARAM_SPECS)

    assert np.all(z >= 0.0)
    assert np.all(z <= 1.0)
    assert x2 == pytest.approx(x)


def test_param_specs_from_physical_bounds_converts_log_params():
    specs = make_param_specs_from_physical_bounds(
        {
            'k0_1': (1.0, 1e4),
            'G_OH': (1.0, 1.6),
        },
        DEFAULT_PARAM_SPECS,
    )

    spec_by_name = {name: (kind, lo, hi) for name, kind, lo, hi in specs}

    assert spec_by_name['k0_1'][0] == 'log10'
    assert spec_by_name['k0_1'][1:] == pytest.approx((0.0, 4.0))
    assert spec_by_name['G_OH'][0] == 'linear'
    assert spec_by_name['G_OH'][1:] == pytest.approx((1.0, 1.6))
    assert spec_by_name['k0_2'][1:] == pytest.approx((-3.0, 5.0))


def test_assess_harmonic_quality_selects_resolvable_channels():
    t = np.linspace(0.0, 2.0 * np.pi, 256)
    harmonics = np.column_stack(
        [
            np.sin(t),
            0.2 * np.sin(2 * t),
            np.full_like(t, 1e-8),
            0.01 * np.sin(4 * t),
            np.full_like(t, 0.0),
            np.full_like(t, 0.0),
            np.full_like(t, 0.0),
        ]
    )

    quality = assess_harmonic_quality(harmonics, min_relative_rms=0.05)

    assert quality['fit_harmonics'] == [1, 2]
    assert quality['channels'][0]['fit'] is True
    assert quality['channels'][2]['fit'] is False


def test_objective_uses_selected_harmonics_only():
    config = InversionConfig(n_points=256, points_per_cycle=32, feature_grid_size=32, fit_harmonics=(1, 2, 3))
    target = make_synthetic_target(TRUTH, config=config, noise_fraction=0.0)
    x_true = encode_params(TRUTH, DEFAULT_PARAM_SPECS)
    clean_value = InversionObjective(target, config=config)(x_true)

    target['harm'][4] = target['harm'][4] + 100.0
    ignored_bad_value = InversionObjective(target, config=config)(x_true)

    assert ignored_bad_value == pytest.approx(clean_value)


def test_synthetic_target_objective_is_zero_at_truth():
    config = InversionConfig(n_points=256, points_per_cycle=32, feature_grid_size=32)

    target = make_synthetic_target(TRUTH, config=config, noise_fraction=0.0)
    objective = InversionObjective(target, config=config)
    x_true = encode_params(TRUTH, DEFAULT_PARAM_SPECS)

    assert objective(x_true) < 1e-12
    assert objective.n_forward == 1


def test_synthetic_target_skips_unavailable_tafel_channel():
    config = InversionConfig(
        n_points=256,
        points_per_cycle=32,
        feature_grid_size=32,
    )
    target = make_synthetic_target(
        TRUTH,
        config=config,
        noise_fraction=0.0,
    )
    objective = InversionObjective(target, config=config)

    assert target['tafel'] is None
    assert objective(encode_params(TRUTH)) < 1e-12
    assert objective.n_tafel_fail == 0


def test_tpe_inverter_runs_small_budget():
    pytest.importorskip("optuna")

    config = InversionConfig(n_points=256, points_per_cycle=32, feature_grid_size=32)
    target = make_synthetic_target(TRUTH, config=config, noise_fraction=0.0)

    result = TPEInverter(config=config, seed=7).run(target, n_trials=3)

    assert result.success
    assert result.best_value >= 0
    assert len(result.best_x) == len(DEFAULT_PARAM_SPECS)
    assert result.n_trials == 3
    assert result.n_forward >= 1
    assert result.fit_quality['level'] in {'excellent', 'acceptable', 'rough', 'poor'}
    assert 'message' in result.fit_quality


def test_assess_fit_quality_marks_review_ready():
    excellent = assess_fit_quality(best_value=0.0, feature_grid_size=32)
    acceptable = assess_fit_quality(best_value=8.0, feature_grid_size=32)
    poor = assess_fit_quality(best_value=1e6, feature_grid_size=32)

    assert excellent['level'] == 'excellent'
    assert excellent['ready_for_review'] is True
    assert acceptable['ready_for_review'] is True
    assert poor['ready_for_review'] is False
    assert poor['completion_percent'] < acceptable['completion_percent']


def test_fixed_params_are_used_in_forward_params():
    config = InversionConfig(
        n_points=256,
        points_per_cycle=32,
        feature_grid_size=32,
        fixed_params=(('Cdl', 150e-6), ('Ru', 25.0), ('E0_pre', 1.52), ('k0_pre', 120.0)),
    )
    params = {
        'k0_1': 100.0,
        'k0_2': 50.0,
        'k0_3': 20.0,
        'k0_4': 80.0,
        'G_OH': 1.23,
        'G_O': 2.80,
        'scaling_OOH_OH': 3.2,
        'gamma': 1e-9,
    }

    full = params_from_vector(encode_params(params), config)

    assert full['Cdl'] == pytest.approx(150e-6)
    assert full['Ru'] == pytest.approx(25.0)
    assert full['E0_pre'] == pytest.approx(1.52)
    assert full['k0_pre'] == pytest.approx(120.0)


def test_tpe_evaluates_initial_params_first():
    pytest.importorskip("optuna")

    config = InversionConfig(n_points=256, points_per_cycle=32, feature_grid_size=32)
    target = make_synthetic_target(TRUTH, config=config, noise_fraction=0.0)

    result = TPEInverter(config=config, seed=7, initial_params=TRUTH).run(target, n_trials=1)

    assert result.best_value < 1e-12
    assert result.history[0]['source'] == 'initial'


def test_objective_reports_named_loss_components():
    config = InversionConfig(
        n_points=256,
        points_per_cycle=32,
        feature_grid_size=32,
        fit_harmonics=(1, 2, 3),
        feature_mode="legacy",
    )
    target = make_synthetic_target(TRUTH, config=config, noise_fraction=0.0)
    objective = InversionObjective(target, config=config)

    objective(encode_params(TRUTH))

    assert set(objective.last_components) >= {
        "dc",
        "harmonic_amplitude",
        "physical",
    }


def test_complex_feature_mode_wraps_phase_residual():
    from oer_aem.features import snr_weights, wrapped_phase_difference

    value = wrapped_phase_difference(
        np.array([np.pi - 0.1]),
        np.array([-np.pi + 0.1]),
    )

    assert value[0] == pytest.approx(-0.2, abs=1e-8)
    assert snr_weights(np.array([2.0, 3.0, 16.5, 30.0, 50.0])).tolist() == pytest.approx(
        [0.0, 0.0, 0.5, 1.0, 1.0]
    )


def test_objective_rejects_unknown_feature_mode():
    config = InversionConfig(feature_mode="unknown")

    with pytest.raises(ValueError, match="feature_mode"):
        InversionObjective({}, config=config)
