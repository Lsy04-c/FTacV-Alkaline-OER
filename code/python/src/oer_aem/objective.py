"""目标函数与参数编解码模块（对应 MATLAB OER_Objective.m）。"""

from typing import Dict, Any, Tuple, List, Optional

import numpy as np

from .physics import initialize_system, OERPhysics
from .signal import extract_harmonics, process_current, safe_df


def calculate_objective(I_sim: np.ndarray, I_exp: np.ndarray,
                        harmonic_weights: np.ndarray) -> float:
    """计算谐波归一化误差目标函数。"""
    I_sim = np.asarray(I_sim)
    I_exp = np.asarray(I_exp)
    harmonic_weights = np.asarray(harmonic_weights)

    total_error = 0.0
    for i in range(I_sim.shape[1]):
        denom = np.mean(I_exp[:, i] ** 2)
        if denom <= 0 or not np.isfinite(denom):
            denom = 1e-12
        err = np.mean((I_sim[:, i] - I_exp[:, i]) ** 2) / denom
        total_error += err * harmonic_weights[i]
    return float(total_error / np.sum(harmonic_weights))


def process_harmonics(t: np.ndarray, i_total: np.ndarray, params: Dict[str, Any],
                      exp_data: Optional[Dict[str, Any]]) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """谐波提取（简化版，与 signal.process_current 对齐）。"""
    t = np.asarray(t).reshape(-1)
    i_total = np.asarray(i_total).reshape(-1)
    df = safe_df(t)
    tdc = params['E_start'] + t * params['v']

    # DC 分量
    sos = params.get('lp_filter_sos', None)
    if sos is not None:
        I_dc = np.abs(filtfilt(sos, i_total))
    else:
        from .signal import _design_lowpass_sos
        fc = params['band'][0] / 2.0
        sos = _design_lowpass_sos(fc, df, order=6)
        I_dc = np.abs(filtfilt(sos, i_total))

    # 谐波提取
    harmonics = extract_harmonics(i_total, df, params)
    I_sim = np.column_stack([I_dc, harmonics])

    if exp_data is None or len(exp_data) == 0:
        tdc_exp = np.array([])
        I_exp = np.array([])
    elif 'I_processed' in exp_data:
        tdc_exp = np.asarray(exp_data['tdc']).reshape(-1)
        I_exp = np.asarray(exp_data['I_processed'])
    else:
        tdc_exp = tdc
        I_exp = np.zeros_like(I_sim)

    return tdc, I_sim, tdc_exp, I_exp


def align_data(tdc: np.ndarray, I_sim: np.ndarray, tdc_exp: np.ndarray) -> np.ndarray:
    """将仿真数据对齐到实验电位网格。"""
    tdc = np.asarray(tdc).reshape(-1)
    tdc_exp = np.asarray(tdc_exp).reshape(-1)
    I_sim = np.atleast_2d(np.asarray(I_sim))

    if len(tdc) == len(tdc_exp):
        return I_sim

    I_sim_aligned = np.zeros((len(tdc_exp), I_sim.shape[1]))
    for i in range(I_sim.shape[1]):
        I_sim_aligned[:, i] = np.interp(tdc_exp, tdc, I_sim[:, i])
    return I_sim_aligned


def decode_params(x_vals: np.ndarray, params: Dict[str, Any],
                  param_names: List[str]) -> Dict[str, Any]:
    """将优化向量解码回参数字典。"""
    current_p = dict(params)
    for i, p_name in enumerate(param_names):
        val = x_vals[i]
        if p_name.startswith('log_'):
            real_name = p_name[4:]
            current_p[real_name] = 10.0 ** val
        else:
            current_p[p_name] = val

    # 重新生成 E0
    current_p = OERPhysics.apply_alkaline_aem_embedded(current_p)
    return current_p


def get_optim_config(params: Dict[str, Any]) -> Tuple[np.ndarray, np.ndarray, np.ndarray, List[str]]:
    """生成优化初始值、上下界与参数名列表。"""
    names = list(params['optimize_params'])
    N = len(names)
    x = np.zeros(N)
    lb = np.zeros(N)
    ub = np.zeros(N)

    for i, name in enumerate(names):
        range_name = f'{name}_range'
        if range_name in params:
            range_val = params[range_name]
        else:
            range_val = [-1e5, 1e5]
        lb[i] = range_val[0]
        ub[i] = range_val[1]

        if name in params:
            x[i] = params[name]
        elif name.startswith('log_'):
            orig = name[4:]
            if orig in params:
                x[i] = np.log10(params[orig])
            else:
                x[i] = (lb[i] + ub[i]) / 2.0
        else:
            x[i] = (lb[i] + ub[i]) / 2.0

        x[i] = max(lb[i], min(ub[i], x[i]))

    return x, lb, ub, names


def calculate_objective_from_simulation(t: np.ndarray, y: np.ndarray,
                                      E_actual: np.ndarray, i_total: np.ndarray,
                                      params: Dict[str, Any],
                                      exp_data: Optional[Dict[str, Any]]) -> float:
    """从仿真结果计算目标函数。"""
    mode = str(params.get('objective_mode', 'ftacv')).lower()

    if mode == 'lsv':
        exp_p = np.asarray(exp_data['potential']).reshape(-1)
        exp_i = np.asarray(exp_data['current']).reshape(-1)
        order = np.argsort(exp_p)
        exp_p = exp_p[order]
        exp_i = exp_i[order]
        # 去除重复电位
        _, idx = np.unique(exp_p, return_index=True)
        exp_p = exp_p[np.sort(idx)]
        exp_i = exp_i[np.sort(idx)]
        i_exp = np.interp(E_actual, exp_p, exp_i)
        j_sim = i_total / params['A'] * 1e3
        j_exp = i_exp / params['A'] * 1e3
        return float(np.sqrt(np.mean((j_sim - j_exp) ** 2)))

    # FTacV 模式
    i_total = np.real(np.asarray(i_total, dtype=float)).reshape(-1)
    if np.count_nonzero(np.isfinite(i_total)) < max(2, int(0.9 * i_total.size)):
        return np.inf

    _, I_sim, _, I_exp = process_harmonics(t, i_total, params, exp_data)
    return calculate_objective(I_sim, I_exp, params['harmonic_weights'])


class OERObjective:
    """目标函数与优化工具入口类。"""

    @staticmethod
    def calculate_objective(I_sim, I_exp, harmonic_weights):
        return calculate_objective(I_sim, I_exp, harmonic_weights)

    @staticmethod
    def calculate_objective_from_simulation(t, y, E_actual, i_total, params, exp_data):
        return calculate_objective_from_simulation(t, y, E_actual, i_total, params, exp_data)

    @staticmethod
    def process_harmonics(t, i_total, params, exp_data):
        return process_harmonics(t, i_total, params, exp_data)

    @staticmethod
    def align_data(tdc, I_sim, tdc_exp):
        return align_data(tdc, I_sim, tdc_exp)

    @staticmethod
    def decode_params(x_vals, params, param_names):
        return decode_params(x_vals, params, param_names)

    @staticmethod
    def get_optim_config(params):
        return get_optim_config(params)


from scipy.signal import filtfilt  # noqa: E402
