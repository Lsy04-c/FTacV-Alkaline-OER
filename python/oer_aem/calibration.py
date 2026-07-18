"""FTacV 实验数据独立标定：从原始数据直接测量电路与位点参数。

可识别性说明（设计约束，勿绕过）
---------------------------------
模型中 Cdl、gamma、A 只以乘积形式出现：
  - 电容电流  i_cap = (Cdl*A) * dphi_s/dt
  - 法拉第电流 i_F  ∝ (gamma*A) * 单位位点速率
因此单组 FTacV 数据可严格直接测量的只有：
  CdlA    = Cdl * A   [F]       —— 非法拉第区交流（1f）响应
  Tafel 斜率 b        [V/dec]   —— OER 起始区的表观动力学约束
给定电极几何面积 A（用户输入）后可反解 Cdl = CdlA/A。

不可直接测量（本模块明确拒绝报数，留给模型反演）：
  GammaA = gamma * A  [mol] 与 E0_pre [V]
  —— 预氧化电荷耦合在催化覆盖度网络中，不表现为独立 Nernstian 峰；
     「解析峰 + 指数背景」直流拟合在本机理下是结构性错误模型，
     合成验证中即使峰可见，GammaA 误差仍达 ~1500%。
     assess_preox_separability 只回答"能否分离"的定性问题。
  Ru —— 在 FTacV 典型频率（~1 Hz）下对谱形影响可忽略，
     应来自 EIS 高频截距或用户先验。
"""

from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Tuple

import numpy as np

F_CONST = 96485.33212  # C/mol
R_CONST = 8.314462618  # J/(mol·K)


# ---------------------------------------------------------------- 扫描参数识别

def identify_scan_params(t: np.ndarray, E: np.ndarray) -> Dict[str, float]:
    """从 (t, E) 识别 v（斜坡速率）、dE（交流振幅）、f（主频）、E_dc 序列。"""
    t = np.asarray(t, dtype=float)
    E = np.asarray(E, dtype=float)
    t = t - t[0]
    slope, intercept = np.polyfit(t, E, 1)
    E_dc = intercept + slope * t
    E_ac = E - E_dc
    dt = float(np.mean(np.diff(t)))
    dE = float(np.std(E_ac) * np.sqrt(2.0))
    Y = np.abs(np.fft.rfft(E_ac))
    freqs = np.fft.rfftfreq(len(t), dt)
    k = int(np.argmax(Y[1:]) + 1) if len(Y) > 1 else 1
    return {
        'v': float(slope), 'dE': dE, 'f': float(freqs[k]),
        'E_start': float(intercept), 'E_end': float(intercept + slope * t[-1]),
        'duration': float(t[-1]), 'fs': 1.0 / dt,
    }


# ---------------------------------------------------------------- Cdl·A 测量

def measure_cdl_a(
    t: np.ndarray, E: np.ndarray, i: np.ndarray,
    f: float, dE: float, v: float,
    window: Tuple[float, float] = (1.0, 1.2),
) -> Dict[str, Any]:
    """非法拉第窗口内测量双电层电容乘积 CdlA [F]。

    方法 A（交流，首选）：1f 复振幅 |I_1f| = CdlA * omega * dE
    方法 B（直流，交叉验证）：窗口内平均充电电流 <i> = CdlA * v
    两者在纯非法拉第区应一致；差异大说明窗口内有法拉第泄漏。
    """
    t = np.asarray(t, dtype=float)
    E = np.asarray(E, dtype=float)
    i = np.asarray(i, dtype=float)
    lo, hi = window
    seg = (E >= lo) & (E <= hi)
    if seg.sum() < 64:
        return {'success': False, 'error': f'窗口 {window} 内数据点不足 ({seg.sum()})'}

    ts, Es, is_ = t[seg], E[seg], i[seg]
    omega = 2.0 * np.pi * f

    # 方法 A：对该段做复数最小二乘投影到 sin/cos(omega t)，取模（对段长稳健）
    s = np.sin(omega * ts)
    c = np.cos(omega * ts)
    A_mat = np.column_stack([s, c, np.ones_like(ts), ts])
    coef, *_ = np.linalg.lstsq(A_mat, is_, rcond=None)
    I1_amp = float(np.hypot(coef[0], coef[1]))
    cdl_a_ac = I1_amp / (omega * dE)
    # 相位诊断：纯电容电流相对 E_ac（同基投影）应超前 90°
    E_ac_seg = Es - np.polyval(np.polyfit(ts, Es, 1), ts)
    cs = np.column_stack([s, c])
    ce, *_ = np.linalg.lstsq(cs, E_ac_seg, rcond=None)
    phase_i = float(np.arctan2(coef[1], coef[0]))
    phase_e = float(np.arctan2(ce[1], ce[0]))
    phase_lead = float(np.degrees((phase_i - phase_e + np.pi) % (2 * np.pi) - np.pi))

    # 方法 B：平均电流 / 扫描速率
    cdl_a_dc = float(np.mean(is_)) / v

    # 一致性：两种方法相对差
    denom = max(abs(cdl_a_ac), 1e-15)
    rel_diff = abs(cdl_a_ac - cdl_a_dc) / denom

    return {
        'success': True,
        'CdlA': cdl_a_ac,
        'CdlA_ac': cdl_a_ac,
        'CdlA_dc': cdl_a_dc,
        'rel_diff': float(rel_diff),
        'phase_lead_deg': phase_lead,
        'window': [lo, hi],
        'n_points': int(seg.sum()),
        'note': '相位超前应接近 90°（纯电容）；AC 与 DC 法差异 >50% 表明窗口存在法拉第泄漏',
    }


# ---------------------------------------------------------------- 预氧化峰可分离性（纯诊断）

def assess_preox_separability(
    E: np.ndarray, i_dc: np.ndarray,
    window: Tuple[float, float] = (1.25, 1.75),
) -> Dict[str, Any]:
    """评估预氧化峰能否从直流与 OER 起始分离（纯诊断，不报 GammaA 数值）。

    历史教训（合成数据验证）：本模型的预氧化电荷耦合在催化覆盖度网络中，
    并不表现为独立的 Nernstian 峰。用「可逆峰 + 指数背景」解析模型做直流
    拟合，即使峰"可见"，GammaA 误差也可达 ~1500%（合成 Γ=5e-8 验证）。
    因此此处只回答"能不能分离"这一定性问题，定量测量一律留给模型反演。

    判据：平滑 dI/dE 在窗口内存在 prominence > 5σ_noise 且不在上沿 15% 内
    的局部峰 → separable=True。
    """
    E = np.asarray(E, dtype=float)
    i_dc = np.asarray(i_dc, dtype=float)
    lo, hi = window
    seg = (E >= lo) & (E <= hi)
    if seg.sum() < 200:
        return {'separable': False, 'reason': f'窗口 {window} 内数据点不足 ({seg.sum()})'}

    from scipy.signal import find_peaks, savgol_filter
    # 实验电位存在重复采样点，先按 E 去重（均值聚合），避免梯度除零
    Eu, inv, cnt = np.unique(E[seg], return_inverse=True, return_counts=True)
    iu = np.bincount(inv, weights=i_dc[seg]) / cnt
    n_s = min(151, len(Eu) // 5 * 2 + 1)  # 奇数窗口
    i_sm = savgol_filter(iu, n_s, 3) if n_s >= 7 else iu
    di = np.gradient(i_sm, Eu)
    # 噪声尺度：窗口前 1/4（OER 未起）的导数标准差
    noise = float(np.std(di[: max(8, len(di) // 4)])) or 1e-12
    pk, props = find_peaks(di, prominence=5.0 * noise)
    # 独立峰要求：峰不在窗口最上沿 15% 内（否则就是 OER 上升沿本身）
    e_cut = lo + 0.85 * (hi - lo)
    independent = [k for k in pk if Eu[k] < e_cut]
    if independent:
        return {
            'separable': True,
            'peak_positions': [float(Eu[k]) for k in independent],
            'reason': 'dI/dE 存在独立鼓包；但 GammaA 定量仍须模型反演'
                      '（直流解析峰模型在本机理下结构性错误，见模块 docstring）',
        }
    return {
        'separable': False,
        'reason': '预氧化峰与 OER 起始重叠，dI/dE 无独立鼓包，直流不可分离；'
                  'GammaA 与 E0_pre 须通过模型反演获得（固定 CdlA 后约束已收紧）',
    }


# ---------------------------------------------------------------- Tafel 斜率

def measure_tafel(
    E: np.ndarray, i_dc: np.ndarray,
    i_lo: float = 3e-5, i_hi: float = 3e-4,
    window: Tuple[float, float] = (1.35, 1.9),
) -> Dict[str, Any]:
    """表观 Tafel 斜率：在 DC 包络上取电流从 i_lo 到 i_hi（一个数量级）
    所跨越的电位差。b = ΔE / log10(i_hi/i_lo) [V/decade]。

    用包络插值过电流阈值，对噪声与非塔菲尔区形状稳健；
    固定窗口最小二乘在起始区曲率大时 R² 崩塌，故不采用。
    """
    E = np.asarray(E, dtype=float)
    i_dc = np.asarray(i_dc, dtype=float)
    lo, hi = window
    seg = (E >= lo) & (E <= hi)
    if seg.sum() < 100:
        return {'success': False, 'error': f'窗口 {window} 内数据点不足'}
    # 去重 + 按 E 排序的包络
    Eu, inv, cnt = np.unique(E[seg], return_inverse=True, return_counts=True)
    iu = np.bincount(inv, weights=i_dc[seg]) / cnt
    # 中值平滑抗噪
    from scipy.signal import medfilt
    k = min(51, len(iu) // 10 * 2 + 1)
    i_sm = medfilt(iu, k) if k >= 5 else iu
    pos = i_sm > 0
    if pos.sum() < 20:
        return {'success': False, 'error': '窗口内正电流点不足'}

    def crossing(level):
        idx = np.where((i_sm[:-1] < level) & (i_sm[1:] >= level))[0]
        if len(idx) == 0:
            return None
        j = idx[0]
        w = (level - i_sm[j]) / (i_sm[j + 1] - i_sm[j])
        return float(Eu[j] + w * (Eu[j + 1] - Eu[j]))

    e_lo = crossing(i_lo)
    e_hi = crossing(i_hi)
    if e_lo is None or e_hi is None:
        return {'success': False,
                'error': f'电流阈值 {i_lo:.0e}/{i_hi:.0e} A 未在窗口内跨越'}
    b = (e_hi - e_lo) / np.log10(i_hi / i_lo)
    return {
        'success': True,
        'tafel_slope': float(b),
        'tafel_slope_mV': float(b * 1e3),
        'E_at_i_lo': e_lo, 'E_at_i_hi': e_hi,
        'i_lo': i_lo, 'i_hi': i_hi,
    }


# ---------------------------------------------------------------- 汇总入口

def calibrate(
    E: np.ndarray, i: np.ndarray, t: np.ndarray,
    T: float = 298.15,
    cdl_window: Tuple[float, float] = (1.0, 1.2),
    preox_window: Tuple[float, float] = (1.25, 1.75),
    tafel_window: Tuple[float, float] = (1.35, 1.9),
    i_dc: Optional[np.ndarray] = None,
) -> Dict[str, Any]:
    """对单组 FTacV 数据执行全部可独立测量的标定。

    i_dc：可选的已提取直流分量；未提供时用滑动中位数粗略包络。
    返回结构：{scan, cdl, tafel, preox, identifiability}
    """
    E = np.asarray(E, dtype=float)
    i = np.asarray(i, dtype=float)
    t = np.asarray(t, dtype=float)
    order = np.argsort(t)
    t, E, i = t[order], E[order], i[order]
    t = t - t[0]

    scan = identify_scan_params(t, E)

    if i_dc is None:
        # 粗略直流包络：按电位分箱取中位数再插值回去（抗 AC 与量化噪声）
        nbin = 400
        edges = np.linspace(E.min(), E.max(), nbin + 1)
        centers = 0.5 * (edges[:-1] + edges[1:])
        idx = np.clip(np.digitize(E, edges) - 1, 0, nbin - 1)
        med = np.array([np.median(i[idx == b]) if np.any(idx == b) else np.nan
                        for b in range(nbin)])
        good = np.isfinite(med)
        i_dc = np.interp(E, centers[good], med[good])
    else:
        i_dc = np.asarray(i_dc, dtype=float)[order] if i_dc is not None else None

    cdl = measure_cdl_a(t, E, i, scan['f'], scan['dE'], scan['v'], window=cdl_window)
    tafel = measure_tafel(E, i_dc, window=tafel_window)
    preox = assess_preox_separability(E, i_dc, window=preox_window)

    return {
        'scan': scan,
        'cdl': cdl,
        'tafel': tafel,
        'preox': preox,
        'identifiability': {
            'measured': ['CdlA [F]', 'Tafel 斜率 [V/dec]'],
            'not_measurable': ['GammaA 与 E0_pre（直流解析峰模型结构性错误，须模型反演）',
                               'Ru（FTacV 频率下不可识别，需 EIS 或先验）'],
            'note': 'Cdl、gamma、A 仅以乘积出现；给定 A 后 Cdl=CdlA/A。',
        },
    }


def derive_per_area(calib: Dict[str, Any], A: float) -> Dict[str, float]:
    """给定电极面积 A [cm²]，把乘积反解为模型参用的面密度量。"""
    out = {}
    cdl = calib.get('cdl', {})
    if cdl.get('success'):
        out['Cdl'] = cdl['CdlA'] / A
    return out
