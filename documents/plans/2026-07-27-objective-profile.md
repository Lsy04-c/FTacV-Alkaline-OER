# Gate A6 Objective Profile Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 生成五个候选参数在四种特征模式下的确定性单参数目标剖面，区分目标不可识别、失败区和 TPE 搜索不足。

**Architecture:** 核心模块负责生成含 truth 的归一化网格并汇总剖面指标；独立 runner 负责构造 frozen A5 配置、并行执行、写 CSV/JSON 与 provenance。正式计算先在 Mac smoke，再从干净 commit 到 Legion。

**Tech Stack:** Python、NumPy、SciPy LSODA、pytest、CSV/JSON、Legion systemd-run

---

### Task 1：核心 profile 网格与摘要

**Files:**
- Create: `code/python/src/oer_aem/profiling.py`
- Create: `code/python/tests/test_profiling.py`

- [x] 写失败测试：41 点边界网格必须包含 0、1 和非网格 truth，且无重复。
- [x] 运行 `test_profiling.py`，确认因模块缺失失败。
- [x] 实现 `profile_grid(truth_coordinate, grid_points=41)`。
- [x] 写失败测试：已知抛物线的 truth 全局最小、局部曲率、`min+1/min+10`
  宽度和有限点比例计算正确。
- [x] 实现 `summarize_profile(rows, truth_coordinate)`，明确近最优宽度不是置信区间。
- [x] 运行目标测试并通过。

### Task 2：正式 runner

**Files:**
- Create: `code/python/scripts/run_objective_profiles.py`
- Create: `code/python/tests/test_objective_profile_runner.py`

- [x] 写失败测试：默认正式配置为 LSODA、8192/32/128、四模式、五参数、
  `mixed_b`、41 网格点和无噪声。
- [x] 实现 CLI、配置构造和任务矩阵；smoke 使用小模拟网格和少量任务。
- [x] 写失败测试：每个候选向量只自由改变目标参数，其余参数由
  `fixed_params` 取 truth，truth 点必须执行。
- [x] 用 `InversionObjective` 执行剖面，记录总损失、九类损失分量、有限性、
  ODE/Tafel 计数和运行时间。
- [x] 写 `profile_rows.csv`、`profile_summary.json`、`run_manifest.json`；
  manifest 记录 commit、dirty、命令、环境、配置和 SHA256。
- [x] 正式模式拒绝 dirty worktree、输出覆盖、缺行、非有限 truth loss 或
  provenance 不完整。

### Task 3：验证、提交与 Legion 正式计算

**Files:**
- Modify: `documents/project/PROJECT_SUMMARY.md`
- Modify: `documents/project/WORK_STATUS.md`
- Modify: `documents/corrections/项目纠错.md`（仅出现新问题时）
- Create: `results/formal/identifiability/gate-a6-profile-<commit>/`

- [x] Mac 运行 runner smoke，验收 truth 点、schema 和 manifest。
- [ ] 运行 Python 全量测试。
- [ ] 提交并推送 profile 代码、测试和计划。
- [ ] 在 Legion 创建精确 commit worktree，用 8 workers、每 worker 1 BLAS
  thread 运行正式 profile。
- [ ] 验收 4×5 个 profile、每个含 41 点与 truth、有限 truth loss、失败计数、
  SHA256、配置和 provenance。
- [ ] 根据预注册门控决定哪些参数进入两参数 profile；不直接启动 TPE。
- [ ] 同步正式证据，更新项目状态，测试、提交并推送。

## 计划压力测试

- 无噪声 profile 先隔离结构与数值问题；量化噪声留到通过参数的后续压力测试。
- 单参数清晰不能证明联合可识别，只允许进入两参数 profile。
- 41 点网格可能漏掉窄极小值，因此强制加入 truth，并把结论限制为离散地形
  诊断；必要时只对 truth 邻域自适应加密。
- ODE penalty 不能当作有限科学损失；摘要必须单独记录失败点。
- Tafel 缺失会改变目标地形，必须记录而不是静默忽略。
