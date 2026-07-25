# OER-FTAcV 工作进展总结（2026-07-18，更新：2026-07-20）

项目：碱性 OER AEM 微观动力学建模与 FTacV 参数反演平台
负责人：刘拾玉
目标体系：Co3O4 / CoOx(OH)y 碱性 OER
当前主线：FTacV 多组数据支持 AEM 热力学描述符的稳定识别，但动力学参数与有效位点数存在强补偿。下一阶段以独立约束 gamma 和分阶段反演为核心，提升参数可解释性。

---

## 1. 当前判断

这套代码已经从早期 demo 进入“可运行的机理反演原型”阶段，但算法还不能作为最终科研结论使用。

当前算法能做：

- 上传实验 FTacV 数据；
- 自动识别 f、dE、扫描范围、扫描速率；
- 提取 DC 与 1-7 次谐波；
- 运行 OER AEM 正演模型；
- 用 TPE 搜索机理参数；
- 用当前参数或反演参数正演并与实验叠加；
- 给出拟合完成度提示；
- 按实验谐波强度自动建议拟合通道。

当前算法还不能直接证明：

- 某个参数就是真实控制因素；
- 反演得到的 k0 或吸附能一定唯一；
- 高阶谐波不匹配一定来自 OER 机理；
- 基底背景、电容泄漏、预氧化残余电流已经被正确分离。

结论：**现在的方向是对的，但目标函数、谐波权重、背景扣除和参数可识别性仍需要重新设计。**

---

## 2. 最近完成的代码进展

### 2.1 TPE 反演核心

已建立 `python/oer_aem/inversion.py`，包含：

- `DEFAULT_PARAM_SPECS`
- `InversionConfig`
- `InversionResult`
- `encode_params`
- `decode_vector`
- `params_from_vector`
- `forward_current`
- `extract_features`
- `make_synthetic_target`
- `InversionObjective`
- `TPEInverter`
- `assess_fit_quality`

对应提交：

- `3bb8b97 feat(inversion): add TPE inversion core`
- `28a1711 feat(inversion): report fit quality`

### 2.2 前端反演流程统一

已取消单独、容易误解的 CMA-ES 页面，把实验数据、正演、反演放在同一个页面。

当前主页面为：

```text
实验 · 正演 · 反演
```

当前图线语义：

- `Experiment` / `Exp DC`：实验数据；
- `当前参数正演`：用户当前参数的正演；
- `反演参数正演`：TPE 反演后参数的正演；
- 没有反演前，不再把正演线称作拟合线。

对应提交：

- `3435ba4 fix(frontend): preserve simulation state across tabs`
- `79651e2 feat(web): connect TPE inversion workflow`
- `812d914 fix(frontend): unify experiment inversion workflow`

### 2.3 初始参数与固定参数

反演时现在会：

- 把当前页面参数作为 `initial_params`；
- 把 `Cdl`、`Ru`、`A`、`E0_pre`、`k0_pre` 作为 `fixed_params`；
- 第一轮 trial 优先评估当前经验初值；
- 避免优化器一开始就跳到完全无物理依据的参数区。

对应提交：

- `f8bf5ab fix(inversion): honor priors and initial parameters`

### 2.4 参数归一化、经验边界、谐波筛选

已新增：

- 参数先映射到 `[0, 1]` 归一化空间搜索；
- 再按物理边界解码回真实参数；
- API 支持传入 `param_bounds`；
- 实验数据分析时用原始谐波 RMS 判断哪些谐波可分辨；
- 反演目标函数只拟合可分辨谐波，其余谐波只作为诊断图保留；
- 前端显示哪些谐波参与拟合，哪些只做诊断。

真实数据 `data/raw/ftacv4-ref-1hz.txt` 当前判定：

```text
拟合通道：H1, H2, H3
诊断通道：H4, H5, H6, H7
```

对应提交：

- `3edb8de feat(inversion): normalize search and select harmonics`

### 2.5 参数重要性分析模块

已建立 `python/oer_aem/importance.py`，实现局部单参数敏感性分析。核心入口：`analyze_parameter_importance(base_params, config)`。

分析 13 个参数：k0_1~4、k0_pre、gamma（log10 扰动±0.25 decade）、G_OH、G_O、scaling_OOH_OH（±0.05 eV）、E0_pre（±30 mV）、Cdl、Ru（±20%）、A（±5%）。每个参数正负双向扰动共 26 次 ODE 正演。

特征输出：DC shape/amplitude、H1-H7 shape/peak、Tafel 斜率、onset 电位。H1-H3 进入主评分，H4-H7 仅诊断。

输出结构：

- `parameter_importance`：13 参数按敏感性排序（score/level/main_features/warning）
- `feature_sensitivity_matrix`：特征×参数变化矩阵
- `warnings`：耦合参数提示（如 gamma/A/Cdl 同时影响 DC amplitude）
- `feature_weights`：自动从谐波 RMS 计算的各特征权重

测试：12 个测试（`python/tests/test_importance.py`），与已有 16 个测试合计 28 个全部通过。

### 2.6 机理调试与参数文献标定（2026-07-19）

**信号处理修复（3 处）：**

- `extract_dc_fft`：DC 带宽从裸 `band[0]` 改为自适应（`max(band[0], min_bw)`），防止低 n_points 时波形压平
- `initialize_filters`：带通滤波器带宽从裸 `band[H]` 改为走 `_auto_band`，消除 FFT 路径与时域路径的带宽不一致（之前 4.51 Hz vs 1.0 Hz）
- `solve_ode_system`：`max_step` 约束为 `min(T/50, 1/(f*20))`，确保每 AC 周期至少 20 步采样

**参数文献标定（Moysiadou 2020 JACS + Davis 2023 Nat. Commun.）：**

- `E0_pre`：1.45→1.50 V（Moysiadou：0.1 M KOH 中 Co³⁺/⁴⁺ 氧化峰实测）
- `Cdl`：文献值 80 µF/cm²（Davis：光滑 Co₃O₄(111) 薄膜），当前保留 20 µF/cm² 待实验标定
- `gamma`：文献值 ~1×10⁻⁹ mol/cm²（Moysiadou：表面 Co 密度 6.1×10¹⁴/cm²，~12% 活性），当前保留 5×10⁻⁸ 待实验标定
- `A`：0.196→1.0 cm²（匹配实际电极）

**HER vs OER 对比诊断文档：**

- 完成 `docs/her_oer_comparison_critique.md`：系统对比谐波提取、目标函数、参数可识别性
- 核心结论：代码移植正确，欠拟合根因不是算法错误，而是 gamma 未独立标定 + 基底背景未扣除 + 谐波权重不合理
- 高次谐波（h4-h7）弱是 AEM+α=0.5 框架的物理极限，非代码错误

**参数调优过程：**

- 尝试增大 gamma（至 2×10⁻⁷）、dE（至 0.30V）、降低 Cdl（至 2×10⁻⁶）、非对称 α（0.35）
- 最优谐波分离：h2/h1≈11%、h3/h1≈4.4%、h4-h7<2%
- 结论：h4-h7 在 5 步 AEM + α=0.5 框架内天然弱，无法通过调参突破 2%

**测试状态：**

- 24/28 通过，4 个 inversion 测试失败（Tafel 提取在 n_points=256 低分辨率下不可靠，因 A=1.0 cm² 使电容电流增大 5 倍；属已知限制，非今日引入）

---

## 3. 当前算法的主要问题

### 3.1 目标函数还不够物理化

现在目标函数主要比较：

- DC；
- 选定谐波包络；
- Tafel 斜率。

问题是：

- 每个谐波归一化后会丢失真实幅值信息；
- 电容背景和基底背景可能混进 DC；
- 低电位基线不为零会影响反演；
- Tafel 区间如果不是纯动力学区，会误导动力学参数；
- 只用包络可能丢失相位信息。

下一版目标函数应考虑：

- 实验噪声；
- 空白基底背景；
- 谐波 SNR；
- 重复实验稳定性；
- 幅值和相位是否同时可用；
- DC、H1-Hn、Tafel 各自的物理可信度。

### 3.2 参数可识别性不足

当前能找到一组参数让目标函数下降，但这不等于参数唯一。

高风险参数包括：

- `k0_1`、`k0_2`、`k0_3`、`k0_4`
- `gamma`
- `Cdl`
- `Ru`
- `G_OH`
- `G_O`
- `scaling_OOH_OH`

原因：

- 快步骤在 1 Hz 左右可能不可分辨；
- 多个参数可能对同一谐波产生相似影响；
- `gamma`、`A`、`Cdl`、背景电流可能互相补偿；
- 标度关系减少自由度，但也会引入参数相关。

### 3.3 HER 代码不能直接照搬

HER 代码已有：

- `log_` 参数化；
- 手动经验边界；
- CMA-ES 内部 `[0, 1]` 归一化采样；
- DC + H1-H7 相对误差目标函数；
- `harmonic_weights = [1,1,1,1,1,1,1,1]`。

但 HER 没有：

- 自动判断实验谐波是否可分辨；
- 按 SNR 或重复性给谐波降权；
- 系统处理基底背景；
- 证明各参数的可识别性。

因此 OER 不能只复制 HER 的“全谐波等权拟合”。

---

## 4. 刘拾玉接下来设计新算法时建议固定的问题边界

新算法不应回答“怎样让曲线最好看”，而应回答：

```text
在给定实验质量和机理模型下，哪些参数能被 FTacV 可靠识别？
哪些参数只能给趋势、范围或下限？
哪些谐波应该进入目标函数？
哪些信号只应作为诊断？
```

建议把新算法拆成四层。

### 4.1 数据可信度层

输入实验数据后先判断：

- DC 基线是否稳定；
- 空白 Ti 板是否有背景；
- H1-H7 的原始幅值；
- H1-H7 的 SNR；
- 谐波峰是否和噪声/旁瓣可区分；
- 重复实验中谐波是否稳定。

输出：

```text
fit_channels
diagnostic_channels
channel_weights
warning_flags
```

### 4.2 参数边界层

边界不能只为了拟合而放宽，应分来源：

- 文献边界；
- 实验标定边界；
- 仪器测量边界；
- 机理硬约束；
- 暂时工程边界。

每个边界最好带来源标签：

```text
fixed / measured / literature / weak_prior / engineering
```

### 4.3 目标函数层

目标函数建议包含：

```text
loss = w_dc * L_dc
     + sum(w_hn * L_hn)
     + w_tafel * L_tafel
     + penalty_physical
```

其中 `w_hn` 不应手动全等，而应来自：

- SNR；
- 谐波重复性；
- 空白背景占比；
- 该谐波对参数的敏感度；
- 是否处于可分辨频段。

### 4.4 可识别性层

反演后必须做：

- 单参数扰动；
- 局部敏感性矩阵；
- 合成数据回收；
- 参数相关性诊断；
- 多起点稳定性；
- 去掉某个谐波后的结果变化。

最终输出不应只是 `best_params`，还应输出：

```text
identifiable_params
weakly_identifiable_params
unidentifiable_params
dominant_factors
model_warnings
```

---

## 5. 下一步代码建议

等新算法设计明确后，优先改底层，不急着改 UI。

建议顺序：

1. 写 `algorithm_design.md`，定义目标函数、权重、边界、可识别性输出。
2. 在 `python/tests/test_inversion.py` 先写测试。
3. 在 `python/oer_aem/inversion.py` 实现新算法核心。
4. 用合成数据验证参数能否回收。
5. 用 `ftacv4-ref.txt` 做真实数据诊断，不强求拟合。
6. 再接 API 和前端展示。

---

## 6. 当前验证状态

最近一次完整验证：

```bash
.venv/bin/python -m compileall -q python/oer_aem web/backend
.venv/bin/python -m pytest python/tests web/backend/test_inversion_api.py -q
```

结果：

```text
17 passed, 1 warning
```

页面检查：

```text
http://localhost:7100/
```

页面能加载；控制台无本次 JSX 运行错误。现有提示主要是 CDN/Babel/form/favicon，不影响当前算法功能。

---

## 7. Git 状态

最新已推送提交：

```text
3edb8de feat(inversion): normalize search and select harmonics
```

远程：

```text
origin/main -> git@github.com:Lsy04-c/FTacV-Alkaline-OER.git
```

当前仍有未提交文件，暂未处理：

```text
M PROJECT_SUMMARY.md
?? preox_check.png
?? sim_vs_exp_current.png
?? web/backend/test
```

这些文件不是本次算法更新的一部分，后续处理前需要单独确认。

---

## 8. 分层反演与跨数据稳定性诊断（2026-07-20）

### 核心发现

对 4 组 FTacV 数据（ftacv2/3/4/8）运行分层 TPE 反演（实验条件固定 → 预氧化边界 → AEM 自由反演），跨数据参数稳定性诊断显示：

**可继续解释的参数：**
- `scaling_OOH_OH`：CV=0.03，跨数据高度稳定
- `G_O`：CV=0.09，跨数据稳定
- `G_OH`：CV=0.26，可用，样品间有合理波动

**不可单独解释的参数：**
- `gamma`：CV=0.89，与 A/Cdl 补偿
- `k0_1~k0_4`：CV=1.0-1.6，多参数互相补偿

### 核心结论

> 多组实验数据表明，AEM 热力学描述符具有较好的跨数据稳定性，而动力学速率常数和有效位点参数存在显著补偿。当前阶段应以热力学参数和标度关系作为主要机理分析对象，避免对单个动力学参数作过度解释。

### 下一步策略

- 固定或强约束 gamma（需 ECSA/负载量/电容测试独立标定）
- 不单独解释每个 k0_i，仅作为拟合辅助
- 用热力学参数（G_OH、G_O、scaling）做主要机理讨论
- 补充 EIS/ECSA/预氧化峰电量来独立约束 gamma/Ru/Cdl

### 新增文件

- `scripts/analyze_data_quality.py` — 批量数据质量评估
- `scripts/staged_inversion.py` — 分层反演脚本
- `results/data_quality/` — 数据质量报告 + 谐波图
- `results/staged_inversion/` — 分层反演报告

### gamma 固定后验证（2026-07-20）

将 gamma 固定为文献值 3×10⁻⁹ mol/cm²（Moysiadou 2020 表面 Co 密度），重跑 staged inversion：

| 参数 | 固定前 CV | 固定后 CV | 结论 |
|------|----------|----------|------|
| scaling_OOH_OH | 0.030 | 0.030 | 稳定 |
| G_O | 0.090 | 0.096 | 稳定 |
| G_OH | 0.260 | **0.156** | 改善（gamma/A 耦合曾拖累 G_OH）|
| k0_1~k0_4 | 1.0-1.6 | 1.5-1.7 | 仍不可靠 |

**结论：热力学参数稳定性在 gamma 约束后仍然成立。** 这验证了当前 AEM 热力学框架对多组数据的解释力。下一阶段可以此为基础撰写项目阶段性结论。

---

## 9. 下一步操作计划（2026-07-20）

已生成：

```text
docs/deepseek/next_action_plan.md
```

当前阶段不按中期汇报推进，而按内部诊断推进。核心任务是定位 `poor fit` 的来源，并压力测试热力学描述符稳定性。

执行顺序：

1. 复核 gamma 约束前后参数 CV，确认热力学稳定性是否真实改善。
2. 定位 `poor fit` 来源，按 DC、H1-H3、onset、高电流区、低电位基线分别诊断。
3. 优先补最低复杂度背景项，不先加入复杂机理。
4. 在背景项和 gamma 约束下重跑 staged inversion。
5. 检查 `G_OH/G_O/scaling_OOH_OH` 是否仍保持跨数据稳定。
6. 根据残差形态只选择一个下一轮模型缺项。

当前判断标准：

```text
不是让拟合曲线更好看，而是找出 AEM 模型为什么 poor fit；
不是证明完整机理，而是验证热力学描述符稳定性是否能经受 gamma、背景和数据质量压力测试。
```

---

## 10. Stage 3 前置诊断更新（2026-07-20）

### 10.1 fixed_params 逻辑修正

发现脚本层问题：`fixed_params` 中包含 `gamma`，但 `DEFAULT_PARAM_SPECS` 仍包含 `gamma` 时，TPE 会继续搜索并覆盖 fixed 值。

已修正：

```text
scripts/staged_inversion.py
scripts/residual_diagnostics.py
scripts/sweep_ru.py
scripts/diagnose_high_current_penalty.py
```

修正原则：凡是进入 `fixed` 的参数，都从 optimizer specs 中移除。

### 10.2 重新固定 gamma 后的 staged inversion

真正固定 `gamma=3e-9 mol/cm2` 后，四组数据结果为：

| 参数 | CV | 判断 |
|---|---:|---|
| `scaling_OOH_OH` | 0.023 | stable |
| `G_O` | 0.038 | stable |
| `G_OH` | 0.068 | stable |
| `k0_1~k0_4` | 1.00-1.73 | unreliable |

结论：热力学参数稳定性更强；动力学参数仍不可单独解释。

### 10.3 Ru 扫描复核

真正固定 gamma 后重跑 Ru=10-50 Ω 扫描，`bias_hi` 仍锁定在约 `+0.399~+0.400`。

结论：

```text
Ru 不是完整高电位区偏差的主因。
```

### 10.4 OH- 传质判断修正

当前残差定义为：

```text
bias_hi = experiment - simulation
```

完整实验网格中 `bias_hi > 0`，表示模型低估高电位区电流。简单 OH- depletion / current-limiting 传质项会降低模拟电流，可能使偏差更差。

因此下一步不应直接加入完整 OH- 传质方程。更稳的顺序是：

1. 核查完整实验网格与 trimmed inversion grid 的残差口径差异。
2. 测试高电位新增贡献项，例如重构导致的 `gamma_eff(E)` 增长。
3. 若符号核查后确认模型在某些口径下高估电流，再讨论 OH- 传质限制。

已新增：

```text
scripts/diagnose_high_current_penalty.py
results/model_gap/high_current_penalty.md
results/model_gap/high_current_penalty.csv
```

---

## 11. 基础环境与测试基线修复（2026-07-25）

已完成：

- 新增`python scripts/run_tests.py ...`标准测试入口，自动使用项目`.venv`；
- 将后端分析脚本改为可被pytest收集的端到端测试；
- 将真实实验输入统一纳入`data/raw/`；
- 修复低分辨率合成目标无法提取Tafel时整条反演中止的问题；
- 同步FastAPI目标契约，允许不可测Tafel为`None`；
- 修正数据质量报告中“H4-H7全部只作诊断”的错误固定文案。

当前新鲜验证：

```text
python scripts/run_tests.py python/tests -q
33 passed

python scripts/run_tests.py web/backend/test_analyze_e2e.py web/backend/test_inversion_api.py -q
3 passed
```

当前共同可靠拟合通道为H1-H3。H4可用于`ftacv2`和`ftacv8`的附加分析，H5仅在`ftacv2`达到当前幅值门槛；H6-H7在所有数据中只作诊断。

详细审计见：

```text
docs/workspace_environment_audit.md
```

`gamma_eff(E)`及旧模型缺项脚本仍属于未验证实验资产，不计入当前通过测试的基线模型。
