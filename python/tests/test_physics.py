"""测试物理模型核心功能。"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import numpy as np
import pytest
from oer_aem import (
    apply_alkaline_aem,
    OERPhysics,
    OERSignal,
    OERObjective,
    initialize_oer_parameters,
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


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
