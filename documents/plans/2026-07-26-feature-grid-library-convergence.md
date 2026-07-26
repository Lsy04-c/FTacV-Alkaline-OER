# Gate A5 Fixed-Library Grid Convergence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> `superpowers:subagent-driven-development` (recommended) or
> `superpowers:executing-plans` to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** 用固定参数库验证四种目标模式在 64/128/256/full 特征网格上的
损失和参数排序收敛，并决定能否冻结 128 点网格。

**Architecture:** 一个无噪声 synthetic truth 作为固定 target；8 个确定性
分层参数向量作为候选库。每个 mode/grid/candidate 独立评价，full grid 是
参考。主进程统一汇总 128 行证据；Legion 使用 8 workers，每 worker 一个
BLAS 线程。该门不运行 TPE，因此只测数值网格，不混入优化随机性。

**Tech Stack:** Python、NumPy、SciPy、LSODA、现有 `InversionObjective`、
CSV/JSON、pytest。

---

## 固定配置

| 项目 | 值 |
|---|---|
| 模式 | legacy、complex_snr、lockin_only、hybrid |
| 网格 | 64、128、256、full |
| 参数库 | 8 个确定性分层向量，seed 23，边界内 10%–90% |
| truth | `compare_feature_objectives.py::TRUTH` |
| 扫描 | 5 Hz、256 cycles、32 points/cycle |
| 后端 | LSODA |
| target | 无噪声、与所有网格共享同一 truth |
| 正式行数 | 4 × 4 × 8 = 128 |

## 共同评价指标

每行记录：

- mode、grid、candidate；
- total loss 和全部独立 loss components；
- common DC RMSE；
- common H1–H3 RMSE；
- ODE 成功、运行时间和参数向量哈希。

对每个 mode/candidate，以 full 为参考计算：

- `total_loss_relative_error`；
- `common_dc_rmse_relative_error`；
- `common_h1_h3_rmse_relative_error`。

对每个 mode/grid，计算 8 个 candidate 的 total-loss Spearman 排名相关。

## Gate

128 点 PASS 要求：

1. 32 个 128-grid 行全部有限且 ODE 成功；
2. total loss 相对 full：median ≤1%，max ≤5%；
3. common DC RMSE 相对误差：median ≤1%，max ≤5%；
4. common H1–H3 RMSE 相对误差：median ≤1%，max ≤5%；
5. 每个模式的 loss 排名 Spearman ≥0.99。

256 点使用同一门做确认；64 点只保留诊断，不决定 128 点是否通过。任一模式
失败则 128 点不能冻结，不按模式删除失败样本。

## Task 1：采样与门控 TDD

**Files:**
- Create: `code/python/scripts/validate_feature_grid_convergence.py`
- Create: `code/python/tests/test_feature_grid_convergence.py`

- [x] 测试参数库确定性、形状为 8×参数数、严格位于 10%–90% 边界。
- [x] 测试零参考值时相对误差使用绝对容差，不能产生 inf/NaN。
- [x] 测试 128 点 max error 5.1% 或 Spearman 0.98 时 Gate FAIL。
- [x] 实现最小 helper 并完成 RED→GREEN。

## Task 2：正式证据入口

**Files:**
- Modify: `code/python/scripts/validate_feature_grid_convergence.py`
- Modify: `code/python/tests/test_feature_grid_convergence.py`

- [x] 每个 worker 构造相同 truth/候选，使用 LSODA 评价一个任务。
- [x] 未启用损失分量显式为 0，字段与 A5 component schema 一致。
- [x] 主进程排序并写 128 行 CSV、summary、input/config hash 和 provenance。
- [x] 串行与 8-worker 单模式 smoke 必须逐字段一致（runtime 除外）。

## Task 3：运行、验收和项目状态

**Files:**
- Create: `results/formal/feature_grid_convergence/gate-a5-grid-<commit>/`
- Modify: `documents/project/PROJECT_SUMMARY.md`
- Modify: `documents/project/WORK_STATUS.md`
- Modify: `documents/corrections/项目纠错.md`
- Modify: `results/README.md`

- [x] 在 Legion 固定 commit 上用 8 workers 正式运行。
- [x] 验收 128 行、32 个 mode/grid 组、有限值、后端、配置和 provenance。
- [x] PASS 时冻结 128；FAIL 时保留真实失败并停止四模式正式 TPE。
- [x] 运行全量测试、审计、提交并推送。

## 压力测试结论

1. 不使用 TPE 做第一层网格门，避免优化随机性掩盖数值误差。
2. 不跨模式比较 total loss，只在同一 mode/candidate 跨网格比较。
3. 参数库不包含 truth，避免参考 loss 为 0 使相对误差失真。
4. loss 接近 0 时必须回退绝对误差尺度并原样记录。
5. 8 workers 预计 wall time 1–3 分钟；线程数不是科学参数。
6. 旧单 target `grid_convergence.csv` 保留为历史证据，不覆盖。
