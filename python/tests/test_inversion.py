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
    decode_vector,
    encode_params,
    make_synthetic_target,
    params_from_vector,
)


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


def test_synthetic_target_objective_is_zero_at_truth():
    config = InversionConfig(n_points=256, points_per_cycle=32, feature_grid_size=32)
    truth = {
        'k0_1': 100.0,
        'k0_2': 50.0,
        'k0_3': 20.0,
        'k0_4': 80.0,
        'G_OH': 1.23,
        'G_O': 2.80,
        'scaling_OOH_OH': 3.2,
        'gamma': 1e-9,
    }

    target = make_synthetic_target(truth, config=config, noise_fraction=0.0)
    objective = InversionObjective(target, config=config)
    x_true = encode_params(truth, DEFAULT_PARAM_SPECS)

    assert objective(x_true) < 1e-12
    assert objective.n_forward == 1


def test_tpe_inverter_runs_small_budget():
    pytest.importorskip("optuna")

    config = InversionConfig(n_points=256, points_per_cycle=32, feature_grid_size=32)
    truth = {
        'k0_1': 100.0,
        'k0_2': 50.0,
        'k0_3': 20.0,
        'k0_4': 80.0,
        'G_OH': 1.23,
        'G_O': 2.80,
        'scaling_OOH_OH': 3.2,
        'gamma': 1e-9,
    }
    target = make_synthetic_target(truth, config=config, noise_fraction=0.0)

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
    truth = {
        'k0_1': 100.0,
        'k0_2': 50.0,
        'k0_3': 20.0,
        'k0_4': 80.0,
        'G_OH': 1.23,
        'G_O': 2.80,
        'scaling_OOH_OH': 3.2,
        'gamma': 1e-9,
    }
    target = make_synthetic_target(truth, config=config, noise_fraction=0.0)

    result = TPEInverter(config=config, seed=7, initial_params=truth).run(target, n_trials=1)

    assert result.best_value < 1e-12
    assert result.history[0]['source'] == 'initial'
