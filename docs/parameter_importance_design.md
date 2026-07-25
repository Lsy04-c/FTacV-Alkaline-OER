# 参数重要性模块设计前瞻

项目：碱性 OER AEM FTacV 参数反演平台  
负责人：刘拾玉  
日期：2026-07-18

背景修正：当前实验数据来自常规宏观电极体系，不是微纳电化学测试数据。参数重要性模块的目标不只是筛选 AEM 机理参数，还要判断哪些参数能与催化剂导电性、电荷传输、膜层接触和有效活性面积建立联系。

## 1. 模块定位

参数重要性模块不直接替代机理反演，也不直接给出最终机理结论。

它的作用是回答：

```text
在当前 AEM 机理模型、当前实验条件和当前可分辨谐波下，
哪些参数最影响 FTacV 特征？
哪些参数值得反演？
哪些参数应该固定、给窄边界，或只作为诊断？
哪些参数变化可能反映导电性或电荷传输差异？
```

因此，这个模块应放在反演前后两处使用：

```text
实验数据分析
→ 可分辨谐波判断
→ 参数重要性分析
→ 确定反演参数、边界和通道权重
→ TPE/其他优化反演
→ 参数可识别性复核
```

核心原则：

```text
机理模型负责物理真实性。
机器学习或统计分析只负责判断参数对可观测特征的影响。
```

## 2. 为什么需要这个模块

当前 OER 代码已经可以运行正演和 TPE 反演，但仍有一个核心风险：

```text
拟合曲线变好，不等于参数具有机理意义。
```

主要问题包括：

- 多个参数可能对同一谐波产生相似影响；
- 快动力学步骤在当前频率下可能不可分辨；
- `gamma`、`A`、`Cdl`、背景电流可能互相补偿；
- `Ru` 主要影响高电流区和相位，缺少 EIS 时不应自由乱跑；
- 高阶谐波如果信噪比低，不能强行进入目标函数；
- 线性标度关系是先验，不是已经被本体系证明的定值。
- 宏观电极体系中，传质、电阻、电容、催化层接触和导电网络可能显著影响 FTacV 响应。

参数重要性模块的任务不是让拟合更好，而是降低错误解释的概率。

在当前课题背景下，它还要避免另一个错误：

```text
把导电性或电荷传输导致的响应变化，误解释为 OER 本征吸附能或 k0 变化。
```

## 3. 第一版建议：局部单参数敏感性分析

第一版不建议直接使用深度学习。更稳妥的方案是做可解释的局部敏感性分析。

基本思想：

```text
以一组基准参数为中心。
每次只扰动一个参数。
运行 ODE 正演。
提取 FTacV 特征。
计算该参数扰动造成的特征变化。
```

优点：

- 结果容易解释；
- 计算成本可控；
- 适合与老师讨论；
- 不会变成黑箱模型；
- 可以直接服务于反演参数选择。

## 4. 输入参数

第一版建议纳入以下参数。

### 4.1 AEM 动力学参数

```text
k0_1  *ox → *ox-OH
k0_2  *ox-OH → *ox-O
k0_3  *ox-O → *ox-OOH
k0_4  *ox-OOH → *ox + O2
```

这些参数决定各步电子转移动力学。它们通常跨数量级变化，应在 `log10` 空间扰动。

### 4.2 热力学与标度关系参数

```text
G_OH
G_O
scaling_OOH_OH
```

这些参数决定：

```text
G_OOH = G_OH + scaling_OOH_OH
DeltaG1 = G_OH
DeltaG2 = G_O - G_OH
DeltaG3 = G_OOH - G_O
DeltaG4 = 4.92 - G_OOH
E01-E04 = DeltaG1-DeltaG4
```

它们直接影响理论过电位、可能的速控步和 onset 行为。

### 4.3 活性位点与电路参数

```text
gamma
Cdl
Ru
A
```

这些参数对电流幅值、背景电流和高电流区形状有影响。它们容易与催化剂真实动力学耦合，必须单独检查。

在宏观电极数据中，这组参数不能只看作干扰项：

- `Ru` 可能包含溶液电阻、膜层电阻、集流体/催化层接触电阻；
- `Cdl` 可能反映粗糙度、界面面积、电容背景和导电网络；
- `gamma` 可能反映有效活性位点数量，也可能受有效导电面积影响；
- `A` 是几何面积或有效面积的入口，容易与 `gamma/Cdl` 互相补偿。

因此，后续输出应增加一个导电性相关参数组：

```text
conductivity_related_params = [Ru, Cdl, gamma, A]
```

该参数组要单独报告，不应简单并入“背景参数”。

### 4.4 预氧化参数

```text
E0_pre
k0_pre
```

预氧化参数决定 Co3+/Co4+ 活性位形成过程。它们如果固定错误，可能影响后续 AEM 参数反演。

## 5. 特征输出

参数重要性不应只看总电流误差。建议提取以下特征。

### 5.1 主拟合特征

```text
DC shape
H1 shape
H2 shape
H3 shape
Tafel slope
onset potential
```

当前真实数据中，H1-H3 相对可分辨，H4-H7 暂时只作为诊断。

### 5.2 幅值与位置特征

```text
DC amplitude
H1 peak intensity
H2 peak intensity
H3 peak intensity
H1 peak potential
H2 peak potential
H3 peak potential
```

这些特征有助于区分：

- 参数是否只改变整体幅值；
- 参数是否改变反应发生的电位区间；
- 参数是否改变谐波形状。

### 5.3 诊断特征

```text
H4-H7 shape
H4-H7 amplitude
high-current residual
low-potential baseline
pre-oxidation region current
phase-related deviation
high-current slope distortion
```

这些特征默认不进入主评分，但应写入报告，作为模型失配提示。

其中 `high-current residual`、`phase-related deviation` 和 `high-current slope distortion` 应作为导电性/电荷传输相关诊断特征。

## 6. 扰动规则

扰动幅度必须和参数类型匹配。

建议第一版使用：

| 参数类型 | 扰动方式 |
| --- | --- |
| `k0_1-k0_4` | `log10(k0) ± 0.25 decade` |
| `gamma` | `log10(gamma) ± 0.25 decade` |
| `G_OH`、`G_O` | `±0.05 eV` 或 `±0.10 eV` |
| `scaling_OOH_OH` | `±0.05 eV` 或 `±0.10 eV` |
| `E0_pre` | `±20-50 mV` |
| `k0_pre` | `log10(k0_pre) ± 0.25 decade` |
| `Cdl` | 按标定误差或 `±20%` |
| `Ru` | 按 EIS 误差或 `±20%` |
| `A` | 按面积误差或 `±5-10%` |

如果扰动后参数超过经验边界，应截断或跳过该扰动，并在报告中标注。

## 7. 评分方法

对每个参数 `p_i`，分别计算正向扰动和负向扰动：

```text
features_base = forward(base_params)
features_plus = forward(base_params with p_i + delta)
features_minus = forward(base_params with p_i - delta)
```

每个特征的归一化变化可以定义为：

```text
change(i, j) =
0.5 * (
  distance(features_plus_j, features_base_j)
  + distance(features_minus_j, features_base_j)
)
```

总重要性：

```text
importance_i =
sum_j feature_weight_j * normalized_change(i, j)
```

其中 `feature_weight_j` 来自实验可信度。

## 8. 特征权重来源

权重不应手动全等。建议由以下因素共同决定：

```text
feature_weight =
SNR_weight
× repeatability_weight
× background_penalty
× sensitivity_validity
```

第一版如果没有重复实验，可以先用：

- 原始谐波 RMS；
- 与最强谐波的相对幅值；
- 低电位基线污染；
- 是否为当前可分辨通道。

当前真实数据的临时策略：

```text
H1-H3 进入主评分。
H4-H7 只做诊断。
```

后续有重复实验后，再把重复性纳入权重。

## 9. 输出结果

模块不应只输出一个排序表。建议输出结构化结果。

```json
{
  "active_features": ["DC", "H1", "H2", "H3", "Tafel", "onset"],
  "diagnostic_features": ["H4", "H5", "H6", "H7", "baseline"],
  "parameter_importance": [
    {
      "name": "G_OH",
      "score": 0.82,
      "level": "strong",
      "main_features": ["Tafel", "onset", "H1"],
      "warning": null
    },
    {
      "name": "gamma",
      "score": 0.64,
      "level": "medium",
      "main_features": ["DC amplitude", "H1 amplitude"],
      "warning": "may couple with A, Cdl, and background current"
    }
  ]
}
```

建议把参数分为四类：

```text
strong      强影响参数
medium      中等影响参数
weak        弱影响参数
unresolved  不可识别或疑似耦合参数
```

另建议增加一组横向标签：

```text
mechanism_related      主要关联 AEM 反应步骤
conductivity_related   主要关联导电性/电荷传输/接触电阻
background_related     主要关联电容或基线背景
coupled                多类因素耦合，不能单独解释
```

## 10. 和反演算法的关系

参数重要性模块应服务于反演，而不是替代反演。

建议流程：

```text
1. 用默认参数或初步反演参数作为 base_params。
2. 做参数重要性分析。
3. 根据结果决定哪些参数自由反演。
4. 对弱影响参数固定或给窄边界。
5. 对耦合参数加入 warning。
6. 运行 TPE 或其他优化器。
7. 反演结束后再次做重要性和可识别性复核。
```

示例：

```text
如果 k0_4 对 DC/H1-H3 几乎无影响，则不应自由解释 k0_4。
如果 gamma 强烈影响所有幅值，但和 A/Cdl 耦合，则不能单独解释为活性位真实变化。
如果 G_OH 改变 onset 和 Tafel，则它更可能是机理解释重点。
如果 Ru 强烈影响高电流区和谐波相位/幅值衰减，则它更可能与导电性或电荷传输有关。
```

## 11. 第二版扩展方向

第一版局部敏感性稳定后，可以扩展到更系统的方法。

### 11.1 Morris screening

用途：

```text
快速筛选高维参数中哪些最重要。
```

优点：

- 计算量比 Sobol 小；
- 能识别非线性和交互趋势；
- 适合参数较多时预筛选。

### 11.2 Sobol 全局敏感性

用途：

```text
区分一阶影响和参数交互影响。
```

缺点：

- 计算成本高；
- 需要大量正演；
- 适合后期或代理模型加速后使用。

### 11.3 代理模型加速

用途：

```text
用机器学习学习 参数 → FTacV 特征 的映射，降低正演成本。
```

限制：

- 代理模型只能加速筛选；
- 最终结论必须回到真实 ODE 正演验证；
- 不能用代理模型直接替代机理模型。

### 11.4 SHAP / Tree-based importance

用途：

```text
在大量模拟数据上分析参数对特征的贡献。
```

限制：

- 结果依赖训练数据覆盖范围；
- 容易把模型内部相关性误解释为真实化学机制；
- 只能作为辅助证据。

## 12. 第一版实现建议

建议新增文件：

```text
python/oer_aem/importance.py
```

建议核心函数：

```python
def analyze_parameter_importance(base_params, config, feature_weights=None):
    ...
```

建议输出：

```text
importance table
feature sensitivity matrix
warnings
active features
diagnostic features
```

建议测试：

```text
test_single_parameter_perturbation_changes_expected_feature
test_log_parameter_perturbation_uses_decade_units
test_unreliable_harmonic_is_excluded_from_score
test_importance_result_contains_warnings_for_coupled_parameters
```

第一版验收标准：

```text
能对当前参数集输出稳定排序。
能说明每个参数主要影响哪些 FTacV 特征。
能区分拟合通道和诊断通道。
不把不可分辨参数强行解释为重要参数。
```

## 13. 参数耦合分析扩展

当前更重要的算法方向是先解决参数耦合，而不是继续更换优化器。

核心假设：

```text
参数耦合强，会提高有效搜索维度。
有效搜索维度高，会增加 TPE/其他优化器的搜索成本。
先识别耦合参数组，再固定、合并或收窄部分参数，可以降低反演成本。
```

### 13.1 压力测试

这个想法合理，但不能过度承诺。

成立条件：

- 当前拟合困难主要来自参数耦合，而不是滤波带宽错误、背景未扣除或物理模型缺项；
- 单参数扰动得到的特征变化向量稳定；
- 不同参数对 DC、H1-H3、Tafel、onset 的影响有可区分性；
- 后续多组实验数据有足够一致的采集条件；
- 机器学习只用于推荐搜索空间和识别耦合类型，不直接输出机理结论。

主要风险：

- H4-H7 噪声大，不能用于耦合判断；
- 如果 H3 也不稳定，耦合矩阵只能依赖 DC/H1/H2，信息量不足；
- `gamma/A/Cdl/Ru` 可能需要 EIS、负载量、膜厚或空白背景才能拆开；
- 模型缺少宏观电极传质或膜层电阻时，耦合诊断可能把模型缺项误判为参数耦合；
- 后续机器学习可能学到批次差异，而不是机理差异。

反证标准：

```text
如果同一参数在重复数据中的重要性排序大幅变化，
或者解耦后反演结果仍不稳定，
或者多起点结果落在多个互不相容的参数组，
则说明当前数据不足或模型缺项，不能继续强行做参数解释。
```

### 13.2 计算方法

利用已有参数重要性模块的 `feature_sensitivity_matrix`。

对每个参数构造特征变化向量：

```text
v_i = [
  ΔDC,
  ΔH1,
  ΔH2,
  ΔH3,
  ΔTafel,
  Δonset,
  ...
]
```

再计算参数之间的相似度：

```text
coupling(i, j) = cosine_similarity(v_i, v_j)
```

如果两个参数的特征变化方向高度相似，说明在当前实验条件下它们难以区分。

### 13.3 输出

建议输出：

```text
parameter_coupling_matrix
strong_coupling_pairs
coupling_groups
recommended_free_params
recommended_fixed_params
recommended_bounds
```

示例解释：

```text
gamma / A / Cdl 强耦合：不宜同时自由反演。
E0_pre / k0_pre 强耦合：建议先固定一个。
G_OH / G_O / scaling 强耦合：标度关系参数需要扫描或给窄边界。
k0_i 之间强耦合：当前频率下部分动力学步骤不可分辨。
```

### 13.4 与机器学习的关系

后续有多组实验数据后，机器学习可以学习：

```text
实验条件 + 谐波质量 + 初步敏感性矩阵
→ 推荐哪些参数自由反演
→ 推荐哪些参数固定或给窄边界
→ 判断哪些参数组强耦合
```

不建议让机器学习直接学习：

```text
实验曲线 → 机理参数
```

这样容易得到好看的结果，但不能保证参数有化学意义。

## 14. 当前应避免的做法

不要直接做：

```text
实验曲线 → 参数
实验曲线 → 机理结论
```

也不要直接用深度学习替代：

```text
ODE 正演
AEM 机理模型
标度关系约束
参数边界
实验可信度判断
```

这些做法可能得到好看的拟合，但不能支撑机理解释。

## 15. 简短结论

参数重要性模块应先做成：

```text
基于机理正演的可解释敏感性分析模块。
```

它的最终作用是：

```text
告诉我们哪些参数值得反演，
哪些参数应该固定，
哪些参数只能给范围或下限，
哪些参数变化真正影响可观测 FTacV 特征。
```
