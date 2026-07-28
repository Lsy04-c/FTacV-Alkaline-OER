# Gate A6 固定预算优化器开发门验收

## 结论

- 执行门：**PASS**
- 数值门：**PASS**
- 开发集科学门：**PASS**
- 冻结候选：`sobol_pattern`
- 下一步：只允许编写并执行一次锁定的 51-study CN 确认集；当前不得启动
  LSODA、三参数恢复或真实数据正式反演。

该结论仅表示 `sobol_pattern` 在三个冻结的
`center/no-noise/seed-7/hybrid/CN` 两参数开发案例中，以每个 study
100 次 optimization objective call 达到归一化参数误差 `<=0.05`。它不证明
参数联合可识别、真实数据可信或 CN 与 LSODA 等价。

## 冻结契约与运行

- 实现 commit：
  `a5b93f55e540682cc8cddb1fabbe63a7e0e92326`
- task spec commit：
  `a235cd1`
- task id：`a5b93f5/a6_optimizer_development_cn`
- spec hash：
  `sha256:94e1b53827390b5f8b9bac8018c871bb81d79b817edd7bc38d6b70cac38f870d`
- backend：CN
- workers：8
- 正式输出时间戳：`20260728_224911`
- Mac 原始归档：
  `/Users/liushiyu/OER-FTAcV-archive/results/a5b93f5/a6_optimizer_development_cn/20260728_224911`
- 状态：`STATUS=SUCCESS`，systemd `Result=success`，退出码 0
- 完整性：9 个唯一 job、900 条 optimization trace、9 次 post-run truth
  diagnostic、`n_ode_fail=0`

首次 smoke `20260728_224756` 因远端复制命令中的变量转义错误，CN 动态库
未复制到 worktree，按协议产生 `FAIL_INFRA`。修正为完整绝对路径后，
smoke `20260728_224840` 通过：3 个 job、300 次调用、三种算法各 100 次，
科学 selection 保持 `null`。失败 smoke 未用于任何科学判断。

## 九个 job

| job | calls | 最大参数误差 | objective regret |
|---|---:|---:|---:|
| `k0_2-k0_3__tpe__center__noise-0__seed-7__budget-100` | 100 | 0.014668 | 0.137841 |
| `k0_2-k0_3__sobol_pattern__center__noise-0__seed-7__budget-100` | 100 | 0.000718 | 0.000318 |
| `k0_2-k0_3__de_fixed__center__noise-0__seed-7__budget-100` | 100 | 0.050948 | 1.411777 |
| `k0_2-G_O__tpe__center__noise-0__seed-7__budget-100` | 100 | 0.017265 | 0.165019 |
| `k0_2-G_O__sobol_pattern__center__noise-0__seed-7__budget-100` | 100 | 0.001875 | 0.004698 |
| `k0_2-G_O__de_fixed__center__noise-0__seed-7__budget-100` | 100 | 0.035996 | 1.486538 |
| `k0_3-G_O__tpe__center__noise-0__seed-7__budget-100` | 100 | 0.024462 | 0.988892 |
| `k0_3-G_O__sobol_pattern__center__noise-0__seed-7__budget-100` | 100 | 0.024110 | 0.484578 |
| `k0_3-G_O__de_fixed__center__noise-0__seed-7__budget-100` | 100 | 0.050948 | 2.892758 |

## 算法级重算结果

| 算法 | 最坏参数误差 | 中位参数误差 | 最大 regret | 资格 |
|---|---:|---:|---:|---|
| TPE | 0.024462 | 0.015966 | 0.988892 | 基线，不进入候选 |
| `sobol_pattern` | 0.024110 | 0.001296 | 0.484578 | **PASS** |
| `de_fixed` | 0.050948 | 0.025442 | 2.892758 | FAIL |

独立 `wf verify` 从 `results.jsonl` 和 `evaluations.jsonl` 重建 9-job 矩阵、
100-call 预算、truth diagnostic 顺序及算法排序，给出
`selected_optimizer=sobol_pattern`。未信任 runner 自报的 selection。

## 文件 SHA-256

| 文件 | SHA-256 |
|---|---|
| `benchmark_plan.json` | `d7b1c00065f4febb9e79996d5a2c1e756404f60fb66ee389bb8ea63f2748e005` |
| `results.jsonl` | `e93ccab24c4a91d9d4d9a2b8e014826b6b1a07b7d0891c6e7dd944b78e17b432` |
| `evaluations.jsonl` | `2f23b670244ef9540984489dd19270e089a551a384417c4d6d3b60f4c2f89114` |
| `summary.json` | `d69c341b38d1ecbb7682290655a75fcbadb8fc225a6a0556e52d07498ace647f` |
| `selection.json` | `2a9ff7831d1ebfbae6d78e0f6332ccda363e56062b0122864bf8dedf58056bdd` |
| `STATUS.json` | `5d1d26db6b0db738d8eb08469eae3b7faeda79993699d3b859a43f485475d337` |
| `task_spec.snapshot.yaml` | `3615d5553c269b90d053aae877c5fe6d1b065b5908d5f774c844dec4df42ec26` |

## 允许与禁止的表述

允许：

- `sobol_pattern` 在冻结的三个开发案例中通过同预算恢复门。
- 当前证据支持进入一次锁定的 51-study CN 确认集。

禁止：

- 参数已经联合可识别或真实数据反演已经可信。
- CN 结果已经获得 LSODA 确认。
- 依据开发集继续调整 Sobol 点数、pattern 步长、预算或恢复阈值。
