# Gate A6 单参数 Objective Profile 正式分析

## 结论

**Infrastructure PASS。** 20 个 profile、820 行、每组 41 点和唯一 truth 点均
完整；正式配置、commit、哈希和有限性通过验收。

无噪声且其他参数取 truth 时，20 个 profile 的 truth 均为离散全局最小值。
这说明目标实现没有系统性偏移，但不代表五参数联合可识别。

`k0_1` 在四种模式中都存在宽广近简并区，应从自由参数集移除。hybrid 和
lockin-only 对 `k0_2,k0_3,G_OH,G_O` 的单参数剖面最清晰，这四个参数可进入
选择性的两参数 profile；仍不得直接恢复联合 TPE。

## 正式配置

- source commit：`3f9aad1248b07de007a8713c47b2d96a742ac8d0`
- truth：`mixed_b`
- noise fraction：0
- LSODA；8192 simulation points；32 points/cycle；128 feature points
- 4 feature modes × 5 parameters × 41 points = 820 rows
- workers：8；每 worker 1 BLAS thread
- systemd CPU time：2 h 0 min 13.6 s

## Profile 摘要

`Δ1` 和 `Δ10` 是 `loss <= minimum + 1/10` 的归一化坐标宽度，只是目标地形
诊断尺度，不是置信区间。

| mode | parameter | truth 为全局最小 | Δ1 宽度 | Δ10 宽度 | 远端 Δ1 近简并 |
|---|---|---:|---:|---:|---:|
| complex_snr | k0_1 | 是 | 1.000 | 1.000 | 是 |
| complex_snr | k0_2 | 是 | 0.400 | 1.000 | 是 |
| complex_snr | k0_3 | 是 | 0.075 | 0.200 | 否 |
| complex_snr | G_OH | 是 | 0.525 | 0.725 | 是 |
| complex_snr | G_O | 是 | 0.025 | 0.600 | 否 |
| legacy | k0_1 | 是 | 0.525 | 1.000 | 是 |
| legacy | k0_2 | 是 | 0.225 | 0.450 | 否 |
| legacy | k0_3 | 是 | 0.050 | 0.225 | 否 |
| legacy | G_OH | 是 | 0.050 | 0.650 | 否 |
| legacy | G_O | 是 | 0.050 | 0.175 | 否 |
| lockin_only | k0_1 | 是 | 0.825 | 0.925 | 是 |
| lockin_only | k0_2 | 是 | 0.025 | 0.250 | 否 |
| lockin_only | k0_3 | 是 | 0.000 | 0.075 | 否 |
| lockin_only | G_OH | 是 | 0.000 | 0.550 | 否 |
| lockin_only | G_O | 是 | 0.000 | 0.075 | 否 |
| hybrid | k0_1 | 是 | 0.825 | 0.925 | 是 |
| hybrid | k0_2 | 是 | 0.025 | 0.250 | 否 |
| hybrid | k0_3 | 是 | 0.000 | 0.075 | 否 |
| hybrid | G_OH | 是 | 0.000 | 0.550 | 否 |
| hybrid | G_O | 是 | 0.000 | 0.050 | 否 |

## 参数角色更新

- `k0_1`：单参数近简并，固定、窄先验或 diagnostic-only；不得继续作为宽
  边界自由参数。
- `k0_2,k0_3,G_OH,G_O`：只在 hybrid/lockin-only 下进入两参数 profile。
- complex_snr：`k0_2` 和 `G_OH` 仍有远端近简并，不作为优先联合模式。
- legacy：可保留为外部对照，不作为最敏锐的联合诊断模式。

## 下一步

先对四参数的六个两两组合执行 hybrid 与 lockin-only 二维 profile。采用
分层策略：粗网格定位谷线，仅对 truth 邻域与近简并区加密。二维 profile
通过后再决定最小联合自由集；不直接增加 TPE trials。
