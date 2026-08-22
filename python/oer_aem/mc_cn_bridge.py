"""ctypes wrapper for the C Crank-Nicolson solver of the low-dim model.

对应源码 `cpp/mc_cn_solver.c`，构建方式见 `scripts/build_mc_cn.sh`。
约定与既有 `cpp_bridge.py` 一致：库文件放在 `cpp/`，缺失时 `is_available()`
返回 False，由调用方决定报错还是回退——**本项目禁止静默回退**
（`docs/项目纠错.md` 第 7 条）。

性能与精度数据见 `docs/solver_acceleration_feasibility.md`。
"""

from __future__ import annotations

import ctypes
import math
import os
import platform
from typing import Tuple

import numpy as np

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_CPP_DIR = os.path.join(_PROJECT_ROOT, "cpp")

if platform.system() == "Darwin":
    _LIB_PATH = os.path.join(_CPP_DIR, "libmccn.dylib")
elif platform.system() == "Linux":
    _LIB_PATH = os.path.join(_CPP_DIR, "libmccn.so")
else:
    _LIB_PATH = os.path.join(_CPP_DIR, "libmccn.dll")

_lib = None
if os.path.exists(_LIB_PATH):
    _lib = ctypes.CDLL(str(_LIB_PATH))
    _lib.mc_cn_solve.restype = ctypes.c_int
    _lib.mc_cn_solve.argtypes = [
        np.ctypeslib.ndpointer(np.float64, flags="C_CONTIGUOUS"),
        ctypes.c_double, ctypes.c_long, ctypes.c_long,
        *([ctypes.c_double] * 12),
        np.ctypeslib.ndpointer(np.float64, flags="C_CONTIGUOUS"),
        np.ctypeslib.ndpointer(np.float64, flags="C_CONTIGUOUS"),
    ]


def is_available() -> bool:
    """返回编译好的动态库是否存在。"""
    return _lib is not None


def library_path() -> str:
    """返回期望的动态库路径（用于 manifest 记录）。"""
    return _LIB_PATH


def required_substeps(dt_out: float, max_dt: float) -> int:
    """把绝对步长上限换算成每个输出点的内部步数。

    步长必须按**绝对时间**设定，不能按"每周期多少点"。体系的快时间尺度由
    ``1/k0``、``1/kf`` 和 ``Ru*Cdl*A`` 决定，与交流频率无关；同样的
    "256 点/周期"在 1 Hz 数据上的绝对步长是 5 Hz 数据的 5 倍。
    等价性门首轮（substeps=1）正是因此在 FT4(1 Hz) 上失败——
    k0=955 时 1/k0=1.05e-3 s 已小于该数据集的输出步长 3.91e-3 s。
    """
    if max_dt <= 0:
        raise ValueError("max_dt 必须为正")
    # 容忍 0.01% 的相对超出：实测步长由 1/(f*ppc) 得到，浮点上会比整定的
    # 上限高出百万分之几，不加容差会平白把步数翻倍。
    ratio = (dt_out / max_dt) * (1.0 - 1e-4)
    return max(1, int(math.ceil(ratio)))


def solve(params: dict, y0: np.ndarray, t_eval: np.ndarray,
          substeps: int = 1, max_dt: float | None = None) -> Tuple[np.ndarray, np.ndarray]:
    """在均匀网格上求解，返回 ``(t_out, i_total)``。

    ``y0`` 必须由 `molecular_catalysis.calculate_mc_steady_state` 生成——
    与 LSODA 路径共用同一个稳态初值。`docs/项目纠错.md` 第 7 条记录过
    C++ 内部自行算初值造成 18.5% NRMSE 的事故，远大于积分格式本身的差异。

    ``substeps`` 为每个输出点内部推进的 CN 步数；输出网格即 ``t_eval``。
    给出 ``max_dt`` 时按绝对步长上限自动推导 substeps，并取二者较大值。
    """
    if _lib is None:
        raise RuntimeError(
            f"CN 动态库不存在：{_LIB_PATH}。先运行 scripts/build_mc_cn.sh。"
            " 本项目禁止静默回退到 LSODA。"
        )
    t_eval = np.ascontiguousarray(t_eval, dtype=float)
    if t_eval.size < 2:
        raise ValueError("t_eval 至少需要 2 个点")

    steps = np.diff(t_eval)
    if not np.allclose(steps, steps[0], rtol=1e-9, atol=0.0):
        raise ValueError("CN 后端要求均匀时间网格")
    if abs(float(t_eval[0])) > 1e-12:
        raise ValueError("CN 后端要求 t_eval 从 0 开始")
    if int(substeps) < 1:
        raise ValueError("substeps 必须 >= 1")

    n_out = int(t_eval.size)
    dt_out = float(steps[0])
    if max_dt is not None:
        substeps = max(int(substeps), required_substeps(dt_out, float(max_dt)))
    t_end = float(t_eval[-1]) + dt_out          # 输出为步首，故总时长多一格
    n_steps = n_out * int(substeps)

    out_t = np.empty(n_out, dtype=float)
    out_i = np.empty(n_out, dtype=float)
    code = _lib.mc_cn_solve(
        np.ascontiguousarray(y0, dtype=float), t_end, n_steps, n_out,
        float(params["RTF"]), float(params["alpha"]), float(params["k0"]),
        float(params["kf"]), float(params["E0_eff"]), float(params["omega"]),
        float(params["E_start"]), float(params["v"]), float(params["dE"]),
        float(params["invRC"]),
        float(params["gamma"]) * float(params["F"]) / float(params["Cdl"]),
        float(params["Ru"]),
        out_t, out_i,
    )
    if code != 0:
        raise RuntimeError(f"mc_cn_solve 返回错误码 {code}")
    return out_t, out_i
