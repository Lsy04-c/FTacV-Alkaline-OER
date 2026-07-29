# Gate A1 用户声明元数据补录验收

## 结论

- 文件结构门：**PASS**
- 采样数值门：**PASS**
- 负责人声明登记：**PASS**
- 仪器预处理元数据：**FAIL_METADATA**
- Gate A1 总结论：**FAIL_METADATA**
- `eligible_for_inversion=false`

四组 FTacV 数据现已登记为电位、电流、时间三列，单位和标尺为
`V vs RHE`、`A`、`s`。这些信息来自项目负责人声明；负责人不是原实验
执行者。现存文件仍不能证明仪器导出前的滤波、平滑、平均、降采样、裁剪、
背景扣除或 iR 补偿，因此本次补录不关闭 Gate A1。

## 冻结运行

- 实现 commit：
  `7cf548f32c07652b4bc1c8339bfc926f963c8fd7`
- 注册表：
  `config/data-contracts/gate-a1-datasets.json`
- 注册表 SHA-256：
  `96aebc642d00d1f90696cd8060ec088eff4a9d22c9a3eba02a2d5bfa83ac4b62`
- Python / NumPy：3.13.3 / 2.4.6
- 开始 / 结束：
  `2026-07-29 17:42:44.593391` /
  `2026-07-29 17:42:44.838001`（北京时间）
- provenance：`dirty=false`，`dirty_paths=[]`
- runner 退出码：2（`FAIL_METADATA`）
- 独立 validator 退出码：2（`FAIL_METADATA`）

## 元数据验收

| 数据集 | 电位 | 电流 | 时间 | 唯一缺失项 | 结构 | 采样 |
|---|---|---|---|---|---|---|
| FT2 | `V vs RHE` | `A` | `s` | `instrument_preprocessing` | PASS | PASS |
| FT3 | `V vs RHE` | `A` | `s` | `instrument_preprocessing` | PASS | PASS |
| FT4 | `V vs RHE` | `A` | `s` | `instrument_preprocessing` | PASS | PASS |
| FT8 | `V vs RHE` | `A` | `s` | `instrument_preprocessing` | PASS | PASS |

四项列定义使用 `source_kind=externally_declared`。配套 CHI CV 文件头只为
`V` 和 `A` 提供辅助一致性证据，不证明 FTacV 文件的预处理历史。
`instrument_preprocessing.value` 保持 `null`，
`source_kind` 保持 `unresolved`。

## 完整性

- 四个原始文件的 SHA-256、字节数和 65,536×3 结构与旧冻结注册表一致；
- runner 与独立 validator 对四个数据集给出相同缺失字段；
- 所有诊断值有限；
- 结果绑定干净 commit、注册表哈希、Python 和 NumPy 版本；
- 旧归档 `gate-a1-a57d42f` 保留，不被本次结果覆盖。

## 文件 SHA-256

| 文件 | SHA-256 |
|---|---|
| `dataset_contracts.json` | `a0847af9942d3ca1d21e513a5d0f715f8e4f88104d144c3be35076decbae2cd6` |
| `gate_a1_summary.json` | `19d891da1e7743c341b27645226bf10a2db855cf9d0e93f58bbd23889f378945` |
| `run_manifest.json` | `8e9085273172575a74d42251b2a0d2d44418e036c56a815ca58fb8790dbaaada` |

## 允许与禁止的表述

允许：

- 四组数据的列序、`V vs RHE`、`A` 和 `s` 已按负责人声明登记；
- 四组数据可用于明确标注元数据假设的条件模型分析；
- Gate A1 的唯一剩余缺失项是仪器预处理记录。

禁止：

- “Gate A1 已 PASS”；
- “现存文件证明未进行预处理”；
- “负责人声明等同于原实验方法记录”；
- “当前数据已获得正式真实反演资格”。

## 下一步

进入 V2 条件模型可达性分析。V2 只判断冻结 M0 是否能覆盖实验
DC/H1–H3 特征，不把最优候选解释为真实参数，也不解除 A6 的反演禁令。
