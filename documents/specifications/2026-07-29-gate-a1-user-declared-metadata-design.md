# Gate A1 用户声明元数据补录设计

## 目标

在不改写原始数据、不推断未知实验处理的前提下，记录项目负责人提供的
列顺序、单位和电位标尺。更新后的 Gate A1 仍须区分已声明信息与未验证信息。

## 输入事实

项目负责人声明四份 FTacV 数据采用相同列定义：

| 列 | 物理量 | 单位或标尺 |
|---|---|---|
| 1 | 电位 | `V vs RHE` |
| 2 | 电流 | `A` |
| 3 | 时间 | `s` |

电位已经过 RHE 校正。负责人不是原实验执行者，不能确认仪器导出前是否执行
滤波、平滑、平均、降采样、裁剪、背景扣除或 iR 补偿。

配套 CHI660E/CHI760F CV 文件头写有 `Potential/V, Current/A`，只能作为
单位的辅助证据，不能证明四份 FTacV 文件没有预处理。

## 登记规则

四份数据的 `potential_unit`、`potential_reference`、`current_unit` 和
`time_unit` 使用 `source_kind=externally_declared`，记录为项目负责人声明，
并在来源说明中注明配套 CV 文件头的辅助证据。

`instrument_preprocessing` 记录为：

```text
除 RHE 校正外未报告其他处理；现存文件无法独立验证。
```

该字段不得写成“无预处理”或其他确定性结论。
其 `source_kind` 保持 `unresolved`，`value` 保持 `null`；上述文本只写入
`source_note`，不能被 validator 当作已解决元数据。

## Gate 结果

更新后重新运行 Gate A1 runner 和独立 validator。预期结果：

- 文件结构：`PASS`
- 采样数值：`PASS`
- 四项列定义元数据：满足用户声明来源要求
- 仪器预处理：仍未获得一手来源
- Gate A1：保持 `FAIL_METADATA`
- `eligible_for_inversion=false`

若实际结果与预期不符，停止后续步骤并保留失败证据，不调整来源等级制造
`PASS`。

## 交付物

- 更新 `config/data-contracts/gate-a1-datasets.json`；
- 增加用户声明和不确定性边界的回归测试；
- 生成绑定干净 commit 的新 Gate A1 正式归档；
- 更新 Gate A1 验收、项目进度和项目纠错文档。

## 非目标

- 不修改四份原始 FTacV 文件；
- 不推断 RHE 换算公式、原参比电极、pH 或温度；
- 不声明仪器未进行预处理；
- 不解除真实数据正式反演禁令；
- 不修改 A2–A6 的证据或结论；
- 不进行参数重构。
