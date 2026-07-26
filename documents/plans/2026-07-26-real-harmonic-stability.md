# Gate A4 Real Harmonic Stability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> `superpowers:subagent-driven-development` (recommended) or
> `superpowers:executing-plans` to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** 验证 FT2、FT3、FT4、FT8 的电位分辨复数谐波对合法降采样和记录
长度变化是否稳定，并以预注册门决定锁相特征能否进入正式精度比较。

**Architecture:** 完整原始记录是每个数据集的参考。输入变体只允许使用带
抗混叠滤波的 2×/4×降采样，以及分别删除两端 10% 的记录长度变体。基频
从完整记录冻结；候选与参考锁相结果只在共同有效电位区比较。四个数据集
相互独立，可用 8 个进程执行，但每个进程限制为一个 BLAS 线程。

**Tech Stack:** Python、NumPy、SciPy `resample_poly`、现有
`oer_aem.signal.lockin_harmonics`、CSV/JSON、pytest。

---

## 固定科学口径

| 项目 | 固定值 |
|---|---|
| 数据集 | FT2、FT3、FT4、FT8 |
| 谐波 | H1–H7 |
| 目标电位分辨率 | 0.025 V |
| 降采样 | full、2×、4×，使用 `resample_poly` |
| 记录长度 | full、trim_start_10pct、trim_end_10pct |
| 基频 | 每个数据集从 full 记录估计后冻结 |
| 可解析性 | 参考通道 RMS ≥参考 H1 RMS 的 2% |
| 强制通道 | H1–H3；H4–H7 仅在可解析时评价 |
| 幅值门 | 共同有效区 amplitude NRMSE ≤0.10 |
| 相位门 | 共同有效区 wrapped phase RMSE ≤0.10 rad |
| 峰位门 | 共同区内参考峰可见时 shift ≤0.025 V |
| 有效区门 | 共同有效点比例 ≥0.50 |
| 独立电位区间 | 共同电位跨度 / 0.025 V ≥10 |

Gate A4 PASS 要求所有数据集的所有强制比较通过。失败时保留原始数值，
不得删除 FT4、弱化 H1–H3、提高阈值或改用相位平移常数。

## Task 1：输入变体与比较指标

**Files:**
- Create: `code/python/scripts/validate_real_harmonic_stability.py`
- Test: `code/python/tests/test_real_harmonic_stability.py`

- [ ] **Step 1: 写输入变体失败测试**

测试应构造等间隔合成信号，要求：

```python
variants = build_variants(time, potential, current)
assert set(variants) == {
    "full", "downsample_2x", "downsample_4x",
    "trim_start_10pct", "trim_end_10pct",
}
assert len(variants["downsample_2x"]["time"]) == len(time) // 2
assert np.all(np.diff(variants["downsample_4x"]["time"]) > 0)
```

- [ ] **Step 2: 验证 RED**

Run:

```bash
.venv/bin/python code/python/scripts/run_tests.py \
  code/python/tests/test_real_harmonic_stability.py -q
```

Expected: 因模块或 `build_variants` 不存在而失败。

- [ ] **Step 3: 最小实现输入变体**

`build_variants()` 必须同时对电位和电流使用
`scipy.signal.resample_poly(..., up=1, down=2|4)`；时间轴由原始起点和
采样间隔重建。trim 变体只删除一端 10%，至少保留 32 个样本。拒绝非单调
时间轴和数组长度不一致。

- [ ] **Step 4: 写指标失败测试**

对已知复数包络检查：

```python
metrics = compare_lockin(reference, candidate, common_grid)
assert metrics["amplitude_nrmse"] == pytest.approx(0.0)
assert metrics["phase_rmse_rad"] == pytest.approx(0.0)
assert metrics["peak_shift_v"] == pytest.approx(0.0)
```

另用 `π-0.05` 与 `-π+0.05` 验证相位差为约 0.10 rad，而不是约 `2π`。

- [ ] **Step 5: 实现共同电位区比较**

先将 `complex` 包络按单调 DC 电位插值到共同网格，再由复数值计算 amplitude
和 phase；禁止直接线性插值相位。返回 amplitude NRMSE、wrapped phase
RMSE、peak shift、共同有效比例和独立电位区间数。

- [ ] **Step 6: 验证 GREEN**

运行 Task 1 测试，预期全部通过。

## Task 2：真实数据 Gate 与证据

**Files:**
- Modify: `code/python/scripts/validate_real_harmonic_stability.py`
- Modify: `code/python/tests/test_real_harmonic_stability.py`
- Create: `results/formal/harmonic_stability/gate-a4-<commit>/`

- [ ] **Step 1: 写门控失败测试**

构造一行 H2 `phase_rmse_rad=0.11` 的可解析结果，要求 `assess_gate()`
返回 FAIL；构造 H7 不可解析结果时，不因相位数值失败。

- [ ] **Step 2: 实现真实数据分析**

对每个数据集：

1. full 记录估计并冻结 `f0` 和扫描速率；
2. 对五种输入运行 `estimate_reference_phase()` 和
   `lockin_harmonics()`；
3. 分别比较 full vs 两种降采样、full vs 两种单端 trim；
4. 输出每个 dataset/variant/harmonic 一行 CSV；
5. JSON summary 写入阈值、通过状态、失败列表和输入文件哈希。

- [ ] **Step 3: 实现 8 进程入口**

主进程使用 `ProcessPoolExecutor(max_workers=min(8, os.cpu_count() or 1))`
按数据集和变体分发；启动前设置：

```text
OMP_NUM_THREADS=1
OPENBLAS_NUM_THREADS=1
MKL_NUM_THREADS=1
NUMEXPR_NUM_THREADS=1
```

worker 不写共享文件，只返回字典；CSV/JSON 由主进程排序后一次写入。

- [ ] **Step 4: smoke 与确定性检查**

先串行和 8 进程各运行一个数据集，要求 CSV 数值与排序一致。若 8 进程
wall time 没有改善，正式运行允许使用 4 进程，但 manifest 必须记录实际值。

- [ ] **Step 5: 正式运行与验收**

正式证据必须满足：

- 4 个数据集；
- 4 个候选变体 × 7 谐波 × 4 数据集 = 112 行；
- 所有必需指标有限；
- 每个输入文件 SHA-256 存在；
- commit、Python/NumPy/SciPy 版本和 worker 数存在；
- summary 与 CSV 的失败项一致。

## Task 3：项目状态和版本

**Files:**
- Modify: `documents/project/PROJECT_SUMMARY.md`
- Modify: `documents/project/WORK_STATUS.md`
- Modify: `documents/corrections/项目纠错.md`
- Modify: `results/README.md`

- [ ] **Step 1: 按真实结果更新 Gate A4**

PASS 只表示信号层稳定，可以进入 A5；不写成反演精度提高。FAIL 时列出具体
数据集、变体和谐波，并降低对应局部特征的使用范围。

- [ ] **Step 2: 完整验证**

```bash
.venv/bin/python code/python/scripts/run_tests.py code/python/tests -q
.venv/bin/python -m pytest code/web/tests/backend -q
.venv/bin/python code/python/scripts/audit_repository_layout.py
git diff --check
```

- [ ] **Step 3: 提交和推送**

只提交 A4 代码、测试、正式证据和对应文档；不提交原始数据副本、临时 smoke
或本机环境秘密。

## 压力测试结论

1. 直接抽点会混叠，必须使用抗混叠降采样。
2. 前半段与后半段没有共同电位范围，不能用于峰位稳定性门。
3. 截断记录后重新估计基频会把频率分辨率误差混入锁相测试，因此冻结 full
   基频。
4. 相位必须在复数域插值并用环绕差比较。
5. H4–H7 低于 2% 时只保留诊断，不能以噪声相位使 Gate 失败。
6. 8 workers 是吞吐起点，不是科学参数；worker 数变化不得改变结果。
7. 任一数据集缺少共同有效区或少于 10 个独立电位区间时，Gate FAIL，
   不通过放宽滤波边缘掩盖。
