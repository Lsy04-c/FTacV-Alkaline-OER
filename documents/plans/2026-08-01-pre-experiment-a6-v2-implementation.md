# 实验前 A6-v2 多协议合成恢复实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不改变冻结 M0、TPE 预算和恢复阈值的前提下，实现 P0/P1/P2 配对多协议合成恢复，并由独立 validator 判定推荐采集协议是否增加低维参数恢复能力。

**Architecture:** 新增聚焦的 `portfolio_recovery.py` 承担协议目录、确定性 target key、条件目标聚合和阶段矩阵；扩展现有 `TPEInverter` 与 `run_synthetic_recovery.py`，复用已有并行、checkpoint、resume 和 provenance。科学门由独立 archive validator 重建，`oer-wf` 只桥接执行和验收。

**Tech Stack:** Python 3.11、NumPy、Optuna TPE、pytest、现有 OER M0 正演器、oer-wf 0.7.0、Legion WSL LSODA。

---

## 执行状态（2026-08-01）

| 任务 | 状态 | 已验证证据 |
|---|---|---|
| 1–3 冻结规格、组合目标、Optuna 共用循环 | 已完成 | 聚焦测试通过，提交 `7342058` |
| 4 runner、checkpoint、resume 和输出 | 已完成 | S0 实跑与 3/3 job resume 通过，提交 `5045e40`、`21284b5` |
| 5 独立 validator 与 oer-wf 桥接 | 已完成 | 篡改拒绝测试、S1 81 行重建测试通过，提交 `2cae743` |
| 6 TaskSpec | S1 已完成；S2 条件等待 | S1 TaskSpec 提交 `eb35b92`；S2 只在 S1 验收且 eligibility 非空后冻结具体 S1 summary 路径 |
| 7 本地验证 | 已完成 | CN S0 `PASS/STRUCTURE_ONLY`；Python 503、oer-wf 136、Web 3 tests 通过 |
| 8 Legion 正式运行 | S1 已完成并独立验收；S2 按冻结规则不创建 | S1：81 jobs × 100 trials × LSODA，N0=0.0；独立 validator `gate=PASS`、`stage_status=DESIGN_INSUFFICIENT_NOISELESS`、`eligible_parameter_pairs=[]`；三组参数对 P2 全失败 → 不创建 S2。归档 `~/OER-FTAcV-archive/results/21284b5/pre_experiment_a6_v2_s1_lsoda/20260801_140736/` |

S2 TaskSpec 不提前写占位路径。这样可避免引用未知时间戳、未经独立验收或错误
S1 归档；若 S1 三组参数对的 P2 全失败，则按冻结规则不创建 S2 正式任务。

### 任务 8 验收（2026-08-02）

S1 结构/完整性 gate PASS，科学门 FAIL（`DESIGN_INSUFFICIENT_NOISELESS`）。
V4.1 推荐三协议在无噪声合成下不能恢复任何参数对；S2 不创建。
详细记录见 WORK_STATUS 第 68 节。

## 0. 文件边界

| 路径 | 责任 |
|---|---|
| `config/recovery/pre-experiment-a6-v2.json` | 唯一冻结科学规格 |
| `code/python/src/oer_aem/portfolio_recovery.py` | 协议、target key/hash、组合目标、job 矩阵和协议分类 |
| `code/python/src/oer_aem/inversion.py` | 复用同一 Optuna 循环运行单条件或组合目标 |
| `code/python/scripts/run_synthetic_recovery.py` | 新阶段 CLI、并行、checkpoint、resume、输出与 provenance |
| `code/python/scripts/validate_pre_experiment_recovery.py` | 独立重建结构门和科学门 |
| `config/oer-wf/oer_wf/validators/pre_experiment_recovery_gate.py` | oer-wf 到独立 validator 的桥接 |
| `config/oer-wf/examples/pre_experiment_a6_v2_s1_lsoda.yaml` | S1 正式 TaskSpec |
| `config/oer-wf/examples/pre_experiment_a6_v2_s2_lsoda.yaml` | S2 正式 TaskSpec |

不得创建第二套 recovery runner，不修改真实数据 Gate A6 的 `FAIL_RECOVERY`，不让 CN 结果进入正式科学门。

## 1. 冻结科学规格

**Files:**

- Create: `config/recovery/pre-experiment-a6-v2.json`
- Create: `code/python/tests/test_portfolio_recovery.py`

- [ ] **Step 1: 写冻结规格解析失败测试**

在 `test_portfolio_recovery.py` 中创建测试，断言：协议严格嵌套；只有三组参数对、三个真值和三个 optimizer seed；正式 trials 必须为 100；H1-H3、hybrid、128 点不可改；N1 噪声必须等于证据值；正式后端必须为 LSODA。

```python
def test_frozen_spec_has_exact_scientific_matrix(project_root):
    spec = load_pre_experiment_spec(
        project_root / "config/recovery/pre-experiment-a6-v2.json"
    )
    assert tuple(spec.portfolios) == ("P0", "P1", "P2")
    assert spec.portfolios["P0"] == ("baseline_5hz_amp_016",)
    assert spec.portfolios["P1"] == (
        "baseline_5hz_amp_016", "candidate_5hz_amp_008"
    )
    assert spec.portfolios["P2"] == (
        "baseline_5hz_amp_016",
        "candidate_5hz_amp_008",
        "candidate_10hz_matched_scan",
    )
    assert spec.parameter_pairs == (
        ("k0_2", "k0_3"), ("k0_3", "G_O"), ("G_OH", "G_O")
    )
    assert spec.truth_ids == ("center", "mixed_a", "mixed_b")
    assert spec.optimizer_seeds == (7, 17, 27)
    assert spec.trials == 100
    assert spec.fit_harmonics == (1, 2, 3)
    assert spec.feature_mode == "hybrid"
    assert spec.feature_grid_size == 128
    assert spec.formal_backend == "lsoda"
```

- [ ] **Step 2: 运行单测并确认因模块或规格缺失而失败**

Run: `.venv/bin/pytest code/python/tests/test_portfolio_recovery.py -q`

Expected: FAIL，错误为 `oer_aem.portfolio_recovery` 或冻结规格不存在。

- [ ] **Step 3: 写入冻结 JSON**

JSON 必须显式包含：三个 condition 的 `E_start/E_end/f/dE/cycles/points_per_cycle`；P0/P1/P2 condition IDs；三组参数对；truth IDs；optimizer seeds；N0/N1；100 trials；hybrid/H1-H3/128；LSODA；冻结阈值；噪声证据相对路径；S1 全 P2 失败时禁止 S2。

正式条件使用：

```json
{
  "schema_version": 1,
  "model": {"id": "M0", "beta_recon": 0.0},
  "conditions": {
    "baseline_5hz_amp_016": {"f": 5.0, "dE": 0.16, "cycles": 256},
    "candidate_5hz_amp_008": {"f": 5.0, "dE": 0.08, "cycles": 256},
    "candidate_10hz_matched_scan": {"f": 10.0, "dE": 0.16, "cycles": 512}
  },
  "portfolios": {
    "P0": ["baseline_5hz_amp_016"],
    "P1": ["baseline_5hz_amp_016", "candidate_5hz_amp_008"],
    "P2": ["baseline_5hz_amp_016", "candidate_5hz_amp_008", "candidate_10hz_matched_scan"]
  },
  "parameter_pairs": [["k0_2", "k0_3"], ["k0_3", "G_O"], ["G_OH", "G_O"]],
  "truth_ids": ["center", "mixed_a", "mixed_b"],
  "optimizer_seeds": [7, 17, 27],
  "trials": 100,
  "feature_mode": "hybrid",
  "fit_harmonics": [1, 2, 3],
  "feature_grid_size": 128,
  "formal_backend": "lsoda",
  "noise_fractions": {"S1": 0.0, "S2": 0.001495726085983469},
  "thresholds": {
    "max_median_normalized_bound_error": 0.025,
    "max_normalized_bound_error": 0.05,
    "max_seed_normalized_bound_dispersion": 0.05,
    "max_boundary_hit_rate": 0.0,
    "require_all_studies_success": true
  }
}
```

- [ ] **Step 4: 实现严格 loader 并通过测试**

`load_pre_experiment_spec(path)` 使用 frozen dataclass 返回不可变对象；拒绝未知 condition 引用、非嵌套 portfolio、非冻结阈值、非 100 trials、重复参数对/seed/truth、非 LSODA 正式后端和非有限数字。

Run: `.venv/bin/pytest code/python/tests/test_portfolio_recovery.py -q`

Expected: PASS。

## 2. 科学核心：条件目标与确定性复用

**Files:**

- Modify: `code/python/src/oer_aem/portfolio_recovery.py`
- Test: `code/python/tests/test_portfolio_recovery.py`

- [ ] **Step 1: 写 target seed、hash 和等权损失失败测试**

```python
def test_target_identity_excludes_portfolio_id():
    a = target_identity("mixed_a", 0.0, "baseline_5hz_amp_016")
    b = target_identity("mixed_a", 0.0, "baseline_5hz_amp_016")
    assert a == b
    assert set(a) == {"target_key", "target_seed"}

def test_portfolio_objective_is_equal_mean_after_condition_normalization():
    left = StubObjective(2.0)
    right = StubObjective(8.0)
    objective = PortfolioObjective((left, right))
    assert objective([0.5, 0.5]) == 5.0
    assert left.calls == 1 and right.calls == 1
```

另加测试：将 P0/P1/P2 名称传给 target identity 不得改变 seed；target manifest 中同一 condition key 只能对应一个 SHA-256；任何一个条件失败返回冻结 penalty；聚合诊断为各条件计数之和。

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/bin/pytest code/python/tests/test_portfolio_recovery.py -q`

Expected: FAIL，缺少 `target_identity`、`PortfolioObjective` 或 manifest 校验。

- [ ] **Step 3: 实现确定性身份与序列化哈希**

```python
def target_identity(truth_id: str, noise_fraction: float, condition_id: str) -> dict[str, object]:
    key = f"{truth_id}|{float(noise_fraction):.17g}|{condition_id}"
    seed = int(hashlib.sha256(key.encode("utf-8")).hexdigest()[:8], 16)
    return {"target_key": key, "target_seed": seed}

def target_sha256(target: Mapping[str, Any]) -> str:
    digest = hashlib.sha256()
    for name in ("current", "dc"):
        values = np.ascontiguousarray(np.asarray(target[name]))
        digest.update(name.encode("ascii"))
        digest.update(values.dtype.str.encode("ascii"))
        digest.update(np.asarray(values.shape, dtype=np.int64).tobytes())
        digest.update(values.tobytes())
    return digest.hexdigest()
```

哈希实现还必须覆盖实际进入 hybrid objective 的 H1-H3 complex/lock-in 数据、mask 和 channel contract hash；不可只覆盖示例中的 `current/dc`。

- [ ] **Step 4: 实现组合目标**

`PortfolioObjective` 接收有序 `(condition_id, InversionObjective)`；每次用同一 encoded vector 调用全部条件目标；返回各条件已经归一化 loss 的算术平均。同步累加 `n_calls/n_forward/n_ode_fail/n_feature_fail/n_tafel_fail`，保存每个条件的 last/best loss；任一条件产生非有限值时返回冻结 `feature_fail_penalty`。

- [ ] **Step 5: 运行单测**

Run: `.venv/bin/pytest code/python/tests/test_portfolio_recovery.py -q`

Expected: PASS。

## 3. 复用 Optuna 循环

**Files:**

- Modify: `code/python/src/oer_aem/inversion.py`
- Modify: `code/python/src/oer_aem/portfolio_recovery.py`
- Test: `code/python/tests/test_inversion.py`
- Test: `code/python/tests/test_portfolio_recovery.py`

- [ ] **Step 1: 写通用 objective runner 失败测试**

测试 `TPEInverter.run_objective(objective, n_trials)` 与现有 `run(target)` 使用相同 sampler、normalized parameter suggestions、history、success 判据和结果类型；禁止 enqueue 真值。

```python
def test_run_delegates_to_run_objective(monkeypatch, synthetic_target):
    inverter = TPEInverter(seed=17)
    seen = {}
    monkeypatch.setattr(inverter, "run_objective", lambda objective, n_trials: seen.setdefault("objective", objective))
    inverter.run(synthetic_target, n_trials=3)
    assert isinstance(seen["objective"], InversionObjective)
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/bin/pytest code/python/tests/test_inversion.py code/python/tests/test_portfolio_recovery.py -q`

Expected: FAIL，`run_objective` 不存在。

- [ ] **Step 3: 抽取最小共用循环**

新增 `TPEInverter.run_objective(objective, n_trials)`；objective 协议必须提供调用接口、best_x、best_value 和诊断计数。保留 `run(target)` 公共行为：它只构造 `InversionObjective` 后转调共用循环。现有 initial_params 行为不变，但 A6-v2 runner 不传 initial params。

- [ ] **Step 4: 让 portfolio 调用共用循环**

`run_portfolio_inversion(...)` 为每个 condition 构造冻结 config 和 target，再构造 `PortfolioObjective`，最后调用 `TPEInverter.run_objective`。结果附带 condition loss、target key/hash、channel contract hash；自由参数仍只由对应参数对决定，其余参数固定为该 truth。

- [ ] **Step 5: 回归验证**

Run: `.venv/bin/pytest code/python/tests/test_inversion.py code/python/tests/test_synthetic_recovery_runner.py code/python/tests/test_portfolio_recovery.py -q`

Expected: PASS，旧单条件 runner 行为不变。

## 4. 扩展现有 runner 和可恢复证据

**Files:**

- Modify: `code/python/scripts/run_synthetic_recovery.py`
- Test: `code/python/tests/test_synthetic_recovery_runner.py`
- Test: `code/python/tests/test_portfolio_recovery.py`

- [ ] **Step 1: 写 CLI 和矩阵失败测试**

增加 `--pre-experiment-spec PATH` 与 `--portfolio-stage {S0,S1,S2}`。当启用该模式时，拒绝 `--trials`、`--free-parameters`、`--feature-modes` 和任意科学 override；S1 生成 81 jobs；S2 必须读取已验收 S1 summary，只为 P2 通过的参数对生成完整 P0/P1/P2 矩阵；三个 P2 均失败时明确拒绝 S2。

```python
def test_s1_matrix_is_complete_and_paired(frozen_spec):
    jobs = build_portfolio_jobs(frozen_spec, stage="S1")
    assert len(jobs) == 81
    assert len({job["job_id"] for job in jobs}) == 81
    assert {job["portfolio_id"] for job in jobs} == {"P0", "P1", "P2"}
    assert {job["trials"] for job in jobs} == {100}
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/bin/pytest code/python/tests/test_synthetic_recovery_runner.py code/python/tests/test_portfolio_recovery.py -q`

Expected: FAIL，新 CLI 或 job builder 不存在。

- [ ] **Step 3: 实现阶段路由且保留旧模式**

未传 `--pre-experiment-spec` 时旧 `pilot/formal` 路径完全不变。传入后：

- S0 可用 CN、最少三 jobs，只验证结构；
- S1 强制 N0、LSODA、100 trials；
- S2 强制 N1、LSODA、100 trials并校验噪声证据和 S1 eligibility；
- `--max-jobs` 仅 S0 可用；
- 正式 CLI 不能覆盖冻结科学矩阵。

- [ ] **Step 4: 将 portfolio 字段纳入 job hash 和 resume fingerprint**

fingerprint 必须包含 spec SHA-256、stage、parameter pair、portfolio condition 列表、truth、noise、optimizer seed、target identities、backend、100 trials、feature contract 和 source commit。checkpoint 行缺失这些字段、job hash 不符、JSONL 尾行损坏或同 target key 出现不同 hash 时拒绝 resume。

- [ ] **Step 5: 写完整输出**

原子写入：`pre_experiment_recovery_spec.json`、`protocol_catalog.csv`、`job_plan.json`、`target_manifest.json`、`results.jsonl`、`portfolio_recovery.csv`、`summary.json`、`run_manifest.json`。`STATUS.json` 和 `task_spec.snapshot.yaml` 由 oer-wf 写入。所有 JSON 使用 `allow_nan=False`；CSV 固定列顺序。

- [ ] **Step 6: 断点恢复回归**

Run: `.venv/bin/pytest code/python/tests/test_synthetic_recovery_runner.py code/python/tests/test_portfolio_recovery.py -q`

Expected: PASS，覆盖部分 checkpoint 复用、损坏拒绝、fingerprint 不匹配拒绝和已完成 job 不重算。

## 5. 独立 archive validator

**Files:**

- Create: `code/python/scripts/validate_pre_experiment_recovery.py`
- Create: `code/python/tests/test_pre_experiment_recovery_validator.py`
- Create: `config/oer-wf/oer_wf/validators/pre_experiment_recovery_gate.py`
- Modify: `config/oer-wf/oer_wf/validators/__init__.py`
- Create: `config/oer-wf/tests/test_pre_experiment_recovery_gate.py`

- [ ] **Step 1: 写结构和分类失败测试**

fixture 覆盖五种分类：`BASELINE_SUFFICIENT`、`AMP_008_ADDS_RECOVERY`、`TEN_HZ_ADDS_RECOVERY`、`DESIGN_INSUFFICIENT`、`NON_MONOTONIC_REQUIRES_REVIEW`。另覆盖缺行、重复行、非有限值、target hash 冲突、非 LSODA 正式结果、阈值被改写、S2 含 S1 不合格参数对、summary 与独立重建不一致。

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/bin/pytest code/python/tests/test_pre_experiment_recovery_validator.py config/oer-wf/tests/test_pre_experiment_recovery_gate.py -q`

Expected: FAIL，validator 不存在。

- [ ] **Step 3: 实现独立重建**

`validate_archive(project_root, task_spec, archive_dir)` 只信任冻结 spec 和原始结果行，不信任 runner 写入的 pass 字段。按 parameter pair / portfolio / truth / noise 重算 seed median error、单次 max error、有符号 seed dispersion、boundary rate 和全 study success；先检查通过序列是否非单调，再分配协议分类。

项目级状态规则固定为：S1 只输出参数对 eligibility；S2 至少一个参数对 P2 同时通过 S1/S2 才为 `PASS_CONDITIONAL_SYNTHETIC_RECOVERY`。任何项目级 PASS 不覆盖其他参数对失败，且 validator 不读取或修改真实 A6 gate。

- [ ] **Step 4: 实现 oer-wf 薄桥接**

桥接器采用 V4 validator 的受限相对路径解析和动态加载模式，只将独立 validator 的 structure/numerical/scientific 结果转换为 `CheckResult`。在 `validators/__init__.py` 注册模块，不复制科学计算。

- [ ] **Step 5: 验证 validator**

Run: `.venv/bin/pytest code/python/tests/test_pre_experiment_recovery_validator.py config/oer-wf/tests/test_pre_experiment_recovery_gate.py -q`

Expected: PASS。

## 6. oer-wf S1/S2 TaskSpec

**Files:**

- Create: `config/oer-wf/examples/pre_experiment_a6_v2_s1_lsoda.yaml`
- Create: `config/oer-wf/examples/pre_experiment_a6_v2_s2_lsoda.yaml`
- Test: `config/oer-wf/tests/test_workflow_smoke_task.py`

- [ ] **Step 1: 写 TaskSpec 契约失败测试**

断言两份 TaskSpec 使用主仓 `.venv/bin/python`、8 workers、四种 BLAS/OpenMP 线程均为 1、正式 LSODA、支持 resume、包含全部预期文件和 `pre_experiment_recovery_gate`。S2 args 必须指向 S1 已验收 summary，不得自行选择参数对。

- [ ] **Step 2: 写 S1 TaskSpec**

核心参数固定为：

```yaml
script: "code/python/scripts/run_synthetic_recovery.py"
supports_resume: true
args: ["--pre-experiment-spec", "config/recovery/pre-experiment-a6-v2.json", "--portfolio-stage", "S1"]
workers: 8
output_dir: "results/pre_experiment_recovery/a6-v2-s1"
```

smoke 只添加 `--portfolio-stage S0` 的等价覆盖，不修改正式 S1 参数；若 oer-wf overrides 无法安全替换同名参数，则提供独立 S0 TaskSpec，禁止产生重复 CLI 参数。

- [ ] **Step 3: 写 S2 TaskSpec**

S2 除 stage 和 S1 eligibility 输入外与 S1 相同；正式执行前 validator 校验 S1 archive commit、spec hash、gate 和 eligible pairs。

- [ ] **Step 4: 验证 TaskSpec**

Run: `.venv/bin/pytest config/oer-wf/tests/test_workflow_smoke_task.py config/oer-wf/tests/test_pre_experiment_recovery_gate.py -q`

Expected: PASS。

## 7. 本地 S0 与全量回归

**Files:**

- Modify only if failures prove necessary: files listed in Tasks 1-6
- Evidence: `results/smoke/pre_experiment_recovery/a6-v2-s0/`（不提交 Git）

- [ ] **Step 1: 运行聚焦测试**

Run: `.venv/bin/pytest code/python/tests/test_portfolio_recovery.py code/python/tests/test_synthetic_recovery_runner.py code/python/tests/test_pre_experiment_recovery_validator.py config/oer-wf/tests/test_pre_experiment_recovery_gate.py -q`

Expected: PASS。

- [ ] **Step 2: 运行 CN S0**

Run: `.venv/bin/python code/python/scripts/run_synthetic_recovery.py --pre-experiment-spec config/recovery/pre-experiment-a6-v2.json --portfolio-stage S0 --backend cn --workers 8 --output results/smoke/pre_experiment_recovery/a6-v2-s0`

Expected: 三个 portfolio 均产生有限结果，target manifest 证明嵌套 condition 的 key/hash 一致，validator 只报告结构通过而不生成正式科学结论。

- [ ] **Step 3: 测试 S0 resume**

在完整 S0 归档副本中只保留部分合法 `results.jsonl`，用相同命令加 `--resume`；预期只执行缺失 jobs。修改一行 `job_input_hash` 后再次执行；预期在启动计算前拒绝。

- [ ] **Step 4: 运行全量测试**

Run: `.venv/bin/pytest code/python/tests -q`

Expected: 当前项目 Python 全量测试全部 PASS。

Run: `.venv/bin/pytest config/oer-wf/tests -q`

Expected: oer-wf 全量测试全部 PASS。

Run: `.venv/bin/python -m pytest code/web/tests/backend -q`

Expected: Web 3 tests PASS；允许已知的 Starlette/httpx 弃用警告，但不得有测试失败。

- [ ] **Step 5: 完成前审计**

Run: `git diff --check`

Expected: 无输出。

Run: `rg -n "T[B]D|T[O]DO|FIX[M]E|PLACEH[O]LDER" config/recovery/pre-experiment-a6-v2.json code/python/src/oer_aem/portfolio_recovery.py code/python/scripts/validate_pre_experiment_recovery.py`

Expected: 无输出。

## 8. Legion 正式 S1、条件 S2 与项目更新

**Files:**

- Modify after verified result: `PROJECT_SUMMARY.md`
- Modify after verified result: `WORK_STATUS.md`
- Modify after verified result: `documents/corrections/项目纠错.md`（仅出现新问题时）
- Archive: `results/formal/pre_experiment_recovery/a6-v2-s1-*`
- Conditional archive: `results/formal/pre_experiment_recovery/a6-v2-s2-*`

- [ ] **Step 1: 读取环境配置并冻结干净 commit**

远程或 GitHub 操作前完整阅读 `/Users/liushiyu/gpt/本机环境配置.md`。确认源代码干净；保留且不提交 `results/smoke/experiment_design/`。提交实现与测试并推送当前 `codex/reclassify-project` 分支，TaskSpec commit 随之冻结为实际提交。

- [ ] **Step 2: Legion doctor、prepare、smoke、verify**

使用 `oer-wf 0.7.0` 和既有 SSH 别名执行；不得手工复制未冻结源码。smoke archive 必须通过 expected files、schema、finite、provenance 和独立 recovery validator。

- [ ] **Step 3: 启动 S1 LSODA**

8 workers，每 worker 数学库线程为 1。执行期间只在用户要求时检查，不创建定时检查。基础设施失败保留证据后用同 commit/spec resume；数值或科学失败不改预算和阈值。

- [ ] **Step 4: 独立验收 S1**

要求 81 唯一 studies、完整 3×3×3×3 矩阵、有限值、全部输出哈希一致、正式 backend 为 LSODA、source commit/spec/env 可追溯。若三个参数对 P2 全失败，写 `DESIGN_INSUFFICIENT_NOISELESS` 并停止，不生成 S2。

- [ ] **Step 5: 仅对 S1 eligible pairs 运行 S2**

S2 为每个 eligible pair 运行完整 P0/P1/P2 × 3 truths × 3 seeds；不得只运行 S1 最优 portfolio。独立 validator 重建协议分类与项目级条件门。

- [ ] **Step 6: 同步、二次验收和更新进度**

同步正式 archive 到 Mac 后再次运行 `wf verify`，确认传输前后哈希相同。更新项目文档时写明：条件恢复结论、失败参数对、适用边界、真实 A6 仍为 `FAIL_RECOVERY`、未来实验所需输入。只提交本项目相关正式证据和文档并推送。

## 压力测试与失败退出条件

1. **跨进程“字节级复用”不能靠共享缓存证明。** 正式证据采用确定性 target key、固定 seed、完整目标哈希和 validator 冲突检查；进程内缓存只是性能优化，不是科学证据。
2. **不同条件的扫描网格不同。** 每个 `InversionObjective` 必须按自己的 condition config 和 channel contract 独立归一化，之后才等权平均；禁止拼接原始残差。
3. **固定参数必须等于该合成 truth。** 只将参数对放入 free specs，其他 M0 参数通过 `fixed_params` 注入；若漏注入，测试必须用非中心 truth 捕获。
4. **S0 的 CN 不能污染正式门。** stage 和 backend 同时进入 job hash、summary、manifest 和 validator；正式 S1/S2 发现 CN 立即 `FAIL_STRUCTURE`。
5. **S1→S2 存在选择依赖但不能形成赢家偏差。** eligibility 只按预注册 P2 绝对门决定；入选参数对在 S2 仍跑全部 portfolio/truth/seed。
6. **非单调不能被“最小通过协议”掩盖。** validator 先检查 P0→P1→P2 pass 序列，再分类；`PASS,FAIL,PASS` 和 `PASS,PASS,FAIL` 均进入人工复核或失败，不写增量收益结论。
7. **100 trials 可能不足，但不能事后增加。** 本阶段回答冻结预算下的恢复能力；失败保留为科学结果，另立新设计才能改变优化器或预算。
8. **逆犯罪边界。** 即使通过，也只证明 M0 正确且固定输入准确时的条件恢复，不证明真实实验可恢复、机理正确或完整参数可识别。

## 完成标准

- S0 结构、resume 和 target 复用证据通过；
- 项目 Python、oer-wf 和 Web 全量测试无回归；
- Legion S1 使用冻结 LSODA/100 trials/8 workers 完成并由独立 validator 验收；
- 只有 S1 eligible pairs 才进入 S2；若触发冻结停止条件则不运行 S2；
- 正式 archive 可追溯到 commit、spec、数据证据、环境和哈希；
- 更新项目进度但保持真实数据 Gate A6 为 `FAIL_RECOVERY`。
