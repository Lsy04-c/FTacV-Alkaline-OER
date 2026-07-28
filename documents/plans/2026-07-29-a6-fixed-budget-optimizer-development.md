# Gate A6 Fixed-Budget Optimizer Development Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and formally evaluate the preregistered 100-call TPE,
Sobol-pattern, and fixed-budget differential-evolution methods on the three-study
Gate A6 development set without truth leakage.

**Architecture:** Put optimizer algorithms in a truth-agnostic core module that
only sees a unit-cube objective, dimension, budget, and seed. Put synthetic
target construction, post-run truth diagnostics, checkpointing, and candidate
selection in a separate benchmark protocol and runner. Add a task-specific
workflow validator so execution PASS and development scientific PASS remain
distinct.

**Tech Stack:** Python 3.11/3.13, NumPy, SciPy QMC, Optuna, pytest, JSONL,
oer-wf, C++ CN through the existing ctypes bridge.

---

## Scope boundary

This plan ends after the three-study development gate:

- 3 parameter pairs × 3 optimizers = 9 jobs;
- 100 optimization calls per job;
- one post-run truth diagnostic per job;
- one frozen `selection.json`.

If neither replacement optimizer passes, execution stops and records failure.
If one passes, the 51-study locked confirmation phase gets a separate plan
pinned to the selected optimizer and implementation commit.

## File map

| File | Responsibility |
|---|---|
| `code/python/src/oer_aem/optimizers.py` | Strict budget wrapper and three truth-agnostic optimizer adapters |
| `code/python/src/oer_aem/optimizer_benchmark.py` | Development job matrix, result metrics, selection, hashes and summaries |
| `code/python/scripts/run_optimizer_benchmark.py` | CLI, CN target construction, multiprocessing, atomic checkpoint/resume and artifacts |
| `code/python/tests/test_optimizers.py` | Exact-budget, determinism, bounds and failure tests |
| `code/python/tests/test_optimizer_benchmark.py` | Job matrix, truth isolation, selection and runner artifact tests |
| `config/oer-wf/oer_wf/validators/optimizer_benchmark_gate.py` | Archive structure and scientific selection validation |
| `config/oer-wf/tests/test_optimizer_benchmark_gate.py` | Validator classification and anti-drift tests |
| `config/oer-wf/examples/a6_optimizer_development_cn.yaml` | Frozen Legion development task |

## Task 1: Strict optimizer contract and TPE baseline

**Files:**

- Create: `code/python/src/oer_aem/optimizers.py`
- Create: `code/python/tests/test_optimizers.py`

- [ ] **Step 1: Write failing contract tests**

Add:

```python
import numpy as np
import pytest

from oer_aem.optimizers import BudgetedObjective, run_optimizer


def sphere(z):
    return float(np.sum((np.asarray(z) - 0.25) ** 2))


def test_tpe_uses_exact_budget_and_is_deterministic():
    first = run_optimizer("tpe", sphere, dimension=2, budget=100, seed=7)
    second = run_optimizer("tpe", sphere, dimension=2, budget=100, seed=7)
    assert first.optimization_calls == 100
    assert len(first.evaluations) == 100
    assert first.evaluations == second.evaluations
    assert np.allclose(first.best_unit, second.best_unit)


def test_budgeted_objective_rejects_call_101():
    wrapped = BudgetedObjective(sphere, dimension=2, budget=100)
    for _ in range(100):
        wrapped([0.5, 0.5])
    with pytest.raises(RuntimeError, match="objective budget exhausted"):
        wrapped([0.5, 0.5])


def test_nonfinite_call_is_counted_then_fails():
    wrapped = BudgetedObjective(lambda z: float("nan"), dimension=2, budget=100)
    with pytest.raises(FloatingPointError, match="non-finite objective"):
        wrapped([0.5, 0.5])
    assert wrapped.calls == 1
    assert wrapped.evaluations[0].error == "non-finite objective"
```

- [ ] **Step 2: Run the tests and verify RED**

Run:

```bash
.venv/bin/pytest -q code/python/tests/test_optimizers.py
```

Expected: collection fails because `oer_aem.optimizers` does not exist.

- [ ] **Step 3: Implement the contract and TPE adapter**

Create these public types and signatures:

```python
from dataclasses import dataclass
from typing import Callable, Sequence

import numpy as np


@dataclass(frozen=True)
class EvaluationRecord:
    index: int
    unit: tuple[float, ...]
    loss: float | None
    error: str | None


@dataclass(frozen=True)
class OptimizerResult:
    optimizer: str
    best_unit: tuple[float, ...]
    best_loss: float
    optimization_calls: int
    evaluations: tuple[EvaluationRecord, ...]
    termination_reason: str


class BudgetedObjective:
    def __init__(
        self,
        objective: Callable[[np.ndarray], float],
        *,
        dimension: int,
        budget: int,
    ) -> None:
        if dimension < 1 or budget < 1:
            raise ValueError("dimension and budget must be positive")
        self.objective = objective
        self.dimension = dimension
        self.budget = budget
        self.calls = 0
        self.evaluations: list[EvaluationRecord] = []

    def __call__(self, unit: Sequence[float]) -> float:
        if self.calls >= self.budget:
            raise RuntimeError("objective budget exhausted")
        point = np.asarray(unit, dtype=float).reshape(-1)
        if point.size != self.dimension:
            raise ValueError("unit coordinate dimension mismatch")
        if (
            not np.all(np.isfinite(point))
            or np.any(point < 0.0)
            or np.any(point > 1.0)
        ):
            raise ValueError("unit coordinates must be finite and in [0,1]")
        self.calls += 1
        try:
            loss = float(self.objective(point))
            if not np.isfinite(loss):
                raise FloatingPointError("non-finite objective")
        except Exception as exc:
            self.evaluations.append(EvaluationRecord(
                index=self.calls,
                unit=tuple(map(float, point)),
                loss=None,
                error=str(exc),
            ))
            raise
        self.evaluations.append(EvaluationRecord(
            index=self.calls,
            unit=tuple(map(float, point)),
            loss=loss,
            error=None,
        ))
        return loss


def run_optimizer(
    name: str,
    objective: Callable[[np.ndarray], float],
    *,
    dimension: int,
    budget: int,
    seed: int,
) -> OptimizerResult:
    if name != "tpe":
        raise ValueError(f"unknown optimizer: {name}")
    wrapped = BudgetedObjective(
        objective, dimension=dimension, budget=budget
    )
    return _run_tpe(
        wrapped, dimension=dimension, budget=budget, seed=seed
    )
```

`BudgetedObjective.__call__` must:

1. reject calls after `budget`;
2. validate finite coordinates and `[0,1]` bounds;
3. increment the call counter before invoking the objective;
4. append one record for success, exception, or non-finite loss;
5. re-raise unexpected exceptions and raise `FloatingPointError` for non-finite
   loss.

The TPE adapter must use `TPESampler(seed=seed, n_startup_trials=10)`, suggest
`z_0` through `z_{dimension-1}`, enqueue nothing, call
`study.optimize(optuna_objective, n_trials=budget)`, and
return the best recorded unit point.

- [ ] **Step 4: Verify GREEN**

Run:

```bash
.venv/bin/pytest -q code/python/tests/test_optimizers.py
```

Expected: all Task 1 tests pass.

- [ ] **Step 5: Commit**

```bash
git add code/python/src/oer_aem/optimizers.py \
  code/python/tests/test_optimizers.py
git commit -m "feat(a6): add strict budgeted optimizer contract"
```

## Task 2: Sobol-pattern adapter

**Files:**

- Modify: `code/python/src/oer_aem/optimizers.py`
- Modify: `code/python/tests/test_optimizers.py`

- [ ] **Step 1: Write failing Sobol-pattern tests**

Add:

```python
def test_sobol_pattern_uses_64_global_and_36_local_calls():
    result = run_optimizer(
        "sobol_pattern", sphere, dimension=2, budget=100, seed=7
    )
    assert result.optimization_calls == 100
    assert len(result.evaluations) == 100
    assert result.best_loss < 1e-3
    assert all(
        0.0 <= coordinate <= 1.0
        for row in result.evaluations
        for coordinate in row.unit
    )


def test_sobol_pattern_same_seed_replays_exact_trace():
    left = run_optimizer(
        "sobol_pattern", sphere, dimension=2, budget=100, seed=17
    )
    right = run_optimizer(
        "sobol_pattern", sphere, dimension=2, budget=100, seed=17
    )
    assert left.evaluations == right.evaluations
```

- [ ] **Step 2: Verify RED**

Run:

```bash
.venv/bin/pytest -q code/python/tests/test_optimizers.py -k sobol
```

Expected: FAIL because `sobol_pattern` is unknown.

- [ ] **Step 3: Implement the frozen algorithm**

Use:

```python
sampler = scipy.stats.qmc.Sobol(d=dimension, scramble=True, seed=seed)
global_points = sampler.random_base2(m=6)  # exactly 64
```

Evaluate all 64 points. Then implement the frozen pattern rules from
`documents/specifications/2026-07-29-a6-fixed-budget-optimizer-benchmark-design.md`:
step `1/8`, ordered negative/positive coordinate moves, improvement keeps the
step, no improvement halves it, step below `1/1024` restarts from the next
ranked Sobol point. Cache coordinates as exact float tuples. If a candidate is
cached, advance without calling the objective; if no local candidate is new,
draw subsequent Sobol points until the wrapper reaches 100 calls.

Reject any budget other than 100 in this version:

```python
if budget != 100:
    raise ValueError("sobol_pattern requires frozen budget=100")
```

- [ ] **Step 4: Verify GREEN**

Run:

```bash
.venv/bin/pytest -q code/python/tests/test_optimizers.py
```

Expected: Task 1 and Task 2 tests pass.

- [ ] **Step 5: Commit**

```bash
git add code/python/src/oer_aem/optimizers.py \
  code/python/tests/test_optimizers.py
git commit -m "feat(a6): add Sobol pattern optimizer"
```

## Task 3: Fixed-budget differential evolution

**Files:**

- Modify: `code/python/src/oer_aem/optimizers.py`
- Modify: `code/python/tests/test_optimizers.py`

- [ ] **Step 1: Write failing DE tests**

Add:

```python
def test_de_fixed_uses_20_points_and_four_generations():
    result = run_optimizer("de_fixed", sphere, dimension=2, budget=100, seed=7)
    assert result.optimization_calls == 100
    assert len(result.evaluations) == 100
    assert result.best_loss < 0.02


def test_de_fixed_rejects_non_two_dimensional_problem():
    with pytest.raises(ValueError, match="dimension=2"):
        run_optimizer("de_fixed", sphere, dimension=3, budget=100, seed=7)


def test_de_reflection_stays_inside_unit_cube():
    result = run_optimizer(
        "de_fixed",
        lambda z: -float(np.sum(np.abs(np.asarray(z) - 0.5))),
        dimension=2,
        budget=100,
        seed=27,
    )
    assert all(
        0.0 <= coordinate <= 1.0
        for row in result.evaluations
        for coordinate in row.unit
    )
```

- [ ] **Step 2: Verify RED**

Run:

```bash
.venv/bin/pytest -q code/python/tests/test_optimizers.py -k de_
```

Expected: FAIL because `de_fixed` is unknown.

- [ ] **Step 3: Implement DE/rand/1/bin**

Use `np.random.default_rng(seed)`, 20 initial uniform points, `F=0.8`,
`CR=0.7`, and four generations. For target index `i`, sample three distinct
indices excluding `i`, compute `a + F*(b-c)`, reflect each coordinate with:

```python
value = abs(value) % 2.0
value = 2.0 - value if value > 1.0 else value
```

Choose a forced crossover dimension with the same RNG. Evaluate one trial for
each population member and replace the target when trial loss is no larger.
Reject `dimension != 2` or `budget != 100`.

- [ ] **Step 4: Verify GREEN**

Run:

```bash
.venv/bin/pytest -q code/python/tests/test_optimizers.py
```

Expected: all optimizer tests pass.

- [ ] **Step 5: Commit**

```bash
git add code/python/src/oer_aem/optimizers.py \
  code/python/tests/test_optimizers.py
git commit -m "feat(a6): add fixed-budget differential evolution"
```

## Task 4: Benchmark protocol and truth-isolated job execution

**Files:**

- Create: `code/python/src/oer_aem/optimizer_benchmark.py`
- Create: `code/python/tests/test_optimizer_benchmark.py`

- [ ] **Step 1: Write failing protocol tests**

Add:

```python
from oer_aem.optimizer_benchmark import (
    DEVELOPMENT_OPTIMIZERS,
    build_development_jobs,
    select_development_candidate,
)


def test_development_matrix_is_preregistered():
    jobs = build_development_jobs(noise_fraction=0.001495726085983469)
    assert len(jobs) == 9
    assert {job["optimizer"] for job in jobs} == {
        "tpe", "sobol_pattern", "de_fixed"
    }
    assert {job["truth_id"] for job in jobs} == {"center"}
    assert {job["noise_fraction"] for job in jobs} == {0.0}
    assert {job["seed"] for job in jobs} == {7}
    assert {tuple(job["free_parameters"]) for job in jobs} == {
        ("k0_2", "k0_3"),
        ("k0_2", "G_O"),
        ("k0_3", "G_O"),
    }


def test_selection_requires_all_three_pairs_to_pass():
    rows = development_rows(
        sobol_errors=[0.01, 0.02, 0.03],
        de_errors=[0.01, 0.02, 0.06],
    )
    selection = select_development_candidate(rows)
    assert selection["selected_optimizer"] == "sobol_pattern"
    assert selection["eligible_optimizers"] == ["sobol_pattern"]


def test_no_candidate_stops_confirmation():
    rows = development_rows(
        sobol_errors=[0.06, 0.02, 0.03],
        de_errors=[0.01, 0.07, 0.03],
    )
    selection = select_development_candidate(rows)
    assert selection["selected_optimizer"] is None
    assert selection["scientific_gate_passed"] is False
    assert selection["next_action"] == "STOP"
```

The local `development_rows` test helper must create all nine rows, including
TPE, with finite objectives, `optimization_calls=100`, `n_ode_fail=0`, no
boundary hits, and two parameter metrics per pair.

- [ ] **Step 2: Verify RED**

Run:

```bash
.venv/bin/pytest -q code/python/tests/test_optimizer_benchmark.py
```

Expected: collection fails because the protocol module does not exist.

- [ ] **Step 3: Implement job construction and selection**

Public constants:

```python
DEVELOPMENT_OPTIMIZERS = ("tpe", "sobol_pattern", "de_fixed")
DEVELOPMENT_PAIRS = (
    ("k0_2", "k0_3"),
    ("k0_2", "G_O"),
    ("k0_3", "G_O"),
)
DEVELOPMENT_TRUTH_ID = "center"
DEVELOPMENT_NOISE = 0.0
DEVELOPMENT_SEED = 7
OPTIMIZATION_BUDGET = 100
```

`build_development_jobs` must derive truth parameters and target seed through
the existing `truth_library` and recovery protocol. Job IDs must include pair,
optimizer, truth, noise, seed, and budget. Job ordering must use parameter pair
as the outer loop and `DEVELOPMENT_OPTIMIZERS` as the inner loop so the first
three jobs exercise all algorithms on `k0_2,k0_3`.

`select_development_candidate` must:

1. require exactly nine unique jobs and the frozen matrix;
2. validate 100 calls, finite values, zero ODE failures and no boundary hits;
3. mark a replacement eligible only when all six parameter errors across its
   three pair jobs are `<=0.05`;
4. rank eligible replacements by worst error, median error, maximum objective
   regret, then fixed `sobol_pattern` preference;
5. emit explicit per-optimizer metrics, selected optimizer or `null`,
   `scientific_gate_passed`, and `next_action`.

- [ ] **Step 4: Add a truth-isolation execution test**

Define the job executor signature:

```python
def run_benchmark_job(
    job: Mapping[str, Any],
    *,
    objective_factory: Callable[..., tuple[Callable, Callable]],
) -> dict[str, Any]:
```

The factory returns separate optimization and post-run truth callables. Test
that the optimizer callable receives only unit coordinates, is called exactly
100 times, and the truth callable is invoked only after optimizer completion.

- [ ] **Step 5: Verify GREEN**

Run:

```bash
.venv/bin/pytest -q code/python/tests/test_optimizer_benchmark.py
```

Expected: all protocol and isolation tests pass.

- [ ] **Step 6: Commit**

```bash
git add code/python/src/oer_aem/optimizer_benchmark.py \
  code/python/tests/test_optimizer_benchmark.py
git commit -m "feat(a6): add optimizer benchmark protocol"
```

## Task 5: Incremental benchmark runner and resume

**Files:**

- Create: `code/python/scripts/run_optimizer_benchmark.py`
- Modify: `code/python/tests/test_optimizer_benchmark.py`

- [ ] **Step 1: Write failing runner tests**

Add tests that invoke `main` with a monkeypatched `run_benchmark_job` and
temporary output:

```python
def test_runner_writes_complete_development_artifacts(monkeypatch, tmp_path):
    patch_successful_jobs(monkeypatch)
    main([
        "--phase", "development",
        "--backend", "cn",
        "--budget", "100",
        "--workers", "1",
        "--output", str(tmp_path / "run"),
    ])
    assert set(path.name for path in (tmp_path / "run").iterdir()) == {
        "benchmark_plan.json",
        "results.jsonl",
        "evaluations.jsonl",
        "summary.json",
        "selection.json",
    }
    assert len(read_jsonl(tmp_path / "run" / "results.jsonl")) == 9
    assert len(read_jsonl(tmp_path / "run" / "evaluations.jsonl")) == 900


def test_resume_reuses_only_matching_job_hashes(monkeypatch, tmp_path):
    output = tmp_path / "resume"
    patch_successful_jobs(monkeypatch)
    main(base_args(output))
    calls = patch_successful_jobs(monkeypatch)
    main([*base_args(output), "--resume"])
    assert calls == []


def test_resume_rejects_optimizer_or_budget_drift(monkeypatch, tmp_path):
    output = tmp_path / "resume"
    patch_successful_jobs(monkeypatch)
    main(base_args(output))
    plan = json.loads((output / "benchmark_plan.json").read_text())
    plan["budget"] = 101
    (output / "benchmark_plan.json").write_text(json.dumps(plan))
    with pytest.raises(ValueError, match="resume_fingerprint mismatch"):
        main([*base_args(output), "--resume"])
```

- [ ] **Step 2: Verify RED**

Run:

```bash
.venv/bin/pytest -q code/python/tests/test_optimizer_benchmark.py -k runner
```

Expected: FAIL because the runner module and artifacts do not exist.

- [ ] **Step 3: Implement CLI and artifacts**

CLI:

```text
--phase development
--backend cn|lsoda
--budget 100
--noise-evidence PATH
--workers N
--output PATH
--smoke
--max-jobs N
--resume
```

Formal development must reject backend other than CN and budget other than 100.
Smoke uses `--max-jobs 3`, preserves the 100-call budget, and reduces only the
forward grid to 256 points through `--smoke`. The first three jobs cover all
algorithms on one pair. It must label itself `is_smoke=true` and cannot produce
a scientific selection PASS.

Use the existing recovery configuration:

```python
InversionConfig(
    n_points=256 if smoke else 8192,
    points_per_cycle=32,
    feature_grid_size=128,
    fit_harmonics=(1, 2, 3),
    feature_mode="hybrid",
    solver_backend=backend,
    seed=job["seed"],
    fixed_params=tuple(
        (name, float(value))
        for name, value in job["truth_params"].items()
        if name not in set(job["free_parameters"])
    ),
)
```

For each job:

1. construct the synthetic target;
2. create `InversionObjective`;
3. expose `unit_objective(z)` that denormalizes through the free specs;
4. call `run_optimizer`;
5. decode best parameters and compute recovery metrics;
6. after optimizer return, evaluate truth once with a separate objective
   instance;
7. return the job result plus all 100 evaluation records.

The parent process must atomically replace `results.jsonl` and
`evaluations.jsonl` after each completed job. Job hashes and the run fingerprint
must include source commit, dirty state, backend, full algorithm constants,
budget, target seed, pair, truth/noise/seed, smoke state and scientific config.

- [ ] **Step 4: Implement summary and selection**

`summary.json` must separate:

```json
{
  "execution_passed": true,
  "scientific_gate_passed": false,
  "job_count": 9,
  "completed_jobs": 9,
  "optimization_calls": 900,
  "diagnostic_truth_calls": 9
}
```

Formal development writes `selection.json` from
`select_development_candidate`. Smoke writes:

```json
{
  "scientific_gate_passed": null,
  "selected_optimizer": null,
  "next_action": "RUN_FORMAL_DEVELOPMENT"
}
```

- [ ] **Step 5: Verify GREEN and full Python regression**

Run:

```bash
.venv/bin/pytest -q code/python/tests/test_optimizer_benchmark.py
.venv/bin/pytest -q code/python/tests
```

Expected: benchmark tests and the full Python suite pass.

- [ ] **Step 6: Commit**

```bash
git add code/python/scripts/run_optimizer_benchmark.py \
  code/python/tests/test_optimizer_benchmark.py
git commit -m "feat(a6): add resumable optimizer benchmark runner"
```

## Task 6: Workflow validator and frozen development spec

**Files:**

- Create: `config/oer-wf/oer_wf/validators/optimizer_benchmark_gate.py`
- Modify: `config/oer-wf/oer_wf/validators/__init__.py`
- Modify: `config/oer-wf/oer_wf/commands/verify.py`
- Create: `config/oer-wf/tests/test_optimizer_benchmark_gate.py`
- Create after the implementation commit is known:
  `config/oer-wf/examples/a6_optimizer_development_cn.yaml`
- Modify: `config/oer-wf/tests/test_verify.py`

- [ ] **Step 1: Write failing validator tests**

Create fixture archives with nine job rows, 900 evaluation rows, summary and
selection. Cover these exact mutations and assertions:

1. `test_gate_passes_one_eligible_replacement` keeps `sobol_pattern` below
   0.05 for every pair and asserts
   `scientific:optimizer_benchmark_gate` passes.
2. `test_gate_fails_when_both_replacements_miss_one_pair` changes one pair
   error for each replacement to 0.051 and asserts scientific FAIL.
3. `test_gate_rejects_99_or_101_calls_as_structure_failure` parameterizes
   call counts 99 and 101 and asserts structure FAIL.
4. `test_gate_rejects_truth_diagnostic_before_last_optimization_call` sets
   the diagnostic sequence index to 99 and asserts structure FAIL.
5. `test_gate_rejects_threshold_drift` changes `max_parameter_error` to
   0.051 and asserts config structure FAIL.
6. `test_verify_classifies_selection_failure_as_scientific` runs
   `run_verify` on a complete failing archive and asserts
   `fail_type.value == "scientific"`.

The frozen validator config is:

```yaml
gate_version: 1
phase: development
optimizers: [tpe, sobol_pattern, de_fixed]
parameter_pairs:
  - [k0_2, k0_3]
  - [k0_2, G_O]
  - [k0_3, G_O]
truth_id: center
noise_fraction: 0.0
seed: 7
optimization_budget: 100
max_parameter_error: 0.05
require_zero_ode_failures: true
require_zero_boundary_hits: true
```

- [ ] **Step 2: Verify RED**

Run:

```bash
.venv/bin/pytest -q config/oer-wf/tests/test_optimizer_benchmark_gate.py
```

Expected: collection fails because the validator does not exist.

- [ ] **Step 3: Implement and register the validator**

The validator must independently reload all JSON/JSONL files, reject
non-standard or non-finite JSON, verify exact job/evaluation matrices, recompute
per-optimizer eligibility and ranking, and compare the result byte-for-byte in
meaning with `selection.json`.

Return:

- `structure:optimizer_benchmark_gate` for missing, duplicate, mismatched, drifted
  or truth-order-invalid evidence;
- `numerical:optimizer_benchmark_gate` for non-finite values;
- `scientific:optimizer_benchmark_gate` when evidence is valid but no replacement
  passes.

Register it in `_VALIDATOR_MAP`. Generalize verify dispatch so every
task-specific validator receives:

```python
fn(
    archive,
    expected,
    validator_config=validator_config.get(name) or {},
)
```

while generic validators retain their current signatures.

- [ ] **Step 4: Verify GREEN**

Run:

```bash
.venv/bin/pytest -q config/oer-wf/tests/test_optimizer_benchmark_gate.py \
  config/oer-wf/tests/test_verify.py
```

Expected: all validator and verify tests pass.

- [ ] **Step 5: Commit implementation before pinning the spec**

```bash
git add config/oer-wf/oer_wf/validators/optimizer_benchmark_gate.py \
  config/oer-wf/oer_wf/validators/__init__.py \
  config/oer-wf/oer_wf/commands/verify.py \
  config/oer-wf/tests/test_optimizer_benchmark_gate.py \
  config/oer-wf/tests/test_verify.py
git commit -m "feat(workflow): validate optimizer development gates"
```

- [ ] **Step 6: Create and test the task spec**

After the implementation commit exists, write its full hash into:

`config/oer-wf/examples/a6_optimizer_development_cn.yaml`

The spec must run:

```yaml
script: code/python/scripts/run_optimizer_benchmark.py
args:
  - --phase
  - development
  - --backend
  - cn
  - --budget
  - "100"
  - --noise-evidence
  - results/formal/identifiability/gate-a6-d9299f8/noise_evidence.json
workers: 8
output_dir: results/a6_optimizer_development_cn
smoke:
  enabled: true
  args: [--smoke]
  overrides:
    max_jobs: 3
expected_files:
  - benchmark_plan.json
  - results.jsonl
  - evaluations.jsonl
  - summary.json
  - selection.json
  - STATUS.json
validators:
  - schema_check
  - finite_check
  - provenance
  - optimizer_benchmark_gate
```

Copy the exact frozen validator config from Step 1. Add a spec test that checks
the full commit, arguments, eight workers, expected files, validators and every
gate field.

- [ ] **Step 7: Run full local verification**

Run:

```bash
.venv/bin/pytest -q config/oer-wf/tests
.venv/bin/pytest -q code/python/tests
.venv/bin/python code/python/scripts/audit_repository_layout.py
git diff --check
```

Expected: both suites, repository audit and diff check pass.

- [ ] **Step 8: Commit and push the spec**

```bash
git add config/oer-wf/examples/a6_optimizer_development_cn.yaml \
  config/oer-wf/tests/test_verify.py
git commit -m "feat(a6): freeze optimizer development task"
git push origin codex/reclassify-project
```

## Task 7: Development smoke, formal gate and project record

**Files:**

- Modify after results:
  `documents/project/WORK_STATUS.md`
- Modify after results:
  `documents/project/PROJECT_SUMMARY.md`
- Modify only if a new issue occurs:
  `documents/corrections/项目纠错.md`
- Create:
  `results/formal/identifiability/gate-a6-optimizer-development/acceptance.md`

- [ ] **Step 1: Read and verify the environment**

Read all of `/Users/liushiyu/gpt/本机环境配置.md`, then run:

```bash
ssh -o BatchMode=yes -o ConnectTimeout=10 legion \
  "whoami; systemctl is-system-running || true; loginctl show-user lsy -p Linger"
```

Expected: `lsy`, `running` or known `degraded`, and `Linger=yes`.

- [ ] **Step 2: Deploy without changing NumPy**

Push the project branch, fetch it on Legion, sync `config/oer-wf/` to the
existing `/home/lsy/oer-wf/` editable source, and run both remote targeted test
suites. Do not run `pip install`, change NumPy, or clean the dirty main repo.

- [ ] **Step 3: Prepare and smoke**

Run:

```bash
.venv/bin/wf prepare config/oer-wf/examples/a6_optimizer_development_cn.yaml
.venv/bin/wf smoke config/oer-wf/examples/a6_optimizer_development_cn.yaml \
  --timeout 180
```

Copy the existing Linux `liboercn.so` into the ignored
`code/cpp/build/liboercn.so` path of the frozen worktree before smoke. Smoke
must produce the six scientific files plus `task_spec.snapshot.yaml` and
`STATUS=SUCCESS`. Smoke scientific selection remains `null`.

- [ ] **Step 4: Run formal once**

Only after smoke PASS:

```bash
.venv/bin/wf run config/oer-wf/examples/a6_optimizer_development_cn.yaml
```

Do not create an automation. The task is expected to finish quickly; inspect
status directly, then sync and verify:

```bash
benchmark_task_id=$(.venv/bin/python - <<'PY'
from pathlib import Path
import yaml
from oer_wf.models import TaskSpec
path = Path("config/oer-wf/examples/a6_optimizer_development_cn.yaml")
print(TaskSpec.model_validate(yaml.safe_load(path.read_text())).task_id)
PY
)
.venv/bin/wf status "$benchmark_task_id"
.venv/bin/wf sync "$benchmark_task_id"
.venv/bin/wf verify "$benchmark_task_id"
```

- [ ] **Step 5: Enforce the result branch**

If no replacement is eligible:

- record scientific FAIL;
- stop before the 51-study confirmation phase;
- preserve `selection.json` and hashes;
- do not change algorithms, budget or development cases.

If one replacement is eligible:

- record its exact name, metrics and implementation commit;
- do not yet run confirmation;
- create a separate confirmation implementation plan pinned to this selection.

- [ ] **Step 6: Update evidence and verify**

The acceptance document must record:

- exact commit and spec hash;
- all nine job IDs and 100-call counts;
- per-optimizer worst/median error and objective regret;
- selected optimizer or explicit `none`;
- execution/numerical/scientific status;
- archive path and SHA-256 for every contract file;
- allowed claim and prohibited interpretations.

Run:

```bash
.venv/bin/python code/python/scripts/audit_repository_layout.py
git diff --check
git status --short
```

- [ ] **Step 7: Commit and push the result record**

```bash
git add documents/project/WORK_STATUS.md \
  documents/project/PROJECT_SUMMARY.md \
  results/formal/identifiability/gate-a6-optimizer-development/acceptance.md
git add documents/corrections/项目纠错.md  # only when actually changed
git commit -m "docs(a6): record optimizer development gate"
git push origin codex/reclassify-project
```

## Plan self-review

- Spec coverage: Tasks 1–3 implement all three frozen algorithms; Tasks 4–5
  implement truth isolation, selection, artifacts and resume; Task 6 implements
  independent workflow verification and the frozen task; Task 7 executes and
  records the development gate.
- Scope: The 51-study confirmation run is intentionally excluded until a
  candidate exists. This prevents writing a mutable confirmation task before
  `selection.json` freezes the optimizer.
- Placeholder scan: no `TBD`, `TODO`, “similar to”, or unspecified error
  handling remains. The remaining `...` tokens occur only inside valid Python
  variadic tuple and callable type annotations.
- Type consistency: all algorithm adapters use unit coordinates and return
  `OptimizerResult`; benchmark rows use decoded physical parameters plus
  normalized recovery metrics; truth diagnostics remain outside the optimizer
  call counter.
