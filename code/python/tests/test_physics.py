"""测试物理模型核心功能。"""

import sys
import os
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

import numpy as np
import pytest
import oer_aem.physics as physics_module
from oer_aem import (
    apply_alkaline_aem,
    OERPhysics,
    OERSignal,
    OERObjective,
    initialize_oer_parameters,
)
from oer_aem.physics import (
    STOICHIOMETRIC_MATRIX,
    coverage_derivatives,
    current_components,
    effective_gamma,
    elementary_rates,
    validate_steady_state,
    validate_physics_parameters,
)


def test_aem_thermodynamics():
    """验证 AEM 热力学约束：ΣΔG = 4.92 eV, E01-E04 生成正确。"""
    params = {'G_OH': 1.5, 'G_O': 3.0}
    result = apply_alkaline_aem(params)

    assert 'E01' in result
    assert 'E02' in result
    assert 'E03' in result
    assert 'E04' in result

    total = result['E01'] + result['E02'] + result['E03'] + result['E04']
    assert abs(total - 4.92) < 1e-6, f"ΣE⁰ = {total}, expected 4.92"

    # G_OOH = G_OH + scaling
    assert abs(result['G_OOH'] - (result['G_OH'] + result.get('scaling_OOH_OH', 3.2))) < 1e-10


def test_scaling_adjustable():
    """scaling_OOH_OH 默认 3.2，但可修改。"""
    params = {'G_OH': 1.5, 'G_O': 3.0, 'scaling_OOH_OH': 3.0}
    result = apply_alkaline_aem(params)
    assert abs(result['G_OOH'] - 4.5) < 1e-10    # 1.5 + 3.0


def test_params_initialization():
    """验证 initialize_oer_parameters 生成完整参数字典。"""
    params = initialize_oer_parameters()
    required_keys = ['G_OH', 'G_O', 'E01', 'E02', 'E03', 'E04',
                     'k0_pre', 'k0_1', 'k0_2', 'k0_3', 'k0_4',
                     'E_start', 'E_end', 'f', 'dE', 'Ru', 'Cdl', 'A', 'gamma']
    for key in required_keys:
        assert key in params, f"缺少参数: {key}"


def test_ode_model_coverage_sum():
    """验证 ODE 右端函数中覆盖度变化之和应为 0。"""
    params = initialize_oer_parameters()
    params['use_steady_state'] = False
    params['E_start'] = 1.5

    y = np.array([1.0, 0.0, 0.0, 0.0, 0.0, 1.5])
    dydt = OERPhysics.oer_model(0.0, y, params)

    # 5 个覆盖度变化之和应 ≈ 0（归一化后θ_sum=1不变）
    dtheta_sum = np.sum(dydt[:5])
    assert abs(dtheta_sum) < 1e-6, f"dθ_sum = {dtheta_sum}"


def test_signal_dc_extraction():
    """验证 DC 分量提取：纯直流的 FFT-DC 应恢复原信号。"""
    params = {'band': np.ones(8) * 0.02, 'f': 9.0}
    t = np.linspace(0, 10, 2048)
    dc_signal = 2.0 + 0.5 * np.sin(2 * np.pi * 0.1 * t)  # 低通信号
    df = 1.0 / np.mean(np.diff(t))

    I_dc = OERSignal.extract_dc_fft(dc_signal, df, params)
    # DC 分量应接近 2.0
    assert abs(np.mean(I_dc) - 2.0) < 0.3


def test_ode_solver_runs():
    """验证 ODE 求解器可正常运行（短时间低分辨率）。"""
    params = initialize_oer_parameters()
    params['n_points'] = 512
    params['points_per_cycle'] = 32
    params['total_time'] = (512 / 32) / params['f']
    params['t_span'] = np.linspace(0, params['total_time'], 512)
    params['use_steady_state'] = False

    t, y, E_actual, i_total = OERPhysics.solve_ode_system(params)
    assert len(t) > 0
    assert not np.any(np.isnan(y))
    assert not np.any(np.isnan(i_total))


def test_lsoda_uses_validated_initial_step_for_stiff_parameter_sets(monkeypatch):
    """锁定 Gate A3 失败样本验证过的 LSODA 初始步长。"""
    captured = {}

    def fake_solve_ivp(**kwargs):
        captured.update(kwargs)
        t_eval = np.asarray(kwargs["t_eval"], dtype=float)
        y0 = np.asarray(kwargs["y0"], dtype=float)
        return SimpleNamespace(
            success=True,
            t=t_eval,
            y=np.repeat(y0[:, None], len(t_eval), axis=1),
            message="ok",
        )

    monkeypatch.setattr(physics_module, "solve_ivp", fake_solve_ivp)
    params = initialize_oer_parameters()
    params.update(
        {
            "n_points": 8,
            "points_per_cycle": 8,
            "total_time": 1.0,
            "t_span": np.linspace(0.0, 1.0, 8),
            "use_steady_state": False,
        }
    )

    OERPhysics.solve_ode_system(params)

    assert captured["method"] == "LSODA"
    assert captured["first_step"] == pytest.approx(1e-8)


def test_dynamic_solver_uses_state_aware_absolute_tolerances(monkeypatch):
    captured = {}

    def fake_solve_ivp(**kwargs):
        captured.update(kwargs)
        t_eval = np.asarray(kwargs["t_eval"], dtype=float)
        y0 = np.asarray(kwargs["y0"], dtype=float)
        return SimpleNamespace(
            success=True,
            t=t_eval,
            y=np.repeat(y0[:, None], len(t_eval), axis=1),
            message="ok",
            nfev=7,
        )

    monkeypatch.setattr(physics_module, "solve_ivp", fake_solve_ivp)
    params = initialize_oer_parameters()
    params.update(
        {
            "n_points": 8,
            "points_per_cycle": 8,
            "total_time": 1.0,
            "t_span": np.linspace(0.0, 1.0, 8),
            "use_steady_state": False,
        }
    )

    result = OERPhysics.solve_ode_system_detailed(params)

    assert physics_module.DYNAMIC_ATOL == pytest.approx(
        np.array([3e-11] * 5 + [1e-8]), rel=0.0, abs=0.0
    )
    assert captured["atol"] == pytest.approx(
        physics_module.DYNAMIC_ATOL, rel=0.0, abs=0.0
    )
    assert result.backend_used == "LSODA"
    assert result.fallback_used is False
    assert [item.backend for item in result.attempts] == ["LSODA"]


def test_detailed_solver_restarts_bdf_from_original_state(monkeypatch):
    calls = []

    def fake_solve_ivp(**kwargs):
        method = kwargs["method"]
        y0 = np.asarray(kwargs["y0"], dtype=float).copy()
        calls.append((method, y0, dict(kwargs)))
        if method == "LSODA":
            failed_state = y0.copy()
            failed_state[0] = 0.5
            return SimpleNamespace(
                success=False,
                t=np.array([0.0]),
                y=failed_state[:, None],
                message="forced LSODA failure",
                nfev=3,
            )
        t_eval = np.asarray(kwargs["t_eval"], dtype=float)
        return SimpleNamespace(
            success=True,
            t=t_eval,
            y=np.repeat(y0[:, None], len(t_eval), axis=1),
            message="BDF ok",
            nfev=9,
        )

    monkeypatch.setattr(physics_module, "solve_ivp", fake_solve_ivp)
    params = initialize_oer_parameters()
    params.update(
        {
            "n_points": 8,
            "points_per_cycle": 8,
            "total_time": 1.0,
            "t_span": np.linspace(0.0, 1.0, 8),
            "use_steady_state": False,
        }
    )

    result = OERPhysics.solve_ode_system_detailed(params)

    assert [call[0] for call in calls] == ["LSODA", "BDF"]
    assert calls[1][1] == pytest.approx(calls[0][1], rel=0.0, abs=0.0)
    assert "first_step" in calls[0][2]
    assert "first_step" not in calls[1][2]
    assert result.backend_used == "BDF"
    assert result.fallback_used is True
    assert [item.success for item in result.attempts] == [False, True]
    assert result.attempts[0].message == "forced LSODA failure"


def test_detailed_solver_raises_when_all_backends_fail(monkeypatch):
    def fake_solve_ivp(**kwargs):
        y0 = np.asarray(kwargs["y0"], dtype=float)
        return SimpleNamespace(
            success=False,
            t=np.array([0.0]),
            y=y0[:, None],
            message=f"forced {kwargs['method']} failure",
            nfev=2,
        )

    monkeypatch.setattr(physics_module, "solve_ivp", fake_solve_ivp)
    params = initialize_oer_parameters()
    params.update(
        {
            "n_points": 8,
            "points_per_cycle": 8,
            "total_time": 1.0,
            "t_span": np.linspace(0.0, 1.0, 8),
            "use_steady_state": False,
        }
    )

    with pytest.raises(RuntimeError, match="LSODA.*BDF") as captured:
        OERPhysics.solve_ode_system_detailed(params)
    assert [item.backend for item in captured.value.attempts] == [
        "LSODA",
        "BDF",
    ]


def test_ode_coverage_trajectory_remains_physical_and_conserved():
    params = initialize_oer_parameters()
    params['n_points'] = 512
    params['points_per_cycle'] = 32
    params['total_time'] = (512 / 32) / params['f']
    params['t_span'] = np.linspace(0, params['total_time'], 512)
    params['use_steady_state'] = False

    _, states, _, _ = OERPhysics.solve_ode_system(params)
    coverage = states[:, :5]

    assert np.min(coverage) >= -1e-6
    assert np.max(coverage) <= 1.0 + 1e-6
    assert np.sum(coverage, axis=1) == pytest.approx(
        np.ones(coverage.shape[0]),
        abs=1e-6,
    )


def test_effective_gamma_is_constant_when_reconstruction_disabled():
    potential = np.array([1.2, 1.5, 1.8])
    params = {
        'gamma': 3e-9,
        'gamma0': 9e-9,
        'beta_recon': 0.0,
    }

    result = effective_gamma(potential, params)

    assert result == pytest.approx(np.full(3, 3e-9))


def test_effective_gamma_increases_above_reconstruction_potential():
    params = {
        'gamma': 3e-9,
        'beta_recon': 2.0,
        'E_recon': 1.55,
        'w_recon': 0.05,
    }

    result = effective_gamma(np.array([1.3, 1.8]), params)

    assert result[1] > result[0]


def test_default_optimizer_does_not_free_reconstruction_parameters():
    params = initialize_oer_parameters()

    assert params['beta_recon'] == 0.0
    assert 'beta_recon' not in params['optimize_params']
    assert 'E_recon' not in params['optimize_params']
    assert 'w_recon' not in params['optimize_params']


def test_forward_current_is_stable_to_output_grid_refinement():
    def simulate(n_points, points_per_cycle):
        params = initialize_oer_parameters()
        params['n_points'] = n_points
        params['points_per_cycle'] = points_per_cycle
        params['total_time'] = (
            n_points / points_per_cycle
        ) / params['f']
        params['v'] = (
            params['E_end'] - params['E_start']
        ) / params['total_time']
        params['t_span'] = np.linspace(
            0.0,
            params['total_time'],
            n_points,
        )
        params['use_steady_state'] = False
        time, _, _, current = OERPhysics.solve_ode_system(params)
        potential = params['E_start'] + params['v'] * time
        return potential, current

    coarse_e, coarse_i = simulate(512, 32)
    fine_e, fine_i = simulate(1024, 64)
    common = np.linspace(coarse_e[0], coarse_e[-1], 200)
    coarse = np.interp(common, coarse_e, coarse_i)
    fine = np.interp(common, fine_e, fine_i)
    scale = max(float(np.max(np.abs(fine))), 1e-30)
    normalized_rmse = float(
        np.sqrt(np.mean((coarse - fine) ** 2)) / scale
    )

    assert normalized_rmse < 0.05


def test_stoichiometric_matrix_conserves_every_elementary_step():
    assert STOICHIOMETRIC_MATRIX.shape == (5, 5)
    assert np.sum(STOICHIOMETRIC_MATRIX, axis=0) == pytest.approx(
        np.zeros(5), abs=0.0
    )


def test_coverage_derivatives_are_generated_by_stoichiometry():
    params = initialize_oer_parameters()
    state = np.array([0.15, 0.25, 0.20, 0.18, 0.22, 1.45])

    rates = elementary_rates(0.17, state, params)
    actual = coverage_derivatives(rates.net)

    assert actual == pytest.approx(
        STOICHIOMETRIC_MATRIX @ rates.net,
        rel=0.0,
        abs=0.0,
    )
    assert np.sum(actual) == pytest.approx(0.0, abs=1e-12)


def test_elementary_rate_is_linear_only_in_its_own_k0():
    params = initialize_oer_parameters()
    state = np.array([0.15, 0.25, 0.20, 0.18, 0.22, 1.45])
    reference = elementary_rates(0.17, state, params)
    changed = dict(params)
    changed["k0_2"] *= 10.0

    candidate = elementary_rates(0.17, state, changed)

    assert candidate.net[2] == pytest.approx(10.0 * reference.net[2])
    assert np.delete(candidate.net, 2) == pytest.approx(
        np.delete(reference.net, 2)
    )


def test_forward_reverse_ratio_increases_with_overpotential():
    params = initialize_oer_parameters()
    low_state = np.array([0.15, 0.25, 0.20, 0.18, 0.22, 1.40])
    high_state = low_state.copy()
    high_state[5] += 0.01

    low = elementary_rates(0.17, low_state, params)
    high = elementary_rates(0.17, high_state, params)

    assert (
        high.forward_constants / high.reverse_constants
        > low.forward_constants / low.reverse_constants
    ).all()


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("Ru", 0.0),
        ("Cdl", 0.0),
        ("A", -1.0),
        ("gamma", -1e-9),
        ("T", 0.0),
        ("k0_3", -1.0),
        ("a", -0.01),
        ("a", 1.01),
    ],
)
def test_parameter_domain_rejects_unsupported_values(name, value):
    params = initialize_oer_parameters()
    params[name] = value

    with pytest.raises(ValueError, match=name):
        validate_physics_parameters(params)


def test_time_grid_contract_rejects_duplicate_or_out_of_range_points():
    params = initialize_oer_parameters()
    params["t_span"] = np.array([0.0, 0.5, 0.5, 1.0])
    params["total_time"] = 1.0
    with pytest.raises(ValueError, match="t_span"):
        validate_physics_parameters(params, require_time_grid=True)

    params["t_span"] = np.array([0.0, 0.5, 1.1])
    with pytest.raises(ValueError, match="t_span"):
        validate_physics_parameters(params, require_time_grid=True)


def test_default_ru_range_excludes_singular_zero_resistance():
    params = initialize_oer_parameters()

    assert params["Ru_range"] == [0.1, 500.0]


def test_steady_state_rejects_solver_failure(monkeypatch):
    def fake_solve_ivp(**kwargs):
        y0 = np.asarray(kwargs["y0"], dtype=float)
        return SimpleNamespace(
            success=False,
            t=np.array([0.0, 0.2]),
            y=np.repeat(y0[:, None], 2, axis=1),
            message="forced failure",
        )

    monkeypatch.setattr(physics_module, "solve_ivp", fake_solve_ivp)
    params = initialize_oer_parameters()

    with pytest.raises(RuntimeError, match="forced failure"):
        OERPhysics.calculate_steady_state(params)


def test_validate_steady_state_rejects_invalid_state_and_rhs():
    params = initialize_oer_parameters()
    params.update({"v": 0.0, "dE": 0.0})
    params = OERPhysics.initialize_system(params)

    nonfinite = np.array([1.0, 0.0, 0.0, 0.0, 0.0, np.nan])
    with pytest.raises(RuntimeError, match="finite"):
        validate_steady_state(nonfinite, params, rhs_t=5.0)

    unconserved = np.array([0.8, 0.1, 0.0, 0.0, 0.0, 0.9])
    with pytest.raises(RuntimeError, match="sum"):
        validate_steady_state(unconserved, params, rhs_t=5.0)

    negative = np.array([1.01, -0.01, 0.0, 0.0, 0.0, 0.9])
    with pytest.raises(RuntimeError, match="range"):
        validate_steady_state(negative, params, rhs_t=5.0)

    not_relaxed = np.array([1.0, 0.0, 0.0, 0.0, 0.0, 0.9])
    with pytest.raises(RuntimeError, match="RHS"):
        validate_steady_state(not_relaxed, params, rhs_t=5.0)


def test_current_components_close_external_circuit_current():
    params = initialize_oer_parameters()
    state = np.array([0.15, 0.25, 0.20, 0.18, 0.22, 1.45])

    parts = current_components(0.17, state, params)

    scale = max(
        abs(parts.solution),
        abs(parts.capacitive),
        abs(parts.faradaic),
        1e-12,
    )
    assert abs(parts.closure_residual) / scale <= 1e-12


def test_full_m0_output_ignores_disabled_reconstruction_parameters():
    base = initialize_oer_parameters()
    base.update(
        {
            "beta_recon": 0.0,
            "n_points": 128,
            "points_per_cycle": 64,
            "total_time": 2.0 / base["f"],
            "use_steady_state": False,
        }
    )
    base["t_span"] = np.linspace(0.0, base["total_time"], 128)
    base = OERPhysics.initialize_system(base)
    changed = dict(base)
    changed.update({"E_recon": 99.0, "w_recon": 0.001})
    state = np.array([0.15, 0.25, 0.20, 0.18, 0.22, 1.45])

    assert OERPhysics.oer_model(0.17, state, base) == pytest.approx(
        OERPhysics.oer_model(0.17, state, changed),
        rel=0.0,
        abs=0.0,
    )
    assert current_components(0.17, state, base) == current_components(
        0.17, state, changed
    )
    base_output = OERPhysics.solve_ode_system(base)
    changed_output = OERPhysics.solve_ode_system(changed)
    for expected, actual in zip(base_output, changed_output):
        assert expected == pytest.approx(actual, rel=0.0, abs=0.0)


def test_boundary_rhs_remains_stoichiometric():
    params = initialize_oer_parameters()
    time = 0.0726711360848602
    state = np.array(
        [
            9.99999999e-01,
            -1.75163948e-09,
            2.92345112e-09,
            -3.64983402e-16,
            -5.85799201e-18,
            7.58001327e-01,
        ]
    )
    rates = elementary_rates(time, state, params)
    expected = STOICHIOMETRIC_MATRIX @ rates.net
    actual = OERPhysics.oer_model(time, state, params)

    assert actual[:5] == pytest.approx(expected, rel=0.0, abs=0.0)
    assert np.sum(actual[:5]) == pytest.approx(0.0, abs=1e-12)


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
