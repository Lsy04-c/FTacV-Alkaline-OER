# -*- coding: utf-8 -*-
"""FTacV 微观动力学参数反演基准（stress test）：Optuna TPE vs 多起点 L-BFGS-B。

用法：
    python bench_inversion.py --quick   # 冒烟模式：每算法 50 次目标评估
    python bench_inversion.py           # 完整模式：每算法 200 次目标评估（TPE 200 trials；L-BFGS-B 3 起点 × maxfun=65 ≈ 195）

说明：
- 正演管线与目标生成完全一致（inverse crime，目的为压力测试优化器）。
- 自由参数按任务参数表为 8 维：log10(k0_1..k0_4)、G_OH、G_O、scaling_OOH_OH、log10(gamma)。
  （任务书标题写"9 个自由参数"，但参数表只列出 4+3+1=8 个；本脚本以参数表为准。）
- 目标函数：DC + 7 次谐波归一化包络残差（公共电位网格 200 点）+ Tafel 斜率残差，
  各通道除以各自 σ 后平方求和，再按通道数（9）取均值。
- 磁盘缓存：以编码参数向量 round 6 位为 key，缓存在 results/benchmarks/bench_artifacts/cache/ 下，
  命中不重复计 nfev（正演次数）。
- 6 个 job（3 场景 × 2 算法）用 ProcessPoolExecutor 并行；每 job 有内部时间预算，
  超时优雅退出并保留进度，不会拖垮整个基准。
"""

import argparse
import contextlib
import copy
import io
import json
import os
import sys
import time
import warnings
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import numpy as np

# 保证 spawn 子进程也能 import 本仓库包。
REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "code" / "python" / "src"))

from oer_aem import OERPhysics, OERSignal, initialize_oer_parameters, apply_alkaline_aem
from oer_aem.calibration import measure_tafel

# ============================ 全局配置 ============================

ARTIFACT_DIR = os.path.join(REPO_ROOT, 'results', 'benchmarks', 'bench_artifacts')
CACHE_DIR = os.path.join(ARTIFACT_DIR, 'cache')
PROGRESS_DIR = os.path.join(ARTIFACT_DIR, 'progress')
RESULTS_JSON = os.path.join(REPO_ROOT, 'results', 'benchmarks', 'bench_inversion_results.json')

PIPELINE_VERSION = 'v1-32cyc-8192pts-200grid'   # 管线变更时 bump，防止误用旧缓存

# 扫描配置（已验证事实）：8192 点 = 32 周期，f=1 Hz → 总时长 32 s，采样率 256 Hz
SCAN_CFG = {
    'E_start': 0.924, 'E_end': 1.923, 'f': 1.0, 'dE': 0.16,
    'n_points': 8192, 'points_per_cycle': 256,
}
TOTAL_TIME = (SCAN_CFG['n_points'] / SCAN_CFG['points_per_cycle']) / SCAN_CFG['f']  # 32.0 s
SCAN_RATE = (SCAN_CFG['E_end'] - SCAN_CFG['E_start']) / TOTAL_TIME                  # v
FS = SCAN_CFG['n_points'] / TOTAL_TIME                                              # 256.0 Hz
T_SPAN = np.linspace(0.0, TOTAL_TIME, SCAN_CFG['n_points'])
TDC = SCAN_CFG['E_start'] + T_SPAN * SCAN_RATE                                      # 电位轴

# 瞬态丢弃：前 1/4 段（32 周期丢 8 个）
I0 = SCAN_CFG['n_points'] // 4
TDC_TRIM = TDC[I0:]
# 公共电位网格：200 点，覆盖丢瞬态后的 tdc 范围
E_GRID = np.linspace(TDC_TRIM[0], TDC_TRIM[-1], 200)

# 通道噪声水平（权重 = 1/σ）
SIGMA_DC = 0.02
SIGMA_HARM = 0.05
SIGMA_TAFEL = 0.05       # V
N_CHANNELS = 9           # DC + H1..H7 + Tafel

ODE_PENALTY = 1e9        # ODE 失败时的罚值
TAFEL_FAIL_RESID = 10.0  # Tafel 测量失败时的残差（σ 单位），即罚 100

# 自由参数定义（编码空间）：(名称, 类型, 下界, 上界)
# 类型 'log10' 表示优化变量即 log10(物理值)，边界为 log10 空间
PARAM_SPECS = [
    ('k0_1', 'log10', -3.0, 5.0),
    ('k0_2', 'log10', -3.0, 5.0),
    ('k0_3', 'log10', -3.0, 5.0),
    ('k0_4', 'log10', -3.0, 5.0),
    ('G_OH', 'linear', 0.8, 1.8),
    ('G_O', 'linear', 2.2, 3.4),
    ('scaling_OOH_OH', 'linear', 2.8, 3.6),
    ('gamma', 'log10', -10.0, -7.0),
]
N_DIM = len(PARAM_SPECS)
LB = np.array([s[2] for s in PARAM_SPECS])
UB = np.array([s[3] for s in PARAM_SPECS])
BOUNDS = list(zip(LB, UB))

# 场景真值（物理单位）
TRUTH_PHYSICAL = {
    'A': {'k0_1': 3e3, 'k0_2': 8e2, 'k0_3': 30.0, 'k0_4': 2e3,
          'G_OH': 1.35, 'G_O': 2.65, 'scaling_OOH_OH': 3.10, 'gamma': 5e-9},
    'B': {'k0_1': 5e2, 'k0_2': 3e3, 'k0_3': 300.0, 'k0_4': 8e2,
          'G_OH': 1.15, 'G_O': 2.95, 'scaling_OOH_OH': 3.30, 'gamma': 2e-8},
}
# 场景定义：A=nominal(0.5% 噪声)，B=参数空间另一区域(0.5%)，C=高噪声(3%，用 A 真值)
SCENARIOS = {
    'A': {'truth': 'A', 'sigma_noise': 0.005, 'seed': 2024001, 'label': 'nominal（真值A + 0.5% 噪声）'},
    'B': {'truth': 'B', 'sigma_noise': 0.005, 'seed': 2024002, 'label': '参数空间另一区域（真值B + 0.5% 噪声）'},
    'C': {'truth': 'A', 'sigma_noise': 0.03, 'seed': 2024003, 'label': '高噪声（真值A + 3% 噪声）'},
}


def truth_x(scenario: str) -> np.ndarray:
    """场景真值的编码向量。"""
    phys = TRUTH_PHYSICAL[SCENARIOS[scenario]['truth']]
    x = []
    for name, kind, _, _ in PARAM_SPECS:
        v = phys[name]
        x.append(np.log10(v) if kind == 'log10' else v)
    return np.array(x, dtype=float)


class BudgetExhausted(Exception):
    """时间预算耗尽（用于 L-BFGS-B 内部优雅中断）。"""


# ============================ 参数装配与正演 ============================

_BASE_PARAMS = None  # 进程内模板（首次使用时构建）


def _build_base_params() -> dict:
    """构建参数模板：默认值 + 本基准的扫描配置（固定参数用默认值：Cdl/A/E0_pre/Ru）。"""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        p = initialize_oer_parameters()
    p.update(dict(SCAN_CFG))
    p['total_time'] = TOTAL_TIME
    p['v'] = SCAN_RATE
    p['t_span'] = T_SPAN.copy()
    p['omega'] = 2 * np.pi * SCAN_CFG['f']
    return p


def make_params(x: np.ndarray) -> dict:
    """由编码向量装配完整参数字典。

    注入顺序（以仓库代码为准）：
    1) 模板上更新自由参数（k0/gamma 为物理值，G 直接给 eV）；
    2) apply_alkaline_aem 由 G_OH/G_O/scaling 重新生成 E01-E04（热力学约束）；
    3) initialize_system 重算派生量（gammaF_Cdl 随 gamma 变化，RTF/invRC/omega 不变）。
    """
    global _BASE_PARAMS
    if _BASE_PARAMS is None:
        _BASE_PARAMS = _build_base_params()
    p = copy.deepcopy(_BASE_PARAMS)
    upd = {}
    for (name, kind, _, _), v in zip(PARAM_SPECS, x):
        upd[name] = float(10.0 ** v) if kind == 'log10' else float(v)
    p.update(upd)
    p = apply_alkaline_aem(p)
    p = OERPhysics.initialize_system(p)
    return p


def forward_current(x: np.ndarray):
    """正演：返回总电流数组（长度 n_points）；ODE 失败返回 None。"""
    p = make_params(x)
    with warnings.catch_warnings():
        warnings.simplefilter('ignore')  # ODE 失败警告太吵，失败由 NaN 检测计数
        _, _, _, i = OERPhysics.solve_ode_system(p)
    i = np.asarray(i).reshape(-1)
    if not np.all(np.isfinite(i)):
        return None
    return i


# ============================ 特征提取 ============================

def compute_features(i: np.ndarray) -> dict:
    """从电流信号提取目标函数特征（全部在丢瞬态后计算）。

    返回：dc/h1..h7 在公共电位网格上的归一化包络 + Tafel 斜率（失败为 None）。
    """
    sp = {'f': SCAN_CFG['f'], 'band': np.ones(8), 'use_fft': True}
    I_dc = np.asarray(OERSignal.extract_dc_fft(i, FS, sp)).reshape(-1)
    I_harm = np.asarray(OERSignal.extract_harmonics(i, FS, sp))  # (n, 7)

    dc = I_dc[I0:]
    harms = I_harm[I0:, :]
    tdc = TDC_TRIM

    # DC 与每个谐波各自归一化（除以各自最大值，下限 1e-30），再插值到公共网格
    dc_n = dc / max(float(np.max(dc)), 1e-30)
    feats = {'dc': np.interp(E_GRID, tdc, dc_n), 'harm': []}
    for k in range(7):
        h = harms[:, k]
        h_n = h / max(float(np.max(h)), 1e-30)
        feats['harm'].append(np.interp(E_GRID, tdc, h_n))

    # Tafel 斜率用未归一化 DC 包络（与标定模块语义一致）
    tf = measure_tafel(tdc, dc)
    feats['tafel'] = float(tf['tafel_slope']) if tf.get('success') else None
    return feats


def generate_target(scenario: str) -> dict:
    """生成场景目标：同一正演管线（inverse crime）+ 高斯噪声，然后提取特征。"""
    cfg = SCENARIOS[scenario]
    x_true = truth_x(scenario)
    i_clean = forward_current(x_true)
    if i_clean is None:
        raise RuntimeError(f'场景 {scenario} 真值正演失败（ODE 不收敛）')
    rng = np.random.default_rng(cfg['seed'])
    sigma = cfg['sigma_noise'] * float(np.max(np.abs(i_clean)))
    i_noisy = i_clean + rng.normal(0.0, sigma, size=i_clean.shape)
    feats = compute_features(i_noisy)
    if feats['tafel'] is None:
        raise RuntimeError(f'场景 {scenario} 目标 Tafel 测量失败')
    feats['max_abs_i'] = float(np.max(np.abs(i_clean)))
    return feats


# ============================ 目标函数（含磁盘缓存与计数） ============================

class EvalCache:
    """以编码向量 round 6 位为 key 的 JSON 磁盘缓存（原子写）。"""

    def __init__(self, scenario: str, algo: str):
        os.makedirs(CACHE_DIR, exist_ok=True)
        self.path = os.path.join(CACHE_DIR, f'{scenario}_{algo}.json')
        self.entries = {}
        if os.path.exists(self.path):
            try:
                with open(self.path, 'r', encoding='utf-8') as fh:
                    blob = json.load(fh)
                meta = blob.get('meta', {})
                if (meta.get('pipeline_version') == PIPELINE_VERSION
                        and meta.get('scenario') == scenario):
                    self.entries = blob.get('entries', {})
            except Exception:
                self.entries = {}  # 缓存损坏则弃用，不影响基准
        self._since_save = 0

    @staticmethod
    def key(x: np.ndarray) -> str:
        return ','.join(f'{float(v):.6f}' for v in x)

    def get(self, x: np.ndarray):
        return self.entries.get(self.key(x))

    def put(self, x: np.ndarray, val: float):
        self.entries[self.key(x)] = float(val)
        self._since_save += 1
        if self._since_save >= 10:
            self.save()

    def save(self):
        blob = {'meta': {'pipeline_version': PIPELINE_VERSION,
                         'scenario': os.path.basename(self.path).split('_')[0],
                         'saved_at': time.strftime('%Y-%m-%dT%H:%M:%S')},
                'entries': self.entries}
        tmp = self.path + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as fh:
            json.dump(blob, fh)
        os.replace(tmp, self.path)
        self._since_save = 0


class Objective:
    """带缓存、计数与时间预算的目标函数。

    计数口径：
      n_calls  — 目标函数有效评估总次数（含缓存命中），受 hard_cap 硬上限约束
      n_fwd    — 实际正演（仿真）次数 = nfev，缓存命中不计
      n_hit    — 缓存命中次数
      n_over_cap — 超出硬预算后被拒评估的次数（返回罚值，不计入 n_calls）
      n_ode_fail / n_tafel_fail — 失败模式统计

    hard_cap：scipy L-BFGS-B 的 maxfun 并非硬上限（Fortran 主循环外的一次
    梯度 + 线搜索可超额 10-40%），为保证与 TPE 的评估预算严格对齐，
    在目标函数层做硬截断：超过 cap 的调用不评估，直接返回大罚值
    （线搜索拒绝该点并收缩步长，L-BFGS-B 随即收敛/停止）。
    """

    OVER_CAP_PENALTY = 1e12

    def __init__(self, target: dict, cache: EvalCache, deadline: float,
                 raise_on_timeout: bool, hard_cap: int = None):
        self.target = target
        self.cache = cache
        self.deadline = deadline
        self.raise_on_timeout = raise_on_timeout
        self.hard_cap = hard_cap
        self.n_calls = 0
        self.n_fwd = 0
        self.n_hit = 0
        self.n_over_cap = 0
        self.n_ode_fail = 0
        self.n_tafel_fail = 0
        self.best_val = np.inf
        self.best_x = None

    def _evaluate(self, x: np.ndarray) -> float:
        self.n_fwd += 1
        i = forward_current(x)
        if i is None:
            self.n_ode_fail += 1
            return ODE_PENALTY
        feats = compute_features(i)
        tgt = self.target
        total = float(np.sum(((feats['dc'] - tgt['dc']) / SIGMA_DC) ** 2))
        for k in range(7):
            total += float(np.sum(((feats['harm'][k] - tgt['harm'][k]) / SIGMA_HARM) ** 2))
        if feats['tafel'] is None:
            self.n_tafel_fail += 1
            total += TAFEL_FAIL_RESID ** 2
        else:
            total += ((feats['tafel'] - tgt['tafel']) / SIGMA_TAFEL) ** 2
        return total / N_CHANNELS

    def __call__(self, x) -> float:
        x = np.asarray(x, dtype=float)
        if self.raise_on_timeout and time.perf_counter() > self.deadline:
            raise BudgetExhausted()
        if self.hard_cap is not None and self.n_calls >= self.hard_cap:
            self.n_over_cap += 1
            return self.OVER_CAP_PENALTY  # 超预算：不评估、不计数，罚值迫使优化器停止
        self.n_calls += 1
        hit = self.cache.get(x)
        if hit is not None:
            self.n_hit += 1
            val = hit
        else:
            val = self._evaluate(x)
            self.cache.put(x, val)
        if val < self.best_val:
            self.best_val = val
            self.best_x = x.copy()
        return val


# ============================ 进度持久化 ============================

def write_progress(scenario: str, algo: str, payload: dict):
    """每 trial / 每 start 更新进度文件（原子写），job 超时或崩溃时可回收部分结果。"""
    os.makedirs(PROGRESS_DIR, exist_ok=True)
    path = os.path.join(PROGRESS_DIR, f'{scenario}_{algo}.json')
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as fh:
        json.dump(payload, fh, ensure_ascii=False)
    os.replace(tmp, path)


# ============================ 算法 1：Optuna TPE ============================

def run_tpe(scenario: str, n_trials: int, time_budget: float) -> dict:
    import optuna  # 子进程内导入，避免主进程强依赖

    optuna.logging.set_verbosity(optuna.logging.WARNING)
    t0 = time.perf_counter()
    target = generate_target(scenario)
    cache = EvalCache(scenario, 'TPE')
    deadline = t0 + time_budget
    obj = Objective(target, cache, deadline, raise_on_timeout=False)

    sampler = optuna.samplers.TPESampler(seed=42, n_startup_trials=30)
    study = optuna.create_study(direction='minimize', sampler=sampler)

    history = []  # 每个完成 trial: {trial, value, best_so_far, n_fwd}
    timed_out = {'flag': False}

    def objective(trial):
        k0 = [trial.suggest_float(f'k0_{j}', 1e-3, 1e5, log=True) for j in range(1, 5)]
        g_oh = trial.suggest_float('G_OH', 0.8, 1.8)
        g_o = trial.suggest_float('G_O', 2.2, 3.4)
        sc = trial.suggest_float('scaling_OOH_OH', 2.8, 3.6)
        gam = trial.suggest_float('gamma', 1e-10, 1e-7, log=True)
        x = np.array([np.log10(k0[0]), np.log10(k0[1]), np.log10(k0[2]), np.log10(k0[3]),
                      g_oh, g_o, sc, np.log10(gam)])
        return obj(x)

    def callback(study_, trial):
        done = len([t for t in study_.trials if t.state == optuna.trial.TrialState.COMPLETE])
        history.append({
            'trial': done,
            'value': float(trial.value) if trial.value is not None else None,
            'best_so_far': float(study_.best_value),
            'n_fwd': obj.n_fwd,
        })
        write_progress(scenario, 'TPE', {
            'status': 'running', 'trials_done': done, 'history': history,
            'best_value': float(study_.best_value),
            'best_x': obj.best_x.tolist() if obj.best_x is not None else None,
            'n_calls': obj.n_calls, 'n_fwd': obj.n_fwd, 'n_hit': obj.n_hit,
        })
        if time.perf_counter() > deadline:
            timed_out['flag'] = True
            study_.stop()

    study.optimize(objective, n_trials=n_trials, callbacks=[callback])
    cache.save()

    return {
        'best_obj': float(study.best_value),
        'best_x': obj.best_x.tolist(),
        'n_calls': obj.n_calls, 'n_fwd': obj.n_fwd, 'n_hit': obj.n_hit,
        'n_over_cap': obj.n_over_cap,
        'n_ode_fail': obj.n_ode_fail, 'n_tafel_fail': obj.n_tafel_fail,
        'history': history,
        'timed_out': timed_out['flag'],
        'target_tafel': target['tafel'],
        'target_max_abs_i': target['max_abs_i'],
    }


# ============================ 算法 2：多起点 L-BFGS-B ============================

def run_lbfgsb(scenario: str, total_budget: int, time_budget: float) -> dict:
    from scipy.optimize import minimize
    from scipy.stats import qmc

    t0 = time.perf_counter()
    target = generate_target(scenario)
    cache = EvalCache(scenario, 'LBFGSB')
    deadline = t0 + time_budget
    # 硬预算：3 起点共享 total_budget 次有效评估；每起点至多 per_start 次。
    # scipy 的 maxfun 非硬上限（梯度+线搜索可超额），故用 Objective.hard_cap
    # 在每个起点前动态收紧：obj.hard_cap = 已用 + per_start，见 Objective 注释。
    obj = Objective(target, cache, deadline, raise_on_timeout=True, hard_cap=0)

    n_starts = 3
    per_start = total_budget // n_starts  # 完整 65 / 冒烟 17（17×3=51≈50）
    # Latin hypercube 起点（固定种子，跨场景一致，保证可比性）
    sampler = qmc.LatinHypercube(d=N_DIM, seed=777)
    starts = qmc.scale(sampler.random(n_starts), LB, UB)

    starts_info = []
    timed_out = False
    for s, x0 in enumerate(starts):
        remaining = total_budget - obj.n_calls
        if remaining <= 0:
            starts_info.append({'start': s, 'x0': x0.tolist(), 'fun': None,
                                'x': None, 'nfev': 0, 'nit': 0,
                                'success': False, 'message': '共享评估预算已耗尽，跳过'})
            break
        obj.hard_cap = obj.n_calls + min(per_start, remaining)
        try:
            res = minimize(obj, x0, method='L-BFGS-B', jac=None, bounds=BOUNDS,
                           options={'maxfun': min(per_start, remaining),
                                    # 数值梯度步长：ODE 求解（rtol=1e-6）使目标带数值噪声，
                                    # 默认 eps=1e-8 的差分会被噪声淹没，取 1e-3（log10 空间）
                                    'eps': 1e-3})
            starts_info.append({
                'start': s, 'x0': x0.tolist(), 'fun': float(res.fun),
                'x': res.x.tolist(), 'nfev': int(res.nfev),
                'nit': int(res.nit), 'success': bool(res.success),
                'message': str(res.message),
            })
        except BudgetExhausted:
            timed_out = True
            starts_info.append({'start': s, 'x0': x0.tolist(), 'fun': None,
                                'x': None, 'nfev': None, 'nit': None,
                                'success': False, 'message': '时间预算耗尽，中断'})
            break
        write_progress(scenario, 'LBFGSB', {
            'status': 'running', 'starts_done': s + 1, 'starts': starts_info,
            'best_value': float(obj.best_val) if np.isfinite(obj.best_val) else None,
            'best_x': obj.best_x.tolist() if obj.best_x is not None else None,
            'n_calls': obj.n_calls, 'n_fwd': obj.n_fwd, 'n_hit': obj.n_hit,
        })
    cache.save()

    return {
        'best_obj': float(obj.best_val),
        'best_x': obj.best_x.tolist() if obj.best_x is not None else None,
        'n_calls': obj.n_calls, 'n_fwd': obj.n_fwd, 'n_hit': obj.n_hit,
        'n_over_cap': obj.n_over_cap,
        'n_ode_fail': obj.n_ode_fail, 'n_tafel_fail': obj.n_tafel_fail,
        'starts': starts_info,
        'timed_out': timed_out,
        'target_tafel': target['tafel'],
        'target_max_abs_i': target['max_abs_i'],
    }


# ============================ 指标与并行调度 ============================

def recovery_metrics(best_x, x_true: np.ndarray) -> dict:
    """恢复误差：k0/gamma 报 log10 绝对误差，G 报绝对误差 (eV)。

    恢复判定：所有 log10 误差 < 0.3 且所有 G 误差 < 0.05 eV。
    """
    per_param = {}
    log_ok, g_ok = True, True
    if best_x is None:
        for name, kind, _, _ in PARAM_SPECS:
            per_param[name] = None
        return {'per_param': per_param, 'recovered': False}
    for (name, kind, _, _), xe, xt in zip(PARAM_SPECS, best_x, x_true):
        err = abs(float(xe) - float(xt))  # 编码空间：log10 空间差 / eV 差
        per_param[name] = err
        if kind == 'log10':
            log_ok = log_ok and (err < 0.3)
        else:
            g_ok = g_ok and (err < 0.05)
    return {'per_param': per_param, 'recovered': bool(log_ok and g_ok)}


def tpe_convergence_point(history: list):
    """TPE 收敛要点：首次 best_so_far ≤ 1.1 × 最终值 的 trial 序号与累计 nfev。"""
    if not history:
        return None
    final = history[-1]['best_so_far']
    if final is None or final <= 0:
        return None
    thr = 1.1 * final
    for h in history:
        if h['best_so_far'] <= thr:
            return {'trial': h['trial'], 'n_fwd': h['n_fwd'],
                    'final_best': final, 'threshold': thr}
    return None


def run_job(scenario: str, algo: str, quick: bool) -> dict:
    """单个 (场景 × 算法) job：生成目标 → 跑算法 → 计算指标。子进程入口。"""
    t0 = time.perf_counter()
    if quick:
        n_trials, total_budget, time_budget = 50, 51, 420.0
    else:
        n_trials, total_budget, time_budget = 200, 195, 1500.0

    if algo == 'TPE':
        res = run_tpe(scenario, n_trials, time_budget)
    else:
        res = run_lbfgsb(scenario, total_budget, time_budget)

    xt = truth_x(scenario)
    res['recovery'] = recovery_metrics(res['best_x'], xt)
    res['truth_x'] = xt.tolist()
    if algo == 'TPE':
        res['convergence_110'] = tpe_convergence_point(res.get('history', []))
    res['wall_time_s'] = time.perf_counter() - t0
    res['scenario'] = scenario
    res['algo'] = algo
    write_progress(scenario, algo, {**res, 'status': 'done'})
    return res


# ============================ 汇总输出 ============================

def fmt(v, nd=4):
    return 'N/A' if v is None else f'{v:.{nd}g}'


def print_scenario_table(scn: str, entry: dict):
    print(f'\n================ 场景 {scn}：{SCENARIOS[scn]["label"]} ================')
    print(f'目标 Tafel 斜率: {fmt(entry.get("target_tafel"), 5)} V/dec, '
          f'max|i_clean| = {fmt(entry.get("target_max_abs_i"), 4)} A')
    header = f'{"算法":<10}{"最优目标值":>12}{"nfev(仿真)":>12}{"目标调用":>10}{"缓存命中":>10}{"ODE失败":>9}{"墙钟(s)":>10}{"恢复":>6}'
    print(header)
    print('-' * len(header))
    for algo in ['TPE', 'LBFGSB']:
        r = entry['algos'].get(algo)
        if r is None:
            print(f'{algo:<10}{"超时/失败（见进度文件）":>20}')
            continue
        name = 'TPE' if algo == 'TPE' else 'L-BFGS-B'
        print(f'{name:<10}{fmt(r["best_obj"], 4):>12}{r["n_fwd"]:>12}{r["n_calls"]:>10}'
              f'{r["n_hit"]:>10}{r["n_ode_fail"]:>9}{r["wall_time_s"]:>10.1f}'
              f'{"是" if r["recovery"]["recovered"] else "否":>6}')

    # 参数恢复误差表
    xt = entry['algos']['TPE']['truth_x'] if entry['algos'].get('TPE') else None
    print(f'\n{"参数":<16}{"真值(编码)":>12}{"TPE估计":>12}{"TPE误差":>10}'
          f'{"LBFGS估计":>12}{"LBFGS误差":>11}')
    for j, (name, kind, _, _) in enumerate(PARAM_SPECS):
        unit = '(log10)' if kind == 'log10' else '(eV)   '
        vals = [f'{name}{unit:<4}']
        xt_j = xt[j] if xt else None
        vals.append(fmt(xt_j, 4))
        for algo in ['TPE', 'LBFGSB']:
            r = entry['algos'].get(algo)
            if r is None or r['best_x'] is None:
                vals += ['N/A', 'N/A']
            else:
                vals.append(fmt(r['best_x'][j], 4))
                vals.append(fmt(r['recovery']['per_param'][name], 3))
        print(f'{vals[0]:<24}{vals[1]:>12}{vals[2]:>12}{vals[3]:>10}{vals[4]:>12}{vals[5]:>11}')

    tpe = entry['algos'].get('TPE')
    if tpe and tpe.get('convergence_110'):
        c = tpe['convergence_110']
        print(f'\nTPE 收敛要点: 第 {c["trial"]} 次 trial（累计 nfev={c["n_fwd"]}）'
              f'达到最终值 {fmt(c["final_best"], 4)} 的 110% 以内')
    lb = entry['algos'].get('LBFGSB')
    if lb:
        if lb.get('n_over_cap'):
            print(f'  L-BFGS-B 超预算拒评估次数: {lb["n_over_cap"]}'
                  f'（scipy maxfun 非硬上限，目标函数层截断）')
        for s in lb.get('starts', []):
            print(f'  L-BFGS-B 起点{s["start"]}: fun={fmt(s["fun"], 4)}, nfev={s["nfev"]}, '
                  f'nit={s["nit"]}, 收敛={s["success"]}, 信息={s.get("message", "")[:60]}')


def main():
    ap = argparse.ArgumentParser(description='FTacV 反演基准：TPE vs 多起点 L-BFGS-B')
    ap.add_argument('--quick', action='store_true',
                    help='冒烟模式：每算法约 50 次目标评估')
    args = ap.parse_args()
    mode = 'quick' if args.quick else 'full'

    print(f'== FTacV 反演基准启动（模式: {mode}）==')
    print(f'自由参数维度: {N_DIM}（按任务参数表：k0_1..4、G_OH、G_O、scaling_OOH_OH、gamma）')
    print(f'正演: 32 周期 / 8192 点, f=1 Hz, dE=0.16 V; 丢前 1/4 瞬态; 公共网格 200 点')
    print(f'预算: TPE {"50" if args.quick else "200"} trials; '
          f'L-BFGS-B 3 起点 × maxfun={"17" if args.quick else "65"}')
    t_all = time.perf_counter()

    results = {}
    jobs = [(s, a) for s in SCENARIOS for a in ('TPE', 'LBFGSB')]
    with ProcessPoolExecutor(max_workers=6) as ex:
        futs = {ex.submit(run_job, s, a, args.quick): (s, a) for s, a in jobs}
        for fut in as_completed(futs):
            scn, algo = futs[fut]
            try:
                r = fut.result()
            except Exception as exc:  # noqa: BLE001
                # 兜底：读取进度文件，能回收多少算多少
                print(f'[警告] job {scn}/{algo} 异常终止: {exc}，尝试回收进度文件')
                path = os.path.join(PROGRESS_DIR, f'{scn}_{algo}.json')
                r = None
                if os.path.exists(path):
                    try:
                        with open(path, 'r', encoding='utf-8') as fh:
                            r = json.load(fh)
                        r['recovered_from_progress'] = True
                        xt = truth_x(scn)
                        r.setdefault('truth_x', xt.tolist())
                        r['recovery'] = recovery_metrics(r.get('best_x'), xt)
                        r.setdefault('wall_time_s', None)
                        r.setdefault('n_ode_fail', -1)
                        r.setdefault('n_tafel_fail', -1)
                        r.setdefault('n_calls', -1)
                        r.setdefault('n_fwd', -1)
                        r.setdefault('n_hit', -1)
                        r.setdefault('best_obj', r.get('best_value'))
                        if algo == 'TPE':
                            r['convergence_110'] = tpe_convergence_point(r.get('history', []))
                    except Exception as exc2:  # noqa: BLE001
                        print(f'[错误] 进度文件回收失败: {exc2}')
                        r = None
            if r is not None:
                results.setdefault(scn, {'algos': {}})['algos'][algo] = r
                print(f'[完成] 场景 {scn} / {algo}: best={fmt(r.get("best_obj"), 4)}, '
                      f'nfev={r.get("n_fwd")}, 墙钟={fmt(r.get("wall_time_s"), 5)} s')
            else:
                results.setdefault(scn, {'algos': {}})

    # 场景级公共信息（目标特征）
    for scn in SCENARIOS:
        for algo in ('TPE', 'LBFGSB'):
            r = results.get(scn, {}).get('algos', {}).get(algo)
            if r:
                results[scn]['target_tafel'] = r.get('target_tafel')
                results[scn]['target_max_abs_i'] = r.get('target_max_abs_i')
                break

    total_wall = time.perf_counter() - t_all
    out = {
        'meta': {
            'mode': mode,
            'pipeline_version': PIPELINE_VERSION,
            'n_dim': N_DIM,
            'param_specs': [list(s) for s in PARAM_SPECS],
            'budget': {'tpe_trials': 50 if args.quick else 200,
                       'lbfgsb_starts': 3,
                       'lbfgsb_maxfun_per_start': 17 if args.quick else 65},
            'channel_sigmas': {'dc': SIGMA_DC, 'harm': SIGMA_HARM, 'tafel': SIGMA_TAFEL},
            'n_channels': N_CHANNELS,
            'scenarios': {k: {'label': v['label'], 'sigma_noise': v['sigma_noise'],
                              'truth': v['truth']} for k, v in SCENARIOS.items()},
            'total_wall_time_s': total_wall,
            'created_at': time.strftime('%Y-%m-%dT%H:%M:%S'),
        },
        'scenarios': results,
    }
    with open(RESULTS_JSON, 'w', encoding='utf-8') as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1)
    print(f'\n结果已写入: {RESULTS_JSON}')
    print(f'总墙钟: {total_wall/60:.1f} 分钟')

    # 文本对比表
    for scn in SCENARIOS:
        entry = results.get(scn)
        if not entry or not entry.get('algos'):
            print(f'\n[缺失] 场景 {scn} 无任何算法结果')
            continue
        entry['target_tafel'] = results[scn].get('target_tafel')
        entry['target_max_abs_i'] = results[scn].get('target_max_abs_i')
        print_scenario_table(scn, entry)


if __name__ == '__main__':
    main()
