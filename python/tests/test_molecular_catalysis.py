"""Bonke 分子催化模型的物理与数值契约测试。"""

import numpy as np
import pytest

from oer_aem.low_dim_fit import harmonic_envelopes
from oer_aem.molecular_catalysis import (
    initialize_mc_system,
    calculate_mc_steady_state,
    simulate,
)


def _base_params(**overrides):
    # 默认扫描窗口必须跨过 E0_eff，否则表面氧化还原根本不被激发，
    # 谐波里只剩双电层响应——早期版本的默认窗口是 1.10-1.14 V 而
    # E0_eff=1.55 V，导致"法拉第电流随 gamma 线性"的测试实际在测噪声。
    params = {
        "E_start": 1.45,
        "v": 0.05,
        "dE": 0.16,
        "f": 5.0,
        "Ru": 10.0,
        "Cdl": 30e-6,
        "A": 1.0,
        "gamma": 3e-10,
        "k0": 50.0,
        "kf": 100.0,
        "E0_eff": 1.55,
        "total_time": 4.0,
    }
    params.update(overrides)
    return params


def _grid(params, points_per_cycle=128):
    n = int(round(params["total_time"] * params["f"] * points_per_cycle))
    return np.linspace(0.0, params["total_time"], n, endpoint=False)


def test_missing_parameter_is_rejected():
    params = _base_params()
    del params["kf"]
    with pytest.raises(KeyError):
        initialize_mc_system(params)


def test_coverage_stays_within_physical_bounds():
    """覆盖度必须严格落在 [0, 1]，且不依赖 SciPy 版本的步长控制。"""
    params = _base_params()
    _, _, theta_ox = simulate(params, _grid(params))
    assert np.all(np.isfinite(theta_ox))
    assert theta_ox.min() >= 0.0
    assert theta_ox.max() <= 1.0


def test_steady_state_is_reduced_far_below_e0():
    """起始电位远负于 E0_eff 时，稳态应几乎全部为还原态。"""
    params = initialize_mc_system(_base_params(E_start=0.90, E0_eff=1.60))
    y0 = calculate_mc_steady_state(params)
    assert y0[0] < 1e-3


def test_zero_gamma_reduces_to_pure_capacitance():
    """gamma=0 时法拉第项消失，电流应为纯 RC 响应。

    纯电容响应在稳态下的交流幅值有解析解 wC*dE/sqrt(1+(wRuC)^2)。
    """
    params = _base_params(gamma=0.0, v=0.0, total_time=6.0)
    t = _grid(params)
    _, i_total, _ = simulate(params, t)

    omega = 2 * np.pi * params["f"]
    C = params["Cdl"] * params["A"]
    expected = omega * C * params["dE"] / np.sqrt(1.0 + (omega * params["Ru"] * C) ** 2)

    tail = i_total[len(i_total) // 2:]
    measured = 0.5 * (tail.max() - tail.min())
    assert measured == pytest.approx(expected, rel=0.02)


def test_faradaic_current_scales_linearly_with_gamma():
    """线性极限下，H3 包络幅值应正比于 gamma。

    两处必须讲究，否则这个测试测的是噪声而不是物理：

    1. **用 `harmonic_envelopes` 而不是裸 FFT。** 电流里的直流斜坡在矩形窗
       下会泄漏到所有频点——纯 RC（gamma=0）情形的裸 FFT 在 3f0 处能读到
       1.5e-4 A，比真实法拉第信号还大。项目的提取路径带 Tukey 边缘窗和
       带通，纯 RC 本底降到约 1e-7 A。
    2. **不做 i_total - i_cap 相减。** 两条 mA 量级的电流相减去恢复
       nA 量级的法拉第分量是灾难性抵消。H3 本身几乎全部来自法拉第
       非线性（线性 RC 不产生三次谐波），直接取即可。

    gamma 取 1e-11/2e-11：信号为纯 RC 本底的 100-220 倍，而 phi_s 方程中的
    反馈项 (gamma*F/Cdl)*r_et 仍然弱。gamma 到 1e-10 时该反馈已把比值压到
    1.85，不再是线性区。
    """
    params_zero = _base_params(gamma=0.0)
    t = _grid(params_zero)
    fs = 1.0 / (t[1] - t[0])
    guard = int(0.15 * t.size)

    def h3_peak(gamma):
        _, current, _ = simulate(_base_params(gamma=gamma), t)
        envelope = harmonic_envelopes(current, fs, params_zero["f"], (3,))[0]
        return envelope[guard:t.size - guard].max()

    floor = h3_peak(0.0)
    small, double = h3_peak(1e-11), h3_peak(2e-11)

    assert small > 50 * floor, "信号必须远高于纯 RC 本底，否则测的是泄漏"
    assert double / small == pytest.approx(2.0, rel=0.03)


def test_catalytic_step_increases_dc_current():
    """打开催化步应提高直流电流（周转再生活性位）。"""
    t = _grid(_base_params())
    _, i_no_cat, _ = simulate(_base_params(kf=0.0, E_start=1.50), t)
    _, i_cat, _ = simulate(_base_params(kf=500.0, E_start=1.50), t)
    assert np.mean(i_cat) > np.mean(i_no_cat)


def _odd_harmonic_peak(params, harmonic=3, points_per_cycle=128):
    """返回奇次谐波包络峰对应的直流电位（带 5% 边缘保护）。"""
    t = _grid(params, points_per_cycle)
    _, i_total, _ = simulate(params, t)
    spectrum = np.fft.rfft(i_total)
    freqs = np.fft.rfftfreq(t.size, d=t[1] - t[0])
    mask = np.abs(freqs - harmonic * params["f"]) < 0.4 * params["f"]
    filtered = np.zeros_like(spectrum)
    filtered[mask] = spectrum[mask]
    envelope = np.abs(np.fft.irfft(filtered, t.size))
    e_dc = params["E_start"] + params["v"] * t
    guard = int(0.05 * t.size)
    return e_dc[guard + int(np.argmax(envelope[guard:t.size - guard]))]


def test_odd_harmonic_peaks_at_e0_eff_without_catalysis():
    """无催化步时，奇次谐波包络峰应落在 E0_eff 上。

    这是 Snitkoff-Sol 2022 用于定位氧化还原电位的判据（奇次谐波中心峰、
    偶次谐波中心极小值对应反应电位）。
    """
    for e0 in (1.50, 1.60):
        params = _base_params(E0_eff=e0, kf=0.0, E_start=1.20, v=0.05,
                              total_time=10.0)
        assert _odd_harmonic_peak(params) == pytest.approx(e0, abs=0.02)


def test_catalysis_shifts_odd_harmonic_peak_positive():
    """EC' 催化步应把奇次谐波峰推向更正电位，且随 kf 单调。

    这是 Bonke 2016 中 process II 的判据（谐波峰位耦合到化学步而非
    单纯电子转移），也是 E0_eff 与 kf 在拟合中并非正交的原因。
    """
    peaks = [
        _odd_harmonic_peak(
            _base_params(E0_eff=1.50, kf=kf, E_start=1.20, v=0.05,
                         total_time=10.0)
        )
        for kf in (0.0, 100.0)
    ]
    assert peaks[1] > peaks[0] + 0.02


def test_even_harmonic_has_central_minimum_at_e0_eff():
    """偶次谐波在 E0_eff 处应为局部极小而非极大。"""
    params = _base_params(E0_eff=1.50, kf=0.0, E_start=1.20, v=0.05,
                          total_time=10.0)
    t = _grid(params)
    _, i_total, _ = simulate(params, t)
    spectrum = np.fft.rfft(i_total)
    freqs = np.fft.rfftfreq(t.size, d=t[1] - t[0])
    mask = np.abs(freqs - 2 * params["f"]) < 0.4 * params["f"]
    filtered = np.zeros_like(spectrum)
    filtered[mask] = spectrum[mask]
    envelope = np.abs(np.fft.irfft(filtered, t.size))
    e_dc = params["E_start"] + params["v"] * t

    at_e0 = envelope[np.abs(e_dc - 1.50) < 0.005].mean()
    lobes = max(
        envelope[np.abs(e_dc - 1.44) < 0.005].mean(),
        envelope[np.abs(e_dc - 1.56) < 0.005].mean(),
    )
    assert at_e0 < 0.8 * lobes


def test_every_free_parameter_bound_has_a_source_label():
    """WORK_STATUS §4.2：每个边界都必须带来源标签，且标签在允许集合内。"""
    from oer_aem.low_dim_fit import BOUND_PROVENANCE, PARAM_NAMES

    allowed = {"fixed", "measured", "literature", "weak_prior", "engineering"}
    for name in PARAM_NAMES:
        real = name.replace("log10_", "")
        assert real in BOUND_PROVENANCE, f"{real} 缺少边界来源标注"
        entry = BOUND_PROVENANCE[real]
        assert entry["lower_source"] in allowed
        assert entry["upper_source"] in allowed
        assert entry["note"].strip(), f"{real} 的来源说明为空"
