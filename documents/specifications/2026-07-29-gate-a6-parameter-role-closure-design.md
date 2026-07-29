# Gate A6 参数角色冻结与失败关闭设计

## 1. 目标

Gate A6 用现有正式证据冻结当前反演允许使用的参数角色，并关闭已经失败的
多参数恢复路线。本阶段不运行新 ODE、优化器或 TPE。

正式状态为 `FAIL_RECOVERY`，当前自由参数集为空：

```text
free_parameters = []
eligible_for_real_inversion = false
```

`FAIL_RECOVERY` 表示没有参数组合通过预注册恢复门。它不等于数学上的结构
不可识别，也不证明任何固定值准确。

## 2. 设计选择

### 2.1 采用：证据分级的机器可读角色登记表

登记表覆盖 13 个模型参数，每个参数只出现一次。角色取值：

```text
fixed
narrow_prior
free
diagnostic_only
```

每条记录同时保存固定原因、证据来源、证据强度、允许表述和禁止表述。
独立 validator 重算集合、文件哈希和角色门。

### 2.2 拒绝：根据局部敏感性直接选择自由参数

局部敏感度只能显示小扰动方向，不能证明多参数、含噪和多 seed 恢复稳定。
现有两参数确认集已经反驳“局部独立即可自由”的推断。

### 2.3 拒绝：继续增加预算或更换优化器

Sobol 锁定确认集已按预注册分支要求停止。继续修改算法、预算或阈值会建立
新研究问题，不能用于改写当前 Gate A6。

## 3. 角色语义

### 3.1 `fixed`

`fixed` 只表示当前反演运行时不优化该参数。登记表必须用
`fixing_basis` 区分：

```text
external_input
calibrated_input
model_assumption
low_sensitivity
coupling_control
```

固定参数仍可有未知误差。没有固定值扰动鲁棒性证据时，禁止把
`fixed` 写成“已知准确”或“没有不确定度”。

### 3.2 `narrow_prior`

只有满足下列至少一项时才能使用：

1. 独立实验或外部可信来源给出中心和宽度；
2. 固定值扰动压力测试证明该宽度内的自由参数结论稳定。

当前没有参数满足该门，`narrow_prior_parameters=[]`。

### 3.3 `free`

参数必须同时满足：

1. 目标函数和特征契约已冻结；
2. 多真值、含噪、多 seed 合成恢复通过；
3. 边界命中、归一化误差和 seed 离散度通过预注册门；
4. 若使用 CN 筛选，LSODA 同配置确认通过。

当前没有参数组合满足全部条件，`free_parameters=[]`。

### 3.4 `diagnostic_only`

该角色允许 profile、敏感性、残差归因和实验设计分析，禁止把点估计写成
可信反演参数。它表示当前证据不足，不表示数学上不可识别。

## 4. 当前参数映射

| 参数 | 角色 | fixing_basis / 直接原因 |
|---|---|---|
| `A` | `fixed` | `external_input`；与 `gamma` 补偿，几何输入需单独记录 |
| `Cdl` | `fixed` | `calibrated_input`；当前不进入联合恢复 |
| `Ru` | `fixed` | `calibrated_input`；当前不进入联合恢复 |
| `E0_pre` | `fixed` | `calibrated_input`；预氧化输入 |
| `k0_pre` | `fixed` | `calibrated_input`；预氧化输入 |
| `gamma` | `fixed` | `coupling_control`；与 `A` 强补偿，现值仍是待验证输入 |
| `k0_4` | `fixed` | `low_sensitivity`；正式敏感性中缺少可用响应 |
| `scaling_OOH_OH` | `fixed` | `coupling_control`；与 `k0_3` 局部共线 |
| `k0_1` | `diagnostic_only` | 四模式单参数 profile 均有宽广近简并区 |
| `k0_2` | `diagnostic_only` | 含该参数的两个 Sobol 两参数确认组合均失败 |
| `k0_3` | `diagnostic_only` | 含该参数的两个 Sobol 两参数确认组合均失败 |
| `G_OH` | `diagnostic_only` | 与 `G_O`、`k0_3` 的二维 profile 强补偿；未进入通过的联合恢复 |
| `G_O` | `diagnostic_only` | 含该参数的两个 Sobol 两参数确认组合均失败 |

这些角色是当前工作流的操作限制，不是材料体系的普适物理结论。

## 5. 证据层级

登记表只引用已冻结文件：

1. 四模式正式敏感性与耦合证据；
2. 单参数 objective profile；
3. 二维 profile 的正式项目记录；
4. 三参数 LSODA 合成恢复失败；
5. 两参数 CN TPE 恢复失败；
6. 固定预算优化器开发门；
7. Sobol 锁定确认集。

每条证据记录项目相对路径和 SHA-256。validator 不信任登记表自报哈希。
Mac 外部原始归档只能作为补充位置；Git 内正式验收文件承担可复核结论。

## 6. 交付物

```text
config/parameter-roles/gate-a6-parameter-roles.json
code/python/scripts/validate_gate_a6_parameter_roles.py
code/python/tests/test_gate_a6_parameter_roles.py
results/formal/identifiability/gate-a6-closure-<commit>/
```

正式目录包含：

```text
parameter_roles.snapshot.json
validation_report.json
run_manifest.json
acceptance.md
```

## 7. Validator 规则

结构门：

- 精确覆盖 13 个参数，无缺失、重复或未知参数；
- 角色和 `fixing_basis` 取值合法；
- 所有证据路径为项目相对路径，文件存在且 SHA-256 匹配；
- manifest 绑定干净 commit；
- 快照、报告和 manifest 为有限规范 JSON。

科学口径门：

- `gate=FAIL_RECOVERY`；
- `eligible_for_real_inversion=false`；
- `free_parameters=[]`；
- `narrow_prior_parameters=[]`；
- 每个 `fixed` 参数明确声明“固定不等于准确”；
- 每个 `diagnostic_only` 参数禁止点估计解释；
- 不得出现 `structurally_unidentifiable=true`；
- Sobol 确认集的 eligible pairs 必须为空。

结构错误返回 `FAIL_STRUCTURE`，非有限值返回 `FAIL_NUMERICAL`，角色或科学
口径漂移返回 `FAIL_ROLE_CONTRACT`。

## 8. 测试

测试覆盖：

- 完整登记表通过；
- 参数缺失、重复、未知；
- 非法角色和 fixing basis；
- 证据文件缺失或哈希被修改；
- 非空 `free_parameters`；
- 无依据的 `narrow_prior`；
- 把 `fixed` 写成准确；
- 把 `diagnostic_only` 写成结构不可识别；
- eligible pairs 非空；
- summary、snapshot 或 manifest 篡改；
- 非有限 JSON。

全量测试通过后才生成一次正式关闭归档。

## 9. 允许与禁止的后续行动

允许：

- 用 diagnostic-only 参数设计新实验或重参数化候选；
- 获得独立测量后提出带版本的新 narrow-prior 设计；
- 将组合参数作为新变量另立 profile 和恢复门。

禁止：

- 在当前路线中继续增加优化预算或更换算法；
- 启动真实数据正式 TPE；
- 报告未通过恢复门的参数点估计；
- 把 `FAIL_RECOVERY` 改写成结构不可识别；
- 用运行时固定值掩盖其输入不确定度。
