# OER-FTAcV 工作进展总结（2026-07-18）

项目：碱性 OER AEM 微观动力学建模与 FTacV 参数反演平台
负责人：刘拾玉
目标体系：Co3O4 / CoOx(OH)y 碱性 OER
当前目标：用 FTacV 解释反应机理，判断不同参数或反应步骤对体系的真实影响。

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

真实数据 `ftacv4-ref.txt` 当前判定：

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
