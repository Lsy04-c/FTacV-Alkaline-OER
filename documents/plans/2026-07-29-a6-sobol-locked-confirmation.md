# Gate A6 Sobol Locked Confirmation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run the preregistered `sobol_pattern` optimizer once on the 51
non-development Stage 2 studies, combine those results with the three frozen
development studies, and independently apply the unchanged Recovery Gate v2.

**Architecture:** Freeze a compact development-evidence file from the accepted
archive before changing the runner. Extend the truth-agnostic benchmark
protocol with a 51-job confirmation matrix that only names `sobol_pattern`.
Keep execution, checkpointing and scientific verification separate; the
workflow validator reloads the development evidence plus confirmation JSONL and
recomputes all three 18-study pair gates.

**Tech Stack:** Python 3.11/3.13, NumPy, pytest, JSON/JSONL, oer-wf, C++ CN.

---

## Scope and fixed decisions

- Selected optimizer: `sobol_pattern`.
- Optimizer implementation commit:
  `a5b93f55e540682cc8cddb1fabbe63a7e0e92326`.
- Budget: exactly 100 optimization objective calls per study.
- Mode/backend: `hybrid` / CN.
- Confirmation matrix: three parameter pairs × 17 remaining studies = 51.
- Excluded development key for every pair:
  `center/noise-0/seed-7`.
- Truth IDs: `center`, `mixed_a`, `mixed_b`.
- Noise levels: `0.0`, `0.001495726085983469`.
- Optimizer seeds: `7`, `17`, `27`.
- Recovery Gate v2 remains:
  group median error `<=0.025`, group max error `<=0.05`, seed dispersion
  `<=0.05`, boundary hit rate `=0`, all studies successful.
- Synthetic truth remains unavailable to optimizer initialization, enqueue,
  boundary selection and stopping.
- This plan ends after CN confirmation. LSODA confirmation requires a new plan
  and only applies to parameter pairs that pass CN v2.

## File map

| File | Responsibility |
|---|---|
| `results/formal/identifiability/gate-a6-optimizer-development/development_evidence.json` | Three accepted Sobol development rows and source hashes |
| `code/python/src/oer_aem/optimizer_benchmark.py` | Frozen 51-job matrix and combined v2 summaries |
| `code/python/scripts/run_optimizer_benchmark.py` | Confirmation CLI, incremental output and evidence fingerprint |
| `code/python/tests/test_optimizer_benchmark.py` | Matrix, leakage, resume and combined-gate tests |
| `config/oer-wf/oer_wf/validators/optimizer_confirmation_gate.py` | Independent 51+3 evidence verification |
| `config/oer-wf/tests/test_optimizer_confirmation_gate.py` | Structure, numerical and scientific failure classification |
| `config/oer-wf/examples/a6_optimizer_confirmation_cn.yaml` | Frozen Legion task |

## Task 1: Freeze development evidence

**Files:**

- Create:
  `results/formal/identifiability/gate-a6-optimizer-development/development_evidence.json`
- Modify:
  `code/python/tests/test_optimizer_benchmark.py`

- [ ] **Step 1: Add a failing evidence-integrity test**

The test must load the file and assert:

```python
assert evidence["selected_optimizer"] == "sobol_pattern"
assert evidence["source_commit"] == (
    "a5b93f55e540682cc8cddb1fabbe63a7e0e92326"
)
assert evidence["source_results_sha256"] == (
    "e93ccab24c4a91d9d4d9a2b8e014826b6b1a07b7d0891c6e7dd944b78e17b432"
)
assert len(evidence["development_rows"]) == 3
assert {row["optimization_calls"] for row in evidence["development_rows"]} == {100}
assert {
    tuple(row["free_parameters"])
    for row in evidence["development_rows"]
} == {
    ("k0_2", "k0_3"),
    ("k0_2", "G_O"),
    ("k0_3", "G_O"),
}
```

- [ ] **Step 2: Verify RED**

Run:

```bash
.venv/bin/pytest -q code/python/tests/test_optimizer_benchmark.py \
  -k development_evidence
```

Expected: FAIL because the evidence file does not exist.

- [ ] **Step 3: Create evidence from the accepted archive**

Copy only the three `optimizer=="sobol_pattern"` rows. Include source archive,
source file hashes, spec hash and selection hash. Do not hand-edit scientific
values.

- [ ] **Step 4: Verify GREEN and commit**

```bash
.venv/bin/pytest -q code/python/tests/test_optimizer_benchmark.py \
  -k development_evidence
git add results/formal/identifiability/gate-a6-optimizer-development/development_evidence.json \
  code/python/tests/test_optimizer_benchmark.py
git commit -m "data(a6): freeze Sobol development evidence"
```

## Task 2: Build the locked 51-job protocol

**Files:**

- Modify: `code/python/src/oer_aem/optimizer_benchmark.py`
- Modify: `code/python/tests/test_optimizer_benchmark.py`

- [ ] **Step 1: Write failing matrix tests**

Add tests requiring:

```python
jobs = build_confirmation_jobs(
    noise_fraction=0.001495726085983469
)
assert len(jobs) == 51
assert {job["optimizer"] for job in jobs} == {"sobol_pattern"}
assert all(job["budget"] == 100 for job in jobs)
assert not any(
    job["truth_id"] == "center"
    and job["noise_fraction"] == 0.0
    and job["seed"] == 7
    for job in jobs
)
```

Also assert the complete product contains exactly 17 identities per pair and
that different measured-noise evidence changes the run fingerprint rather than
the frozen selected noise.

- [ ] **Step 2: Verify RED**

```bash
.venv/bin/pytest -q code/python/tests/test_optimizer_benchmark.py \
  -k confirmation
```

Expected: FAIL because `build_confirmation_jobs` is absent.

- [ ] **Step 3: Implement the matrix**

Add constants:

```python
CONFIRMATION_OPTIMIZER = "sobol_pattern"
CONFIRMATION_TRUTHS = ("center", "mixed_a", "mixed_b")
CONFIRMATION_NOISES = (0.0, 0.001495726085983469)
CONFIRMATION_SEEDS = (7, 17, 27)
DEVELOPMENT_IDENTITY = ("center", 0.0, 7)
```

Build the full product per parameter pair and exclude exactly
`DEVELOPMENT_IDENTITY`. Reuse the current truth library and deterministic
target-seed function. Do not accept an optimizer argument.

- [ ] **Step 4: Add combined v2 summary tests**

Create synthetic 3-row development plus 51-row confirmation evidence. Test
each threshold independently at `0.05` versus `0.050001`, `0.025` versus
`0.025001`, and dispersion `0.05` versus `0.050001`. Each parameter pair must
receive an independent PASS/FAIL result.

- [ ] **Step 5: Verify and commit**

```bash
.venv/bin/pytest -q code/python/tests/test_optimizer_benchmark.py
git add code/python/src/oer_aem/optimizer_benchmark.py \
  code/python/tests/test_optimizer_benchmark.py
git commit -m "feat(a6): add locked Sobol confirmation protocol"
```

## Task 3: Extend the resumable runner

**Files:**

- Modify: `code/python/scripts/run_optimizer_benchmark.py`
- Modify: `code/python/tests/test_optimizer_benchmark.py`

- [ ] **Step 1: Write failing runner tests**

Tests must require:

- `--phase confirmation`;
- `--development-evidence PATH`;
- 51 result rows and 5100 evaluation rows;
- only `sobol_pattern`;
- evidence SHA-256 in `benchmark_plan.json` and every resume fingerprint;
- smoke runs one preregistered job from each parameter pair, still at 100 calls;
- modified evidence, optimizer, budget, backend or commit rejects resume;
- confirmation never rewrites the development evidence.

- [ ] **Step 2: Verify RED**

```bash
.venv/bin/pytest -q code/python/tests/test_optimizer_benchmark.py \
  -k confirmation_runner
```

- [ ] **Step 3: Implement confirmation dispatch**

`main` must choose `build_confirmation_jobs` only for
`--phase confirmation`. Load and validate the development evidence before
creating output. Add its resolved path and SHA-256 to the run contract. Formal
confirmation must require CN and budget 100.

Smoke must use an explicit three-job list containing one frozen job per
parameter pair; it must not use `jobs[:3]` if those jobs belong to one pair.
Smoke writes `scientific_gate_passed=null`.

- [ ] **Step 4: Write combined confirmation output**

Formal completion writes:

- `benchmark_plan.json`;
- `results.jsonl` with 51 rows;
- `evaluations.jsonl` with 5100 rows;
- `summary.json`;
- `confirmation_gate.json` with three pair decisions;
- `STATUS.json` from the workflow wrapper.

The runner may calculate `confirmation_gate.json`, but the workflow validator
must recompute it independently.

- [ ] **Step 5: Verify and commit**

```bash
.venv/bin/pytest -q code/python/tests/test_optimizer_benchmark.py
.venv/bin/pytest -q code/python/tests
git add code/python/scripts/run_optimizer_benchmark.py \
  code/python/tests/test_optimizer_benchmark.py
git commit -m "feat(a6): run resumable Sobol confirmation"
```

## Task 4: Add independent confirmation verification

**Files:**

- Create:
  `config/oer-wf/oer_wf/validators/optimizer_confirmation_gate.py`
- Modify: `config/oer-wf/oer_wf/validators/__init__.py`
- Modify: `config/oer-wf/oer_wf/commands/verify.py`
- Create:
  `config/oer-wf/tests/test_optimizer_confirmation_gate.py`

- [ ] **Step 1: Write failing validator tests**

Cover:

1. exact 51 confirmation jobs and three frozen development rows PASS;
2. missing/duplicate development identity is structure FAIL;
3. 99/101 calls or 5099/5101 traces is structure FAIL;
4. evidence SHA mismatch is transport/structure FAIL;
5. NaN is numerical FAIL;
6. all three pair gates fail is scientific FAIL;
7. one pair passes and two fail is a valid scientific result, with only that
   pair eligible for LSODA.

- [ ] **Step 2: Verify RED**

```bash
.venv/bin/pytest -q \
  config/oer-wf/tests/test_optimizer_confirmation_gate.py
```

- [ ] **Step 3: Implement and register**

The validator must independently load all artifacts, reconstruct the 54-study
combined matrix, group by pair/truth/noise, apply the unchanged v2 thresholds,
and compare its result with `confirmation_gate.json`. It must not import or
call the runner's gate function.

- [ ] **Step 4: Verify and commit**

```bash
.venv/bin/pytest -q \
  config/oer-wf/tests/test_optimizer_confirmation_gate.py \
  config/oer-wf/tests/test_verify.py
git add config/oer-wf/oer_wf/validators/optimizer_confirmation_gate.py \
  config/oer-wf/oer_wf/validators/__init__.py \
  config/oer-wf/oer_wf/commands/verify.py \
  config/oer-wf/tests/test_optimizer_confirmation_gate.py
git commit -m "feat(workflow): verify Sobol confirmation gate"
```

## Task 5: Freeze, deploy and run once

**Files:**

- Create after implementation commit:
  `config/oer-wf/examples/a6_optimizer_confirmation_cn.yaml`
- Modify after results: `documents/project/WORK_STATUS.md`
- Modify after results: `documents/project/PROJECT_SUMMARY.md`
- Create after results:
  `results/formal/identifiability/gate-a6-sobol-confirmation/acceptance.md`

- [ ] **Step 1: Freeze the spec**

Pin the full implementation commit, eight workers, CN, budget 100, the measured
noise evidence and tracked development-evidence path. Expected files must
include `benchmark_plan.json`, both JSONL files, `summary.json`,
`confirmation_gate.json` and `STATUS.json`.

- [ ] **Step 2: Run full local verification**

```bash
.venv/bin/pytest -q config/oer-wf/tests
.venv/bin/pytest -q code/python/tests
.venv/bin/python code/python/scripts/audit_repository_layout.py
git diff --check
```

- [ ] **Step 3: Push and deploy without dependency changes**

Read `/Users/liushiyu/gpt/本机环境配置.md`, push the project branch, fetch on
Legion, sync existing oer-wf source, create a commit worktree and copy the
existing Linux CN library using full absolute paths. Do not run `pip install`
or change NumPy.

- [ ] **Step 4: Smoke then formal**

Run `wf prepare` and the three-pair 300-call smoke. Verify selection is null,
all three pairs are represented, calls equal 300 and ODE failures equal zero.
Only then run formal once. Do not create an automation.

- [ ] **Step 5: Enforce the branch**

- If all three pairs FAIL v2: stop Gate A6 multi-parameter recovery.
- If one or more pairs PASS: freeze only those pairs and write a separate
  LSODA confirmation plan; do not run LSODA in this task.
- Never change the algorithm, 100-call budget, dataset split or v2 thresholds
  after seeing confirmation results.

- [ ] **Step 6: Record and push evidence**

Record commit, spec hash, 51 job IDs, per-pair v2 metrics, archive hashes,
allowed claim and prohibited interpretations. Commit only project-related
summary evidence and documents; do not commit raw 5100-row trace files.

## Plan self-review

- Spec coverage: the selected optimizer, exact budget, 51-study exclusion,
  development evidence, v2 recombination, resume protection, independent
  validation and CN→LSODA boundary are each assigned to an explicit task.
- Leakage pressure test: truth metadata remains in target construction and
  post-run diagnostics only; optimizer input remains unit coordinates,
  dimension, budget and seed.
- Confirmation contamination pressure test: the three viewed development
  studies are frozen by hashes and excluded from the 51-job run; confirmation
  results cannot modify their evidence.
- Failure exit: infrastructure, numerical and scientific failures stop
  dependent stages without threshold or algorithm adjustment.
- Placeholder scan: no unresolved implementation placeholder remains.
