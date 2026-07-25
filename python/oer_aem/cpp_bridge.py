"""ctypes wrapper for the C++ OER Crank-Nicolson solver (liboercn)."""

from __future__ import annotations

import ctypes
import os
import platform
from typing import Optional

import numpy as np

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_CPP_DIR = os.path.join(_PROJECT_ROOT, "cpp")

if platform.system() == "Darwin":
    _lib_path = os.path.join(_CPP_DIR, "liboercn.dylib")
elif platform.system() == "Linux":
    _lib_path = os.path.join(_CPP_DIR, "liboercn.so")
else:
    _lib_path = os.path.join(_CPP_DIR, "liboercn.dll")

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


def pack_params(params: dict) -> np.ndarray:
    """Convert a full parameter dictionary to the flat C array (32 doubles)."""
    p = np.zeros(32, dtype=np.float64)
    for i, key in enumerate(_PARAM_KEYS):
        p[i] = float(params.get(key, 0.0))
    return p


def solve_cn(
    params: dict,
    y0: Optional[np.ndarray] = None,
) -> np.ndarray:
    """Run the C++ Crank-Nicolson solver and return total current.

    Parameters
    ----------
    params : dict
        Full parameter dictionary from ``params_from_vector()``.
    y0 : (6,) array, optional
        Initial state.  Defaults to steady-state inside the C++ solver.

    Returns
    -------
    current : (n_points,) array or None on failure
    """
    if not _available:
        return None

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
        return None

    current = np.asarray(i_out, dtype=float)
    if not np.all(np.isfinite(current)):
        return None
    return current
