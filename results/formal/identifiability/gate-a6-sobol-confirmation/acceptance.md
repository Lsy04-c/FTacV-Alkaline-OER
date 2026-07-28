# Gate A6 Sobol 锁定确认集验收

## 结论

- 执行门：**PASS**
- 数值门：**PASS**
- 结构门：**PASS**
- Recovery Gate v2：**FAIL**
- eligible pairs：无
- 决策：停止 Gate A6 多参数恢复；不启动 LSODA 确认、三参数扩展或真实
  数据正式反演，不增加预算、不更换算法、不修改阈值。

该结果表示：开发门选出的 `sobol_pattern` 在冻结的 51-study 确认集与
3 条开发证据合并后，三个两参数组合均未通过 Recovery Gate v2。它不能
单独证明参数结构不可识别；失败同时包含优化搜索与参数恢复稳定性因素。

## 冻结契约与运行

- 科学实现 commit：
  `1015a38364b514f597b2023478cb29659594669e`
- optimizer 实现基线：
  `a5b93f55e540682cc8cddb1fabbe63a7e0e92326`
- task id：`1015a38/a6_optimizer_confirmation_cn`
- spec hash：
  `sha256:7f69cd553677456be87eabd49621b751116721ad004dfa80e8c13206ad3a061e`
- backend / mode / workers：CN / hybrid / 8
- optimizer / budget：`sobol_pattern` / 100 calls per study
- 正式输出：`20260728_231715`
- 开始 / 结束：`2026-07-29 07:17:19` /
  `2026-07-29 07:18:13`（北京时间）
- Mac 原始归档：
  `/Users/liushiyu/OER-FTAcV-archive/results/1015a38/a6_optimizer_confirmation_cn/20260728_231715`
- 完整性：51 个唯一确认 job、5100 条 optimization trace、51 次
  post-run truth diagnostic、`n_ode_fail=0`、`STATUS=SUCCESS`

确认矩阵对每个参数对使用
`truth ∈ {center,mixed_a,mixed_b}` ×
`noise ∈ {0,0.001495726085983469}` ×
`seed ∈ {7,17,27}`，并精确排除
`center/noise-0/seed-7` 开发案例。因此每参数对 17 个确认 job，三个参数对
共 51 个；完整 job ID 集由上述笛卡尔积、排除项和 `results.jsonl` 的
SHA-256 唯一固定。

## Recovery Gate v2 重算

| 参数对 | 最大误差 | 最坏中位误差 | 最大 seed 离散度 | boundary rate | 结论 |
|---|---:|---:|---:|---:|---|
| `k0_2,k0_3` | 0.191743 | 0.001545 | 0.192928 | 0 | FAIL |
| `k0_2,G_O` | 0.191191 | 0.014780 | 0.192767 | 0 | FAIL |
| `k0_3,G_O` | 0.246298 | 0.036859 | 0.270408 | 0 | FAIL |

冻结阈值为：每组中位误差 `<=0.025`、最大误差 `<=0.05`、seed 离散度
`<=0.05`、boundary rate `=0`，且所有 study 成功。独立 validator 从
51 条确认结果与 3 条冻结开发结果重建 54-study 矩阵，未信任 runner 自报
结论。

第一次独立验证因失败原因列表的排序契约不一致而报结构 FAIL：runner 使用
`median → max → dispersion`，validator 使用
`max → median → dispersion`。数值和科学决定完全相同。加入真实多阈值
回归测试并统一 validator 顺序后，原始归档不做任何修改即通过结构门，
随后按预注册规则得到 scientific FAIL。

## 文件 SHA-256

| 文件 | SHA-256 |
|---|---|
| `STATUS.json` | `8b56a6d3d90fa0b28c1df8137d7c58dd613da8958509f742bfe63b0b1bd10a08` |
| `benchmark_plan.json` | `ca0b9667c7900c9df94ca9d6ed26c098984f08a87043fffc09f61e7089c91de5` |
| `confirmation_gate.json` | `e092550dcb4c62d04603b9e9073bc473ab5de1ed578667f9b42dd820e44ea5de` |
| `development_evidence.snapshot.json` | `116099242f034c133f4895d068429673f0a12be611b76ea00cc3ebf415a83b8a` |
| `evaluations.jsonl` | `3111bb2a64fffda0e8251aaaaf6433ecb9f1169530f7a1568fd0cc6671760fb8` |
| `results.jsonl` | `d77103933d7fc53e5dcdddc39fa942c0ec9ad9b82539d0d71f43c4462aeffbf7` |
| `summary.json` | `9c2f6d3d3e1ead3cd83ad128d6243b668086af249f98947e903942916b4a3447` |
| `task_spec.snapshot.yaml` | `c8a71d5e33dedfc00f760fc43d593bbec85086aa7347cd36c807874199452789` |

## 允许与禁止的表述

允许：

- `sobol_pattern` 在冻结的 51-study CN 确认集中未能使任何两参数组合通过
  Recovery Gate v2。
- 当前预注册路线要求停止 Gate A6 多参数恢复。

禁止：

- 把开发门 PASS 继续表述为整体恢复 PASS。
- 把本次 CN FAIL 直接解释为数学上不可识别。
- 事后增加预算、更换优化器、调整数据划分或放宽阈值后仍称为同一确认集。
- 启动 LSODA、三参数扩展或真实数据正式 TPE。
