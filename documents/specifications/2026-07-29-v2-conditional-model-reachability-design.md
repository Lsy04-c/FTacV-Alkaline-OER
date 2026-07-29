# V2 条件模型可达性设计

## 1. 目标

V2 判断一个受限问题：

> 在冻结的 M0、实验扫描条件、参数边界和固定输入假设下，是否存在至少一个
> 模型候选同时达到四组实验各自的 DC、全局复数 H1–H3 和电位分辨
> lock-in H1–H3 特征容差？

V2 不估计真实参数，不证明参数可识别，也不证明 M0 是唯一机理。未找到合格
候选只能表述为“冻结参数库内未达到”，不能表述为数学不可达。

## 2. 采用方案

采用两阶段判定、单次正演：

1. 先评价 DC 和全局复数 H1–H3；
2. 全局阶段通过后，再评价同一候选的电位分辨 lock-in H1–H3；
3. 正演时一次提取两类特征，避免重复 ODE 求解；
4. 四组数据分别判定，不平均、不共享最优候选。

仅使用全局特征会掩盖电位区间错配；直接把全部 lock-in 残差压成一个总损失
则不利于定位失败通道。两阶段判定保留两类信息，同时避免跨模式比较
`total_loss`。

## 3. 输入和冻结边界

### 3.1 数据

使用 FT2、FT3、FT4、FT8 原始三列文件。数据哈希和元数据来自：

```text
config/data-contracts/gate-a1-datasets.json
results/formal/data_contract/gate-a1-7cf548f/
```

列序、`V vs RHE`、`A`、`s` 属于负责人声明；仪器预处理保持
`unresolved`。V2 的结论必须带此条件。

### 3.2 模型和特征

- 模型：现有 M0 AEM；
- 正式求解器：LSODA，允许现有显式 BDF 回退并记录 attempt；
- `fit_harmonics=(1,2,3)`；
- `feature_mode=hybrid`；
- `feature_grid_size=128`；
- `discard_fraction=0.25`；
- 每个数据集按实测周期数构建仿真，正式输出采样为 128 points/cycle；
- 活动通道、SNR 权重和有效掩码由实验 target 冻结。

CN 只允许做开发性能检查。A3 尚未关闭其 H2/H3 相位偏差，因此 CN 不参与
候选筛选、排序或 V2 科学分类。

### 3.3 诊断参数空间

V2 只在下列五个 `diagnostic_only` 参数上建立主参数库：

| 参数 | 坐标 | 下限 | 上限 |
|---|---|---:|---:|
| `k0_1` | log10 | -3 | 5 |
| `k0_2` | log10 | -3 | 5 |
| `k0_3` | log10 | -3 | 5 |
| `G_OH` | linear | 0.8 | 1.8 |
| `G_O` | linear | 2.2 | 3.4 |

边界沿用当前 `DEFAULT_PARAM_SPECS`，不根据实验结果收窄。

参数库使用 seed 29 的 scrambled Sobol 序列，共 512 个候选。生成后保存
物理值、编码值和整体 SHA-256。每一维的归一化最小值必须不高于 0.02，
最大值必须不低于 0.98，否则结构验收失败。

### 3.4 固定输入

主参数库使用下列运行时基线：

| 参数 | 基线 | 来源边界 |
|---|---:|---|
| `A` | 1.0 cm² | 当前运行时默认，不表示准确 |
| `Cdl` | 20 µF cm⁻² | 当前运行时默认，不表示准确 |
| `Ru` | 10 Ω | 当前运行时默认，不表示准确 |
| `E0_pre` | 1.45 V vs RHE | 当前运行时默认，不表示准确 |
| `k0_pre` | 500 s⁻¹ | 当前运行时默认，不表示准确 |
| `gamma` | 3×10⁻⁹ mol cm⁻² | 既有真实数据分析基线，不表示准确 |
| `k0_4` | 5×10³ s⁻¹ | 当前运行时默认，不表示准确 |
| `scaling_OOH_OH` | 3.2 eV | 当前标度关系基线，不表示准确 |

这些值只定义条件模型，不升级为独立测量。

固定输入压力测试采用一次只改一个变量：

- 正值参数 `A`、`Cdl`、`Ru`、`k0_pre`、`gamma`、`k0_4`：
  基线的 0.5× 和 2×；
- `E0_pre`：基线 ±0.05 V；
- `scaling_OOH_OH`：基线 ±0.2 eV。

压力测试只作用于每个数据集主参数库最终分数最低的 8 个候选，共
4×8×16=512 次额外正演。它检验局部结论稳定性，不代表完整固定输入
不确定度传播。

## 4. 特征距离

所有残差统一为“模拟减实验”；符号进入明细，分类使用绝对量。

### 4.1 全局阶段

活动指标包括：

- 归一化 DC 曲线 RMSE；
- 活动 H1–H3 的复数幅值相对误差；
- 活动 H1–H3 的包裹相位绝对误差。

幅值分母使用：

```text
max(|target_h|, 0.02 × max_active_target_amplitude)
```

避免弱通道产生无穷相对误差。低于 A5 冻结 SNR 门的通道保持非活动。

### 4.2 lock-in 阶段

只在目标与候选有效掩码交集上计算：

- 每个活动谐波的幅值 NRMSE；
- 每个活动谐波的包裹相位 RMSE；
- 有效区交集比例；
- 幅值峰位偏移。

### 4.3 工程容差

| 指标 | 容差 |
|---|---:|
| DC NRMSE | 0.10 |
| 全局谐波幅值相对误差 | 0.10 |
| 全局谐波相位误差 | 0.10 rad |
| lock-in 幅值 NRMSE | 0.10 |
| lock-in 相位 RMSE | 0.10 rad |
| lock-in 峰位偏移 | 0.025 V |
| 有效区交集比例 | ≥0.50 |

谐波容差、峰位和有效区门沿用 A4 冻结阈值。DC 0.10 是与幅值门一致的
工程容差，不是实验噪声或置信区间。V2 不允许据此报告统计显著性。

每个指标除以自身容差，候选阶段分数取最大比值。全局分数不高于 1 才进入
lock-in 判定；全局与 lock-in 全部指标均不高于 1 时，该候选为
`REACHED`。

## 5. 数据集分类

每组数据独立输出以下一种状态：

| 状态 | 条件 |
|---|---|
| `REACHED` | 至少一个 LSODA 候选通过全局和 lock-in 两阶段 |
| `NOT_REACHED_WITHIN_LIBRARY` | 无候选通过，且 256→512 候选的最佳分数改善不超过 10% |
| `INCONCLUSIVE_LIBRARY` | 无候选通过，且最佳分数改善超过 10% |
| `FIXED_INPUT_SENSITIVE` | 基线未达到，但局部固定输入压力测试出现达到候选，或基线达到结论被压力测试推翻 |
| `INCONCLUSIVE_NUMERICAL` | 主参数库 ODE 成功率低于 95% |
| `FAIL_CONTRACT` | 数据、目标、参数库或通道契约不完整 |

分类优先级为：

```text
FAIL_CONTRACT
→ INCONCLUSIVE_NUMERICAL
→ FIXED_INPUT_SENSITIVE
→ REACHED
→ INCONCLUSIVE_LIBRARY
→ NOT_REACHED_WITHIN_LIBRARY
```

`NOT_REACHED_WITHIN_LIBRARY` 仍不是数学不可达。

## 6. 输出接口

正式目录至少包含：

```text
task_spec.json
parameter_library.csv
targets.json
base_results.jsonl
stress_results.jsonl
summary.json
run_manifest.json
acceptance.md
```

runner 只生成前七个科学产物；`acceptance.md` 必须由独立 validator 在完成
结构、数值和分类重算后生成。runner 不得自我签发验收结果。

`task_spec.json` 在计算前冻结数据哈希、参数边界、基线、压力场景、Sobol
seed、候选数、采样、特征和阈值。

每个基础结果记录：

- `dataset_id`、`candidate_id`；
- 编码和物理参数；
- solver attempt、最终后端、运行时间；
- 活动通道和契约哈希；
- 所有分项指标、分数和通过状态；
- ODE/特征失败原因。

结果不得使用 `best_params`、`estimated_params` 或 `truth` 等字段名；统一用
`nearest_candidate` 和 `conditional_candidate`。

## 7. 运行与续跑

runner 使用确定性 job ID：

```text
base:<dataset_id>:<candidate_id>
stress:<dataset_id>:<candidate_id>:<scenario_id>
```

结果逐行原子追加，恢复时校验 `task_spec`、参数库和已有 job hash。未知文件、
重复 job、hash 冲突或部分 JSON 行立即停止。默认 8 workers，每个 worker
限制一个 BLAS 线程。

正式计算前先运行：

```text
8 candidates × 4 datasets，全部使用 LSODA
```

smoke 只运行 4×8 个基础候选，不运行固定输入压力测试；它只验收接口、失败
路径、runtime 和输出结构，不产生科学分类，也不得因缺少正式压力任务而失败。

## 8. 独立验证

validator 不导入 runner 或 `oer_aem.reachability`，独立完成：

1. 文件集合、schema、有限值和唯一 job 检查；
2. 数据、task spec、参数库和产物 SHA-256 检查；
3. Sobol 维度、候选数、边界覆盖和嵌套 256/512 前缀检查；
4. 活动通道、容差归一化、阶段分数和分类重算；
5. 基础任务数 4×512 和压力任务数 4×8×16 检查；
6. ODE 成功率和失败分层检查；
7. 每组最低分候选的 LSODA 抽样重算；
8. manifest 的 clean commit、命令和环境检查。

结构、数值、科学分类和流程状态分开报告。validator 的结构 PASS 不能覆盖
`NOT_REACHED_WITHIN_LIBRARY` 或 `INCONCLUSIVE_*`。

## 9. 压力测试结论

- **数据泄漏：** 参数边界、Sobol seed、阈值和预算在读取候选结果前冻结；
- **后端偏差：** CN 不参与排序，避免 A3 相位偏差改变候选；
- **弱通道爆炸：** 使用 2% 幅值地板和 A5 活动通道；
- **总损失掩盖：** 采用最大分项容差比，不用平均总损失抵消失败通道；
- **预算不足：** 比较嵌套 256/512 前缀，未收敛时标记
  `INCONCLUSIVE_LIBRARY`；
- **固定值不准：** 运行局部 OAT 压力测试，敏感时单独分类；
- **多组数据误合并：** 四组分别判定；
- **错误科学升级：** 输出只允许条件可达性，不允许真实参数或机理结论。

## 10. 完成标准

V2 完成需同时满足：

1. smoke 结构通过；
2. 正式 LSODA 任务完整或按规则恢复；
3. 独立 validator 重算一致；
4. 四组数据均获得合法分类；
5. 固定输入敏感性单独报告；
6. 结果绑定干净 commit、配置、数据和环境；
7. 项目总览、路线、进度和纠错同步；
8. 不启动真实数据 TPE，不改变 A1/A3/A6 结论。
