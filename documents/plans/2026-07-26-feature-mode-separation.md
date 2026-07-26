# Gate A5 Feature Mode Separation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> `superpowers:subagent-driven-development` (recommended) or
> `superpowers:executing-plans` to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将目标函数拆成语义严格的 `legacy`、`complex_snr`、
`lockin_only` 和 `hybrid`，并使每个损失分量可独立审计。

**Architecture:** DC 和 physical 约束保留为所有模式的共同块。legacy 只用
历史谐波包络；complex_snr 只用全局复数谐波；lockin_only 只用电位分辨
锁相复数包络；hybrid 同时使用全局复数与锁相块。历史 `combined` 仅作为
hybrid 兼容别名，不出现在新正式结果中。

**Tech Stack:** Python、NumPy、现有 `InversionObjective`、pytest、
Optuna smoke。

---

## 固定语义

| 模式 | DC | legacy envelope | global complex | lock-in complex | physical |
|---|---:|---:|---:|---:|---:|
| legacy | 是 | 是 | 否 | 否 | 是 |
| complex_snr | 是 | 否 | 是 | 否 | 是 |
| lockin_only | 是 | 否 | 否 | 是 | 是 |
| hybrid | 是 | 否 | 是 | 是 | 是 |

`total_loss` 只在同一模式内用于优化，不用于跨模式科学比较。跨模式 smoke
统一报告共同 DC RMSE、共同 H1–H3 RMSE、失败次数、边界命中和运行时间。

## Task 1：模式语义 TDD

**Files:**
- Modify: `code/python/tests/test_inversion.py`
- Modify: `code/python/src/oer_aem/inversion.py`

- [ ] 写失败测试，要求 `make_synthetic_target(lockin_only)` 含 `lockin`
  但不含 `complex_harmonics`。
- [ ] 写失败测试，要求 `make_synthetic_target(hybrid)` 同时包含两者。
- [ ] 写失败测试，要求 lockin_only 的全局损失分量严格为 0，修改锁相
  amplitude 后只有锁相 amplitude 分量增加。
- [ ] 运行目标测试并确认因现有语义而失败。
- [ ] 最小修改 `extract_features()` 和 `InversionObjective` 的模式分支。
- [ ] 接受 `combined` 但按 hybrid 执行；未知模式继续抛出明确错误。
- [ ] 运行目标测试并确认通过。

## Task 2：损失分量拆分

**Files:**
- Modify: `code/python/src/oer_aem/inversion.py`
- Modify: `code/python/tests/test_inversion.py`

- [ ] 将锁相 amplitude 和 phase 分别拆为 common（H1–H3）与
  dataset-specific（H4–H7）。
- [ ] ODE 失败行返回与成功路径完全相同的 component schema。
- [ ] 测试 H4 target 扰动只增加 dataset-specific 锁相分量。
- [ ] 不改变现有 sigma、phase_weight、SNR 或总损失归一化公式。

固定 component schema：

```text
dc
common_harmonics
dataset_specific_harmonics
phase
lockin_common_amplitude
lockin_dataset_specific_amplitude
lockin_common_phase
lockin_dataset_specific_phase
physical
```

其中 `common_harmonics`、`dataset_specific_harmonics`、`phase` 只表示
legacy/global 块；未启用的块必须为 0。

## Task 3：比较入口和 smoke 证据

**Files:**
- Modify: `code/python/scripts/compare_feature_objectives.py`
- Modify: `code/python/tests/test_inversion.py`
- Create: `results/smoke/architecture_validation/feature_mode_separation/`

- [ ] 新模式顺序固定为 legacy、complex_snr、lockin_only、hybrid。
- [ ] `_experimental_target()` 按固定语义只构建所需观测块。
- [ ] CSV 新增四个锁相损失分量列，旧全局列语义保持。
- [ ] 运行 synthetic 单 seed、每模式 1 trial smoke；只验证流程、字段和
  共同指标有限，不评价模式优劣。
- [ ] smoke 使用 LSODA，不重新启用 CN。

## Task 4：验证、文档与版本

**Files:**
- Modify: `documents/project/PROJECT_SUMMARY.md`
- Modify: `documents/project/WORK_STATUS.md`
- Modify: `documents/corrections/项目纠错.md`
- Modify: `results/README.md`

- [ ] 运行 Python 全量、Web 后端、Markdown 审计和 `git diff --check`。
- [ ] 明确记录 A5 仅完成接口拆分，正式精度比较仍未开始。
- [ ] 只提交代码、测试、小预算 smoke 和对应文档并推送。

## 压力测试结论

1. 不能删除 `combined` 而破坏历史配置；保留兼容别名但不生成新结果。
2. 不能用不同模式的 `total_loss` 排名，因为活动观测块数量不同。
3. 本阶段不同时改权重、损失归一化和模式语义，否则无法归因回归。
4. lockin_only 不得为“保护旧指标”隐式包含 global complex。
5. 未启用分量必须显式为 0，而不是缺失或 NaN。
6. smoke 只证明四模式可运行和证据完整，不证明反演精度提高。
