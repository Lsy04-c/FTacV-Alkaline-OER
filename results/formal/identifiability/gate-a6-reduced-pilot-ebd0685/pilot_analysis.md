# Gate A6 五参数条件恢复预算分析

## 结论

**Infrastructure PASS，Scientific FAIL。**

36 个 study 全部完成，结果有限且 provenance 一致，但
`k0_1,k0_2,k0_3,G_OH,G_O` 五参数条件自由集仍未达到恢复要求。不得启动
原计划的 72-study 正式恢复，也不得通过放宽边界或只增加 trials 制造 PASS。

## 正式配置

- source commit：`ebd06858df37cc50003a9d47a3e1f0e959aa8c41`
- 自由参数：`k0_1,k0_2,k0_3,G_OH,G_O`
- 其余三个反演参数：按每个 synthetic truth 的真实值固定
- TPE：不使用 truth 初始化
- LSODA；8192 simulation points；32 points/cycle；128 feature points
- 4 modes × 3 seeds × 20/50/100 trials = 36 studies
- workers：8；每 worker 1 BLAS thread
- wall time：2805.2 s
- ODE failures：124；Tafel extraction failures：634

## 预算稳定性

100 trials 为预注册参考：

| trials | 中位配对误差差 | 90 分位差 | 边界集合一致率 | 结果 |
|---:|---:|---:|---:|---|
| 20 | 0.14860 | 0.26262 | 0.5833 | FAIL |
| 50 | 0.10288 | 0.24158 | 0.8333 | FAIL |
| 100 | 0 | 0 | 1 | reference |

20 和 50 trials 均不稳定；100 trials 只能作为参考预算，不能据此宣称恢复。

## 100-trial 恢复结果

| feature mode | seed 范围覆盖真值 | 最大归一化边界误差范围 |
|---|---:|---:|
| complex_snr | 2/5 | 0.266–0.694 |
| hybrid | 4/5 | 0.272–0.544 |
| legacy | 3/5 | 0.380–0.482 |
| lockin_only | 4/5 | 0.140–0.646 |

`k0_1` 在四种模式中均未被三个 optimizer seed 的估计范围覆盖。
complex_snr 下 `k0_3`、`G_OH` 和 `G_O` 也未覆盖真值。即使其他参数取正确
固定值，五参数联合搜索仍表现出明显的多解性或优化不稳定性。

## 科学解释边界

本结果证明“五参数联合 TPE 条件恢复”不可用，但尚不能区分：

1. 特征目标本身对某参数近似平坦或存在多重极小值；
2. 参数组合仍存在非线性耦合；
3. 100-trial TPE 在五维宽边界内仍未可靠找到正确极小值；
4. Tafel 缺失惩罚和 ODE 失败区改变了可搜索目标地形。

因此下一步不再扩大 TPE 预算，而是先做确定性的单参数 profile：
其他参数固定在 truth，对每个参数扫描完整归一化边界，检查真值是否为全局
极小值、局部曲率、近最优区宽度和失败区。只有单参数 profile 有明确极小值
的参数才进入两参数组合 profile；再据此决定最小自由集、窄先验或
diagnostic-only 角色。
