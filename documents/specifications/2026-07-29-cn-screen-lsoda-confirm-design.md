# CN 筛选与 LSODA 复核设计

## 目标

建立一个可重复、可审计的三阶段合成恢复流程，用 CN 先做低成本筛选，再用
LSODA 做最终复核，避免把数值失败、配置漂移或后验改阈值误判为参数有效。

本轮候选参数限定为 `k0_2`、`k0_3` 和 `G_O`。拟合只使用项目当前可稳定
提取的 H1–H3；CN 不提供高次谐波最终科学证据。

本规范的唯一目标是定义执行标准，不定义新的科学结论。

## 非目标

- 不重新解释现有科学假设。
- 不在运行后调整 scientific gate 阈值。
- 不把 CN 结果直接当作最终冻结结论。
- 不允许因 CN 动态库缺失而自动切换到其他后端。
- 不允许扩展到未批准的参数集或额外实验分支。

## 三阶段流程

### 第一阶段：CN 单参数

分别对 `k0_2`、`k0_3` 和 `G_O` 做单参数 synthetic recovery。每个
synthetic truth 中，其他参数固定为该 truth 的真实值；优化器不得读取自由
参数真值作为初始化。

要求：

- 只使用 CN 后端。
- 若 CN 动态库缺失，必须直接失败，禁止 fallback 到 LSODA 或其他后端。
- 记录每个单参数的完整结果、失败原因和 provenance。
- 该阶段只负责筛查，不负责冻结。

判定：

- 单参数 CN PASS 只能进入第二阶段。
- 单参数 CN FAIL 必须记录原因，并用于剪枝后续组合。

### 第二阶段：CN 两参数

仅对第一阶段通过的参数组成两参数 synthetic recovery。候选组合限定为
`k0_2+k0_3`、`k0_2+G_O` 和 `k0_3+G_O`，任何含单参数 FAIL 项的组合直接
剪枝。

要求：

- 只使用 CN 后端。
- 两后端除 backend 外配置必须完全一致。
- 结果必须与第一阶段共享同一套输入、同一套 frozen scientific gate、同一套 provenance 规则。

判定：

- 两参数 CN PASS 只能进入第三阶段。
- 两参数 CN FAIL 不得被后续 LSODA 结果覆盖为“已通过 CN”。

### 第三阶段：LSODA 复核

对通过前两阶段筛选的候选参数集，用 LSODA 做最终复核。

要求：

- backend 默认使用 `lsoda`。
- 除 backend 外，其余配置必须与 CN 版本完全一致。
- 只允许复核已经晋级的候选，不允许借 LSODA 重新发起新筛选。

判定：

- 只有 LSODA PASS 才能冻结参数集。
- LSODA FAIL 说明该候选不成立，不能以 CN PASS 作为最终冻结依据。

## 配置与追踪

backend 相关信息必须进入以下四类记录：

- `job`
- `config`
- `provenance`
- `resume fingerprint`

同时，所有后端都必须进入隔离输出目录，禁止混写、覆盖或复用同一输出路径。

两后端除 `backend` 字段外，其他配置必须严格一致，包括：

- 参数集合
- 网格或采样定义
- 固定参数
- 随机种子
- scientific gate
- 输出结构
- 日志字段

本轮沿用已冻结的 A6 协议：4 个 feature modes、3 个 synthetic truths、
无噪声与已登记实验噪声、3 个 optimizer seeds、100 trials/job、H1–H3。
CN 阶段不得通过减少 modes、truths、noise levels、seeds 或 trials 获得
表面上的加速。smoke 可以缩小任务，但不得作为科学判定。

## Scientific gate

scientific gate 在本规范中视为冻结配置的一部分。

要求：

- 运行开始前先冻结 gate。
- 运行过程中不得改阈值、不得放宽条件、不得事后补写门槛。
- 任何 PASS 或 FAIL 都必须按冻结时的 gate 判定。

本轮 gate 延续 `a6_recovery_reduced.yaml` 的已批准规则：

- 所有 studies 必须成功；
- 每个自由参数的真值必须落在多 seed 恢复范围内；
- `boundary_hit_rate` 必须为 0；
- 输出结构、有限值和 provenance 必须通过。

## 剪枝规则

单参数失败时，必须剪枝所有包含该参数的组合。

具体要求：

- 若参数 `p` 的单参数 CN FAIL，则所有包含 `p` 的两参数组合直接停止，不得进入 CN 两参数阶段。
- 剪枝结果必须写入 provenance，供后续复核和 resume 使用。
- 只有显式记录的 PASS 才可继续进入下一阶段。

## 测试与验收

验收前必须检查以下项：

1. CN 动态库缺失时确实失败，且无 fallback 路径。
2. CN 与 LSODA 的非 backend 配置完全一致。
3. `job/config/provenance/resume fingerprint` 均包含 backend 信息。
4. 两后端输出目录隔离，互不覆盖。
5. scientific gate 在运行后保持不变。
6. 单参数 FAIL 能正确剪枝包含该参数的组合。
7. 只有 CN PASS 能晋级，只有 LSODA PASS 能冻结。

## 失败退出

以下情况必须立即失败退出，不得降级继续：

- CN 动态库缺失。
- backend 与默认要求冲突且未显式批准。
- 发现运行后 scientific gate 被修改。
- 发现 CN/LSODA 除 backend 外配置不一致。
- 发现输出目录未隔离或已被污染。
- 发现单参数 FAIL 后仍继续评估包含该参数的组合。

失败退出时必须保留日志、配置快照、provenance 和失败原因，不得重跑覆盖证据。

## 交付物

交付时必须包含：

- 规范文件本身。
- 冻结后的 scientific gate 配置快照。
- CN 单参数结果。
- CN 两参数结果。
- LSODA 复核结果。
- provenance 记录。
- resume fingerprint。
- 失败案例与剪枝记录。

最终结论只能按以下顺序成立：

1. CN PASS 仅表示允许晋级。
2. LSODA PASS 才表示参数集可以冻结。
3. 任何未经过 LSODA PASS 的结果都不得写成最终冻结结论。
