# Potential-Resolved Complex Harmonics & Signed Sensitivity

> **面向 agent 执行者。** 本文件描述本轮（2026-07-26 起）需要实现的四个代码改动及其验收标准。所有改动在 `code/python/src/oer_aem/` 和 `code/python/scripts/` 中，不涉及前端或 API。

**前置状态：**
- 代码基线：`b8b176c`（上一轮架构验证报告已推送）
- 70 测试通过（Mac），Legion 验收环境 Python 3.11.2 + NumPy 2.2.6 + SciPy 1.16.3 + Optuna 4.9.0
- M0 基线模型已验证，M1 被拒绝，Complex-SNR 通过多数规则但 H1-H3 恶化 +38.8%

**本轮目标：** 四个改动组合成一个版本，在相同计算预算下，真实数据的热力学参数 CV 不恶化、H1-H3 RMSE 不恶化、合成恢复误差不上升。若任一条件不满足，记录失败并将本轮改动标记为实验分支。

**数据范围：** 仅使用高基频数据（FT2/FT3/FT8，f0=5Hz）+ 合成目标。FT4（f0=1Hz）因电位分辨率的物理限制排除。

---

## 改动 1：软件锁相放大 → 电位分辨复数谐波

### 动机

当前 `extract_complex_harmonics()` 对整个信号做一次全局 FFT，每个谐波只得到一个复数系数。这丢失了谐波幅值和相位沿电位轴的变化信息。上一轮 Complex-SNR 的 H1-H3 恶化可能与此有关——全局复数系数无法捕捉电位依赖的结构化差异。

### 方法：软件锁相放大器（Software Lock-In Amplifier）

不使用 STFT（计算量大、窗口参数敏感）。改为模拟物理锁相放大器的信号处理链：

```
signal → [× sin(2π·h·f0·t)] → lowpass → I_h(t)
signal → [× cos(2π·h·f0·t)] → lowpass → Q_h(t)
A_h(t) = sqrt(I_h² + Q_h²)
φ_h(t) = atan2(Q_h, I_h)
```

低通滤波的截止频率控制电位分辨率。

### 接口

**新增函数** `code/python/src/oer_aem/signal.py`：

```python
def lockin_harmonics(
    signal: np.ndarray,
    t: np.ndarray,
    f0: float,
    harmonics: Sequence[int] = (1, 2, 3, 4, 5, 6, 7),
    potential_resolution: float = 0.025,  # V, 自适应计算时作为下限
) -> dict:
    """
    Returns
    -------
    dict with keys:
        amplitude: list of np.ndarray  # 每个谐波的 A(t)，长度同 signal
        phase: list of np.ndarray      # 每个谐波的 φ(t)，长度同 signal
        complex: list of np.ndarray    # I + jQ
        snr: list of np.ndarray        # 局部 SNR 估计
        t: np.ndarray                  # 时间轴
    """
```

**自适应 potential_resolution 计算：**
```python
def _adaptive_resolution(
    n_points: int, f0: float, scan_rate: float,
    min_resolution: float = 0.010,  # 10 mV
    max_resolution: float = 0.050,  # 50 mV
) -> float:
    """基于扫描速率和频率自适应计算电位分辨率。

    核心约束：低通滤波器的时间常数必须 << 扫描一个分辨率宽度的时间。
    resolution = max(min_resolution, min(max_resolution, scan_rate / (f0 * 4)))
    """
```

**低通滤波器设计：**
```python
def _design_lockin_lowpass(
    fs: float,        # 采样率
    f0: float,        # 基频
    harmonic: int,    # 谐波次数
    resolution: float, # 电位分辨率 (V)
    scan_rate: float,  # 扫描速率 (V/s)
) -> tuple:
    """设计 Butterworth 低通滤波器。

    截止频率 fc = scan_rate / resolution  # 单位时间内扫过 resolution 伏特
    但必须 < 2 * f0（避免混入基频分量），取 min(fc, 0.5 * f0)。
    阶数 = 4，零相位（forward-backward filtfilt）。
    """
```

### 验收

- 对纯正弦信号（已知 A 和 φ），恢复的 A(t) 在稳态段波动 < 1%，φ(t) 波动 < 0.02 rad
- 对合成 FTacV 信号，H1-H3 的 A(E) 和 φ(E) 曲线平滑（无不合理的跳变）
- 采样率或记录长度变化时，电位分辨曲线的峰位漂移 < 5 mV
- 现有 `extract_complex_harmonics` 和 `extract_harmonics` 的测试继续通过（不修改旧路径）

---

## 改动 2：全量实验数据点参与特征网格

### 动机

当前 `InversionConfig.e_grid` 将实验电位轴降采样到 200 点。这可能导致 onset 附近、peak 位置等关键特征的插值误差。上一轮 residual contract 显示全量网格与裁剪网格的 bias_hi 有细微差异（如 FT2: full=-0.0015 vs trimmed=-0.0020），说明降采样引入了微小但系统性的偏差。

### 改动

**`code/python/src/oer_aem/inversion.py`：**

`e_grid` 属性改为返回全量后 discard 网格：

```python
@property
def e_grid(self) -> np.ndarray:
    """Full post-discard potential grid — no downsampling."""
    return self.tdc[self.discard_index :]
```

`feature_grid_size` 改为计算属性（保持向后兼容，不破坏现有引用）：

```python
@property
def feature_grid_size(self) -> int:
    return self.e_grid.size
```

构造 `InversionConfig` 时不再需要传入 `feature_grid_size`，该参数保留但设置默认 sentinel `0` 表示"自动计算为全量"。

**`code/python/scripts/residual_diagnostics.py`：**

去掉 trimmed grid 行，只输出 full grid。CSV 输出从 8 行（4 数据集 × 2 网格）变为 4 行。

**波及脚本：** 以下脚本中移除显式 `feature_grid_size=XXX` 传参：
- `code/python/scripts/compare_feature_objectives.py`（当前 `feature_grid_size=64`）
- `code/python/scripts/compare_reconstruction_model.py`（当前 `feature_grid_size=64`）
- `code/python/scripts/run_architecture_validation.py`（当前 `feature_grid_size=200/32`）
- `code/python/scripts/staged_inversion.py`（当前 `feature_grid_size=200`）
- `code/python/scripts/diagnose_high_current_penalty.py`（当前 `feature_grid_size=200`）
- `code/python/scripts/sweep_ru.py`（当前 `feature_grid_size=200`）

`code/python/src/oer_aem/importance.py` 中 `feature_grid_size=200` 一并移除。

### 验收

- 所有现有测试继续通过（grid 大小变化可能影响 `assess_fit_quality` 的 sigma-RMSE 计算，需同步更新）
- `residual_diagnostics.py` 输出从 8 行变为 4 行，`grid` 列只有 `"full"`
- 任一脚本构造 `InversionConfig` 时不传 `feature_grid_size` 也能正常运行
- 扫描速率相对误差仍 < 5e-4

### 性能影响

目标函数评估点数从 200 → ~6000（30×），TPE 单次 trial 耗时增加。Legion 上 50 trials × 8 workers 的 wall time 预估从 ~2.5h 增加到 ~4-6h。接受此代价。

---

## 改动 3：带符号敏感矩阵列

### 动机

当前 `identifiability.py` 的 `classify_columns` 使用 `np.linalg.norm(matrix, axis=0)` 判断敏感性，丢失了正负号信息。无法判断两个参数对同一特征是"同向推"还是"对向拉"——这是识别补偿效应的关键信息。

### 改动

**`code/python/src/oer_aem/identifiability.py`：**

1. `sensitivity_correlation` 保持使用归一化矩阵（已有符号信息，因为归一化除的是正数 norm）
2. 新增函数：

```python
def signed_sensitivity_table(
    names: Sequence[str],
    feature_names: Sequence[str],
    matrix: np.ndarray,
) -> list[dict]:
    """返回每对 (feature, parameter) 的带符号敏感度。

    输出格式：
    [{"feature": "H1_amplitude", "parameter": "G_OH", "sensitivity": +0.042}, ...]
    """
```

3. `classify_columns` 增加可选输出：对每个 coupled 参数，标注它与谁耦合以及耦合方向（同号 = 补偿风险高，异号 = 可区分）。

**`code/python/scripts/run_architecture_validation.py`：**

输出中新增 `signed_sensitivity.csv`（替代或补充当前 `sensitivity_matrix.csv`），列：
- `feature_name`
- `parameter_name`
- `sensitivity`（带符号）
- `abs_sensitivity`
- `direction`（`"positive"` / `"negative"`）

### 验收

- `classify_columns` 对完全反相关的两列仍正确标记为 coupled
- 带符号矩阵中，已知存在补偿的参数对（如 gamma/A、gamma/Cdl、k0_1/k0_2）应呈现相反符号
- 现有 `test_identifiability.py` 测试通过（可能需要补充 signed 路径的测试）

---

## 改动 4：Combined 目标函数（Complex-SNR + H1-H3 包络保护项）

### 动机

上一轮 Complex-SNR 的 H1-H3 RMSE 恶化 +38.8%，不能无条件替换 legacy。本轮创建一个新的 `feature_mode="combined"`，在 Complex-SNR 基础上显式加入 H1-H3 幅值包络保护项。

### 改动

**`code/python/src/oer_aem/inversion.py`：**

新增 `feature_mode="combined"`，目标函数结构：

```python
loss_total = (
    w_dc * loss_dc +                          # DC 形状（权重 ~0.3）
    w_complex * loss_complex_harmonics +       # SNR 加权复数谐波（权重 ~0.4）
    w_envelope * loss_h1h3_envelope +          # H1-H3 幅值包络保护（权重 ~0.2）
    w_phase * loss_phase +                     # 环绕相位（权重 ~0.1）
    loss_physical                               # 物理惩罚（不加权）
)
```

`loss_h1h3_envelope` 使用电位分辨的锁相放大器幅值（改动 1），对 H1-H3 的 A(E) 逐点计算 RMSE，归一化方式同 legacy。

权重可配置但提供合理默认值。目的是让 H1-H3 幅值包络不被 Complex-SNR 的全局复数系数稀释。

**`code/python/scripts/compare_feature_objectives.py`：**

比较模式从 2 个扩展到 3 个：`legacy`、`complex_snr`、`combined`。

### 验收

- `feature_mode="combined"` 的目标函数能正常计算并返回分量
- 在合成恢复测试中，combined 的恢复误差不高于 legacy
- 在真实数据 3-trial smoke run 中，combined 的 H1-H3 RMSE 不高于 legacy（初步验证保护项有效）
- `test_inversion.py` 中新增 `feature_mode="combined"` 的 loss 分量测试

---

## 执行顺序

```
Step 1: 在 Legion 上建新工作树，拉 b8b176c，确认环境
Step 2: 实现改动 1（锁相放大）+ 测试
Step 3: 实现改动 2（全量数据点）
Step 4: 实现改动 3（带符号敏感性）
Step 5: 实现改动 4（combined 目标函数）
Step 6: Mac 上跑全量测试，确认 70+ 通过
Step 7: push GitHub
Step 8: Legion 拉取 → 运行 formal 比较（3 modes × 3 datasets × 3 seeds × 50 trials）
Step 9: 结果回传 → 报告 → 决策
```

---

## 验收门控（Go/No-Go）

Formal 计算完成后，以下条件全部满足才将本轮改动合并为主线：

| # | 条件 | 量化标准 |
|---|------|----------|
| 1 | 热力学参数 CV 不恶化 | G_OH、G_O、scaling 的 CV ≤ 上轮 combined-SNR（0.058, 0.030, 0.033） |
| 2 | H1-H3 RMSE 不恶化 | combined 的 common H1-H3 RMSE ≤ legacy 的 0.2084 |
| 3 | 合成恢复误差不上升 | combined 合成恢复误差 ≤ 0.1612 |
| 4 | 计算可复现 | 70+ 测试通过，扫描速率误差 < 5e-4 |

任一条件不满足 → 记录失败，本轮改动保留为实验分支，不回退但也不合并为主推荐。

---

## 波及文件清单

| 文件 | 改动类型 | 说明 |
|------|----------|------|
| `code/python/src/oer_aem/signal.py` | 新增 | `lockin_harmonics()` + 辅助函数 |
| `code/python/src/oer_aem/features.py` | 新增 | 电位分辨特征向量构建 |
| `code/python/src/oer_aem/inversion.py` | 修改 | `e_grid` 全量、`feature_mode="combined"`、loss 分量 |
| `code/python/src/oer_aem/identifiability.py` | 修改 | `signed_sensitivity_table()` |
| `code/python/src/oer_aem/importance.py` | 修改 | 移除 `feature_grid_size=200` |
| `code/python/tests/test_features.py` | 修改 | 新增锁相放大恢复测试 |
| `code/python/tests/test_inversion.py` | 修改 | 新增 combined mode 测试 |
| `code/python/tests/test_identifiability.py` | 修改 | 新增带符号敏感矩阵测试 |
| `code/python/scripts/residual_diagnostics.py` | 修改 | 只输出 full grid |
| `code/python/scripts/compare_feature_objectives.py` | 修改 | 3 modes, 移除 feature_grid_size |
| `code/python/scripts/compare_reconstruction_model.py` | 修改 | 移除 feature_grid_size |
| `code/python/scripts/run_architecture_validation.py` | 修改 | 移除 feature_grid_size, 输出 signed_sensitivity |
| `code/python/scripts/staged_inversion.py` | 修改 | 移除 feature_grid_size |
| `code/python/scripts/diagnose_high_current_penalty.py` | 修改 | 移除 feature_grid_size |
| `code/python/scripts/sweep_ru.py` | 修改 | 移除 feature_grid_size |

---

## 环境与计算

- **代码工作**：Mac（`/Users/liushiyu/OER-FTAcV`）
- **计算执行**：Legion WSL2 Debian-Bookworm
- **工作树**：基于 `b8b176c` 新建（`/home/lsy/OER-FTAcV-run-<commit>`）
- **Python**：`/home/lsy/OER-FTAcV-run-8cf26be/.venv/bin/python`（已验证环境）
- **测试入口**：`.venv/bin/python code/python/scripts/run_tests.py code/python/tests -q`
- **计算预算**：3 modes × 3 datasets × 3 seeds × 50 trials = 1350 trials（上轮 2 modes × 4 datasets = 1200 trials），预估 Legion wall time ~5h（含 M0/M1 比较）

---

## 压力测试

### 风险 1：锁相放大对低基频数据的电位分辨率不足 ✅ 已排除

**原问题**：FT4（f0=1Hz）的 fc < f0 → 分辨率 > 1V，电位分辨无效。

**决策**：本轮只用高基频数据（FT2/FT3/FT8，f0=5Hz）。FT4 不进入 formal 比较。对于 5Hz，fc=4Hz，scan_rate≈1V/s → 分辨率 ~250mV → ~4 独立点。足够。

### 风险 2：全量数据点导致 TPE 目标函数计算量膨胀

**问题**：e_grid 从 200 点 → ~6000 点，目标函数每轮评估需计算 6000 点的 DC + 谐波残差。

**实际影响**：检测发现 ODE 正演（`forward_current`）是瓶颈（~50ms/次），网格上做 200 或 6000 点的向量减法和归一化仅 ~0.1ms。增量可忽略。

**结论**：不阻塞。全量网格不显著增加单次评估耗时。

### 风险 3：combined 模式的权重调节可能需多次试错

**问题**：`loss_complex_harmonics`（SNR 加权复数）和 `loss_h1h3_envelope`（幅值包络）的权重需要平衡。权重不当可能导致一方主导、另一方无效。

**缓解**：
1. 默认权重基于上一轮数据校准：w_envelope 初始设为使 `w_envelope * loss_h1h3_envelope` 约等于 `w_complex * loss_complex_harmonics / 3`（即包络项占总谐波损失的 ~25%）。
2. 权重可通过 `InversionConfig` 参数覆盖，方便调试。
3. 3-trial smoke run 先验证两条损失都不触及其边界或失效。

**结论**：低风险，可通过 smoke run 快速校准。

### 风险 4：`feature_grid_size` 移除破坏现有脚本

**问题**：7 个脚本当前显式传 `feature_grid_size=XXX`。如果直接删除构造参数，调用会因多余关键字而失败。

**缓解**：保留 `feature_grid_size` 作为 `InversionConfig` 的可选参数（默认 `0` = 全量），显式传入的值被忽略并记录 warning。这样现有脚本无需修改即可运行，后续逐步清理。

**结论**：向后兼容方案已就绪。

### 风险 5：带符号敏感矩阵的信息量可能不足以判断补偿

**问题**：当前敏感矩阵 21 行 × 13 列，特征数量有限。加上符号后，某些参数对的 sign pattern 可能不够清晰。

**缓解**：
1. 带符号矩阵是诊断工具，不要求严格的统计显著性。
2. 输出中显式标注低灵敏度条目的不可靠性。
3. 结合上一轮的 CV 分析和参数分类交叉验证。

**结论**：不阻塞。作为辅助诊断输出足够。

### 风险 6：Legion 计算耗时

**问题**：3 modes × (1 synthetic + 3 real) × 3 seeds = 36 row-groups × 50 trials = 1800 TPE 研究。

**实际估算**：上轮 2 modes 在 4 datasets 上 9162s。本轮 3 modes × 3 datasets → 预估 ~10300s ≈ 2.9h。含 M0/M1 比较 → ~5h。单次 ODE 求解占 >95% 耗时。

**结论**：~5h 在 Legion 上 tmux 后台运行，可接受。

### 风险 7：改动 1 和改动 4 的交互——锁相放大输出需要匹配 combined 目标函数

**问题**：锁相放大给出 `A(t)` 和 `φ(t)`（在模拟时间网格上），而 combined 目标函数需要在 `e_grid`（电位网格）上比较实验与模拟。两者坐标系不同。

**缓解**：模拟的 `t_span → tdc` 映射是线性的（恒定扫描速率），所以 `A(t)` 可直接按 tdc 索引映射到电位。实验谐波按相同的 `tdc` 插值。两者在同一个电位轴上对齐。

**结论**：不阻塞，需在 `extract_features` 中处理映射逻辑。
