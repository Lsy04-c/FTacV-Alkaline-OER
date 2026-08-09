"""ctypes wrapper for the C++ OER Crank-Nicolson solver (liboercn)."""

from __future__ import annotations

import ctypes
import os
import platform
from pathlib import Path
from typing import Optional

import numpy as np

_PROJECT_ROOT = Path(__file__).resolve().parents[4]
_CPP_DIR = _PROJECT_ROOT / "code" / "cpp" / "build"

if platform.system() == "Darwin":
    _lib_path = str(_CPP_DIR / "liboercn.dylib")
elif platform.system() == "Linux":
    _lib_path = str(_CPP_DIR / "liboercn.so")
else:
    _lib_path = str(_CPP_DIR / "liboercn.dll")

_lib = None
_available = os.path.exists(_lib_path)

if _available:
    _lib = ctypes.CDLL(str(_lib_path))
    _lib.oer_cn_solve.argtypes = [
        ctypes.POINTER(ctypes.c_double),   # p (32 doubles)
        ctypes.c_int,                       # n_points
        ctypes.POINTER(ctypes.c_double),   # y0_in (6 doubles)
        ctypes.POINTER(ctypes.c_double),   # t_out
        ctypes.POINTER(ctypes.c_double),   # y_out
        ctypes.POINTER(ctypes.c_double),   # i_out
        ctypes.POINTER(ctypes.c_double),   # E_out
    ]
    _lib.oer_cn_solve.restype = ctypes.c_int
    _lib.oer_cn_solve_batch.argtypes = [
        ctypes.POINTER(ctypes.c_double), ctypes.c_int, ctypes.c_int,
        ctypes.POINTER(ctypes.c_double), ctypes.POINTER(ctypes.c_int),
    ]
    _lib.oer_cn_solve_batch.restype = ctypes.c_int

# Parameter layout matching the C++ P_* enum
_PARAM_KEYS = [
    "E_start", "E_end", "f", "dE", "Ru", "Cdl", "A", "gamma",
    "k0_1", "k0_2", "k0_3", "k0_4", "k0_pre",
    "G_OH", "G_O", "scaling_OOH_OH", "a",
    "E01", "E02", "E03", "E04", "E0_pre",
    "RTF", "invRC", "gammaF_Cdl", "total_time", "v", "omega",
    "beta_recon", "E_recon", "w_recon", "F",
]


def is_available() -> bool:
    """Return True if the compiled C++ library exists."""
    return _available


def library_path() -> str:
    """Return the platform-specific classified C++ library path."""
    return _lib_path


def pack_params(params: dict) -> np.ndarray:
    """Convert a full parameter dictionary to the flat C array (32 doubles)."""
    p = np.zeros(32, dtype=np.float64)
    for i, key in enumerate(_PARAM_KEYS):
        p[i] = float(params.get(key, 0.0))
    return p


def solve_cn_with_status(
    params: dict,
    y0: Optional[np.ndarray] = None,
) -> tuple[Optional[np.ndarray], int]:
    """Run CN and return ``(current, status)`` without hiding C status codes.

    Parameters
    ----------
    params : dict
        Full parameter dictionary from ``params_from_vector()``.
    y0 : (6,) array, optional
        Initial state.  Defaults to steady-state inside the C++ solver.

    Returns
    -------
    current : (n_points,) array or None on failure
    status : int
        C ABI status: 0 success, -1 invalid input, -2 steady-state failure,
        -3 non-finite output, -4 time-step Newton/subdivision failure.
    """
    if not _available:
        return None, -1

    p_arr = pack_params(params)
    n_points = int(params.get("n_points", 8000))

    y0_arr = np.asarray(y0, dtype=np.float64) if y0 is not None else None
    if y0_arr is not None and y0_arr.size != 6:
        raise ValueError(f"y0 must have 6 elements, got {y0_arr.size}")

    i_out = np.empty(n_points, dtype=np.float64)

    ret = _lib.oer_cn_solve(
        p_arr.ctypes.data_as(ctypes.POINTER(ctypes.c_double)),
        ctypes.c_int(n_points),
        y0_arr.ctypes.data_as(ctypes.POINTER(ctypes.c_double)) if y0_arr is not None else None,
        None,  # t_out
        None,  # y_out
        i_out.ctypes.data_as(ctypes.POINTER(ctypes.c_double)),
        None,  # E_out
    )
    if ret != 0:
        return None, int(ret)

    current = np.asarray(i_out, dtype=float)
    if not np.all(np.isfinite(current)):
        return None, -3
    return current, 0


def solve_cn(
    params: dict,
    y0: Optional[np.ndarray] = None,
) -> Optional[np.ndarray]:
    """Run CN and preserve the historical current-only return API."""
    current, _status = solve_cn_with_status(params, y0=y0)
    return current


def solve_cn_batch(params_list: list[dict]) -> tuple[np.ndarray, np.ndarray]:
    """Run independent screen cases through the batch C ABI.

    Per-case status codes are returned unchanged; failures must be handled by
    the caller and are never silently converted to NaN or dropped.
    """
    if not _available:
        raise RuntimeError("CN screen library is unavailable")
    if not params_list:
        raise ValueError("params_list must not be empty")
    n_cases = len(params_list)
    n_points = int(params_list[0].get("n_points", 8000))
    if n_points < 2:
        raise ValueError("n_points must be at least two")
    if any(int(item.get("n_points", n_points)) != n_points for item in params_list):
        raise ValueError("all batch cases must use the same n_points")
    packed = np.ascontiguousarray(
        np.vstack([pack_params(item) for item in params_list]), dtype=np.float64
    )
    currents = np.empty((n_cases, n_points), dtype=np.float64)
    statuses = np.empty(n_cases, dtype=np.int32)
    ret = _lib.oer_cn_solve_batch(
        packed.ctypes.data_as(ctypes.POINTER(ctypes.c_double)),
        ctypes.c_int(n_cases), ctypes.c_int(n_points),
        currents.ctypes.data_as(ctypes.POINTER(ctypes.c_double)),
        statuses.ctypes.data_as(ctypes.POINTER(ctypes.c_int)),
    )
    if ret != 0:
        raise RuntimeError(f"CN batch ABI failed with status {ret}")
    return currents, statuses
