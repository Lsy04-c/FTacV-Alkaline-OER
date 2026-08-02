# OER-FTAcV 综合方案网络文献与物理压力测试

日期：2026-08-02
对象：`2026-08-02-physics-constrained-effective-dimension-inversion-design.md`
范围：公开文献、当前 M0 方程和最小数值复核；不修改当前 A6-v2 S1

## 1. 结论

现有“物理约束 → 有效组合 → 多盆地优化 → 恢复门”方向成立，但执行顺序需要
调整：

```text
解析物理结构与模型假设
→ 精确重参数化和结构可辨识性
→ 模型充分性与噪声契约
→ 多锚点敏感性 / 活跃方向
→ profile
→ 优化器与新后端
```

不能先对原始参数做 active-subspace 式降维。当前 M0 已存在至少一个可解析的
精确结构不辨识；同时，若干参数实际是固定电解液和模型假设下的有效参数，而
不是可跨条件解释的微观常数。

本轮没有发现“换一个优化器即可闭合反演”的文献证据。相反，文献支持先处理
结构/实用可辨识性、覆盖度和实验条件，再比较混合全局—局部优化。

## 2. 检索范围与证据等级

通过 Crossref、OpenAlex、期刊 DOI 页面和公开摘要检索以下主题：

- OER 吸附物演化机理、覆盖度、pH和标度关系；
- Co3O4/CoOx(OH)y 工作态表面；
- 电双层对氧电催化动力学的影响；
- FTacV 水氧化参数化、Bayesian 参数恢复和活性位点密度；
- ODE 模型结构/实用可辨识性、profile和可辨识组合；
- 大型动力学模型的优化器基准、active subspace和多保真降维。

本文把证据分为：

1. **代码可证明事实：** 可直接从当前方程推导并数值复核；
2. **文献事实：** 来源明确的论文结论；
3. **项目推断：** 文献与当前残差/模型之间的合理联系，仍需项目内验证。

## 3. 物理层关键发现

### 3.1 `A/Cdl/gamma` 存在精确结构不辨识

当前模型的表面电位和观测电流为：

```text
dφ/dt = (Eapp-φ)/(Ru·Cdl·A) - (gamma·F/Cdl) Σrj
i      = (Eapp-φ)/Ru
```

令任意正数 `c` 执行：

```text
A'     = c·A
Cdl'   = Cdl/c
gamma' = gamma/c
Ru'    = Ru
```

则 `A·Cdl`、`A·gamma`、`gamma/Cdl` 和整个 ODE/电流均保持不变。因此在
当前 M0、总电流单位为 A 且没有独立面积/电容/位点测量时，三者不能分别由
FTacV 电流识别。

最小LSODA复核使用同一动力学参数和扫描配置，将
`(A,Cdl,gamma)=(1,2e-5,5e-8)` 变为 `(2,1e-5,2.5e-8)`；512个输出点的
最大绝对、相对和RMS差均为0。

应优先沿用代码校准模块已有命名并重参数化为：

```text
CdlA   = A·Cdl       # 总双电层电容，单位 F
GammaA = A·gamma     # 总活性位点量，单位 mol
Ru
```

若 `A` 由几何/电化学面积独立获得，再将总量换算为面密度。以上命名成立的
前提是模型与实验比较的是总电流A。若实验文件已经归一为电流密度，则正演应
直接使用面电容和面位点密度，`A`完全退出正演。现有A1已将电流单位`A`登记为
项目负责人声明，配套CHI CV文件头的`Current/A`提供辅助证据；未闭合的是原始
预处理、仪器增益和面积归一化历史。因此条件模型分支可把
`current_basis=total`作为有来源假设并实施`CdlA/GammaA`，但正式真实反演仍由
A1 `FAIL_METADATA`阻断。合成开发分支则按方程定义冻结为总电流。
网络综述也强调，电化学活性位点密度是区分位点数与周转活性的必要输入，而
不是普通优化器可以自动拆开的量 [9]。

这项结论不依赖局部灵敏度或文献类比，而是当前方程的解析对称性。现有最小
LSODA复核尚未固化为仓库测试，因此实施时必须先增加“等价变换前后全轨迹和
H1-H3严格一致”的自动测试，再修改正式参数schema。

### 3.2 当前五步 M0 是研究假设，不是 Bonke 模型的直接复现

Bonke 等对金属氧化物水氧化的 FTacV 分析使用的是有效“分子催化”模型：一个
表面限域氧化还原过程耦合一个底物催化反应 [3]。原文明确说明，为避免过参数化，
转移系数任意固定为0.50；模型将四电子过程压缩为一个关键电子转移、一个催化
反应和一个假想三电子过程，水浓度折入速率常数，硼酸盐碱基传质显式参与。
实验—模拟比较拟合的核心参数是 `E0cat/k0cat/kf`，不是五步AEM的全部微观参数。
当前代码则使用预氧化加四步 AEM、五个覆盖度状态和每步 Butler–Volmer 速率。

因此：

- Bonke 论文支持 FTacV 能分离催化相关过程；
- 它不直接验证当前五步状态、五个 `k0` 或完整 AEM 参数能由同一数据恢复；
- 当前 `k0_pre/k0_1...k0_4` 应标记为 M0 下的有效速率参数，不能仅凭引用升级
  为材料固有微观常数。

### 3.3 热力学标度关系应分为恒等式与模型先验

Man 等给出了氧化物表面 `HOO*` 与 `HO*` 吸附能的近似通用标度关系，并据此
建立 OER 火山图 [1]。这支持把约3.2 eV用作 AEM 描述符先验，但不支持把它
当作重构 CoOx(OH)y 在所有电位下的精确物理定律。

当前热力学模块需要区分：

- 四电子标准循环总自由能：冻结温度和标准态下的热力学闭合；
- `G_OOH-G_OH`：材料/模型相关的标度先验；
- `G_OH/G_O`：当前 M0 的有效描述符，不等于实验直接观测量。

代码允许 `T` 改变，但总自由能固定为 `4×1.23 eV`。首版应冻结 `T=298.15 K`
和标准态；未来支持温度变化时再引入一致的热力学修正。

现有热力学 docstring 引用的 Snitkoff-Sol 2024 是 FePc 氧还原瞬态伏安研究，
Bergmann 2015 是 Co3O4 工作态重构研究；二者都不是3.2 eV AEM标度公式的一手
来源。Man 2011 才是当前公式更直接的来源。

### 3.4 活度、pH和逆反应口径未显式进入模型

当前每步速率只包含覆盖度、同一组正逆向 `k0` 和电位指数，没有显式
`a_OH-`、水活度或 `p_O2`。这可以解释为固定电解液下的有效速率，但这种
简化不能同时证明正逆反应的活度依赖正确。此时：

- `k0` 不能跨 pH/浓度直接比较；
- 反应级数不能由当前参数自动推出；
- 第4步逆反应等价于使用隐式固定氧活度，而不是代码注释中的 `pO2≈0`；
- 不同实验条件联合反演前必须登记 pH、浓度、气体和标准态。

Shinagawa 等指出 OER 的 Tafel 斜率依赖覆盖度，简化覆盖度极限和不恰当使用
Butler–Volmer 会导致机理误判 [2]。Antipin 和 Risch进一步证明 AEM 的 Tafel
斜率与反应级数会随覆盖度和 pH 改变 [6]。因此当前共享 `a=0.5` 和无活度速率
只能作为 M0 假设，不能作为硬物理真值。

### 3.5 恒定 `Cdl` 可能把电双层非线性误归因于动力学

当前电路使用常数 `Cdl` 和 `Ru`。电双层结构会随材料、电解质、pH、离子类型、
浓度和电位变化，并影响氧电催化动力学 [7]。FTacV文献已专门研究大振幅扰动下
的非线性背景 [16]。较高阶谐波通常比DC和基频更少受背景影响 [17]，但这不等于
H1-H3全部无背景，也不证明当前电极的 `Cdl` 与电位无关。

项目推断：若没有空白电极或非Faradaic窗口验证常数 `Cdl`，优化器可能让
`k0/G` 吸收背景谐波。首版不应立即增加任意 `Cdl(E)` 多项式，而应先建立：

1. 空白/非Faradaic背景门；
2. 常数Cdl残差诊断；
3. 只有结构残差稳定出现时，才注册低自由度背景模型作为独立版本。

### 3.6 固定 `gamma` 与 Co3O4 工作态重构存在潜在模型冲突

Bergmann 等观察到 Co3O4 在 OER 电位形成可逆的亚纳米无定形
CoOx(OH)y 活性层 [5]；FTacV综述将活性位点密度列为定量解释所需参数 [9]。
“当前实验的位点密度随电位变化”仍是项目推断，文献不能替代本项目的原位证据。

这不证明当前 `beta_recon` 候选模型正确，但说明固定 `gamma` 是需要检验的 M0
假设。正确顺序是：

- 保持当前 M0 失败/通过证据；
- 用分电位、分谐波和跨协议残差判断是否存在位点变化信号；
- 有独立电荷/光谱/负载量证据后，再注册 M1；
- 不用增加三个重构参数来强行改善拟合。

### 3.7 覆盖度归一化可能掩盖候选级物理失败

`elementary_rates()` 在每次 RHS 评价时把五个覆盖度除以其和，然后才计算速率。
虽然化学计量矩阵和合法初值理论上保持覆盖度和为1，这个内部归一化仍会把数值
偏差从速率层隐藏起来，与“候选违反守恒即显式失败”的设计不完全一致。

本轮不直接删除该行为。先运行两条并列诊断：

- 原状态速率与归一化速率的轨迹/谐波差异；
- 全参数压力样本中覆盖度和偏差及求解失败率。

若删除归一化不改变合法轨迹，应在新commit重过A2-R；若改变显著，应先解释
模型或求解器问题，不能把归一化保留为无记录修补。

五个覆盖度还受总和为1的代数约束，实际化学状态只有四个独立覆盖度。现有五
状态写法不是参数结构不辨识，但会引入一个守恒零方向；RHS归一化又改变了该
方向上的导数。开发前向灵敏度或CVODES前必须二选一并独立验证：使用四个独立
覆盖度重建第五个，或保留五状态并把守恒误差作为显式失败。否则灵敏度矩阵可能
混入数值投影，而不是纯物理响应。

### 3.8 初始稳态不等于实验历史

模型在 `E_start`、无AC条件下松弛到稳态，再启动完整扫描。真实实验可能经历
预处理、连续循环、表面重构和不同初始覆盖度。当前A1缺少完整仪器历史，因此
稳态初值只能作为冻结计算假设。

应比较至少两种有来源的初始化：起始电位稳态和前一实验周期/预处理状态。没有
实验记录时只做敏感性，不选择更好拟合者冒充真实历史。

## 4. 对原方案各层的压力测试

| 原方案层 | 网络/代码攻击 | 结论 | 修订 |
|---|---|---|---|
| 参数schema | 参数数可变，但物理等价变换未登记 | 不充分 | 增加解析组合和结构可辨识门 |
| 硬物理约束 | 守恒通过，但活度、标准态、共享转移系数未分层 | 不充分 | 分成恒等式、有效参数和模型假设 |
| 白化Gramian | FIM/局部谱不能发现所有非线性或结构不辨识 | 只能作筛选 | 解析重参数化和profile在前后夹击 |
| 物理分组 | 可能切断精确跨参数组合 | 不能作主证据 | 只作解释；组合由方程和数据决定 |
| profile | 方法成立，但需要似然尺度且计算昂贵 | 有条件通过 | 只对活跃组合和拟报告单参数运行 |
| TuRBO/CMA | 可处理多峰，但没有物理信息 | 不能作主线第一步 | 先提供梯度多起点基线 |
| 多保真 | 粗模型可能旋转敏感方向或漏盆地 | 高风险 | 需主夹角、输出误差和盆地召回门 |
| 合成恢复 | 同一M0生成和拟合存在inverse crime | 必要但不充分 | 增加跨模型失配和留出协议 |
| 实验设计 | 信息矩阵可能受错误模型支配 | 有条件使用 | 先做模型充分性，再优化协议 |
| 桌面端 | 快速反演依赖算法和求解器闭合 | 尚未就绪 | 保留任务管理/结果查看范围 |

## 5. 修订后的可落地路线

### P0：关闭当前 S1

当前 A6-v2 S1继续按冻结 TPE、LSODA、两参数和 P0/P1/P2 验收。其结果只回答
原问题，不用于证明新算法。

### P1：解析物理与参数本体

交付：

1. 版本化 parameter schema，区分原始输入、有效参数、组合参数和派生量；
2. 为条件分支冻结有来源的总电流口径，再将冗余坐标映射为`CdlA/GammaA`；
3. 外部 `A`只负责换算，不与面参数共同自由拟合；
4. 冻结温度、pH、OH活度、氧活度和标准态口径；
5. 将 `k0` 标为当前条件下有效速率，直到活度模型独立通过；
6. 修正文献来源，不改变已有数值结果；
7. 对覆盖度内部归一化和四/五状态表示做不改正式路径的诊断门。

停止条件：解析等价变换未被测试覆盖，或参数定义依赖未登记实验条件。A1未
闭合时允许合成与条件分支继续，但禁止正式真实参数解释。

### P2：模型充分性基线

在不新增自由参数的前提下，输出：

- 分电位、分扫描方向、分协议、分DC/H1–H3残差；
- 空白/非Faradaic背景需求清单；
- 初始状态、共享转移系数、活度和固定gamma的压力场景；
- M0不能解释的稳定残差结构。

只有一个物理假设在多个数据/协议中产生可复现残差时，才建立一个新模型版本；
一次只改变一个假设。

### P3：灵敏度实现升级

当前中心差分保留为校验基线。优先开发前向灵敏度方程或CVODES灵敏度接口，
因为当前状态数只有6而参数数为版本化 `N`。这可同时服务：

- 白化Jacobian与活跃组合；
- 局部条件数和profile；
- trust-region/least-squares梯度；
- 减少中心差分的 `2N` 倍正演成本。

Villaverde 等在大型动力学模型基准中发现，多起点梯度局部法和全局—局部混合
方法通常优于单纯随机全局法，前提是参数灵敏度计算可靠 [14]。该结论不能直接
保证本项目最优，但足以把“梯度多起点”提升为优化器基线。

### P4：结构与实用可辨识性

顺序：

```text
解析组合
→ 多锚点白化敏感性Gramian
→ stiff/sloppy方向诊断
→ 留出噪声门
→ 活跃组合profile
→ 拟展开单参数profile
```

Wieland等指出经典FIM对实用可辨识性存在明显局限，建议用profile likelihood
补充 [12]；Raue等展示profile可检测函数关系和有限数据造成的不辨识 [11]；
Eisenberg和Hayashi给出用subset profiling识别参数组合的方法 [13]。

### P5：计算引擎

优先级：

1. 缓存目标、波形、滤波器和重复参数哈希；
2. 批量候选与多条件并行；
3. 编译RHS的CVODE/CVODES原型，统一提供状态和灵敏度；
4. 对LSODA重过状态、电流、H1–H3相位和盆地召回门；
5. 再考虑多保真方向估计。

不把周期稳态求解器直接列为首选：当前直流电位持续扫描，并非严格周期系统。
任何准周期或慢—快分解都需要独立误差门。

### P6：优化器

首轮在冻结有效坐标 `z` 中比较：

1. Sobol/scatter初始点 + 多起点 trust-region least-squares；
2. TuRBO多信赖域；
3. 固定总预算BIPOP-CMA-ES；
4. TPE历史基线。

优先指标为组合恢复、最坏seed、盆地召回、物理失败和墙钟时间，不按单个最低
loss选择。TuRBO和CMA只有在梯度基线漏盆地时才升级为默认候选。

### P7：抗模型失配恢复

正式A6除同模型合成恢复外，增加：

- 用轻微电位依赖Cdl、活度变化或位点变化生成目标，再用M0拟合；
- 参数范围外推；
- 非白噪声、漂移和背景代理；
- 留出频率/振幅/扫描协议；
- 固定输入误差传播。

这些测试只用于判断结论鲁棒性，不允许看到结果后挑选最有利的失配模型。

### P8：实验与产品

恢复实验后补齐面积、总电容、位点总量、pH/浓度、气体、温度、预处理、空白
和协议。只有物理模型、恢复和性能门通过后，桌面端才提供快速反演；此前只提供
数据分析、正演探索、任务管理和合格结果查看。

## 6. 对综合方案的最终判定

### 保留

- 硬不变量、软先验和模型充分性三层；
- 版本化 `N` 维参数schema；
- 白化敏感性、活跃组合和profile；
- 多盆地、固定预算和LSODA确认；
- 合成恢复、留出协议和失败停止条件。

### 必须前移

- 解析结构可辨识性；
- `A/Cdl/gamma`到`CdlA/GammaA`的精确重参数化；
- 活度、标准态、温度和有效速率口径；
- 模型引用与假设清单；
- 覆盖度归一化诊断。

### 降级

- TuRBO不再预设为默认替代TPE；
- active-subspace谱不单独决定有效维数；
- 同模型合成恢复不承担模型真实性；
- 周期稳态求解不列为未经验证的直接加速项；
- PINN/自编码器不进入当前formal路线。

## 7. 主要来源

1. Man et al., *Universality in Oxygen Evolution Electrocatalysis on Oxide
   Surfaces*, ChemCatChem (2011), DOI:
   [10.1002/cctc.201000397](https://doi.org/10.1002/cctc.201000397).
2. Shinagawa, Garcia-Esparza & Takanabe, *Insight on Tafel slopes from a
   microkinetic analysis of aqueous electrocatalysis for energy conversion*,
   Scientific Reports (2015), DOI:
   [10.1038/srep13801](https://doi.org/10.1038/srep13801).
3. Bonke et al., *Parameterization of Water Electrooxidation Catalyzed by Metal
   Oxides Using Fourier Transformed Alternating Current Voltammetry*, JACS
   (2016), DOI: [10.1021/jacs.6b10304](https://doi.org/10.1021/jacs.6b10304).
4. Zhang et al., *Fourier transformed alternating current voltammetry in
   electromaterials research*, Current Opinion in Electrochemistry (2018), DOI:
   [10.1016/j.coelec.2018.04.016](https://doi.org/10.1016/j.coelec.2018.04.016).
5. Bergmann et al., *Reversible amorphization and the catalytically active state
   of crystalline Co3O4 during oxygen evolution*, Nature Communications (2015),
   DOI: [10.1038/ncomms9625](https://doi.org/10.1038/ncomms9625).
6. Antipin & Risch, *Calculation of the Tafel slope and reaction order of the
   oxygen evolution reaction between pH 12 and pH 14 for the adsorbate
   mechanism*, Electrochemical Science Advances (2022), DOI:
   [10.1002/elsa.202100213](https://doi.org/10.1002/elsa.202100213).
7. Li et al., *Electric Double Layer Effects in Electrocatalysis: Insights
   from Ab Initio Simulation and Hierarchical Continuum Modeling*, JACS Au
   (2023), DOI:
   [10.1021/jacsau.3c00410](https://doi.org/10.1021/jacsau.3c00410).
8. Gavaghan et al., *Use of Bayesian Inference for Parameter Recovery in DC and
   AC Voltammetry*, ChemElectroChem (2017), DOI:
   [10.1002/celc.201700678](https://doi.org/10.1002/celc.201700678).
9. Snitkoff-Sol, Bond & Elbaz, *Fourier-Transformed Alternating Current
   Voltammetry (FTacV) for Analysis of Electrocatalysts*, ACS Catalysis (2024),
   DOI: [10.1021/acscatal.4c01526](https://doi.org/10.1021/acscatal.4c01526).
10. Constantine, *Active Subspaces*, SIAM (2015), DOI:
    [10.1137/1.9781611973860](https://doi.org/10.1137/1.9781611973860).
11. Raue et al., *Structural and practical identifiability analysis of partially
    observed dynamical models by exploiting the profile likelihood*,
    Bioinformatics (2009), DOI:
    [10.1093/bioinformatics/btp358](https://doi.org/10.1093/bioinformatics/btp358).
12. Wieland et al., *On structural and practical identifiability*, Current
    Opinion in Systems Biology (2021), DOI:
    [10.1016/j.coisb.2021.03.005](https://doi.org/10.1016/j.coisb.2021.03.005).
13. Eisenberg & Hayashi, *Determining identifiable parameter combinations using
    subset profiling*, Mathematical Biosciences (2014), DOI:
    [10.1016/j.mbs.2014.08.008](https://doi.org/10.1016/j.mbs.2014.08.008).
14. Villaverde et al., *Benchmarking optimization methods for parameter
    estimation in large kinetic models*, Bioinformatics (2018), DOI:
    [10.1093/bioinformatics/bty736](https://doi.org/10.1093/bioinformatics/bty736).
15. Lam et al., *Multifidelity Dimension Reduction via Active Subspaces*, SIAM
    Journal on Scientific Computing (2020), DOI:
    [10.1137/18M1214123](https://doi.org/10.1137/18M1214123).
16. Bond et al., *Characterization of Nonlinear Background Components in
    Voltammetry by Use of Large Amplitude Periodic Perturbations and Fourier
    Transform Analysis*, Analytical Chemistry (2009), DOI:
    [10.1021/ac901318r](https://doi.org/10.1021/ac901318r).
17. Baranska et al., *Practical Guide to Large Amplitude Fourier-Transformed
    Alternating Current Voltammetry—What, How, and Why*, ACS Measurement
    Science Au (2024), DOI:
    [10.1021/acsmeasuresciau.4c00008](https://doi.org/10.1021/acsmeasuresciau.4c00008).
