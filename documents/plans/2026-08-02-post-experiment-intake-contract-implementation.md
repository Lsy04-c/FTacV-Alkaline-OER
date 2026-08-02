# 恢复实验接入契约实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立 Gate A1 之前的实验接入模板和独立 validator，在反演前冻结数据角色、核验文件与元数据，并输出唯一下一动作。

**Architecture:** `experiment_intake.py`只做纯数据校验和状态分类；命令行脚本负责文件读写、哈希绑定、`acceptance.md`和条件式 A1 seed。空模板固定为`WAITING_FOR_DATA`；只有三个预注册条件全部 collected、结构正确且关键元数据齐全时才生成非正式 A1 seed。

**Tech Stack:** Python 3.13、标准库`json/hashlib/pathlib`、pytest；不依赖 NumPy、求解器、优化器或 Web。

**Execution constraint:** 用户要求本阶段不提交 Git。各检查点只运行测试和`git diff --check`。

---

## 文件结构

- Create `config/data-contracts/post-experiment-intake-v1.template.json`：无真实数据的计划模板。
- Create `code/python/src/oer_aem/experiment_intake.py`：路径、角色、元数据、哈希和状态机。
- Create `code/python/scripts/validate_post_experiment_intake.py`：CLI和结果输出。
- Create `code/python/tests/test_experiment_intake.py`：纯逻辑测试。
- Create `code/python/tests/test_post_experiment_intake_validator.py`：真实临时文件和CLI测试。
- Modify `documents/project/PROJECT_SUMMARY.md`、`WORK_STATUS.md`和已批准设计文档。

### Task 1：冻结模板与空状态

**Files:**
- Create: `config/data-contracts/post-experiment-intake-v1.template.json`
- Create: `code/python/src/oer_aem/experiment_intake.py`
- Create: `code/python/tests/test_experiment_intake.py`

- [x] **Step 1: 写失败测试**

```python
def test_empty_frozen_template_waits_for_data():
    manifest = json.loads(TEMPLATE.read_text(encoding="utf-8"))
    result = validate_intake(ROOT, manifest)
    assert result["status"] == "WAITING_FOR_DATA"
    assert result["missing_conditions"] == [
        "baseline_5hz_amp016",
        "lowamp_5hz_amp008",
        "highfreq_10hz_amp016",
    ]
    assert result["structure_errors"] == []
    assert result["metadata_errors"] == []
```

- [x] **Step 2: 确认 RED**

```bash
.venv/bin/python -m pytest code/python/tests/test_experiment_intake.py::test_empty_frozen_template_waits_for_data -q
```

Expected: import或模板缺失导致FAIL。

- [x] **Step 3: 创建模板**

顶层字段固定为`schema_version/intake_id/manifest_state/role_freeze/batch/datasets/
independent_inputs`。`datasets`包含三条planned主记录：

```python
REQUIRED_CONDITION_ROLES = {
    "baseline_5hz_amp016": "training",
    "lowamp_5hz_amp008": "selection",
    "highfreq_10hz_amp016": "holdout",
}
```

每条记录包含空`raw_file/method_file`、`sample_role=formal_sample`和全部关键
metadata。空字段统一使用：

```json
{"value": null, "source_kind": "unresolved", "source_note": "not collected"}
```

- [x] **Step 4: 实现最小入口**

```python
ACCEPTED_SOURCE_KINDS = {"file_observed", "derived", "externally_declared"}
REQUIRED_METADATA = {
    "column_contract", "original_reference_electrode", "rhe_conversion",
    "ph", "temperature_K", "electrolyte", "ir_compensation",
    "instrument_preprocessing", "current_basis",
}

def validate_intake(project_root: Path, manifest: dict) -> dict:
    """Return deterministic intake status without mutating inputs."""
```

首版只接受`schema_version=1`、精确检查三条planned记录和冻结角色；全部planned
返回`WAITING_FOR_DATA`，不把空metadata当失败。

- [x] **Step 5: 确认 GREEN**

```bash
.venv/bin/python -m pytest code/python/tests/test_experiment_intake.py -q
git diff --check
```

Expected: PASS、exit 0。

### Task 2：结构门与状态优先级

**Files:**
- Modify: `code/python/src/oer_aem/experiment_intake.py`
- Modify: `code/python/tests/test_experiment_intake.py`

- [x] **Step 1: 写三个失败测试**

```python
def test_collected_record_with_missing_file_is_structure_failure(tmp_path):
    manifest = collected_manifest(tmp_path)
    manifest["datasets"][0]["raw_file"]["path"] = "data/raw/missing.txt"
    result = validate_intake(tmp_path, manifest)
    assert result["status"] == "FAIL_STRUCTURE"

def test_holdout_role_cannot_be_reassigned(tmp_path):
    manifest = collected_manifest(tmp_path)
    manifest["datasets"][2]["analysis_role"] = "training"
    assert validate_intake(tmp_path, manifest)["status"] == "FAIL_STRUCTURE"

def test_same_raw_file_cannot_serve_training_and_holdout(tmp_path):
    manifest = collected_manifest(tmp_path)
    manifest["datasets"][2]["raw_file"] = dict(manifest["datasets"][0]["raw_file"])
    assert validate_intake(tmp_path, manifest)["status"] == "FAIL_STRUCTURE"
```

测试helper独立创建三个小型三列文件、三个方法文件和真实SHA-256，不调用产品
代码生成预期值。

- [x] **Step 2: 确认 RED**

```bash
.venv/bin/python -m pytest code/python/tests/test_experiment_intake.py -q
```

Expected: 新增结构测试FAIL。

- [x] **Step 3: 实现路径与唯一性规则**

```python
def _safe_source_path(root: Path, raw: object, label: str):
    if not isinstance(raw, str) or not raw:
        return None, f"{label} path is missing"
    relative = Path(raw)
    if relative.is_absolute() or ".." in relative.parts:
        return None, f"{label} path must be project-relative"
    if relative.parts and relative.parts[0] in {"results", ".git"}:
        return None, f"{label} path must be a source artifact"
    return root / relative, None
```

随后检查：dataset/experiment/condition ID唯一；condition与角色精确匹配；状态
只允许planned/collected；collected的raw/method存在且SHA一致；training与
holdout不能引用同一raw哈希。任一结构错误优先返回`FAIL_STRUCTURE`。

- [x] **Step 4: 确认 GREEN**

```bash
.venv/bin/python -m pytest code/python/tests/test_experiment_intake.py -q
```

Expected: PASS。

### Task 3：元数据门、报告限制和READY

**Files:**
- Modify: `code/python/src/oer_aem/experiment_intake.py`
- Modify: `code/python/tests/test_experiment_intake.py`

- [x] **Step 1: 写失败测试**

```python
def test_unknown_preprocessing_is_metadata_failure(tmp_path):
    manifest = collected_manifest(tmp_path)
    manifest["datasets"][0]["metadata"]["instrument_preprocessing"] = {
        "value": None, "source_kind": "unresolved", "source_note": "unknown"
    }
    assert validate_intake(tmp_path, manifest)["status"] == "FAIL_METADATA"

def test_complete_collected_manifest_is_ready_for_a1(tmp_path):
    result = validate_intake(tmp_path, collected_manifest(tmp_path))
    assert result["status"] == "READY_FOR_A1_AUDIT"
    assert result["next_action"] == "generate_new_batch_a1_registry"

def test_missing_active_site_amount_only_adds_reporting_restriction(tmp_path):
    manifest = collected_manifest(tmp_path)
    manifest["independent_inputs"]["active_site_amount"] = None
    result = validate_intake(tmp_path, manifest)
    assert result["status"] == "READY_FOR_A1_AUDIT"
    assert "no_site_normalized_turnover" in result["reporting_restrictions"]
```

- [x] **Step 2: 确认 RED**

```bash
.venv/bin/python -m pytest code/python/tests/test_experiment_intake.py -q
```

Expected: 元数据/READY测试FAIL。

- [x] **Step 3: 实现元数据规则**

每个collected记录必须精确包含`REQUIRED_METADATA`。字段必须为对象，
`source_kind`可接受且`value`非null。预处理`value`必须是以下完整布尔映射：

```python
PREPROCESSING_KEYS = {
    "filtering", "smoothing", "averaging", "background_subtraction",
    "cropping", "downsampling", "current_normalization",
}
```

独立输入不阻止A1 readiness，但非空记录必须含
`value/unit/uncertainty/method/source_path/source_sha256/independent_of_ftacv`。
非独立输入增加`not_eligible_as_fixed_input:<name>`；缺位点量增加
`no_site_normalized_turnover`。

- [x] **Step 4: 冻结分类顺序**

```python
if structure_errors:
    status = "FAIL_STRUCTURE"
elif metadata_errors:
    status = "FAIL_METADATA"
elif missing_conditions:
    status = "WAITING_FOR_DATA"
else:
    status = "READY_FOR_A1_AUDIT"
```

输出必须含`status/structure_errors/metadata_errors/missing_conditions/
reporting_restrictions/next_action`，数组排序以保证确定性。

- [x] **Step 5: 确认 GREEN**

```bash
.venv/bin/python -m pytest code/python/tests/test_experiment_intake.py -q
```

Expected: PASS。

### Task 4：独立CLI与条件式A1 seed

**Files:**
- Create: `code/python/scripts/validate_post_experiment_intake.py`
- Create: `code/python/tests/test_post_experiment_intake_validator.py`

- [x] **Step 1: 写CLI失败测试**

```python
def test_template_cli_waits_without_writing_a1_seed(tmp_path):
    output = tmp_path / "out"
    code = main(["--project-root", str(ROOT), "--manifest", str(TEMPLATE),
                 "--output", str(output)])
    assert code == 2
    assert json.loads((output / "intake_summary.json").read_text())["status"] == "WAITING_FOR_DATA"
    assert not (output / "a1_seed.json").exists()

def test_ready_cli_writes_nonformal_a1_seed(tmp_path):
    root, manifest_path = complete_fixture(tmp_path)
    output = tmp_path / "out"
    assert main(["--project-root", str(root), "--manifest", str(manifest_path),
                 "--output", str(output)]) == 0
    seed = json.loads((output / "a1_seed.json").read_text())
    assert seed["status"] == "UNVALIDATED_SEED"
    assert seed["requires_new_batch_a1_validator"] is True
```

- [x] **Step 2: 确认 RED**

```bash
.venv/bin/python -m pytest code/python/tests/test_post_experiment_intake_validator.py -q
```

Expected: CLI模块缺失导致FAIL。

- [x] **Step 3: 实现CLI**

参数为`--project-root/--manifest/--output`。输出目录非空即拒绝；JSON拒绝
NaN/Inf；原子写`intake_summary.json`和`acceptance.md`。退出码固定：

```python
EXIT_CODES = {
    "READY_FOR_A1_AUDIT": 0,
    "WAITING_FOR_DATA": 2,
    "FAIL_METADATA": 3,
    "FAIL_STRUCTURE": 4,
}
```

- [x] **Step 4: 实现A1 seed和文本边界**

仅READY写`a1_seed.json`，其中必须包含：

```json
{
  "schema_version": 1,
  "status": "UNVALIDATED_SEED",
  "requires_new_batch_a1_validator": true,
  "source_intake_id": "...",
  "source_manifest_sha256": "...",
  "datasets": []
}
```

seed不写固定行数，不宣布数值门通过，不复用旧A1 gate version。acceptance必须
包含：“本结果不代表 Gate A1 PASS；不授权 A6-v2、真实反演或参数点估计。”

- [x] **Step 5: 确认 GREEN**

```bash
.venv/bin/python -m pytest code/python/tests/test_post_experiment_intake_validator.py -q
```

Expected: PASS。

### Task 5：故障注入与依赖隔离

**Files:**
- Modify: `code/python/tests/test_experiment_intake.py`
- Modify: `code/python/tests/test_post_experiment_intake_validator.py`

- [x] **Step 1: 增加单变量故障测试**

分别覆盖：raw改一字节、method哈希错误、重复experiment ID、绝对路径、`../`、
`results/`来源、NaN/Inf、collected缺文件、角色互换、同文件承担training与
holdout、未知预处理、不独立`Ru/Cdl`。每项断言精确状态和错误分类。

- [x] **Step 2: 增加依赖隔离测试**

```python
def test_intake_validator_does_not_import_scientific_runtime():
    source = VALIDATOR.read_text(encoding="utf-8")
    for forbidden in ("oer_aem.physics", "scipy", "optuna", "code.web"):
        assert forbidden not in source
```

- [x] **Step 3: 运行全部接入测试**

```bash
.venv/bin/python -m pytest \
  code/python/tests/test_experiment_intake.py \
  code/python/tests/test_post_experiment_intake_validator.py -q
```

Expected: PASS且无warning。

### Task 6：模板验收、文档和全量回归

**Files:**
- Create: `results/smoke/experiment_intake/template-v1/intake_summary.json`
- Create: `results/smoke/experiment_intake/template-v1/acceptance.md`
- Modify: `documents/project/PROJECT_SUMMARY.md`
- Modify: `documents/project/WORK_STATUS.md`
- Modify: `documents/specifications/2026-08-02-post-experiment-intake-contract-design.md`

- [x] **Step 1: 运行空模板验收**

```bash
.venv/bin/python code/python/scripts/validate_post_experiment_intake.py \
  --project-root . \
  --manifest config/data-contracts/post-experiment-intake-v1.template.json \
  --output results/smoke/experiment_intake/template-v1
```

Expected: exit 2、`WAITING_FOR_DATA`、无`a1_seed.json`。

- [x] **Step 2: 验收文件集合**

```bash
test -f results/smoke/experiment_intake/template-v1/intake_summary.json
test -f results/smoke/experiment_intake/template-v1/acceptance.md
test ! -e results/smoke/experiment_intake/template-v1/a1_seed.json
```

Expected: all exit 0。

- [x] **Step 3: 更新文档**

总览写入唯一入口、三角色、四状态和“READY不等于A1 PASS”。进度记录实现文件、
模板状态、测试数和产物SHA-256。设计文档状态改为“已实施；等待真实数据”，并
加入模板、validator和smoke路径。

- [x] **Step 4: 运行目标回归**

```bash
git diff --check
.venv/bin/python -m pytest \
  code/python/tests/test_data_contract.py \
  code/python/tests/test_gate_a1_contract_validator.py \
  code/python/tests/test_experiment_intake.py \
  code/python/tests/test_post_experiment_intake_validator.py -q
```

Expected: all pass。

- [x] **Step 5: 运行全量回归**

```bash
.venv/bin/python -m pytest code/python/tests -q
```

Expected: no failures；把准确计数和耗时写入`WORK_STATUS.md`。

- [x] **Step 6: 最终范围审计**

```bash
git status --short
git diff --check
```

确认未修改旧Gate A1注册表、正式归档、模型、求解器、优化器或Web；不提交、
不推送。
