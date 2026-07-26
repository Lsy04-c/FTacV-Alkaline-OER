"""Experimental Numba-JIT OER AEM RHS; not part of the formal solver path."""

import numpy as np
from numba import njit


@njit(cache=True)
def oer_rhs_jit(t, y, p):
    """JIT-compiled OER AEM RHS.

    p layout (32 doubles):
      [E_start, E_end, f, dE, Ru, Cdl, A, gamma,
       k0_1, k0_2, k0_3, k0_4, k0_pre,
       G_OH, G_O, scaling_OOH_OH, a,
       E01, E02, E03, E04, E0_pre,
       RTF, invRC, gammaF_Cdl, total_time, v, omega,
       beta_recon, E_recon, w_recon, F]
    """
    th_s, th_ox, th_OH, th_O, th_OOH, phi = y[0], y[1], y[2], y[3], y[4], y[5]

    s = th_s + th_ox + th_OH + th_O + th_OOH
    if s > 1e-12:
        inv = 1.0 / s
        th_s *= inv; th_ox *= inv; th_OH *= inv; th_O *= inv; th_OOH *= inv

    E = p[0] + p[26] * t + p[3] * np.sin(p[27] * t)
    RTF = p[22]; a = p[16]; b = 1.0 - a
    bRTF = b * RTF; maRTF = -a * RTF

    ep = phi - p[21]; e1 = phi - p[17]; e2 = phi - p[18]
    e3 = phi - p[19]; e4 = phi - p[20]

    kfp = p[12] * np.exp(min(bRTF * ep, 100.0)) if bRTF * ep < 600 else 1e100
    krp = p[12] * np.exp(min(maRTF * ep, 100.0)) if maRTF * ep < 600 else 1e100
    kf1 = p[8]  * np.exp(min(bRTF * e1, 100.0)) if bRTF * e1 < 600 else 1e100
    kr1 = p[8]  * np.exp(min(maRTF * e1, 100.0)) if maRTF * e1 < 600 else 1e100
    kf2 = p[9]  * np.exp(min(bRTF * e2, 100.0)) if bRTF * e2 < 600 else 1e100
    kr2 = p[9]  * np.exp(min(maRTF * e2, 100.0)) if maRTF * e2 < 600 else 1e100
    kf3 = p[10] * np.exp(min(bRTF * e3, 100.0)) if bRTF * e3 < 600 else 1e100
    kr3 = p[10] * np.exp(min(maRTF * e3, 100.0)) if maRTF * e3 < 600 else 1e100
    kf4 = p[11] * np.exp(min(bRTF * e4, 100.0)) if bRTF * e4 < 600 else 1e100
    kr4 = p[11] * np.exp(min(maRTF * e4, 100.0)) if maRTF * e4 < 600 else 1e100

    a_OH = 1.0; a_H2O = 1.0
    rp = kfp * th_s   * a_OH - krp * th_ox * a_H2O
    r1 = kf1 * th_ox  * a_OH - kr1 * th_OH
    r2 = kf2 * th_OH  * a_OH - kr2 * th_O  * a_H2O
    r3 = kf3 * th_O   * a_OH - kr3 * th_OOH
    r4 = kf4 * th_OOH * a_OH - kr4 * th_ox * a_H2O

    dydt = np.zeros(6)
    dydt[0] = -rp; dydt[1] = rp - r1 + r4; dydt[2] = r1 - r2
    dydt[3] = r2 - r3; dydt[4] = r3 - r4

    g_eff = p[7]
    if p[28] > 0:
        x = (E - p[29]) / max(p[30], 1e-6)
        if x > -60.0 and x < 60.0:
            g_eff = p[7] * (1.0 + p[28] / (1.0 + np.exp(-x)))

    gF_Cdl = g_eff * p[31] / p[5]
    r_elec = rp + r1 + r2 + r3 + r4
    dydt[5] = (E - phi) * p[23] - gF_Cdl * r_elec

    for i in range(5):
        if y[i] <= 0.0 and dydt[i] < 0.0:
            dydt[i] = 0.0
    return dydt


# Parameter list matching the p array layout
PARAM_KEYS = [
    "E_start", "E_end", "f", "dE", "Ru", "Cdl", "A", "gamma",
    "k0_1", "k0_2", "k0_3", "k0_4", "k0_pre",
    "G_OH", "G_O", "scaling_OOH_OH", "a",
    "E01", "E02", "E03", "E04", "E0_pre",
    "RTF", "invRC", "gammaF_Cdl", "total_time", "v", "omega",
    "beta_recon", "E_recon", "w_recon", "F",
]


def pack_params(params: dict) -> np.ndarray:
    """Convert params dict to flat double array for JIT RHS."""
    p = np.zeros(32, dtype=np.float64)
    for i, key in enumerate(PARAM_KEYS):
        p[i] = float(params.get(key, 0.0))
    return p


def make_jit_rhs(params: dict):
    """Return a callable f(t, y) suitable for scipy.integrate.solve_ivp."""
    p = pack_params(params)
    # Warm up JIT
    y0 = np.zeros(6)
    oer_rhs_jit(0.0, y0, p)
    return lambda t, y: oer_rhs_jit(t, np.asarray(y, dtype=np.float64), p)
