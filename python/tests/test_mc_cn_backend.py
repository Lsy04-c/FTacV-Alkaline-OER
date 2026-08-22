"""CN 后端的契约测试。

库未编译时整体跳过——`scripts/build_mc_cn.sh` 生成 `cpp/libmccn.*`。
"""

import numpy as np
import pytest

from oer_aem import mc_cn_bridge
from oer_aem.molecular_catalysis import simulate

pytestmark = pytest.mark.skipif(
    not mc_cn_bridge.is_available(),
    reason="CN 动态库未编译（运行 scripts/build_mc_cn.sh）",
)


def _params(**overrides):
    params = {
        "E_start": 1.20, "v": 0.01756, "dE": 0.16, "f": 5.0,
        "Ru": 10.0, "Cdl": 30.8e-6, "A": 1.0,
        "gamma": 3e-10, "k0": 50.0, "kf": 200.0, "E0_eff": 1.58,
        "total_time": 25.6,
    }
    params.update(overrides)
    return params


def _grid(params, points_per_cycle=256):
    n = int(round(params["total_time"] * params["f"] * points_per_cycle))
    return np.linspace(0.0, params["total_time"], n, endpoint=False)


def test_cn_matches_lsoda_on_reference_point():
    """CN 与 LSODA 的总电流应在 1% 以内（等价性门的同一判据）。"""
    params = _params()
    t = _grid(params)
    _, i_lsoda, _ = simulate(dict(params, solver_backend="lsoda"), t)
    _, i_cn, _ = simulate(dict(params, solver_backend="cn"), t)
    span = np.max(np.abs(i_lsoda))
    assert np.sqrt(np.mean((i_cn - i_lsoda) ** 2)) / span < 0.01


def test_cn_converges_with_substeps():
    """加密内部步长应使 CN 单调逼近 LSODA。"""
    params = _params()
    t = _grid(params)
    _, ref, _ = simulate(dict(params, solver_backend="lsoda"), t)
    errors = []
    for substeps in (1, 4):
        _, i_cn, _ = simulate(dict(params, solver_backend="cn",
                                   cn_substeps=substeps), t)
        errors.append(np.max(np.abs(i_cn - ref)))
    assert errors[1] < errors[0]


def test_cn_rejects_non_uniform_grid():
    """CN 是定步长格式，非均匀网格必须报错而不是给出错误结果。"""
    params = _params()
    t = _grid(params)
    t_bad = t.copy()
    t_bad[10] += 0.5 * (t[1] - t[0])
    with pytest.raises(ValueError, match="均匀"):
        simulate(dict(params, solver_backend="cn"), t_bad)


def test_cn_rejects_grid_not_starting_at_zero():
    params = _params()
    t = _grid(params) + 1.0
    with pytest.raises(ValueError, match="从 0 开始"):
        simulate(dict(params, solver_backend="cn"), t)


def test_unknown_backend_is_rejected():
    """未知后端必须报错，禁止静默回退（docs/项目纠错.md 第 7 条）。"""
    params = _params()
    with pytest.raises(ValueError, match="solver_backend"):
        simulate(dict(params, solver_backend="bogus"), _grid(params))


def test_cn_uses_same_steady_state_initial_condition():
    """CN 与 LSODA 的首个输出点应一致——二者共用稳态初值。

    WORK_STATUS §19 记录过 C++ 自行计算初值造成 18.5% NRMSE 的事故。
    """
    params = _params()
    t = _grid(params)
    _, i_lsoda, _ = simulate(dict(params, solver_backend="lsoda"), t)
    _, i_cn, _ = simulate(dict(params, solver_backend="cn"), t)
    scale = np.max(np.abs(i_lsoda))
    assert abs(i_cn[0] - i_lsoda[0]) / scale < 1e-6


def test_required_substeps_uses_absolute_time():
    """步长上限按绝对时间换算——同样的每周期点数在低频下绝对步长更大。"""
    from oer_aem.mc_cn_bridge import required_substeps
    dt_5hz = 1.0 / (5.008 * 256)
    dt_1hz = 1.0 / (0.999 * 256)
    assert required_substeps(dt_5hz, 7.8e-4) == 1
    assert required_substeps(dt_1hz, 7.8e-4) == 6
    assert required_substeps(dt_1hz, dt_1hz) == 1
    with pytest.raises(ValueError):
        required_substeps(dt_1hz, 0.0)


def test_cn_max_dt_improves_low_frequency_accuracy():
    """1 Hz + 快动力学下，绝对步长上限应显著改善与 LSODA 的一致性。

    这正是等价性门首轮失败的参数区域（FT4, k0 接近上界）。
    """
    params = _params(f=1.0, v=0.0039, k0=955.0, gamma=6.7e-12,
                     kf=4.6, E0_eff=1.79, total_time=40.0)
    t = _grid(params)
    _, ref, _ = simulate(dict(params, solver_backend="lsoda"), t)
    scale = np.max(np.abs(ref))
    _, coarse, _ = simulate(dict(params, solver_backend="cn"), t)
    _, fine, _ = simulate(dict(params, solver_backend="cn", cn_max_dt=7.8e-4), t)
    err_coarse = np.sqrt(np.mean((coarse - ref) ** 2)) / scale
    err_fine = np.sqrt(np.mean((fine - ref) ** 2)) / scale
    assert err_fine < err_coarse
    assert err_fine < 0.01
