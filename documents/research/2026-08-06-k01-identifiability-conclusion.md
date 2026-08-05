# k0_1 结构非可辨识：结论（2026-08-06）

> 本文件修订归档 SUMMARY（`~/OER-FTAcV-archive/results/6400989/a6_recovery_k0_123/20260805_165514/SUMMARY.md`）
> 的结论 #2——原结论将 k0_1 恢复失败归因于「TPE 探索不足」，本会话证据表明是
> **结构非可辨识（structural non-identifiability）**，换优化器无效。

## 1. 背景与问题

Gate-A6 合成恢复 pilot（k0_4+γ 固定，6 参数自由，100 trials，全量 8192 点）：
k0_1 在 3/4 模式完全错过 truth（低 1–4 个数量级）。遗留问题：是**优化器局限**
（换算法/加预算可解）还是**结构不可辨**（换算法无用）？

## 2. 证据链（本会话，legacy 全量）

### 2.1 算法对比：TPE 与适配版 CMA-ES 都恢复不了 k0_1

| 采样器 | seed | k0_1 估计 | k0_1 NBE | k0_2 NBE | k0_3 NBE | G_OH 估计 |
|---|---|---|---|---|---|---|
| TPE（归档 100t） | 7/17/27 | 0.03 / 0.003 / 0.02 | 0.51–0.64 | 0.05–0.19 | 0.003–0.56 | 1.10–1.35 |
| cmaes_raw（本会话 100t） | 7/17/27 | 9.7 / 0.81 / 0.89 | 0.20–0.34 | 0.07–0.23 | 0.02–0.46 | 1.40（✓ 精确） |

truth：k0_1=398，k0_2=0.251，k0_3=158，G_OH=1.4。
CMA-ES（raw cmaes 包，盒子中点温启动，100 trials）比 TPE 好一档，但三个 seed 全部漏掉 k0_1
（低 1.6–2.7 个数量级）。k0_2/k0_3/G_OH 两者都能恢复。**问题特定于 k0_1。**

### 2.2 k0_1 单独 profile：最有利情形下仍是水平平台

固定其余 5 个自由参数全部在 truth，只扫 k0_1（全量）：

| k0_1 | obj | obj/truth |
|---|---|---|
| 0.04 | 1.92 | 127× |
| 3.98 | 1.45 | 96× |
| 25 | 0.226 | 15× |
| 63 | 0.038 | 2.5× |
| **398（truth）** | **0.0152** | **1.00** |
| 1000 | 0.0152 | 1.00 |
| 1e4 | 0.0154 | 1.01 |
| 1e5（盒上界） | 0.0154 | 1.02 |

→ 目标函数从 398 到盒子上界（高 2.4 个数量级）是**水平平台**，无最小值；向下 k0_1<~100
才陡升。**k0_1 单边可辨：只能定下界（≳~100–160），不能定值。**

耦合伙伴已核实固定在 truth 模型取值上：
- `G_OH`(=E01)：显式固定 truth 1.4，`params_from_vector` → `apply_alkaline_aem` 每次重算 E01=G_OH；
- `θ_ox`（k0_pre/E0_pre）：不在 truth 字典（truth_library 只存 8 个 z），走默认
  k0_pre=500 / E0_pre=1.45——`make_synthetic_target` 用同一 config 生成 target，两边一致。

### 2.3 Tafel 对 k0_1 免疫，对 G_OH 敏感

| 情形 | k0_1 | G_OH | 表观 Tafel (mV/dec) |
|---|---|---|---|
| k0_1 跨 5 个数量级（3.98→3.98e4） | 任意 | 1.4 | 恒定 125.9 |
| G_OH 1.1→1.4 | 398 | 变化 | 103→126 |

→ 文献 Tafel 数值**不能**约束 k0_1（对 k0_1 完全免疫），可约束/验证 G_OH。

### 2.4 机制根源（代码级）

`physics.py` 五步（无裸 `*OH`，中间体全在氧化位点 `*ox` 上）：

| 步 | k0_i | 反应 |
|---|---|---|
| 0 | k0_pre | `* + OH⁻ ⇌ *ox + H₂O + e⁻`（预氧化 Co3+→Co4+） |
| **1** | **k0_1** | **`*ox + OH⁻ ⇌ *ox-OH + e⁻`（AEM-1）** |
| 2 | k0_2 | `*ox-OH ⇌ *ox-O` |
| 3 | k0_3 | `*ox-O ⇌ *ox-OOH` |
| 4 | k0_4 | `*ox-OOH ⇌ *ox + O₂` |

step-1 净速率 = `k0_1·exp(b·RTF·(φ_s−E01))·θ_ox − k0_1·exp(−a·RTF·(φ_s−E01))·θ_ox-OH`，
其中 `E01 = ΔG1 = G_OH`（`thermodynamics.py`）。→ 两条补偿路径：
- **k0_1 ↔ G_OH**：指数里直接耦合（E01=G_OH），一族 (k0_1, G_OH) 给相同净速率；
- **k0_1 ↔ θ_ox**：氧化位点覆盖度由预氧化步（k0_pre/E0_pre）决定。

物理上：k0_1 一大，step-1 准平衡化，FTACV 电流被后面更慢的 k0_2/k0_3 与覆盖度卡住，
k0_1 精确值不再进观测量（「快过阈值 ≈ 等效无穷快」）。

## 3. 文献对齐

- **structural non-identifiability / sloppy models**（Gutenkunst、Sethna）：多参数动力学模型
  信息矩阵特征值跨多个数量级，只有少数 **stiff 组合**被数据钉住，多数单参数（sloppy 方向）
  可漂移几个数量级而输出几乎不变。k0_1 落在 sloppy 方向；k0_2/k0_3/G_OH 更接近 stiff。
- **电化学 practical identifiability**（Bond、Simonov、Gavaghan 线）：AC/谐波能提高可辨识性，
  但速率常数与热力学/覆盖度/面积等**参数组等价**仍存在；OER 微动力学部分速率常数在可测频段
  明确不可辨，处理是固定或放弃，不是加 trial。
- **Tafel/Arrhenius 补偿**：高过电位斜率由控速步决定，表观 Tafel 不能当作逐步 k0 的独立标定
  ——与「k0_1 跨 5 数量级 Tafel 不变」一致。

## 4. 结论（对齐文献）

> 在当前观测与 M0 结构下，k0_1 与 G_OH 及预氧化覆盖度存在结构补偿，属于
> structural non-identifiability（及 sloppy 方向）。这与多参数动力学与电化学参数估计文献中
> 的已知现象一致；更换全局优化器或增加同类 FTacV trial 不能恢复唯一的 k0_1 点估计。
> 正式结果应固定/边缘化 k0_1 或仅报告可辨识组合，并单独传播不确定度。

## 5. 处理建议

| 策略 | 对 k0_1 |
|---|---|
| 承认不可辨，改报告对象 | 报告 stiff 组合 / 条件值（如「固定 G_OH 下的 k0_1」），不报点估计 |
| 固定或强先验钉一条腿 | 用 DFT 范围钉 G_OH（ΔG_*OH 软先验 0.8–1.3 eV 中心），或固定 k0_1 名义值做敏感性 |
| 切断补偿通道 | 独立约束预氧化（k0_pre, E0_pre → θ_ox）或低过电位 CV 特征，再复查 k0_1 |
| 换坐标再优化 | 在 active/组合坐标上估，k0_1 方向按 inactive 传播不确定度 |
| 停止加同类数据 | 对 k0_1 增加同类 FTacV trials 不消除结构不可辨 |
| 预测仍可准 | sloppy 参数松、输出预测可紧——正演/谐波形状仍可用 |

## 6. 对旧归档结论的修订

旧 SUMMARY 结论 #2「瓶颈是 TPE 探索不足」→ **修订为结构非可辨识**。
证据：k0_1 单独 profile 在最有利情形（其余全对）下仍为平台，换优化器（raw cmaes 适配版）
三个 seed 仍漏掉 k0_1。

## 7. 方法学教训

1. **smoke 分辨率（256 点）landscape 失真**：truth 点在该分辨率下 Tafel 特征提取失败
   （physical=100，obj=20 vs 全量 0.015），最优与全量无关——**筛选/恢复必须全量 8192 点**。
2. **optuna 4.9.0 弃用 CmaEsSampler 适配参数**：`restart_strategy` 自动回退 None、`x0` 使整个
   run 退化成 RandomSampler——真正适配测试需用 **raw `cmaes` 包**。

## 8. 复现与归档

- 代码提交：`fb1b218`（`code/python/scripts/screen_cmaes_raw.py`，raw-cmaes 适配版驱动）
- Legion：worktree `worktrees/fb1b218/a6_cmaes_screen`，systemd 单元 `oer-cmaes-screen`
- 结果：`screen_log/cmaes_raw_seed{7,17,27}.json`（本会话）
- TPE 归档：`~/OER-FTAcV-archive/results/6400989/a6_recovery_k0_123/20260805_165514/`
