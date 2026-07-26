# Gate A6 全参数预算校准分析

## 结论

**Scientific FAIL。** 远程执行和 36 个 study 均完成，但当前 8 参数全自由
集合无法通过恢复门，不得进入 72-study 正式恢复。

## 配置

- source commit：`1b094bcafc7549f9713d5dc42b29330f4100644e`
- LSODA；8192 simulation points；32 points/cycle；128 feature points
- 模式：legacy、complex_snr、lockin_only、hybrid
- 困难真值：`mixed_b`
- 噪声下限：`0.001495726085983469`
- seeds：7、17、27
- budgets：20、50、100 trials
- workers：8；每 worker 1 BLAS 线程
- 完成：36/36；wall time 3039.2 s

## 预算门

预注册规则以 100 trials 为参考：

- 配对最大归一化误差差值中位数 ≤ 0.02；
- 90 分位差值 ≤ 0.05；
- 边界集合一致率 ≥ 0.8。

结果：

| trials | 中位差 | 90 分位差 | 边界一致率 | 结果 |
|---:|---:|---:|---:|---|
| 20 | 0.00035 | 0.14955 | 0.75 | FAIL |
| 50 | 0.00000 | 0.08599 | 0.9167 | FAIL |
| 100 | 0 | 0 | 1 | reference |

因此预算只能选择 100 trials，但该结论不代表参数可恢复。

## 恢复失败

100-trial 参考中，多模式仍出现：

- 参数最大归一化边界误差中位数约 0.52–0.58；
- 多个参数真值不在三个 optimizer-seed 解的范围内；
- `gamma` 在部分模式出现边界命中；
- 共 171 次 ODE 失败、629 次 Tafel 提取失败，均发生于广边界搜索。

这些是全参数自由集合不可行的证据，不是远程 systemd 或 worker 故障。
下一步必须依据正式带符号敏感性缩减参数集，再重新校准预算。
