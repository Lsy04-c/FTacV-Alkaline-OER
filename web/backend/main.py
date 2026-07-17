"""碱性 OER AEM FTacV 参数反演平台 — FastAPI 后端"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'python'))

import numpy as np
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import Optional, List

from oer_aem import OERPhysics, OERSignal, OERObjective, initialize_oer_parameters

app = FastAPI(title="OER-FTAcV API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ===== 数据模型 =====

class SimParams(BaseModel):
    """仿真参数（前端传入的子集，其余使用默认值）"""
    G_OH: float = 1.55
    G_O: float = 3.10
    scaling_OOH_OH: float = 3.2
    E0_pre: float = 1.50
    k0_pre: float = 100.0
    k0_1: float = 1e4
    k0_2: float = 1e4
    k0_3: float = 10.0
    k0_4: float = 1e3
    E_start: float = 0.9
    E_end: float = 1.8
    f: float = 9.02
    dE: float = 0.08
    Ru: float = 75.0
    Cdl: float = 60e-6
    A: float = 0.196
    gamma: float = 1e-9
    n_points: int = 2048
    objective_mode: str = "ftacv"

class SimResult(BaseModel):
    success: bool
    E_actual: Optional[List[float]] = None
    i_total: Optional[List[float]] = None
    coverage_star: Optional[List[float]] = None
    coverage_ox: Optional[List[float]] = None
    coverage_OH: Optional[List[float]] = None
    coverage_O: Optional[List[float]] = None
    coverage_OOH: Optional[List[float]] = None
    eta_theoretical: Optional[float] = None
    E01: Optional[float] = None
    E02: Optional[float] = None
    E03: Optional[float] = None
    E04: Optional[float] = None
    time_elapsed: Optional[float] = None
    error: Optional[str] = None


# ===== API 路由 =====

@app.get("/api/params/defaults")
async def get_default_params():
    """返回默认参数（完整字典）。"""
    params = initialize_oer_parameters()
    # 只返回前端需要的可序列化字段
    keys = ['G_OH', 'G_O', 'scaling_OOH_OH', 'E0_pre',
            'k0_pre', 'k0_1', 'k0_2', 'k0_3', 'k0_4',
            'E01', 'E02', 'E03', 'E04',
            'E_start', 'E_end', 'f', 'dE',
            'Ru', 'Cdl', 'A', 'gamma',
            'n_points', 'points_per_cycle', 'T',
            'a', 'objective_mode']
    return {k: _serialize(params.get(k)) for k in keys}


@app.post("/api/simulate", response_model=SimResult)
async def simulate(p: SimParams):
    """运行单次 ODE 仿真，返回电流 + 覆盖度 + 平衡电位。"""
    import time
    try:
        params = initialize_oer_parameters()
        # 覆盖前端传入的参数
        for field, value in p.model_dump().items():
            if field in ('objective_mode',):
                params[field] = str(value)
            else:
                params[field] = value

        params['n_points'] = min(params['n_points'], 8192)
        params['points_per_cycle'] = 32
        params['total_time'] = (params['n_points'] / params['points_per_cycle']) / params['f']
        params['t_span'] = np.linspace(0, params['total_time'], params['n_points'])

        t0 = time.perf_counter()
        t, y, E_actual, i_total = OERPhysics.solve_ode_system(params)
        elapsed = time.perf_counter() - t0

        return SimResult(
            success=True,
            E_actual=E_actual.tolist(),
            i_total=i_total.tolist(),
            coverage_star=y[:, 0].tolist(),
            coverage_ox=y[:, 1].tolist(),
            coverage_OH=y[:, 2].tolist(),
            coverage_O=y[:, 3].tolist(),
            coverage_OOH=y[:, 4].tolist(),
            eta_theoretical=max(params['E01'], params['E02'], params['E03'], params['E04']) - 1.23,
            E01=params['E01'], E02=params['E02'], E03=params['E03'], E04=params['E04'],
            time_elapsed=elapsed,
        )
    except Exception as e:
        return SimResult(success=False, error=str(e))


@app.get("/api/health")
async def health():
    return {"status": "ok"}


def _serialize(val):
    """将 numpy 类型转为 Python 原生类型。"""
    if isinstance(val, (np.integer,)):
        return int(val)
    if isinstance(val, (np.floating,)):
        return float(val)
    if isinstance(val, np.ndarray):
        return val.tolist()
    if isinstance(val, (list, tuple)):
        return [_serialize(v) for v in val]
    return val


if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host='0.0.0.0', port=8000)
