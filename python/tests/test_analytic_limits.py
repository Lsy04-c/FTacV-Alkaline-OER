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
    """可逆极限下 H1–H4 必须匹配 Nernst 闭式解。

    k0 -> 无穷、无催化、Ru -> 0 时，表面覆盖度严格服从 Nernst：

        theta_ox(t) = 1 / (1 + exp(-f (E_app - E0)))
        i_F(t)      = A * gamma * F * f * theta (1-theta) * dE_app/dt

    且 Ru -> 0 时电容电流只贡献 DC 与一次谐波，因此 H2 以上纯属法拉第。
    """
    e0, area, gamma = 1.58, 1.0, 1e-11
    f0, amplitude, scan_rate = 5.0, 0.16, 0.02
    e_start, n_cycles = 1.45, 12
    total_time = n_cycles / f0
    n = int(n_cycles * 512)
    t = np.linspace(0.0, total_time, n, endpoint=False)
    omega = 2 * np.pi * f0

    params = dict(E_start=e_start, v=scan_rate, dE=amplitude, f=f0,
                  Ru=0.01, Cdl=30.8e-6, A=area, gamma=gamma,
                  k0=1e7, kf=0.0, E0_eff=e0, total_time=total_time)
    _, i_ode, _ = simulate(params, t)

    e_app = e_start + scan_rate * t + amplitude * np.sin(omega * t)
    theta = 1.0 / (1.0 + np.exp(-F_OVER_RT * (e_app - e0)))
    de_dt = scan_rate + amplitude * omega * np.cos(omega * t)
    i_exact = (area * gamma * F_CONST * F_OVER_RT * theta * (1 - theta) * de_dt
               + params["Cdl"] * area * de_dt)

    guard = int(0.12 * n)
    for harmonic in (1, 2, 3, 4):
        exact = _harmonic_envelope(i_exact, t, harmonic, f0)[guard:-guard].max()
        numeric = _harmonic_envelope(i_ode, t, harmonic, f0)[guard:-guard].max()
        assert numeric == pytest.approx(exact, rel=0.02), (
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
    assert np.max(np.abs(i_full - i_cap)) / scale < 1e-3
