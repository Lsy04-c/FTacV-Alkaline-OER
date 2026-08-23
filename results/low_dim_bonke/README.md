# 低维 Bonke 模型反演结果

> **状态：2026-08-22 夜间那轮的后验已作废。** 见 `docs/项目纠错.md` §25：
> `MLE-ExpHarmPer` 把高度相关的包络点当独立样本（冗余约 128 倍），
> 似然过尖导致链几乎不动，R-hat 达 3–10^13。修正似然并通过合成数据
> 回收验证后才可重跑。**`posterior_summary.csv` 与 `correlation.csv`
> 不得引用。**

## 仍然有效的产物

`ru_sensitivity.csv` 与 `run_manifest.json` 中的 `best_harmper`
走 HarmPer 优化路径，**不含该缺陷**。其中 Ru 敏感性给出了本轮最重要的
结论（`docs/项目纠错.md` §15）：

| 数据 | Ru 5→20 Ω 的后果 | ΔHarmPer |
|---|---|---:|
| FT3 | E⁰_eff +154 mV，k₀ 变 137×，γ 变 0.3× | 0.035 |
| FT4 | E⁰_eff +237 mV，k₀ 变 8×，γ 变 34.9× | 0.071 |
| FT8 | E⁰_eff +349 mV，k₀ 变 115×，γ 变 6.6× | 0.016 |

拟合质量几乎不变而机理参数相差一到两个数量级——**数据区分不出 Ru，
但 Ru 决定机理参数**。因此 EIS 实测 Ru 已升级为正式反演的前置阻断项。

## 运行信息

commit `3af3de0`，拯救者 `LAPTOP-JBG0SNHL`，解释器 `/home/lsy/oer-venv/bin/python`，
LSODA，8000 迭代 × 4 链 × 4 数据集，约 6 小时。各目录 `run_manifest.json`
记录完整配置、依赖版本与四条链的接受率。
