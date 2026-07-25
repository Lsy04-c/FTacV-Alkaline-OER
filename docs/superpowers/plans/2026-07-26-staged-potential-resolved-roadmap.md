# OER-FTAcV 分阶段研究与实施路线

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to execute this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Do not start a later phase until the preceding gate is recorded as PASS.

**Goal:** 在不牺牲现有低阶谐波拟合、合成参数恢复和热力学参数稳定性的前提下，判断电位分辨复数谐波是否能为 OER-FTAcV 反演提供可重复的新信息。

**Architecture:** 将基线冻结、锁相信号验证、网格收敛、带符号敏感性和组合目标函数拆成相互独立的阶段。每个阶段形成独立证据、提交和 Go/No-Go 决策；失败阶段停止后续依赖项，避免把多个改动混入一次正式反演。

**Tech Stack:** Python 3.11、NumPy、SciPy、Optuna、pytest；Mac 负责代码、单元测试、文档与 Git，Legion WSL2 使用现有已验证环境执行长时间计算。

---

## 1. 当前判断

### 1.1 研究方向

全局 FFT 将每个谐波压缩成一个复数系数，无法表达幅值和相位沿电位轴的变化。电位分辨复数谐波 \(Z_h(E)\) 有希望保留这些信息，但只有在以下条件同时成立时才能进入反演：

1. 幅值和相位具有明确、统一的物理参考；
2. 结果对采样率、记录长度和滤波边缘稳定；
3. 局部特征增加的是独立信息，而非滤波相关点的伪重复；
4. 新目标函数的权重在正式真实数据评价前已经冻结；
5. 与 legacy、Complex-SNR 的比较使用同一基线、同一数据和同一计算预算。

### 1.2 当前工作树

当前 HEAD 为 `b8b176c`，但工作树中已有未提交的实验性改动，涉及：

- `python/oer_aem/signal.py`
- `python/oer_aem/inversion.py`
- `python/oer_aem/identifiability.py`
- `python/tests/test_features.py`
- `python/tests/test_inversion.py`

这些改动同时引入了锁相、full-grid、combined 和 signed sensitivity 的部分实现。它们不是可信基线，也尚未通过本路线的阶段门控。后续 agent 必须先记录并审计这些改动，禁止直接将其作为正式结果提交或在 Legion 上开展 formal inversion。

### 1.3 已确认的基线矛盾

`docs/architecture_validation_report.md` 仍声明正式比较使用 12 points/cycle。现有脚本部分已经改为 32 points/cycle，但正式 CSV 的旧字段和旧结果不足以证明 32 点重跑已完成。因此以下旧数值只能作为历史记录，不能作为新阶段的绝对验收阈值：

- synthetic recovery error：`0.2513 → 0.1612`
- common H1–H3 RMSE：`0.2084 → 0.2893`
- M1：仅 `1/4` 数据集通过，已拒绝

---

## 2. 全局规则

### 2.1 阶段隔离

每个阶段只改变一个科学变量：

| 阶段 | 唯一允许变化的变量 | 禁止同时变化 |
|---|---|---|
| Phase 0 | 基线采样与证据一致性 | 特征、网格、权重、模型 |
| Phase 1 | 锁相信号提取 | 反演、full-grid、combined |
| Phase 2 | 特征网格密度 | 特征定义、损失权重 |
| Phase 3 | 敏感度的符号计算与报告 | 优化目标、参数边界 |
| Phase 4 | 目标函数组合方式 | 网格、数据集、预算、权重校准集 |
| Phase 5 | 正式评价 | 任何代码或配置调参 |

一旦某阶段 FAIL，停止依赖它的后续阶段。保留证据和实验分支，不用后续调参掩盖失败。

### 2.2 计算与环境

- Mac：代码修改、快速测试、文档、Git。
- Legion：正式数值计算。
- Legion 使用已有环境：Python 3.11.2、NumPy 2.2.6、SciPy 1.16.3、Optuna 4.9.0。
- 不安装或切换 NumPy；每份结果记录实际环境版本。
- 长时间计算启动后，每隔至少 20 分钟按北京时间进行一次真实检查。
- 检查间隔不足 20 分钟时，不访问远端进程，也不声称已经检查。
- 阶段成功后先验收输出，再启动下一阶段；阶段失败后停止后续计算。

### 2.3 数据与泄漏控制

- Phase 1 检查 FT2、FT3、FT4、FT8，不预先排除 FT4。
- 只有客观的分辨率、相位稳定性或边缘污染证据才能排除数据集。
- 正式评价使用的数据不得用于选择 combined 权重。
- 实验权重只能从实验信号本身的预先定义统计量产生，不能随候选模拟参数变化。
- 没有重复实验时，不把局部 SNR 解释为真实实验不确定度。
- 所有正式模式使用相同数据、种子、trial 数、参数边界、初始条件和失败惩罚。

### 2.4 Git 与文档

- 每个通过验证的独立阶段形成一个逻辑提交并推送 GitHub。
- 提交前运行该阶段测试和全量测试。
- 结果文件必须包含 commit、配置、环境、数据集、随机种子和输出校验信息。
- agent 工作交接文档只保存在本机，不提交 GitHub。
- 不读取、复制或提交 `docs/environment_resolved_state.md` 中的敏感值。

### 2.5 预注册的非劣界限

以下界限在 Phase 0 基线重算后冻结。若 Phase 0 暴露量纲或统计定义错误，应先修正规则并记录原因，然后再启动任何新方法；正式结果生成后不得修改界限。

| 指标 | 非劣条件 | 说明 |
|---|---:|---|
| synthetic recovery | 新方法多种子中位误差 / 配对 legacy ≤ 1.05 | 允许最多 5% 相对恶化 |
| common H1–H3 RMSE | 新方法配对 pooled RMSE / legacy ≤ 1.05 | 每个数据集同时报告，不用平均值隐藏单组崩溃 |
| 热力学参数稳定性 | 三个参数的 CV ratio 中位数 ≤ 1.10，且任一参数 ≤ 1.25 | CV 分母接近零时改报稳健尺度，不强算 CV |
| boundary hits | 新方法总数不高于 legacy；任一核心热力学参数不得新增持续边界命中 | “持续”指超过一半种子命中同一边界 |
| 失败率 | 新方法失败研究数不高于 legacy，ODE/Tafel failure rate 增量 ≤ 1 个百分点 | 同时报绝对计数 |
| runtime | median wall time / legacy ≤ 2.0 | 超过两倍需证明信息增益足以抵偿 |

“通过”要求满足全部核心条件。优越性结论另需配对置信区间或全部种子方向一致；仅达到非劣不能写成“精度提高”。

---

## 3. Phase 0：冻结可信基线

**目的：** 建立后续所有比较唯一可信的代码、配置和结果基线。

**允许修改：**

- `scripts/compare_feature_objectives.py`
- `scripts/residual_diagnostics.py`
- `scripts/build_validation_manifest.py`
- `docs/architecture_validation_report.md`
- `results/architecture_validation/`
- 与基线证据字段直接相关的测试

### Task 0.1：审计未提交实验改动

- [ ] 运行 `git status --short`，保存受影响文件清单。
- [ ] 运行 `git diff --check`，确认不存在冲突标记或空白错误。
- [ ] 将每项改动标注为 Phase 1、2、3 或 4，不把它们混入 Phase 0。
- [ ] 在不丢失用户工作、不使用 destructive reset 的前提下，为 Phase 0 建立干净、可追踪的执行状态。

**验收：** Phase 0 使用的代码不包含 lock-in、full-grid、combined 或 signed-sensitivity 行为变化。

### Task 0.2：统一采样证据

- [ ] 确认正式基线的 `points_per_cycle`，推荐固定为 32；如果 H7 的 Nyquist 或稳定性测试不通过，则先提高采样，不得降低到 12。
- [ ] 将 `points_per_cycle` 写入 residual、feature objective、reconstruction 和 manifest 的每一行或每一研究记录。
- [ ] 为缺少 `points_per_cycle` 字段的旧 CSV 设置验证失败，不允许 manifest 把它识别为新基线。
- [ ] 运行：

```bash
python scripts/run_tests.py python/tests/test_baseline_audit.py \
  python/tests/test_residual_diagnostics.py \
  python/tests/test_inversion.py -q
```

**预期：** 全部通过；证据文件缺少采样字段时测试明确失败。

### Task 0.3：重算同构基线

- [ ] 使用 legacy 和 Complex-SNR 两个模式。
- [ ] 对 synthetic、FT2、FT3、FT4、FT8 使用完全相同的种子、trial 数和采样配置。
- [ ] smoke run 只验证流程，不参与科学结论。
- [ ] formal run 前生成冻结配置和预计研究数。
- [ ] formal run 后核对实际行数、唯一键、失败数和采样字段。

**Gate 0 — PASS 条件：**

- 报告、CSV、manifest 对 `points_per_cycle` 的记录一致；
- 同一模式和数据集不存在重复或缺失的 `(dataset, mode, seed)`；
- 所有正式结果能追溯到同一 commit 和冻结配置；
- 基线测试在 Mac 和 Legion 环境均通过；
- 旧 12-point 数值不再作为新路线的验收阈值。

**FAIL 动作：** 停止 Phase 1，修复证据生成链；不得用手工修改报告数值代替重算。

---

## 4. Phase 1：锁相信号层验证

**目的：** 在不运行反演的情况下，证明电位分辨复数谐波是定义清晰且数值稳定的观测量。

**允许修改：**

- `python/oer_aem/signal.py`
- 新建 `python/oer_aem/lockin.py`（若独立模块能减少 `signal.py` 职责）
- `python/tests/test_features.py`
- 新建 `scripts/validate_potential_resolved_harmonics.py`
- 新建 `results/potential_resolved_harmonics/`

### Task 1.1：冻结 I/Q 与相位约定

采用应用电位参考相位 \(\theta_E(t)\)，定义：

\[
Z_h(t)=2\,LPF\{[i(t)-\bar{i}]e^{-j h\theta_E(t)}\},
\quad A_h(t)=|Z_h(t)|,\quad \phi_h(t)=\arg Z_h(t)
\]

- [ ] API 必须显式接收 `reference_phase` 或等价的应用电位参考，禁止隐式依赖数组 `t=0`。
- [ ] 幅值实现包含混频后的因子 2。
- [ ] `complex`、`amplitude` 和 `phase` 必须满足 `amplitude == abs(complex)`、`phase == angle(complex)`。
- [ ] 相位差使用环绕差 `angle(exp(1j * delta))`。

### Task 1.2：定义滤波和有效区域

- [ ] 明确低通滤波器类型、阶数、截止频率和零相位处理。
- [ ] 截止频率必须同时满足谐波隔离和期望电位分辨率，禁止使用固定 `scan_rate=1.0 V/s` 默认值代表真实数据。
- [ ] 返回 `fc_used`、`effective_resolution_v`、`edge_trim_samples` 和 `valid_mask`。
- [ ] 正式评价仅使用有效区域，不把 filtfilt 边缘当作信号特征。
- [ ] 检查时间轴严格递增、近似等间隔、输入长度满足滤波 padding。

### Task 1.3：定义局部噪声和 SNR

第一版局部 SNR 只用于诊断，不进入反演权重。定义必须包含：

- 信号幅值的局部估计；
- 噪声来自预先指定的邻频带或重复轨迹，不来自待优化模拟残差；
- 窗口宽度和边缘处理；
- SNR floor、上限和无效值处理；
- 权重冻结规则。

若当前数据无法支持可信局部噪声估计，输出 `snr_status="diagnostic_only"`，Phase 4 暂不使用局部 SNR 权重。

### Task 1.4：合成信号验证

- [ ] 测试单一余弦的幅值、相位和因子 2。
- [ ] 测试 H1–H7 多谐波叠加，确认互不串扰。
- [ ] 测试已知缓变幅值包络和相位包络。
- [ ] 测试整体时间平移但应用电位参考同步平移时，结果不变。
- [ ] 测试采样率和记录长度变化。
- [ ] 测试 Nyquist、非均匀时间轴、短序列和非法谐波输入。
- [ ] 运行：

```bash
python scripts/run_tests.py python/tests/test_features.py -q
```

### Task 1.5：四个真实数据集诊断

- [ ] 对 FT2、FT3、FT4、FT8 输出 H1–H7 的幅值、相位、有效区域和实际分辨率。
- [ ] 比较至少两种合法采样密度或重采样设置。
- [ ] 记录峰位漂移、相位中位差、有效独立区间数和边缘丢失比例。
- [ ] 不因 `f0=1 Hz` 自动排除 FT4。

**Gate 1 — PASS 条件：**

- 纯信号稳态幅值相对误差 ≤ 3%，环绕相位误差 ≤ 0.04 rad；
- H1–H7 在满足 Nyquist 时均通过幅值与相位恢复测试；
- 合法采样变化下主要幅值峰位漂移 ≤ 5 mV，或给出数据物理分辨率不允许达到 5 mV 的明确证据并预注册替代阈值；
- 时间平移不改变应用电位参考相位；
- 有效区域和边缘丢失有机器可读记录；
- FT4 的保留或排除由实测证据决定。

**FAIL 动作：** 不进入反演。保留全局 FFT 路径，记录哪类数据不支持电位分辨相位。

---

## 5. Phase 2：网格收敛实验

**目的：** 找到足以保持反演结果稳定的最小网格，避免 full-grid 伪重复。

**允许修改：**

- `python/oer_aem/inversion.py` 中网格构造和损失归一化
- `python/tests/test_inversion.py`
- `scripts/residual_diagnostics.py`
- 新建 `scripts/compare_feature_grids.py`

### Task 2.1：修正网格接口

- [ ] 保留 `feature_grid_size: int | None` 作为配置字段。
- [ ] `None` 表示自动选择；正整数表示显式网格。
- [ ] 使用不同名称的只读属性报告最终大小，例如 `resolved_feature_grid_size`。
- [ ] 保留 full 和 trimmed residual 诊断，不删除对照行。

### Task 2.2：消除点数尺度效应

- [ ] DC、各谐波包络和相位损失分别采用 mean residual 或预先定义的有效自由度归一化。
- [ ] 网格点数改变时，物理惩罚和 Tafel 项的相对权重保持不变。
- [ ] `assess_fit_quality` 使用真实残差项数，而不是把相关点全部视为独立观测。

### Task 2.3：收敛比较

- [ ] 比较 64、128、256、full。
- [ ] 先用 synthetic 和一个代表性真实数据集做 smoke。
- [ ] 对通过 smoke 的网格运行固定预算、多种子比较。
- [ ] 输出参数偏移、objective 偏移、H1–H3 RMSE、峰位偏移、运行时间和有效独立点数。

**Gate 2 — PASS 条件：**

- 连续两级网格的 G_OH、G_O 和 scaling 参数相对变化均 ≤ 2%，k0 的 log10 值变化均 ≤ 0.10；
- 连续两级网格的 H1–H3 RMSE 相对变化 ≤ 2%，主要峰位变化 ≤ 5 mV；
- 目标函数各分量比例不因点数机械变化；
- 选择满足条件的最小网格，而非默认 full。

**FAIL 动作：** 保留当前 200 点基线，调查插值、电位映射或损失尺度；不进入 combined。

---

## 6. Phase 3：带符号敏感性

**目的：** 从特征产生阶段保留参数扰动方向，识别耦合方向及低敏感度参数。

**允许修改：**

- `python/oer_aem/importance.py`
- `python/oer_aem/identifiability.py`
- `python/tests/test_importance.py`
- `python/tests/test_identifiability.py`
- `scripts/run_architecture_validation.py`

### Task 3.1：从源头计算符号

对标量特征使用中心差分：

\[
S_{ij}=
\frac{f_i(\theta_j+\delta_j)-f_i(\theta_j-\delta_j)}
{2\delta_j}
\]

- [ ] 明确线性参数和 log10 参数的 \(\delta_j\) 含义。
- [ ] 参数边界附近使用对称可行扰动；无法对称时标记为不可靠，禁止静默改成绝对值。
- [ ] 形状特征必须先定义有方向的标量投影，再计算符号。
- [ ] 保留原始有符号矩阵，同时另算绝对值用于排序。

### Task 3.2：正确解释耦合

- [ ] `|corr|` 接近 1 表示耦合，无论正负。
- [ ] 正负号只描述两参数在特征空间的相对方向和补偿方式。
- [ ] 低列范数参数标记为 unresolved，不解释其相关符号。
- [ ] 不把 gamma/A、gamma/Cdl 或 k0 参数对的预期符号写成验收标准。

### Task 3.3：输出证据

- [ ] 输出 long-form `signed_sensitivity.csv`。
- [ ] 输出参数对相关表，包括 `correlation`、`abs_correlation` 和可靠性。
- [ ] manifest 记录扰动步长、参数尺度、特征定义和 commit。

**Gate 3 — PASS 条件：**

- 人工构造的正相关、负相关和零敏感矩阵分类正确；
- 中心差分符号在减半扰动步长后稳定；
- 上游未使用 `abs`、norm 或距离覆盖符号；
- 低敏感度结果不会被解释为可靠耦合。

**FAIL 动作：** 保留 unsigned 诊断，不用 signed 结果支持机理结论。

---

## 7. Phase 4：组合目标函数

**目的：** 在固定信号定义和固定网格上判断电位分辨信息能否改善反演。

**允许修改：**

- `python/oer_aem/features.py`
- `python/oer_aem/inversion.py`
- `python/tests/test_inversion.py`
- `scripts/compare_feature_objectives.py`
- `scripts/plot_architecture_validation.py`

### Task 4.1：先比较 lock-in-only

正式模式顺序：

1. `legacy`
2. `complex_snr`
3. `lockin_only`
4. `combined`

先运行前三种。只有 `lockin_only` 在合成恢复和 H1–H3 上显示非劣，才实现 combined。这样可以区分“新信息有效”与“保护项强行拉回旧指标”。

### Task 4.2：归一化并冻结损失组

- [ ] DC、global complex、lock-in amplitude、lock-in phase 和 physical penalty 分别输出。
- [ ] 每组损失先转换为无量纲均值尺度。
- [ ] 权重使用 synthetic 或独立校准规则冻结。
- [ ] 冻结权重写入配置和 manifest；正式真实数据运行后禁止修改。
- [ ] 没有可信局部 SNR 时，使用预注册的统一权重，不伪装成 SNR weighting。

### Task 4.3：最小 combined

combined 只组合已独立通过的分量。第一版禁止同时引入：

- 新物理模型；
- 新参数边界；
- M1；
- 数据集排除变化；
- full-grid；
- 额外后处理调权。

### Task 4.4：smoke 与预算核对

- [ ] smoke 只检查有限值、分量存在、失败计数和运行时间。
- [ ] formal 启动前计算准确研究数：

\[
N_{\text{trials}} =
N_{\text{modes}}\times N_{\text{targets}}\times
N_{\text{seeds}}\times N_{\text{trials per study}}
\]

- [ ] synthetic 是否计入 targets 必须显式写明。
- [ ] 输出预计 wall time、并行度和内存需求。

**Gate 4 — PASS 条件：**

- lock-in-only 的科学增益可独立观察；
- combined 没有通过权重变化掩盖某个严重恶化分量；
- 所有模式的输入、预算和参数搜索空间完全配对；
- 代码测试通过，smoke 无非有限损失和异常失败率。

**FAIL 动作：** 如果 lock-in-only 失败，停止 combined；如果 combined 失败，保留通过的独立特征，不通过调权反复试探正式真实数据。

---

## 8. Phase 5：正式科学评价

**目的：** 用冻结代码和配置作一次可复现、可否证的正式比较。

### Task 5.1：运行前锁定

- [ ] 记录 commit、工作树状态、Python 和依赖版本。
- [ ] 记录数据文件哈希。
- [ ] 记录模式、数据集、种子、trial、参数边界和权重。
- [ ] 生成预计输出行数和唯一键集合。
- [ ] 禁止 formal 运行期间修改代码或配置。

### Task 5.2：正式运行与监控

- [ ] 在 Legion 新工作树拉取目标 commit。
- [ ] 使用现有已验证虚拟环境。
- [ ] 在 tmux 中启动。
- [ ] 每次检查前读取北京时间；距上次真实检查至少 20 分钟才检查。
- [ ] 每次记录完成数、失败数、最新输出和进程状态。
- [ ] 发现失败率异常、输出 schema 错误或非有限结果时停止本阶段。

### Task 5.3：配对评价

正式评价至少报告：

- synthetic 参数恢复误差及多种子分布；
- common H1–H3 RMSE；
- 各数据集 DC 与谐波分量；
- G_OH、G_O、scaling_OOH_OH 的跨数据集与跨种子稳定性；
- boundary hits、ODE failures、Tafel failures；
- runtime 和 forward count；
- 对采样率、记录长度和相位参考的稳定性证据。

**Gate 5 — Go 条件：**

- synthetic recovery 满足第 2.5 节非劣界限；
- H1–H3 满足第 2.5 节非劣界限；
- 热力学参数稳定性满足第 2.5 节非劣界限；
- boundary hit、失败率和 runtime 满足第 2.5 节界限；
- 新方法的幅值与相位稳定性通过 Phase 1；
- 增益在多个种子或置信区间上存在，而非单个最好结果；
- runtime 在预先接受的范围内。

**No-Go：** 任一核心条件失败，则新方法保留为实验分支，不替代 legacy。报告失败本身，不进行同一正式数据上的事后调权。

---

## 9. Phase 6：实验数据发展

算法阶段完成后，优先提升数据质量：

1. 每个条件获取重复 FTacV 轨迹；
2. 保存应用电位参考信号或可靠的相位/time-zero 元数据；
3. 用重复实验估计幅值、相位和参数不确定度；
4. 验证跨天、跨电极和跨批次稳定性；
5. 在有重复数据后再赋予局部 SNR 物理统计含义。

没有重复实验时，应把跨数据集 CV 解释为“数据集间稳定性”，而不是测量不确定度。

---

## 10. 压力测试结果

### 风险 A：四项改动混合，结果不可归因

**攻击场景：** combined 变好，但同时改变了网格和损失尺度，无法证明锁相提供了信息。

**控制：** Phase 1–4 单变量推进；先比较 lock-in-only，再允许 combined。

**残余风险：** 信号处理和目标函数天然有接口依赖。通过冻结 Phase 1 输出 schema 和 Phase 2 网格控制依赖。

### 风险 B：旧 12-point 结果污染新门槛

**攻击场景：** 新方法看似通过，其实与不同采样的旧数字比较。

**控制：** Phase 0 重算同构基线；正式 CSV 强制记录 `points_per_cycle`。

**失败退出：** 证据字段不完整时不进入 Phase 1。

### 风险 C：相位参考错误导致虚假差异

**攻击场景：** 实验与模拟只因 time-zero 不同而出现相位残差。

**控制：** 相位参考绑定应用电位；加入同步时间平移不变性测试。

**失败退出：** 无法恢复参考相位的数据集不参与相位目标，但仍可参与幅值诊断。

### 风险 D：full-grid 产生伪重复

**攻击场景：** 6000 个高度相关点压倒物理惩罚，看似降低 RMSE。

**控制：** 独立网格收敛、均值尺度损失、有效自由度诊断、选择最小收敛网格。

### 风险 E：局部 SNR 定义不足

**攻击场景：** 权重来源于候选模拟或同一正式数据的事后调节，产生泄漏。

**控制：** Phase 1 先诊断；没有重复数据时允许明确标为 `diagnostic_only`，不强行进入损失。

### 风险 F：signed sensitivity 只是重命名 unsigned 数据

**攻击场景：** 上游已取绝对值，下游表格添加正负标签却没有真实符号。

**控制：** 在特征构建处计算中心差分，并检查减半步长的符号稳定性。

### 风险 G：FT4 被错误排除

**攻击场景：** 使用假设的 1 V/s 扫描速率推断 1 Hz 数据不可用。

**控制：** 使用每个数据集实际扫描速率；Phase 1 对四个数据集做相同诊断。

### 风险 H：combined 权重过拟合三组真实数据

**攻击场景：** 多次查看 FT2/FT3/FT8 后调整权重，正式结果偏乐观。

**控制：** 权重在 synthetic 或独立校准规则上冻结；正式运行后禁止修改。

### 风险 I：计算预算统计错误

**攻击场景：** 忽略 synthetic 或模式数量，运行数从 1350 实际变成 1800。

**控制：** formal 前由配置生成预计研究数和唯一键，不手算后直接启动。

### 风险 J：在脏工作树继续开发

**攻击场景：** 未提交实验改动与新阶段混合，无法重现或安全回退。

**控制：** Phase 0 首先审计、分类和隔离；不删除用户改动，不将其误认为验证完成。

### 风险 K：只有四个数据集，统计把握不足

**攻击场景：** 单个数据集或单个种子的改善被当作普遍结论。

**控制：** 使用配对多种子分布，限制结论强度；Phase 6 获取重复实验。

### 风险 L：H4–H7 低信号仍被归一化放大

**攻击场景：** 极弱高阶谐波经过逐通道归一化后主导目标函数。

**控制：** 先在原始幅值尺度进行可解析性筛选；无可靠信号的谐波只报告，不进入反演。

---

## 11. 推荐的下一次执行范围

下一轮只执行以下内容：

1. Phase 0：审计当前未提交改动；
2. 解决 12/32 points-per-cycle 证据矛盾；
3. 重建 legacy 与 Complex-SNR 的可信同构基线；
4. 输出 Phase 0 Gate 结果。

在 Gate 0 通过前，不运行 full-grid、combined 或 formal lock-in inversion。Gate 0 通过后，下一轮只执行 Phase 1 的信号层验证。

---

## 12. 完成定义

本路线只有在以下条件全部满足时才算完成：

- 每个阶段都有机器可读结果、人工摘要和 PASS/FAIL；
- 正式结果能追溯到 commit、配置、环境、数据和种子；
- 新方法的增益能归因于电位分辨特征，而非网格、权重或预算变化；
- 失败阶段被如实记录并阻止后续依赖项；
- 通过验证的项目版本已提交并推送 GitHub；
- 本地 agent 交接文档未进入 Git 历史；
- 最终项目进度文档说明推荐方法、限制和下一项实验优先级。
