# OER-FTAcV 项目总览、架构与交接

更新日期：2026-08-02
负责人：刘拾玉
当前分支：`codex/reclassify-project`

> 本文是项目唯一总入口，保存当前架构、接口、正式结论、未完成目标和交接
> 方法。历史执行过程见 `WORK_STATUS.md`，当前行动步骤见
> `documents/plans/2026-07-29-vacation-and-post-experiment-roadmap.md`。

## 1. 当前一句话状态

项目的物理正演、谐波特征、目标函数契约和计算工作流已经形成可验证底座；
现有四组 FTacV 数据可用于条件模型分析，但关键实验元数据尚未完全追溯，
且当前参数组合没有通过合成恢复门，因此暂时不能报告正式真实数据反演参数。
V1 已登记负责人声明的列序、单位和 RHE 标尺；V2 已证明冻结参数库内四组
数据均未达到预注册特征门；V3 已完成正式残差归因；V4.1 已在冻结条件模型
下通过实验信息设计门，优先建议 `5 Hz / 0.08 V` 振幅协议，再增加
`10 Hz` 匹配扫描协议。待补实验信息继续留到恢复实验后；V4 PASS 不改变
A1 `FAIL_METADATA`、A3 `FAIL` 或 A6 `FAIL_RECOVERY`。单协议六参数恢复及
三协议联合恢复均未通过；`mixed_a`附近的`G_OH-log10(k0_1)`组合仅登记为
`LOCAL_ONLY`，不得外推为全局降维坐标。恢复实验接入契约已实施，空模板
固定为`WAITING_FOR_DATA`，当前不会生成A1种子或启动反演。

当前主线：

```text
休假期间：现有数据的条件模型可达性与残差归因
→ 形成解除参数耦合的实验设计
→ 恢复实验后按接入契约补齐独立约束与结构化数据
→ 重开 A6-v2 合成恢复
→ 通过后再做正式联合反演和置信度
```

当前不是主线：

- 继续增加 TPE trials；
- 为获得 PASS 更换优化器、扩大边界或放宽阈值；
- 把四组不同实验当作重复实验平均；
- 继续扩展复杂机理；
- 用 C++ CN 结果承担正式科学结论；
- 报告未经恢复门验证的参数点估计。

## 2. 项目目标与科学边界

### 2.1 科学目标

建立可验证、可复现的碱性 OER FTacV 微观动力学方法，回答：

1. 当前实验条件能约束哪些参数或参数组合；
2. 哪些参数必须由独立实验固定或给先验范围；
3. DC、不同谐波和不同电位区间各自提供什么信息；
4. 模型不能拟合时，问题来自机理、背景、电位标尺还是数据处理；
5. 参数结论在求解误差、优化随机性和实验变化下是否稳定。

### 2.2 工程目标

形成可复用的 Python 核心和远程工作流，支持严格数据导入、AEM 正演、
复数谐波与 lock-in、冻结目标、敏感性/profile/合成恢复、失败分层及
commit/配置/环境/结果哈希追溯；科学核心可信后再完成 Web 交付。

### 2.3 科学结论等级

结果按实现事实、数值事实、条件科学结论、正式反演结论和机理结论分级。
当前只允许前三类；拟合损失降低不能升级为参数真实性或机理证明。

## 3. 系统架构与数据流

### 3.1 科学数据流

```text
三列实验数据（电位、电流、时间）
        │
        ▼
严格数据契约与采样诊断
        │
        ├───────────────┐
        ▼               ▼
AEM 正演模型        实验信号处理
LSODA/BDF            DC / H1–H7 / lock-in
        │               │
        └───────┬───────┘
                ▼
         冻结特征通道契约
                │
                ▼
     敏感性 / profile / 合成恢复
                │
        ┌───────┴────────┐
        ▼                ▼
条件模型分析       通过 Gate 后正式反演
        │                │
        └───────┬────────┘
                ▼
      正式证据归档 / API / Web
```

### 3.2 Gate 依赖

```text
实验接入 → 新批次 A1 数据 → A2 物理 → A3 求解器 → A4 信号 → A5 特征
→ A6 参数恢复 → A7 证据链 → 正式反演 → 不确定度/机理
```

Gate 不是简单的全部 PASS 串联：失败 Gate 会改变允许路线。例如 A3 失败后
仍可使用 LSODA，但不能让 CN 承担正式结论；A6 失败后仍可做条件模型
可达性和实验设计，但不能报告可信参数点估计。

## 4. 代码目录与关键接口

### 4.1 仓库目录

| 路径 | 职责 |
|---|---|
| `code/python/src/oer_aem/` | 正式 Python 科学计算核心 |
| `code/python/scripts/` | 计算、诊断、正式 runner 和独立 validator |
| `code/python/tests/` | 单元、回归、结构和失败路径测试 |
| `code/cpp/src/` | C++ CN 及实验性编译核心 |
| `code/matlab/` | MATLAB 参考实现和历史比较 |
| `code/web/` | FastAPI 后端和静态前端 |
| `config/data-contracts/` | 实验数据注册表 |
| `config/parameter-roles/` | 参数角色注册表 |
| `config/oer-wf/` | 远程计算工作流工具和任务规格 |
| `data/raw/` | 原始实验数据，只读保存 |
| `results/formal/` | 可追溯的正式科学证据 |
| `results/smoke/` | 小预算流程检查，不承担科学结论 |
| `results/diagnostics/` | 辅助诊断和探索结果 |
| `documents/project/` | 当前总览、历史状态和工作规则 |
| `documents/corrections/` | 项目内错误、根因和复用规则 |

### 4.2 关键接口

| 模块 | 主入口 | 输入 | 输出 | 状态/限制 |
|---|---|---|---|---|
| 恢复实验接入 | `experiment_intake.validate_intake` / `validate_post_experiment_intake.py` | 版本化清单、原始文件、方法文件 | 四状态、验收说明、条件式非正式A1 seed | 已实施；当前`WAITING_FOR_DATA`，READY不等于A1 PASS |
| 严格数据读取 | `data_contract.read_strict_experimental_trace` | 三列文本文件 | `ExperimentalTrace`、文件事实 | 已验证；不静默排序、裁剪或插值 |
| 采样诊断 | `data_contract.derive_sampling_diagnostics` | 电位、电流、时间 | 频率、振幅、采样率、扫描速率、缺口 | 已验证量化时间戳 |
| 默认参数 | `defaults.py` | 无或覆盖值 | 统一参数字典 | 已实现 |
| 统一核心 | `core.OERCore` | 参数和实验数据 | 物理、信号和目标入口 | 兼容入口 |
| 热力学 | `thermodynamics.py` | AEM 参数 | 标度关系和电位参数 | 已实现；不等于参数已验证 |
| 物理 RHS | `physics.elementary_rates`、`coverage_derivatives` | 状态、时间、参数 | 五步速率和覆盖度导数 | A2-R 正式通过 |
| 正式动态求解 | `physics.OERPhysics.solve_ode_system` | 冻结参数 | `ODESolution`、attempt 记录 | LSODA；失败时显式 BDF 回退 |
| C++ CN | `cpp_bridge.py`、`code/cpp/src/oer_cn_solver.cpp` | 同一正演参数 | 快速电流轨迹 | 实验后端；A3 未通过 |
| 全局谐波 | `signal.extract_complex_harmonics` | 电流、采样率、基频 | H1–H7 复数特征 | 已验证 |
| 电位分辨特征 | `signal.lockin_harmonics` | 电流、电位参考、时间 | 电位分辨 I/Q、幅值、相位 | A4 稳定性通过 |
| 特征契约 | `inversion.build_feature_channel_contract` | 目标数据和模式 | 活动通道、权重、掩码、分母 | A5 正式通过 |
| 特征提取 | `inversion.extract_features` | 电流和 `InversionConfig` | DC、复数谐波、lock-in、物理项 | 128 点正式网格 |
| 目标函数 | `inversion.InversionObjective` | 冻结目标、候选参数 | 分量损失、失败计数、总损失 | 候选不能改变目标通道 |
| TPE 适配 | `inversion.TPEInverter` | 目标、边界、预算 | `InversionResult` | 已实现；当前禁止正式真实反演 |
| 敏感性 | `importance.py`、`identifiability.py` | 参数和冻结特征 | 有符号敏感性、相关和分类 | 局部诊断，不证明联合可恢复 |
| Profile | `profiling.py`、`run_objective_profiles.py` | 参数网格 | 单/二维目标地形 | 诊断用 |
| 合成恢复 | `recovery.py`、`run_synthetic_recovery.py` | 真值、噪声、seed、算法 | 逐 study 结果和 recovery gate | A6 当前失败 |
| 优化器比较 | `optimizers.py`、`optimizer_benchmark.py` | 固定调用预算 | TPE/Sobol/DE 轨迹 | 开发证据不能覆盖确认失败 |
| Web API | `code/web/backend/main.py` | JSON/实验数据 | analyze、simulate、TPE 响应 | 原型可用；非当前主线 |
| Web 前端 | `code/web/frontend/index.html` | API 响应 | 实验、正演和反演视图 | 静态原型 |

### 4.3 正式验证入口

| Gate | Runner / validator |
|---|---|
| A1前接入 | `validate_post_experiment_intake.py` |
| A1 | `audit_experimental_contracts.py` / `validate_gate_a1_contracts.py` |
| A2 | `audit_physics_invariants.py` / `validate_gate_a2_physics.py` |
| A2-R | `audit_gate_a2r.py` / `validate_gate_a2r.py` |
| A3 | `validate_solver_equivalence.py` |
| A4 | `validate_real_harmonic_stability.py` |
| A5 | `audit_feature_channel_contracts.py` / `validate_gate_a5_channels.py` |
| A6 | `validate_gate_a6_parameter_roles.py` |
| 仓库文档 | `audit_repository_layout.py` |

Validator 的 `PASS` 只说明其负责的结构或关闭契约通过，不能覆盖底层科学
Gate 的 `FAIL`。

## 5. Gate A1–A7 状态

| Gate | 当前结论 | 已证明 | 未证明/限制 | 主要证据 |
|---|---|---|---|---|
| A1 数据契约 | `FAIL_METADATA` | 结构、哈希、采样及负责人声明的 `V vs RHE`、`A`、`s` 已登记 | 仪器预处理一手记录不足 | `results/formal/data_contract/gate-a1-7cf548f/acceptance.md` |
| A2-R 物理不变量 | `PASS` | 守恒、稳态、电流闭合、极端回退通过 | 不证明 M0 是唯一机理 | `results/formal/physics_invariants/gate-a2r-496a701/acceptance.md` |
| A3 求解器 | `FAIL` | LSODA 参考路径可用 | CN 锁相相位不等价 | `results/formal/solver_equivalence/formal-a4581de-ppc256/solver_equivalence_summary.json` |
| A4 信号稳定性 | `PASS` | 合法降采样和截断下特征稳定 | 不证明反演更准确 | `results/formal/harmonic_stability/gate-a4-6848613/harmonic_stability_summary.json` |
| A5 特征契约 | `PASS` | 通道、权重、掩码和分母候选不变 | 不证明参数可恢复 | `results/formal/feature_channel_contract/gate-a5-13adcb1/acceptance.md` |
| A6 参数恢复 | `FAIL_RECOVERY` | 13 参数角色和失败路线已冻结 | 无参数具备正式反演资格 | `results/formal/identifiability/gate-a6-closure-75e25ed/acceptance.md` |
| A7 证据工作流 | `PASS`（工程） | prepare/smoke/run/status/sync/verify 闭环 | 不证明任何科学 Gate | `WORK_STATUS.md` 第 0.7 节 |

### 5.1 当前三个阻断项

1. **A1 元数据：** 已知列序和单位，但仪器预处理缺少原始记录；
2. **A3 加速后端：** CN 没有通过相位等价性，正式计算仍依赖较慢的 LSODA；
3. **A6 参数恢复：** 所有锁定两参数组合均失败，当前自由参数为空。

这些阻断项不会使现有四组数据“不能使用”，但会限制结果等级。

## 6. 当前数据、特征与参数口径

### 6.1 实验数据

当前原始 FTacV 数据：

| 数据集 | 基频 | 振幅 | 点/周期 | 说明 |
|---|---:|---:|---:|---|
| FT2 | 5 Hz | 0.16 V | 256 | 独立实验 |
| FT3 | 5 Hz | 0.16 V | 256 | 独立实验 |
| FT4 | 1 Hz | 0.16 V | 256 | 独立实验 |
| FT8 | 5 Hz | 0.16 V | 256 | 独立实验 |

统一列序：

```text
第 1 列：potential
第 2 列：current
第 3 列：time
```

当前单位声明：

```text
potential = V vs RHE
current = A
time = s
```

来源边界：

- 列序、单位和 RHE 标尺来自项目负责人声明；
- 配套 CHI660E/CHI760F CV 文件头辅助支持 `V` 和 `A`；
- 负责人不是原实验执行者；
- 除 RHE 校正外未报告其他预处理，但现存文件不能证明“无预处理”；
- 四组数据不是重复实验，禁止平均后当作降噪重复。

### 6.2 特征口径

- DC 和 H1–H3 是当前共同核心评价特征；
- H4–H7 只有达到冻结可解析门时才进入评价；
- 正式特征网格为 128 点；
- `legacy`、`complex_snr`、`lockin_only`、`hybrid` 语义已分离；
- 现阶段优先用 `hybrid` 和 `lockin_only` 做条件诊断；
- 不同模式活动通道数不同，不能直接用未经同构化的总损失排名。

### 6.3 参数角色

当前机器可读登记表：

```text
config/parameter-roles/gate-a6-parameter-roles.json
```

| 角色 | 参数 | 含义 |
|---|---|---|
| `fixed` | `A`、`Cdl`、`Ru`、`E0_pre`、`k0_pre`、`gamma`、`k0_4`、`scaling_OOH_OH` | 当前运行时固定，不表示准确 |
| `diagnostic_only` | `k0_1`、`k0_2`、`k0_3`、`G_OH`、`G_O` | 可做 profile/敏感性，不报告可信点估计 |
| `free` | 无 | 当前没有通过恢复门的自由参数 |
| `narrow_prior` | 无 | 当前没有独立依据冻结窄先验 |

已确认的主要补偿：

| 参数对 | 证据 | 当前处理 |
|---|---|---|
| `k0_3`–`scaling_OOH_OH` | 局部相关约 −0.99995 | 不同时自由拟合 |
| `A/Cdl/gamma` | `gamma`–`A`局部相关约+0.9895；当前方程另有精确尺度对称性 | 新schema按观测口径改为`CdlA/GammaA`或面参数 |
| `k0_1`–`k0_pre` | complex 模式约 +0.9881 | `k0_1` 仅诊断 |
| `G_OH`–`G_O` | complex 模式约 −0.9848 | 需新电位/条件信息 |
| `k0_2`–`k0_3`–`G_O` | 多参数恢复失稳 | 不报告联合点估计 |

局部相关和恢复失败不能单独证明数学结构不可识别。

## 7. 已完成能力与证据

### 7.1 科学与数值底座

- 数据：严格解析、哈希、量化时间戳诊断和负责人声明元数据登记；
- 物理：五步 AEM、守恒、电流分解、LSODA/BDF；
- 信号：复数谐波、lock-in 和候选不变目标；
- 反演诊断：敏感性、profile、恢复门、优化器比较和参数角色；
- 证据：commit、配置、环境和文件哈希绑定。

### 7.2 计算工作流

`oer-wf 0.7.0` 已实现：

```text
doctor → prepare → smoke → run → status → sync → verify → clean
```

它支持固定 commit worktree、systemd 后台任务、规格哈希、smoke gate、
job 级续跑、失败分层、Mac 同步和后端来源留痕。

### 7.3 Web 原型

FastAPI 和静态前端已支持数据分析、正演、TPE 接口和曲线显示；它不是当前
科研主线，界面结果不能替代正式验收。

## 8. 未完成目标与依赖

| 顺序 | 未完成目标 | 依赖 | 完成信号 |
|---:|---|---|---|
| 1 | 条件模型可达性（已完成） | A2-R、A4、A5 | 四组均为 `NOT_REACHED_WITHIN_LIBRARY` |
| 2 | DC/H1–H3 残差归因（已完成） | 目标 1 | 48/48 job 与冻结 Legion validator 通过 |
| 3 | 实验信息设计（已完成） | 目标 1–2 | V4.1 正式门和 8 条独立复算通过 |
| 4 | 恢复实验接入接口（已完成） | 目标 3 | 模板、四状态validator和空模板验收固定 |
| 5 | 原始方法和独立测量 | 恢复实验条件 | 接入状态不再为`FAIL_METADATA` |
| 6 | 结构化新 FTacV 数据 | 目标 3–5 | 三条件齐全并达到`READY_FOR_A1_AUDIT` |
| 7 | A6-v2 合成恢复 | 新条件敏感性/profile | 至少一个参数集通过锁定恢复门 |
| 8 | 正式真实数据联合反演 | A1 与 A6-v2 通过 | 参数具备正式反演资格 |
| 9 | 不确定度和机理结论 | 目标 8 | 数值、优化和实验置信度完整 |
| 10 | Web 最终交付 | 科学输出 schema 冻结 | 前端只展示合格结论和限制 |

依赖顺序不能通过增加优化预算绕过。

### 8.1 物理约束有效维数路线（已批准启动）

- **物理约束有效维数反演：** 候选方案见
  `documents/specifications/2026-08-02-physics-constrained-effective-dimension-inversion-design.md`。
  网络压力测试发现当前M0存在`A/Cdl/gamma`解析结构不辨识，后续必须先改为
  `CdlA/GammaA`组合参数，再做模型充分性、白化敏感性、profile和多盆地优化。
  A1用户声明与配套CHI文件头支持条件分支按总电流处理；预处理历史未闭合，
  因此该重参数化不解除正式真实反演禁令。
  梯度多起点成为首个优化基线，TuRBO/CMA-ES仅作固定预算对照；降维、优化器
  和求解器仍分别验证。网络审计见
  `documents/research/2026-08-02-network-literature-physical-pressure-test.md`。
  2026-08-02已完成G1第一切片：新增`CdlA/GammaA`组合参数解析API，旧输入与
  canonical-only输入的全轨迹、DC和H1-H3在`1e-12`绝对门内等价；开发版schema
  保持`development_only`。第二切片证明四独立覆盖度在内部状态与五状态
  RHS和短轨迹等价，同时确认现有RHS会隐藏归一化离开守恒流形的输入。
  将内部守恒重建与输出物理验收分离后，边界初值四/五状态也在不截断、
  不归一化、不放宽门下等价。长协议与灵敏度方向尚未验收，故未切换正式路径。
  G1仍未完成，不改变A6-v2 S1冻结设计，
  也不解除真实反演禁令。
  有效维数核心已开始实施：新增协方差白化、多锚点加权Gramian和活跃方向分解；
  不从特征值谱自动选维。旧敏感性列混用原始单位与`log10`坐标，现已强制
  按schema边界映射到无量纲`[0,1]`坐标；`CdlA/GammaA`边界未有来源，因此在
  schema中显式保持`unresolved`，不伪造范围以启动全参数分解。
  开发smoke已进一步冻结3/2/1训练、selection和holdout锚点，并将实验量化
  分辨率下限传播到134个结构可观测特征。96个lock-in窗外固定零行已按有效
  掩码排除，未用方差下限伪造信息。12/24/48个噪声seed下selection门均要求
  保留全部7个候选参数；48-seed结果中r6丢弃方向仍为`712.16σ`。因此当前
  G3不支持线性降维，也不具备启动低维优化器竞赛的资格；holdout结果不能
  反向用于挑选维数。证据见
  `results/smoke/effective_dimension/dev-20260802-seed17-v9/summary.json`。
  随后按预注册seed 23扩展到12/4/2锚点；18个锚点、270次敏感性正演全部
  成功。training局部有效秩跨2–6变化，前1–6维相对全局基的最坏主角约
  `54.67°–86.50°`；selection和holdout继续否决固定r6。故当前默认路线已从
  “单一全局线性降维”转为“保留完整7维、先做固定预算多盆地全局—局部恢复
  基线”。分区局部子空间只保留为待验证假设，不能事后按holdout分组。扩展
  证据见
  `results/smoke/effective_dimension/dev-partitioned-seed23-v1/summary.json`。
  完整7维固定预算最小恢复也已执行：Sobol四盆地和Sobol/Powell混合均未进入
  TPE的较好盆地；`192 TPE + 64 Powell`把loss从`2.8505`降至`0.1481`，但
  最大参数误差保持`0.4266`，中位误差由`0.1672`变差到`0.1782`。因此当前
  没有新优化器获得默认资格，且“更低loss”已被实证否决为参数恢复证据。
  下一步转向真值点局部秩和objective profile，不再扩充优化器名单。
  真值点诊断随后确认局部有效秩仅为6；唯一低于1σ的方向由`k0_4`
  （载荷`0.99999`）主导，且其±0.10条件objective切片均为0。故七参数单点
  恢复资格已失败。后续仅可把`k0_4`作为条件未分辨固定输入传播，不能报告其
  点估计。求解器收敛检查确认`rtol=1e-6`的约`2.5e-7 A`数值地板高于原始
  电流等价阈值；在独立`rtol=1e-8`验收下，既有默认值与真值电流差收敛为
  `5.47e-9 A`，未修改`1e-8 A`门。六参数同预算恢复随后仍失败：TPE与
  TPE+Powell最大无量纲误差分别为`0.4076/0.4041`。因此固定最弱`k0_4`
  不能解除其余参数补偿。补参数重优化profile随后用CN搜索、LSODA逐候选确认：
  `k0_2/k0_3/G_OH/G_O/scaling`在真值±0.10附近均存在`Δloss<1`补偿解；
  `k0_1`仅低侧loss升至`3.99–8.04`，高侧仍可补偿到`<0.05`。因此当前六参数
  都不具备独立点估计资格，最多保留`k0_1`单侧约束假设。优化器路线暂停，
  后续转向可恢复组合和新协议设计。LSODA确认的低-loss补偿位移进一步给出
  首个留出稳定候选：`G_OH-0.1132*log10(k0_1)`（忽略常数）。其系数接近
  `a=0.5, 298.15 K`下冻结M0正向BV尺度
  `RT ln(10)/((1-a)F)=0.1183 eV/dec`，但当时只在单真值/单协议成立；后续
  `a` holdout未全过门，故该接近不能升级为机制标度。
  压力测试确认该组合仅在`mixed_a`局部闭合，移到`center`后仍有`loss<1`
  补偿解；`mixed_b`甚至不能把`k0_4`固定为默认值。因此不存在统一六维线性
  降维。将V4.1推荐的低振幅5 Hz和匹配扫描10 Hz加入联合目标后，`mixed_a`
  最大误差由约`0.404`改善到`0.300`，但`center`仍为`0.373`，六参数恢复门
 仍失败。独立协议重提取显示该局部方向在baseline/lowamp/highfreq间只旋转
 `1.25°/6.82°`，但转移系数holdout中`a=0.35`的经验系数相对冻结M0正向BV
 预测`RT ln(10)/((1-a)F)`偏差`17.79%`，未过预注册`10%`门。因此该组合只
 是有限区域内的经验补偿坐标，不是全局物理标度；温度扰动已停止。V4.1采集
 排序保留，参数点估计资格不变。机器可读登记已冻结为`LOCAL_ONLY`并绑定6个
 来源哈希：`results/smoke/scaling_validation/dev-local-combination-registry-v1/summary.json`；
 后续Agent只能追加独立证据，不能把该登记解释成区域分类器或正式反演授权。

### 8.2 工程待办

- **桌面计算平台方案与压力测试：** 按
  `documents/specifications/2026-08-02-desktop-compute-platform-client-brief.md`
  先审计 React/Tauri、PySide6/Qt 和 MATLAB 备选路线，再决定是否实施。
  本地与远程计算必须共用任务和验收契约；本项不阻塞 A6-v2，也不授权重写
  已验证的科学核心。
- **封装 `oer-ftacv-workflow` Skill（本轮 A6-v2 S1 验收后实施）：**
  采用薄封装，只规定 `oer-wf` 调用顺序、JSON 状态推进、失败停止条件、
  环境配置读取和科学验收边界；不复制 CLI 实现、项目工作流指南或 validator
  的科学逻辑。完成信号为 Skill 结构校验通过，并由一个无当前对话背景的
  Agent 完成一次 `doctor → status/verify` 接续演练且未绕过冻结 Gate。

## 9. 休假期间路线

### 9.1 V1：补录已知元数据

**已完成。** 四组数据已写入列序、`V vs RHE`、`A`、`s` 和声明来源；
预处理保持 `unresolved`。新 A1 证据为 `FAIL_METADATA`，没有获得正式
反演资格。

### 9.2 V2：条件模型可达性

**V2 已完成正式验收；四组均为 `NOT_REACHED_WITHIN_LIBRARY`，下一步进入
V3 残差归因。**

```text
在冻结模型、合理参数范围和当前元数据假设下，
M0 是否能够达到四组实验的 DC/H1–H3 特征区域？
```

输出可达/不可达特征、条件参数集合、模型距离、失败区域和固定输入稳定性；
不得把最优候选写成真实参数。

已完成 V2 设计、机器可读任务契约、实验分析核心拆分、Sobol 参数库与评分
纯函数、可续跑 runner 和第一版独立 validator。绑定代码脏状态指纹的本机
LSODA smoke 完成 4×8 个基础任务，7 个 runner 产物及独立评分重算
`PASS`；证据位于
`results/smoke/conditional_reachability/v2-dirty-6b134cd906f9/`。

首轮 smoke 暴露固定 5 s 稳态松弛与最低 `k0=1e-3 s⁻¹` 的时间尺度冲突。
现已改为累计 5/50/500/5000/50000 s 的有界自适应 Radau 松弛，保持
RHS `1e-8`、覆盖度和守恒门不变。新 4×8 LSODA smoke 为 32/32 成功、
无 BDF 回退；27 个候选在 5 s 收敛，3 个在 50 s、1 个在 500 s、1 个在
5000 s 收敛。独立 validator `PASS`，8 workers wall time 100.44 s。
证据位于
`results/smoke/conditional_reachability/v2-adaptive-steady-state-smoke/`。
该证据关闭初始化阻断点，但不产生科学分类。

独立 validator 已实现正式 stress job 集合、payload/hash、评分和分类
重算；`--rerun-best` 已对四组 smoke 最近候选完成 LSODA 复算。oer-wf
新增专用门和 V2 TaskSpec，本机 wrapper smoke 为 32/32 成功、0 次 BDF
回退、98.45 s；snapshot 驱动的 `wf verify` 13 项检查全部通过。证据：
`results/smoke/conditional_reachability/v2-oer-wf-local-smoke-3/`。

compute commit 已冻结为 `fbda4cff248f`，TaskSpec 已绑定该提交。Legion
正式计算完成 2048 base + 512 stress，共 2560 job；运行时间 7548.53 s。
同一冻结 commit、同一 Legion 环境和单线程数值变量下，独立 validator
重建 job、hash、评分和分类，并对四组最近候选执行 LSODA `rerun-best`，
正式门为 `PASS`。

FT2、FT3、FT4、FT8 均为 `NOT_REACHED_WITHIN_LIBRARY`；最近分数分别为
15.5203、10.4393、5.2607 和 6.4683，512 候选相对前 256 候选的改进分别
为 6.484%、2.418%、0% 和 0%。16 个固定输入压力场景均未改变分类。
这只证明冻结参数库和压力场景未达到预注册特征门，不证明连续参数空间全局
不可达，也不得把最近候选写成真实参数。正式证据：
`results/formal/conditional_reachability/v2-fbda4cf/`。

Mac 跨平台复算未满足逐指标 `1e-8` 等值门；未恢复单线程变量的 Legion
进程也会出现约 `1e-5` 量级漂移。正式单线程 Legion 环境可复现通过。
该差异登记为工作流环境冻结/可移植性问题，不回写科学门、不放宽阈值。

正式前压力测试已关闭两个工作流阻断点：V2 resume 现在声明
`task_spec.json`、`targets.json` 和 `parameter_library.csv`，不再被通用
`job_plan.json` 前提拒绝；清洁门只忽略未跟踪的 `.wf_lock` 与
`results/` 运行产物，其他 Git 变化仍阻断 formal。正式规模为 2560 job，
实际正式 wall time 为约 2.10 小时，与预算一致。

### 9.3 V3：残差归因

按数据集和模式检查 DC、H1–H3 幅值/相位、电位残差位置，以及
`Cdl`、`Ru`、`E0_pre`、`gamma/A` 扰动；四组分别报告。

当前状态：**正式计算与冻结 Legion 验收已完成。** 设计、runner、独立
validator 和 `oer-wf 0.6.8` 专用门已实现。
候选规则固定为每组从前 64 个成功候选中选择最近点和 11 个五维 maximin
代表点；不运行新的 TPE。最终任务哈希下的本机 4-job smoke 为 4/4 成功，
独立 validator 与工作流门均 `PASS`。

正式 compute commit 为 `f82d3918647b`。Legion 以 8 workers、每 worker
单数值库线程完成 48/48 job，wall time 127.60 s；44 个任务使用 LSODA，
4 个在 LSODA 明确失败后按冻结契约回退 BDF。四组各保留 12 个候选。冻结
Legion validator 重建输入哈希、候选选择、残差矩阵、参数关联和压力方向，
并用 LSODA 复算四组最近候选，正式门为 `PASS`。证据：
`results/formal/residual_attribution/v3-f82d391/`。

残差方向在 FT2、FT3 最稳定，各有 11/15 个通道区段达到至少 9/12 候选
同号；FT4 为 5/15，FT8 为 7/15。总体得分的最强条件关联在 FT2、FT3
为 `G_OH`（Spearman ρ=0.538、0.418），在 FT4、FT8 为 `k0_1`
（ρ=0.359、0.428）。这些关联只用于确定 V4 的信息采集优先级，不构成
因果解释、真实参数估计或机理证明。

Mac 在冻结 commit 上重建出完全相同的 48 个候选 ID 和顺序，但 5 个
`selection_min_distance` 相差 1 ULP（`1.11e-16`）；validator 的字节级
JSON 比较因此产生结构假阴性。正式科学口径仍采用同 commit、同环境的
Legion PASS；该可移植性缺陷已进入项目纠错，未调整科学阈值。

一手预处理记录、独立固定参数约束和新增实验条件按项目负责人要求留到恢复
实验后，不阻断 V3；相关证据在 V3 中必须标为 deferred，不能写成已排除。

### 9.4 V4：实验信息设计

**V4.1 已完成正式验收。** 冻结 M0、8 个 V3 条件参数点和 LSODA/BDF
正式后端下，792 个主任务与 80 个半步长任务全部成功；72 个敏感矩阵、
推荐排序、产物哈希和 8 条独立 baseline 复算均通过。

条件模型的两阶段优先级为：

1. `candidate_5hz_amp_008`：保持 5 Hz，将交流振幅设为 0.08 V；
2. `candidate_10hz_matched_scan`：增加 10 Hz 匹配扫描条件。

证据：`results/formal/experiment_design/v4-fbbba8d/`。该排序用于未来
采集协议预注册，不是参数点估计，也未证明真实实验一定提高恢复精度。
恢复实验后仍需补 EIS、面积、负载量、位点量和预处理记录，并用新数据
重开 A6-v2。

Bonke et al. (*JACS*, 2016, DOI `10.1021/jacs.6b10304`) 和 Zhang et al.
(*Current Opinion in Electrochemistry*, 2018, DOI
`10.1016/j.coelec.2018.04.016`) 只作为实验与解释边界的文献依据：独立
约束电活性位点量，保存可评价 H4 以上谐波的原始时间序列，并设置空白基底
和负载量对照。项目不新增 Bonke 风格三参数模型，也不把其有效参数映射为
五步 AEM 的微观参数。文献要求不改变现有 Gate、参数角色或 V4 排序。

### 9.5 V5：计算加速

只有 V2/V3 证明 LSODA 是主要瓶颈时才投入。优先并行和缓存，再评估编译型
刚性求解器；新后端必须重过 A3，CN 只作开发诊断。

## 10. 恢复实验后的路线

### 10.0 接入契约

复制`config/data-contracts/post-experiment-intake-v1.template.json`建立新批次，
在查看特征或反演结果前冻结`training/selection/holdout`角色，再运行
`validate_post_experiment_intake.py`。只有`READY_FOR_A1_AUDIT`可生成
`UNVALIDATED_SEED`；该状态仍不代表Gate A1 PASS。当前固定证据位于
`results/smoke/experiment_intake/template-v1/`。

### 10.1 E1：原始实验记录

保存仪器方法、参比电极、RHE 换算、pH、温度、电流归一化、iR 补偿、
滤波/平均/背景/裁剪、面积、负载量、批次和实验编号。

### 10.2 E2：独立固定输入

先确认数据是总电流还是电流密度，再独立约束 `Ru`、总/面电容、几何面积、
负载量和总/面有效位点量；只报告观测口径支持的`CdlA/GammaA`或面参数。

### 10.3 E3：结构化 FTacV 条件矩阵

至少改变基频、交流振幅和扫描速率，必要时改变电位窗口。具体数值由 V4
预先决定，不能看到结果后再选择。

### 10.4 E4：新条件敏感性与 profile

先比较相关是否降低，再比较单参数和二维目标谷；保留旧 A6 失败证据，
新结论使用独立版本。

### 10.5 E5：A6-v2

使用多真值、无噪声/实测噪声、多 seed 和固定预算；不使用 truth 初始化；
CN 只筛选，由等价后端确认；失败即停止真实反演。

### 10.6 E6–E7：正式反演与结论

只有 A1 和 A6-v2 均通过后，才冻结联合反演，并执行多 seed、bootstrap、
固定输入误差传播和留出验证。

## 11. 运行、测试与远程计算

### 11.1 本机测试

```bash
.venv/bin/python code/python/scripts/run_tests.py code/python/tests -q
.venv/bin/python -m pytest code/web/tests/backend -q
.venv/bin/python code/python/scripts/audit_repository_layout.py
git diff --check
```

### 11.2 远程计算

远程或 GitHub 操作前完整读取：

```text
/Users/liushiyu/gpt/本机环境配置.md
```

原则：

- 使用已有 SSH 别名和项目虚拟环境；
- 正式任务绑定干净 commit；
- 长计算用 `oer-wf` 和 systemd 用户服务；
- 默认 8 workers，每 worker 1 个 BLAS 线程；
- CN 可优先用于开发筛选，但正式结论必须使用通过等价门的后端；
- 不自动创建周期检查，除非用户明确要求；
- 每阶段验证后只提交项目相关文件。

结果分为 `results/smoke/`（流程）、`results/diagnostics/`（条件诊断）和
`results/formal/`（冻结证据）；目录名不能替代验收。

## 12. 后续 Agent 交接

### 12.1 最小阅读顺序

1. 根 `README.md`；
2. 本文件；
3. `documents/plans/2026-07-29-vacation-and-post-experiment-roadmap.md`；
4. 当前任务直接相关的正式结果或 `acceptance.md`；
5. 需要历史原因时再查 `WORK_STATUS.md` 和项目纠错；
6. 需要远程环境时才读本机环境配置。

不要默认读取全部历史 Git、所有正式结果或完整 `WORK_STATUS.md`。

### 12.2 接手前检查

先检查分支、工作树和全量测试，再确认任务阶段、冻结输入/输出/commit/阈值、
A1/A3/A6 边界和用户未提交改动。

### 12.3 结果表达

必须区分观察、工程事实、数值结论、条件科学判断和机理假设；不确定内容
标注“待验证”或“推测”，PASS/提高/等价必须给出可复现证据。

## 13. 项目完成定义

项目完成不是“曲线看起来拟合”，而是同时满足：

1. 实验数据、元数据和预处理可追溯；
2. 物理模型和数值后端通过对应 Gate；
3. 特征和目标函数候选不变且可独立验证；
4. 至少一个参数集通过多真值、含噪、多 seed 合成恢复；
5. 正式真实数据反演绑定冻结配置和干净 commit；
6. 固定输入误差、优化随机性和实验变化进入不确定度；
7. 参数结论不超过数据支持范围；
8. 新数据或留出条件能复核主要结论；
9. Web 只展示通过科学 schema 的结果和限制；
10. 代码、结果、文档和环境可由后续 Agent 重跑。

当前完成度属于“可信底座已建立，正式参数反演尚未获得资格”。
