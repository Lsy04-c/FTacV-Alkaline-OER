# OER-FTAcV 恢复实验接入契约设计

状态：已实施；空模板验收通过，等待真实数据
日期：2026-08-02
上游：V4.1 实验信息设计、Gate A1 v1、A6 `FAIL_RECOVERY`

## 1. 目标

本契约在新实验进入 Gate A1 前检查资料完整性，并在任何反演前冻结数据角色。
它回答三个问题：原始文件和实验记录是否一一对应；关键元数据与独立输入是否
有可追溯来源；新批次是否具备生成独立 Gate A1 注册表的条件。

本契约不评价谐波质量、模型拟合或参数可辨识性。`READY_FOR_A1_AUDIT`仅表示
资料可以进入新批次 A1 审计，不表示 A1、A6 或真实反演通过。

## 2. 与现有 Gate 的边界

现有 Gate A1 v1 固定 FT2、FT3、FT4、FT8、65,536 行和对应哈希。未来实验
可能改变采样点数、频率、振幅和文件数量，因此不得把新数据追加到旧注册表，
也不得修改旧阈值使其兼容新数据。

数据流固定为：

```text
新实验原始文件与记录
        ↓
实验接入清单及 validator
        ↓ READY_FOR_A1_AUDIT
新批次 Gate A1 注册表与数值审计
        ↓ A1 PASS
E2 独立输入验收
        ↓
E4 敏感性/profile → E5 A6-v2
        ↓ PASS
真实数据联合反演
```

任何上游失败都会停止依赖步骤。下游拟合结果不得反向补写元数据或改变数据
角色。

## 3. 冻结实验角色

恢复实验的最小 FTacV 条件矩阵采用 V4.1 排序，并在查看新数据前冻结角色：

| 条件 | 名义设置 | 初始分析角色 | 用途 |
|---|---|---|---|
| `baseline_5hz_amp016` | 5 Hz、0.16 V | `training` | 建立新批次基线与目标 |
| `lowamp_5hz_amp008` | 5 Hz、0.08 V | `selection` | 检查低振幅是否降低补偿 |
| `highfreq_10hz_amp016` | 10 Hz、0.16 V，匹配扫描 | `holdout` | 只评价冻结模型的跨协议预测 |

`holdout`在评价前不能参与参数选择、边界调整、特征选择或模型扩展。若三条件
通过后要把全部数据用于最终联合反演，必须另设独立批次或预注册外部验证条件；
不能把已经使用过的 highfreq 数据继续称为留出验证。

名义设置不是文件真值。validator只检查采集计划和声明；后续 Gate A1 从应用
电位与时间列独立重算频率、振幅、扫描速率和采样质量。

## 4. 接入清单结构

仓库提供一个不含真实路径和数值的版本化模板。恢复实验后复制模板并生成新
`intake_id`，不得覆盖旧批次。

### 4.1 批次字段

- `schema_version`、`intake_id`、采集日期和操作员记录；
- 电极批次、催化剂批次、基底和电解液批次；
- 数据角色冻结时间、冻结人和角色表版本；
- 原始数据目录只保存项目相对路径。

### 4.2 每个数据集字段

- `collection_state=planned|collected`；
- `dataset_id`、`condition_id`、`analysis_role`、实验编号和批次编号；
- 原始时间序列路径、SHA-256、字节数和列契约；
- 对应仪器方法文件路径与 SHA-256；
- 原参比电极、RHE 换算方法和换算输入；
- pH、温度、电解液组成和浓度；
- iR 补偿是否启用、补偿比例和来源；
- 滤波、平滑、平均、背景扣除、裁剪、降采样和电流归一化记录；
- 电流口径：总电流或电流密度；
- 空白基底、负载量对照或正式样品的样品角色。

布尔字段必须明确为 `true` 或 `false`；未知信息使用 `null`并附
`source_kind=unresolved`，不得用 `false` 表示“不知道”。

`planned`记录只冻结条件与角色，允许文件和实验元数据为空；`collected`记录
声明实验已经发生，必须提供真实文件和关键元数据。把已采集数据重新标为
`planned`以回避失败属于结构错误。

### 4.3 独立输入字段

`Ru`、`Cdl`、几何面积、催化剂负载量和有效位点量分别记录：

- 数值、单位和不确定度；
- 测量方法；
- 来源文件路径与 SHA-256；
- 是否独立于待反演 FTacV 数据；
- 适用的数据集或批次。

缺少有效位点量不自动阻止 A1，但会冻结报告限制：禁止把`GammaA`换算为面位点
密度或单个位点周转量。用总金属负载量替代有效位点量属于结构错误。

## 5. 状态机

validator只输出四种状态：

| 状态 | 条件 | 下一动作 |
|---|---|---|
| `WAITING_FOR_DATA` | 模板尚无真实文件或声明 | 等待采集，不运行 A1 |
| `FAIL_STRUCTURE` | schema、角色、路径、哈希字段或一一对应关系错误 | 修正清单或找回原始文件 |
| `FAIL_METADATA` | 文件齐全但关键实验元数据无可靠来源 | 补一手记录，不推断默认值 |
| `READY_FOR_A1_AUDIT` | 接入结构与关键元数据完整 | 生成新批次 A1 注册表 |

状态优先级为`FAIL_STRUCTURE`高于`FAIL_METADATA`，两者都高于
`WAITING_FOR_DATA`。只有所有必需记录仍为`planned`，或已收集记录均合格但
尚有必需条件未采集时，才输出`WAITING_FOR_DATA`。只要记录已标为
`collected`但文件缺失，就属于`FAIL_STRUCTURE`，不能退回等待状态。

## 6. 验收规则

### 6.1 结构门

- 三个预注册 FTacV 条件各有且仅有一个主要数据集记录；额外重复或对照使用
  独立dataset ID和样品角色，不取代三个主要记录；
- `training/selection/holdout`角色一一对应且不能重复；
- dataset、experiment、batch 和 condition ID 唯一；
- 路径为项目相对路径，不含`..`，不指向结果目录；
- 声明存在的原始文件和方法文件可读取且哈希一致；
- 原始文件与方法文件一一关联；
- source 文件不得位于`results/`或临时目录。

### 6.2 元数据门

以下字段必须来自`file_observed`、`derived`或`externally_declared`：

- 三列含义与单位；
- 原参比电极与 RHE 换算记录；
- pH、温度和电解液；
- iR 补偿；
- 全部仪器与导出预处理；
- 总电流/电流密度口径；
- 实验编号、样品编号和批次。

未知预处理会产生`FAIL_METADATA`。项目负责人声明可作为
`externally_declared`，但必须记录声明人是否为原实验操作员。

### 6.3 数据角色泄漏门

- 角色冻结时间必须早于首次特征、profile 或反演结果；
- `holdout`不得出现在训练、选择或参数边界来源中；
- 修改角色必须生成新 intake 版本，并保留旧版本；
- 发现泄漏后，原 holdout 永久降级为 development 数据，必须另采验证数据。

## 7. 输出

validator生成：

- `intake_summary.json`：状态、错误分类、缺失字段、来源哈希和下一动作；
- `acceptance.md`：用户可读的允许/禁止事项；
- `a1_seed.json`：仅在`READY_FOR_A1_AUDIT`时生成的新批次 A1 注册表种子。

输出写入新的批次目录，不覆盖输入清单。所有 JSON 拒绝 NaN、Inf 和重复 ID。

## 8. 压力测试

- 把未知预处理写成`false`：validator必须判`FAIL_METADATA`；
- 把 highfreq 改为 training：判`FAIL_STRUCTURE`；
- 用同一文件承担 training 和 holdout：判`FAIL_STRUCTURE`；
- 修改原始文件一字节：哈希门失败；
- 只填写文件名中的`5hz`：不能满足频率证据；
- 用拟合得到的`Ru/Cdl`冒充独立输入：记录为非独立并禁止固定；
- 缺少位点量但其余资料完整：允许进入 A1，同时写入报告限制；
- 清单仍是空模板：输出`WAITING_FOR_DATA`，不得产生 A1 seed；
- 新数据行数不是65,536：接入阶段不失败，由新批次 A1 依据方法与采样门审核。

## 9. 测试

- 单元测试覆盖四种状态、路径、哈希、重复 ID、角色泄漏和来源等级；
- 集成测试使用小型三列合成文件和方法文件，验证一一对应及哈希；
- 修改输入后旧输出不得复用；
- validator不导入优化器、求解器、Web或实验拟合代码；
- 空模板的固定预期状态为`WAITING_FOR_DATA`。

## 10. 完成标准

本切片完成需同时具备：

1. 模板、validator和测试；
2. 空模板验收为`WAITING_FOR_DATA`；
3. 完整合成样例验收为`READY_FOR_A1_AUDIT`并生成 A1 seed；
4. 结构和元数据故障注入按设计分类；
5. 项目总览、进度和交接入口指向本契约；
6. 全量回归通过。

本切片不提交真实实验数据，不修改旧 Gate A1，不启动 E4、A6-v2 或真实反演。

## 11. 实施入口与当前证据

- 模板：`config/data-contracts/post-experiment-intake-v1.template.json`；
- 纯校验模块：`code/python/src/oer_aem/experiment_intake.py`；
- 唯一命令行入口：`code/python/scripts/validate_post_experiment_intake.py`；
- 空模板证据：`results/smoke/experiment_intake/template-v1/`。

当前固定状态为`WAITING_FOR_DATA`，缺少三个预注册条件；结构错误和元数据
错误均为空，且没有生成`a1_seed.json`。模板SHA-256为
`1a891c8283498b09eaa57f698e66e8e7e3ded9a0acb815b063889ab4f3805521`。
恢复实验后必须复制模板生成新`intake_id`，不能覆盖本模板或旧Gate A1注册表。
