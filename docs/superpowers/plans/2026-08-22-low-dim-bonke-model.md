# 低维 Bonke 分子催化模型：范围、依据与边界

日期：2026-08-22
负责人：刘拾玉
状态：执行中（探索性拟合，非正式结论）

---

## 1. 为什么换模型

对 `02-原始资料` 中五篇 FTacV 方法论文做实际拟合自由度对照：

| 工作 | 体系 | FTacV 实际拟合的模型 | 自由参数 | 数据量 |
|---|---|---|---:|---|
| Bonke 2016 JACS | CoOx/NiOx/MnOx **水氧化** | 1 表面限域氧化还原 + 1 赝一级催化步 | **3** | 多个 Γ 梯度 |
| Snitkoff-Sol 2022 | FeNC ORR（EASD） | **单一** Nernst 表面物种 | **2** | 只用第 7 次谐波 |
| Gundry 2021 ChemElectroChem | Fe(CN)6 3-/4-（干净可逆） | 准可逆单电子 BV | 6，**D 与 Ru 收敛失败被迫钉住** | 10 合成 + 10 实验 |
| Snitkoff-Sol 2024 Nat. Catal. | FePc ORR | 完整微观动力学 + 标度关系 | 多 | **5 频率 × 10 重复** |
| 本项目 Phase 0-4 | Co3O4 碱性 OER | 预氧化 + AEM 5 步 + 标度关系 | **8-9** | 4 组，各单频，无重复 |

两条判断：

1. Gundry 2021 是最直接的现实校准——Bond/Gavaghan 组用干净体系、
   Adaptive Covariance MCMC、6 参数模型，`Ru` 和 `D` 依然无法辨识。
   本项目 8-9 参数 + 量化噪声受限的数据，差距不是调目标函数能跨过的。
2. 唯一在同体系（碱性 CoOx 水氧化）做过 FTacV 反演的先例是 Bonke 2016，
   而他用的是 3 参数模型，且刻意采用 pmol/cm² 量级的超低负载，理由是
   只有催化直流电流足够小时谐波才被表面氧化还原主导。

因此本阶段把 AEM 5 步降级为"待更多数据支持的扩展模型"，先用 Bonke
分子催化模型在现有 4 组数据上取得可辩护的结果。

## 2. 模型

```
A（电子转移）：  *red  <=>  *ox + e-        E0_eff, k0, alpha
B（催化）：      *ox   -->  *red + O2...    kf（赝一级，化学步无电荷）
```

自由参数 4 个：`E0_eff`、`k0`、`kf`、`gamma`
钉住参数：`Ru`(engineering)、`A`(engineering)、`Cdl`(derived_from_data)、`alpha`(literature)

**标度简并**：法拉第电流正比于 `gamma * A`。`A` 钉住时反演出的 `gamma`
实为 `gamma * A / A_assumed`，不得单独解释为真实位点密度。

实现：`python/oer_aem/molecular_catalysis.py`

## 3. 拟合窗口与通道

窗口 **1.20 – 1.65 V**（各数据集按实际扫描范围取交集）。依据：

* 高次谐波中可复现的表面氧化还原特征位于 1.52 – 1.63 V（见第 5 节）；
* 排除高电流区——那里 `i*Ru`（11 mA × 10 Ω ≈ 110 mV）与交流幅值
  160 mV 同量级，且气泡、OH- 传质、基底背景均未建模。同一刀同时
  移除四个未建模物理过程，而不丢失目标信号。

拟合通道 **H2、H3、H4**。刻意排除：

* **DC** —— 实验 DC 含未扣除的基底背景电流，而 FTacV 谐波本来就是用于
  排除背景的；纳入 DC 会让优化器用机理参数吸收背景。
* **H1** —— 被双电层电流与上升的催化电流主导。

## 4. 目标函数与推断

依据 Gundry 2021 的比较结论（谐波类方法优于总电流法）：

* 优化：**HarmPer**（逐谐波归一化包络相对 RMS）+ CMA-ES；
* 推断：**MLE-ExpHarmPer** 对数似然，逐谐波噪声 `sigma_h` 以 Jeffreys
  先验解析积分掉，得 `logL = -sum_h (N_h/2) log(SSR_h)`；
* 采样：自适应协方差 MCMC（Haario），4 条链，报告 R-hat。

实现：`python/oer_aem/low_dim_fit.py`、`python/oer_aem/mcmc.py`
（不引入 emcee/pints 依赖——Legion 正式环境依赖版本是钉住的）

**这一步替代了旧的"跨数据 CV"可辨识性判据。** 旧判据的问题见
`docs/项目纠错.md` 第 10 条：CV 在 linear/log 混合参数化下检测的是
参数用的哪种尺度，不是可辨识性。可辨识性必须在单个数据集内部由后验
宽度和相关矩阵给出。

## 5. 支撑本阶段的模型无关证据

对四组原始电流做带通 + 包络，取内部局部极大值（非边界）：

| 数据 | f | 扫速 | H3 峰位 | H4 伴峰 |
|---|---:|---:|---:|---:|
| FT2 | 5 Hz | 9.7 mV/s | 1.596 | 1.538 |
| FT3 | 5 Hz | 19.5 mV/s | 1.629 | 1.562 |
| FT4 | 1 Hz | 3.9 mV/s | 1.589 | 1.521 |
| FT8 | 5 Hz | 17.6 mV/s | 1.584 | 1.544 |
| | | | **1.600 ± 0.020** | **1.541 ± 0.017** |

跨 2 个频率、3 个扫描窗口、5 倍扫速差一致到 ±20 mV。
模型侧对应关系已由 `test_molecular_catalysis.py` 固化：无催化步时奇次
谐波包络峰落在 `E0_eff` 上，偶次谐波在该处为中心极小值
（Snitkoff-Sol 2022 判据），EC' 催化步把峰推向更正电位（Bonke process II）。

**待确认**：FT3(5 Hz) 与 FT4(1 Hz) 扫描窗口完全相同，H3 峰位相差
+40 mV。若二者为同一电极，这是已在手的两点频率色散，可约束 `k0`；
若不是同一电极，该位移混入样品差异，只作定性提示。

## 6. 明确不做的事

* **不建立 phase gate、预注册非劣界限、manifest 哈希链。** 本阶段是
  探索性拟合，其输出用于设计下一轮实验。Phase 1–4 每个阶段派生新阶段、
  Phase 5 无限期暂停，机制正是在模型未定型时过早上验收链。等模型定型、
  补充实验回来后再上。
* **不删除 AEM 5 步模型**，只降级。补充实验到位后可作为 M2 重新 gate。
* **不解释单个 `k0_i`**（AEM 版），也不把本阶段 `gamma` 当绝对位点密度。

## 7. 留痕要求

每份结果记录 commit、环境、seed、数据集、配置、截断窗口、钉住参数
及其来源标签。逐数据集落盘（WORK_STATUS §16 记录过末尾统一写 CSV
导致整轮结果只剩表头的事故）。

产出：
```
results/low_dim_bonke/posterior_samples.csv
results/low_dim_bonke/posterior_summary.csv    含 provenance 列
results/low_dim_bonke/correlation.csv
results/low_dim_bonke/ru_sensitivity.csv
results/low_dim_bonke/run_manifest.json
```
