# 碱性 OER AEM 微观动力学建模与 FTacV 参数反演平台

整理日期：2026-07-17
负责人：刘拾玉

## 1. 项目立项

### 背景

课题组主要方向为微纳电化学，可在测试中同步获得催化剂性能和电导率数据。然而，常规 LSV/CV/Tafel 方法只能给出宏观活性指标（过电位、Tafel 斜率），无法直接回答以下问题：

- 哪一个反应步骤最影响体系？
- 哪一个中间体或平衡电位最敏感？
- 拟合出的参数是否具有化学意义？
- 不同催化剂之间的差异来自热力学因素还是动力学因素？

FTacV（Fourier-transformed alternating-current voltammetry）的高次谐波信号对不同动力学步骤的敏感度不同，结合微观动力学模型，可以将实验数据转化为有机理意义的参数。

### 目标体系

四氧化三钴（Co₃O₄）碱性 OER，采用吸附物演化机理（Adsorbate Evolution Mechanism, AEM）作为模型起点。Co₃O₄ 在碱性 OER 电位下表面会发生可逆非晶化，形成 CoOₓ(OH)ᵧ 重构壳层——真正的活性相不是原始尖晶石表面，而是这层无定形壳。


### 最终目标

```
实验 FTacV 数据 → 微观动力学模型 → 参数反演 → 敏感性判断 → 解释反应中真正重要的因素
```

构建一个 Web 端可用的 FTacV 参数反演工作台，支持：参数调整 → ODE 仿真 → 谐波提取 → 与实验对比 → 优化反演 → 可视化。

## 2. 核心方法学参考

| 文献                                           | 核心贡献                                                    | 与本项目的关系                                                                                      |
| ---------------------------------------------- | ----------------------------------------------------------- | --------------------------------------------------------------------------------------------------- |
| **Bonke et al. 2016 JACS**               | FTacV + "分子催化"模型反演 CoOₓ/NiOₓ/MnOₓ 的动力学参数   | OER FTacV 参数反演的方法论直接来源，包含预氧化步骤                                                  |
| **Snitkoff-Sol et al. 2024 Nat. Catal.** | FTacV + 微观动力学模型反演 FePc ORR 的所有动力学/热力学参数 | 提供了完整的参数拟合范式：反应步骤→速率方程→标度关系约束→目标函数(Eq. S59)→BADS优化→敏感性分析 |
| **Bergmann et al. 2015 Nat. Commun.**    | Co₃O₄ 在 OER 电位下表面可逆非晶化为 CoOₓ(OH)ᵧ           | 确定了 Co₃O₄ 的真实活性相，指导 DFT 计算表面选择和模型假设                                        |

## 3. 技术路线

### 3.1 物理模型（5 步）

```
步骤 0（预氧化）：* + OH⁻     ⇌ *ox + H₂O + e⁻      (Co³⁺ → Co⁴⁺，催化剂活化)
步骤 1（AEM-1）：*ox + OH⁻   ⇌ *ox-OH + e⁻         (*OH 吸附)
步骤 2（AEM-2）：*ox-OH + OH⁻ ⇌ *ox-O + H₂O + e⁻    (*O 生成)
步骤 3（AEM-3）：*ox-O + OH⁻ ⇌ *ox-OOH + e⁻         (O-O 键形成)
步骤 4（AEM-4）：*ox-OOH + OH⁻ ⇌ *ox + O₂ + H₂O + e⁻ (O₂ 释放，活性位再生)
```

### 3.2 热力学约束

通过线性标度关系降低参数自由度：

```
G_OOH = G_OH + scaling_OOH_OH（≈ 3.2 eV，可调）
→ ΔG₁ = G_OH，ΔG₂ = G_O − G_OH，ΔG₃ = G_OOH − G_O，ΔG₄ = 4.92 − G_OOH
→ E01−E04 全部由 G_OH、G_O、scaling_OOH_OH 生成（仅 2-3 个自由参数）
→ 硬约束：ΣΔG = 4.92 eV（4 × 1.23 V）
```

### 3.3 参数拟合策略

参照 Snitkoff-Sol 2024 的参数三分法：

- **直接拟合**：G_OH、G_O、各步 k⁰ᵢ、预氧化 k⁰_pre、Γ_total、Ru
- **由标度关系计算**：G_OOH、E01−E04、各步 ΔG
- **固定或只给下限**：α=0.5（转移系数）、Cdl（双电层电容）、scaling_OOH_OH（默认 3.2 eV，可扫描）

拟合对象为 FTacV 第 3-6 次谐波的归一化误差（Eq. S59），而非原始总电流。

## 4. 关键难点

### 4.1 预氧化步骤的必要性

Bonke 2016 明确指出，CoOₓ 在催化 OER 之前必须先完成 Co³⁺/⁴⁺ 氧化。如果模型不包含预氧化步骤，低电位区的表面覆盖度和电流 onset 行为会偏离实验。这是当前模型比传统 AEM 四步模型多一步的原因。

### 4.2 标度关系不是绝对常数

G_OOH − G_OH ≈ 3.2 eV 是 DFT 在多种氧化物上的平均值。Snitkoff-Sol 2024 在 FePc 上拟合出 3.03 eV，Co₃O₄/CoOₓ(OH)ᵧ 没有实验标定值。代码中保留为可调参数，默认 3.2 eV，后续可通过 FTacV 数据反演出体系实际值。

### 4.3 微纳体系的特殊性

- Bergmann 2015 的"仅 ~1.8% Co 参与"是中性 KPi + 宏观膜电极的数据，不适用于碱性微纳体系
- 微纳电极半球形扩散效率更高，a_OH⁻ ≈ 1 的假设比宏观体系更可靠
- 活性位点浓度 Γ_total 的数量级需要根据组内实验数据独立标定

### 4.4 参数敏感性

不是所有拟合出的参数都可信。参照 Snitkoff-Sol 2024 SI Note 3，部分参数（如 k₂ > 2000 s⁻¹ 后不敏感、k⁰₄/k⁰₅ 几乎不敏感）只能给下限或固定，不能强行解释为真实化学差异。

## 5. 代码架构（MATLAB → Web 迁移中）

### 当前 MATLAB 模块（OER-FTAcV/）

```
OER_Physics.m              ← 核心：预氧化 + AEM 5 步物理模型
OER_Signal.m               ← 信号处理：FFT/谐波/滤波/对齐
OER_IO.m                   ← 数据 IO：加载实验数据 / 导出
OER_Objective.m            ← 目标函数 + 参数解码 / 优化配置
OER_Params.m               ← 参数打包 / 默认值
OER_Core.m                 ← 统一入口封装
initialize_oer_parameters.m ← 参数初始化（Co₃O₄ 默认值）
apply_alkaline_aem.m       ← AEM 热力学约束（外置函数）
```

### 计划中的 Web 架构

```
React 前端（参数面板、谐波可视化、优化进度）
  ↕ REST API
FastAPI 后端（调度仿真、调用 ODE 求解器）
  ↕
Python 核心（scipy.solve_ivp + NumPy FFT）
```

## 6. 当前进度与待解决问题

### 已完成

- [X] 阅读并整理 Bonke 2016、Snitkoff-Sol 2024、Bergmann 2015 三篇核心文献
- [X] 完成 AEM 热力学约束模块 `apply_alkaline_aem.m`（输入 G_OH/G_O → 输出 E01-E04）
- [X] 完成含预氧化步骤的完整物理模型 `OER_Physics.m`（5 步，覆盖度 + 电位耦合）
- [X] 完成信号处理、数据 IO、参数管理、目标函数等配套模块
- [X] 生成完整微观动力学模型说明文档（co3o4_oer_aem_microkinetic_model.pdf + code implementation PDF）

### 待解决

- [ ] MATLAB 代码未在拯救者上测试（拯救者暂时不可用）
- [ ] 缺少真实 Co₃O₄ FTacV 实验数据进行模型验证
- [ ] 预氧化步骤的 E0_pre 和 k0_pre 需要实验标定
- [ ] MATLAB → Python 翻译
- [ ] Web 前端搭建（参数面板 + Dashboard）
- [ ] 多频率拟合和参数敏感性分析模块
- [ ] 长期：MCMC/CMA-ES 优化算法接入

## 7. 相关文件索引

| 文件                       | 路径                                                  |
| -------------------------- | ----------------------------------------------------- |
| AEM 微观动力学模型文档     | `docs/co3o4_oer_aem_microkinetic_model.pdf`         |
| 代码实现设计文档           | `docs/co3o4_aem_code_implementation.pdf`            |
| 碱性 OER 任务总结          | `docs/alkaline_oer_aem_conversation_summary.md`     |
| Snitkoff-Sol 2024 阅读笔记 | `docs/snitkoff_sol_2024_ftacv_orr_notes.md`         |
| 参数拟合逻辑整理           | `docs/snitkoff_sol_2024_parameter_fitting_logic.md` |
| Agent 参考文档             | `docs/snitkoff_sol_2024_agent_brief.md`             |
| GitHub 配置                | `config/github_project_config.env`                  |
| MATLAB 代码（主目录）      | `OER-FTAcV/`                                        |
