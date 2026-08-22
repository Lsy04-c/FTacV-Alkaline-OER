"""Bonke 分子催化模型（低维 FTacV 正演）。

模型参考：
    Bonke, Bond, Spiccia, Simonov (2016) JACS 138, 16095-16104.

与 `physics.py` 的 5 步 AEM 不同，本模块只实现 Bonke 用于 CoOx/NiOx/MnOx
水氧化的 "molecular catalysis" 模型——一个表面限域氧化还原耦合一个赝一级
催化步：

    A (电子转移)：  *red  <=>  *ox + e-        (E0_eff, k0, alpha)
    B (催化)：      *ox   -->  *red + O2...    (kf，赝一级，化学步无电荷)

选择该模型的理由记录在
`docs/superpowers/plans/2026-08-22-low-dim-bonke-model.md`：自由度与本项目
现有数据的信息量匹配（4 个自由参数 vs AEM 的 8-9 个），且是同体系
（碱性 CoOx 水氧化）唯一的 FTacV 反演先例。

自由参数：``E0_eff``、``k0``、``kf``、``gamma``
钉住参数：``Ru``、``Cdl``、``A``、``alpha``（来源标签见拟合脚本输出）

重要标度简并：法拉第电流正比于 ``gamma * A``。本模块不试图分开二者；
``A`` 被钉住时，反演得到的 ``gamma`` 实为 ``gamma * A / A_assumed``。
"""

from __future__ import annotations

import warnings
from typing import Any, Dict, Tuple

import numpy as np
from scipy.integrate import solve_ivp

F_CONST = 96485.0
R_CONST = 8.314
T_DEFAULT = 298.15


def _safe_exp(x: np.ndarray | float) -> np.ndarray:
    """安全 exp，防止 BV 指数溢出（与 physics.py 保持一致）。"""
    return np.exp(np.clip(np.asarray(x, dtype=float), -708.0, 708.0))


def initialize_mc_system(params: Dict[str, Any]) -> Dict[str, Any]:
    """填充默认值并计算派生常数。"""
    params = dict(params)

    params.setdefault("alpha", 0.5)
    params.setdefault("T", T_DEFAULT)
    params.setdefault("F", F_CONST)
    params.setdefault("R", R_CONST)
    params.setdefault("use_steady_state", True)
    params.setdefault("solver_backend", "lsoda")
    params.setdefault("cn_substeps", 1)

    for required in ("E_start", "v", "dE", "f", "Ru", "Cdl", "A",
                     "gamma", "k0", "kf", "E0_eff", "total_time"):
        if required not in params:
            raise KeyError(f"缺少参数: {required}")

    params["RTF"] = params["F"] / (params["R"] * params["T"])
    params["omega"] = 2.0 * np.pi * params["f"]
    params["invRC"] = 1.0 / (params["Ru"] * params["Cdl"] * params["A"])
    return params


def _mc_rhs(t: float, y: np.ndarray, p: Dict[str, Any]) -> np.ndarray:
    """ODE 右端：状态 = [theta_ox, phi_s]，theta_red = 1 - theta_ox。"""
    theta_ox = min(max(float(y[0]), 0.0), 1.0)
    phi_s = float(y[1])

    theta_red = 1.0 - theta_ox

    E_dc = p["E_start"] + p["v"] * t
    E_app = E_dc + p["dE"] * np.sin(p["omega"] * t)

    RTF = p["RTF"]
    a = p["alpha"]
    eta = phi_s - p["E0_eff"]

    k_fwd = p["k0"] * float(_safe_exp((1.0 - a) * RTF * eta))
    k_rev = p["k0"] * float(_safe_exp(-a * RTF * eta))
    k_fwd = min(k_fwd, 1e100)
    k_rev = min(k_rev, 1e100)

    # 电子转移速率（正向氧化为正）
    r_et = k_fwd * theta_red - k_rev * theta_ox
    # 催化步：赝一级消耗 *ox，再生 *red，化学步不贡献电荷
    r_cat = p["kf"] * theta_ox

    dtheta_ox = r_et - r_cat

    gammaF_Cdl = p["gamma"] * p["F"] / p["Cdl"]
    dphi_s = (E_app - phi_s) * p["invRC"] - gammaF_Cdl * r_et

    if y[0] <= 0.0 and dtheta_ox < 0.0:
        dtheta_ox = 0.0
    if y[0] >= 1.0 and dtheta_ox > 0.0:
        dtheta_ox = 0.0

    return np.array([dtheta_ox, dphi_s])


def calculate_mc_steady_state(p: Dict[str, Any]) -> np.ndarray:
    """在起始电位处短时松弛，得到 ODE 初值。

    与 `physics.calculate_steady_state` 同构：关闭扫描和交流，静置松弛。
    求解器等价性经验（WORK_STATUS §19）表明初值不一致会造成远大于模型
    差异的下游偏差，因此这里保持同一套做法。
    """
    p_ss = dict(p)
    p_ss["v"] = 0.0
    p_ss["dE"] = 0.0
    p_ss = initialize_mc_system(p_ss)
    p_ss["omega"] = 0.0

    y0_guess = np.array([0.0, float(p["E_start"])])
    try:
        sol = solve_ivp(
            fun=lambda t, y: _mc_rhs(t, y, p_ss),
            t_span=(0.0, 5.0),
            y0=y0_guess,
            method="Radau",
            rtol=1e-4,
            atol=1e-8,
            max_step=0.1,
        )
        return sol.y[:, -1]
    except Exception as exc:  # noqa: BLE001
        warnings.warn(f"稳态计算失败，使用默认初值: {exc}", stacklevel=2)
        return y0_guess


def simulate(params: Dict[str, Any], t_eval: np.ndarray) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """求解模型，返回 ``(E_app, i_total, theta_ox)``。

    ``i_total`` 由 ``(E_app - phi_s) / Ru`` 得到，与 `physics.py` 一致，
    因此天然包含双电层电流。

    ``params["solver_backend"]`` 可取 ``"lsoda"``（默认）或 ``"cn"``。
    ``"cn"`` 走 `mc_cn_bridge` 的编译求解器；**动态库缺失或求解失败时直接
    抛错，不静默回退**（`docs/项目纠错.md` 第 7 条）。CN 路径不返回覆盖度，
    第三个返回值为 NaN 数组——它只用于搜索加速，覆盖度诊断请用 LSODA。
    """
    p = initialize_mc_system(params)
    t_eval = np.asarray(t_eval, dtype=float)

    y0 = (calculate_mc_steady_state(p) if p["use_steady_state"]
          else np.array([0.0, float(p["E_start"])]))

    backend = str(p.get("solver_backend", "lsoda")).lower()
    if backend == "cn":
        from .mc_cn_bridge import solve as cn_solve
        # 与 LSODA 共用同一个稳态初值 y0，见 mc_cn_bridge.solve 的说明
        t_out, i_total = cn_solve(p, y0, t_eval, int(p.get("cn_substeps", 1)))
        E_app = (p["E_start"] + p["v"] * t_out
                 + p["dE"] * np.sin(p["omega"] * t_out))
        return E_app, i_total, np.full(t_out.size, np.nan)
    if backend != "lsoda":
        raise ValueError(f"未知 solver_backend: {backend!r}（可选 lsoda / cn）")

    try:
        sol = solve_ivp(
            fun=lambda t, y: _mc_rhs(t, y, p),
            t_span=(float(t_eval[0]), float(t_eval[-1])),
            y0=y0,
            t_eval=t_eval,
            method="LSODA",
            rtol=1e-6,
            atol=1e-9,
            max_step=1.0 / (p["f"] * 20.0),
        )
        if not sol.success:
            raise RuntimeError(f"ODE 中断于 t={sol.t[-1]:.4g}: {sol.message}")
        y = sol.y.T
    except Exception as exc:  # noqa: BLE001
        warnings.warn(f"ODE 求解失败: {exc}", stacklevel=2)
        nan = np.full(t_eval.size, np.nan)
        return nan, nan, nan

    E_dc = p["E_start"] + p["v"] * t_eval
    E_app = E_dc + p["dE"] * np.sin(p["omega"] * t_eval)
    i_total = (E_app - y[:, 1]) / p["Ru"]

    # 覆盖度按定义属于 [0, 1]。求解器的稠密输出可以在边界附近下冲/上冲
    # 约 atol 量级（不同 SciPy 版本的步长控制不同，实测本机 1.18 与拯救者
    # 1.16 的下冲量不同）。RHS 内部本来就对 theta 做同样的截断，所以这里
    # 截断输出不改变解，只是消除版本相关的边界噪声。
    coverage = np.clip(y[:, 0], 0.0, 1.0)
    return E_app, i_total, coverage
