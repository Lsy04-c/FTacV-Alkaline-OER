"""低维（Bonke 分子催化）模型的数据接入、目标函数与拟合驱动。

目标函数选择依据 Gundry et al. (2021) ChemElectroChem 8, 2238-2258：

* ``HarmPer``——逐谐波归一化的包络相对误差，用于确定性优化（CMA-ES）；
* ``MLE-ExpHarmPer``——逐谐波独立噪声的对数似然，用于贝叶斯推断。
  每个谐波的噪声标准差以 Jeffreys 先验解析积分掉，得到
  ``logL = -sum_h (N_h/2) * log(SSR_h)``。

刻意不纳入目标函数的两项，理由记录在计划文档中：

* **DC 分量**——实验 DC 含未扣除的基底背景电流，而 FTacV 的谐波本身
  就是用来排除背景的；纳入 DC 会让优化器用机理参数吸收背景。
* **H1**——被双电层电流和上升的催化电流主导。

标度简并：法拉第电流正比于 ``gamma * A``。``A`` 钉住时反演出的 ``gamma``
实为 ``gamma * A / A_assumed``，不可单独解释为真实位点密度。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Sequence, Tuple

import numpy as np

from .molecular_catalysis import simulate
from .signal import extract_harmonics

FIT_HARMONICS: Tuple[int, ...] = (2, 3, 4)
EDGE_GUARD_FRACTION = 0.08

# 似然中每个交流周期保留的包络点数。
#
# 谐波包络是慢变量：实测 FT8 的 H2/H3/H4 有 99% 能量落在 f < 0.09*f0 以内，
# 而实验采样为 256 点/周期，冗余约 128 倍。把这些高度相关的点当独立样本会
# 让 logL = -sum (N/2) log(SSR) 的指数虚增约两个数量级，后果是链几乎不动
# （R-hat 曾达 1e13）且后验被压窄约 14 倍。详见 docs/项目纠错.md §25。
#
# 按 Nyquist，包络带宽 ~0.09*f0 时每周期 2 点即足够；取 4 点留一倍余量。
# 这是**去冗余，不是丢信息**。优化用的 HarmPer 不受影响。
LIKELIHOOD_POINTS_PER_CYCLE = 4


@dataclass(frozen=True)
class ExperimentRecord:
    """一段已截断、频率与扫速均由数据实测的 FTacV 记录。"""

    name: str
    t: np.ndarray
    E: np.ndarray
    I: np.ndarray
    fs: float
    f0: float
    dE: float
    v: float
    E_start: float
    E_end: float

    @property
    def total_time(self) -> float:
        return float(self.t[-1] - self.t[0])


def load_ftacv_columns(path) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """读取三列（E, I, t）FTacV 文本，跳过非数值表头。"""
    rows = []
    with open(path, "r", errors="ignore") as handle:
        for line in handle:
            parts = line.replace(",", " ").split()
            if len(parts) < 3:
                continue
            try:
                rows.append([float(parts[0]), float(parts[1]), float(parts[2])])
            except ValueError:
                continue
    if not rows:
        raise ValueError(f"{path} 中未找到三列数值数据")
    data = np.asarray(rows, dtype=float)
    return data[:, 0], data[:, 1], data[:, 2]


def detect_fundamental(E: np.ndarray, t: np.ndarray, f_min: float = 0.3) -> float:
    """从实测电位的去趋势谱中估计交流基频。

    直接对 ``E`` 取谱会被直流斜坡主导，因此先扣除 5 阶多项式趋势，
    并忽略 ``f_min`` 以下的分量。
    """
    fs = 1.0 / float(np.median(np.diff(t)))
    detrended = E - np.polyval(np.polyfit(t, E, 5), t)
    spectrum = np.abs(np.fft.rfft(detrended))
    freqs = np.fft.rfftfreq(E.size, d=1.0 / fs)
    spectrum[freqs < f_min] = 0.0
    return float(freqs[int(np.argmax(spectrum))])


def dc_potential(E: np.ndarray, points_per_cycle: int) -> np.ndarray:
    """以一个交流周期的滑动平均得到直流电位分量。"""
    kernel = np.ones(points_per_cycle) / points_per_cycle
    return np.convolve(E, kernel, mode="same")


def load_truncated(path, name: str, e_lo: float, e_hi: float) -> ExperimentRecord:
    """载入并截断到 ``[e_lo, e_hi]`` 直流电位区间。

    截断理由（见计划文档）：该区间覆盖高次谐波中可复现的表面氧化还原
    特征，同时排除高电流区——那里 ``i*Ru`` 压降与交流幅值同量级，
    且气泡、OH- 传质、基底背景均未建模。
    """
    E, I, t = load_ftacv_columns(path)
    fs = 1.0 / float(np.median(np.diff(t)))
    f0 = detect_fundamental(E, t)
    points_per_cycle = int(round(fs / f0))

    e_dc = dc_potential(E, points_per_cycle)
    inside = np.where((e_dc >= e_lo) & (e_dc <= e_hi))[0]
    if inside.size < 8 * points_per_cycle:
        raise ValueError(f"{name} 在 [{e_lo}, {e_hi}] V 内的数据不足")

    # 对齐到整数个交流周期，避免 FFT 泄漏
    n_cycles = inside.size // points_per_cycle
    lo = int(inside[0])
    hi = lo + n_cycles * points_per_cycle
    sl = slice(lo, hi)

    t_seg = t[sl] - t[lo]
    e_seg, i_seg = E[sl], I[sl]

    detrended = e_seg - np.polyval(np.polyfit(t_seg, e_seg, 5), t_seg)
    dE = float(np.max(np.abs(np.fft.rfft(detrended))) / e_seg.size * 2.0)
    e_dc_seg = dc_potential(e_seg, points_per_cycle)
    guard = points_per_cycle
    v = float(np.polyfit(t_seg[guard:-guard], e_dc_seg[guard:-guard], 1)[0])
    e_start = float(e_dc_seg[guard])

    return ExperimentRecord(
        name=name,
        t=t_seg,
        E=e_seg,
        I=i_seg,
        fs=fs,
        f0=f0,
        dE=dE,
        v=v,
        E_start=e_start - v * t_seg[guard],
        E_end=float(e_dc_seg[-guard]),
    )


def harmonic_envelopes(
    current: np.ndarray,
    fs: float,
    f0: float,
    harmonics: Sequence[int] = FIT_HARMONICS,
) -> np.ndarray:
    """返回指定谐波的包络，形状 ``(len(harmonics), n_points)``。

    直接复用 `signal.extract_harmonics`，使实验与模拟走完全相同的
    提取路径（带宽、边缘窗、解析信号），这是 WORK_STATUS §12 残差
    契约的要求。
    """
    params = {"f": f0, "band": np.zeros(8), "use_fft": True}
    table = extract_harmonics(np.asarray(current, dtype=float), fs, params)
    return np.stack([table[:, h - 1] for h in harmonics])


def _guard_slice(n: int) -> slice:
    """去掉两端受 Tukey 边缘窗影响的点。"""
    guard = int(EDGE_GUARD_FRACTION * n)
    return slice(guard, n - guard)


def harm_per(simulated: np.ndarray, experimental: np.ndarray) -> float:
    """Gundry HarmPer：逐谐波归一化的包络相对 RMS 误差的平均。"""
    sl = _guard_slice(experimental.shape[1])
    total = 0.0
    for sim_row, exp_row in zip(simulated[:, sl], experimental[:, sl]):
        denominator = float(np.sqrt(np.sum(exp_row ** 2)))
        if denominator <= 0.0:
            return np.inf
        total += float(np.sqrt(np.sum((sim_row - exp_row) ** 2))) / denominator
    return total / experimental.shape[0]


def likelihood_stride(fs: float, f0: float,
                      points_per_cycle: int = LIKELIHOOD_POINTS_PER_CYCLE) -> int:
    """返回似然抽稀步长，使每个交流周期保留约 ``points_per_cycle`` 个点。"""
    if fs <= 0 or f0 <= 0:
        raise ValueError("fs 与 f0 必须为正")
    return max(1, int(round(fs / f0 / max(points_per_cycle, 1))))


def mle_exp_harm_per(simulated: np.ndarray, experimental: np.ndarray,
                     stride: int = 1) -> float:
    """MLE-ExpHarmPer 对数似然（逐谐波噪声以 Jeffreys 先验解析积分掉）。

    ``stride`` 对包络抽稀后再计算，理由见 ``LIKELIHOOD_POINTS_PER_CYCLE``：
    相邻包络点高度相关，直接当独立样本会让似然过尖到无法采样，且后验过窄。
    """
    sl = _guard_slice(experimental.shape[1])
    step = max(int(stride), 1)
    log_likelihood = 0.0
    for sim_row, exp_row in zip(simulated[:, sl][:, ::step],
                                experimental[:, sl][:, ::step]):
        residual = sim_row - exp_row
        sum_squares = float(np.sum(residual ** 2))
        if not np.isfinite(sum_squares) or sum_squares <= 0.0:
            return -np.inf
        log_likelihood -= 0.5 * residual.size * np.log(sum_squares)
    return log_likelihood


def implied_sigma(simulated: np.ndarray, experimental: np.ndarray) -> np.ndarray:
    """返回各谐波被积分掉的噪声标准差的极大似然估计。"""
    sl = _guard_slice(experimental.shape[1])
    out = []
    for sim_row, exp_row in zip(simulated[:, sl], experimental[:, sl]):
        residual = sim_row - exp_row
        out.append(float(np.sqrt(np.mean(residual ** 2))))
    return np.asarray(out)


PARAM_NAMES: Tuple[str, ...] = ("E0_eff", "log10_k0", "log10_kf", "log10_gamma")


# WORK_STATUS §4.2：边界不能只为了拟合而放宽，必须分来源标注。
# 标签集沿用该节定义：fixed / measured / literature / weak_prior / engineering
# 上下界分别标注——`gamma` 正是一个下界来自文献、上界属工程放宽的例子。
BOUND_PROVENANCE: Dict[str, Dict[str, str]] = {
    "E0_eff": {
        "lower_source": "measured",
        "upper_source": "measured",
        "note": "本项目四组数据 H3/H4 包络实测特征 1.52-1.63 V，"
                "两侧各留出 EC' 催化步引起的正移余量",
    },
    "k0": {
        "lower_source": "literature",
        "upper_source": "literature",
        "note": "覆盖 Snitkoff-Sol 2022 的 6 s^-1 与 Bonke 2016 的 110-325 s^-1",
    },
    "kf": {
        "lower_source": "literature",
        "upper_source": "literature",
        "note": "覆盖 Bonke 2016 的 kf1 = 2e3-4e4 s^-1",
    },
    "gamma": {
        "lower_source": "literature",
        "upper_source": "engineering",
        "note": "下界取 Bonke 2016 的 pmol/cm^2 量级；上界放宽到本项目此前"
                "假设的 1e-8，属工程边界，无独立标定支持",
    },
}


def default_bounds() -> Tuple[np.ndarray, np.ndarray]:
    """自由参数边界。

    来源：``E0_eff`` 覆盖本项目数据中 H3/H4 实测特征（1.52-1.63 V）并留出
    EC' 正移余量；``k0`` 覆盖 Snitkoff-Sol 2022 的 6 s^-1 与 Bonke 2016 的
    110-325 s^-1；``kf`` 覆盖 Bonke 的 2e3-4e4 s^-1；``gamma`` 下界取
    Bonke 的 pmol/cm^2 量级，上界放宽到本项目此前假设的 1e-8。
    """
    lower = np.array([1.35, -1.0, 0.0, -12.0])
    upper = np.array([1.80, 4.0, 6.0, -8.0])
    return lower, upper


def decode(unit: np.ndarray, lower: np.ndarray, upper: np.ndarray) -> Dict[str, float]:
    """把 ``[0,1]`` 空间的向量解码为模型参数。"""
    values = lower + np.asarray(unit, dtype=float) * (upper - lower)
    return {
        "E0_eff": float(values[0]),
        "k0": float(10.0 ** values[1]),
        "kf": float(10.0 ** values[2]),
        "gamma": float(10.0 ** values[3]),
    }


class LowDimObjective:
    """把归一化参数向量映射到 HarmPer 损失与 MLE-ExpHarmPer 对数似然。"""

    def __init__(self, record: ExperimentRecord, pinned: Dict[str, float],
                 harmonics: Sequence[int] = FIT_HARMONICS):
        self.record = record
        self.pinned = dict(pinned)
        self.harmonics = tuple(harmonics)
        self.lower, self.upper = default_bounds()
        self.target = harmonic_envelopes(record.I, record.fs, record.f0, self.harmonics)
        self.stride = likelihood_stride(record.fs, record.f0)

    def _simulate_envelopes(self, unit: np.ndarray) -> np.ndarray | None:
        params = decode(unit, self.lower, self.upper)
        params.update(self.pinned)
        params.update(
            E_start=self.record.E_start,
            v=self.record.v,
            dE=self.record.dE,
            f=self.record.f0,
            total_time=self.record.total_time,
        )
        _, current, _ = simulate(params, self.record.t)
        if not np.all(np.isfinite(current)):
            return None
        return harmonic_envelopes(current, self.record.fs, self.record.f0, self.harmonics)

    def loss(self, unit: np.ndarray) -> float:
        envelopes = self._simulate_envelopes(unit)
        if envelopes is None:
            return 1e6
        return harm_per(envelopes, self.target)

    def log_posterior_unit(self, unit: np.ndarray) -> float:
        if np.any(np.asarray(unit) <= 0.0) or np.any(np.asarray(unit) >= 1.0):
            return -np.inf
        envelopes = self._simulate_envelopes(unit)
        if envelopes is None:
            return -np.inf
        return mle_exp_harm_per(envelopes, self.target, self.stride)
