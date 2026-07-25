# 项目上下文总结（2026-07-20）

## 项目定位

碱性 OER AEM 微观动力学建模与 FTacV 参数反演平台。目标不是拟合曲线，而是用 FTacV 数据判断哪些参数/反应步骤最影响体系响应。

## 当前主线

> FTacV 多组数据支持 AEM 热力学描述符的稳定识别，但动力学参数与有效位点数存在强补偿。下一阶段以独立约束 gamma 和分阶段反演为核心。

## 关键结论（已通过反复验证）

1. **热力学参数稳定**：`scaling_OOH_OH`(CV=0.03)、`G_O`(CV=0.10)、`G_OH`(CV=0.16, gamma 固定后改善自 0.26)
2. **动力学参数不可靠**：`k0_1~k0_4`(CV=1.5-1.7)、`gamma`(CV=1.3)，存在强参数补偿
3. **所有拟合等级均为 poor**：模型缺项主导，不能靠继续调参解决
4. **高次谐波 h4-h7**：AEM+α=0.5 框架物理极限，仅诊断

## 残差诊断结果

4 组 FTacV 数据一致显示：**低电位基线 OK（bias≈0），高电流段严重偏高（bias=+0.54~0.71），onset 对齐 OK**。

→ 优先调 Ru（当前 10Ω 偏低），不先补背景模型。

## 代码架构

```
OER-FTAcV/
├── python/oer_aem/     # 核心：physics/signal/inversion/importance/thermodynamics
├── web/backend/         # FastAPI：/api/simulate, /api/data/analyze, /api/inversion/tpe
├── web/frontend/        # React 单页：实验·正演·反演
├── scripts/             # analyze_data_quality.py, staged_inversion.py, residual_diagnostics.py
├── results/             # data_quality/, staged_inversion/, model_gap/
├── data/raw/            # 4×FTacV + 3×CV 原始数据
└── docs/                # 文献笔记、诊断文档、操作计划
```

## 实验数据

- 4 组 FTacV：ftacv2(5Hz, 质量最好), ftacv3(5Hz), ftacv4(1Hz), ftacv8(5Hz)
- 3 组 CV：cv-ftacv2/3/8
- 电极面积：1.0 cm²，常规电化学体系（非微纳）
- 当前 Ru=10Ω、Cdl≈28µF/cm²、gamma 固定 3e-9、A=1.0

## 当前关键参数

| 参数 | 值 | 来源 |
|------|-----|------|
| gamma | 3e-9 (固定) | Moysiadou 2020 文献估算 |
| E0_pre | 1.50 V | Moysiadou 2020 |
| Cdl | 28 µF/cm² | 数据质量分析均值 |
| G_OH | 1.10 eV | defaults |
| G_O | 2.70 eV | defaults |
| scaling | 3.2 eV | Man 2011 |

## 已知限制

- Tafel 提取在 n_points=256 低分辨率下不可靠（4 个 inversion 测试失败）
- k0_i 不可单独解释
- 无 OH⁻/O₂ 传质模块
- 无基底背景扣除

## 下一步

调 Ru → 重跑 staged inversion → 检查 bias_hi 是否改善
