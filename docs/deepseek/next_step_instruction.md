# DeepSeek 下一步工作指令

项目路径：`/Users/liushiyu/OER-FTAcV`
负责人：刘拾玉
研究对象：Co3O4 / CoOx(OH)y 碱性 OER 的 FTacV 机理解释与参数反演
当前核心问题：多组实验数据已经存在，下一步应先判断数据质量、谐波可用性和参数耦合，再优化反演算法。

## 1. 项目目标

本项目不是单纯拟合曲线。目标是用 FTacV 数据解释碱性 OER 中哪些参数或反应步骤最影响体系响应。

算法输出不应只有 `best_params`，还应输出：

- 哪些谐波可用于拟合；
- 哪些谐波只能诊断；
- 哪些参数可识别；
- 哪些参数强耦合；
- 哪些结论只能作为趋势，不能作为机理证明。

## 2. 当前项目结构

```text
OER-FTAcV/
├── data/
│   ├── raw/                 # 原始实验数据
│   └── processed/           # 后续处理数据
├── docs/
│   ├── deepseek/            # 给 DeepSeek/其他 agent 的任务文档
│   ├── papers/              # 文献 PDF
│   ├── her_oer_comparison_critique.md
│   └── parameter_importance_design.md
├── python/
│   ├── oer_aem/             # Python 机理模型、信号处理、反演算法
│   └── tests/               # Python 测试
├── results/
│   ├── benchmarks/          # 基准测试和缓存
│   └── figures/             # 诊断图
├── web/                     # FastAPI + 前端页面
├── WORK_STATUS.md           # 当前工作进展
└── PROJECT_SUMMARY.md       # 项目背景总结
```

## 3. 已有实验数据

原始数据目录：`data/raw/`

```text
ftacv2-ref-5hz.txt
ftacv3-ref-5Hz.txt
ftacv4-ref-1hz.txt
ftacv8-ref-5Hz.txt
cv-ftacv2.txt
cv2-ftacv8.txt
cv4-ftacv3.txt
```

其中 `ftacv4-ref-1hz.txt` 是旧基准数据。新增 5 Hz 数据应优先用于比较重复性和谐波质量。

## 4. 当前代码能力

已实现：

- 实验数据上传与自动识别；
- DC 和 H1-H7 谐波提取；
- OER AEM 正演；
- TPE 参数反演；
- 参数归一化和经验边界；
- 可分辨谐波自动筛选；
- 参数重要性初版模块。

关键文件：

```text
python/oer_aem/signal.py
python/oer_aem/physics.py
python/oer_aem/inversion.py
python/oer_aem/importance.py
web/backend/main.py
web/frontend/index.html
```

## 5. 下一步优先级

### P0：多组实验数据质量评估

先写脚本批量读取 `data/raw/*.txt`，输出每组数据的基本信息：

- 点数；
- 时间范围；
- 电位范围；
- 采样率；
- 估计频率 `f`；
- AC 振幅 `dE`；
- 扫描速率；
- DC 基线范围；
- H1-H7 相对 RMS；
- 推荐拟合谐波；
- 推荐诊断谐波。

建议输出：

```text
results/data_quality/data_quality_summary.csv
results/data_quality/data_quality_summary.md
results/data_quality/<sample>_harmonics.png
```

判断重点：

- 5 Hz 数据的 H2/H3 是否比 1 Hz 更稳定；
- H4 以后是否仍主要是噪声；
- 不同样品是否有一致的低电位基线偏移；
- CV 数据是否能给预氧化峰或 OER onset 的先验。

### P1：先处理参数耦合，不急着反演

基于 `python/oer_aem/importance.py` 的 `feature_sensitivity_matrix`，新增参数耦合诊断。

建议输出：

```text
parameter_coupling_matrix
strong_coupling_pairs
coupling_groups
recommended_free_params
recommended_fixed_params
recommended_bounds
```

计算方式：

- 对每个参数取其特征敏感性向量；
- 对向量做标准化；
- 用 cosine similarity 判断两个参数是否影响相似特征；
- 对强耦合参数组给出固定/合并/分阶段反演建议。

重点关注：

```text
gamma / A / Cdl
Ru / Cdl
k0_1~k0_4
G_OH / G_O / scaling_OOH_OH
E0_pre / k0_pre
```

### P2：设计分阶段反演

不要一次性放开所有参数。

建议分三阶段：

1. 用 CV/低电位区约束 `E0_pre`、`k0_pre`、`Cdl`、基线背景。
2. 用 DC、H1、H2 约束 `gamma`、`Ru`、整体电流尺度。
3. 只在 H2/H3 质量足够时，反演 `G_OH`、`G_O`、`k0_i`。

如果某组数据 H3 质量差，不应强行反演完整 AEM 参数。

### P3：目标函数改造

当前目标函数仍偏工程化。下一版应把每个通道的可信度写入 loss。

建议形式：

```text
loss = w_dc * L_dc
     + sum(w_hn * L_hn)
     + w_tafel * L_tafel
     + penalty_physical
```

其中 `w_hn` 来自：

- 谐波 SNR；
- 重复实验稳定性；
- 空白基底背景占比；
- 参数敏感性；
- 是否处于可分辨频段。

禁止为了降低 loss 随意放宽物理边界。

## 6. 重要约束

- 不要把高阶谐波拟合差直接归因于机理错误。
- 不要把参数拟合结果直接解释为真实机理。
- 不要为了曲线好看加入无物理意义的参数。
- 不要直接套用 HER 的全谐波等权拟合。
- 不要把文献中性体系参数直接套到碱性 KOH。
- 不要把 `gamma` 解释成全部 Co 位点；它更接近有效参与 FTacV 响应的位点。

## 7. 建议先运行的验证命令

```bash
cd /Users/liushiyu/OER-FTAcV
.venv/bin/python -m compileall -q python/oer_aem web/backend
.venv/bin/python -m pytest python/tests web/backend/test_inversion_api.py -q
```

如果改动了数据路径，也运行：

```bash
.venv/bin/python web/backend/test_analyze_e2e.py
```

## 8. 本轮应交付的结果

DeepSeek 下一步应优先交付：

1. 一个批量数据质量分析脚本；
2. 一份 `results/data_quality/data_quality_summary.md`；
3. 参数耦合诊断的设计或初版实现；
4. 明确说明哪些数据能用于拟合，哪些只能用于诊断。

最重要的判断标准：代码应帮助刘拾玉判断“哪些信息可靠”，而不是只给一条看起来贴合的曲线。
