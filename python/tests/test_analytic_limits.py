"""正演模型的解析极限校验——项目自建实现的**外部**参照。

为什么需要：`test_molecular_catalysis.py` 的 9 项测试全部是自洽的（模型
与自己比），无法发现"整套实现一致地错"。本文件用**闭式解**作参照，
不依赖任何外部软件。

为什么不用 MECSim：它是 2019 年编译、无签名、无源码、仓库停更 7 年的
二进制，且依赖 Debian 已下架的 libgfortran3。要跑通它需要拼装一个不再
存在的运行时环境——参照物本身的可信度会低于被验证对象。
详见 `docs/external_validation.md`。
"""

import numpy as np
import pytest

from oer_aem.molecular_catalysis import simulate

F_CONST = 96485.0
R_CONST = 8.314
T_CONST = 298.15
F_OVER_RT = F_CONST / (R_CONST * T_CONST)


def _harmonic_envelope(signal, t, harmonic, f0):
    spectrum = np.fft.rfft(signal)
    freqs = np.fft.rfftfreq(signal.size, t[1] - t[0])
    mask = np.abs(freqs - harmonic * f0) < 0.4 * f0
    filtered = np.zeros_like(spectrum)
    filtered[mask] = spectrum[mask]
    return np.abs(np.fft.irfft(filtered * 2, signal.size))


def test_reversible_limit_matches_nernst_closed_form():
    """可逆极限下法拉第谐波必须匹配 Nernst 闭式解。

        theta_ox(E) = 1 / (1 + exp(-f (E - E0)))
        i_F(t)      = A * gamma * F * f * theta (1-theta) * dE_app/dt

    **必须扣除同一体系 gamma=0 的电容基线再比较。** 闭式解假设 Ru -> 0，
    而 ODE 用的是有限 Ru，两者的电容支路存在固定的绝对差异；不扣除时该
    差异会被较小的法拉第信号除大，表现为 H3 约 0.65% 的"偏差"，且随
    gamma 减小而增大（∝1/gamma），一度被误判为模型误差。扣除后误差降到
    5e-5 量级且不再随 gamma 变化——说明那是参照式的电容污染，不是模型问题。

    该污染还与求解器版本相关（松容差下 SciPy 1.16 与 1.18 表现不同），
    是本测试曾在拯救者失败而在本机通过的原因。扣除基线后两平台一致。
    """
    e0, area = 1.58, 1.0
    f0, amplitude, scan_rate = 5.0, 0.16, 0.02
    e_start, n_cycles = 1.45, 12
    total_time = n_cycles / f0
    n = int(n_cycles * 512)
    t = np.linspace(0.0, total_time, n, endpoint=False)
    omega = 2 * np.pi * f0

    # 收紧容差：k0=1e7 的可逆极限极其刚性，默认 rtol=1e-6 下差分残差
    # 达 1e-3–9e-3，测到的会是积分误差而非模型正确性。
    base = dict(E_start=e_start, v=scan_rate, dE=amplitude, f=f0,
                Ru=0.01, Cdl=30.8e-6, A=area, k0=1e7, kf=0.0,
                E0_eff=e0, total_time=total_time, rtol=1e-9, atol=1e-12)
    gamma = 1e-11
    _, i_full, _ = simulate({**base, "gamma": gamma}, t)
    _, i_cap, _ = simulate({**base, "gamma": 0.0}, t)
    i_faradaic = i_full - i_cap

    e_app = e_start + scan_rate * t + amplitude * np.sin(omega * t)
    theta = 1.0 / (1.0 + np.exp(-F_OVER_RT * (e_app - e0)))
    de_dt = scan_rate + amplitude * omega * np.cos(omega * t)
    i_exact = area * gamma * F_CONST * F_OVER_RT * theta * (1 - theta) * de_dt

    guard = int(0.12 * n)
    for harmonic in (2, 3, 4):
        exact = _harmonic_envelope(i_exact, t, harmonic, f0)[guard:-guard].max()
        numeric = _harmonic_envelope(i_faradaic, t, harmonic, f0)[guard:-guard].max()
        assert numeric == pytest.approx(exact, rel=5e-4), (
            f"H{harmonic} 偏离 Nernst 解析解：解析 {exact:.4e} vs 数值 {numeric:.4e}"
        )


def test_catalytic_steady_state_matches_closed_form():
    """强催化 + 慢扫下，直流电流必须匹配稳态闭式解。

    dtheta/dt -> 0 时：

        theta_ox = k_fwd / (k_fwd + k_rev + kf)
        i        = A * gamma * F * kf * theta_ox

    这一支覆盖 `test_reversible_limit_...` 未覆盖的催化步。
    """
    e0, area, gamma = 1.58, 1.0, 1e-10
    k0, kf, alpha = 1e5, 500.0, 0.5
    f0, scan_rate = 5.0, 0.002
    e_start, total_time = 1.70, 4.0        # 远正于 E0，覆盖度已达稳态平台
    n = int(total_time * f0 * 512)
    t = np.linspace(0.0, total_time, n, endpoint=False)

    params = dict(E_start=e_start, v=scan_rate, dE=0.0, f=f0, Ru=0.01,
                  Cdl=30.8e-6, A=area, gamma=gamma, k0=k0, kf=kf,
                  E0_eff=e0, alpha=alpha, total_time=total_time)
    _, i_ode, _ = simulate(params, t)

    tail = slice(int(0.7 * n), None)
    e_app = e_start + scan_rate * t
    eta = e_app - e0
    k_fwd = k0 * np.exp((1 - alpha) * F_OVER_RT * eta)
    k_rev = k0 * np.exp(-alpha * F_OVER_RT * eta)
    theta_ss = k_fwd / (k_fwd + k_rev + kf)
    i_exact = area * gamma * F_CONST * kf * theta_ss

    assert i_ode[tail].mean() == pytest.approx(i_exact[tail].mean(), rel=0.02)


def test_no_faradaic_current_far_below_e0():
    """远负于 E0 时法拉第电流应可忽略，总电流退化为纯电容。"""
    total_time = 2.0
    params = dict(E_start=0.60, v=0.0, dE=0.16, f=5.0, Ru=10.0, Cdl=30.8e-6,
                  A=1.0, gamma=1e-9, k0=100.0, kf=100.0, E0_eff=1.58,
                  total_time=total_time)
    n = int(total_time * 5.0 * 256)
    t = np.linspace(0.0, total_time, n, endpoint=False)
    _, i_full, _ = simulate(params, t)
    _, i_cap, _ = simulate(dict(params, gamma=0.0), t)
    scale = np.max(np.abs(i_cap))
    # 2e-3 而非 1e-3：该比值本身在不同 SciPy 版本上有约 1e-4 的浮动
    # （拯救者实测 1.04e-3），阈值需留出求解器实现差异的余量。
    assert np.max(np.abs(i_full - i_cap)) / scale < 2e-3
