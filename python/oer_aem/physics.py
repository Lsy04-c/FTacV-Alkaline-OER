"""碱性 OER 微观动力学模型（含预氧化步骤）。

模型参考：
    Bonke et al. (2016) JACS 138, 16095–16104.
    Snitkoff-Sol et al. (2024) Nat. Catal. 7, 139–147.
    Bergmann et al. (2015) Nat. Commun. 6, 8625.

反应步骤（5 步）：
    0. * + OH-  <=> *ox + H2O + e-       预氧化（Co3+ -> Co4+）
    1. *ox + OH- <=> *ox-OH + e-         AEM-1
    2. *ox-OH + OH- <=> *ox-O + H2O + e-  AEM-2
    3. *ox-O + OH- <=> *ox-OOH + e-       AEM-3
    4. *ox-OOH + OH- <=> *ox + O2 + H2O + e-  AEM-4
"""

import warnings
from types import SimpleNamespace
from typing import Dict, Any, Tuple, List

import numpy as np
from scipy.integrate import solve_ivp

from .thermodynamics import apply_alkaline_aem


def get_state_indices(N: int = 2) -> SimpleNamespace:
    """返回状态变量索引。N 为扩散网格点数（当前模型 N=2，暂不含传质）。"""
    _ = N  # 保留参数以兼容 MATLAB 接口
    idx = SimpleNamespace()
    idx.theta_star = 0    # *   — 还原态 Co 位点
    idx.theta_ox = 1      # *ox — 氧化态 Co 位点（OER 活性位）
    idx.theta_OH = 2      # *ox-OH
    idx.theta_O = 3       # *ox-O
    idx.theta_OOH = 4     # *ox-OOH
    idx.phi_s = 5         # 表面电位 (V)
    idx.num_states = 6    # 不含传质时为 6
    return idx


def get_param_list() -> List[str]:
    """返回与 MEX 兼容的参数名顺序（保留用于 API 兼容）。"""
    return [
        'E_start', 'v', 'dE', 'omega',        # 1-4
        'Ru', 'Cdl', 'A', 'gamma',             # 5-8
        'k0_pre', 'k0_1', 'k0_2', 'k0_3', 'k0_4',  # 9-13
        'E0_pre', 'E01', 'E02', 'E03', 'E04',  # 14-18
        'a', 'RTF', 'invRC',                   # 19-21
        'gammaF_Cdl',                          # 22
        'n_points', 'total_time', 'N'          # 23-25
    ]


def pack_parameters(params: Dict[str, Any]) -> np.ndarray:
    """将参数字典打包为向量（保留 MATLAB 兼容顺序）。"""
    basic = get_param_list()
    n_basic = len(basic)
    vec = np.zeros(n_basic + 8 + 8)
    for i, name in enumerate(basic):
        if name in params:
            vec[i] = params[name]
        else:
            raise KeyError(f'缺少参数: {name}')

    base = n_basic
    if 'band' in params:
        vec[base:base + 8] = np.asarray(params['band']).reshape(8)
    base += 8
    if 'harmonic_weights' in params:
        vec[base:base + 8] = np.asarray(params['harmonic_weights']).reshape(8)
    return vec


def initialize_system(params: Dict[str, Any]) -> Dict[str, Any]:
    """填充默认值并计算派生物理常数。"""
    params = dict(params)

    # 默认值
    params.setdefault('a', 0.5)
    params.setdefault('N', 2)
    params.setdefault('band', np.ones(8) * 0.01)
    params.setdefault('harmonic_weights', np.ones(8))
    params.setdefault('use_steady_state', True)
    params.setdefault('use_mex', False)
    params.setdefault('use_fft', True)

    params.setdefault('F', 96485.0)
    params.setdefault('R', 8.314)
    params.setdefault('T', 298.15)

    # 衍生常数
    params['RTF'] = params['F'] / (params['R'] * params['T'])
    params['invRC'] = 1.0 / (params['Ru'] * params['Cdl'] * params['A'])
    params['gammaF_Cdl'] = params['gamma'] * params['F'] / params['Cdl']
    params['omega'] = 2 * np.pi * params['f']

    return params


def _oer_model_rhs(t: float, y: np.ndarray, params: Dict[str, Any]) -> np.ndarray:
    """ODE 右端函数（内部实现）。"""
    y = np.asarray(y, dtype=float)
    theta_star = y[0]
    theta_ox = y[1]
    theta_OH = y[2]
    theta_O = y[3]
    theta_OOH = y[4]
    phi_s = y[5]

    # 归一化覆盖度
    theta_sum = theta_star + theta_ox + theta_OH + theta_O + theta_OOH
    if theta_sum > 1e-12:
        theta_star /= theta_sum
        theta_ox /= theta_sum
        theta_OH /= theta_sum
        theta_O /= theta_sum
        theta_OOH /= theta_sum

    # 施加电位
    E_dc = params['E_start'] + params['v'] * t
    E_app = E_dc + params['dE'] * np.sin(params['omega'] * t)

    # 模型假设：碱性微纳体系
    a_OH = 1.0
    a_H2O = 1.0

    RTF = params['RTF']
    a = params['a']
    b = 1.0 - a

    # 各步过电位
    eta_pre = phi_s - params['E0_pre']
    eta_1 = phi_s - params['E01']
    eta_2 = phi_s - params['E02']
    eta_3 = phi_s - params['E03']
    eta_4 = phi_s - params['E04']

    # BV 速率常数
    k_fwd_pre = params['k0_pre'] * np.exp(b * RTF * eta_pre)
    k_rev_pre = params['k0_pre'] * np.exp(-a * RTF * eta_pre)

    k_fwd_1 = params['k0_1'] * np.exp(b * RTF * eta_1)
    k_rev_1 = params['k0_1'] * np.exp(-a * RTF * eta_1)

    k_fwd_2 = params['k0_2'] * np.exp(b * RTF * eta_2)
    k_rev_2 = params['k0_2'] * np.exp(-a * RTF * eta_2)

    k_fwd_3 = params['k0_3'] * np.exp(b * RTF * eta_3)
    k_rev_3 = params['k0_3'] * np.exp(-a * RTF * eta_3)

    k_fwd_4 = params['k0_4'] * np.exp(b * RTF * eta_4)
    k_rev_4 = params['k0_4'] * np.exp(-a * RTF * eta_4)

    # 各步速率（正向 - 反向）
    r_pre = k_fwd_pre * theta_star * a_OH - k_rev_pre * theta_ox * a_H2O
    r_1 = k_fwd_1 * theta_ox * a_OH - k_rev_1 * theta_OH
    r_2 = k_fwd_2 * theta_OH * a_OH - k_rev_2 * theta_O * a_H2O
    r_3 = k_fwd_3 * theta_O * a_OH - k_rev_3 * theta_OOH
    r_4 = k_fwd_4 * theta_OOH * a_OH - k_rev_4 * theta_ox * a_H2O

    # 覆盖度演化
    dtheta_star = -r_pre
    dtheta_ox = r_pre - r_1 + r_4
    dtheta_OH = r_1 - r_2
    dtheta_O = r_2 - r_3
    dtheta_OOH = r_3 - r_4

    # 表面电位演化
    r_elec_sum = r_pre + r_1 + r_2 + r_3 + r_4
    dphi_s = (E_app - phi_s) * params['invRC'] + params['gammaF_Cdl'] * r_elec_sum

    dydt = np.array([dtheta_star, dtheta_ox, dtheta_OH, dtheta_O, dtheta_OOH, dphi_s])

    # 非负约束：若某覆盖度接近 0 且导数为负，则阻止其继续减小
    for i in range(5):
        if y[i] <= 0 and dydt[i] < 0:
            dydt[i] = 0.0

    return dydt


class OERPhysics:
    """碱性 OER 物理模型入口类（对应 MATLAB OER_Physics）。"""

    @staticmethod
    def get_state_indices(N: int = 2) -> SimpleNamespace:
        return get_state_indices(N)

    @staticmethod
    def get_param_list() -> List[str]:
        return get_param_list()

    @staticmethod
    def pack_parameters(params: Dict[str, Any]) -> np.ndarray:
        return pack_parameters(params)

    @staticmethod
    def initialize_system(params: Dict[str, Any]) -> Dict[str, Any]:
        return initialize_system(params)

    @staticmethod
    def oer_model(t: float, y: np.ndarray, params: Dict[str, Any]) -> np.ndarray:
        return _oer_model_rhs(t, y, params)

    @staticmethod
    def solve_ode_system(params: Dict[str, Any]) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        """求解 ODE 系统，返回 (t, y, E_actual, i_total)。"""
        if 'RTF' not in params:
            params = initialize_system(params)

        num_states = 6
        y0 = np.zeros(num_states)
        y0[0] = 1.0
        y0[5] = params['E_start']

        if params.get('use_steady_state', True):
            y0 = OERPhysics.calculate_steady_state(params)

        t_span = (0.0, float(params['total_time']))
        t_eval = np.asarray(params['t_span'])
        if t_eval.ndim == 0 or len(t_eval) == 0:
            t_eval = np.linspace(0.0, t_span[1], int(params['n_points']))

        try:
            sol = solve_ivp(
                fun=lambda t, y: _oer_model_rhs(t, y, params),
                t_span=t_span,
                y0=y0,
                t_eval=t_eval,
                method='BDF',
                rtol=1e-5,
                atol=1e-6,
                max_step=t_span[1] / 100.0,
            )
            t = sol.t
            y = sol.y.T
            E_dc = params['E_start'] + params['v'] * t
            E_actual = E_dc + params['dE'] * np.sin(params['omega'] * t)
            i_total = (E_actual - y[:, 5]) / params['Ru']
        except Exception as exc:  # noqa: BLE001
            warnings.warn(f'ODE 求解失败: {exc}', stacklevel=2)
            t = np.asarray(params['t_span']).reshape(-1)
            y = np.full((len(t), num_states), np.nan)
            E_actual = np.full(len(t), np.nan)
            i_total = np.full(len(t), np.nan)

        return t, y, E_actual, i_total

    @staticmethod
    def calculate_steady_state(params: Dict[str, Any]) -> np.ndarray:
        """在起始电位处进行短时间稳态松弛。"""
        num_states = 6
        y0_guess = np.zeros(num_states)
        y0_guess[0] = 1.0
        y0_guess[5] = params['E_start']

        params_ss = dict(params)
        params_ss['v'] = 0.0
        params_ss['dE'] = 0.0
        params_ss['omega'] = 0.0
        params_ss = initialize_system(params_ss)

        ss_time = 5.0
        try:
            sol = solve_ivp(
                fun=lambda t, y: _oer_model_rhs(t, y, params_ss),
                t_span=(0.0, ss_time),
                y0=y0_guess,
                method='BDF',
                rtol=1e-6,
                atol=1e-8,
                max_step=ss_time / 50.0,
            )
            y0 = sol.y[:, -1]
        except Exception as exc:  # noqa: BLE001
            warnings.warn(f'稳态计算失败，使用默认初值: {exc}', stacklevel=2)
            y0 = y0_guess

        return y0

    @staticmethod
    def apply_default_E0(params: Dict[str, Any]) -> Dict[str, Any]:
        """若未提供 E0_pre，使用默认或从自由能生成。"""
        params = dict(params)
        if 'E0_pre' not in params and 'G_OH' in params:
            params = OERPhysics.apply_alkaline_aem_embedded(params)
        elif 'E0_pre' not in params:
            params['E0_pre'] = 1.50
            params['E01'] = 1.55
            params['E02'] = 1.60
            params['E03'] = 1.70
            params['E04'] = 1.45
        return params

    @staticmethod
    def apply_alkaline_aem_embedded(params: Dict[str, Any]) -> Dict[str, Any]:
        """内嵌版 AEM 热力学约束（调用独立模块）。"""
        params = dict(params)
        if 'E0_pre' not in params:
            params['E0_pre'] = 1.50
        return apply_alkaline_aem(params)


# 保持模块级别名，方便直接导入
apply_alkaline_aem_embedded = OERPhysics.apply_alkaline_aem_embedded
apply_default_E0 = OERPhysics.apply_default_E0
