# 补实验后参数接入与加速恢复设计

日期：2026-08-08
范围：OER-FTAcV Python 科学核心、C++ 筛选后端、实验接入准备层
明确排除：Web 前后端、真实数据正式反演授权、未通过 A3 的 C++ 正式计算

## 1. 目标

补实验完成后，原始 FTacV、独立标定量和参数角色能够通过一个可追溯输入包进入
A1/A6 审查；搜索器不再把 `gamma` 等固定角色误加入自由变量；C++ 后端能够
批量快速筛选候选，但所有正式候选仍由 LSODA/BDF 复核。

## 2. 关键科学约束

- `gamma` 当前不是随机 truth，也不是正式自由参数。没有独立 `GammaA` 证据时，
  使用有来源的基准值并进行上下限敏感性传播。
- `A/Cdl/gamma` 的尺度关系统一按 `CdlA/GammaA` 口径审计；不允许三者同时自由搜索。
- 当前 A6 条件搜索固定 `A`、`Cdl/CdlA`、`Ru`、`E0_pre`、`k0_pre`、`gamma/GammaA`、
  `k0_4`、`scaling_OOH_OH`、`a` 和协议参数；`k0_1` 只做 profile/下界诊断。
- `k0_2`、`k0_3`、`G_OH`、`G_O` 可作为有先验的候选自由参数，但必须先做 profile
  校准步长，再做搜索和独立恢复验证。
- 补实验后，固定角色只能通过新的 profile、独立测量和 A6-v2 证据重新开放，不能
  由优化器自动改写。

### 2.1 参数固定/搜索选择接口

任务不再依赖脚本内的隐式固定集合。`build_parameter_selection()` 要求调用者
一次性提交 `free_names`、`fixed_values` 和可选 `diagnostic_names`，并返回
`free_specs`、`fixed_params` 和角色证据。所有模型搜索参数必须被明确分配；遗漏、
重复、越界值和 fixed/free 冲突都会拒绝。`A`、`Cdl`、`Ru` 等运行时输入可以作为
显式 fixed 值传入；若要把它们改为自由变量，调用者必须同时提供带物理单位和边界
依据的自定义 `ParamSpec`，不能依赖默认范围。当前固定角色（含 `gamma`）只有在
显式 `allow_role_override=True` 的诊断任务中才能重开，正式结论仍需新的证据门。

## 3. 系统边界

```text
原始文件 + intake manifest + 独立测量
              │
              ▼
       post-experiment target bundle
       (targets / fixed inputs / hashes)
              │
       ┌──────┴──────┐
       ▼             ▼
   profile/步长    C++ screen-only
       │             │
       └──────┬──────┘
              ▼
       LSODA/BDF 确认与 A6 门
```

target bundle 只准备输入和证据，不启动反演，不把“可运行”写成“可辨识”。

## 4. 加速后端决策

采用平台原生 C++ 共享库和 Python `ctypes`/批量接口，不把 MEX 作为主路径。
MEX 只在未来 MATLAB 工作台需要时作为薄适配层。C++ 初期标记为 `screen_only`：
它可以用于候选排序和预算估计，但必须记录后端标记；A3 等价门通过前不得写入
正式科学结论。新 C++ 实现优先复用统一参数打包和解析 Jacobian，避免当前 CN
数值 Jacobian 的额外开销，并提供逐案例状态码。

## 5. 步长与验证策略

搜索前对每个候选自由参数执行局部 profile，估计在目标允许范围内的无量纲半宽；
优化器步长由该半宽和参数编码共同决定。没有 profile 证据时只能做诊断 smoke，
不能启动正式恢复。搜索结果必须经过独立 truth、噪声和 holdout 验证；低 loss
不能单独升级为参数恢复。

## 6. 失败策略

- manifest、原始文件、采样、单位或独立输入缺失：返回等待/结构失败，不补默认值；
- 参数同时出现在 fixed 和 free：立即拒绝任务；
- C++ 返回非有限值或失败状态：该候选淘汰并保留状态码，不能静默回退为成功；
- C++ 与 LSODA 差异超过筛选门：C++ 继续保留为诊断，不进入确认路径；
- profile 未覆盖窄盆地：报告“步长未校准”，不扩大 trial 掩盖问题。

## 7. 验收标准

1. 任何 formal/pre-experiment runner 都不能把 `gamma` 加入 free specs；
2. 三个 truth 的 gamma 保持一致，除非任务显式声明为 gamma 敏感性实验；
3. target bundle 可由独立脚本重建，输入哈希和参数角色哈希一致；
4. C++ screen-only 能批量运行、返回逐案例状态和耗时，并与 Python bridge 对接；
5. C++ 只在显式 screen-only 模式可用，正式 LSODA/BDF 路径不被替换；
6. Python 全量测试、C++ bridge 测试和 bundle smoke 全部通过。
