# Gate A6 固定预算优化器基准设计

**状态：** 已批准设计，待实施计划
**依据：** Stage 2 CN 两参数恢复 commit `732bf5d` 的 54-study 正式结果
**目标：** 在不增加优化预算、不使用 synthetic truth 初始化的前提下，
判断替代优化器能否比当前 TPE 更可靠地找到狭窄真值盆地。

## 1. 问题定义

三个两参数 `hybrid` CN 任务均通过执行、结构、数值和 provenance 门，但
Recovery Gate v2 scientific FAIL。离线复算显示：

- 54/54 个 study 的真值 objective 均低于 TPE 最优 objective；
- 无噪声真值 objective 为 0；
- 重新计算的 TPE 最优 objective 与归档 `best_value` 一致到
  `5e-13` 以内。

因此当前证据首先指向搜索失败：100-trial TPE 没有进入狭窄的已知更优
盆地。该证据不证明参数可联合识别，也不允许放宽恢复门。

## 2. 设计原则

1. 每种算法每个 study 恰好获得 100 次 optimization objective call。
2. ODE 失败和 Tafel 失败的调用仍计入预算。
3. 算法只接收单位超立方体边界、维数、随机种子和 objective callable。
4. synthetic truth、truth coordinate、truth objective 和旧恢复误差不得传入
   算法。
5. 算法结束后可额外计算一次 truth objective；该调用记为 diagnostic，
   不计入 100 次优化预算，也不得改变返回结果。
6. 参数边界、feature mode、truth library、noise、target seed、CN backend
   和 Recovery Gate v2 均保持不变。
7. 开发集失败后停止，不用确认集反向修改算法。

## 3. 候选方法

### 3.1 基线：TPE

使用现有 Optuna `TPESampler`：

- 100 trials；
- 10 startup trials；
- 与 study seed 相同的 sampler seed；
- 不 enqueue truth 或其他初始参数。

本基准重新运行开发集 TPE，不只引用旧结果，以验证统一 benchmark harness
没有改变基线行为。

### 3.2 推荐：Sobol + bounded pattern search

`sobol_pattern` 分两段：

1. 用 scramble 后的 Sobol 序列在 `[0,1]^d` 评估 64 个点；
2. 从全局阶段最优点开始，用剩余 36 次调用执行有界 coordinate pattern
   search。

局部搜索规则：

- 初始归一化步长 `1/8`；
- 每轮按参数顺序评估 `x-step`、`x+step`，坐标裁剪到 `[0,1]`；
- 重复坐标不重新求值，但预算只能由真实 objective call 消耗；
- 本轮存在改善时移动到最优候选并保持步长；
- 无改善时步长减半；
- 步长小于 `1/1024` 且仍有预算时，从 Sobol 排名中的下一个未局部搜索点
  重启，步长恢复为 `1/8`；
- 局部候选重复且没有可用重启点时，继续生成后续 Sobol 点，直到获得新的
  坐标；
- 达到第 100 次 optimization call 时立即停止。

选择 64 而不是 48 个 Sobol 点，是为了保留 `2^m` 样本的平衡性质。局部
搜索自实现严格预算控制，不依赖 SciPy optimizer 的隐式额外调用。

### 3.3 对照：固定预算 Differential Evolution

`de_fixed` 在单位坐标中运行标准 `DE/rand/1/bin`：

- 本版本只接受 `d=2`，其他维数直接结构 FAIL；
- population size：`10 × d`；当前 `d=2`，即 20；
- 初始 population：20 次调用；
- 4 个完整 generation：每代 20 次调用；
- 总计恰好 100 次调用；
- mutation factor `F=0.8`；
- crossover probability `CR=0.7`；
- 至少一个维度强制交叉；
- 越界坐标反射回 `[0,1]`；
- 不执行 polish；
- 所有随机数来自 study seed。

该实现用于算法对照。任何参数变化都需要新版本设计，不能在开发集运行后
调整。

## 4. 数据划分

### 4.1 开发集

固定三个 study，不根据旧结果的最坏组选择：

| 参数组合 | truth | noise | seed | mode | backend |
|---|---|---:|---:|---|---|
| `k0_2,k0_3` | `center` | 0 | 7 | hybrid | CN |
| `k0_2,G_O` | `center` | 0 | 7 | hybrid | CN |
| `k0_3,G_O` | `center` | 0 | 7 | hybrid | CN |

三种算法共运行 9 个 study、900 次 optimization objective call。开发集只
用于选择一个候选算法。

### 4.2 锁定确认集

完整 Stage 2 包含 54 个 study。开发集占 3 个，剩余 51 个组成锁定确认集：

- 3 个参数组合；
- 3 truths；
- 2 noise 条件；
- 3 seeds；
- 排除每个组合的 `center/no-noise/seed-7`。

我们已经看过旧 TPE 的完整结果，因此该集合不是统计意义上的盲测。其约束
是：候选算法冻结后只运行一次，结果不得用于调算法再重跑同一版本。

## 5. 开发集选择门

每个算法必须先满足执行门：

- 3/3 study 成功；
- 每个 study `optimization_calls=100`；
- 输出有限；
- `n_ode_fail=0`；
- boundary hit rate 0；
- 运行配置和源码 commit 一致。

科学选择门：

- 每个 study、每个自由参数的 normalized bound error `<=0.05`；
- 三个 study 全部通过才有候选资格。

若多个替代算法通过，按以下冻结顺序选择：

1. 三个 study 的 worst parameter error；
2. 三个 study 的 median parameter error；
3. objective regret：
   `best_objective - truth_objective` 的最大值；
4. 完全相同则选择 `sobol_pattern`，因为其全局覆盖可直接审计。

TPE 是基线，不作为“新候选”进入确认集。若两个替代算法均未通过，停止，
不运行确认集，不增加预算。

## 6. 确认集与晋级规则

开发集选出的唯一算法在 51 个锁定 study 上运行。将开发集和确认集结果合并
为每个参数组合完整的 18-study 恢复结果，再应用未修改的 Recovery Gate v2：

- group median normalized error `<=0.025`；
- group max normalized error `<=0.05`；
- seed normalized dispersion `<=0.05`；
- boundary hit rate 0；
- studies 全成功；
- `hybrid` 为唯一 mode。

每个参数组合独立判定：

- PASS：允许建立同配置 LSODA 确认任务；
- FAIL：该组合停止，不因其他组合 PASS 而恢复资格。

只有至少一个组合通过 CN v2，才进入 LSODA。三项均失败时，停止 Gate A6
多参数恢复，转向目标函数几何、参数重参数化或新增实验信息，不启动真实数据
正式 TPE。

## 7. 软件边界

### 7.1 优化器接口

新增统一接口，输入仅包含：

```text
objective(encoded_vector) -> finite loss
parameter specs
budget = 100
seed
```

返回：

```text
optimizer name and version
best encoded vector and decoded parameters
best objective
optimization call count
ODE/Tafel failure counts
evaluation trace
termination reason
```

算法适配器不得导入 truth library，也不得接收 target metadata。

### 7.2 Benchmark runner

独立 benchmark runner 负责：

1. 从现有 recovery job contract 构造 target；
2. 调用三个 optimizer adapter；
3. 在算法返回后计算 recovery metrics 和 truth objective；
4. 原子写入增量结果；
5. 支持严格 fingerprint 的 job-level resume；
6. 区分 execution status 与 scientific selection gate。

不直接改写正式 recovery runner 的默认 optimizer。候选通过确认集后，再
单独设计如何接入正式反演。

## 8. 输出与留痕

每次 benchmark 至少输出：

- `benchmark_plan.json`
- `results.jsonl`
- `evaluations.jsonl`
- `summary.json`
- `selection.json`
- `STATUS.json`
- `task_spec.snapshot.yaml`

每个 job 记录：

- source commit、dirty state、backend 和动态库路径；
- optimizer 名称、冻结超参数和 seed；
- truth/noise/target seed，但 optimizer adapter 不接收 truth；
- 100 次 optimization call 的坐标、loss 和顺序；
- 单独标注的 post-run truth objective；
- best params、参数误差、边界命中和失败计数；
- runtime 和 job input hash。

`evaluations.jsonl` 可能较大，但开发集与 51-study 确认集规模可控。正式归档
保留完整 trace；Git 只提交精简 summary、selection、验收文档和哈希。

## 9. 测试要求

### 9.1 单元测试

- 三种算法在常数、凸二次和边界最优函数上恰好调用 100 次；
- 同 seed 逐点评估 trace 相同；
- 不同 seed 的随机算法 trace 不同；
- Sobol 重复坐标不消耗额外调用；
- DE 越界反射始终落在 `[0,1]`；
- objective 非有限值或异常被记为失败且仍计入预算；
- optimizer adapter 的签名不包含 truth；
- post-run truth diagnostic 不改变 best result 或 optimization call count。

### 9.2 集成测试

- CN smoke：1 pair × 3 algorithms × 1 study × 100 calls，使用缩小的
  256-point forward grid；smoke 不降低算法预算；
- 三个输出流可中断后按 job hash 恢复；
- backend、optimizer、budget 或算法超参数变化时 resume fingerprint 改变；
- 旧 TPE recovery 结果不能混入 benchmark checkpoint；
- summary 的 job 数、evaluation 数和每 job call count 一致。

## 10. 压力测试

### 数据泄漏

风险：runner 已知 truth，错误地把 truth 坐标传给 optimizer。

控制：

- adapter 只接收 callable、specs、budget 和 seed；
- 测试用 sentinel truth 检查输入和首批点；
- 禁止 enqueue、warm start、边界收窄或以 truth 选择初始点；
- truth objective 只在 optimizer 返回后计算。

### 预算漂移

风险：SciPy 或局部算法隐式增加函数调用。

控制：

- 两个候选算法使用显式循环；
- `BudgetedObjective` 统一计数；
- 第 101 次 optimization call 直接失败；
- diagnostic call 使用独立计数器。

unexpected exception 或非有限 objective 会先消耗并记录当前调用，然后使
该 job numerical FAIL；算法不得用固定罚值掩盖未知错误。模型定义内已有的
ODE/Tafel 有限罚值仍按普通 objective 处理。

### 事后选算法

风险：查看确认集后调整 Sobol 点数、DE 参数或排序。

控制：

- 本文和实现 commit 先于开发集；
- 开发集只允许一次正式运行；
- 选择结果冻结到 `selection.json`；
- 确认集只接受 selection 指定的单一算法和 commit。

### 将优化成功误写成可识别

风险：算法恢复真值后宣称真实数据参数可信。

控制：

- benchmark 只验证 synthetic 搜索能力；
- CN 只作筛选；
- LSODA、真实数据模型失配和实验不确定度仍为独立后续门；
- 结论限定为“在当前 synthetic contract 下达到恢复门”。

## 11. 失败退出

出现以下任一情况立即停止依赖阶段：

- 开发集两个替代算法均未通过；
- 任一算法未严格满足 100-call 预算；
- 发现 truth 泄漏、fingerprint 混用或非有限结果；
- benchmark harness 不能复现开发集 TPE 基线；
- 确认集三组合全部 scientific FAIL；
- CN 候选在 LSODA 确认中失败。

任何失败都保留证据，不修改本设计的预算、阈值、数据划分或算法超参数。
