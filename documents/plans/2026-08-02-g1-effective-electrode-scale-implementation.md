# G1 有效电极标度参数实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不改变冻结A6-v2输入和科学阈值的前提下，把总电流模型中的
`A/Cdl/gamma`精确尺度对称性固化为组合参数API、回归测试和开发版schema。

**Architecture:** 新模块只负责把旧面参数和新组合参数解析为唯一的总量表示。
Python物理核心继续接受旧输入，同时内部登记`CdlA/GammaA`并用它们计算派生
电路量。新schema标记为`development_only`，不替换冻结A6角色表。

**Tech Stack:** Python 3、NumPy/SciPy、pytest、JSON。

---

## 范围与压力边界

- 只支持当前有来源的`current_basis=total`；电流密度分支显式拒绝。
- 旧`A/Cdl/gamma`和新`CdlA/GammaA`同时出现时必须数值一致，否则失败。
- 新组合输入可缺省`A`；内部以`A=1`构造等价旧参数，不把该值解释为真实面积。
- 不修改`DEFAULT_PARAM_SPECS`、A6-v2任务、TPE、LSODA、CN或Gate阈值。
- 不提交Git；验证后由项目负责人决定是否提交。

### Task 1: 组合参数解析API

**Files:**

- Create: `code/python/src/oer_aem/electrode_scale.py`
- Create: `code/python/tests/test_electrode_scale.py`

- [x] **Step 1: 写失败测试**

```python
import pytest

from oer_aem.electrode_scale import canonicalize_electrode_scale


def test_legacy_scale_is_converted_to_total_quantities():
    result = canonicalize_electrode_scale(
        {"A": 2.0, "Cdl": 1e-5, "gamma": 2.5e-8}
    )
    assert result["current_basis"] == "total"
    assert result["CdlA"] == 2e-5
    assert result["GammaA"] == 5e-8


def test_canonical_totals_expand_to_an_equivalent_legacy_tuple():
    result = canonicalize_electrode_scale(
        {"current_basis": "total", "CdlA": 2e-5, "GammaA": 5e-8}
    )
    assert result["A"] == 1.0
    assert result["Cdl"] == 2e-5
    assert result["gamma"] == 5e-8


def test_inconsistent_redundant_scale_is_rejected():
    with pytest.raises(ValueError, match="CdlA"):
        canonicalize_electrode_scale(
            {
                "A": 2.0,
                "Cdl": 1e-5,
                "gamma": 2.5e-8,
                "CdlA": 3e-5,
                "GammaA": 5e-8,
            }
        )


def test_density_basis_is_not_silently_interpreted_as_total_current():
    with pytest.raises(ValueError, match="current_basis"):
        canonicalize_electrode_scale(
            {"current_basis": "density", "Cdl": 1e-5, "gamma": 2.5e-8}
        )
```

- [x] **Step 2: 验证测试因模块缺失而失败**

Run:

```bash
.venv/bin/python -m pytest code/python/tests/test_electrode_scale.py -q
```

Expected: collection fails with `ModuleNotFoundError: oer_aem.electrode_scale`.

- [x] **Step 3: 实现最小解析器**

```python
import math
from typing import Any, Mapping


def _positive(name: str, value: Any) -> float:
    number = float(value)
    if not math.isfinite(number) or number <= 0.0:
        raise ValueError(f"{name} must be finite and strictly positive")
    return number


def _require_close(name: str, actual: float, expected: float) -> None:
    if not math.isclose(actual, expected, rel_tol=1e-12, abs_tol=0.0):
        raise ValueError(f"{name} conflicts with legacy A/Cdl/gamma")


def canonicalize_electrode_scale(params: Mapping[str, Any]) -> dict[str, Any]:
    result = dict(params)
    basis = str(result.get("current_basis", "total"))
    if basis not in {"total", "total_current"}:
        raise ValueError("current_basis must be 'total' for the M0 total-current model")

    legacy_present = all(name in result for name in ("A", "Cdl", "gamma"))
    canonical_present = all(name in result for name in ("CdlA", "GammaA"))
    if not legacy_present and not canonical_present:
        raise ValueError("provide A/Cdl/gamma or CdlA/GammaA")

    area = _positive("A", result.get("A", 1.0))
    if legacy_present:
        cdl_a_legacy = area * _positive("Cdl", result["Cdl"])
        gamma_a_legacy = area * _positive("gamma", result["gamma"])
    if canonical_present:
        cdl_a = _positive("CdlA", result["CdlA"])
        gamma_a = _positive("GammaA", result["GammaA"])
        if legacy_present:
            _require_close("CdlA", cdl_a, cdl_a_legacy)
            _require_close("GammaA", gamma_a, gamma_a_legacy)
    else:
        cdl_a, gamma_a = cdl_a_legacy, gamma_a_legacy

    result.update(
        current_basis="total",
        A=area,
        Cdl=cdl_a / area,
        gamma=gamma_a / area,
        CdlA=cdl_a,
        GammaA=gamma_a,
    )
    return result
```

- [x] **Step 4: 运行新测试并确认通过**

Run: `.venv/bin/python -m pytest code/python/tests/test_electrode_scale.py -q`

Expected: all tests pass.

### Task 2: 接入Python物理核心并证明等价

**Files:**

- Modify: `code/python/src/oer_aem/physics.py`
- Modify: `code/python/src/oer_aem/__init__.py`
- Modify: `code/python/tests/test_physics.py`

- [x] **Step 1: 写canonical-only全轨迹与谐波失败测试**

```python
def test_canonical_total_scale_matches_legacy_full_output_and_harmonics():
    legacy = initialize_oer_parameters()
    legacy.update(
        {
            "A": 2.0,
            "Cdl": 1e-5,
            "gamma": 2.5e-8,
            "n_points": 256,
            "points_per_cycle": 64,
            "total_time": 4.0 / legacy["f"],
            "use_steady_state": False,
        }
    )
    legacy["t_span"] = np.linspace(0.0, legacy["total_time"], 256)
    legacy = OERPhysics.initialize_system(legacy)

    canonical = {
        key: value
        for key, value in legacy.items()
        if key not in {
            "A",
            "Cdl",
            "gamma",
            "invRC",
            "gammaF_Cdl",
            "_electrode_scale_source",
        }
    }
    canonical.update(
        {"current_basis": "total", "CdlA": 2e-5, "GammaA": 5e-8}
    )
    canonical = OERPhysics.initialize_system(canonical)

    legacy_result = OERPhysics.solve_ode_system(legacy)
    canonical_result = OERPhysics.solve_ode_system(canonical)
    assert canonical_result[2] == pytest.approx(legacy_result[2], abs=1e-12)

    fs = OERSignal.safe_df(legacy_result[0])
    legacy_h = OERSignal.extract_harmonics(legacy_result[2], fs, legacy)
    canonical_h = OERSignal.extract_harmonics(canonical_result[2], fs, canonical)
    assert canonical_h[:, :3] == pytest.approx(legacy_h[:, :3], abs=1e-12)
```

- [x] **Step 2: 验证canonical-only输入因缺少旧字段而失败**

Run:

```bash
.venv/bin/python -m pytest \
  code/python/tests/test_physics.py::test_canonical_total_scale_matches_legacy_full_output_and_harmonics -q
```

Expected: FAIL，错误指出缺少`Cdl/A/gamma`之一。

- [x] **Step 3: 最小接入**

在`initialize_system()`开头调用`canonicalize_electrode_scale()`，并使用：

```python
params["invRC"] = 1.0 / (params["Ru"] * params["CdlA"])
params["gammaF_Cdl"] = params["GammaA"] * params["F"] / params["CdlA"]
```

保留旧字段供C++桥和冻结流程兼容。导出`canonicalize_electrode_scale`供schema和
后续反演入口复用。

- [x] **Step 4: 运行组合参数和物理测试**

Run:

```bash
.venv/bin/python -m pytest \
  code/python/tests/test_electrode_scale.py \
  code/python/tests/test_physics.py -q
```

Expected: all tests pass.

### Task 3: 开发版机器可读schema

**Files:**

- Create: `config/parameter-schemas/m0-total-current-effective-v1.json`
- Create: `code/python/tests/test_effective_parameter_schema.py`

- [x] **Step 1: 写失败测试**

```python
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
SCHEMA_PATH = (
    ROOT / "config" / "parameter-schemas" /
    "m0-total-current-effective-v1.json"
)


def test_effective_parameter_schema_excludes_exact_legacy_redundancy():
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    assert schema["status"] == "development_only"
    assert schema["current_basis"] == "total"
    assert schema["legacy_mapping"]["CdlA"] == "A*Cdl"
    assert schema["legacy_mapping"]["GammaA"] == "A*gamma"
    assert not {"A", "Cdl", "gamma"}.issubset(schema["forward_parameters"])
    assert schema["frozen_workflows"] == ["A6-v2-S1"]
```

- [x] **Step 2: 验证schema缺失导致测试失败**

Run: `.venv/bin/python -m pytest code/python/tests/test_effective_parameter_schema.py -q`

Expected: FAIL with `FileNotFoundError`.

- [x] **Step 3: 创建schema**

```json
{
  "schema_version": 1,
  "model_version": "M0",
  "status": "development_only",
  "current_basis": "total",
  "current_basis_source": {
    "kind": "externally_declared",
    "value": "A",
    "supporting_evidence": "paired CHI CV headers: Current/A"
  },
  "forward_parameters": [
    "CdlA",
    "GammaA",
    "Ru",
    "E0_pre",
    "k0_pre",
    "k0_1",
    "k0_2",
    "k0_3",
    "k0_4",
    "G_OH",
    "G_O",
    "scaling_OOH_OH"
  ],
  "parameters": {
    "CdlA": {"unit": "F", "role": "calibrated_input"},
    "GammaA": {"unit": "mol", "role": "coupling_control"},
    "A": {"unit": "cm^2", "role": "reporting_input", "forward_parameter": false},
    "Ru": {"unit": "ohm", "role": "calibrated_input"}
  },
  "legacy_mapping": {
    "CdlA": "A*Cdl",
    "GammaA": "A*gamma"
  },
  "frozen_workflows": ["A6-v2-S1"],
  "eligible_for_real_inversion": false
}
```

不得改写旧A6角色表。

- [x] **Step 4: 运行schema测试**

Run: `.venv/bin/python -m pytest code/python/tests/test_effective_parameter_schema.py -q`

Expected: pass.

### Task 4: 验证与项目进度

**Files:**

- Modify: `documents/project/PROJECT_SUMMARY.md`
- Modify: `documents/project/WORK_STATUS.md`

- [x] **Step 1: 运行G1目标测试**

```bash
.venv/bin/python -m pytest \
  code/python/tests/test_electrode_scale.py \
  code/python/tests/test_effective_parameter_schema.py \
  code/python/tests/test_physics.py -q
```

- [x] **Step 2: 运行全量Python测试**

```bash
.venv/bin/python -m pytest code/python/tests -q
```

- [x] **Step 3: 审计差异**

```bash
git diff --check
git status --short
```

- [x] **Step 4: 更新进度口径**

只在验证通过后记录：组合参数API、旧输入兼容、canonical-only等价测试、schema
状态及测试计数。明确G1仍未完成的覆盖度四/五状态诊断，不宣称可正式真实反演。

### Task 5: 四状态守恒坐标与隐藏归一化诊断

**Files:**

- Create: `code/python/src/oer_aem/coverage_coordinates.py`
- Create: `code/python/tests/test_coverage_coordinates.py`
- Modify: `code/python/src/oer_aem/physics.py`
- Modify: `code/python/src/oer_aem/__init__.py`
- Modify: `code/python/tests/test_physics.py`

**Scope:** 只新增开发态四坐标适配器和严格覆盖度策略；现有正式五状态
求解入口仍保留`legacy_normalize`默认，不改C++桥、求解器或Gate阈值。

- [x] **Step 1: 写覆盖度坐标失败测试**

```python
def test_four_coordinates_reconstruct_unit_sum_full_coverages():
    reduced = np.array([0.25, 0.20, 0.18, 0.22])
    full = expand_independent_coverages(reduced)
    np.testing.assert_allclose(full, [0.15, 0.25, 0.20, 0.18, 0.22])
    assert reduce_full_coverages(full) == pytest.approx(reduced)


def test_invalid_reconstructed_eliminated_coverage_is_rejected():
    with pytest.raises(ValueError, match="theta_star"):
        expand_independent_coverages(np.array([0.4, 0.3, 0.2, 0.2]))
```

- [x] **Step 2: 确认红灯**

Run:

```bash
.venv/bin/python -m pytest code/python/tests/test_coverage_coordinates.py -q
```

Expected: collection fails with `ModuleNotFoundError: oer_aem.coverage_coordinates`.

- [x] **Step 3: 实现最小守恒坐标API**

API固定消去`theta_star`：独立坐标为
`[theta_ox, theta_OH, theta_O, theta_OOH]`，用
`theta_star = 1 - sum(independent)`重建。输入必须有限，满足边界与
总和容差`1e-8`；超界失败，不截断、不再归一化。

- [x] **Step 4: 写严格五状态和缩减RHS失败测试**

```python
def test_strict_rates_reject_off_manifold_state_hidden_by_legacy_normalization():
    params = initialize_oer_parameters()
    off_manifold = np.array([0.30, 0.50, 0.40, 0.36, 0.44, 1.45])
    legacy = elementary_rates(0.17, off_manifold, params)
    assert legacy.original_coverage_sum == pytest.approx(2.0)
    with pytest.raises(ValueError, match="sum"):
        elementary_rates(
            0.17, off_manifold, params, coverage_policy="strict"
        )


def test_reduced_rhs_matches_full_rhs_on_conservation_manifold():
    params = initialize_oer_parameters()
    full = np.array([0.15, 0.25, 0.20, 0.18, 0.22, 1.45])
    reduced = np.r_[reduce_full_coverages(full[:5]), full[5]]
    full_rhs = OERPhysics.oer_model(0.17, full, params)
    reduced_rhs = OERPhysics.reduced_oer_model(0.17, reduced, params)
    assert reduced_rhs[:4] == pytest.approx(full_rhs[1:5], abs=1e-12)
    assert reduced_rhs[4] == pytest.approx(full_rhs[5], abs=1e-12)
```

- [x] **Step 5: 确认测试因策略和RHS缺失而失败**

Run:

```bash
.venv/bin/python -m pytest \
  code/python/tests/test_physics.py::test_strict_rates_reject_off_manifold_state_hidden_by_legacy_normalization \
  code/python/tests/test_physics.py::test_reduced_rhs_matches_full_rhs_on_conservation_manifold -q
```

Expected: FAIL，分别指向未支持`coverage_policy`和未实现`reduced_oer_model`。

- [x] **Step 6: 实现最小严格策略和缩减RHS**

`elementary_rates(..., coverage_policy="legacy_normalize")`保留旧默认；
`coverage_policy="strict"`调用`validate_full_coverages()`。
`OERPhysics.reduced_oer_model()`重建五覆盖度，在`strict`策略下计算速率，
返回四个独立覆盖度导数和表面电位导数。

- [x] **Step 7: 比较四/五状态短轨迹和电流**

在同一`solve_ivp(LSODA, rtol=1e-9, atol=1e-11)`、同一`t_eval`和初值下积分。
四状态轨迹逐点重建后，要求全覆盖度、表面电位和总电流的最大差异
不超过`1e-7`，且两路均为有限值。

- [x] **Step 8: 运行目标和全量回归**

```bash
.venv/bin/python -m pytest \
  code/python/tests/test_coverage_coordinates.py \
  code/python/tests/test_physics.py -q
.venv/bin/python -m pytest code/python/tests -q
```

- [x] **Step 9: 只根据证据决定下一切片**

- 若RHS与轨迹均通过：把“四状态正式切换”列为下一个独立切片，本阶段
  仍不切换。
- 若RHS通过但轨迹失败：保留数值差异证据，停止正式切换。
- 若四坐标产生越界：报告积分器/坐标边界问题，不用截断或放宽守恒门掩盖。

**Observed decision at Task 5:** 内部物理状态的四/五坐标RHS与短轨迹等价，但从
`theta_star=1`的边界初值积分时，LSODA内部试探步产生约`-9.26e-8`的临时
覆盖度，严格四坐标策略按设计拒绝。因此保留开发态适配器，不切换正式
求解入口；下一切片应比较“仅严格守恒、输出边界验收”与正值坐标变换，不截断
负覆盖度。

### Task 6: LSODA内部试探与输出物理门分离

**Files:**

- Modify: `code/python/src/oer_aem/coverage_coordinates.py`
- Modify: `code/python/src/oer_aem/physics.py`
- Modify: `code/python/tests/test_coverage_coordinates.py`
- Modify: `code/python/tests/test_physics.py`

**Frozen design:** 四坐标RHS用`theta_star=1-sum(independent)`保证精确守恒，
但不在积分器内部试探点检查正值边界；只在`t_eval`输出轨迹上按`1e-8`原门
验收。不截断、不重归一化、不放宽阈值。

- [x] 先写失败测试：守恒重建接受有限的小幅负内部点且总和严格为1；严格
  输出验收必须拒绝同一越界点。
- [x] 确认红灯原因为`reconstruct_conserved_coverages()`和
  `validate_reduced_trajectory()`尚未实现。
- [x] 实现两层API：内部层只验证形状/有限值并精确重建；输出层对每个点
  调用既有`validate_full_coverages()`。
- [x] 让`reduced_oer_model()`仅在内部使用守恒重建，保持其他入口不变。
- [x] 从`theta_star=1`边界初值运行同配置LSODA四/五状态；要求两路成功、输出
  物理门通过，覆盖度/电位/总电流最大差不超过`1e-7`。
- [x] 运行目标测试、全量Python测试和差异审计；失败则停止四状态正式切换。

**Observed decision at Task 6:** 边界初值的四/五状态LSODA均成功；四状态
输出最小覆盖度为0，总和最大误差`2.22e-16`，两路最大覆盖度差
`2.30e-13`、表面电位差`9.29e-10 V`、总电流差`9.29e-11 A`。
边界数值问题已在不截断、不归一化、不改门的前提下闭环；下一步进入更长协议
等价性和灵敏度方向审计。
