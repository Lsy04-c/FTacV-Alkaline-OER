# 实验前 A6-v2 多协议合成恢复设计

状态：待实现
日期：2026-08-01
上游证据：V4.1 正式实验信息设计

## 1. 目标与结论边界

本阶段验证 V4 推荐协议在冻结 M0 完全正确、非自由参数精确已知的合成条件
下，能否恢复预注册的低维参数对。它只检验协议组合、现有反演器和特征契约
形成的条件恢复能力。

本阶段不接触真实数据反演，不改变 Gate A6 当前的 `FAIL_RECOVERY`，不把
任何参数升级为 `free` 或 `narrow_prior`，也不证明真实实验、完整五步 AEM
或机理正确。真实数据资格仍依赖 A1、一手元数据、独立 `Ru/Cdl/gamma`
约束、新实验数据和后续正式 A6-v2。

## 2. 设计选择

采用嵌套协议组合的配对恢复：

| 组合 | 条件 | 用途 |
|---|---|---|
| P0 | 5 Hz、0.16 V、256 cycles | 现有匹配基线 |
| P1 | P0 + 5 Hz、0.08 V、256 cycles | 检验第一推荐协议的增量 |
| P2 | P1 + 10 Hz、0.16 V、512 cycles | 检验完整两阶段推荐 |

三个条件沿用 V4 的 `E_start=0.924097277474612 V`、
`E_end=1.9229037265531128 V`、128 points/cycle 和约 51.2 s 扫描时长。
P0 对应 V4 的匹配 5 Hz 基线；P1、P2 分别加入
`candidate_5hz_amp_008` 和 `candidate_10hz_matched_scan`。

拒绝以下替代方案：

- 分别恢复单个协议：不能检验联合数据是否解除补偿；
- 继续做局部敏感性：V4 已完成，不能替代全局恢复；
- 同时更换优化器：会把协议效应与算法效应混在一起；
- 新增 Bonke 三参数模型：不能回答五步 M0 在推荐协议下的条件恢复问题。

## 3. 冻结模型、参数与特征

### 3.1 模型和后端

- 正演模型：当前冻结 M0，`beta_recon=0`；
- 正式后端：LSODA，明确失败时只允许冻结的 BDF 回退路径；
- CN：仅用于开发 smoke，不参与正式科学门；
- 每个 worker 的 OMP、OpenBLAS、MKL 和 NumExpr 线程均固定为 1；
- 正式运行绑定完整 commit、Python、环境、配置和结果哈希。

### 3.2 参数对

只评价三个预注册参数对：

1. `k0_2, k0_3`；
2. `k0_3, G_O`；
3. `G_OH, G_O`。

边界和 log/linear 编码沿用 `DEFAULT_PARAM_SPECS`。每项研究仅优化指定参数
对；其他参数取对应合成真值并保持固定。该设置只证明“固定输入准确时”的
条件恢复能力，不检验固定输入误差传播。

### 3.3 特征和目标

- 特征模式：仅 `hybrid`；
- 拟合谐波：H1–H3；
- 特征网格：128 点；
- H4–H7：不进入目标、恢复门或本阶段输出；
- 每个条件先按冻结的单条件目标独立归一化；
- 协议组合目标为各条件归一化损失的等权算术平均；
- 禁止先拼接原始特征再统一归一化，避免点数或幅值更大的条件支配目标；
- P0 中同一条件的目标、噪声和哈希在 P1/P2 中必须逐字节复用。

## 4. 真值、噪声与泄漏控制

### 4.1 真值与优化种子

- 使用现有 `truth_library` 的 `center`、`mixed_a`、`mixed_b` 三个内部真值；
- 使用优化 seed `7, 17, 27`；
- 真值不得进入初始点、TPE enqueue、边界收窄、提前停止或候选排序；
- 每个参数对、真值和 seed 在 P0/P1/P2 间严格配对；
- 目标噪声 seed 只由 `truth_id + noise_fraction + condition_id` 派生，不能
  包含 portfolio ID，保证嵌套组合复用完全相同的单条件观测。

### 4.2 噪声层级

阶段 N0 使用 `noise_fraction=0`。阶段 N1 使用现有证据冻结的
`0.001495726085983469`，证据文件为
`results/formal/identifiability/gate-a6-d9299f8/noise_evidence.json`。

N1 只表示现有数据导出的白噪声代理，不代表未来 5 Hz/0.08 V 或 10 Hz
实验的真实噪声，也不包含漂移、背景、气泡、批次差异或模型失配。

## 5. 阶段与计算矩阵

### 5.1 S0：结构 smoke

每个协议组合至少运行一个最小 job，验证多条件目标、嵌套目标复用、结果
schema、有限值、断点恢复和工作流状态。smoke 不产生科学结论。

### 5.2 S1：无噪声正式门

冻结 TPE 100 trials，不运行新的预算选择。矩阵为：

```text
3 参数对 × 3 portfolios × 3 truths × 3 optimizer seeds = 81 studies
```

逐参数对判断 P2 是否通过全部无噪声门。若三个参数对的 P2 均失败，停止
S2，状态记为 `DESIGN_INSUFFICIENT_NOISELESS`，不得增加 trials、更换优化器
或删除失败真值。

### 5.3 S2：噪声代理正式门

只有 P2 在 S1 通过的参数对进入 S2。每个入选参数对仍完整运行
P0/P1/P2、三个真值和三个 seed；不能只运行 S1 中表现最好的 portfolio。
最大矩阵为 81 studies。

任何中间失败都保留已完成行和失败分类。基础设施失败修复后可按 job hash
续跑；数值或科学失败停止其依赖阶段。

## 6. 恢复门与协议分类

沿用 recovery gate v2 的冻结阈值：

| 指标 | 门限 |
|---|---:|
| 每组 seed 中位归一化边界误差 | ≤ 0.025 |
| 单次最大归一化边界误差 | ≤ 0.05 |
| seed 间有符号归一化误差离散 | ≤ 0.05 |
| 边界命中率 | 0 |
| study 成功 | 全部成功 |

门按参数对、portfolio、truth 和噪声层分别重建。不得用跨真值平均掩盖某个
真值失败。协议组合按绝对门分类，不另设事后“改善百分比”。分类先检查
非单调；若通过状态随条件增加保持单调，再按最小通过 portfolio 分类：

| 结果 | 分类 |
|---|---|
| 通过状态非嵌套 | `NON_MONOTONIC_REQUIRES_REVIEW` |
| P0、P1、P2 均通过 | `BASELINE_SUFFICIENT` |
| P0 失败、P1 通过 | `AMP_008_ADDS_RECOVERY` |
| P0/P1 失败、P2 通过 | `TEN_HZ_ADDS_RECOVERY` |
| P2 失败 | `DESIGN_INSUFFICIENT` |

项目级实验前门只在至少一个参数对的 P2 同时通过 S1 和 S2 时记为
`PASS_CONDITIONAL_SYNTHETIC_RECOVERY`。其余参数对仍逐项保留失败，不得用
项目级 PASS 覆盖。

## 7. 软件边界与数据流

新增能力应保持现有模块边界：

```text
冻结 protocol catalog
        │
        ▼
每条件 synthetic target ──按 condition key 缓存并复用
        │
        ▼
单条件 hybrid objective ──先独立归一化
        │
        ▼
portfolio 等权聚合 objective
        │
        ▼
现有 TPE inverter / LSODA
        │
        ▼
job 级结果 → 恢复门重建 → 协议分类
```

实现必须扩展现有 recovery/inversion 接口，不复制第二套 runner：

- 科学核心负责协议目录、目标复用和 portfolio 聚合；
- runner 负责 job 计划、并行、原子 checkpoint、resume 和 provenance；
- 独立 validator 从结果行重建矩阵、阈值和协议分类；
- `oer-wf` 只负责远程执行、同步和冻结环境验收，不内嵌科学判断。

## 8. 输出与不可变证据

正式输出至少包含：

```text
pre_experiment_recovery_spec.json
protocol_catalog.csv
job_plan.json
target_manifest.json
results.jsonl
portfolio_recovery.csv
summary.json
run_manifest.json
STATUS.json
task_spec.snapshot.yaml
```

`target_manifest.json` 必须记录每个 `truth/noise/condition` 目标的输入哈希，
并证明它在 P0/P1/P2 中复用。`portfolio_recovery.csv` 保存每个参数对和
portfolio 的绝对门结果及分类，不保存未经门验证的“推荐真参数”。

正式归档保持只读；二次验收通过 `oer-wf 0.7.0` 在冻结 Legion worktree
执行，receipt 写到计算归档之外。

## 9. 失败分层与退出条件

- `FAIL_STRUCTURE`：任务矩阵、目标复用、schema、哈希或 provenance 错；
- `FAIL_INFRA`：SSH、systemd、文件传输或环境不可用；
- `FAIL_NUMERICAL`：正式正演不能生成有限目标或求解失败使 study 无效；
- `FAIL_RECOVERY`：执行完整但未达到恢复阈值；
- `NON_MONOTONIC_REQUIRES_REVIEW`：新增条件使绝对门从通过变为失败。

结构和基础设施失败不得写成科学失败；修复后使用相同冻结规格重跑。数值或
恢复失败后停止依赖阶段，不调整阈值、参数对、真值、seed 或预算。

## 10. 测试与完成标准

实现前先补失败测试，至少覆盖：

1. P0/P1/P2 条件集合严格嵌套；
2. 单条件目标在不同 portfolio 中字节级复用；
3. 条件先归一化、portfolio 后等权聚合；
4. portfolio ID 不进入目标噪声 seed；
5. 参数对、真值、seed 和噪声矩阵完整且无重复；
6. 100-trial 和阈值不能由 CLI override 改写；
7. 无噪声 P2 全失败时拒绝生成 S2 计划；
8. 五种协议分类和非单调路径；
9. checkpoint 损坏、job hash 不符和 resume 拒绝；
10. validator 独立重建统计、分类和项目级门；
11. archive 验收前后哈希一致；
12. 现有 A6、V4、oer-wf 和项目全量测试无回归。

完成要求：本地 smoke、全量测试和独立 validator 通过；正式计算前冻结
干净 commit、任务规格、环境、随机种子、100-trial 预算和上述阈值。只有
正式 Legion LSODA 结果通过后，才能更新实验采集建议；无论 PASS/FAIL，
都不得改变真实数据 Gate A6 的当前失败状态。
