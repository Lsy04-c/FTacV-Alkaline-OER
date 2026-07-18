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
    decode_vector,
    encode_params,
    make_synthetic_target,
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
