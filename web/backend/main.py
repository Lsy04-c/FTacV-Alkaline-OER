"""碱性 OER AEM FTacV 参数反演平台 — FastAPI 后端"""

import sys, os, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'python'))

import numpy as np
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import Optional, List, Dict, Any

from oer_aem import OERPhysics, OERSignal, initialize_oer_parameters

app = FastAPI(title="OER-FTAcV API", version="0.2.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# 托管前端静态文件
frontend_dir = os.path.join(os.path.dirname(__file__), '..', 'frontend')
app.mount("/static", StaticFiles(directory=frontend_dir), name="static")

# ===== 数据模型 =====
class SimParams(BaseModel):
    # 与 python/oer_aem/defaults.py 保持一致（2026-07-18 统一）
    G_OH: float = 1.23
    G_O: float = 2.80
    scaling_OOH_OH: float = 3.2
    E0_pre: float = 1.45
    k0_pre: float = 500.0
    k0_1: float = 1e3
    k0_2: float = 5e2
    k0_3: float = 50.0
    k0_4: float = 1e3
    E_start: float = 0.9
    E_end: float = 2.0
    f: float = 9.02
    dE: float = 0.15
    Ru: float = 10.0
    Cdl: float = 60e-6
    A: float = 0.196
    gamma: float = 1e-9
    n_points: int = 16384
    points_per_cycle: int = 256
    objective_mode: str = "ftacv"


class ExpDataIn(BaseModel):
    """实验数据：[[E, i, t], ...]（V, A, s）"""
    rows: List[List[float]]


def _to_list(arr):
    if isinstance(arr, np.ndarray): return arr.tolist()
    return list(arr) if arr is not None else None


def _analyze_ftacv_data(rows: np.ndarray) -> Dict[str, Any]:
    """从 FTacV 实验数据自动识别采集参数并提取 DC + 1-7 次谐波。

    数据格式：[E (V), i (A), t (s)]，单次正向扫描。
    识别：v（线性斜坡）、dE（去趋势振幅）、f（FFT 主频）。
    """
    E_raw, i_raw, t_raw = rows[:, 0], rows[:, 1], rows[:, 2]
    t = t_raw - t_raw[0]
    order = np.argsort(t)
    t, E_raw, i_raw = t[order], E_raw[order], i_raw[order]

    duration = float(t[-1])
    dt = float(np.mean(np.diff(t)))
    fs = 1.0 / dt

    # DC 斜坡 → v
    slope, intercept = np.polyfit(t, E_raw, 1)
    v = float(slope)
    E_dc = intercept + slope * t

    # 交流分量 → dE, f
    E_ac = E_raw - E_dc
    dE = float(np.std(E_ac) * np.sqrt(2.0))
    Y = np.abs(np.fft.rfft(E_ac))
    freqs = np.fft.rfftfreq(len(t), dt)
    k = int(np.argmax(Y[1:]) + 1) if len(Y) > 1 else 1
    f0 = float(freqs[k])

    # 谐波提取（与仿真同一管线：Tukey 窗 + FFT 选带）
    sp = {'f': f0, 'band': np.ones(8), 'use_fft': True}
    I_dc = OERSignal.extract_dc_fft(i_raw, fs, sp)
    I_harm = OERSignal.extract_harmonics(i_raw, fs, sp)

    norm = lambda a: (a / max(np.max(np.abs(a)), 1e-30))
    return {
        'success': True,
        'meta': {
            'f': f0, 'dE': dE, 'v': v,
            'E_start': float(intercept), 'E_end': float(intercept + slope * duration),
            'duration': duration, 'n_points': int(len(t)), 'fs': fs,
        },
        'tdc': _to_list(E_dc),
        'E_raw': _to_list(E_raw),
        'i_raw': _to_list(i_raw),
        'dc': _to_list(norm(I_dc)),
        'harmonics': [_to_list(norm(I_harm[:, kk])) for kk in range(7)],
    }



def _serialize(val):
    if isinstance(val, (np.integer,)): return int(val)
    if isinstance(val, (np.floating,)): return float(val)
    if isinstance(val, np.ndarray): return val.tolist()
    if isinstance(val, (list, tuple)): return [_serialize(v) for v in val]
    return val


# ===== API 路由 =====

@app.post("/api/data/analyze")
async def analyze_data(d: ExpDataIn) -> Dict[str, Any]:
    """接收实验 FTacV 数据行 [[E, i, t], ...]，识别采集参数并提取 DC + 1-7 次谐波。"""
    try:
        rows = np.asarray(d.rows, dtype=float)
        if rows.ndim != 2 or rows.shape[1] < 3 or rows.shape[0] < 1024:
            return {'success': False, 'error': f'数据形状无效: {rows.shape}（需要 N×3 且 N≥1024）'}
        return _analyze_ftacv_data(rows)
    except Exception as e:
        return {'success': False, 'error': str(e)}


@app.get("/api/params/defaults")
async def get_default_params():
    params = initialize_oer_parameters()
    keys = ['G_OH', 'G_O', 'scaling_OOH_OH', 'E0_pre',
            'k0_pre', 'k0_1', 'k0_2', 'k0_3', 'k0_4',
            'E01', 'E02', 'E03', 'E04',
            'E_start', 'E_end', 'f', 'dE',
            'Ru', 'Cdl', 'A', 'gamma',
            'n_points', 'points_per_cycle', 'T', 'a', 'objective_mode',
            'use_steady_state', 'use_fft']
    return {k: _serialize(params.get(k)) for k in keys}


@app.post("/api/simulate")
async def simulate(p: SimParams) -> Dict[str, Any]:
    """运行 ODE 仿真 + 谐波提取，返回全部可视化数据。"""
    try:
        params = initialize_oer_parameters()
        for field, value in p.model_dump().items():
            if field == 'objective_mode':
                params[field] = str(value)
            else:
                params[field] = value

        params['n_points'] = min(params['n_points'], 65536)
        params['total_time'] = (params['n_points'] / params['points_per_cycle']) / params['f']
        params['t_span'] = np.linspace(0, params['total_time'], params['n_points'])

        t0 = time.perf_counter()
        t, y, E_actual_raw, i_total_raw = OERPhysics.solve_ode_system(params)
        elapsed = time.perf_counter() - t0

        # ---- 谐波提取 ----
        df = OERSignal.safe_df(t)
        i_total = np.asarray(i_total_raw).reshape(-1)
        tdc = params['E_start'] + t * params['v']

        # DC 分量（与谐波同流程：FFT 选带 + 边缘加窗）
        I_dc = OERSignal.process_current(i_total, df, params)[:, 0]

        # 1-7 次谐波
        I_harm = OERSignal.extract_harmonics(i_total, df, params)

        # 功率谱
        L = len(i_total)
        Y = np.fft.fft(i_total)
        P2 = np.abs(Y / L)
        P1 = P2[:L // 2 + 1]
        P1[1:-1] = 2 * P1[1:-1]
        f_axis = df * np.arange(L // 2 + 1) / L

        # 截取到 15*f 以内
        f_max = 15 * params['f']
        idx = f_axis <= f_max

        return {
            'success': True,
            # 总电流曲线
            'E_actual': _to_list(E_actual_raw),
            'i_total': _to_list(i_total),
            'tdc': _to_list(tdc),
            # 覆盖度
            'coverage_star': _to_list(y[:, 0]),
            'coverage_ox':   _to_list(y[:, 1]),
            'coverage_OH':   _to_list(y[:, 2]),
            'coverage_O':    _to_list(y[:, 3]),
            'coverage_OOH':  _to_list(y[:, 4]),
            # 功率谱
            'ps_freq': _to_list(f_axis[idx]),
            'ps_mag':  _to_list(P1[idx]),
            # DC + 谐波（归一化到各自最大值）
            'dc':   _to_list(I_dc / max(np.max(I_dc), 1e-30)),
            'harmonics': [_to_list(I_harm[:, k] / max(np.max(np.abs(I_harm[:, k])), 1e-30)) for k in range(7)],
            # 参数摘要
            'E01': params['E01'], 'E02': params['E02'],
            'E03': params['E03'], 'E04': params['E04'],
            'eta_theoretical': max(params['E01'], params['E02'], params['E03'], params['E04']) - 1.23,
            'time_elapsed': elapsed,
        }
    except Exception as e:
        return {'success': False, 'error': str(e)}


from fastapi.responses import FileResponse

@app.get("/")
async def root():
    return FileResponse(os.path.join(frontend_dir, "index.html"))

@app.get("/api/health")
async def health():
    return {"status": "ok"}


if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host='0.0.0.0', port=8000)
