"""实验数据加载与导出模块（对应 MATLAB OER_IO.m）。"""

import os
import warnings
from typing import Dict, Any, Optional, Tuple

import numpy as np

from .physics import initialize_system, OERPhysics
from .signal import process_data


def read_numeric_file(file_path: str) -> np.ndarray:
    """读取数值文本文件。"""
    if not os.path.isfile(file_path):
        raise FileNotFoundError(f'文件不存在: {file_path}')
    try:
        data = np.loadtxt(file_path)
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f'实验数据无法读取: {file_path}') from exc
    if data.size == 0 or not np.issubdtype(data.dtype, np.number):
        raise ValueError(f'实验数据无法读取: {file_path}')
    return data


def load_experimental_data(params: Dict[str, Any]) -> Dict[str, Any]:
    """加载 FTacV 实验数据。"""
    raw_data = read_numeric_file(params['data_path'])
    if raw_data.ndim == 1:
        raw_data = raw_data.reshape(-1, 1)
    if raw_data.shape[1] < 3:
        raise ValueError(f'实验数据列数不足: {params["data_path"]}')
    raw_data = raw_data[:, :3]

    if params.get('Eref', 0) != 0:
        raw_data[:, 0] += params['Eref']

    time_rel = raw_data[:, 2] - raw_data[0, 2]
    order = np.argsort(time_rel)
    raw_data = raw_data[order, :]

    time_unique, idx = np.unique(time_rel[order], return_index=True)
    t_e_exp = np.linspace(0.0, params['total_time'], int(params['n_points']))

    exp_data = {}
    exp_data['raw'] = raw_data
    exp_data['time'] = t_e_exp
    exp_data['current'] = np.interp(t_e_exp, time_unique, raw_data[idx, 1])

    dt = np.mean(np.diff(t_e_exp))
    exp_data['df'] = 1.0 / dt
    exp_data['i_total'] = exp_data['current']

    # 预处理实验谐波
    tdc, I_processed = process_data(exp_data['time'], None, exp_data['current'], params, None)
    exp_data['tdc'] = tdc
    exp_data['I_processed'] = I_processed
    exp_data['I_dc'] = I_processed[:, 0]
    exp_data['I_harmonics'] = I_processed[:, 1:8]
    return exp_data


def load_lsv_data(params: Dict[str, Any], file_path: Optional[str] = None) -> Dict[str, Any]:
    """加载 LSV 数据。"""
    if file_path is None or not file_path:
        file_path = params['data_path']

    raw_all = read_numeric_file(file_path)
    if raw_all.ndim == 1:
        raw_all = raw_all.reshape(-1, 1)
    if raw_all.shape[1] < 3:
        raise ValueError('未解析到任何数值数据。')

    potential = raw_all[:, 0]
    current = raw_all[:, 1]
    time_abs = raw_all[:, 2]
    time_rel = time_abs - time_abs[0]

    if params.get('Eref', 0) != 0:
        potential += params['Eref']

    exp_data = {}
    exp_data['raw'] = np.column_stack([potential, current, time_abs])
    exp_data['potential_raw'] = potential
    exp_data['current_raw'] = current
    exp_data['time_raw'] = time_rel

    order = np.argsort(time_rel)
    potential_sorted = potential[order]
    current_sorted = current[order]
    time_rel_sorted = time_rel[order]

    time_unique, idx = np.unique(time_rel_sorted, return_index=True)
    potential_u = potential_sorted[idx]
    current_u = current_sorted[idx]

    time_grid = np.linspace(0.0, params['total_time'], int(params['n_points']))
    exp_data['time'] = time_grid
    exp_data['current'] = np.interp(time_grid, time_unique, current_u)
    exp_data['potential'] = np.interp(time_grid, time_unique, potential_u)

    dt = np.mean(np.diff(time_grid))
    exp_data['df'] = 1.0 / dt
    exp_data['i_total'] = exp_data['current']
    return exp_data


def configure_params_for_lsv(params: Dict[str, Any], exp_data: Dict[str, Any]) -> Dict[str, Any]:
    """根据 LSV 实验数据配置扫描参数。"""
    params = dict(params)
    t_end = float(exp_data['time_raw'][-1])
    params['dE'] = 0.0
    params['total_time'] = t_end
    params['n_points'] = len(exp_data['time_raw'])
    params['t_span'] = np.linspace(0.0, params['total_time'], params['n_points'])
    params['E_start'] = float(exp_data['potential_raw'][0])
    params['E_end'] = float(exp_data['potential_raw'][-1])
    params['omega'] = 2 * np.pi * params['f']
    params['v'] = (params['E_end'] - params['E_start']) / params['total_time']
    return initialize_system(params)


def load_data_for_objective(params: Dict[str, Any], file_path: Optional[str] = None,
                            default_mode: str = 'ftacv') -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """统一数据加载入口。"""
    params = dict(params)
    if file_path is not None and file_path:
        params['data_path'] = file_path

    params['objective_mode'] = str(default_mode).lower()

    if params['objective_mode'] == 'lsv':
        exp_data = load_lsv_data(params)
        params['dE'] = 0.0
        exp_data['potential'] = np.asarray(exp_data['potential_raw']).reshape(-1)
        exp_data['current'] = np.asarray(exp_data['current_raw']).reshape(-1)
        exp_data['time'] = np.asarray(exp_data['time_raw']).reshape(-1)
        params['total_time'] = float(exp_data['time_raw'][-1])
        params['n_points'] = len(exp_data['time_raw'])
        params['t_span'] = np.linspace(0.0, params['total_time'], params['n_points'])
        params['omega'] = 2 * np.pi * params['f']
        params['v'] = (params['E_end'] - params['E_start']) / params['total_time']
        params = initialize_system(params)
    else:
        exp_data = load_experimental_data(params)
        params = initialize_system(params)

    return params, exp_data


def create_unique_folder(save_root: str, data_path: str, suffix: Optional[str] = None) -> str:
    """创建唯一保存文件夹。"""
    parent_folder = os.path.basename(os.path.dirname(data_path))
    filename = os.path.splitext(os.path.basename(data_path))[0]

    if suffix:
        base_name = f'{parent_folder}_{filename}_{suffix}'
    else:
        base_name = f'{parent_folder}_{filename}'

    main_folder_path = os.path.join(save_root, base_name)
    os.makedirs(main_folder_path, exist_ok=True)

    i = 1
    while True:
        folder_name = os.path.join(main_folder_path, str(i))
        if not os.path.exists(folder_name):
            os.makedirs(folder_name, exist_ok=True)
            return folder_name
        i += 1


def _export_data(data: np.ndarray, params: Dict[str, Any], data_type: str) -> str:
    """导出数据到文本文件。"""
    save_dir = os.path.join(params.get('result_root', '.'), 'exported_simulation_data')
    os.makedirs(save_dir, exist_ok=True)
    base_filename = os.path.splitext(os.path.basename(params['data_path']))[0]
    export_path = os.path.join(save_dir, f'{base_filename}_{data_type}_exported.txt')
    np.savetxt(export_path, data, delimiter='\t')
    print(f'数据已导出到: {export_path}')
    return export_path


def export_i_total(E_actual: np.ndarray, i_total: np.ndarray, t: np.ndarray,
                   params: Dict[str, Any]) -> str:
    """导出总电流。"""
    data = np.column_stack([E_actual, i_total, t])
    return _export_data(data, params, 'i_total')


def export_I_sim(tdc: np.ndarray, I_sim: np.ndarray, params: Dict[str, Any]) -> str:
    """导出仿真谐波。"""
    data = np.column_stack([tdc, I_sim])
    return _export_data(data, params, 'I_sim')


def export_I_exp(tdc_exp: np.ndarray, I_exp: np.ndarray, params: Dict[str, Any]) -> str:
    """导出实验谐波。"""
    data = np.column_stack([tdc_exp, I_exp])
    return _export_data(data, params, 'I_exp')


class OERIO:
    """实验数据 IO 入口类（对应 MATLAB OER_IO）。"""

    @staticmethod
    def load_experimental_data(params):
        return load_experimental_data(params)

    @staticmethod
    def read_numeric_file(file_path):
        return read_numeric_file(file_path)

    @staticmethod
    def load_lsv_data(params, file_path=None):
        return load_lsv_data(params, file_path)

    @staticmethod
    def configure_params_for_lsv(params, exp_data):
        return configure_params_for_lsv(params, exp_data)

    @staticmethod
    def load_data_for_objective(params, file_path=None, default_mode='ftacv'):
        return load_data_for_objective(params, file_path, default_mode)

    @staticmethod
    def create_unique_folder(save_root, data_path, suffix=None):
        return create_unique_folder(save_root, data_path, suffix)

    @staticmethod
    def export_i_total(E_actual, i_total, t, params):
        return export_i_total(E_actual, i_total, t, params)

    @staticmethod
    def export_I_sim(tdc, I_sim, params):
        return export_I_sim(tdc, I_sim, params)

    @staticmethod
    def export_I_exp(tdc_exp, I_exp, params):
        return export_I_exp(tdc_exp, I_exp, params)
