# 结果与证据索引

结果按证据等级分类。目录位置表示证据用途，不表示科学结论自动成立。

## 目录

| 路径 | 用途 | 能否进入科学结论 |
|---|---|---|
| `formal/` | 完整配置、正式预算和 manifest 支持的结果 | 验收通过后可以 |
| `smoke/` | 小预算流程检查 | 不可以 |
| `diagnostics/` | 数据、残差、网格、求解器和模型诊断 | 作为辅助证据 |

## Formal

`formal/architecture_validation/` 保存 32 points/cycle 同构架构验证基线及 manifest。正式文件不得被 smoke 运行覆盖。

`formal/solver_equivalence/formal-1becc12/` 保存 24 样本 CN–LSODA
正式等价性失败证据。该目录属于正式预算结果，但 Gate A3 为 FAIL，
不能作为 CN 可进入正式搜索的依据。

## Smoke

`smoke/architecture_validation/feature_objective_comparison_3trial.csv` 是 3-trial 流程检查。它不替代正式 feature comparison。

## Diagnostics

| 路径 | 内容 |
|---|---|
| `diagnostics/data_quality/` | 实验数据和谐波质量 |
| `diagnostics/model_gap/` | 残差、Ru 和高电流诊断 |
| `diagnostics/potential_resolved_harmonics/` | 电位分辨谐波诊断 |
| `diagnostics/staged_inversion/` | 历史分阶段反演诊断 |
| `diagnostics/benchmarks/` | 优化器基准 |
| `diagnostics/figures/` | 辅助图 |

## 新结果规则

1. 运行前确定 `formal`、`smoke` 或 `diagnostics`。
2. 每个正式结果记录输入、配置、随机种子、代码提交和环境。
3. smoke 文件名必须写明预算或 smoke。
4. 缓存、进度文件、空测试输出和失败下载不得提交。
5. 结果路径变化时同步修改生成脚本和本 README。
