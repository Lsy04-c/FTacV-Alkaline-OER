# k0_1 条件式实用可辨识性：合成诊断结论（2026-08-06）

> 本文件修订归档 SUMMARY（`~/OER-FTAcV-archive/results/6400989/a6_recovery_k0_123/20260805_165514/SUMMARY.md`）
> 的结论 #2——原结论将 k0_1 恢复失败归因于「TPE 探索不足」，本会话证据表明是
> **当前 M0 合成协议下的条件式、单边实用不敏感**；换同预算优化器未解决。
> 这不是连续模型的结构可辨识性证明，也不是实验参数结论。

## 1. 背景与问题

Gate-A6 合成恢复 pilot（k0_4+γ 固定，6 参数自由，100 trials，全量 8192 点）：
k0_1 在 3/4 模式完全错过 truth（低 1–4 个数量级）。遗留问题：是**优化器局限**
（换算法/加预算可解）还是**当前协议在给定条件下缺少约束**（换同类 trial 无用）？

## 2. 证据链（本会话，legacy 全量）

### 2.1 算法对比：TPE 与适配版 CMA-ES 都恢复不了 k0_1

| 采样器 | seed | k0_1 估计 | k0_1 NBE | k0_2 NBE | k0_3 NBE | G_OH 估计 |
|---|---|---|---|---|---|---|
| TPE（归档 100t） | 7/17/27 | 0.03 / 0.003 / 0.02 | 0.51–0.64 | 0.05–0.19 | 0.003–0.56 | 1.10–1.35 |
| cmaes_raw（本会话 100t） | 7/17/27 | 9.7 / 0.81 / 0.89 | 0.20–0.34 | 0.07–0.23 | 0.02–0.46 | 1.40（✓ 精确） |

truth：k0_1=398，k0_2=0.251，k0_3=158，G_OH=1.4。
CMA-ES（raw cmaes 包，盒子中点温启动，100 trials）比 TPE 好一档，但三个 seed 全部漏掉 k0_1
（低 1.6–2.7 个数量级）。k0_2/k0_3/G_OH 两者都能恢复。**问题特定于 k0_1。**

### 2.2 k0_1 单独条件 profile：给定其余真值时仍是水平平台

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

→ 在“其余参数固定为合成 truth”的条件切片上，目标函数从 398 到盒子上界（高 2.4 个数量级）
近似水平；向下 k0_1<~100 才陡升。它支持**该离散 M0 协议下的条件式单边敏感性**
（可报告条件下界约 100–160），不证明全参数空间无唯一极小值，也不授权实验点估计。

耦合伙伴已核实固定在 truth 模型取值上：
- `G_OH`(=E01)：显式固定 truth 1.4，`params_from_vector` → `apply_alkaline_aem` 每次重算 E01=G_OH；
- `θ_ox`（k0_pre/E0_pre）：不在 truth 字典（truth_library 只存 8 个 z），走默认
  k0_pre=500 / E0_pre=1.45——`make_synthetic_target` 用同一 config 生成 target，两边一致。

### 2.3 Tafel 对 k0_1 免疫，对 G_OH 敏感

| 情形 | k0_1 | G_OH | 表观 Tafel (mV/dec) |
|---|---|---|---|
| k0_1 跨 5 个数量级（3.98→3.98e4） | 任意 | 1.4 | 恒定 125.9 |
| G_OH 1.1→1.4 | 398 | 变化 | 103→126 |

→ 在本 M0 合成扫描内，表观 Tafel 对 k0_1 不敏感、对 G_OH 有响应。真实文献 Tafel 是否能
提供独立约束仍待用独立实验模型验证，不能由此表直接推出。

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

模型解释：当 k0_1 增大时，M0 中 step-1 接近准平衡，数值输出主要由后续步骤和覆盖度控制，
于是此协议的目标对 k0_1 变化变钝。这是对 M0 实现的可检验机制假设，不是对真实 Co3O4
界面动力学的直接判定。

## 3. 文献对齐

- **sloppy models / practical identifiability**（Gutenkunst、Sethna）：多参数动力学模型
  常出现条件数很大的局部信息矩阵；少数方向在指定协议下敏感，其余方向输出变化小。本工作仅有
  truth-fixed 1-D 切片，尚未完成全空间 profile likelihood、Fisher/SVD 或独立 truth 验证，
  因而不把参数标为结构上 sloppy/stiff。
- **电化学 practical identifiability**（Bond、Simonov、Gavaghan 线）：AC/谐波能提高可辨识性，
  但速率常数与热力学/覆盖度/面积等**参数组等价**仍存在；OER 微动力学部分速率常数在可测频段
  明确不可辨，处理是固定或放弃，不是加 trial。
- **Tafel/Arrhenius 补偿**：高过电位斜率由控速步决定，表观 Tafel 不能当作逐步 k0 的独立标定
  ——与「k0_1 跨 5 数量级 Tafel 不变」一致。

## 4. 当前可支持的结论与边界

> 对当前无噪、全量、M0 合成目标的 truth-fixed 1-D 切片，k0_1 在高值区呈单边平台；
> 同预算 TPE 与 raw-CMA 也未恢复该合成 truth。正式恢复暂不报告 k0_1 点估计，改为在明确
> 固定条件下报告敏感性/下界候选并传播不确定度。是否为全空间 practical/structural
> non-identifiability，须经重优化 profile、多个 truth、噪声/holdout 和未来 A1 数据验证。

## 5. 处理建议

| 策略 | 对 k0_1 |
|---|---|
| 承认不可辨，改报告对象 | 报告 stiff 组合 / 条件值（如「固定 G_OH 下的 k0_1」），不报点估计 |
| 固定或强先验钉一条腿 | 用 DFT 范围钉 G_OH（ΔG_*OH 软先验 0.8–1.3 eV 中心），或固定 k0_1 名义值做敏感性 |
| 切断补偿通道 | 独立约束预氧化（k0_pre, E0_pre → θ_ox）或低过电位 CV 特征，再复查 k0_1 |
| 换坐标再优化 | 在 active/组合坐标上估，k0_1 方向按 inactive 传播不确定度 |
| 暂停增加同类数据 | 在现有条件切片中，增加同类 FTacV trial 不会直接检验该补偿；需新协议或独立约束 |
| 预测仍可准 | sloppy 参数松、输出预测可紧——正演/谐波形状仍可用 |

## 6. 对旧归档结论的修订

旧 SUMMARY 结论 #2「瓶颈是 TPE 探索不足」→ **修订为：当前合成协议中同时存在优化探索困难
与 k0_1 高值区条件平台。**证据是 truth-fixed 1-D profile 与三个 seed 的对照；不以此宣称
结构不可辨。

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

## 9. 全参数可辨识性报告（2026-08-06，补充）

工具 `code/python/scripts/screen_identifiability.py`（`2583330`，修复 `54a0d34`）：1-D 剖面，
其余参数固定 truth，全量 8192 点。Legion 并行结果（`worktrees/54a0d34/a6_identifiability/screen_log/`）：

| 参数 | 条件切片分类 | within 2×floor | 当前证据 |
|---|---|---|---|
| k0_1 | one-sided | [119, 1e5] | ✗ 只有下界（≳119） |
| k0_pre | one-sided | [100, 1e5] | ✗ 只有下界（≳100） |
| k0_2 | sharp | [0.251, 0.251] | 仅条件切片敏感 |
| k0_3 | sharp | [158.5, 158.5] | 仅条件切片敏感 |
| G_OH | sharp | [1.4, 1.4] | 仅条件切片敏感 |
| G_O | sharp | [2.68, 2.68] | 仅条件切片敏感 |
| scaling_OOH_OH | sharp | [3.36, 3.36] | 仅条件切片敏感 |

**条件式敏感性图**：在其余值固定为 truth 的 1-D 剖面中，k0_2/k0_3/G_OH/G_O/scaling 显示窄谷，
k0_1 与 k0_pre 显示高值区平台。这提示预氧化 θ_ox 供应与 step-1 速率可能补偿；分组、
全局可辨性和真实体系含义均待验证。

**报告约定（A，sloppy-models / practical-identifiability 文献）**：
1. 当前正式输出不报 k0_1/k0_pre 点估计；可在注明固定条件下报告约束范围；
2. 优化前先用重优化 profile / 局部敏感性确定候选自由坐标，不能把本 1-D 结果当作最终分组；
3. 后续需用多个 truth、噪声、holdout 与 A1 数据做独立验证，不能单报最优一点。

## 10. C 落地：stiff-coordinate 恢复 + 范围报告（2026-08-07）

- 自由 = 5 sharp（k0_2/k0_3/G_OH/G_O/scaling）；固定 = k0_1=1e3、k0_pre=1e3（平台值）。
- Legion 全量 3 seed × 100 trials（`worktrees/54a0d34/a6_stiff_coord/`）：
  - best seed：k0_2 NBE 0.042、G_OH 0.036、G_O 0.033、k0_3 0.081（2–3× 内）；
  - obj 0.63–2.4（地板 0.015 的 40–160×）——优化器 100 trials 盒子中点未进窄盆地，属探索问题。
- 报告契约：k0_1 ≳119、k0_pre ≳100 到盒子上界，不报点估计。
- 当前结论：在这组固定值和合成 truth 下，部分候选参数的误差降低；该结果不能区分
  实际可辨性与 inverse-crime 条件优势，仍需独立 truth/noise/holdout 验收。

## 11. 探索 gap 根因：盆地宽度 < 优化器步长（2026-08-07，突破）

- 温启动到 truth（默认 sigma=0.25）：obj 漂到 1.1–2.0（地板 70–130×）——从 truth 也逃逸。
- **小步长验证（--init truth --sigma 0.02，全量 3 seed × 100 trials）：obj 0.017–0.036
  （地板 0.015 上），5 个 sharp 参数 NBE ≤ 0.024（2–3% 内）**。
- 根因：sharp 盆地 < 0.5 decade，CMA-ES 默认 sigma=0.25 ≈ 2 decade，第一代采样即逃出。
- 结论：小步长能在 truth 初始化附近维持局部盆地；这只校准局部步长，不证明从无先验可恢复，
  也不改变 k0_1/k0_pre 的条件平台观察。
- 证据：`~/OER-FTAcV-archive/results/{ddb89b3/a6_warmstart, 6b2bd18/a6_sigmasmall}/`。

## 12. 对原始框架结论的修正（2026-08-07）

原始框架把两个不同的问题混在一起了，需修正：

1. **条件剖面与恢复表现不是同一证据**：k0_1/k0_pre 的高值平台和其它参数的窄切片，
   都只是在“其余参数固定 truth”的局部诊断，不是全空间 landscape 真相。
2. **恢复表现依赖优化器与初始化**：TPE/CMA 的结果受到步长/init 限制；truth-init 小步长
   的低 NBE 只证明局部数值一致性，不能证明无先验可恢复。
3. 原归档中“探索不足”与“参数不可辨”的表述均应保留为待验证假设，等待重优化 profile 和
   独立合成/实验门，而非对不同参数给出确定物理标签。

**修正后的恢复图景**：
- k0_2/k0_3/G_OH/G_O/scaling：在 truth-fixed 剖面中敏感；需要无先验恢复和 holdout 才能升级；
- k0_1/k0_pre：在该切片上为高值平台；暂只做条件敏感性报告；
- 后续策略：先做重优化 profile、多个 truth/noise/holdout，再决定实际自由坐标与搜索步骤。

## 13. 两阶段恢复端到端：无先验失败（2026-08-07，重要边界）

两阶段（12 随机起点粗搜 → 最优点 sigma 0.02 细化）**未找到 truth 盆地**：
- Stage 1 最优 obj 0.66（参数远于 truth）；Stage 2 refine 到 obj 0.31–0.34，
  但 NBE 仍 0.13–0.66（细化只是练低错误局部极小）。
- 原因：sharp 窄井体积分数 ~1e-6（5-D 盒），1200 evals 随机采样采不到；
  truth init 能恢复（NBE ≤ 0.024），但无先验搜索找不到。
- **边界**：truth 初始化的局部低损失不能证明可无先验恢复；目前无先验两阶段失败，
  所以 future initial_params 必须作为待验证物理先验，并与外部来源和 holdout 绑定。
- 证据：`~/OER-FTAcV-archive/results/af3acb5/a6_twostage/`。
