# 上下文压缩（2026-07-26）

## 项目定位

碱性 OER AEM FTacV 参数反演平台。目标不是拟合曲线，是判断哪些参数/步骤最影响体系响应。

## 当前主线

FTacV 多组数据支持 AEM 热力学描述符稳定识别。动力学参数与有效位点强补偿。下一阶段以独立约束 gamma + 分阶段反演为核心。

## 已确认结论

| 结论 | 证据 |
|------|------|
| G_OH, G_O, scaling 跨数据稳定 | CV=0.02~0.07（gamma约束后） |
| k0_1~k0_4, gamma 不可单独解释 | CV=1.0~1.7 |
| h4-h7 仅诊断 | AEM+α=0.5 物理极限 |
| 高电流段偏差（bias_hi≈+0.4）是主矛盾 | 4/4 数据集一致 |
| 低电位基线 OK, onset OK, Ru扫描无效 | bias_lo≈0, onset_offset≈0, Ru=10-50Ω无改善 |
| gamma_eff(E) 已实现但效果微弱 | β=3仅增2%电流，PDS k0_3 瓶颈 |

## 代码架构

```
OER-FTAcV/
├── python/oer_aem/       # physics/signal/inversion/importance/thermodynamics/data_contract
├── web/backend/ + frontend/  # FastAPI + React 单页
├── scripts/              # analyze_data_quality / staged_inversion / residual_diagnostics / sweep_ru / run_architecture_validation
├── results/              # data_quality / staged_inversion / model_gap / architecture_validation
├── data/raw/             # 4×FTacV + 3×CV
└── docs/                 # 文献、诊断、操作计划
```

## 实验参数

A=1.0 cm², gamma=3e-9（固定）, E0_pre=1.50V, Cdl≈28µF/cm², Ru=10Ω, G_OH=1.10, G_O=2.70, scaling=3.2

## Legion 环境

- 提交: 3e08bdd, 70 tests passing (Mac)
- WSL Debian-Bookworm, user lsy
- 工作树: /home/lsy/OER-FTAcV-run-3e08bdd
- Python: /home/lsy/OER-FTAcV-run-8cf26be/.venv/bin/python (np 2.2.6, scipy 1.16.3, optuna 4.9.0)

## 待办

Formal 计算（Legion）: residual_diagnostics(30), architecture_validation(50), feature comparison(50+8w), M0/M1 comparison(50+8w)
