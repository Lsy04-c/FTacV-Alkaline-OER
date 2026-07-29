# V2 Conditional Model Reachability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a reproducible LSODA workflow that classifies whether M0 reaches
each FT2/FT3/FT4/FT8 DC, complex H1–H3 and lock-in H1–H3 target within the
frozen V2 library and stress-test contract.

**Architecture:** Move experimental feature analysis out of the FastAPI module,
add a pure reachability metrics/library module, then add a resumable runner and
an independent archive validator. The runner writes raw component metrics and
provenance; the validator duplicates scoring and classification without
importing the runner or reachability module.

**Tech Stack:** Python 3.13, NumPy, SciPy Sobol QMC, existing `oer_aem` physics
and signal modules, pytest, JSON/JSONL/CSV.

---

### Task 1: Extract the experimental analysis boundary

**Files:**

- Create: `code/python/src/oer_aem/experimental.py`
- Modify: `code/web/backend/main.py`
- Modify: `code/python/scripts/compare_feature_objectives.py`
- Test: `code/python/tests/test_experimental_analysis.py`

- [x] **Step 1: Write a failing core-import test**

```python
def test_analyze_ftacv_trace_is_available_without_fastapi():
    from oer_aem.experimental import analyze_ftacv_trace

    trace = read_strict_experimental_trace(RAW / "ftacv4-ref-1hz.txt")[0]
    result = analyze_ftacv_trace(trace)
    assert result["meta"]["f"] == pytest.approx(1.0, rel=1e-3)
    assert result["meta"]["dE"] == pytest.approx(0.16, rel=5e-3)
    assert len(result["harmonics"]) == 7
```

- [x] **Step 2: Verify RED**

Run:

```bash
.venv/bin/python -m pytest \
  code/python/tests/test_experimental_analysis.py -q
```

Expected: import failure for `oer_aem.experimental`.

- [x] **Step 3: Move the existing analyzer into the core**

Implement:

```python
def analyze_ftacv_trace(trace: ExperimentalTrace) -> dict[str, Any]:
    """Return sampling metadata, DC, H1-H7 and calibration diagnostics."""
```

The function must use the existing formulas unchanged. Add:

```python
def build_experimental_target(
    trace: ExperimentalTrace,
    analysis: Mapping[str, Any],
    config: InversionConfig,
) -> dict[str, Any]:
    """Build DC, complex and lock-in target blocks on config.e_grid."""
```

Make the Web API and `compare_feature_objectives.py` call these functions.

- [x] **Step 4: Verify GREEN and API parity**

Run:

```bash
.venv/bin/python -m pytest \
  code/python/tests/test_experimental_analysis.py \
  code/web/tests/backend -q
```

Expected: all tests pass; the existing API response schema remains unchanged.

### Task 2: Implement pure reachability contracts

**Files:**

- Create: `code/python/src/oer_aem/reachability.py`
- Test: `code/python/tests/test_reachability.py`

- [x] **Step 1: Write failing library and score tests**

```python
def test_sobol_library_is_deterministic_and_covers_bounds():
    first = generate_sobol_library(DIAGNOSTIC_SPECS, 512, seed=29)
    second = generate_sobol_library(DIAGNOSTIC_SPECS, 512, seed=29)
    assert first.sha256 == second.sha256
    assert np.array_equal(first.encoded, second.encoded)
    assert np.all(first.unit.min(axis=0) <= 0.02)
    assert np.all(first.unit.max(axis=0) >= 0.98)


def test_candidate_score_uses_worst_active_component():
    result = score_candidate(
        {"dc_nrmse": 0.05, "global_phase_h1": 0.11},
        {"dc_nrmse": 0.10, "global_phase_h1": 0.10},
    )
    assert result.score == pytest.approx(1.1)
    assert result.passed is False
```

Also cover wrapped phase, near-zero amplitude floors, mask intersections,
non-finite rejection, stress scenario IDs and classification priority.

- [x] **Step 2: Verify RED**

Run:

```bash
.venv/bin/python -m pytest code/python/tests/test_reachability.py -q
```

Expected: import failure for `oer_aem.reachability`.

- [x] **Step 3: Implement the pure API**

Implement these public interfaces:

```python
@dataclass(frozen=True)
class ParameterLibrary:
    unit: np.ndarray
    encoded: np.ndarray
    physical: tuple[dict[str, float], ...]
    sha256: str


@dataclass(frozen=True)
class ScoreResult:
    score: float
    passed: bool
    limiting_metrics: tuple[str, ...]


def generate_sobol_library(
    specs: Sequence[ParamSpec],
    n_candidates: int,
    seed: int,
) -> ParameterLibrary: ...


def build_fixed_stress_scenarios(
    baseline: Mapping[str, float],
) -> tuple[dict[str, Any], ...]: ...


def wrapped_phase_rmse(
    candidate: np.ndarray,
    target: np.ndarray,
    mask: np.ndarray,
) -> float: ...


def masked_nrmse(
    candidate: np.ndarray,
    target: np.ndarray,
    mask: np.ndarray,
) -> float: ...


def score_candidate(
    metrics: Mapping[str, float],
    thresholds: Mapping[str, float],
) -> ScoreResult: ...


def classify_dataset(
    *,
    contract_valid: bool,
    ode_success_fraction: float,
    baseline_reached: bool,
    stress_changed: bool,
    prefix_improvement: float,
) -> str: ...
```

Canonical hashes must use sorted finite JSON or little-endian float64 bytes.

- [x] **Step 4: Verify GREEN**

Run:

```bash
.venv/bin/python -m pytest code/python/tests/test_reachability.py -q
```

Expected: all reachability unit tests pass.

### Task 3: Freeze the machine-readable V2 task

**Files:**

- Create: `config/reachability/v2-conditional-reachability.json`
- Test: `code/python/tests/test_conditional_reachability_runner.py`

- [x] **Step 1: Write a failing task-spec test**

```python
def test_v2_task_spec_freezes_science_inputs():
    spec = json.loads(SPEC.read_text())
    assert spec["candidate_count"] == 512
    assert spec["sobol_seed"] == 29
    assert spec["solver_backend"] == "lsoda"
    assert spec["points_per_cycle"] == 128
    assert spec["feature_grid_size"] == 128
    assert spec["fit_harmonics"] == [1, 2, 3]
    assert len(spec["diagnostic_parameter_specs"]) == 5
    assert len(spec["fixed_stress_scenarios"]) == 16
```

- [x] **Step 2: Verify RED**

Run:

```bash
.venv/bin/python -m pytest \
  code/python/tests/test_conditional_reachability_runner.py -q
```

Expected: missing spec failure.

- [x] **Step 3: Add the complete spec**

The JSON must include:

```json
{
  "schema_version": 1,
  "analysis_id": "v2-conditional-model-reachability",
  "datasets": ["FT2", "FT3", "FT4", "FT8"],
  "candidate_count": 512,
  "sobol_seed": 29,
  "points_per_cycle": 128,
  "feature_grid_size": 128,
  "fit_harmonics": [1, 2, 3],
  "feature_mode": "hybrid",
  "solver_backend": "lsoda",
  "top_stress_candidates": 8,
  "thresholds": {
    "dc_nrmse": 0.1,
    "global_amplitude_relative_error": 0.1,
    "global_phase_error_rad": 0.1,
    "lockin_amplitude_nrmse": 0.1,
    "lockin_phase_rmse_rad": 0.1,
    "lockin_peak_shift_v": 0.025,
    "lockin_valid_fraction_min": 0.5,
    "ode_success_fraction_min": 0.95,
    "prefix_improvement_max": 0.1
  }
}
```

Include all five parameter bounds, eight fixed baselines, sixteen expanded
stress scenarios, and the four raw-data SHA-256 values.

- [x] **Step 4: Verify GREEN**

Run the task-spec test and parse the JSON with `jq -e`.

### Task 4: Build the resumable runner

**Files:**

- Create: `code/python/scripts/run_conditional_reachability.py`
- Test: `code/python/tests/test_conditional_reachability_runner.py`

- [x] **Step 1: Write failing runner tests**

Tests must cover:

```python
def test_smoke_job_plan_contains_all_four_datasets():
    plan = build_job_plan(load_spec(SPEC), smoke=True)
    assert len(plan["base_jobs"]) == 32
    assert {row["dataset_id"] for row in plan["base_jobs"]} == {
        "FT2", "FT3", "FT4", "FT8"
    }


def test_resume_rejects_job_hash_conflict(tmp_path):
    write_jsonl(tmp_path / "base_results.jsonl", [tampered_row])
    with pytest.raises(ValueError, match="job hash"):
        load_resume_state(tmp_path, expected_jobs)
```

Also cover unknown output files, duplicate jobs, partial JSON, ODE failure
records, summary priority and refusal to overwrite scientific output.

- [x] **Step 2: Verify RED**

Run the runner test file. Expected: missing runner module failure.

- [x] **Step 3: Implement runner structure**

The runner must:

1. validate task spec and raw hashes;
2. write `task_spec.json`, `parameter_library.csv` and `targets.json`;
3. generate deterministic base jobs;
4. evaluate each job with
   `OERPhysics.solve_ode_system_detailed`;
5. extract hybrid features once;
6. write one result through a single parent-process JSONL writer;
7. select the lowest-score eight successful base candidates per dataset;
8. evaluate the sixteen OAT scenarios;
9. write `summary.json` and `run_manifest.json`;
10. support `--resume`, `--smoke`, `--workers`, `--output` and
    `--task-spec`.

The runner writes the seven scientific files listed below. It must not write
`acceptance.md`; only the independent validator may issue that file.

CLI:

```bash
.venv/bin/python code/python/scripts/run_conditional_reachability.py \
  --task-spec config/reachability/v2-conditional-reachability.json \
  --smoke --workers 2 --output <new-directory>
```

Smoke must use the first eight Sobol candidates for all four datasets, skip all
stress jobs, and set `scientific_classification=null`. Missing stress jobs are
therefore valid only when the archived task explicitly records smoke mode.

- [x] **Step 4: Verify runner GREEN**

Run runner unit tests, then a real local smoke. Expected files:

```text
task_spec.json
parameter_library.csv
targets.json
base_results.jsonl
stress_results.jsonl
summary.json
run_manifest.json
```

### Task 5: Add the independent validator

**Files:**

- Create: `code/python/scripts/validate_conditional_reachability.py`
- Test: `code/python/tests/test_conditional_reachability_validator.py`

- [x] **Step 1: Write failing validator tests**

Cover a valid synthetic archive and tampering of:

- missing files;
- duplicate jobs;
- task-spec hash;
- parameter-library hash;
- non-finite metrics;
- score formula;
- classification;
- dirty manifest;
- raw-data hash.

Example:

```python
def test_validator_rejects_tampered_dataset_classification(tmp_path):
    archive = write_valid_fixture(tmp_path)
    summary = read_json(archive / "summary.json")
    summary["datasets"]["FT2"]["classification"] = "REACHED"
    write_json(archive / "summary.json", summary)
    result = validate_archive(ROOT, SPEC, archive, rerun_best=False)
    assert result["gate"] == "FAIL_STRUCTURE"
```

- [x] **Step 2: Verify RED**

Run the validator test file. Expected: missing validator module failure.

- [x] **Step 3: Implement independent validation**

The validator must not import:

```text
run_conditional_reachability
oer_aem.reachability
```

It independently reconstructs expected jobs, thresholds, scores, prefix
improvement and classifications from archive records. With `--rerun-best`, it
reruns each dataset's nearest baseline candidate through LSODA and compares
component metrics within `1e-8` relative or absolute tolerance.

For smoke archives, it expects exactly 32 base jobs, zero stress jobs and null
scientific classifications. For formal archives, it expects 4×512 base jobs
and 4×8×16 stress jobs. On completion it writes `acceptance.md`; this is the
eighth formal-directory file and is validator-owned evidence.

- [x] **Step 4: Verify GREEN**

Run validator tests and validate the real smoke archive. Smoke validation must
pass structure while preserving `scientific_classification=null`.

### Task 6: Integrate workflow and verify the implementation

**Files:**

- Create: `config/oer-wf/examples/v2_conditional_reachability_lsoda.yaml`
- Modify: `documents/specifications/oer-wf-workflow-guide.md`
- Test: `config/oer-wf/tests/test_e2e_gates.py`

- [x] **Step 1: Add a failing workflow-spec test**

Assert the task expects all seven scientific files, injects `--output`,
`--workers` and `--resume`, and uses the V2 validator command.

- [x] **Step 2: Add the task specification**

Freeze:

- scientific runner and validator paths;
- expected files;
- smoke overrides;
- `workers=8`;
- one BLAS thread per worker;
- result directory category;
- resume support.

- [x] **Step 3: Run verification**

Run:

```bash
.venv/bin/python -m pytest \
  code/python/tests/test_experimental_analysis.py \
  code/python/tests/test_reachability.py \
  code/python/tests/test_conditional_reachability_runner.py \
  code/python/tests/test_conditional_reachability_validator.py -q
.venv/bin/python -m pytest config/oer-wf/tests -q
.venv/bin/python code/python/scripts/run_tests.py code/python/tests -q
.venv/bin/python code/python/scripts/audit_repository_layout.py
git diff --check
```

All commands must pass before freezing a compute commit.

### Task 7: Smoke and decision

Tasks 1–6 passed local implementation and workflow verification on
2026-07-29. Task 7 remains open until a clean compute commit is frozen.

Frozen formal workload:

- 2048 base jobs: four datasets × 512 Sobol candidates;
- 512 stress jobs: four datasets × eight nearest candidates × 16 scenarios;
- eight workers and one BLAS thread per worker;
- projected wall time about 2.2 hours from the 98.45 s / 32-job smoke;
  reserve 2–4 hours for slow-tail candidates and orchestration;
- no timed monitor unless the project owner requests one;
- infrastructure or contract failure stops validation; a valid scientific
  classification such as unreachable or solver-limited is reported, not
  converted into an infrastructure failure.

**Files:**

- Create after a clean compute commit:
  `results/smoke/conditional_reachability/<commit>/`
- Update after validation:
  `documents/project/WORK_STATUS.md`

- [ ] **Step 1: Run Mac LSODA smoke**

Run 8×4 base jobs with two workers. Record wall time, ODE attempts, fallback
count, files and validator result.

- [ ] **Step 2: Apply the decision**

- If any contract, hash or numerical path fails, stop and preserve evidence.
- If projected Legion wall time is acceptable, prepare one formal 8-worker
  LSODA task.
- If projected wall time is excessive, optimize only orchestration or output
  reuse; do not substitute CN into scientific ranking.

- [ ] **Step 3: Update project state**

Record the smoke as engineering evidence only. Do not mark V2 complete until
the 512-candidate LSODA archive and independent validator pass.
