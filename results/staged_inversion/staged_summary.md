# Staged Inversion Report

> **状态：Layer 4 结论已撤回（2026-08-22）。** 下方的
> "Cross-Dataset Parameter Stability" 表格及其 stable/unreliable 判定
> **不能作为可辨识性证据**，理由见 `docs/项目纠错.md` 第 10 条：CV 在
> linear/log 混合参数化下不可比，`k0` 的 CV 与纯先验抽样不可区分，三个
> "stable" 参数相对先验的收缩倍数几乎相同。此外本轮的 Tafel 目标是写死的
> 60 mV/dec（第 11 条），Layer 2 边界从未生效（第 12 条），四组数据共用
> seed 与初值，`n_forward=50`。
>
> 可辨识性现由单数据集后验给出：`results/low_dim_bonke/`。
> 本文件保留仅供追溯。

## Layer 1 — Fixed Experimental Parameters

| Param | Value |
|-------|-------|
| Cdl | 2.777e-05 |
| Ru | 10 |
| A | 1 |
| gamma | 3e-09 |

## Layer 2 — Pre-Oxidation Bounds

| Param | Lower | Upper |
|-------|-------|-------|
| E0_pre | 1.400 | 1.550 |
| k0_pre | 50.000 | 800.000 |

## Layer 3 — AEM Inversion Results

| Dataset | Fit H | Best Value | Level | n_forward |
|---------|-------|------------|-------|----------|
| ftacv2-ref-5hz.txt | [1, 2, 3, 4, 5] | 8497.1209 | poor | 50 |
| ftacv3-ref-5Hz.txt | [1, 2, 3] | 6978.3174 | poor | 50 |
| ftacv4-ref-1hz.txt | [1, 2, 3] | 3599.0983 | poor | 50 |
| ftacv8-ref-5Hz.txt | [1, 2, 3, 4] | 4959.3854 | poor | 50 |

## Layer 4 — Cross-Dataset Parameter Stability

| Param | Mean | Std | CV | Level |
|-------|------|-----|-----|-------|
| G_O | 3.114 | 0.1188 | 0.038 | stable |
| G_OH | 1.707 | 0.1167 | 0.068 | stable |
| k0_1 | 4658 | 4639 | 0.996 | unreliable |
| k0_2 | 343.1 | 557.2 | 1.624 | unreliable |
| k0_3 | 3512 | 3988 | 1.136 | unreliable |
| k0_4 | 9.415 | 16.28 | 1.729 | unreliable |
| scaling_OOH_OH | 2.973 | 0.06934 | 0.023 | stable |

## Diagnostics

**Unstable parameters (high cross-dataset variance):**
- `k0_1`: CV=1.00 — likely coupled or unresolvable
- `k0_2`: CV=1.62 — likely coupled or unresolvable
- `k0_3`: CV=1.14 — likely coupled or unresolvable
- `k0_4`: CV=1.73 — likely coupled or unresolvable
**Stable parameters (consistent across datasets):**
- `G_OH`: CV=0.07
- `G_O`: CV=0.04
- `scaling_OOH_OH`: CV=0.02
