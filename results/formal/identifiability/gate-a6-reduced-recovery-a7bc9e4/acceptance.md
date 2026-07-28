# Gate A6 缩减三参数合成恢复正式验收

验收日期：2026-07-29

计算 commit：`a7bc9e4dd274013137b714c7d120bddf175565b1`

结论：**基础设施 PASS，科学 Gate FAIL**

## 运行与结构

- systemd：`inactive/dead`，`Result=success`，`ExecMainStatus=0`
- `STATUS.json`：`SUCCESS`，退出码 0
- 任务：72/72 完成，72 个唯一 `job_id`
- 设计：4 feature modes × 3 truths × 2 noise levels × 3 optimizer seeds
- 自由参数：`k0_2,k0_3,G_O`
- 预算：每个 job 100 trials
- 后端：LSODA
- 并行：4 workers
- wall time：13974.94 s（约 3 h 52 min 55 s）
- provenance：commit 匹配，`dirty=false`
- JSON 数值：全部有限
- optimizer job：72/72 `success=true`
- trial 内失败计数：218 ODE failures，1563 Tafel failures

trial 内失败由目标函数惩罚并未阻止72个study完成，不能单独解释为基础设施失败。

## 科学恢复结果

每个模式、真值和噪声组合使用3个optimizer seed。这里的seed最小/最大值只表示优化器
稳定性范围，不是统计置信区间。

| 参数 | 真值被seed范围覆盖 | 最差组中位归一化边界误差 | 最差单seed归一化边界误差 |
|---|---:|---:|---:|
| `k0_2` | 19/24 | 0.2988 | 0.5952 |
| `k0_3` | 15/24 | 0.2846 | 0.4893 |
| `G_O` | 13/24 | 0.2646 | 0.6479 |
| 合计 | 47/72 | — | — |

按噪声分层：

- 无噪声：24/36 覆盖；
- 量化噪声 `0.001495726085983469`：23/36 覆盖。

按feature mode分层：

- `complex_snr`：9/18；
- `legacy`：10/18；
- `hybrid`：14/18；
- `lockin_only`：14/18。

## Gate 决策

缩减到三个自由参数后，仍有25/72个组—参数组合的seed范围不覆盖真值；失败同时存在于
无噪声合成数据，不能归因于实验噪声。因此当前目标函数与数据不能稳定联合恢复
`k0_2,k0_3,G_O`。

根据预注册规则：

- 不冻结该三参数集为正式真实数据反演自由集；
- 不启动正式真实数据TPE；
- 不增加trials、不扩大参数边界、不修改阈值制造PASS；
- 下一步应先比较单参数/两参数可恢复性，或改变实验信息量与目标设计。

## 工具限制

`wf verify a7bc9e4/a6_recovery_reduced` 使用了通用默认文件
`summary.csv/manifest.json`，没有加载本任务的
`summary.json/job_plan.json/results.jsonl` 契约，因此报告structure FAIL。该问题属于
`wf verify`任务spec解析缺陷，与本次结果文件是否完整分开记录。本验收使用任务冻结
配置逐项检查。

## 原始证据 SHA-256

```text
c18caefe3efe0ca67d05b61c67bacfb9e4e21c96657c073dfa165a59af4dec34  STATUS.json
de989bf1e86d9fa790af2a796ebf08c8423211f7cd6a98542db2fc0b4fc5f973  job_plan.json
e6b6c47cdbdacd695c659b2b8c44be0b9103af65b4922123c04d0350551f0628  results.jsonl
97e926c7a9791edb974b91ffb0c5bf0b67cbf147c8a7abc4e65353085ee27174  summary.json
```
