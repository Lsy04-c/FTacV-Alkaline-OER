# 补实验后参数接入与加速恢复实施计划

> **For agentic workers:** 按任务顺序执行；每个任务完成后运行列出的测试，再进入下一任务。

**Goal:** 建立可追溯的补实验输入包、统一参数角色约束和 C++ screen-only 批量加速框架。

**Architecture:** Python 负责数据契约、参数角色、target bundle、profile 和正式 LSODA/BDF；C++ 只负责候选筛选并通过稳定的 C ABI 返回逐案例状态。所有输出绑定输入哈希、角色哈希、后端和 commit。

**Tech Stack:** Python 3.13、NumPy/SciPy、pytest、C++17、ctypes、JSON/NPZ。

### Task 0: Unified parameter assignment API

- [x] Add `ParameterSelection`/`build_parameter_selection()` so each task explicitly
  assigns every search parameter to `free`, `fixed`, or `diagnostic`.
- [x] Reject omitted, duplicate, non-finite, out-of-bound, and fixed/free-conflicting
  assignments; permit external runtime inputs as explicit fixed values.
- [x] Require an explicit role override before reopening a currently fixed role.
- [ ] Migrate each formal runner to this API; historical runners remain unchanged until
  their job schemas are versioned.

补充进度：`run_synthetic_recovery.py` 已提供 `--parameter-selection` schema v1
显式入口。该入口仅允许 formal legacy recovery，旧版不带参数时仍保持 legacy
job/hash 语义；explicit job、resume fingerprint、provenance 和 summary 均绑定
selection evidence hash。portfolio/pre-experiment 路径尚未迁移。

---

### Task 1: Freeze parameter-role enforcement

**Files:**
- Modify: `code/python/src/oer_aem/recovery.py`
- Modify: `code/python/scripts/run_synthetic_recovery.py`
- Test: `code/python/tests/test_synthetic_recovery_protocol.py`
- Test: `code/python/tests/test_synthetic_recovery_runner.py`

- [x] Add a role-aware helper that keeps `gamma` identical across synthetic truths and rejects a fixed parameter appearing in free specs.
- [x] Add tests for identical gamma and duplicate fixed/free rejection.
- [x] Run the focused tests before changing runner defaults.
- [ ] Migrate the legacy synthetic runner to reject fixed roles by default; its historical 8-D matrix remains reproducibility-only until separately versioned.
- [ ] Record `fixed_params`, `free_parameters`, and role policy in job input hashes.

### Task 2: Add profile-derived step-size contract

**Files:**
- Create: `code/python/src/oer_aem/search_policy.py`
- Create: `code/python/tests/test_search_policy.py`
- Modify: `code/python/scripts/screen_cmaes_raw.py`

- [x] Define a pure function converting profile half-width in encoded coordinates to a bounded CMA step size.
- [x] Reject missing, non-finite, or zero-width profiles.
- [x] Add CLI output containing encoded half-width and selected sigma, bound to a hashed profile-summary source.
- [x] Keep current raw-CMA driver diagnostic-only until a profile half-width is supplied.
- [x] Test that the prior `sigma=0.25` is rejected unless explicitly overridden for a diagnostic run.

### Task 3: Build post-experiment target bundle

**Files:**
- Create: `code/python/src/oer_aem/post_experiment.py`
- Create: `code/python/scripts/build_post_experiment_bundle.py`
- Create: `code/python/tests/test_post_experiment_bundle.py`

- [x] Read only `collected` rows from a validated intake manifest.
- [x] Parse each three-column FTacV file with the strict data contract.
- [x] Build condition-specific targets using `analyze_ftacv_trace` and `build_experimental_target`.
- [x] Store arrays in NPZ and metadata/roles/hashes in JSON; never overwrite raw files.
- [x] Require explicit independent-input records for `Ru`, `CdlA`, area, load and any GammaA claim; missing values produce `WAITING_FOR_INDEPENDENT_INPUT`.
- [x] Add deterministic reconstruction tests and a hash-conflict test.

### Task 4: Rewrite C++ screen-only solver interface

**Files:**
- Create: `code/cpp/src/oer_screen_solver.cpp`
- Modify: `code/python/src/oer_aem/cpp_bridge.py`
- Create: `code/python/tests/test_cpp_screen_bridge.py`
- Modify: `code/cpp/README.md`

- [x] Replace the existing CN Newton finite-difference Jacobian with an analytical Jacobian and finite-output status checks; keep it explicitly screen-only.
- [x] Expose `oer_cn_solve_batch` with explicit per-case status codes and finite-output checks; a separate elapsed-steps ABI remains pending.
- [ ] Keep parameter order in one documented C ABI table and test pack/unpack round trips.
- [ ] Build macOS `.dylib` locally and Linux `.so` on Legion separately; never copy binaries across platforms.
- [x] Add a bridge smoke test for batch shape, status preservation, and single-case equivalence; backend remains `screen_only` and formal mode is still rejected by policy.

### Task 5: Benchmark and scientific separation

**Files:**
- Create: `code/python/scripts/benchmark_screen_solver.py`
- Create: `code/python/tests/test_screen_solver_policy.py`
- Modify: `documents/project/WORK_STATUS.md`

- [x] Compare C++ screen-only and LSODA using the existing solver-equivalence tool; fix its feature-mode wiring and retain DC/H1–H7 plus phase diagnostics.
- [x] Report failure rate and per-case status; the batch microbenchmark is recorded as ~1.12× call-overhead speedup, not a scientific accuracy claim.
- [x] A3/smoke equivalence remains FAIL; evidence is diagnostic-only and LSODA/BDF stays formal.
- [ ] Run Python, bridge, workflow and layout tests; only then update project status.

补充进度（2026-08-09）：复用 `validate_solver_equivalence.py` 做 2-sample
screen smoke 时发现其配置为 `lockin_only` 却读取 `complex_harmonics` 的实现错误，
已修正为 `hybrid` 并增加回归测试。修复后 smoke 正常产出 14 行结果，但仍有 10
项 CN/LSODA 差异超门，科学结论为 FAIL，未改变阈值或 formal 后端；另增加 CLI
失败退出码和失败 summary 持久化的回归测试。

### CN 后续复核结论（2026-08-09）

- Newton 未收敛不得接受；解析 Jacobian、严格残差下降 line search 和失败区间内部二分
  已实现并通过本机回归。
- 完整 24-sample 对照仍未通过：20/24 CN 案例成功，4 案例返回 `-4`（时间步/细分未收敛；
  `-2` 保留给稳态初始化失败）；成功案例还存在
  lock-in 相位及 DC 超门。该证据不支持把 CN 提升为 formal backend。
- CSV 已记录 `lsoda_status`/`cn_status`，失败位置可区分；这属于可观测性修复，不是
  阈值放宽或科学结论改变。
- 当前路线冻结为：LSODA/BDF formal，CN screen-only。后续优先把计算预算用于参数可
  辨识性、两阶段恢复和补实验输入，而不是继续无证据增加 CN 复杂度。

### Profile-driven CMA 步长契约（2026-08-09）

- 正式 raw-CMA 现在必须读取带 SHA-256 的 `profile_summary.json`，按当前 feature mode
  过滤，并要求所有 free 参数均有有效、正值、归一化范围内的 `delta_1_width`。
- 公共 sigma 取所有 free 参数半宽的最小值再经过既有 safety/floor/cap；裸数字半宽仅
  保留给 diagnostic，不作为 formal 证据。
- 缺少参数、重复模式、未知区间语义或跨 mode 混用都会拒绝；profile 源路径、哈希、
  参数宽度和选择规则写入结果 provenance。另强制匹配 truth、LSODA、非 smoke、
  8192 点/32 points-per-cycle、128 feature grid、H1-H3、41 profile grid 和零噪声配置。
- 另外要求每个 profile 的 truth 是全局最小、无远端近似谷、所有点有限且无 ODE/Tafel
  失败；这防止把局部补偿谷当成 sigma 依据。
