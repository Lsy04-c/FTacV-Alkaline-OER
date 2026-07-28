# Gate A6 Recovery Gate v2 设计提案

**状态：** 已按版本化方案实现并完成离线复核；未启动新计算
**适用范围：** Gate A6 合成数据恢复的 feature mode 筛选
**不适用范围：** 真实数据参数置信区间、模型正确性证明、多参数联合可辨识性证明

## 1. 目的

现有 scientific gate 使用
`seed_min <= truth <= seed_max` 作为硬门，并把四种 feature mode
捆绑判定。Stage 1 结果证明该规则不能稳定表达恢复精度：

- 三个 seed 都非常接近真值但位于同一侧时会 FAIL；
- 离散度很大、仅因范围跨过真值时可能 PASS；
- 一个较差 mode 会否决同一参数下表现良好的 mode。

v2 的目标是按 `(parameter set, feature_mode)` 独立判断恢复误差和
seed 稳定性，用于选择进入下一阶段的候选。v1 的三项 scientific FAIL
永久保留，不得回写为 PASS。

## 2. 冻结指标与阈值

所有误差均在参数边界归一化坐标中计算。阈值在实现和任何新计算前冻结：

| 指标 | 硬门 | 来源 |
|---|---:|---|
| 每组 seed 中位误差 | `<= 0.025` | 既有 41 点 profile 的一格 `1 / 40` |
| 每组 seed 最大误差 | `<= 0.050` | 两个 profile 网格间隔 |
| 每组 seed 坐标极差 | `<= 0.050` | 两个 profile 网格间隔 |
| boundary hit rate | `= 0` | 既有 A6 边界门 |
| studies success | 全部成功 | 既有 A6 执行门 |

`truth_covered_by_seed_range` 保留为诊断指标，不再作为硬门。

这里的 profile 网格只提供工程分辨率基准，不是统计置信区间。通过上述门
只能称为“在当前单参数同模型合成恢复中达到预注册工程精度”。

## 3. 分层判定

每个 `(parameter set, feature_mode)` 必须独立覆盖：

- 3 个 truth；
- 2 个 noise 条件；
- 每组 3 个 seed；
- 每个 study 100 trials；
- 共 6 组、18 个 study。

任一组违反硬门，则该 mode 对该 parameter set FAIL。不能用其他组的均值
抵消最坏组，也不能把四种 mode 合并成一个总门。

参数进入下一阶段的最低条件：

1. 至少一个非 `legacy` mode 通过全部 6 组；
2. 结构、数值、provenance 和 backend 检查通过；
3. 候选按 `worst_group_max_error` 从小到大排序；
4. 第一项相同时，依次比较 `worst_group_median_error`、
   `worst_group_seed_dispersion`；
5. 完全相同时使用固定顺序
   `complex_snr > hybrid > lockin_only > legacy`，不得在看结果后改顺序。

`legacy` 只作为基线，不得成为唯一晋级依据。

## 4. Stage 1 归档离线审计

数据来源：

- commit `d0defa75017191302b95269bc5cc701d48df652c`
- backend `cn`
- 每参数 24 groups、72 studies
- 三份归档均 `STATUS=SUCCESS`、`dirty=false`、`n_ode_fail=0`

下表是对现有 `results.jsonl` 的离线重算；数值为六组中的最坏值：

| 参数 | mode | 最大误差 | 中位误差 | seed 极差 | v2 候选结果 |
|---|---|---:|---:|---:|---|
| `k0_2` | complex_snr | 0.031573 | 0.030550 | 0.001302 | FAIL |
| `k0_2` | hybrid | 0.001061 | 0.000894 | 0.000782 | PASS |
| `k0_2` | legacy | 0.002080 | 0.001903 | 0.000782 | PASS |
| `k0_2` | lockin_only | 0.002026 | 0.001874 | 0.001228 | PASS |
| `k0_3` | complex_snr | 0.001867 | 0.001100 | 0.002319 | PASS |
| `k0_3` | hybrid | 0.001867 | 0.001100 | 0.002573 | PASS |
| `k0_3` | legacy | 0.001867 | 0.001394 | 0.001893 | PASS |
| `k0_3` | lockin_only | 0.001867 | 0.001100 | 0.002573 | PASS |
| `G_O` | complex_snr | 0.149151 | 0.000499 | 0.149490 | FAIL |
| `G_O` | hybrid | 0.002237 | 0.000499 | 0.002439 | PASS |
| `G_O` | legacy | 0.001120 | 0.001044 | 0.001300 | PASS |
| `G_O` | lockin_only | 0.002237 | 0.000567 | 0.002439 | PASS |

这是“如果事前采用 v2，离线会得到的候选结果”，不是对 v1 历史结论的
重分类。按排序规则，当前单参数候选为：

- `k0_2`: `hybrid`
- `k0_3`: `complex_snr`
- `G_O`: `hybrid`

这三项候选使用不同 mode，因此不能直接组成一个共享 mode 的多参数任务。
在建立 Stage 2 前必须先冻结“每个参数可否使用不同特征目标”或“所有参数
必须共享一个 mode”的架构选择。

## 5. 压力测试

### 5.1 防止事后调门

- 阈值来自已存在的 41 点 profile 配置；
- v1 FAIL 保留；
- v2 必须有新版本号和独立结果字段；
- v2 生效前形成 commit，后续归档保存该 commit 和 task snapshot。

### 5.2 防止宽松均值掩盖失败

- 所有硬门按每个 truth/noise group 检查；
- mode 的结果取六组最坏值；
- 禁止对 18 个 study 只计算一个总平均。

### 5.3 防止把优化稳定性当成参数可信度

- 三个 seed 接近只说明优化器在当前目标上稳定；
- 同一 forward model 生成和反演属于 inverse crime；
- 单参数恢复未测试参数耦合；
- CN PASS 后仍需 LSODA 同配置确认；
- 真实实验结果必须另做不确定性与模型失配验证。

### 5.4 Tafel 失败计数

Stage 1 存在 trial 级 `n_tafel_fail`，但最终 study 均成功且最优解有限。
当前没有事前批准的 trial 失败率阈值，因此 v2 只把它作为诊断量，不新增
硬门。实现时必须汇总每个 mode 的失败数和总 trial 数；若 LSODA 复核显示
失败集中在候选邻域，再单独设计数值域门，不能用本轮计数反推阈值。

### 5.5 失败退出

出现以下任一情况立即停止依赖阶段：

- 归档字段不足以重算归一化误差或 seed 极差；
- snapshot 与归档 commit/backend 不一致；
- 非有限值、重复 job、缺 group 或 study 失败；
- v2 实现结果与独立离线审计不一致；
- CN 候选在 LSODA 同配置确认中失败。

## 6. 实施边界

批准后按测试驱动实施：

1. 给 `recovery_gate` 增加显式 `gate_version: 2`，不静默改变 v1；
2. v1 继续按原逻辑验收历史任务；
3. v2 输出每个 mode 的独立检查和最坏组指标；
4. 增加真实子集测试，覆盖“同侧高精度”“跨真值但高离散”“单 mode
   失败不否决其他 mode”；
5. 用三份归档离线验收，暂不启动计算；
6. 解决共享 mode 架构选择后，才允许生成 Stage 2 CN spec；
7. CN 只筛选，最终候选必须通过 LSODA 确认。

## 7. 已冻结决策

1. 采用上述 v2 指标和阈值，v1 保持默认以兼容历史任务；
2. Stage 2 暂不引入参数专属复合目标，所有参数共享一个 feature mode；
3. 以同时通过三个单参数门的 `hybrid` 作为 Stage 2 唯一 mode；
4. 后续结果若否定该设计，建立新版本和新预注册任务，不回写 v2。

Stage 2 已据此建立三份两参数 CN 筛选 spec，均只运行 `hybrid`：

- `config/oer-wf/examples/a6_recovery_cn_k0_2_k0_3.yaml`
- `config/oer-wf/examples/a6_recovery_cn_k0_2_G_O.yaml`
- `config/oer-wf/examples/a6_recovery_cn_k0_3_G_O.yaml`
