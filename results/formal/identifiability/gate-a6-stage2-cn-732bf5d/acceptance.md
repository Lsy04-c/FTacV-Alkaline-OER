# Gate A6 Stage 2 CN 两参数恢复验收

## 结论

三项任务均执行成功、结构与 provenance PASS，但 Recovery Gate v2
scientific FAIL。停止三参数扩展和 LSODA 复核，不调整阈值、不增加 trials。

## 冻结配置

- 实现 commit：`732bf5de27a878192ab46abe76b08de66f3af29b`
- backend：CN
- feature mode：`hybrid`
- 每项：3 truths × 2 noise × 3 seeds = 18 jobs
- 每 job：100 trials
- workers：8
- v2 门：
  - group median normalized error `<= 0.025`
  - group max normalized error `<= 0.05`
  - seed normalized dispersion `<= 0.05`
  - boundary hit rate `= 0`
  - studies 全成功

## 正式结果

| 参数组合 | wall time | 最大误差 | 最坏中位误差 | 最大 seed 极差 | Tafel fail | 结论 |
|---|---:|---:|---:|---:|---:|---|
| `k0_2,k0_3` | 21.94 s | 0.231369 | 0.177096 | 0.251891 | 366/1800 | FAIL |
| `k0_2,G_O` | 22.28 s | 0.180300 | 0.026136 | 0.202199 | 157/1800 | FAIL |
| `k0_3,G_O` | 21.76 s | 0.117248 | 0.039060 | 0.147170 | 337/1800 | FAIL |

三项均满足：

- `STATUS=SUCCESS`、exit code 0；
- 18/18 jobs 完成且唯一；
- `n_ode_fail=0`；
- boundary hit rate 0；
- task snapshot、commit 和 spec hash 匹配；
- 五个归档契约文件齐全。

## 参数级最坏指标

| 组合 | 参数 | 最大误差 | 最坏中位误差 | 最大 seed 极差 |
|---|---|---:|---:|---:|
| `k0_2,k0_3` | `k0_2` | 0.231369 | 0.177096 | 0.251891 |
| `k0_2,k0_3` | `k0_3` | 0.008707 | 0.005293 | 0.011258 |
| `k0_2,G_O` | `k0_2` | 0.180300 | 0.026136 | 0.202199 |
| `k0_2,G_O` | `G_O` | 0.007657 | 0.006401 | 0.014058 |
| `k0_3,G_O` | `k0_3` | 0.117248 | 0.039060 | 0.147170 |
| `k0_3,G_O` | `G_O` | 0.093986 | 0.036828 | 0.095840 |

`k0_2` 与另一参数联合时是主要失败源；`k0_3,G_O` 则两者同时失稳。
跨 18 个 study 的带符号误差相关分别为：

- `k0_2,k0_3`: -0.648708
- `k0_2,G_O`: -0.352291
- `k0_3,G_O`: -0.339817

负相关支持参数补偿存在，但不能单独证明结构不可识别。

## 优化器与可识别性归因

使用相同 target、backend、配置和参数边界，离线复算每个 study 的真值
objective 与 TPE 最优 objective：

- 54/54 个 study 中，真值 objective 均低于 TPE 最优 objective；
- 所有无噪声 study 的真值 objective 为 0；
- 无噪声条件下三组合的 TPE 最优 objective 中位数分别为
  0.1042、0.1650、0.8639；
- 有噪声条件下真值 objective 中位数约 0.01719，而 TPE 最优中位数分别为
  0.1803、0.3385、0.7221；
- 重新计算的 TPE 最优 objective 与归档 `best_value` 最大差异
  `< 5e-13`。

因此本轮直接证据支持：

1. 当前 100-trial TPE 没有找到已知更优的真值盆地；
2. 当前 FAIL 首先是优化器/预算组合的恢复失败；
3. 不能仅凭本轮把参数判为结构不可识别；
4. 下一步应在相同 forward-evaluation 预算下比较优化算法，而不是增加
   trials 或修改恢复阈值。

## Mac 归档与哈希

### `k0_2,k0_3`

归档：
`/Users/liushiyu/OER-FTAcV-archive/results/732bf5d/a6_recovery_cn_k0_2_k0_3/20260728_220436`

| 文件 | SHA-256 |
|---|---|
| `summary.json` | `04fd1e0eeb96f85b1816c06ef98ba64c02145322a34e6233373395a6069794ff` |
| `results.jsonl` | `2b66da0a0b710ddb6879b6b604cf663c76b1286db824afcfa6b6f5b8f81557dd` |
| `job_plan.json` | `2b54c22919f2edd259320b512041e89cc84b0d47b40b361d8b44d205eaf341a2` |
| `STATUS.json` | `9e4642d972b5c8099eb9d9209332cd84ba3db26680d20c5feb23e2874e37a857` |
| `task_spec.snapshot.yaml` | `48dc7213116476f6f007298f429e2be2e537073f4871ed37f70211b36db25b6d` |

### `k0_2,G_O`

归档：
`/Users/liushiyu/OER-FTAcV-archive/results/732bf5d/a6_recovery_cn_k0_2_G_O/20260728_220542`

| 文件 | SHA-256 |
|---|---|
| `summary.json` | `eeb144789727936f6138f2b5ef0e3e5547467f5c63948c2b987430e5a5701175` |
| `results.jsonl` | `a0346872eaa0af9e41c1213a231da712b6cfcce37d896b56c54e2fb12f23ed91` |
| `job_plan.json` | `f1c997cd227fac090c9ae377a42a36a4c05c85eb0653a3433f67d3680442d991` |
| `STATUS.json` | `3f8d52debc62eeebbd349d51ea97f3ebf21a8fd573bab9c78fdd8089bc27fbcc` |
| `task_spec.snapshot.yaml` | `4d8257f28115bd4bfaf285a58bf5a718bcefc1d2d5eb3ce9d72d2df5c10a52c6` |

### `k0_3,G_O`

归档：
`/Users/liushiyu/OER-FTAcV-archive/results/732bf5d/a6_recovery_cn_k0_3_G_O/20260728_220645`

| 文件 | SHA-256 |
|---|---|
| `summary.json` | `54db68d836d2cb5afd19ad1c416b3a88f78c768ff9e3bf9cec54607e9d43db39` |
| `results.jsonl` | `00df0e4cdbd4f09083aa9497d086ce1d0c35e30bf6641350fd02249ae665bf90` |
| `job_plan.json` | `5f07459c8b1add3a0384d87153aaa7a5f4ba120db67e02deb03a1592d05a9891` |
| `STATUS.json` | `9a077da41c8ce6316df95867223d8f61baa35387d3657356147b043b508b806f` |
| `task_spec.snapshot.yaml` | `a3265fe67e9e6d25480a7a03897fb1e0a124e3279fbc8cfd169bc2e29ece0d2b` |
