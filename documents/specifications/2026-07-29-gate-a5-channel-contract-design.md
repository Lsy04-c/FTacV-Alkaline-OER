# Gate A5 特征通道与损失归一化契约设计

## 1. 目标

Gate A5 冻结每次反演实际使用的观测通道、目标侧权重、有效点掩码、排除原因
和损失归一化因子。任何候选参数只能改变预测值，不能改变观测集合或权重。

本阶段不比较优化算法，不证明反演精度提高，也不重新打开 Gate A6。

## 2. 已确认的缺口

当前 `InversionConfig.fit_harmonics` 只表示请求的谐波：

- legacy 模式直接使用请求通道；
- Complex-SNR 根据目标 SNR 生成权重，低于阈值时权重为 0，但没有记录
  通道已失活；
- lock-in 使用目标与候选的 `valid_mask` 和有限值交集。候选出现 NaN 或
  有效区变化时，相应点会被静默跳过；
- 最终损失除以 `2 + len(fit_harmonics)`，不是实际活动观测块的冻结权重和。

因此当前结果不能完整回答：

1. 哪个通道实际进入了目标函数；
2. 为什么某个通道被排除；
3. 每个通道用了多少点、权重是多少；
4. 两个候选是否在同一观测集合上评价。

## 3. 方案比较

### 方案 A：只在结果中补写请求谐波

拒绝。它不能区分零权重、缺失目标和候选侧静默跳点。

### 方案 B：继续按候选有限值动态取交集，但记录每次点数

拒绝。记录可以暴露漂移，但目标函数本身仍随候选改变。

### 方案 C：目标侧冻结通道契约，候选侧缺失固定失败

采用。契约在 `InversionObjective` 初始化时只从目标和配置生成。候选评价
只读取该契约，不重新选择通道、权重或掩码。

## 4. 通道记录

每个观测块使用一条记录：

```text
channel_id
block
harmonic
role
requested
available
active
target_weight
loss_weight
n_points
mask_sha256
exclusion_reason
```

`block` 取值：

```text
dc
legacy_amplitude
complex_amplitude
complex_phase
lockin_amplitude
lockin_phase
tafel
```

`role` 取值：

```text
global
common
dataset_specific
physical
```

`exclusion_reason` 只能取：

```text
not_requested
mode_disabled
target_missing
target_shape_mismatch
target_nonfinite
below_snr_floor
insufficient_valid_points
not_applicable
```

`target_weight` 保存目标侧可靠性权重；`loss_weight` 保存应用
`phase_weight` 后实际进入分子和分母的权重。活动记录的
`exclusion_reason` 必须为 `null`，非活动记录必须有明确原因。

## 5. 目标侧冻结规则

### 5.1 DC

DC 始终请求。目标数组必须与 `e_grid` 等长且全部有限；否则构造 objective
时失败，不进入优化。

### 5.2 Legacy envelope

只对 `fit_harmonics` 中的通道请求。目标数组必须与 `e_grid` 等长且全部
有限。活动权重固定为 1。

### 5.3 Complex-SNR

目标的 amplitude、phase、SNR 必须覆盖请求的最高谐波。每个请求通道：

- 数值缺失或非有限：非活动并记录原因；
- `snr_weights(target_snr) == 0`：非活动，原因 `below_snr_floor`；
- 其他情况：amplitude 与 phase 均活动，目标权重为冻结的 SNR 权重。

权重只从目标计算一次，不依赖候选。

### 5.4 Lock-in

每个请求谐波分别冻结：

```text
target.valid_mask
& finite(target amplitude)
& finite(target phase)
```

至少两个点才活动。内部契约保存布尔掩码；可序列化证据只保存点数和掩码
SHA-256。

候选的 `valid_mask` 不参与重新选择。候选在冻结点上缺失、非有限或形状不符
时，整次候选评价进入固定特征失败惩罚。

### 5.5 Tafel

目标 Tafel 为有限数时活动；`None` 时非活动，原因 `not_applicable`。

## 6. 候选侧失败

新增 `feature_fail_penalty`，默认等于 `ode_penalty`。任一活动观测块出现：

- 缺少字段；
- 数组长度错误；
- 冻结点上非有限；
- lock-in 冻结点在候选中无效；

则：

1. `n_feature_fail += 1`；
2. 本次 objective 返回固定 `feature_fail_penalty`；
3. `loss_components["feature_failure"]` 保存该惩罚；
4. 不缩小掩码、不填零、不使用部分残差。

ODE 失败和特征失败分别计数。

## 7. 损失与归一化

各块先计算自身均方残差，再乘冻结目标权重：

- DC 权重 1；
- legacy amplitude 权重 1；
- complex/lock-in amplitude 权重为目标通道权重；
- phase 权重为 `target_weight * phase_weight`；
- Tafel 权重 1。

总损失：

```text
sum(weighted block losses) / sum(active block weights)
```

分母在 objective 初始化时冻结。任何候选都必须使用同一个
`normalization_weight_sum`。

`hybrid` 使用 complex 与 lock-in 的活动块并集。不同模式仍不能仅凭
`total_loss` 横向排名；模式比较继续使用共同外部指标。

## 8. 结果与证据

`InversionResult` 新增：

```text
n_feature_fail
channel_contract
channel_contract_sha256
normalization_weight_sum
```

正式 A5 runner 不运行 TPE。它对 FT2、FT3、FT4、FT8 和四种模式：

1. 构建目标侧通道契约；
2. 验证契约只依赖目标和配置；
3. 用两个不同有限候选证明契约哈希和分母不变；
4. 注入候选缺失值，证明固定惩罚而非静默跳点；
5. 输出活动/排除通道、权重、点数和原因。

输出：

```text
channel_contracts.jsonl
candidate_invariance.jsonl
gate_a5_summary.json
run_manifest.json
```

## 9. Gate A5 阈值

- 4 datasets × 4 modes = 16 份唯一契约；
- 每份契约哈希非空且可独立重算；
- 所有活动权重有限且严格正；
- 所有非活动块具有合法排除原因；
- 冻结分母有限且严格正；
- 两个有限候选的契约哈希和分母完全相同；
- 注入缺失值后 `n_feature_fail` 增加 1，返回固定惩罚；
- 任何候选不得改变活动通道、权重、掩码或点数；
- runner 与独立 validator 结论一致。

## 10. 数据边界

四份实验数据只用于冻结相对谐波/锁相信号通道，不运行参数优化，也不解释
电流、电位或时间的物理单位。Gate A1 的 `FAIL_METADATA` 继续禁止真实数据
正式反演。

## 11. 失败出口

- `FAIL_STRUCTURE`：修复证据链，不改变通道规则。
- `FAIL_NUMERICAL`：停止，不通过动态删点或补零修复。
- `FAIL_CONTRACT`：目标集合或权重随候选改变，停止进入层级 B。
- `PASS`：关闭 Gate A5 的特征与损失冻结；Gate A6 历史 FAIL 和 A1
  `FAIL_METADATA` 均保持。

## 12. 设计自审

- 通道选择、权重和掩码全部来自目标侧。
- 候选缺失不再改变观测集合。
- 零权重通道具有明确排除原因。
- 分母与活动块权重一致且在候选间固定。
- 正式门不运行 TPE，不把执行成功写成精度提高。
- 未修改 A4、A6 或历史 A5 网格归档。
