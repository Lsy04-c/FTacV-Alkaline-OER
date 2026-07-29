"""测试 TPE 反演正式模块的最小行为。"""

import copy
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

import numpy as np
import pytest

from oer_aem.inversion import (
    DEFAULT_PARAM_SPECS,
    InversionConfig,
    InversionObjective,
    TPEInverter,
    assess_fit_quality,
    assess_harmonic_quality,
    build_feature_channel_contract,
    decode_vector,
    denormalize_vector,
    encode_params,
    forward_current,
    make_param_specs_from_physical_bounds,
    match_experimental_sampling,
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


def _channel_contract_target(config):
    size = config.resolved_feature_grid_size
    grid = np.linspace(0.0, 1.0, size)
    return {
        "dc": grid.copy(),
        "harm": [grid + 0.01 * index for index in range(7)],
        "complex_harmonics": {
            "amplitude": np.array([1.0, 0.5, 0.2, 0.1]),
            "phase": np.array([0.1, 0.2, 0.3, 0.4]),
            "snr": np.array([30.0, 10.0, 2.0, 20.0]),
        },
        "lockin": {
            "amplitude": [
                grid + 0.1 * index for index in range(4)
            ],
            "phase": [
                grid * 0.0 + 0.1 * index for index in range(4)
            ],
            "valid_mask": np.array(
                [False] + [True] * (size - 2) + [False]
            ),
        },
        "tafel": None,
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


def test_channel_contract_is_deterministic_and_explains_inactive_blocks():
    config = InversionConfig(
        n_points=8,
        points_per_cycle=8,
        discard_fraction=0.5,
        feature_grid_size=4,
        fit_harmonics=(1, 2, 3, 4),
        feature_mode="hybrid",
        phase_weight=0.5,
        snr_floor=3.0,
    )
    target = _channel_contract_target(config)

    contract = build_feature_channel_contract(target, config)
    repeated = build_feature_channel_contract(
        copy.deepcopy(target), config
    )

    assert contract.sha256 == repeated.sha256
    assert contract.normalization_weight_sum > 0.0
    assert all(
        channel.exclusion_reason is None
        for channel in contract.channels
        if channel.active
    )
    by_id = {channel.channel_id: channel for channel in contract.channels}
    assert by_id["complex_amplitude:H3"].active is False
    assert (
        by_id["complex_amplitude:H3"].exclusion_reason
        == "below_snr_floor"
    )
    assert by_id["complex_phase:H3"].active is False
    assert by_id["legacy_amplitude:H1"].exclusion_reason == "mode_disabled"
    assert by_id["tafel"].exclusion_reason == "not_applicable"


def test_channel_contract_records_missing_nonfinite_and_short_lockin():
    config = InversionConfig(
        n_points=8,
        points_per_cycle=8,
        discard_fraction=0.5,
        feature_grid_size=4,
        fit_harmonics=(1, 2, 3, 4),
        feature_mode="hybrid",
    )
    target = _channel_contract_target(config)
    target["complex_harmonics"]["phase"] = np.array([0.1, np.nan, 0.3])
    target["lockin"]["amplitude"] = target["lockin"]["amplitude"][:3]
    target["lockin"]["amplitude"][2] = np.array(
        [np.nan, 1.0, np.nan, np.nan]
    )

    contract = build_feature_channel_contract(target, config)
    by_id = {channel.channel_id: channel for channel in contract.channels}

    assert (
        by_id["complex_phase:H2"].exclusion_reason == "target_nonfinite"
    )
    assert by_id["complex_amplitude:H4"].exclusion_reason == "target_missing"
    assert (
        by_id["lockin_amplitude:H3"].exclusion_reason
        == "insufficient_valid_points"
    )
    assert by_id["lockin_phase:H4"].exclusion_reason == "target_missing"


@pytest.mark.parametrize(
    "dc",
    [
        None,
        np.array([1.0, 2.0]),
        np.array([0.0, 1.0, np.nan, 3.0]),
    ],
)
def test_channel_contract_rejects_invalid_dc(dc):
    config = InversionConfig(
        n_points=8,
        points_per_cycle=8,
        discard_fraction=0.5,
        feature_grid_size=4,
        feature_mode="legacy",
    )
    target = _channel_contract_target(config)
    if dc is None:
        target.pop("dc")
    else:
        target["dc"] = dc

    with pytest.raises(ValueError, match="DC target"):
        build_feature_channel_contract(target, config)


def test_objective_keeps_channel_hash_and_normalization_candidate_invariant(
    monkeypatch,
):
    config = InversionConfig(
        n_points=8,
        points_per_cycle=8,
        discard_fraction=0.5,
        feature_grid_size=4,
        fit_harmonics=(1, 2, 3),
        feature_mode="hybrid",
        phase_weight=0.5,
    )
    target = _channel_contract_target(config)
    candidates = [copy.deepcopy(target), copy.deepcopy(target)]
    candidates[1]["dc"] = np.asarray(candidates[1]["dc"]) + 0.2
    monkeypatch.setattr(
        "oer_aem.inversion.forward_current",
        lambda *args, **kwargs: np.zeros(config.n_points),
    )
    monkeypatch.setattr(
        "oer_aem.inversion.extract_features",
        lambda *args, **kwargs: candidates.pop(0),
    )
    objective = InversionObjective(target, config=config)
    frozen_hash = objective.channel_contract.sha256
    frozen_normalization = (
        objective.channel_contract.normalization_weight_sum
    )

    objective(encode_params(TRUTH))
    objective(encode_params(TRUTH))

    assert objective.channel_contract.sha256 == frozen_hash
    assert (
        objective.channel_contract.normalization_weight_sum
        == frozen_normalization
    )
    assert frozen_normalization == pytest.approx(
        sum(
            channel.loss_weight
            for channel in objective.channel_contract.channels
            if channel.active
        )
    )


def test_candidate_missing_frozen_lockin_point_fails_closed(monkeypatch):
    config = InversionConfig(
        n_points=8,
        points_per_cycle=8,
        discard_fraction=0.5,
        feature_grid_size=4,
        fit_harmonics=(1, 2),
        feature_mode="lockin_only",
        feature_fail_penalty=12345.0,
    )
    target = _channel_contract_target(config)
    candidate = copy.deepcopy(target)
    candidate["lockin"]["amplitude"][0][1] = np.nan
    monkeypatch.setattr(
        "oer_aem.inversion.forward_current",
        lambda *args, **kwargs: np.zeros(config.n_points),
    )
    monkeypatch.setattr(
        "oer_aem.inversion.extract_features",
        lambda *args, **kwargs: candidate,
    )
    objective = InversionObjective(target, config=config)

    value = objective(encode_params(TRUTH))

    assert value == config.feature_fail_penalty
    assert objective.n_feature_fail == 1
    assert (
        objective.last_components["feature_failure"]
        == config.feature_fail_penalty
    )


def test_zero_snr_channel_is_absent_from_normalization():
    config = InversionConfig(
        n_points=8,
        points_per_cycle=8,
        discard_fraction=0.5,
        feature_grid_size=4,
        fit_harmonics=(1, 2, 3),
        feature_mode="complex_snr",
        phase_weight=0.5,
    )
    target = _channel_contract_target(config)
    contract = build_feature_channel_contract(target, config)
    by_id = {channel.channel_id: channel for channel in contract.channels}

    assert by_id["complex_amplitude:H3"].loss_weight == 0.0
    assert by_id["complex_phase:H3"].loss_weight == 0.0
    assert contract.normalization_weight_sum == pytest.approx(
        sum(
            channel.loss_weight
            for channel in contract.channels
            if channel.active
        )
    )


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
        solver_backend="lsoda",
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
    assert result.n_feature_fail >= 0
    assert result.channel_contract_sha256
    assert result.channel_contract["sha256"] == result.channel_contract_sha256
    assert result.normalization_weight_sum == pytest.approx(
        result.channel_contract["normalization_weight_sum"]
    )
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
        "common_harmonics",
        "dataset_specific_harmonics",
        "physical",
    }


def test_objective_separates_common_and_dataset_specific_harmonics():
    config = InversionConfig(
        n_points=256,
        points_per_cycle=32,
        feature_grid_size=32,
        fit_harmonics=(1, 2, 3, 4),
        feature_mode="legacy",
    )
    target = make_synthetic_target(TRUTH, config=config, noise_fraction=0.0)
    target["harm"][3] = target["harm"][3] + 0.1
    objective = InversionObjective(target, config=config)

    objective(encode_params(TRUTH))

    assert objective.last_components["common_harmonics"] == pytest.approx(0.0)
    assert objective.last_components["dataset_specific_harmonics"] > 0.0


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


def test_feature_modes_build_only_their_declared_observation_blocks():
    common = {
        "n_points": 256,
        "points_per_cycle": 32,
        "feature_grid_size": 32,
        "fit_harmonics": (1, 2, 3),
        "solver_backend": "lsoda",
    }

    complex_target = make_synthetic_target(
        TRUTH,
        config=InversionConfig(feature_mode="complex_snr", **common),
    )
    lockin_target = make_synthetic_target(
        TRUTH,
        config=InversionConfig(feature_mode="lockin_only", **common),
    )
    hybrid_target = make_synthetic_target(
        TRUTH,
        config=InversionConfig(feature_mode="hybrid", **common),
    )

    assert "complex_harmonics" in complex_target
    assert "lockin" not in complex_target
    assert "complex_harmonics" not in lockin_target
    assert "lockin" in lockin_target
    assert "complex_harmonics" in hybrid_target
    assert "lockin" in hybrid_target


def test_lockin_only_reports_only_lockin_loss_for_lockin_amplitude_change():
    config = InversionConfig(
        n_points=256,
        points_per_cycle=32,
        feature_grid_size=32,
        fit_harmonics=(1, 2, 3),
        feature_mode="lockin_only",
        solver_backend="lsoda",
    )
    target = make_synthetic_target(TRUTH, config=config)
    target["lockin"]["amplitude"][0] = (
        np.asarray(target["lockin"]["amplitude"][0]) + 0.05
    )
    objective = InversionObjective(target, config=config)

    objective(encode_params(TRUTH))

    assert objective.last_components["common_harmonics"] == 0.0
    assert objective.last_components["dataset_specific_harmonics"] == 0.0
    assert objective.last_components["phase"] == 0.0
    assert objective.last_components["lockin_common_amplitude"] > 0.0
    assert objective.last_components["lockin_dataset_specific_amplitude"] == 0.0
    assert objective.last_components["lockin_common_phase"] == 0.0
    assert objective.last_components["lockin_dataset_specific_phase"] == 0.0


def test_lockin_loss_separates_common_and_dataset_specific_harmonics():
    config = InversionConfig(
        n_points=256,
        points_per_cycle=32,
        feature_grid_size=32,
        fit_harmonics=(1, 2, 3, 4),
        feature_mode="lockin_only",
        solver_backend="lsoda",
    )
    target = make_synthetic_target(TRUTH, config=config)
    target["lockin"]["amplitude"][3] = (
        np.asarray(target["lockin"]["amplitude"][3]) + 0.05
    )
    objective = InversionObjective(target, config=config)

    objective(encode_params(TRUTH))

    assert objective.last_components["lockin_common_amplitude"] == 0.0
    assert objective.last_components["lockin_dataset_specific_amplitude"] > 0.0
    assert objective.last_components["lockin_common_phase"] == 0.0
    assert objective.last_components["lockin_dataset_specific_phase"] == 0.0


def test_experimental_sampling_preserves_scan_duration():
    duration = 51.19921875
    frequency = 5.0000762951094835
    n_points, points_per_cycle = match_experimental_sampling(
        duration,
        frequency,
        points_per_cycle=12,
    )
    config = InversionConfig(
        E_start=1.124,
        E_end=1.623,
        f=frequency,
        n_points=n_points,
        points_per_cycle=points_per_cycle,
    )

    assert config.total_time == pytest.approx(duration, rel=2e-4)
    assert config.scan_rate == pytest.approx(
        (1.623 - 1.124) / duration,
        rel=2e-4,
    )


def test_default_experimental_sampling_resolves_h1_h7():
    n_points, points_per_cycle = match_experimental_sampling(
        duration=51.19922,
        frequency=5.0,
    )

    assert n_points == 256 * points_per_cycle
    assert points_per_cycle >= 4 * 7


def test_sampling_evidence_records_reproducible_configuration():
    from scripts.compare_feature_objectives import _sampling_evidence

    config = InversionConfig(
        n_points=320,
        points_per_cycle=32,
        fit_harmonics=(1, 2, 3, 5),
        fixed_params=(("Ru", 25.0), ("Cdl", 1e-4)),
        solver_backend="cn",
    )
    evidence = _sampling_evidence(config, {})

    assert evidence["n_points"] == 320
    assert evidence["points_per_cycle"] == 32
    assert evidence["fit_harmonics"] == "1;2;3;5"
    assert evidence["fixed_params"] == "Ru=25;Cdl=0.0001"
    assert evidence["solver_backend"] == "cn"


def test_complex_mode_extracts_only_required_harmonics_below_nyquist():
    config = InversionConfig(
        n_points=192,
        points_per_cycle=12,
        feature_grid_size=24,
        fit_harmonics=(1, 2, 3, 4, 5),
        feature_mode="complex_snr",
    )

    target = make_synthetic_target(TRUTH, config=config, noise_fraction=0.0)
    objective = InversionObjective(target, config=config)

    assert len(target["complex_harmonics"]["amplitude"]) == 5
    assert objective(encode_params(TRUTH)) < 1e-12


def test_lockin_interpolation_wraps_phase_and_marks_filter_edges_invalid():
    from oer_aem import inversion as inversion_module

    source_e = np.array([0.0, 1.0, 2.0, 3.0])
    target_e = np.array([0.0, 1.0, 1.5, 2.0, 3.0])
    phases = np.array([2.9, 3.10, -3.10, -2.9])
    complex_values = np.exp(1j * phases)
    lockin = {
        "complex": [complex_values],
        "valid_mask": np.array([False, True, True, False]),
        "fc_used": 0.5,
        "effective_resolution_v": 0.02,
    }

    mapped = inversion_module._interpolate_lockin_to_grid(
        lockin,
        source_e,
        target_e,
    )

    assert mapped["valid_mask"].tolist() == [False, True, True, True, False]
    assert abs(abs(mapped["phase"][0][2]) - np.pi) < 0.06
    assert mapped["amplitude"][0][1:4] == pytest.approx(np.ones(3), abs=2e-3)


def test_lsoda_backend_never_calls_cpp_solver(monkeypatch):
    from oer_aem import cpp_bridge
    from oer_aem.physics import OERPhysics

    config = InversionConfig(
        n_points=32,
        points_per_cycle=32,
        solver_backend="lsoda",
    )
    expected = np.linspace(0.0, 1.0, config.n_points)

    def fail_if_called(*args, **kwargs):
        raise AssertionError("C++ solver must not run for the lsoda backend")

    def fake_lsoda(params):
        return (
            np.arange(config.n_points),
            np.zeros((6, config.n_points)),
            np.zeros(config.n_points),
            expected,
        )

    monkeypatch.setattr(cpp_bridge, "is_available", fail_if_called)
    monkeypatch.setattr(cpp_bridge, "solve_cn", fail_if_called)
    monkeypatch.setattr(OERPhysics, "solve_ode_system", staticmethod(fake_lsoda))

    current = forward_current(encode_params(TRUTH), config)

    assert current == pytest.approx(expected)


def test_cn_backend_does_not_silently_fallback_to_lsoda(monkeypatch):
    from oer_aem import cpp_bridge
    from oer_aem.physics import OERPhysics

    config = InversionConfig(
        n_points=32,
        points_per_cycle=32,
        solver_backend="cn",
    )

    def fail_if_called(*args, **kwargs):
        raise AssertionError("LSODA fallback is forbidden for the cn backend")

    monkeypatch.setattr(cpp_bridge, "is_available", lambda: False)
    monkeypatch.setattr(OERPhysics, "solve_ode_system", staticmethod(fail_if_called))

    assert forward_current(encode_params(TRUTH), config) is None


def test_cn_backend_uses_same_steady_state_initial_condition_as_lsoda(monkeypatch):
    from oer_aem import cpp_bridge
    from oer_aem.physics import OERPhysics

    config = InversionConfig(
        n_points=32,
        points_per_cycle=32,
        solver_backend="cn",
    )
    expected_y0 = np.arange(6, dtype=float)
    expected_current = np.linspace(0.0, 1.0, config.n_points)
    received = {}

    monkeypatch.setattr(cpp_bridge, "is_available", lambda: True)
    monkeypatch.setattr(
        OERPhysics,
        "calculate_steady_state",
        staticmethod(lambda params: expected_y0.copy()),
    )

    def fake_cn(params, y0=None):
        received["y0"] = y0
        return expected_current

    monkeypatch.setattr(cpp_bridge, "solve_cn", fake_cn)

    current = forward_current(encode_params(TRUTH), config)

    assert current == pytest.approx(expected_current)
    assert received["y0"] == pytest.approx(expected_y0)


def test_auto_backend_falls_back_to_lsoda_when_cn_is_unavailable(monkeypatch):
    from oer_aem import cpp_bridge
    from oer_aem.physics import OERPhysics

    config = InversionConfig(
        n_points=32,
        points_per_cycle=32,
        solver_backend="auto",
    )
    expected = np.linspace(0.0, 1.0, config.n_points)

    monkeypatch.setattr(cpp_bridge, "is_available", lambda: False)
    monkeypatch.setattr(
        OERPhysics,
        "solve_ode_system",
        staticmethod(
            lambda params: (
                np.arange(config.n_points),
                np.zeros((6, config.n_points)),
                np.zeros(config.n_points),
                expected,
            )
        ),
    )

    current = forward_current(encode_params(TRUTH), config)

    assert current == pytest.approx(expected)


def test_forward_current_rejects_unknown_solver_backend():
    config = InversionConfig(solver_backend="unknown")

    with pytest.raises(ValueError, match="solver_backend"):
        forward_current(encode_params(TRUTH), config)
