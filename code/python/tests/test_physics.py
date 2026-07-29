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
    effective_gamma,
    elementary_rates,
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


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
