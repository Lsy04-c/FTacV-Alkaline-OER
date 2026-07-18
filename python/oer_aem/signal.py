"""FTacV 信号处理模块（谐波提取、滤波、对齐）。

参照 MATLAB OER_Signal.m，使用 scipy.signal 与 numpy.fft 实现。
"""

from typing import Dict, Any, Tuple, List, Optional

import numpy as np
from scipy.signal import butter, filtfilt, hilbert
from scipy.signal.windows import tukey


def _apply_edge_taper(signal: np.ndarray, alpha: float = 0.1) -> np.ndarray:
    """对信号两端加 Tukey 余弦渐变窗（默认首尾各 5%）。

    FTacV 信号的首尾存在启停瞬态与非周期斜坡，矩形 FFT 选带后做 IFFT
    会在窗口两端产生 Gibbs 振铃，淹没高次谐波的真实包络。
    加窗压制两端不连续性，中部信号不受影响。
    """
    n = len(signal)
    if n < 16:
        return signal
    w = tukey(n, alpha=alpha)
    return signal * w


def _design_lowpass_sos(fc: float, fs: float, order: int = 6) -> np.ndarray:
    """设计低通滤波器（SOS 形式）。"""
    nyq = fs / 2.0
    wn = min(fc / nyq, 0.999)
    return butter(order, wn, btype='low', output='sos')


def _design_bandpass_sos(low: float, high: float, fs: float, order: int = 4) -> Optional[np.ndarray]:
    """设计带通滤波器（SOS 形式）。"""
    nyq = fs / 2.0
    epsf = max(1e-9, 1e-6 * fs)
    low = max(epsf, low)
    high = min(nyq - epsf, high)
    if high <= low:
        return None
    wn = [low / nyq, high / nyq]
    return butter(order, wn, btype='band', output='sos')


def initialize_filters(params: Dict[str, Any]) -> Dict[str, Any]:
    """初始化 DC 低通与 1-7 次谐波带通滤波器。"""
    params = dict(params)
    dt = params['total_time'] / (params['n_points'] - 1)
    fs = 1.0 / dt

    # DC 低通滤波器
    fc = params['band'][0] / 2.0
    params['lp_filter_sos'] = _design_lowpass_sos(fc, fs, order=6)
    params['lp_filter_fs'] = fs
    params['lp_filter_fpass'] = fc

    # 1-7 次谐波带通滤波器
    bp_filters = []
    bp_edges = []
    for i in range(7):
        H = i + 1
        bw = params['band'][H]
        lower = H * params['f'] - bw / 2.0
        upper = H * params['f'] + bw / 2.0
        sos = _design_bandpass_sos(lower, upper, fs, order=4)
        bp_filters.append(sos)
        bp_edges.append((lower, upper))

    params['bp_filters'] = bp_filters
    params['bp_filter_edges'] = bp_edges
    params['bp_filter_fs'] = fs
    return params


def compute_tdc(t: np.ndarray, params: Dict[str, Any]) -> np.ndarray:
    """计算直流电位扫描轴。"""
    return params['E_start'] + t * params['v']


def safe_df(t: np.ndarray) -> float:
    """从时间数组估算采样频率。"""
    t = np.asarray(t)
    if t.size > 1:
        return 1.0 / float(np.mean(np.diff(t)))
    return 1.0


def _clean_current(current: np.ndarray) -> np.ndarray:
    """清洗电流信号：转实数、处理非有限值。"""
    current = np.asarray(current, dtype=float)
    if not np.isrealobj(current):
        current = np.real(current)
    if not np.all(np.isfinite(current)):
        if not np.any(np.isfinite(current)):
            current = np.zeros_like(current)
        else:
            # 线性插值填充 NaN，边界用最近值
            finite_idx = np.isfinite(current)
            x = np.arange(len(current))
            current = np.interp(x, x[finite_idx], current[finite_idx],
                                left=current[finite_idx][0], right=current[finite_idx][-1])
            current[~np.isfinite(current)] = 0.0
    return current


def extract_dc_fft(signal: np.ndarray, df: float, params: Dict[str, Any]) -> np.ndarray:
    """通过 FFT 提取 DC 分量。"""
    signal = _apply_edge_taper(_clean_current(signal))
    L = len(signal)
    Y = np.fft.fft(signal)
    f_axis = df * np.arange(L) / L
    bw_half = params['band'][0] / 2.0

    mask = (f_axis <= bw_half) | (f_axis >= (df - bw_half))
    Y_filtered = np.zeros_like(Y)
    Y_filtered[mask] = Y[mask]
    return np.abs(np.fft.ifft(Y_filtered))


def extract_harmonics(signal: np.ndarray, df: float, params: Dict[str, Any]) -> np.ndarray:
    """提取 1-7 次谐波包络。band 带宽自动适配 FFT 频率分辨率。"""
    signal = _apply_edge_taper(_clean_current(signal))
    L = len(signal)
    f0 = params['f']

    # 自动计算最小带宽：至少覆盖 3 个 FFT bin
    df_res = df / L
    min_bw = max(0.5 * f0, df_res * 5)  # 至少 0.5*f 或 5 bins

    if params.get('use_fft', True):
        Y = np.fft.fft(signal)
        f_axis = df * np.arange(L) / L
        harmonics = np.zeros((L, 7))
        half_L = L // 2 + 1

        for k in range(7):
            H = k + 1
            center_freq = H * f0
            # 自适应带宽
            bw = _auto_band(params, H, f0, min_bw)

            lb = center_freq - bw / 2.0
            ub = center_freq + bw / 2.0
            idx_pos = (f_axis >= lb) & (f_axis <= ub)
            idx_pos[0] = False
            pos_mask = idx_pos & (np.arange(L) > 0) & (np.arange(L) < half_L)

            mask_analytic = np.zeros(L)
            mask_analytic[pos_mask] = 2.0
            harmonics[:, k] = np.abs(np.fft.ifft(Y * mask_analytic))
    else:
        harmonics = np.zeros((L, 7))
        for i in range(7):
            H = i + 1
            bw = _auto_band(params, H, f0, min_bw)
            lower = H * f0 - bw / 2.0
            upper = H * f0 + bw / 2.0
            epsf = max(1e-9, 1e-6 * df)
            lower = max(epsf, lower)
            upper = min(df / 2.0 - epsf, upper)
            if upper <= lower:
                YHarC = np.zeros(L)
            else:
                bp_filters = params.get('bp_filters', None)
                if bp_filters is not None and i < len(bp_filters) and bp_filters[i] is not None:
                    YHarC = filtfilt(bp_filters[i], signal)
                else:
                    sos = _design_bandpass_sos(lower, upper, df, order=4)
                    if sos is not None:
                        YHarC = filtfilt(sos, signal)
                    else:
                        YHarC = np.zeros(L)
            harmonics[:, i] = np.abs(hilbert(YHarC))

    return harmonics


def _auto_band(params: dict, H: int, f0: float, min_bw: float) -> float:
    """自适应带宽：取用户设置的 band[H] 和自动计算的最小值中较大者。"""
    band = params.get('band', None)
    if band is not None and H < len(band):
        user_bw = float(band[H])
        return max(user_bw, min_bw)
    return min_bw


def process_current(current: np.ndarray, df: float, params: Dict[str, Any]) -> np.ndarray:
    """处理电流：提取 DC 分量与 1-7 次谐波。"""
    current = _clean_current(current)

    if params.get('use_fft', True):
        I_dc = extract_dc_fft(current, df, params)
    else:
        sos = params.get('lp_filter_sos', None)
        if sos is not None:
            ydc = filtfilt(sos, current)
        else:
            fc = params['band'][0] / 2.0
            sos = _design_lowpass_sos(fc, df, order=6)
            ydc = filtfilt(sos, current)
        I_dc = np.abs(ydc)

    I_harm = extract_harmonics(current, df, params)
    return np.column_stack([I_dc, I_harm])


def process_experimental(exp_data: Optional[Dict[str, Any]], params: Dict[str, Any]) -> Tuple[np.ndarray, np.ndarray]:
    """处理实验数据。"""
    if exp_data is None or len(exp_data) == 0:
        return np.array([]), np.array([])

    if 'I_processed' in exp_data and 'tdc' in exp_data:
        return np.asarray(exp_data['tdc']).reshape(-1), np.asarray(exp_data['I_processed'])

    current = np.asarray(exp_data['current']).reshape(-1)
    df = exp_data.get('df', safe_df(np.asarray(exp_data['time']).reshape(-1)))

    if 'tdc' in exp_data:
        tdc_exp = np.asarray(exp_data['tdc']).reshape(-1)
    else:
        tdc_exp = compute_tdc(np.asarray(exp_data['time']).reshape(-1), params)

    I_exp = process_current(current, df, params)
    return tdc_exp, I_exp


def process_data(t: np.ndarray, y: np.ndarray, i_total: np.ndarray,
                 params: Dict[str, Any], exp_data: Optional[Dict[str, Any]]) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """主数据处理入口。"""
    t = np.asarray(t).reshape(-1)
    i_total = np.asarray(i_total).reshape(-1)

    tdc = compute_tdc(t, params)
    df_sim = safe_df(t)
    I_sim = process_current(i_total, df_sim, params)

    tdc_exp, I_exp = process_experimental(exp_data, params)
    return tdc, I_sim, tdc_exp, I_exp


def align_data(tdc: np.ndarray, I_sim: np.ndarray, tdc_exp: np.ndarray) -> np.ndarray:
    """将仿真数据对齐到实验电位网格。"""
    tdc = np.asarray(tdc).reshape(-1)
    tdc_exp = np.asarray(tdc_exp).reshape(-1)
    I_sim = np.atleast_2d(np.asarray(I_sim))

    if len(tdc) == len(tdc_exp):
        return I_sim

    # 去除重复电位并排序
    x_unique, keep_idx = np.unique(tdc, return_index=True)
    y_keep = I_sim[keep_idx, :]
    sort_idx = np.argsort(x_unique)
    x_sorted = x_unique[sort_idx]
    y_sorted = y_keep[sort_idx, :]

    I_sim_aligned = np.full((len(tdc_exp), I_sim.shape[1]), np.nan)
    for i in range(I_sim.shape[1]):
        yi = y_sorted[:, i]
        if len(x_sorted) > 1:
            I_sim_aligned[:, i] = np.interp(tdc_exp, x_sorted, yi)
        else:
            I_sim_aligned[:, i] = yi[0]
    return I_sim_aligned


class OERSignal:
    """FTacV 信号处理入口类（对应 MATLAB OER_Signal）。"""

    @staticmethod
    def initialize_filters(params: Dict[str, Any]) -> Dict[str, Any]:
        return initialize_filters(params)

    @staticmethod
    def process_data(t, y, i_total, params, exp_data):
        return process_data(t, y, i_total, params, exp_data)

    @staticmethod
    def extract_dc_fft(signal, df, params):
        return extract_dc_fft(signal, df, params)

    @staticmethod
    def extract_harmonics(signal, df, params):
        return extract_harmonics(signal, df, params)

    @staticmethod
    def align_data(tdc, I_sim, tdc_exp):
        return align_data(tdc, I_sim, tdc_exp)

    @staticmethod
    def compute_tdc(t, params):
        return compute_tdc(t, params)

    @staticmethod
    def safe_df(t):
        return safe_df(t)

    @staticmethod
    def process_current(current, df, params):
        return process_current(current, df, params)

    @staticmethod
    def process_experimental(exp_data, params):
        return process_experimental(exp_data, params)
