# CN Screening and LSODA Confirmation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 A6 synthetic recovery 增加可审计的 CN 筛选后端，并按单参数 CN、两参数 CN、LSODA 复核三阶段冻结最终自由参数集。

**Architecture:** `run_synthetic_recovery.py` 接收显式 backend，默认保持 `lsoda`。backend 进入 job、配置、provenance、任务指纹和隔离输出；CN 缺库时直接失败。三份单参数 CN spec 先执行，只有通过冻结 scientific gate 的参数才能组成两参数 CN spec；只有两参数 CN PASS 才能建立同配置 LSODA 复核 spec。

**Tech Stack:** Python 3.11/3.13、Pydantic、Optuna、C++ CN 动态库、SciPy LSODA、pytest、oer-wf、YAML、Git、Legion WSL systemd

---

## 文件结构

- Modify: `code/python/scripts/run_synthetic_recovery.py`
  - 解析 backend，并把它传入每个恢复问题及审计记录。
- Modify: `code/python/tests/test_synthetic_recovery_runner.py`
  - 覆盖默认 LSODA、显式 CN、指纹隔离和 CN 无 fallback。
- Create:
  - `config/oer-wf/examples/a6_recovery_cn_k0_2.yaml`
  - `config/oer-wf/examples/a6_recovery_cn_k0_3.yaml`
  - `config/oer-wf/examples/a6_recovery_cn_G_O.yaml`
  - 三份 Stage 1 正式配置；各自使用独立 task name 和 output directory。
- Modify: `config/oer-wf/tests/test_verify.py`
  - 验证三份配置沿用冻结 gate，且 backend、参数和输出互不混用。
- Modify after execution:
  - `documents/project/WORK_STATUS.md`
  - `documents/corrections/项目纠错.md`
  - 只记录实际验证和结果，不预写 PASS。

## Task 1: Backend CLI and configuration propagation

**Files:**
- Modify: `code/python/scripts/run_synthetic_recovery.py`
- Test: `code/python/tests/test_synthetic_recovery_runner.py`

- [ ] **Step 1: Write failing parser and configuration tests**

Add:

```python
def test_recovery_backend_defaults_to_lsoda(tmp_path):
    args = parse_args([
        "--phase", "formal",
        "--noise-fraction", "0.0015",
        "--output", str(tmp_path),
        "--trials", "1",
    ])
    assert args.backend == "lsoda"
    assert build_config(args, feature_mode="hybrid", seed=17).solver_backend == "lsoda"


def test_recovery_backend_accepts_explicit_cn(tmp_path):
    args = parse_args([
        "--phase", "formal",
        "--noise-fraction", "0.0015",
        "--output", str(tmp_path),
        "--trials", "1",
        "--backend", "cn",
    ])
    assert build_config(args, feature_mode="hybrid", seed=17).solver_backend == "cn"


def test_validate_backend_rejects_unavailable_cn(monkeypatch):
    from oer_aem import cpp_bridge

    monkeypatch.setattr(cpp_bridge, "is_available", lambda: False)
    with pytest.raises(RuntimeError, match="CN backend requested but unavailable"):
        recovery_runner.validate_backend("cn")
```

- [ ] **Step 2: Run tests and verify RED**

Run:

```bash
.venv/bin/python -m pytest -q \
  code/python/tests/test_synthetic_recovery_runner.py \
  -k "backend_defaults or backend_accepts"
```

Expected: FAIL because `args.backend` and `validate_backend()` do not exist and
`build_config()` still hardcodes LSODA.

- [ ] **Step 3: Add the minimal CLI option**

In `parse_args()`:

```python
parser.add_argument(
    "--backend",
    choices=("cn", "lsoda"),
    default="lsoda",
    help="ODE backend; CN is screening-only and LSODA remains the formal default",
)
```

In `build_config()`:

```python
solver_backend=args.backend,
```

Add an early preflight:

```python
def validate_backend(backend: str) -> None:
    if backend != "cn":
        return
    from oer_aem import cpp_bridge

    if not cpp_bridge.is_available():
        raise RuntimeError("CN backend requested but unavailable; fallback is forbidden")
```

Call `validate_backend(args.backend)` in `main()` immediately after
`parse_args()`, before building jobs or creating the output directory. This
preserves failure evidence in the workflow wrapper while avoiding hundreds of
doomed TPE trials.

In `build_recovery_problem()` preserve backend from the job:

```python
args = argparse.Namespace(
    smoke=smoke,
    noise_fraction=job["noise_fraction"],
    workers=1,
    backend=job["backend"],
)
```

- [ ] **Step 4: Put backend into every job**

After building jobs in `build_jobs()`:

```python
for job in jobs:
    job["free_parameters"] = free_parameters
    job["backend"] = args.backend
```

Do not derive backend from environment variables.

- [ ] **Step 5: Run targeted tests and verify GREEN**

Run the Step 2 command.

Expected: all three backend tests PASS.

- [ ] **Step 6: Commit Task 1**

```bash
git add code/python/scripts/run_synthetic_recovery.py \
  code/python/tests/test_synthetic_recovery_runner.py
git diff --cached --check
git commit -m "feat(a6): add explicit recovery backend"
```

## Task 2: Resume fingerprint, provenance, and strict backend isolation

**Files:**
- Modify: `code/python/scripts/run_synthetic_recovery.py`
- Test: `code/python/tests/test_synthetic_recovery_runner.py`

- [ ] **Step 1: Write a failing fingerprint isolation test**

```python
def test_resume_fingerprint_changes_with_backend(monkeypatch, tmp_path):
    common = [
        "--phase", "formal",
        "--noise-fraction", "0.0015",
        "--output", str(tmp_path),
        "--trials", "1",
        "--free-parameters", "k0_2",
        "--max-jobs", "1",
    ]
    lsoda_args = parse_args([*common, "--backend", "lsoda"])
    cn_args = parse_args([*common, "--backend", "cn"])
    lsoda_jobs = build_jobs(lsoda_args)
    cn_jobs = build_jobs(cn_args)
    provenance = {
        "source_commit": "deadbeef",
        "dirty": False,
        "dirty_paths": [],
    }
    lsoda = build_resume_metadata(lsoda_args, lsoda_jobs, provenance, None)
    cn = build_resume_metadata(cn_args, cn_jobs, provenance, None)
    assert lsoda["resume_fingerprint"] != cn["resume_fingerprint"]
    assert lsoda_jobs[0]["backend"] == "lsoda"
    assert cn_jobs[0]["backend"] == "cn"
```

- [ ] **Step 2: Run the fingerprint test and verify RED**

```bash
.venv/bin/python -m pytest -q \
  code/python/tests/test_synthetic_recovery_runner.py::test_resume_fingerprint_changes_with_backend
```

Expected: FAIL until backend reaches the job input hash and fingerprint.

- [ ] **Step 3: Record backend in plan and summary provenance**

Ensure `_job_input_payload()` already serializes `job["backend"]` through the cleaned job and records:

```python
"solver_backend": config.solver_backend,
```

Add an explicit top-level field to the written job plan:

```python
"backend": args.backend,
```

Add to `summary`:

```python
"backend": args.backend,
```

The runner must reject a resumed checkpoint whose `job_input_hash` was generated with the other backend.

- [ ] **Step 4: Write and run a checkpoint mismatch test**

```python
def test_checkpoint_from_other_backend_is_rejected(tmp_path):
    job = {"job_id": "same-job", "trials": 1, "backend": "cn"}
    row = _checkpoint_row(job, "cn-hash")
    path = tmp_path / "results.jsonl"
    path.write_text(json.dumps(row) + "\n")
    with pytest.raises(ValueError, match="job_input_hash mismatch"):
        recovery_runner.load_checkpoint_rows(path, {"same-job": "lsoda-hash"})
```

Use the existing checkpoint-row helper in the test file; do not invent a second checkpoint format.

Run:

```bash
.venv/bin/python -m pytest -q \
  code/python/tests/test_synthetic_recovery_runner.py \
  -k "fingerprint_changes_with_backend or other_backend"
```

Expected: both tests PASS.

- [ ] **Step 5: Verify the existing strict-CN contract**

The repository already contains
`test_cn_backend_does_not_silently_fallback_to_lsoda` in
`code/python/tests/test_inversion.py`. Do not duplicate it. Run it with the new
runner tests:

Run:

```bash
.venv/bin/python -m pytest -q \
  code/python/tests/test_inversion.py::test_cn_backend_does_not_silently_fallback_to_lsoda \
  code/python/tests/test_synthetic_recovery_runner.py \
  -k "backend or fingerprint"
```

Expected: PASS and no LSODA call.

- [ ] **Step 6: Commit Task 2**

```bash
git add code/python/scripts/run_synthetic_recovery.py code/python/tests
git diff --cached --check
git commit -m "fix(a6): isolate recovery checkpoints by backend"
```

## Task 3: Stage 1 CN task specifications

**Files:**
- Create: `config/oer-wf/examples/a6_recovery_cn_k0_2.yaml`
- Create: `config/oer-wf/examples/a6_recovery_cn_k0_3.yaml`
- Create: `config/oer-wf/examples/a6_recovery_cn_G_O.yaml`
- Modify: `config/oer-wf/tests/test_verify.py`

- [ ] **Step 1: Write a failing spec contract test**

```python
@pytest.mark.parametrize(
    ("filename", "parameter", "task_name"),
    [
        ("a6_recovery_cn_k0_2.yaml", "k0_2", "a6_recovery_cn_k0_2"),
        ("a6_recovery_cn_k0_3.yaml", "k0_3", "a6_recovery_cn_k0_3"),
        ("a6_recovery_cn_G_O.yaml", "G_O", "a6_recovery_cn_G_O"),
    ],
)
def test_a6_cn_single_parameter_specs(filename, parameter, task_name):
    path = Path(__file__).resolve().parents[1] / "examples" / filename
    data = yaml.safe_load(path.read_text())
    assert data["task_name"] == task_name
    assert data["workers"] == 8
    assert _arg_value(data["args"], "--backend") == "cn"
    assert _arg_value(data["args"], "--free-parameters") == parameter
    assert _arg_value(data["args"], "--trials") == "100"
    assert data["validator_config"]["recovery_gate"] == {
        "parameter_names": [parameter],
        "require_all_studies_success": True,
        "require_truth_covered_by_seed_range": True,
        "max_boundary_hit_rate": 0.0,
    }
    assert parameter in data["output_dir"]
```

Use a local `_arg_value(args, flag)` test helper that returns the list element
after `flag` and fails if the flag is absent.

- [ ] **Step 2: Run the spec test and verify RED**

```bash
.venv/bin/python -m pytest -q \
  config/oer-wf/tests/test_verify.py::test_a6_cn_single_parameter_specs
```

Expected: FAIL because the three files do not exist.

- [ ] **Step 3: Create the three specs**

Copy the approved scientific fields from
`config/oer-wf/examples/a6_recovery_reduced.yaml`, then change only:

```yaml
task_name: "a6_recovery_cn_k0_2"
description: "Gate A6 Stage 1 CN screen: k0_2"
args:
  # preserve phase, noise fraction, noise evidence
  - "--free-parameters"
  - "k0_2"
  - "--trials"
  - "100"
  - "--backend"
  - "cn"
workers: 8
output_dir: "results/a6_recovery_cn_k0_2"
validator_config:
  recovery_gate:
    parameter_names: ["k0_2"]
    require_all_studies_success: true
    require_truth_covered_by_seed_range: true
    max_boundary_hit_rate: 0.0
```

Repeat exactly for `k0_3` and `G_O`. Each task must have a unique task name and
output directory. Initially set `commit` to the full source commit returned by
`git rev-parse HEAD`. After the implementation commit is created, update all
three specs to that exact full commit before deployment and commit the pin
separately.

- [ ] **Step 4: Run the spec and model tests**

```bash
.venv/bin/python -m pytest -q \
  config/oer-wf/tests/test_verify.py \
  config/oer-wf/tests/test_prepare.py \
  config/oer-wf/tests/test_run.py \
  config/oer-wf/tests/test_smoke.py
```

Expected: all PASS.

- [ ] **Step 5: Commit Task 3**

```bash
git add config/oer-wf/examples/a6_recovery_cn_*.yaml \
  config/oer-wf/tests/test_verify.py
git diff --cached --check
git commit -m "feat(a6): add single-parameter CN screening specs"
```

## Task 4: Local smoke, full regression, and review

**Files:**
- No product file changes expected.

- [ ] **Step 1: Run one-job CN smoke locally**

Use a temporary output outside tracked scientific results:

```bash
.venv/bin/python code/python/scripts/run_synthetic_recovery.py \
  --phase formal \
  --noise-fraction 0.001495726085983469 \
  --free-parameters k0_2 \
  --trials 1 \
  --backend cn \
  --workers 1 \
  --smoke \
  --max-jobs 1 \
  --output /tmp/oer-a6-cn-smoke
```

Expected:

- process exit code 0;
- `summary.json` reports `backend=cn`;
- `results.jsonl` contains one unique job with
  `configuration.solver_backend=cn`;
- no LSODA fallback record;
- all JSON values finite.

If the Mac CN library is not at the path expected by the current loader, report
an infrastructure failure. Do not change to LSODA to make the smoke pass.

- [ ] **Step 2: Run all local tests**

```bash
.venv/bin/python -m pytest -q config/oer-wf/tests
.venv/bin/python code/python/scripts/run_tests.py code/python/tests -q
```

Expected: both suites PASS.

- [ ] **Step 3: Run static integrity checks**

```bash
.venv/bin/python -m compileall -q \
  config/oer-wf/oer_wf \
  code/python/scripts/run_synthetic_recovery.py
git diff --check
git status --short
```

Expected: compilation and diff check succeed; only planned files are modified.

- [ ] **Step 4: Dispatch reviewer**

Reviewer checks:

- explicit CN never falls back;
- backend changes the resume hash;
- default remains LSODA;
- specs preserve trials, modes, truths, noise and seeds;
- no scientific threshold changed;
- output directories are unique;
- no credentials or local environment files entered Git.

Fix blocking findings and rerun Steps 2–3.

## Task 5: Freeze commit, push, and deploy Legion

**Files:**
- Modify: three Stage 1 YAML specs to pin the final full commit.

- [ ] **Step 1: Commit verified implementation**

Stage only project code, tests, specs, and approved docs. Review:

```bash
git diff --cached --check
git diff --cached --stat
git status --short
```

Use a Conventional Commit message. Do not include
`/Users/liushiyu/gpt/本机环境配置.md`, `.codex/`, temporary smoke outputs, or
Mac dynamic libraries.

- [ ] **Step 2: Pin specs to the implementation commit**

Set each spec `commit` to the full 40-character implementation commit. Commit:

```bash
git add config/oer-wf/examples/a6_recovery_cn_*.yaml
git commit -m "chore(a6): pin CN screening specs"
```

- [ ] **Step 3: Push the project branch**

```bash
git push origin codex/reclassify-project
```

Expected: remote branch advances to the spec-pin commit.

- [ ] **Step 4: Perform read-only Legion checks**

First read `/Users/liushiyu/gpt/本机环境配置.md`, then verify:

```bash
ssh legion "whoami && systemctl is-system-running"
ssh legion "test -f /home/lsy/OER-FTAcV/cpp/liboercn.so && echo CN_OK"
```

Expected: user `lsy`, systemd `running` or `degraded`, and `CN_OK`.

- [ ] **Step 5: Fetch and create a frozen worktree**

Follow the existing environment document. Fetch the pushed branch and create a
new commit-specific worktree. Do not clean or overwrite
`/home/lsy/OER-FTAcV`.

- [ ] **Step 6: Verify remote code and tests**

Confirm the imported `oer_wf` path and run the targeted backend/spec tests in
the frozen worktree. Do not reinstall NumPy.

## Task 6: Execute Stage 1 and enforce the pruning gate

**Files:**
- Results are generated remotely and later synchronized to the Mac archive.
- Modify after evidence exists:
  - `documents/project/WORK_STATUS.md`
  - `documents/corrections/项目纠错.md`

- [ ] **Step 1: Run smoke for all three specs**

Run the exact commands below:

```bash
wf prepare config/oer-wf/examples/a6_recovery_cn_k0_2.yaml
wf smoke config/oer-wf/examples/a6_recovery_cn_k0_2.yaml
wf prepare config/oer-wf/examples/a6_recovery_cn_k0_3.yaml
wf smoke config/oer-wf/examples/a6_recovery_cn_k0_3.yaml
wf prepare config/oer-wf/examples/a6_recovery_cn_G_O.yaml
wf smoke config/oer-wf/examples/a6_recovery_cn_G_O.yaml
```

Required smoke evidence:

- snapshot contract exists;
- STATUS is `SUCCESS`;
- backend is `cn`;
- one job completes with finite values;
- solver records no LSODA fallback.

Any smoke failure stops that parameter's formal run.

- [ ] **Step 2: Run Stage 1 formal jobs**

Start only the specs whose smoke passed. Use `wf run` and the existing systemd
workflow. Do not add timed monitoring unless the user requests it.

- [ ] **Step 3: Sync and verify each archive**

For each completed task, replace `COMMIT7` with its actual seven-character
commit prefix:

```bash
wf status COMMIT7/a6_recovery_cn_k0_2
wf sync COMMIT7/a6_recovery_cn_k0_2
wf verify COMMIT7/a6_recovery_cn_k0_2
wf status COMMIT7/a6_recovery_cn_k0_3
wf sync COMMIT7/a6_recovery_cn_k0_3
wf verify COMMIT7/a6_recovery_cn_k0_3
wf status COMMIT7/a6_recovery_cn_G_O
wf sync COMMIT7/a6_recovery_cn_G_O
wf verify COMMIT7/a6_recovery_cn_G_O
```

`wf verify` must load `task_spec.snapshot.yaml` and apply the single-parameter
`recovery_gate`.

- [ ] **Step 4: Apply pruning without reinterpretation**

For each parameter:

- infrastructure or numerical FAIL: stop and diagnose; do not call it a
  scientific FAIL;
- scientific FAIL: record the frozen gate failure and prune every pair
  containing that parameter;
- scientific PASS: mark the parameter eligible for pairing, but do not freeze
  it as a final result.

- [ ] **Step 5: Update progress with actual evidence**

Use `editor` to add concise evidence to `WORK_STATUS.md`; main agent verifies
counts, hashes and fail types. Use `tester` for archive integrity. Commit and
push only after verification.

## Task 7: Generate Stage 2 and Stage 3 specs after observed gates

**Files:**
- Create only for eligible pairs:
  - `config/oer-wf/examples/a6_recovery_cn_k0_2_k0_3.yaml`
  - `config/oer-wf/examples/a6_recovery_cn_k0_2_G_O.yaml`
  - `config/oer-wf/examples/a6_recovery_cn_k0_3_G_O.yaml`
  - `config/oer-wf/examples/a6_recovery_lsoda_k0_2_k0_3.yaml`
  - `config/oer-wf/examples/a6_recovery_lsoda_k0_2_G_O.yaml`
  - `config/oer-wf/examples/a6_recovery_lsoda_k0_3_G_O.yaml`
- Test: `config/oer-wf/tests/test_verify.py`

- [ ] **Step 1: Create CN pair specs only from Stage 1 PASS parameters**

Use the same scientific protocol and gates. Set `parameter_names` to the exact
pair. Keep `--backend cn`, 100 trials/job and a unique output directory.

- [ ] **Step 2: Test, review, commit, push, smoke, and run each CN pair**

Repeat Tasks 3–6. A CN pair PASS only permits LSODA confirmation.

- [ ] **Step 3: Create LSODA specs only for CN pair PASS results**

For each eligible pair, copy the corresponding CN spec and change only backend
plus the metadata required to distinguish runs. Example for `k0_2+k0_3`:

```yaml
task_name: "a6_recovery_lsoda_k0_2_k0_3"
description: "Gate A6 Stage 3 LSODA confirmation: k0_2+k0_3"
args:
  # All other arguments remain byte-for-byte equal to the CN spec.
  - "--backend"
  - "lsoda"
output_dir: "results/a6_recovery_lsoda_k0_2_k0_3"
```

The test must compare normalized CN and LSODA specs after removing only
`task_name`, `description`, `output_dir`, `commit`, and backend value. Any other
difference blocks execution.

- [ ] **Step 4: Run LSODA confirmation**

Use the same smoke, formal, sync and verify workflow. Only an LSODA archive
that passes structure, numerical, provenance and the frozen scientific gate
can support freezing the pair.

- [ ] **Step 5: Close A6 or record FAIL**

Update project progress with:

- exact commit and task snapshot;
- backend;
- job, truth, noise, seed and trial counts;
- coverage by parameter;
- boundary-hit rates;
- infrastructure, numerical and scientific status;
- explicit freeze or rejection decision.

Do not proceed to real-data formal TPE unless at least one LSODA-confirmed
parameter set passes the frozen gate.
