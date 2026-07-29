# Gate A6 参数角色失败关闭验收

## 结论

- 关闭流程验证：**PASS**
- Gate A6 科学状态：**FAIL_RECOVERY**
- `eligible_for_real_inversion=false`
- `free_parameters=[]`
- `narrow_prior_parameters=[]`
- `eligible_pairs=[]`

PASS 只表示登记表、证据哈希、角色口径和归档来源通过独立验证，不表示
参数恢复通过。冻结确认集中没有两参数组合通过 Recovery Gate v2，因此
真实数据正式反演继续禁止。

## 冻结角色

| 角色 | 参数 |
|---|---|
| `fixed` | `A`、`Cdl`、`Ru`、`E0_pre`、`k0_pre`、`gamma`、`k0_4`、`scaling_OOH_OH` |
| `diagnostic_only` | `k0_1`、`k0_2`、`k0_3`、`G_OH`、`G_O` |
| `free` | 无 |
| `narrow_prior` | 无 |

`fixed` 只表示当前运行时固定，不表示数值准确或没有不确定度。
`diagnostic_only` 允许 profile、敏感性和实验设计，不允许报告可信反演点估计，
也不等于数学上结构不可识别。

## 验证与来源

- 实现 commit：`75e25edab82dc9db980a77c381f6baf1961024eb`
- validator：`code/python/scripts/validate_gate_a6_parameter_roles.py`
- 登记表：`config/parameter-roles/gate-a6-parameter-roles.json`
- 证据范围：四模式敏感性、单/二维 profile、缩减恢复、Stage 2、
  优化器开发门和 Sobol 锁定确认集。
- 独立归档复验：`PASS`
- 参数数：13；`fixed=8`，`diagnostic_only=5`
- 本阶段不运行 ODE、CN、LSODA、优化器或 TPE。

## 文件 SHA-256

| 文件 | SHA-256 |
|---|---|
| `parameter_roles.snapshot.json` | `17b0ee54a1c73c546bb681f530594d0e30e8cc5bd7a245f6b865964d35c6b509` |
| `validation_report.json` | `c4aa91308f847abb0352a6a8b8c4c13acca0b84f6c0e6f6b6446f902b3ca5c52` |
| `run_manifest.json` | `3d0f0ac3b660436b0ff0ecd218b7a14d122783330d0a3e95d30356daf6379f3b` |

## 后续边界

当前路线到此关闭。若要重新尝试参数恢复，必须以新的研究假设和新协议立项，
例如引入独立实验约束、重参数化组合量或改变实验设计；不得通过增加预算、
更换算法或放宽既有门槛改写本次 `FAIL_RECOVERY`。
