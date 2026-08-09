# Formal-v2 无 legacy-DC Tafel 的实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为未来 A6 formal profile 建立版本化的 `formal-v2-no-tafel` 目标契约：没有独立验收的表观 Tafel 时，显式关闭历史 DC 阈值 Tafel 通道，而不是以提取失败罚分代替物理判断。

**Architecture:** `InversionConfig` 增加显式 Tafel 通道模式。默认 `legacy_dc_diagnostic` 保持历史结果可重放；新的 objective contract 将其设为 `disabled`，让特征契约记录关闭理由、目标和候选均不计算 legacy `measure_tafel`、目标函数不产生 `physical=100`。现有 profile runner 以版本化命令参数传入该模式并写入 task、summary 与 manifest。未来外部 `validated_apparent_tafel` 另行实现，不把现有 CV 伪装成该约束。

**Tech Stack:** Python 3.13、NumPy、SciPy、pytest、JSON、LSODA。

---

## 冻结边界与压力测试

- 不修改 `2026-08-09` 的 legacy profile、其失败门、CSV 或结论；该运行仍为 `FAIL_PROFILE_CONTRACT`。
- `formal-v2-no-tafel` 与 legacy-v1 的 loss/width 不可直接比较，因为 active feature contract 不同；结果只可回答“移除非科学罚分后的合成可恢复性”。
- 本轮不把 `TafelConstraint` 空壳接入目标函数。外部约束必须先满足 `2026-08-09-tafel-constraint-revision.md` 的 RHE、iR、面积、稳态、重复性与 holdout 门。
- 新 profile 即使基础设施通过，也不能自动启动 CMA；仍需零 ODE/feature failure、truth global-minimum、有效宽度和预注册 recovery gate。
- 正式运行固定 LSODA，CN 仍只能 screen-only。

## 文件与职责

| 路径 | 改动职责 |
|---|---|
| `code/python/src/oer_aem/inversion.py` | 定义并执行 Tafel 通道模式；把 mode 写入特征契约并关停 legacy 特征。 |
| `code/python/scripts/run_objective_profiles.py` | 提供版本化 objective contract，传递给 worker 并写入完整 provenance。 |
| `code/python/tests/test_inversion.py` | 锁定 disabled 模式不提取、不罚分、且契约可审计。 |
| `code/python/tests/test_objective_profile_runner.py` | 锁定 legacy 默认可重放与 formal-v2 禁用 Tafel 的配置/manifest。 |
| `documents/project/PROJECT_SUMMARY.md` | 标记 formal-v2 的科学边界和 legacy profile 不变。 |
| `documents/project/WORK_STATUS.md` | 记录实现、smoke、formal 运行和 gate 结论。 |

### Task 1: 写入 feature-contract 的 Tafel 模式

**Files:**

- Modify: `code/python/src/oer_aem/inversion.py`
- Modify: `code/python/tests/test_inversion.py`

- [x] **Step 1: 写失败测试**

```python
def test_disabled_tafel_channel_never_creates_a_penalty():
    config = InversionConfig(
        n_points=256, points_per_cycle=32, feature_grid_size=32,
        tafel_channel_mode="disabled",
    )
    target = make_synthetic_target(TRUTH, config=config)
    objective = InversionObjective(target, config=config)
    assert target["tafel"] is None
    by_id = {item.channel_id: item for item in objective.channel_contract.channels}
    assert by_id["tafel"].exclusion_reason == "disabled_by_objective_contract"
    assert objective(encode_params(TRUTH, DEFAULT_PARAM_SPECS)) < 1e-12
    assert objective.n_tafel_fail == 0
```

- [x] **Step 2: 运行失败测试**

Run: `PYTHONPATH=code/python/src .venv/bin/python -m pytest code/python/tests/test_inversion.py -k disabled_tafel -q`
Expected: FAIL，因为 `InversionConfig` 尚无该模式。

- [x] **Step 3: 最小实现**

在 `InversionConfig` 新增 `tafel_channel_mode: str = "legacy_dc_diagnostic"`；
只允许 `legacy_dc_diagnostic` 与 `disabled`。在 `extract_features()` 中，只有前者调用
`measure_tafel()`；后者输出 `features["tafel"] = None`。在
`build_feature_channel_contract()` 中，disabled Tafel channel 的
`is_requested=False`、`available=False`、`active=False`、`reason="disabled_by_objective_contract"`，并把模式写入 evidence/hash。非法模式在建 objective 前拒绝。

- [x] **Step 4: 验证**

Run: `PYTHONPATH=code/python/src .venv/bin/python -m pytest code/python/tests/test_inversion.py -q`
Expected: PASS；旧 legacy 测试仍保持历史行为。

### Task 2: 将 objective contract 固化到 profile provenance

**Files:**

- Modify: `code/python/scripts/run_objective_profiles.py`
- Modify: `code/python/tests/test_objective_profile_runner.py`

- [x] **Step 1: 写失败测试**

```python
def test_formal_v2_profile_contract_disables_legacy_dc_tafel(tmp_path):
    args = runner.parse_args([
        "--output", str(tmp_path / "profiles"),
        "--objective-contract", "formal-v2-no-tafel",
    ])
    config = runner.build_config(args, feature_mode="hybrid")
    assert config.tafel_channel_mode == "disabled"
```

- [x] **Step 2: 运行失败测试**

Run: `PYTHONPATH=code/python/src .venv/bin/python -m pytest code/python/tests/test_objective_profile_runner.py -k formal_v2 -q`
Expected: FAIL，因为 CLI 尚不识别 objective contract。

- [x] **Step 3: 最小实现**

新增 `--objective-contract {legacy-v1,formal-v2-no-tafel}`，默认
`legacy-v1` 以允许历史重放；contract 到 Tafel 模式的映射只在一个函数维护。将
`objective_contract` 复制到每个 task，让 `ProcessPoolExecutor` worker 使用同一配置，并写入 summary/manifest `configuration`。不要改动 profile 的网格、truth、solver、workers 或历史结果路径。

- [x] **Step 4: 验证 smoke provenance**

Run: `PYTHONPATH=code/python/src .venv/bin/python -m pytest code/python/tests/test_objective_profile_runner.py -q`
Expected: PASS；新增 smoke manifest 精确包含 `objective_contract="formal-v2-no-tafel"` 与 `tafel_channel_mode="disabled"`。

### Task 3: 科学验收、提交与后续运行授权

**Files:**

- Modify: `documents/project/PROJECT_SUMMARY.md`
- Modify: `documents/project/WORK_STATUS.md`

- [x] **Step 1: 写入不变性**

明确 legacy profile 的 `physical=100` 是历史证据；formal-v2 禁用通道不是修补阈值，也不是 Tafel 机理通过。未来 external Tafel 只能由新的 `validated_apparent_tafel` 接口加入。

- [x] **Step 2: 运行本机验证**

Run: `.venv/bin/python code/python/scripts/run_tests.py code/python/tests -q`
Expected: 全量通过；再运行 `git diff --check`。

- [x] **Step 3: Sol 只读质检**

检查 disabled 模式是否可由候选绕过、是否仍计入 `n_tafel_fail`、worker configuration 是否丢失、以及文档是否把 no-Tafel profile 误称为真实 Tafel 结论。

- [ ] **Step 4: 提交与远端 formal profile**

仅在本机测试、Sol 质检与 GitHub 推送通过后，在 clean Legion worktree 运行：

```bash
python code/python/scripts/run_objective_profiles.py \
  --objective-contract formal-v2-no-tafel \
  --grid-points 41 --workers 8 \
  --output results/formal/objective_profiles/<commit>-formal-v2-no-tafel
```

验收 20 profiles、820 rows、LSODA/8192/32ppc/H1-H3/zero-noise、contract 与 commit 一致、全部有限、truth global-minimum、无 ODE failure；再按新的 profile contract 决定是否可以运行 recovery。Tafel 不得作为此运行的 fail gate。

验收必须调用 `code/python/scripts/validate_formal_profile_contract.py`，将只读
`acceptance_formal_v2.json` 写入结果目录；validator 的 `PASS` 仅证明 profile 证据完整，
不自动授权 CMA 或真实反演。
